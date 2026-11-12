"""P2-03/04/05/06 reporting: templates, formats, saved views, definitions, schedules, reproducibility."""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime, time, timedelta

import pytest
from django.utils import timezone
from openpyxl import load_workbook
from pypdf import PdfReader

from apps.audit.models import AuditEvent
from apps.customers.models import CustomerMembership, CustomerSourceMapping
from apps.integrations import sync
from apps.integrations.models import IntegrationInstance, SyncRun, SyncSchedule
from apps.integrations.vsa.adapter import VsaXAdapter
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import Asset
from apps.reporting import renderers
from apps.reporting.models import ReportDefinition, ReportRun, ReportSchedule, ScheduledExecution
from apps.reporting.scheduling import (
    compute_next_run,
    dispatch_due_report_schedules,
    dispatch_due_sync_schedules,
    execute_slot,
)

pytestmark = pytest.mark.django_db

HOSTILE = '=cmd|"/C calc"!A0 <font color="red">x</font>'


def devices(org: int, prefix: str, n: int, *, hostile: bool = False) -> list[dict]:
    out = []
    for i in range(n):
        out.append(
            {
                "Identifier": f"{prefix}-{i:03d}",
                "Name": HOSTILE if (hostile and i == 0) else f"{prefix.upper()}{i}",
                "OrganizationId": org,
                "Type": "windows",
                "GroupName": "G - HQ - WS",
                "LastSeenOnline": (timezone.now() - timedelta(days=30 if i % 2 else 0)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "InstalledSoftware": [{"Name": "Google Chrome", "Publisher": "Google LLC", "Version": "1.0"}],
                "Updates": {"Critical": 1, "Important": 0, "Unspecified": 0},
                "AvailableUpdates": [
                    {
                        "UpdateId": "u1",
                        "RevisionNumber": 1,
                        "KbArticle": "5099001",
                        "Severity": "Critical",
                        "Title": "Fixture update",
                        "ReleaseDate": "2026-10-14",
                    }
                ],
            }
        )
    return out


def do_sync(mapping, user, data):
    run, _ = sync.request_sync(mapping, requested_by=user)
    t = FixtureVsaTransport(data)
    return sync.execute(str(run.id), adapter_factory=lambda i: VsaXAdapter(i, transport=t, sleeper=lambda s: 0))


@pytest.fixture
def env(world):
    inst = IntegrationInstance.objects.create(
        name="VSA", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True, enabled=True, max_rps=20
    )
    now = timezone.now()
    ma = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=now,
    )
    mb = CustomerSourceMapping.objects.create(
        customer=world.customer_b,
        integration_instance=inst,
        external_org_id="22",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=now,
    )
    assert do_sync(ma, world.engineer_a, devices(11, "a", 4, hostile=True)).state == "completed"
    assert do_sync(mb, world.engineer_b, devices(22, "b", 3)).state == "completed"
    return {"inst": inst, "ma": ma, "mb": mb}


def request(world, user, customer, capture, report_type, fmt="csv", filters=None, expect=202):
    with capture(execute=True):
        resp = world.client(user).post(
            f"/api/v1/customers/{customer.id}/reports/",
            {"report_type": report_type, "format": fmt, "filters": filters or {}},
        )
    assert resp.status_code == expect, resp.content
    return resp.json()


def download(world, user, run_id) -> bytes:
    resp = world.client(user).get(f"/api/v1/reports/{run_id}/download/")
    assert resp.status_code == 200, resp.status_code
    return b"".join(resp.streaming_content)


def csv_rows(raw: bytes) -> tuple[list[str], list[list[str]]]:
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"))))
    header = next(i for i, r in enumerate(rows) if r and not r[0].startswith("# "))
    return [r[0] for r in rows[:header]], rows[header + 1 :]


# ---------------------------------------------------------------- templates (P2-03)


def test_templates_endpoint_lists_code_defined_reports(world):
    data = world.client(world.viewer_a).get("/api/v1/report-templates/").json()
    keys = {t["key"] for t in data}
    assert {"asset_inventory", "software_compliance", "os_updates", "software_distribution", "stale_devices"} <= keys
    os_t = next(t for t in data if t["key"] == "os_updates")
    assert os_t["formats"] == ["csv", "xlsx", "pdf"] and "kb" in os_t["filters"]


# ---------------------------------------------------------------- XLSX / PDF (P2-04, REP-01/02, SEC-02)


