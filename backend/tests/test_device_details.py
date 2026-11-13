"""VSA4-03 device notifications (PII-minimised) and customer-approved custom fields. Fixture-based — NOT live."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.integrations.vsa.adapter import ALLOWED_PATHS
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.integrations.vsa.schema import normalize_custom_fields, normalize_notifications
from apps.inventory import details
from apps.inventory.models import Asset, CustomFieldAllowlist, DeviceCustomField, DeviceDetailFetch, DeviceNotification

from .test_p2_reporting import csv_rows
from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db
RECENT = (datetime.now(UTC) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_documented_shapes_and_time_forms():
    items = normalize_notifications(
        [
            {"Id": 2733, "Message": "Disk low", "DateTime": "2023-07-12T16:15:02Z", "Priority": "Elevated"},
            {"Id": 2750, "Message": "DB down", "DateTime": 1463473104, "Priority": "critical"},
            {"Id": 1, "Message": "odd", "DateTime": "yesterday", "Priority": "normal"},
        ]
    )
    assert items[0].occurred_at == datetime(2023, 7, 12, 16, 15, 2, tzinfo=UTC) and items[0].priority == "elevated"
    assert items[1].occurred_at == datetime.fromtimestamp(1463473104, tz=UTC)
    assert items[2].occurred_at is None and items[2].occurred_raw == "yesterday"  # kept raw, never guessed
    cf = normalize_custom_fields([{"Id": 345, "Name": "Custom Field Name2", "Value": 2, "Type": "Number"}])
    assert cf[0].value == "2" and cf[0].type == "Number"


def test_message_minimisation():
    text, n = details.minimise_message(
        "Logon failure for CORP\\jsmith reported by jane.doe@example.com; password=hunter2 on 'PC-01'"
    )
    assert "jsmith" not in text and "jane.doe" not in text and "hunter2" not in text
    assert "[account]" in text and "[email]" in text and "'PC-01'" in text and n >= 3


@pytest.mark.parametrize(
    ("name", "sensitive"),
    [
        ("Local Admin Password", True),
        ("BitLocker Recovery Key", True),
        ("API Token", True),
        ("Door PIN", True),
        ("License Key", True),
        ("Rack", False),
        ("Asset Owner Department", False),
    ],
)
def test_sensitive_field_names(name, sensitive):
    assert details.is_sensitive_field_name(name) is sensitive


def test_routes_exclude_tenant_wide_notifications():
    def allowed(p: str) -> bool:
        return any(r.fullmatch(p) for r in ALLOWED_PATHS)

    assert allowed("/api/v3/devices/11-dev-001/notifications") and allowed("/api/v3/devices/11-dev-001/customfields")
    assert not allowed("/api/v3/notifications") and not allowed("/api/v3/customfields")


# ---------------------------------------------------------------- sync


def _assets() -> list[dict]:
    a = [asset(i, 11, ip=f"10.0.1.{i}") for i in range(1, 4)]
    a[0]["_Notifications"] = [
        {
            "Id": 10,
            "Message": "Logon failure for CORP\\svc reported by ops@example.com",
            "DateTime": RECENT,
            "Priority": "critical",
        },
        {"Id": 9, "Message": "Very old", "DateTime": "2020-01-01T00:00:00Z", "Priority": "normal"},
    ]
    for x in a:
        x["_CustomFields"] = [
            {"Id": 1, "Name": "Rack", "Value": "R1", "Type": "Text"},
            {"Id": 2, "Name": "Local Admin Password", "Value": "never-store-me", "Type": "Text"},
            {"Id": 3, "Name": "Owner", "Value": "Finance", "Type": "Text"},
        ]
    return a


def _budgets(env, n=10):  # noqa: F811
    env["inst"].notifications_budget = n
    env["inst"].custom_fields_budget = n
    env["inst"].save(update_fields=["notifications_budget", "custom_fields_budget"])


def test_notifications_window_and_redaction(world, env):  # noqa: F811
    _budgets(env)
    t = FixtureVsaTransport(_assets())
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed", r.error_code
    assert r.notifications_requested == 3
    f = DeviceDetailFetch.objects.get(
        generation_id=r.generation_id, kind="notifications", asset__external_id="11-dev-001"
    )
    assert (f.status, f.reported, f.stored, f.dropped) == ("collected", 2, 1, 1)
    n = DeviceNotification.objects.get(fetch=f)
    assert n.message == "Logon failure for [account] reported by [email]" and n.redactions == 2
    assert not any("customfields" in p for p, _ in t.calls)  # nothing approved -> nothing requested
    assert set(
        DeviceDetailFetch.objects.filter(generation_id=r.generation_id, kind="custom_fields").values_list(
            "status", flat=True
        )
    ) == {"not_requested"}


def test_only_approved_custom_fields_are_stored(world, env):  # noqa: F811
    _budgets(env)
    CustomFieldAllowlist.objects.create(
        customer=world.customer_a,
        name="Rack",
        name_key="rack",
        reason="asset location",
        state="approved",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
    )
    # Defence in depth: even a credential-like row forced into the DB is never stored.
    CustomFieldAllowlist.objects.create(
        customer=world.customer_a,
        name="Local Admin Password",
        name_key="local admin password",
        reason="bypass",
        state="approved",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
    )
    r = run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets()))
    rows = DeviceCustomField.objects.filter(generation_id=r.generation_id)
    assert set(rows.values_list("name", flat=True)) == {"Rack"} and rows.count() == 3
    assert not DeviceCustomField.objects.filter(value="never-store-me").exists()
    f = DeviceDetailFetch.objects.filter(generation_id=r.generation_id, kind="custom_fields").first()
    assert (f.reported, f.stored, f.dropped) == (3, 1, 2)


def test_budget_zero_and_failures_are_isolated(world, env):  # noqa: F811
    r = run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets()))
    assert set(DeviceDetailFetch.objects.filter(generation_id=r.generation_id).values_list("status", flat=True)) == {
        "not_requested"
    }
    _budgets(env)
    t = FixtureVsaTransport(_assets())
    original = t.get
    t.get = lambda url, **kw: FakeResponse(404) if url.endswith("11-dev-002/notifications") else original(url, **kw)  # type: ignore[method-assign]
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed"
    assert (
        DeviceDetailFetch.objects.get(
            generation_id=r.generation_id, kind="notifications", asset__external_id="11-dev-002"
        ).status
        == "failed"
    )


def test_db_rejects_cross_customer_notification(world, env):  # noqa: F811
    _budgets(env)
    run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets()))
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        DeviceNotification.objects.update(customer=world.customer_b)


# ---------------------------------------------------------------- API


@pytest.fixture
def synced(world, env):  # noqa: F811
    _budgets(env)
    run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets()))
    return env


def url(c, tail):
    return f"/api/v1/customers/{c.id}/{tail}"


def test_allowlist_two_person_and_denylist(world, synced):
    admin = world.client(world.admin_a)
    base = url(world.customer_a, "custom-field-allowlist/")
    assert (
        world.client(world.engineer_a).post(base, {"name": "Rack", "reason": "location"}, format="json").status_code
        == 404
    )
    bad = admin.post(base, {"name": "BitLocker Recovery Key", "reason": "handy"}, format="json")
    assert bad.status_code == 400 and "cannot be approved" in str(bad.json())
    created = admin.post(base, {"name": "Rack", "reason": "asset location"}, format="json")
    assert created.status_code == 201
    assert (
        admin.post(base, {"name": "rack", "reason": "dup again"}, format="json").status_code == 400
    )  # case-insensitive
    fid = created.json()["id"]
    assert admin.post(f"{base}{fid}/approve/").status_code == 400
    assert world.client(world.super_admin).post(f"{base}{fid}/approve/").status_code == 200
    assert world.client(world.engineer_b).get(url(world.customer_b, "custom-field-allowlist/")).json() == []
    assert (
        AuditEvent.objects.filter(action__startswith="custom_field_allowlist.", customer=world.customer_a).count() == 2
    )


def test_notifications_api_and_asset_block(world, synced):
    c = world.client(world.viewer_a)
    s = c.get(url(world.customer_a, "notifications/summary/")).json()
    assert s["notifications"] == 1 and s["by_priority"] == {"critical": 1}
    assert s["collection_status"]["collected"] == 3 and "Devices not collected" in s["note"]
    rows = c.get(url(world.customer_a, "notifications/?priority=critical")).json()["results"]
    assert rows[0]["hostname"] == "PC1" and "[email]" in rows[0]["message"]
    assert world.client(world.engineer_b).get(url(world.customer_a, "notifications/")).status_code == 404
    a1 = Asset.objects.get(customer=world.customer_a, external_id="11-dev-001")
    body = c.get(f"/api/v1/assets/{a1.id}/").json()
    assert body["notifications"]["status"] == "collected" and body["notifications"]["dropped"] == 1
    assert body["custom_fields"]["status"] == "not_requested" and body["custom_fields"]["items"] == []


def test_r15_report(world, synced, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(
            url(world.customer_a, "reports/"),
            {"report_type": "device_notifications", "format": "csv", "filters": {}},
            format="json",
        )
    assert resp.status_code == 202, resp.content
    raw = world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/download/")
    provenance, rows = csv_rows(b"".join(raw.streaming_content))
    assert len(rows) == 1 and rows[0][2] == "critical" and "ops@example.com" not in rows[0][4]
    assert any("redacted" in p for p in provenance)
