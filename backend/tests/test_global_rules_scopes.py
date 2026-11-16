"""GR-01 patch global rules and automation scopes: read-only configuration, fixture data only."""

from __future__ import annotations

import pytest

from apps.automation.models import AutomationScope, PatchGlobalRules
from apps.software import thirdparty

from .test_automation import demo  # noqa: F401

pytestmark = pytest.mark.django_db


def test_scopes_and_global_rules_are_in_the_catalog(world, demo):  # noqa: F811
    assert PatchGlobalRules.objects.get(integration_instance=demo).software_rules[0]["ProductName"] == "Mozilla Firefox"
    catalog = world.client(world.super_admin).get("/api/v1/automation/catalog/").json()
    scope = next(s for s in catalog["scopes"] if s["id"] == "71")
    assert scope["total_devices"] == 118
    assert {"type": "Organization", "identifier": "1001"} in scope["criteria"]
    assert {(u["type"], u["name"]) for u in scope["used_by"]} == {
        ("Task", "DEMO Weekly maintenance (fixture)"),
        ("Workflow", "DEMO Clean temp files (fixture)"),
    }
    assert catalog["global_rules"][0]["os_rules"][0]["Severity"] == "CRITICAL"
    assert world.client(world.engineer_a).get("/api/v1/automation/catalog/").status_code == 403


def test_custom_field_criteria_values_are_not_kept(world, demo):  # noqa: F811
    from django.utils import timezone

    from apps.automation.collector import _collect_rules_and_scopes

    class Adapter:
        def get_global_rules(self):
            return {"Data": {"OsRules": [], "SoftwareRules": []}}

        def list_scopes(self):
            return [{"Id": 9, "Name": "By custom field"}]

        def get_scope(self, sid):
            return {"Data": {"Criteria": [{"Type": "Custom field", "Identifier": "Owner=jane"}], "TotalDevices": 3}}

        def get_scope_usage(self, sid):
            return []

    _collect_rules_and_scopes(demo, Adapter(), timezone.now())
    assert AutomationScope.objects.get(integration_instance=demo, external_id="9").criteria == [
        {"type": "Custom field", "identifier": ""}
    ]


def test_global_software_rule_counts_as_coverage(world, demo):  # noqa: F811
    from apps.patching.models import AppliedPolicyObservation

    assigned = list(
        AppliedPolicyObservation.objects.filter(customer=world.customer_a).values_list("id", flat=True)[:40]
    )
    AppliedPolicyObservation.objects.filter(id__in=assigned).update(patch_state="assigned", patch_policy_id="9999")
    rows = [r for r in thirdparty.rows(world.customer_a.id) if r["program_key"].startswith("mozilla firefox")]
    assert rows, "demo devices report Firefox"
    by_global = [r for r in rows if r["policy_name"] == "Global rule"]
    assert by_global and all(r["coverage"] == "covered" for r in by_global)
    # Devices outside patch management (state unknown here) are never marked covered by a global rule.
    in_scope = {
        str(a) for a in AppliedPolicyObservation.objects.filter(id__in=assigned).values_list("asset_id", flat=True)
    }
    assert all(r["asset_id"] in in_scope for r in by_global)
    assert all(r["coverage"] == "unknown" for r in rows if r["asset_id"] not in in_scope)
    PatchGlobalRules.objects.all().delete()
    assert not any(r["policy_name"] == "Global rule" for r in thirdparty.rows(world.customer_a.id))
