"""CAT-02: daily read of the VSA application catalog page; safe version increases apply, the rest waits for review."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.software.models import CatalogImport, CatalogRevision, SoftwareAlias, VsaCatalogCheck
from apps.software.vsa_catalog import CATALOG_URL
from apps.software.vsa_catalog_sync import SYSTEM_EMAIL, page_to_text, run

from .test_p1_api import reviewer, synced  # noqa: F401

pytestmark = pytest.mark.django_db
STATUS = "/api/v1/catalog/imports/vsa-catalog-status/"
PUBLIC = lambda host: ["93.184.216.34"]  # noqa: E731 - a public address


def page(*rows: tuple[str, str, str, str]) -> str:
    body = "".join(
        f"<tr><td>{a}</td><td>{v}</td><td>{t}</td><td>{ver}</td><td>2026-11-01</td></tr>" for a, v, t, ver in rows
    )
    return (
        "<html><body><p><i>Last updated:&#160;November 11, 2026</i></p><table><thead><tr><th>Application</th>"
        "<th>Vendor</th><th>Tier</th><th>Version</th><th>Release Date</th></tr></thead>"
        f"<tbody>{body}</tbody></table></body></html>"
    )


class Response:
    def __init__(self, html: str, status: int = 200):
        self.status_code, self.content, self.encoding = status, html.encode(), "utf-8"


class Transport:
    def __init__(self, html: str, status: int = 200):
        self.html, self.status, self.urls = html, status, []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return Response(self.html, self.status)


CHROME = ("Google Chrome (64-bit)", "Google LLC", "1")


def check(html, status=200, **kw):
    transport = Transport(html, status)
    result = run(transport=transport, resolver=PUBLIC, **kw)
    assert transport.urls in ([CATALOG_URL], [])
    return result


def test_reads_the_table_and_last_updated_date():
    text, updated = page_to_text(page(("7-zip (64-bit)", "Igor Pavlov", "2", "26.06")))
    assert updated == "November 11, 2026"
    assert text.splitlines()[1] == "7-zip (64-bit)\tIgor Pavlov\t2\t26.06\t2026-11-01"


def test_new_products_wait_then_higher_versions_apply_automatically(
    world,
    synced,  # noqa: F811
    django_capture_on_commit_callbacks,
):
    first = check(page((*CHROME, "131.0.6778.86")))
    assert (first.outcome, first.applied) == ("updated", 0)
    pending = first.pending_import
    assert pending.state == "pending" and pending.created_by.email == SYSTEM_EMAIL
    assert CatalogRevision.objects.count() == 0  # a new product is never applied without approval

    # Approved once by a person (the automatic account is not a reviewer, so any administrator may approve).
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.super_admin).post(f"/api/v1/catalog/imports/{pending.id}/approve/")
    assert resp.status_code == 200, resp.content

    # Same page again: nothing to do.
    assert check(page((*CHROME, "131.0.6778.86"))).outcome == "no_change"

    # Kaseya publishes a higher version: applied without anyone, audited, devices re-evaluated.
    with django_capture_on_commit_callbacks(execute=True):
        later = check(page((*CHROME, "132.0.6834.83")))
    assert (later.outcome, later.applied, later.pending_import) == ("updated", 1, None)
    rev = CatalogRevision.objects.filter(state="published").order_by("-effective_at").first()
    assert rev.reference_version == "132.0.6834.83" and rev.reviewed_by.email == SYSTEM_EMAIL
    assert later.applied_import.state == "approved"
    summary = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    assert next(p for p in summary["products"] if "Chrome" in p["label"])["states"]["outdated"] == 6
    event = AuditEvent.objects.filter(action="catalog.vsa_auto_update", outcome="success").latest("created_at")
    assert event.metadata["applied"] == ["Google Chrome 132.0.6834.83"]


def test_decreases_and_format_warnings_wait_for_review(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    first = check(page((*CHROME, "131.0.6778.86")))
    with django_capture_on_commit_callbacks(execute=True):
        world.client(world.super_admin).post(f"/api/v1/catalog/imports/{first.pending_import.id}/approve/")
    lower = check(page((*CHROME, "120.0")))
    assert lower.applied == 0 and lower.pending_import.state == "pending"
    assert lower.pending_import.preview[0]["change"] == "version_down"

    # A newer check with different content supersedes the previous automatic pending import; identical ones are kept.
    again = check(page((*CHROME, "125.0")))
    lower.pending_import.refresh_from_db()
    assert lower.pending_import.state == "rejected" and "Superseded" in lower.pending_import.review_note
    assert check(page((*CHROME, "125.0"))).pending_import_id == again.pending_import_id
    assert CatalogImport.objects.filter(state="pending").count() == 1


def test_new_installed_names_are_only_proposed(world, synced, django_capture_on_commit_callbacks):  # noqa: F811
    first = check(page((*CHROME, "131.0.6778.86")))
    with django_capture_on_commit_callbacks(execute=True):
        world.client(world.super_admin).post(f"/api/v1/catalog/imports/{first.pending_import.id}/approve/")
    alias = SoftwareAlias.objects.get(name_pattern="Google Chrome")
    alias.delete()  # as if this installed name appeared only after the first approval
    check(page((*CHROME, "132.0")))
    assert SoftwareAlias.objects.get(name_pattern="Google Chrome").review_status == "proposed"


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"status": 503}, "http_503"),
        ({"html": "<html>No table here</html>"}, "page_format_changed"),
    ],
)
def test_failures_are_recorded_not_raised(world, synced, kwargs, code):  # noqa: F811
    html = kwargs.get("html", page((*CHROME, "131.0")))
    result = check(html, kwargs.get("status", 200))
    assert (result.outcome, result.error_code) == ("failed", code)
    assert AuditEvent.objects.filter(action="catalog.vsa_auto_update", outcome="failure").exists()


def test_private_destination_is_refused(world, synced):  # noqa: F811
    result = run(transport=Transport(page()), resolver=lambda host: ["10.0.0.5"])
    assert (result.outcome, result.error_code) == ("failed", "egress_blocked")


def test_switched_off_schedule_does_nothing(world, synced, settings):  # noqa: F811
    settings.VSA_APP_CATALOG_AUTO_UPDATE = False
    transport = Transport(page((*CHROME, "131.0")))
    assert run(transport=transport, resolver=PUBLIC).outcome == "disabled" and transport.urls == []


def test_status_and_check_now_are_system_admin_only(world, synced, monkeypatch):  # noqa: F811
    import apps.software.vsa_catalog_sync as sync

    monkeypatch.setattr(sync, "fetch", lambda transport=None, resolver=None: page((*CHROME, "131.0.6778.86")))
    assert world.client(world.admin_a).get(STATUS).status_code == 403
    body = world.client(world.super_admin).post(STATUS).json()
    latest = body["checks"][0]
    assert body["enabled"] is True and latest["trigger"] == "manual" and latest["outcome"] == "updated"
    assert latest["catalog_last_updated"] == "November 11, 2026" and latest["pending_import"]
    assert VsaCatalogCheck.objects.get(pk=latest["id"]).triggered_by == world.super_admin