def test_xlsx_is_valid_string_typed_and_matches_row_count(world, env, django_capture_on_commit_callbacks):
    run = request(
        world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory", "xlsx"
    )
    raw = download(world, world.engineer_a, run["id"])
    wb = load_workbook(io.BytesIO(raw))
    assert wb.sheetnames == ["Data", "Provenance"]
    data = list(wb["Data"].iter_rows(values_only=False))
    assert [c.value for c in data[0]][:2] == ["device_id", "hostname"]
    body = data[1:]
    assert len(body) == ReportRun.objects.get(pk=run["id"]).row_count == 4
    assert all(c.data_type != "f" for row in body for c in row)  # never formulas
    assert all(c.data_type == "s" for row in body for c in row if c.value not in (None, ""))
    assert any(c.value == "'" + HOSTILE for row in body for c in row)
    prov = {r[0].value: r[1].value for r in list(wb["Provenance"].iter_rows())[1:]}
    assert prov["Data basis"] == "fixture" and prov["Records included"] == "4"
    resp = world.client(world.engineer_a).get(f"/api/v1/reports/{run['id']}/download/")
    assert resp["Content-Type"].startswith("application/vnd.openxmlformats")


def test_pdf_is_valid_escapes_markup_and_states_provenance(world, env, django_capture_on_commit_callbacks):
    run = request(
        world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory", "pdf"
    )
    raw = download(world, world.engineer_a, run["id"])
    assert raw.startswith(b"%PDF")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(raw)).pages)
    assert "Asset inventory (RPT-01)" in text and "Records included" in text and "fixture" in text
    flat = "".join(text.split())
    assert '<fontcolor="red">x</font>' in flat  # rendered literally, not interpreted as markup
    assert "B0" not in text and "B1" not in text  # other customer's hostnames absent


def test_pdf_row_limit_fails_safely(world, env, monkeypatch, django_capture_on_commit_callbacks):
    monkeypatch.setattr(renderers, "PDF_MAX_ROWS", 2)
    run = request(
        world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory", "pdf"
    )
    r = ReportRun.objects.get(pk=run["id"])
    assert r.state == "failed" and r.error_code == "too_many_rows_for_pdf"


@pytest.mark.parametrize("fmt", ["csv", "xlsx", "pdf"])
def test_all_formats_same_record_count(world, env, fmt, django_capture_on_commit_callbacks):
    run = request(world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "os_updates", fmt)
    assert ReportRun.objects.get(pk=run["id"]).row_count == 4  # one available update on each of A's 4 devices


# ---------------------------------------------------------------- new report types


def test_os_updates_report_scoped_with_status_provenance(world, env, django_capture_on_commit_callbacks):
    run = request(world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "os_updates")
    prov, rows = csv_rows(download(world, world.engineer_a, run["id"]))
    assert any(p.startswith("# Devices by AvailableUpdates status: collected=4") for p in prov)
    assert any("NOT counted as having zero missing updates" in p for p in prov)
    assert len(rows) == 4 and all(r[0].startswith("a-") and r[3] == "KB5099001" for r in rows)


def test_cross_tenant_and_invalid_filters_denied(world, env, django_capture_on_commit_callbacks):
    b_asset = Asset.objects.filter(customer=world.customer_b).first()
    for rt in ("os_updates", "software_compliance"):
        resp = request(
            world,
            world.engineer_a,
            world.customer_a,
            django_capture_on_commit_callbacks,
            rt,
            filters={"asset": str(b_asset.id)},
            expect=400,
        )
        assert "Asset not found for this customer" in str(resp)
    request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "os_updates",
        filters={"kb": "5099001; DROP"},
        expect=400,
    )
    request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "asset_inventory",
        filters={"customer": str(world.customer_b.id)},
        expect=400,
    )
    request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "asset_inventory",
        "docx",
        expect=400,
    )


def test_stale_and_distribution_reports(world, env, django_capture_on_commit_callbacks):
    run = request(
        world,
        world.engineer_a,
        world.customer_a,
        django_capture_on_commit_callbacks,
        "stale_devices",
        filters={"stale_days": 7},
    )
    _, rows = csv_rows(download(world, world.engineer_a, run["id"]))
    assert len(rows) == 2 and {r[6] for r in rows} == {"stale"}
    run = request(
        world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "software_distribution"
    )
    assert ReportRun.objects.get(pk=run["id"]).state == "completed"


# ---------------------------------------------------------------- reproducibility (P2-06, SOFT-05)


