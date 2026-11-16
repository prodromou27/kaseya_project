"""AUT-01 automation health: workflow runs attributed only through the customer's own devices. Fixture data."""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.automation.collector import collect
from apps.automation.models import AutomationCollection, WorkflowExecution
from apps.customers.models import CustomerSourceMapping
from apps.integrations import sync
from apps.integrations.http import VendorClientError
from apps.integrations.models import IntegrationInstance

pytestmark = pytest.mark.django_db


@pytest.fixture
def demo(world, django_capture_on_commit_callbacks):
    inst = IntegrationInstance.objects.create(
        name="Demo VSA",
        provider="vsa_x",
        base_url="https://vsa-demo.invalid",
        is_fixture=True,
        enabled=True,
        max_rps=50,
    )
    mapping = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="1001",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )
    run, _ = sync.request_sync(mapping, requested_by=world.engineer_a)
    assert sync.execute(str(run.id)).state == "completed"
    return inst


def test_workflow_runs_are_reported_per_customer_device(world, demo):
    body = world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/automation/", {"days": 7}).json()
    assert body["totals"] == {"runs": 28, "failed": 4, "devices_with_failures": 4}
    clean = next(w for w in body["workflows"] if w["name"] == "DEMO Clean temp files (fixture)")
    assert clean["runs"] + next(w for w in body["workflows"] if w["workflow_id"] == "502")["runs"] == 28
    assert len(body["executions"]) == 4 and all(e["status"] == "Failed" for e in body["executions"])
    assert body["executions"][0]["failed_step"] == "Script exited with code 1 (fixture)"
    assert body["executions"][0]["hostname"].startswith("DEMOA-")
    assert body["collection"][0]["status"] == "ok"
    assert "task runs" in body["task_limitation"]
    # The server-targeted run is never attributed to a customer.
    assert WorkflowExecution.objects.filter(target_type="Server", customer__isnull=True).count() == 1


def test_other_customers_see_nothing_and_catalog_is_super_admin_only(world, demo):
    assert world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_a.id}/automation/").status_code == 404
    b = world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_b.id}/automation/").json()
    assert b["totals"]["runs"] == 0
    assert world.client(world.engineer_a).get("/api/v1/automation/catalog/").status_code == 403
    catalog = world.client(world.super_admin).get("/api/v1/automation/catalog/").json()
    assert len(catalog["workflows"]) == 3 and len(catalog["tasks"]) == 2
    assert next(t for t in catalog["tasks"] if t["id"] == "601")["scheduled"] is True


def test_collection_is_throttled_and_tolerates_missing_permission(world, demo):
    assert collect(demo, adapter=None) == "skipped"  # collected moments ago by the sync

    class NoPermission:
        def list_workflows(self):
            raise VendorClientError("forbidden", status=403)

    assert collect(demo, NoPermission(), force=True) == "not_permitted"
    state = AutomationCollection.objects.get(integration_instance=demo)
    assert state.error_code == "http_403" and state.last_success_at is not None  # earlier success kept


def test_new_workflow_failures_raise_an_alert(world, demo):
    from apps.alerts.engine import evaluate_customer
    from apps.alerts.models import Alert

    resp = world.client(world.engineer_a).post(
        "/api/v1/alert-subscriptions/",
        {"customer": str(world.customer_a.id), "kind": "workflow_failed", "params": {}},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    assert evaluate_customer(world.customer_a.id) == 0  # existing failures were primed
    existing = WorkflowExecution.objects.filter(customer=world.customer_a, status="Failed").first()
    WorkflowExecution.objects.create(
        integration_instance=demo,
        external_id="99999",
        workflow_external_id="501",
        target_type="Device",
        target_id=existing.target_id,
        asset=existing.asset,
        customer=world.customer_a,
        status="Failed",
        created_at=timezone.now(),
    )
    assert evaluate_customer(world.customer_a.id) == 1
    alert = Alert.objects.get(user=world.engineer_a)
    assert alert.link == "/automation" and alert.body.startswith("DEMOA-")
