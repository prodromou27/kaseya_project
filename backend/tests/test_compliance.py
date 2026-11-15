"""Compliance baselines: rules evaluate pass/fail/unknown from the current snapshot; scoped, audited, validated."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.compliance.models import ComplianceBaseline

from .test_p1_api import synced  # noqa: F401  (fixture: 6 devices for A, 4 for B; Chrome + Contoso Tool)

pytestmark = pytest.mark.django_db


def url(world, suffix=""):
    return f"/api/v1/customers/{world.customer_a.id}/compliance-baselines/{suffix}"


BASELINE = {
    "name": "Workstation standard",
    "rules": [
        {"kind": "required_software", "params": {"name": "chrome", "min_version": "131"}, "severity": "high"},
        {"kind": "forbidden_software", "params": {"name": "Contoso"}},
        {"kind": "antivirus_healthy", "params": {}},
    ],
}


def create(world, body=BASELINE, user=None):
    return world.client(user or world.admin_a).post(url(world), body, format="json")


def test_admin_creates_a_baseline_and_results_are_evaluated(world, synced):  # noqa: F811
    resp = create(world)
    assert resp.status_code == 201, resp.content
    bid = resp.json()["id"]
    assert resp.json()["rules"][0]["label"] == "“chrome” is installed (version 131 or later)"
    data = world.client(world.viewer_a).get(url(world, f"{bid}/results/")).json()
    assert data["devices_in_scope"] == 6
    chrome, contoso, av = data["rules"]
    # Even indices run the 131 reference, odd ones 130.x
    assert chrome["counts"] == {"pass": 3, "fail": 3, "unknown": 0}
    assert contoso["counts"] == {"pass": 0, "fail": 6, "unknown": 0}
    # The fixture has no Security section: antivirus is unknown, never a pass or fail
    assert av["counts"] == {"pass": 0, "fail": 0, "unknown": 6}
    assert data["totals"] == {"pass": 0, "fail": 6, "unknown": 0} and data["score_pct"] == 0.0
    failing = world.client(world.viewer_a).get(url(world, f"{bid}/results/"), {"rule": chrome["id"]}).json()
    assert failing["count"] == 3
    assert all("older than 131" in d["results"][0]["reason"] for d in failing["results"])
    assert AuditEvent.objects.filter(action="compliance_baseline.created", target_id=bid).exists()


def test_unknown_only_device_is_not_counted_in_the_score(world, synced):  # noqa: F811
    bid = create(world, {"name": "AV only", "rules": [{"kind": "antivirus_healthy", "params": {}}]}).json()["id"]
    data = world.client(world.admin_a).get(url(world, f"{bid}/results/")).json()
    assert data["totals"] == {"pass": 0, "fail": 0, "unknown": 6} and data["score_pct"] is None


def test_overview_lists_enabled_baselines(world, synced):  # noqa: F811
    bid = create(world).json()["id"]
    create(world, {"name": "Disabled", "enabled": False, "rules": [{"kind": "firewall_enabled", "params": {}}]})
    body = world.client(world.engineer_a).get(url(world, "overview/")).json()
    assert [b["id"] for b in body["baselines"]] == [bid]
    assert body["baselines"][0]["groups"][0]["group_name"]
    assert any(k["kind"] == "no_critical_updates" for k in body["rule_kinds"])


def test_only_admins_edit_and_other_customers_cannot_see(world, synced):  # noqa: F811
    # Without the manage capability the customer is "not found" for writes (project convention: 404, not 403)
    assert create(world, user=world.engineer_a).status_code == 404
    assert create(world, user=world.viewer_a).status_code == 404
    bid = create(world).json()["id"]
    # Customer B's engineer: unknown customer for them -> 404, nothing revealed
    assert world.client(world.engineer_b).get(url(world)).status_code == 404
    assert world.client(world.engineer_b).get(url(world, f"{bid}/results/")).status_code == 404
    b_url = f"/api/v1/customers/{world.customer_b.id}/compliance-baselines/{bid}/"
    assert world.client(world.super_admin).get(b_url).status_code == 404  # A's baseline is not under B
    patch = world.client(world.admin_a).patch(url(world, f"{bid}/"), {"enabled": False}, format="json")
    assert patch.status_code == 200 and not ComplianceBaseline.objects.get(pk=bid).enabled
    assert world.client(world.admin_a).delete(url(world, f"{bid}/")).status_code == 204
    assert AuditEvent.objects.filter(action="compliance_baseline.deleted", target_id=bid).exists()


@pytest.mark.parametrize(
    "rule",
    [
        {"kind": "required_software", "params": {}},
        {"kind": "os_min_version", "params": {"version": "ten"}},
        {"kind": "disk_free_min", "params": {"percent": 150}},
        {"kind": "max_days_offline", "params": {"days": True}},
        {"kind": "run_script", "params": {}},
    ],
)
def test_invalid_rules_are_rejected(world, synced, rule):  # noqa: F811
    assert create(world, {"name": "Bad", "rules": [rule]}).status_code == 400
    assert not ComplianceBaseline.objects.exists()


def test_names_are_unique_per_customer(world, synced):  # noqa: F811
    assert create(world).status_code == 201
    assert create(world).status_code == 400
