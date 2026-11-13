"""VSA3-04 applied patch policies, policy definitions and expected-policy drift.

Documented examples from https://api.vsax.net/ (2026-11-13): GET /devices/:id/appliedpolicies and
GET /patchmanagement/policies/:id. Fixture-based only — NOT live validation.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from django.db import IntegrityError, transaction

from apps.audit.models import AuditEvent
from apps.integrations.vsa.adapter import ALLOWED_PATHS
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.integrations.vsa.schema import RecordInvalid, normalize_applied_policies, normalize_patch_policy
from apps.onboarding.matching import Device, Params, reconcile
from apps.patching.models import AppliedPolicy, AppliedPolicyObservation, PatchPolicyDefinition
from apps.patching.policies import Drift, drift

from .test_p2_reporting import csv_rows
from .test_vsa1_hierarchy_network import asset, env, run  # noqa: F401 - env is a fixture

pytestmark = pytest.mark.django_db

DOC_APPLIED = [
    {"PolicyType": "Antivirus", "PolicyId": None, "PolicyName": "No Antivirus"},
    {"PolicyType": "Ransomware Detection", "PolicyId": None, "PolicyName": "No Policy (Explicitly configured)"},
    {"PolicyType": "Patch Management", "PolicyId": 292, "PolicyName": "My Patch Management Policy"},
    {
        "PolicyType": "Device Configuration",
        "PolicyId": 214,
        "PolicyName": "My DC Policy",
        "Profiles": [{"Id": 1906, "Name": "My DC Profile", "Category": "General", "Settings": {"AllowLogin": False}}],
    },
]
DOC_POLICY = {
    "Id": 292,
    "Name": "My Patch Management Policy",
    "Description": "Every saturday at 23:30",
    "GeneralSettings": {
        "CreateRestorePoint": True,
        "RebootOption": "DO_NOT_REBOOT",
        "NotificationSettings": {"Recipients": ["someone@example.invalid"]},
        "UndocumentedThing": 1,
    },
    "OsRules": [{"Field": "SEVERITY", "Operator": "CONTAINS", "Severity": "CRITICAL", "Action": "APPROVE_AND_INSTALL"}],
    "SoftwareRules": [
        {"ProductId": "7-zip-x64", "ProductName": "7-Zip (64-bit)", "Action": "INSTALL_AND_UPDATE", "X": 1}
    ],
}
PM_NONE = {"PolicyType": "Patch Management", "PolicyId": None, "PolicyName": "No Policy (Explicitly configured)"}


def pm(pid: int, name: str = "") -> dict:
    return {"PolicyType": "Patch Management", "PolicyId": pid, "PolicyName": name or f"Policy {pid}"}


# ---------------------------------------------------------------- schema + adapter


def test_documented_applied_policies_and_definition():
    items = normalize_applied_policies(DOC_APPLIED)
    assert [(i.policy_type, i.policy_id, i.explicit_none) for i in items] == [
        ("Antivirus", "", True),
        ("Ransomware Detection", "", True),
        ("Patch Management", "292", False),
        ("Device Configuration", "214", False),
    ]
    assert items[3].profiles == (("1906", "My DC Profile", "General"),)  # Settings never kept
    d = normalize_patch_policy({"Data": DOC_POLICY, "Meta": {"ResponseCode": 200}}, "292")
    assert d.general_settings == {"CreateRestorePoint": True, "RebootOption": "DO_NOT_REBOOT"}
    assert d.software_rules == [
        {"ProductId": "7-zip-x64", "ProductName": "7-Zip (64-bit)", "Action": "INSTALL_AND_UPDATE"}
    ]
    with pytest.raises(RecordInvalid):
        normalize_patch_policy({"Data": DOC_POLICY}, "293")
    with pytest.raises(RecordInvalid):
        normalize_applied_policies([{"PolicyType": "Patch Management", "PolicyId": "x"}])


def test_policy_routes_are_get_only_and_exact():
    def allowed(path: str) -> bool:
        return any(p.fullmatch(path) for p in ALLOWED_PATHS)

    assert allowed("/api/v3/devices/11-dev-001/appliedpolicies")
    assert allowed("/api/v3/patchmanagement/policies/292")
    assert not allowed("/api/v3/patchmanagement/policies/292/assign")
    assert not allowed("/api/v3/patchmanagement/globalrules")
    assert not allowed("/api/v3/devices/11-dev-001/move")


# ---------------------------------------------------------------- sync collection


def _set_budget(env, n):  # noqa: F811
    env["inst"].applied_policies_budget = n
    env["inst"].save(update_fields=["applied_policies_budget"])


def _assets():
    a = [asset(i, 11, ip=f"10.0.1.{i}") for i in range(1, 5)]
    a[0]["_AppliedPolicies"] = [*DOC_APPLIED[:2], pm(301, "WS weekly")]
    a[1]["_AppliedPolicies"] = [PM_NONE]
    a[2]["_AppliedPolicies"] = [DOC_APPLIED[0]]  # no Patch Management entry at all
    a[3]["_AppliedPolicies"] = [pm(302, "Servers monthly")]
    return a


POLICIES = {
    "301": {**DOC_POLICY, "Id": 301, "Name": "WS weekly"},
    "302": {**DOC_POLICY, "Id": 302, "Name": "Servers monthly"},
}


def test_budgeted_collection_states_and_definitions(world, env):  # noqa: F811
    _set_budget(env, 10)
    t = FixtureVsaTransport(_assets(), patch_policies=POLICIES)
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed", r.error_code
    assert r.applied_policies_requested == 4
    states = dict(
        AppliedPolicyObservation.objects.filter(generation_id=r.generation_id).values_list(
            "asset__external_id", "patch_state"
        )
    )
    assert states == {
        "11-dev-001": "assigned",
        "11-dev-002": "explicit_none",
        "11-dev-003": "not_reported",
        "11-dev-004": "assigned",
    }
    defs = {d.policy_id: d for d in PatchPolicyDefinition.objects.filter(generation_id=r.generation_id)}
    assert set(defs) == {"301", "302"} and defs["301"].status == "collected"
    assert "NotificationSettings" not in defs["301"].general_settings
    policy_calls = [p for p, _ in t.calls if p.startswith("/api/v3/patchmanagement/")]
    assert sorted(policy_calls) == ["/api/v3/patchmanagement/policies/301", "/api/v3/patchmanagement/policies/302"]


def test_budget_zero_means_unknown_and_no_calls(world, env):  # noqa: F811
    t = FixtureVsaTransport(_assets(), patch_policies=POLICIES)
    r = run(env["ma"], world.engineer_a, t)
    assert not any("appliedpolicies" in p for p, _ in t.calls)
    assert set(
        AppliedPolicyObservation.objects.filter(generation_id=r.generation_id).values_list("status", "patch_state")
    ) == {("not_requested", "unknown")}


def test_rotation_and_carry_forward(world, env):  # noqa: F811
    _set_budget(env, 3)
    r1 = run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets(), patch_policies=POLICIES))
    first = dict(
        AppliedPolicyObservation.objects.filter(generation_id=r1.generation_id).values_list(
            "asset__external_id", "status"
        )
    )
    assert sorted(first.values()) == ["collected", "collected", "collected", "not_requested"]
    never = next(k for k, v in first.items() if v == "not_requested")
    t2 = FixtureVsaTransport(_assets(), patch_policies=POLICIES)
    r2 = run(env["ma"], world.engineer_a, t2)
    second = {
        o.asset.external_id: o
        for o in AppliedPolicyObservation.objects.filter(generation_id=r2.generation_id).select_related("asset")
    }
    assert second[never].status == "collected"  # never-collected device goes first
    carried = [o for o in second.values() if o.status == "carried_forward"]
    assert len(carried) == 1
    prev = AppliedPolicyObservation.objects.get(generation_id=r1.generation_id, asset=carried[0].asset)
    assert carried[0].collected_at == prev.collected_at and carried[0].patch_state == prev.patch_state
    assert AppliedPolicy.objects.filter(policy_observation=carried[0]).count() == prev.policies.count()


def test_per_device_and_definition_failures_are_isolated(world, env):  # noqa: F811
    _set_budget(env, 10)
    t = FixtureVsaTransport(_assets(), patch_policies={"301": POLICIES["301"]})  # 302 -> 404
    original = t.get
    t.get = lambda url, **kw: FakeResponse(404) if url.endswith("11-dev-002/appliedpolicies") else original(url, **kw)  # type: ignore[method-assign]
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed"
    o = AppliedPolicyObservation.objects.get(generation_id=r.generation_id, asset__external_id="11-dev-002")
    assert (o.status, o.patch_state) == ("failed", "unknown")
    assert PatchPolicyDefinition.objects.get(generation_id=r.generation_id, policy_id="302").status == "failed"


def test_db_rejects_policy_row_with_mismatched_customer(world, env):  # noqa: F811
    _set_budget(env, 10)
    r = run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets(), patch_policies=POLICIES))
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        AppliedPolicy.objects.filter(generation_id=r.generation_id).update(customer=world.customer_b)
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        PatchPolicyDefinition.objects.filter(generation_id=r.generation_id).update(customer=world.customer_b)


# ---------------------------------------------------------------- API, baselines, drift


@pytest.fixture
def synced(world, env):  # noqa: F811
    _set_budget(env, 10)
    run(env["ma"], world.engineer_a, FixtureVsaTransport(_assets(), patch_policies=POLICIES))
    b = [asset(1, 22, ip="10.0.1.10", site=8, group=81)]
    b[0]["_AppliedPolicies"] = [pm(999, "B only")]
    run(env["mb"], world.engineer_b, FixtureVsaTransport(b, patch_policies={"999": {**DOC_POLICY, "Id": 999}}))
    return env


def url(customer, tail):
    return f"/api/v1/customers/{customer.id}/{tail}"


def test_summary_separates_states_and_states_denominator(world, synced):
    s = world.client(world.viewer_a).get(url(world.customer_a, "patch-policies/summary/")).json()
    assert s["devices"] == 4
    assert s["patch_states"] == {"assigned": 2, "explicit_none": 1, "not_reported": 1, "unknown": 0}
    assert s["coverage"]["verified_denominator"] == 3 and s["coverage"]["percent"] == 66.7
    assert s["coverage"]["excluded_unknown"] == 1
    assert {d["policy_id"] for d in s["definitions"]} == {"301", "302"}
    assert "not evidence that any patch was installed" in s["note"]
    assert s["drift"]["no_baseline"] == 4
    assert world.client(world.engineer_b).get(url(world.customer_a, "patch-policies/summary/")).status_code == 404


def test_device_list_filters(world, synced):
    c = world.client(world.viewer_a)
    rows = c.get(url(world.customer_a, "patch-policies/devices/?patch_state=explicit_none")).json()["results"]
    assert [r["hostname"] for r in rows] == ["PC2"]
    assert c.get(url(world.customer_a, "patch-policies/devices/?policy_id=302")).json()["count"] == 1


def test_baseline_two_person_approval_and_drift(world, synced):
    admin = world.client(world.admin_a)
    base = url(world.customer_a, "patch-policy-baselines/")
    body = {"scope_type": "group", "scope_external_id": "51", "expected_policy_id": "301", "reason": "WS standard"}
    assert world.client(world.engineer_a).post(base, body, format="json").status_code == 404  # needs manage_exceptions
    assert admin.post(base, {**body, "expected_policy_id": "999"}, format="json").status_code == 400  # B's policy
    assert admin.post(base, {**body, "scope_external_id": "81"}, format="json").status_code == 400  # B's group
    created = admin.post(base, body, format="json")
    assert created.status_code == 201, created.content
    bid = created.json()["id"]
    assert created.json()["expected_policy_name"] == "WS weekly"
    assert admin.post(base, body, format="json").status_code == 400  # one active per scope
    assert admin.post(f"{base}{bid}/approve/").status_code == 400  # proposer cannot approve
    s = world.client(world.viewer_a).get(url(world.customer_a, "patch-policies/summary/")).json()
    assert s["drift"]["no_baseline"] == 4  # proposals do not drive drift
    assert world.client(world.super_admin).post(f"{base}{bid}/approve/").status_code == 200
    s = world.client(world.viewer_a).get(url(world.customer_a, "patch-policies/summary/")).json()
    # Group 51 holds all four: 301 matches, explicit none -> missing, not reported -> unknown, 302 -> different.
    assert s["drift"] == {
        "no_baseline": 0,
        "unknown": 1,
        "matches": 1,
        "different_policy": 1,
        "missing_policy": 1,
        "unexpected_policy": 0,
    }
    assert world.client(world.engineer_b).get(url(world.customer_b, "patch-policy-baselines/")).json() == []
    assert AuditEvent.objects.filter(action__startswith="patch_baseline.", customer=world.customer_a).count() == 2


def test_drift_function_states():
    class B:
        def __init__(self, none, pid=""):
            self.expect_no_policy, self.expected_policy_id = none, pid

    assert drift(None, "assigned", "1") == Drift.NO_BASELINE
    assert drift(B(True), "explicit_none", "") == Drift.MATCHES
    assert drift(B(True), "assigned", "1") == Drift.UNEXPECTED_POLICY
    assert drift(B(False, "1"), "not_reported", "") == Drift.UNKNOWN
    assert drift(B(False, "1"), "unknown", "") == Drift.UNKNOWN


def test_asset_detail_policies_block(world, synced):
    from apps.inventory.models import Asset

    a = Asset.objects.get(customer=world.customer_a, external_id="11-dev-001")
    p = world.client(world.viewer_a).get(f"/api/v1/assets/{a.id}/").json()["policies"]
    assert p["patch_state"] == "assigned" and p["patch_policy_id"] == "301"
    assert {x["type"] for x in p["applied"]} == {"Antivirus", "Ransomware Detection", "Patch Management"}
    assert p["definition"]["name"] == "WS weekly" and p["definition"]["os_rules"]


def test_r08_report(world, synced, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        resp = world.client(world.engineer_a).post(
            url(world.customer_a, "reports/"),
            {"report_type": "patch_policy_coverage", "format": "csv", "filters": {}},
            format="json",
        )
    assert resp.status_code == 202, resp.content
    raw = world.client(world.engineer_a).get(f"/api/v1/reports/{resp.json()['id']}/download/")
    provenance, rows = csv_rows(b"".join(raw.streaming_content))
    assert any("Assignment is configuration, not deployment" in p for p in provenance) and len(rows) == 4
    assert sorted(r[4] for r in rows) == ["assigned", "assigned", "explicit_none", "not_reported"]


def test_onboarding_no_patch_policy_flag_only_for_explicit_none():
    now = datetime(2026, 11, 13, tzinfo=UTC)
    devs = [
        Device("a1", "g1", "PC1", last_seen_online=now, network_status="collected", patch_policy_state="explicit_none"),
        Device("a2", "g2", "PC2", last_seen_online=now, network_status="collected", patch_policy_state="not_reported"),
        Device("a3", "g3", "PC3", last_seen_online=now, network_status="collected", patch_policy_state="unknown"),
    ]
    out = reconcile(
        [(2, {"hostname": "PC1"}), (3, {"hostname": "PC2"}), (4, {"hostname": "PC3"})], devs, Params(snapshot_at=now)
    )
    assert [r.flags for r in out.rows] == [["NO_PATCH_POLICY"], [], []]
    assert "NO_PATCH_POLICY" not in out.summary["parameters"]["flags_not_evaluated"]