def test_regenerated_report_reproduces_original_snapshot(world, env, django_capture_on_commit_callbacks):
    original = request(world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory")
    _, rows_before = csv_rows(download(world, world.engineer_a, original["id"]))
    assert do_sync(env["ma"], world.engineer_a, devices(11, "a", 5)).state == "completed"  # new generation published
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(f"/api/v1/reports/{original['id']}/regenerate/")
    assert resp.status_code == 202
    regen = ReportRun.objects.get(pk=resp.json()["id"])
    assert regen.regenerated_from_id == ReportRun.objects.get(pk=original["id"]).id
    prov, rows_after = csv_rows(download(world, world.engineer_a, regen.id))
    assert rows_after == rows_before and len(rows_after) == 4
    assert any(p.startswith("# Regenerated from run:") for p in prov)
    fresh = request(world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory")
    assert ReportRun.objects.get(pk=fresh["id"]).row_count == 5


def test_forged_pins_cannot_cross_tenants(world, env, django_capture_on_commit_callbacks):
    b_gen = str(env["mb"].generations.get(is_current=True).id)
    run = ReportRun.objects.create(
        customer=world.customer_a,
        requested_by=world.engineer_a,
        report_type="asset_inventory",
        filters_hash="x",
        as_of_generation_ids={"generations": [b_gen], "evaluations": []},
    )
    from apps.reporting.services import generate

    assert generate(str(run.id)).row_count == 0


def test_regenerate_requires_access(world, env, django_capture_on_commit_callbacks):
    original = request(world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory")
    assert world.client(world.engineer_b).post(f"/api/v1/reports/{original['id']}/regenerate/").status_code == 404


# ---------------------------------------------------------------- saved views (P2-03)


def test_saved_views_validated_scoped_and_owner_controlled(world, env):
    url = f"/api/v1/customers/{world.customer_a.id}/saved-views/"
    c = world.client(world.engineer_a)
    b_asset = Asset.objects.filter(customer=world.customer_b).first()
    assert c.post(url, {"name": "x", "view_type": "software", "filters": {"asset": str(b_asset.id)}}).status_code == 400
    assert c.post(url, {"name": "x", "view_type": "assets", "filters": {"sql": "1"}}).status_code == 400
    private = c.post(url, {"name": "Mine", "view_type": "assets", "filters": {"os": "Windows 11"}}).json()
    shared = c.post(url, {"name": "Team", "view_type": "assets", "filters": {"offline": "true"}, "shared": True}).json()
    viewer = world.client(world.viewer_a)
    assert [v["name"] for v in viewer.get(url).json()["results"]] == ["Team"]
    assert viewer.patch(f"{url}{shared['id']}/", {"name": "Hijack"}).status_code == 403
    assert viewer.delete(f"{url}{private['id']}/").status_code == 404
    assert world.client(world.engineer_b).get(url).status_code == 404


# ---------------------------------------------------------------- definitions & schedules (P2-05)


def make_definition(world, user=None, customer=None, **kw):
    user, customer = user or world.engineer_a, customer or world.customer_a
    resp = world.client(user).post(
        f"/api/v1/customers/{customer.id}/report-definitions/",
        {"name": "Weekly inventory", "report_type": "asset_inventory", "format": "xlsx", **kw},
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


def test_definition_permissions_and_filters(world, env):
    url = f"/api/v1/customers/{world.customer_a.id}/report-definitions/"
    assert world.client(world.viewer_a).post(url, {"name": "x", "report_type": "asset_inventory"}).status_code == 404
    assert (
        world.client(world.engineer_a).post(url, {"name": "x", "report_type": "customer_audit_log"}).status_code == 403
    )
    assert (
        world.client(world.engineer_a)
        .post(url, {"name": "x", "report_type": "asset_inventory", "filters": {"bogus": 1}})
        .status_code
        == 400
    )
    make_definition(world)


def test_schedule_validation(world, env):
    d = make_definition(world)
    url = f"/api/v1/customers/{world.customer_a.id}/report-schedules/"
    c = world.client(world.engineer_a)
    base = {
        "definition": d["id"],
        "frequency": "weekly",
        "time_of_day": "07:00",
        "weekday": 0,
        "timezone": "Asia/Nicosia",
    }
    assert c.post(url, {**base, "timezone": "Mars/Olympus"}).status_code == 400
    assert c.post(url, {**base, "weekday": None}).status_code == 400
    assert c.post(url, {**base, "frequency": "monthly", "day_of_month": 31}).status_code == 400
    assert c.post(url, {**base, "recipients": [world.engineer_b.email]}).status_code == 400  # no access to A
    assert c.post(url, {**base, "recipients": [world.viewer_a.email]}).status_code == 400  # viewer lacks export
    resp = c.post(url, {**base, "recipients": [world.admin_a.email]})
    assert resp.status_code == 201 and resp.json()["recipient_emails"] == [world.admin_a.email]
    assert resp.json()["next_run_at"]
    # other customer's definition cannot be scheduled through A's route
    d_b = make_definition(world, world.engineer_b, world.customer_b)
    assert c.post(url, {**base, "definition": d_b["id"]}).status_code == 400


def _sched(freq="daily", tz="UTC", t=time(7, 0), **kw):
    return ReportSchedule(frequency=freq, time_of_day=t, timezone=tz, **kw)


def test_next_run_timezone_and_dst():
    # Cyprus switches to UTC+3 on 2026-03-29; 07:00 local is 05:00 UTC before and 04:00 UTC after.
    s = _sched(tz="Asia/Nicosia")
    assert compute_next_run(s, datetime(2026, 3, 27, 12, tzinfo=UTC)) == datetime(2026, 3, 28, 5, tzinfo=UTC)
    assert compute_next_run(s, datetime(2026, 3, 28, 12, tzinfo=UTC)) == datetime(2026, 3, 29, 4, tzinfo=UTC)
    weekly = _sched("weekly", weekday=0)  # Monday
    assert compute_next_run(weekly, datetime(2026, 11, 13, tzinfo=UTC)) == datetime(2026, 11, 16, 7, tzinfo=UTC)
    monthly = _sched("monthly", day_of_month=1)
    assert compute_next_run(monthly, datetime(2026, 11, 13, tzinfo=UTC)) == datetime(2026, 12, 1, 7, tzinfo=UTC)
    nonexistent = _sched(tz="Asia/Nicosia", t=time(3, 30))  # 03:30 does not exist on 2026-03-29 in Nicosia
    assert compute_next_run(nonexistent, datetime(2026, 3, 28, 12, tzinfo=UTC)).tzinfo is not None


def _schedule(world, recipients=()):
    d = ReportDefinition.objects.get(pk=make_definition(world)["id"])
    s = ReportSchedule.objects.create(
        definition=d,
        frequency="daily",
        time_of_day=time(6, 0),
        timezone="UTC",
        created_by=world.engineer_a,
        next_run_at=timezone.now() - timedelta(minutes=1),
    )
    s.recipients.set(recipients)
    return s


def test_dispatch_runs_once_per_slot(world, env, django_capture_on_commit_callbacks):
    s = _schedule(world, [world.admin_a])
    slot = s.next_run_at
    with django_capture_on_commit_callbacks(execute=True):
        assert dispatch_due_report_schedules() == 1
        assert dispatch_due_report_schedules() == 0  # already advanced
        assert execute_slot(s, slot) is None  # duplicate dispatch of the same slot suppressed by the DB
    assert ScheduledExecution.objects.filter(schedule=s).count() == 1
    s.refresh_from_db()
    assert s.next_run_at > timezone.now() and s.last_run_at == slot
    ex = ScheduledExecution.objects.get(schedule=s)
    assert ex.state == "started" and ex.report_run.state == "completed" and ex.report_run.format == "xlsx"
    inbox = world.client(world.admin_a).get("/api/v1/reports/inbox/").json()
    assert [r["id"] for r in inbox] == [str(ex.report_run_id)]


def test_revoked_recipient_is_dropped_and_loses_inbox_access(world, env, django_capture_on_commit_callbacks):
    """AUTH-05: revoked membership → pending distribution blocked, scheduled report denied."""
    s = _schedule(world, [world.admin_a])
    CustomerMembership.objects.filter(user=world.admin_a).update(is_active=False)
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_due_report_schedules()
    ex = ScheduledExecution.objects.get(schedule=s)
    assert str(world.admin_a.id) not in ex.delivered_to
    assert AuditEvent.objects.filter(action="report.schedule_recipients_removed").exists()
    assert world.client(world.admin_a).get("/api/v1/reports/inbox/").json() == []
    assert world.client(world.admin_a).get(f"/api/v1/reports/{ex.report_run_id}/download/").status_code == 404


def test_owner_revoked_skips_slot(world, env, django_capture_on_commit_callbacks):
    s = _schedule(world)
    CustomerMembership.objects.filter(user=world.engineer_a).update(is_active=False)
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_due_report_schedules()
    ex = ScheduledExecution.objects.get(schedule=s)
    assert ex.state == "skipped" and ex.reason == "owner_access_revoked" and ex.report_run is None


def test_recipient_inbox_access_revoked_after_delivery(world, env, django_capture_on_commit_callbacks):
    _schedule(world, [world.admin_a])
    with django_capture_on_commit_callbacks(execute=True):
        dispatch_due_report_schedules()
    assert len(world.client(world.admin_a).get("/api/v1/reports/inbox/").json()) == 1
    CustomerMembership.objects.filter(user=world.admin_a).update(is_active=False)
    assert world.client(world.admin_a).get("/api/v1/reports/inbox/").json() == []


def test_sync_schedules_dispatch_idempotently(world, env, django_capture_on_commit_callbacks):
    sched = SyncSchedule.objects.create(
        mapping=env["ma"], interval_hours=6, next_run_at=timezone.now() - timedelta(minutes=5)
    )
    with django_capture_on_commit_callbacks(execute=False):
        assert dispatch_due_sync_schedules() == 1
        assert dispatch_due_sync_schedules() == 0
    run = SyncRun.objects.filter(trigger="schedule").get()
    assert run.idempotency_key.startswith(f"sched:{sched.id}:")
    sched.refresh_from_db()
    assert sched.next_run_at > timezone.now()


def test_sync_schedule_for_revoked_mapping_is_skipped_and_audited(world, env):
    CustomerSourceMapping.objects.filter(pk=env["ma"].pk).update(mapping_status="revoked")
    SyncSchedule.objects.create(mapping=env["ma"], interval_hours=6, next_run_at=timezone.now() - timedelta(minutes=5))
    assert dispatch_due_sync_schedules() == 0
    assert AuditEvent.objects.filter(action="sync.schedule_skipped").exists()


# ---------------------------------------------------------------- trends (P2-06)


def test_trends_from_retained_generations_with_identity(world, env):
    from apps.integrations.models import DatasetGeneration

    first = DatasetGeneration.objects.get(customer=world.customer_a, is_current=True)
    DatasetGeneration.objects.filter(pk=first.pk).update(published_at=timezone.now() - timedelta(days=3))
    assert do_sync(env["ma"], world.engineer_a, devices(11, "a", 6)).state == "completed"
    data = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/trends/", {"days": 30}).json()
    pts = data["points"]
    assert [p["devices"] for p in pts] == [4, 6]
    assert pts[0]["generation_id"] == str(first.id) and pts[0]["data_basis"] == "fixture"
    assert pts[1]["software"]["eligible"] == 6 and pts[1]["software"]["algorithm_version"]
    assert pts[1]["os_updates"]["devices_with_critical"] == 6
    assert world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_b.id}/trends/").status_code == 404
    assert (
        world.client(world.engineer_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/trends/", {"days": "x"})
        .status_code
        == 400
    )


def test_trends_exclude_revoked_mapping(world, env):
    CustomerSourceMapping.objects.filter(pk=env["ma"].pk).update(mapping_status="revoked")
    data = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/trends/").json()
    assert data["points"] == []


def test_expired_artifacts_are_purged_and_audited(world, env, django_capture_on_commit_callbacks):
    from apps.reporting.models import ReportArtifact
    from apps.reporting.services import purge_expired_artifacts, storage_path

    run = request(world, world.engineer_a, world.customer_a, django_capture_on_commit_callbacks, "asset_inventory")
    artifact = ReportArtifact.objects.get(report_run_id=run["id"])
    path = storage_path(artifact.storage_key)
    assert path.is_file()
    assert purge_expired_artifacts() == 0  # not expired yet
    ReportArtifact.objects.filter(pk=artifact.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
    assert purge_expired_artifacts() == 1
    assert not path.exists()
    artifact.refresh_from_db()
    assert artifact.purged_at is not None
    assert world.client(world.engineer_a).get(f"/api/v1/reports/{run['id']}/download/").status_code == 404
    assert AuditEvent.objects.filter(action="report.artifact_purged", target_id=run["id"]).exists()


def test_sync_schedule_api_is_super_admin_only_and_requires_approved_mapping(world, env):
    url = "/api/v1/sync-schedules/"
    assert world.client(world.admin_a).post(url, {"mapping": str(env["ma"].id)}).status_code == 403
    sa = world.client(world.super_admin)
    resp = sa.post(url, {"mapping": str(env["ma"].id), "interval_hours": 12})
    assert resp.status_code == 201 and resp.json()["customer"]["code"] == "ACME"
    assert sa.post(url, {"mapping": str(env["ma"].id)}).status_code == 400  # one per mapping
    CustomerSourceMapping.objects.filter(pk=env["mb"].pk).update(mapping_status="revoked")
    assert sa.post(url, {"mapping": str(env["mb"].id)}).status_code == 400
    assert sa.post(url, {"mapping": str(env["ma"].id), "interval_hours": 0}).status_code == 400
