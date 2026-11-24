"""Default deployment has one administrator: they can approve their own changes, and every approval is audited."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent

from .test_vsa1_hierarchy_network import asset, env, run, synced  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db
URL = "/api/v1/catalog/lifecycle/"
ENTRY = {
    "kind": "os",
    "os_family": "Windows 11",
    "release_label": "23H2",
    "end_of_support": "2027-11-10",
    "source_url": "https://lifecycle-evidence.example.test/page",
    "source_type": "vendor_lifecycle_page",
    "source_checked_at": "2026-11-01",
    "confidence": "official",
}


def test_one_step_when_second_approver_not_required(world, settings):
    """Product owner 2026-11-24: one authorization. Saving is approving; both steps are audited."""
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    client = world.client(world.super_admin)
    created = client.post(URL, ENTRY, format="json").json()
    assert created["state"] == "approved" and created["reviewed_by"] == world.super_admin.email
    actions = set(AuditEvent.objects.filter(target_id=created["id"]).values_list("action", flat=True))
    assert {"lifecycle.proposed", "lifecycle.approved"} <= actions
    assert client.post(f"{URL}{created['id']}/approve/", {}, format="json").status_code == 400  # nothing left to do


def test_self_approval_refused_when_second_approver_required(world, settings):
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = True
    client = world.client(world.super_admin)
    eid = client.post(URL, ENTRY, format="json").json()["id"]
    assert client.post(f"{URL}{eid}/approve/", {}, format="json").status_code == 400


def test_setting_defaults_to_single_admin(monkeypatch):
    import importlib

    import config.settings as s

    monkeypatch.delenv("REQUIRE_SECOND_APPROVER", raising=False)
    monkeypatch.delenv("CATALOG_REQUIRE_SEPARATE_REVIEWER", raising=False)
    assert importlib.reload(s).CATALOG_REQUIRE_SEPARATE_REVIEWER is False
    monkeypatch.setenv("REQUIRE_SECOND_APPROVER", "true")
    assert importlib.reload(s).CATALOG_REQUIRE_SEPARATE_REVIEWER is True
    monkeypatch.delenv("REQUIRE_SECOND_APPROVER")
    importlib.reload(s)


def _customer(world, tail):
    return f"/api/v1/customers/{world.customer_a.id}/{tail}"


@pytest.mark.parametrize(
    ("tail", "body", "audit"),
    [
        (
            "expected-subnets/",
            {"scope_type": "site", "scope_external_id": "5", "cidr": "10.0.1.0/24", "reason": "HQ LAN"},
            "expected_subnet",
        ),
        ("custom-field-allowlist/", {"name": "Rack", "reason": "asset location"}, "custom_field_allowlist"),
        (
            "health-thresholds/",
            {
                "offline_hours": 24,
                "stale_days": 7,
                "disk_warning_free_pct": 15,
                "disk_critical_free_pct": 5,
                "minimum_agent_version": "5.1",
                "reason": "Agent 5.1 baseline",
            },
            "health_thresholds",
        ),
    ],
)
def test_customer_settings_apply_when_saved(world, synced, settings, tail, body, audit):  # noqa: F811
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    resp = world.client(world.admin_a).post(_customer(world, tail), body, format="json")
    assert resp.status_code == 201, resp.content
    assert resp.json()["state"] == "approved"
    actions = set(AuditEvent.objects.filter(target_id=resp.json()["id"]).values_list("action", flat=True))
    assert {f"{audit}.proposed", f"{audit}.approved"} <= actions


def test_customer_settings_wait_for_a_second_administrator_when_required(world, synced, settings):  # noqa: F811
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = True
    resp = world.client(world.admin_a).post(
        _customer(world, "custom-field-allowlist/"), {"name": "Rack", "reason": "asset location"}, format="json"
    )
    assert resp.status_code == 201 and resp.json()["state"] == "proposed"


def test_mapping_applies_now_for_a_super_admin_but_waits_for_a_customer_admin(world, settings):
    from apps.customers.models import CustomerSourceMapping
    from apps.integrations.models import SyncSchedule

    from .factories import IntegrationFactory

    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    inst = IntegrationFactory()
    url = _customer(world, "mappings/")
    by_admin = world.client(world.admin_a).post(url, {"integration_instance": str(inst.id), "external_org_id": "1001"})
    assert by_admin.status_code == 201 and by_admin.json()["mapping_status"] == "proposed"
    CustomerSourceMapping.objects.filter(pk=by_admin.json()["id"]).delete()
    by_super = world.client(world.super_admin).post(
        url, {"integration_instance": str(inst.id), "external_org_id": "1001"}
    )
    assert by_super.status_code == 201 and by_super.json()["mapping_status"] == "approved"
    assert SyncSchedule.objects.filter(mapping_id=by_super.json()["id"]).exists()
    approved = AuditEvent.objects.get(action="mapping.approved", target_id=by_super.json()["id"])
    assert approved.metadata["self_approved"] is True


def test_catalog_import_and_alias_apply_when_saved(world, settings):
    from apps.software.models import CatalogRevision

    from .test_p1_api import chrome_import

    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    client = world.client(world.super_admin)
    imp = chrome_import(client)
    assert imp.status_code == 201 and imp.json()["state"] == "approved"
    product = CatalogRevision.objects.get().product
    alias = client.post(
        "/api/v1/catalog/aliases/", {"product": str(product.id), "name_pattern": "Contoso Tool", "match_type": "exact"}
    )
    assert alias.status_code == 201 and alias.json()["review_status"] == "approved"
    assert AuditEvent.objects.filter(action="catalog.import_approved", target_id=imp.json()["id"]).exists()
