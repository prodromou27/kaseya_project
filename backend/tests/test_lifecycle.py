"""VSA4-05 lifecycle catalog: matching, classification, two-person review, immutability, customer view.

Dates and URLs below are test values, not vendor facts.
"""

from __future__ import annotations

import datetime as dt

import pytest
from django.db import connection, transaction
from django.db.utils import DatabaseError
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.software.lifecycle import classify, os_candidates, prefix_matches, version_parts
from apps.software.models import LifecycleEntry, SoftwareProduct

from .factories import UserFactory
from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db
TODAY = dt.date(2026, 11, 13)
URL = "https://lifecycle-evidence.example.test/page"


def entry(**kw) -> LifecycleEntry:
    base = {
        "kind": "os",
        "os_family": "Windows 11",
        "release_label": "23H2",
        "version_prefix": "",
        "end_of_support": dt.date(2027, 11, 10),
        "source_url": URL,
        "source_type": "vendor_lifecycle_page",
        "source_checked_at": TODAY,
        "confidence": "official",
        "state": "approved",
    }
    base.update(kw)
    return LifecycleEntry(**base)


# ---------------------------------------------------------------------------------------------- pure logic


def test_version_parts_keep_every_component():
    assert version_parts("10.0.22631.0") == (10, 0, 22631, 0)
    assert version_parts("v115.3esr") == (115, 3)
    assert version_parts("build 7") is None and version_parts("") is None


@pytest.mark.parametrize(
    ("version", "prefix", "ok"),
    [
        ("10.0.22631.0", "10.0.22631", True),
        ("10.0.22631.0", "10.0", True),
        ("10.0.22631.0", "10.0.2", False),  # component-wise, not string prefix
        ("10.0.19045.1", "10.0.22631", False),
        ("anything", "", True),
    ],
)
def test_prefix_matching(version, prefix, ok):
    assert prefix_matches(version_parts(version), prefix) is ok


def test_classification_states_and_reasons():
    v = version_parts("10.0.22631.0")
    assert classify([], v, True, TODAY).reason == "no_entry"
    assert classify([entry(confidence="secondary")], v, True, TODAY).reason == "unverified_only"
    assert classify([entry(end_of_support=dt.date(2026, 1, 1))], v, True, TODAY).status == "end_of_support"
    assert classify([entry(end_of_support=dt.date(2027, 3, 1))], v, True, TODAY).status == "ending_soon"
    assert classify([entry()], v, True, TODAY).status == "supported"
    # Most specific prefix wins over the family-wide entry.
    family = entry(version_prefix="", end_of_support=dt.date(2030, 1, 1))
    build = entry(version_prefix="10.0.22631", end_of_support=dt.date(2026, 1, 1))
    verdict = classify([family, build], v, True, TODAY)
    assert verdict.status == "end_of_support" and verdict.entry is build
    # Two equally specific official entries with different dates: refuse to choose.
    clash = classify([build, entry(version_prefix="10.0.22631", end_of_support=dt.date(2028, 1, 1))], v, True, TODAY)
    assert (clash.status, clash.reason) == ("unknown", "conflicting_entries")
    # A build-specific entry cannot match a device whose version is unparsable.
    assert classify([build], None, False, TODAY).reason == "version_not_parsable"


def test_os_family_most_specific_name_wins():
    generic = entry(os_family="Windows Server", release_label="any")
    specific = entry(os_family="Windows Server 2016", release_label="2016")
    assert os_candidates([generic, specific], "Microsoft Windows Server 2016 Standard") == [specific]
    assert os_candidates([generic, specific], "Windows 11 Enterprise") == []


# ---------------------------------------------------------------------------------------------- catalog API

URL_LIST = "/api/v1/catalog/lifecycle/"


def payload(**kw):
    data = {
        "kind": "os",
        "os_family": "Windows 11",
        "release_label": "23H2",
        "version_prefix": "10.0.22631",
        "end_of_support": "2027-11-10",
        "source_url": URL,
        "source_type": "vendor_lifecycle_page",
        "source_checked_at": "2026-11-01",
        "confidence": "official",
    }
    data.update(kw)
    return data


