"""SCR-01 script collectors: only allowlisted output variables are kept; values feed compliance and reports."""

from __future__ import annotations

import pytest

from apps.automation.models import AutomationScript, DeviceScriptValue
from apps.integrations import sync

from .test_automation import demo  # noqa: F401  (demo tenant synced for customer A)

pytestmark = pytest.mark.django_db
SCRIPT = "5c0e0b8e-0000-4000-8000-00000000b17c"


def make_collector(world, demo, variables):  # noqa: F811
    return world.client(world.super_admin).post(
        "/api/v1/script-collectors/",
        {
            "integration_instance": str(demo.id),
            "script_external_id": SCRIPT,
            "label": "BitLocker",
            "allowed_variables": variables,
        },
        format="json",
    )


def resync(world, demo):  # noqa: F811
    from apps.customers.models import CustomerSourceMapping

    mapping = CustomerSourceMapping.objects.get(integration_instance=demo)
    run, _ = sync.request_sync(mapping, requested_by=world.engineer_a)
    assert sync.execute(str(run.id)).state == "completed"


def test_collector_keeps_only_allowlisted_variables(world, demo):  # noqa: F811
    assert AutomationScript.objects.filter(external_id=SCRIPT).exists()  # catalog came with the first sync
    assert make_collector(world, demo, ["RecoveryKey"]).status_code == 400  # credential-like name refused
    assert make_collector(world, demo, ["BitLockerProtection"]).status_code == 201
    resync(world, demo)
    values = DeviceScriptValue.objects.filter(customer=world.customer_a)
    collected = values.filter(state="collected")
    assert collected.count() == 32 and values.filter(state="never_run").count() == 8 + 90
    assert all(set(v.values) == {"BitLockerProtection"} for v in collected)  # RecoveryKey never stored
    assert not any("SECRET" in str(v.values) for v in values)

    body = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/script-values/").json()
    assert body["collectors"][0]["label"] == "BitLocker"
    assert {
        r["values"].get("BitLockerProtection", {}).get("value") for r in body["results"] if r["state"] == "collected"
    } == {"On", "Off"}
    assert (
        world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_a.id}/script-values/").status_code == 404
    )
    assert world.client(world.admin_a).post("/api/v1/script-collectors/", {}, format="json").status_code == 403


def test_script_values_drive_compliance_and_custom_reports(world, demo):  # noqa: F811
    cid = make_collector(world, demo, ["BitLockerProtection"]).json()["id"]
    resync(world, demo)
    rule = {
        "kind": "script_value",
        "params": {"collector": cid, "variable": "BitLockerProtection", "op": "equals", "value": "On"},
    }
    created = world.client(world.admin_a).post(
        f"/api/v1/customers/{world.customer_a.id}/compliance-baselines/",
        {"name": "Encryption", "rules": [rule]},
        format="json",
    )
    assert created.status_code == 201, created.content
    assert created.json()["rules"][0]["label"] == "BitLocker: BitLockerProtection is “On”"
    result = (
        world.client(world.admin_a)
        .get(f"/api/v1/customers/{world.customer_a.id}/compliance-baselines/{created.json()['id']}/results/")
        .json()
    )
    counts = result["rules"][0]["counts"]
    assert counts["pass"] + counts["fail"] == 32 and counts["fail"] > 0 and counts["unknown"] == 98
    bad = {**rule, "params": {**rule["params"], "variable": "RecoveryKey"}}
    assert (
        world.client(world.admin_a)
        .post(
            f"/api/v1/customers/{world.customer_a.id}/compliance-baselines/",
            {"name": "Bad", "rules": [bad]},
            format="json",
        )
        .status_code
        == 400
    )

    preview = (
        world.client(world.engineer_a)
        .post(
            f"/api/v1/customers/{world.customer_a.id}/custom-reports/preview/",
            {"source": "script_values", "conditions": [{"field": "value", "op": "equals", "value": "Off"}]},
            format="json",
        )
        .json()
    )
    assert preview["count"] == counts["fail"] and all("Off" in r for r in preview["rows"])


def test_customers_see_their_collectors_for_rule_building(world, demo):  # noqa: F811
    make_collector(world, demo, ["BitLockerProtection"])
    rows = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/script-collectors/").json()
    assert [(r["label"], r["allowed_variables"]) for r in rows] == [("BitLocker", ["BitLockerProtection"])]
    assert (
        world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_b.id}/script-collectors/").json() == []
    )
    assert (
        world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_a.id}/script-collectors/").status_code
        == 404
    )
