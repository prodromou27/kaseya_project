"""VSA4-01 agent health and VSA4-02 disk/hardware/security observations. Fixture-based only — NOT live validation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from apps.audit.models import AuditEvent
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.integrations.vsa.schema import normalize_asset
from apps.inventory import health
from apps.inventory.health import DIMENSIONS, Thresholds
from apps.inventory.models import Asset, AssetObservation, HealthThresholds
from apps.onboarding.matching import Device, Params, reconcile

from .test_p2_reporting import csv_rows
from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db
NOW = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------- classifiers


def test_connectivity_boundaries_and_never_seen():
    t = Thresholds()
    assert health.connectivity(None, NOW, t) == "never_seen"
    assert health.connectivity(NOW - timedelta(hours=23), NOW, t) == "seen_recently"
    assert health.connectivity(NOW - timedelta(hours=25), NOW, t) == "offline"
    assert health.connectivity(NOW - timedelta(days=8), NOW, t) == "stale"


def test_agent_version_requires_approved_minimum():
    assert health.agent_version("5.0.7", Thresholds()) == "not_evaluated"
    t = Thresholds(minimum_agent_version="5.1")
    assert health.agent_version("5.0.7", t) == "old"
    assert health.agent_version("5.1.0", t) == "current"
    assert health.agent_version("5.10.1", t) == "current"
    assert health.agent_version("dev-build", t) == "unparseable"
    assert health.agent_version("", t) == "missing"


def test_disk_uses_system_disks_and_keeps_unknowns_apart():
    t = Thresholds()
    d = Decimal
    assert health.disk("collected", [(True, d("30")), (False, d("2"))], t) == ("ok", d("30"))  # data disk ignored
    assert health.disk("collected", [(None, d("10")), (None, d("40"))], t) == ("warning", d("10"))  # no system flag
    assert health.disk("collected", [(True, d("4.5"))], t)[0] == "critical"
    assert health.disk("collected", [(True, None)], t)[0] == "free_pct_not_reported"
    assert health.disk("collected", [], t)[0] == "no_disks_reported"
    assert health.disk("not_collected", [(True, d("1"))], t)[0] == "not_collected"


@pytest.mark.parametrize(
    ("items", "expected"),
    [
        ([(True, True)], "enabled_up_to_date"),
        ([(True, False)], "enabled_outdated"),
        ([(True, None)], "enabled_update_unknown"),
        ([(False, True)], "disabled"),
        ([(None, None)], "state_unknown"),
        ([], "not_reported"),
    ],
)
def test_antivirus_tri_state(items, expected):
    assert health.antivirus("collected", items) == expected
    assert health.antivirus("not_collected", items) == "not_collected"


def test_firewall_profiles():
    assert health.firewall("collected", [True, True]) == "enabled"
    assert health.firewall("collected", [True, False]) == "disabled"
    assert health.firewall("collected", [True, None]) == "state_unknown"
    assert health.firewall("collected", []) == "not_reported"


def test_documented_aggregate_and_hardware_fields_kept_verbatim():
    a = normalize_asset(
        {
            "Identifier": "x1",
            "OrganizationId": 1,
            "MemoryTotal": 8589398016,
            "FirewallEnabled": True,
            "AntivirusEnabled": "enabled",
            "AntivirusUpToDate": "yes",
            "UacEnabled": "true",  # not a documented boolean -> unknown, never coerced
            "CpuUsage": 19,
            "MemoryUsage": 55,
            "AssetInfo": [
                {
                    "CategoryName": "System",
                    "CategoryData": {"CPU": "12th Gen", "Number of Cores": "12", "Number of Logical Processors": "2"},
                }
            ],
        }
    )
    assert (a.memory_total_raw, a.firewall_enabled, a.uac_enabled) == ("8589398016", True, None)
    assert (a.antivirus_enabled_raw, a.antivirus_up_to_date_raw) == ("enabled", "yes")
    assert (a.cpu_name, a.cpu_cores_raw, a.logical_processors_raw) == ("12th Gen", "12", "2")
    assert not hasattr(a, "cpu_usage")  # point-in-time telemetry deliberately not stored


# ---------------------------------------------------------------- sync + API


def _assets():
    a = [asset(i, 11, ip=f"10.0.1.{i}") for i in range(1, 6)]
    a[0]["ClientVersion"], a[0]["LastSeenOnline"] = (
        "5.1.2",
        (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    a[1]["ClientVersion"], a[1]["LastSeenOnline"] = (
        "5.0.7",
        (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    a[2]["ClientVersion"] = "dev-build"
    a[2]["LastSeenOnline"] = (datetime.now(UTC) - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
    a[3].pop("LastSeenOnline")
    a[3]["ClientVersion"] = "5.1.2"
    a[4]["ClientVersion"] = "5.1.2"
    a[4]["LastSeenOnline"] = (datetime.now(UTC) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Helper defaults kept on purpose for PC1-PC3: 12% free disk (below the 15% warning) and an antivirus item
    # without UpToDate (-> enabled_update_unknown).
    a[3].pop("Disks")
    a[3].pop("Security")
    a[4]["Disks"] = [{"Name": "C:", "System": True, "FreePercentage": 3, "TotalValue": 100}]
    a[4]["Security"] = [
        {"Type": "Antivirus", "Name": "AV", "Enabled": False},
        {"Type": "Firewall", "Name": "FW", "Enabled": True},
    ]
    a[4]["MemoryTotal"] = 1234
    return a


@pytest.fixture
def synced(world, env):  # noqa: F811
    run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets()))
    run(env["mb"], world.engineer_b, FixtureVsaTransport([asset(1, 22, ip="10.0.1.10", site=8, group=81)]))
    return env


def url(customer, tail):
    return f"/api/v1/customers/{customer.id}/{tail}"


def test_summary_partitions_every_dimension(world, synced):
    s = world.client(world.viewer_a).get(url(world.customer_a, "device-health/summary/")).json()
    assert s["devices"] == 5 and s["thresholds"]["source"] == "default"
    for dim in DIMENSIONS:
        assert sum(s["dimensions"][dim].values()) == 5, dim
    assert s["dimensions"]["connectivity"] == {"seen_recently": 2, "offline": 1, "stale": 1, "never_seen": 1}
    assert s["dimensions"]["agent_version"]["not_evaluated"] == 5
    assert s["dimensions"]["disk"] == {
        "ok": 0,
        "warning": 3,
        "critical": 1,
        "free_pct_not_reported": 0,
        "no_disks_reported": 0,
        "not_collected": 1,
    }
    assert s["dimensions"]["antivirus"]["disabled"] == 1 and s["dimensions"]["antivirus"]["not_collected"] == 1
    assert any("not live monitoring telemetry" in n for n in s["notes"])
    assert world.client(world.engineer_b).get(url(world.customer_a, "device-health/summary/")).status_code == 404


def test_device_filters_and_hardware(world, synced):
    c = world.client(world.viewer_a)
    rows = c.get(url(world.customer_a, "device-health/devices/?disk=critical")).json()["results"]
    assert [r["hostname"] for r in rows] == ["PC5"]
    assert rows[0]["hardware"]["memory_total_raw"] == "1234" and rows[0]["worst_disk_free_pct"] == 3.0
    assert c.get(url(world.customer_a, "device-health/devices/?connectivity=never_seen")).json()["count"] == 1
    attention = c.get(url(world.customer_a, "device-health/devices/?connectivity=offline,stale,never_seen"))
    assert attention.status_code == 200 and attention.json()["count"] == 3
    assert {r["connectivity"] for r in attention.json()["results"]} == {"offline", "stale", "never_seen"}
    assert c.get(url(world.customer_a, "device-health/devices/?connectivity=offline,invalid")).status_code == 400
    assert (
        world.client(world.engineer_b).get(url(world.customer_a, "device-health/devices/?disk=critical")).status_code
        == 404
    )


def test_summary_matches_detailed_classification_for_every_dimension(world, synced):
    from collections import Counter

    from apps.inventory import health

    rows = health.device_rows(world.customer_a.id)
    summary = health.summary(world.customer_a.id)
    assert summary["devices"] == len(rows)
    for dimension, states in health.DIMENSIONS.items():
        counts = Counter(row[dimension] for row in rows)
        assert summary["dimensions"][dimension] == {state: counts[state] for state in states}
    assert sum(group["devices"] for group in summary["by_group"]) == len(rows)


def test_thresholds_two_person_approval_and_supersede(world, synced):
    admin = world.client(world.admin_a)
    base = url(world.customer_a, "health-thresholds/")
    body = {
        "offline_hours": 24,
        "stale_days": 7,
        "disk_warning_free_pct": 15,
        "disk_critical_free_pct": 5,
        "minimum_agent_version": "5.1",
        "reason": "Agent 5.1 baseline",
    }
    assert world.client(world.engineer_a).post(base, body, format="json").status_code == 404
    assert admin.post(base, {**body, "minimum_agent_version": "latest"}, format="json").status_code == 400
    assert admin.post(base, {**body, "disk_critical_free_pct": 20}, format="json").status_code == 400
    assert admin.post(base, {**body, "stale_days": 1, "offline_hours": 48}, format="json").status_code == 400
    first = admin.post(base, body, format="json")
    assert first.status_code == 201, first.content
    assert admin.post(base, body, format="json").status_code == 400  # one pending proposal at a time
    assert admin.post(f"{base}{first.json()['id']}/approve/").status_code == 400  # proposer cannot approve
    assert world.client(world.super_admin).post(f"{base}{first.json()['id']}/approve/").status_code == 200
    s = world.client(world.viewer_a).get(url(world.customer_a, "device-health/summary/")).json()
    assert s["thresholds"]["source"] == "approved"
    assert s["dimensions"]["agent_version"] == {
        "current": 3,
        "old": 1,
        "unparseable": 1,
        "missing": 0,
        "not_evaluated": 0,
    }
    second = admin.post(base, {**body, "minimum_agent_version": "5.2"}, format="json").json()
    world.client(world.super_admin).post(f"{base}{second['id']}/approve/")
    states = dict(
        HealthThresholds.objects.filter(customer=world.customer_a).values_list("minimum_agent_version", "state")
    )
    assert states == {"5.1": "superseded", "5.2": "approved"}
    eff = world.client(world.viewer_a).get(f"{base}effective/").json()
    assert eff["minimum_agent_version"] == "5.2"
    assert AuditEvent.objects.filter(action__startswith="health_thresholds.", customer=world.customer_a).count() == 4
    assert world.client(world.engineer_b).get(url(world.customer_b, "health-thresholds/")).json() == []


def test_asset_detail_health_block(world, synced):
    a = Asset.objects.get(customer=world.customer_a, external_id="11-dev-005")
    h = world.client(world.viewer_a).get(f"/api/v1/assets/{a.id}/").json()["health"]
    assert h["disk"] == "critical" and h["antivirus"] == "disabled" and h["firewall"] == "enabled"
    assert h["thresholds"]["source"] == "default"


@pytest.mark.parametrize(
    ("report", "col_index", "expected"),
    [
        ("agent_health", 5, ["never_seen", "offline", "seen_recently", "seen_recently", "stale"]),
        ("disk_hardware", 2, ["critical", "not_collected", "warning", "warning", "warning"]),
        (
            "security_observations",
            2,
            ["disabled", "enabled_update_unknown", "enabled_update_unknown", "enabled_update_unknown", "not_collected"],
        ),
    ],
)
def test_health_reports(world, synced, django_capture_on_commit_callbacks, report, col_index, expected):
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(
            url(world.customer_a, "reports/"), {"report_type": report, "format": "csv", "filters": {}}, format="json"
        )
    assert resp.status_code == 202, resp.content
    raw = world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/download/")
    provenance, rows = csv_rows(b"".join(raw.streaming_content))
    assert any("not live monitoring telemetry" in p for p in provenance)
    assert sorted(r[col_index] for r in rows) == expected


def test_onboarding_old_agent_flag_only_with_approved_minimum():
    devs = [
        Device("a1", "g1", "PC1", last_seen_online=NOW, network_status="collected", client_version="5.0.7"),
        Device("a2", "g2", "PC2", last_seen_online=NOW, network_status="collected", client_version="dev-build"),
        Device("a3", "g3", "PC3", last_seen_online=NOW, network_status="collected", client_version="5.1.2"),
    ]
    rows = [(2, {"hostname": "PC1"}), (3, {"hostname": "PC2"}), (4, {"hostname": "PC3"})]
    out = reconcile(rows, devs, Params(snapshot_at=NOW, minimum_agent_version="5.1"))
    assert [r.flags for r in out.rows] == [["OLD_AGENT"], [], []]
    assert out.summary["parameters"]["flags_not_evaluated"] == {}
    out = reconcile(rows, devs, Params(snapshot_at=NOW))
    assert all("OLD_AGENT" not in r.flags for r in out.rows)
    assert "OLD_AGENT" in out.summary["parameters"]["flags_not_evaluated"]


def test_observation_stores_aggregates(world, synced):
    o = AssetObservation.objects.get(
        customer=world.customer_a, asset__external_id="11-dev-005", generation__is_current=True
    )
    assert o.memory_total_raw == "1234"