def test_two_person_review_and_audit(world):
    reviewer = UserFactory(email="reviewer@example.test", global_role=world.super_admin.global_role)
    resp = world.client(world.super_admin).post(URL_LIST, payload(), format="json")
    assert resp.status_code == 201, resp.content
    eid = resp.json()["id"]
    assert resp.json()["state"] == "proposed"
    same = world.client(world.super_admin).post(f"{URL_LIST}{eid}/approve/", {}, format="json")
    assert same.status_code == 400 and "different reviewer" in same.content.decode()
    ok = world.client(reviewer).post(f"{URL_LIST}{eid}/approve/", {}, format="json")
    assert ok.status_code == 200 and ok.json()["state"] == "approved" and ok.json()["reviewed_by"] == reviewer.email
    assert {e.action for e in AuditEvent.objects.filter(target_id=eid)} == {"lifecycle.proposed", "lifecycle.approved"}
    retired = world.client(world.super_admin).post(f"{URL_LIST}{eid}/retire/", {}, format="json")
    assert retired.json()["state"] == "retired"


@pytest.mark.parametrize("who", ["admin_a", "engineer_a", "viewer_a"])
def test_only_super_admins_manage_the_catalog(world, who):
    client = world.client(getattr(world, who))
    assert client.get(URL_LIST).status_code == 403
    assert client.post(URL_LIST, payload(), format="json").status_code == 403


@pytest.mark.parametrize(
    "bad",
    [
        {"source_url": "http://insecure.example.test/x"},
        {"source_checked_at": "2999-01-01"},
        {"end_of_mainstream": "2028-01-01"},  # after end of support
        {"extended_until": "2026-01-01"},  # before end of support
        {"os_family": ""},
        {"version_prefix": "10.x"},
        {"kind": "software"},  # no product
        {"source_type": "blog_post"},
    ],
)
def test_validation(world, bad):
    resp = world.client(world.super_admin).post(URL_LIST, payload(**bad), format="json")
    assert resp.status_code == 400, (bad, resp.content)


def test_bulk_is_all_or_nothing(world):
    client = world.client(world.super_admin)
    resp = client.post(f"{URL_LIST}bulk/", {"rows": [payload(), payload(source_url="http://x")]}, format="json")
    assert resp.status_code == 400 and not LifecycleEntry.objects.exists()
    resp = client.post(f"{URL_LIST}bulk/", {"rows": [payload(), payload(release_label="22H2")]}, format="json")
    assert resp.status_code == 201 and LifecycleEntry.objects.count() == 2


def test_approved_entries_are_immutable_in_the_database(world):
    e = entry(created_by=world.super_admin, reviewed_by=world.super_admin)
    e.save()
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("UPDATE software_lifecycleentry SET end_of_support = '2099-01-01' WHERE id = %s", [e.id])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("DELETE FROM software_lifecycleentry WHERE id = %s", [e.id])
    with connection.cursor() as cur:  # retirement is the only allowed change
        cur.execute("UPDATE software_lifecycleentry SET state = 'retired' WHERE id = %s", [e.id])
    with pytest.raises(DatabaseError), transaction.atomic(), connection.cursor() as cur:
        cur.execute("UPDATE software_lifecycleentry SET state = 'approved' WHERE id = %s", [e.id])


# ---------------------------------------------------------------------------------------------- customer view


def _os_asset(i: int, os_name: str, version: str) -> dict:
    a = asset(i, 11)
    a["AssetInfo"] = [{"CategoryName": "Operating System", "CategoryData": {"Name": os_name, "Version": version}}]
    return a


def test_customer_view_classifies_and_never_guesses(world, env, monkeypatch):  # noqa: F811
    run(
        env["ma"],
        world.engineer_a,
        FixtureVsaTransport(
            [
                _os_asset(1, "Windows 10 Pro", "10.0.19045.1"),
                _os_asset(2, "Windows 11 Enterprise", "10.0.22631.0"),
                _os_asset(3, "Windows 11 Enterprise", "10.0.26100.1"),  # build without any entry
                _os_asset(4, "Ubuntu 24.04", "24.04"),
            ]
        ),
    )
    reviewer = world.super_admin
    for kw in (
        {
            "os_family": "Windows 10",
            "release_label": "22H2",
            "version_prefix": "10.0.19045",
            "end_of_support": dt.date(2025, 10, 14),
        },
        {
            "os_family": "Windows 11",
            "release_label": "23H2",
            "version_prefix": "10.0.22631",
            "end_of_support": dt.date(2027, 3, 1),
        },
        {"os_family": "Ubuntu", "release_label": "24.04", "version_prefix": "24.04", "confidence": "secondary"},
        {"os_family": "Windows 11", "release_label": "draft", "version_prefix": "10.0.26100", "state": "proposed"},
    ):
        entry(created_by=reviewer, reviewed_by=reviewer, **kw).save()
    client = world.client(world.engineer_a)
    body = client.get(f"/api/v1/customers/{world.customer_a.id}/lifecycle/", {"on": "2026-11-13"}).json()
    assert body["os"]["totals"] == {"end_of_support": 1, "ending_soon": 1, "supported": 0, "unknown": 2}
    eos = next(g for g in body["os"]["groups"] if g["status"] == "end_of_support")
    assert eos["entry"]["source_url"] == URL and eos["entry"]["end_of_support"] == "2025-10-14" and eos["count"] == 1
    reasons = {g["reason"] for g in body["os"]["groups"] if g["status"] == "unknown"}
    assert reasons == {"no_entry", "unverified_only"}  # proposed entries are ignored; secondary is not trusted
    devices = client.get(
        f"/api/v1/customers/{world.customer_a.id}/lifecycle/devices/", {"on": "2026-11-13", "status": "end_of_support"}
    ).json()
    assert [r["os_name"] for r in devices["results"]] == ["Windows 10 Pro"]
    # Another customer's member cannot read it.
    assert world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_a.id}/lifecycle/").status_code == 404


def test_software_lifecycle_uses_reviewed_product_only(world, env):  # noqa: F811
    from apps.software.models import SoftwareAlias

    product = SoftwareProduct.objects.create(vendor="Example", product="Browser")
    SoftwareAlias.objects.create(
        product=product,
        name_pattern="Example Browser",
        review_status="approved",
        created_by=world.super_admin,
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    a1 = asset(1, 11)
    a1["InstalledSoftware"] = [
        {"Name": "Example Browser", "Publisher": "Example", "Version": "115.4.0"},
        {"Name": "Unreviewed Tool", "Publisher": "Nobody", "Version": "1.0"},
    ]
    run(env["ma"], world.engineer_a, FixtureVsaTransport([a1]))
    entry(
        kind="software",
        os_family="",
        product=product,
        release_label="ESR 115",
        version_prefix="115",
        end_of_support=dt.date(2026, 6, 1),
        created_by=world.super_admin,
        reviewed_by=world.super_admin,
    ).save()
    body = (
        world.client(world.engineer_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/lifecycle/", {"on": "2026-11-13"})
        .json()
    )
    assert body["software"]["totals"]["end_of_support"] == 1 and body["software"]["devices_with_end_of_support"] == 1
    unknown = [g for g in body["software"]["groups"] if g["status"] == "unknown"]
    assert unknown and unknown[0]["reason"] == "product_not_catalogued"


def test_r17_report_is_pinned_and_regenerates_identically(world, env, django_capture_on_commit_callbacks):  # noqa: F811
    from .test_p2_reporting import csv_rows

    run(env["ma"], world.engineer_a, FixtureVsaTransport([_os_asset(1, "Windows 10 Pro", "10.0.19045.1")]))
    e = entry(
        os_family="Windows 10",
        release_label="22H2",
        version_prefix="10.0.19045",
        end_of_support=dt.date(2025, 10, 14),
        created_by=world.super_admin,
        reviewed_by=world.super_admin,
    )
    e.save()
    client = world.client(world.engineer_a)
    base = f"/api/v1/customers/{world.customer_a.id}/reports/"
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(
            base, {"report_type": "lifecycle", "format": "csv", "filters": {"kind": "os"}}, format="json"
        )
    assert resp.status_code == 202, resp.content
    first = resp.json()["id"]
    provenance, rows = csv_rows(b"".join(client.get(f"/api/v1/reports/{first}/download/").streaming_content))
    assert any("1 approved lifecycle entry" in p for p in provenance)
    assert [(r[0], r[4], r[7], r[9]) for r in rows] == [("os", "end_of_support", "2025-10-14", URL)]
    # Retire the entry: the original report still regenerates from the pinned entry and date.
    LifecycleEntry.objects.filter(pk=e.pk).update(state="retired")
    with django_capture_on_commit_callbacks(execute=True):
        again = client.post(f"/api/v1/reports/{first}/regenerate/", {}, format="json")
    assert again.status_code == 202, again.content
    _, rows2 = csv_rows(b"".join(client.get(f"/api/v1/reports/{again.json()['id']}/download/").streaming_content))
    assert rows2 == rows
    # A new report now has no approved entry: unknown, never guessed.
    with django_capture_on_commit_callbacks(execute=True):
        fresh = client.post(base, {"report_type": "lifecycle", "format": "csv", "filters": {}}, format="json")
    _, rows3 = csv_rows(b"".join(client.get(f"/api/v1/reports/{fresh.json()['id']}/download/").streaming_content))
    assert {r[4] for r in rows3 if r[0] == "os"} == {"unknown"}
