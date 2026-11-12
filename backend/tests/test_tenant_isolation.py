"""P0-05 tenant authorization. TESTING.md AUTH-02..05; P0 gate: a user with Customer A cannot access
Customer B via list, detail, search, guessed UUID, report, async job or artifact."""

from __future__ import annotations

import uuid

import pytest

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.audit.models import AuditEvent
from apps.audit.services import record_event
from apps.customers.models import Customer, CustomerMembership
from apps.reporting.models import ReportRun
from apps.reporting.services import generate

from .factories import MappingFactory, MembershipFactory, role

pytestmark = pytest.mark.django_db


def _codes(resp) -> list[str]:
    return [c["code"] for c in resp.json()["results"]]


# ---------------------------------------------------------------- list / search / detail


def test_member_lists_only_assigned_customers(world):
    assert _codes(world.client(world.engineer_a).get("/api/v1/customers/")) == ["ACME"]
    assert _codes(world.client(world.engineer_b).get("/api/v1/customers/")) == ["BETA"]
    assert _codes(world.client(world.outsider).get("/api/v1/customers/")) == []
    assert sorted(_codes(world.client(world.super_admin).get("/api/v1/customers/"))) == ["ACME", "BETA"]


def test_search_cannot_reveal_other_customer(world):
    client = world.client(world.engineer_a)
    resp = client.get("/api/v1/customers/", {"search": "Beta"})
    assert resp.json()["count"] == 0 and resp.json()["results"] == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/customers/{b}/",
        "/api/v1/customers/{b}/memberships/",
        "/api/v1/customers/{b}/mappings/",
        "/api/v1/customers/{b}/audit-events/",
        "/api/v1/customers/{b}/reports/",
    ],
)
def test_cross_customer_routes_return_404_without_metadata(world, path):
    """AUTH-02: Customer B ID in route → 404, body contains no name/count/metadata of B."""
    resp = world.client(world.admin_a).get(path.format(b=world.customer_b.id))
    assert resp.status_code == 404
    body = resp.content.decode()
    assert "Beta" not in body and "BETA" not in body and "count" not in body
    assert resp.json()["error"]["code"] == "not_found"


def test_unknown_and_unauthorised_ids_are_indistinguishable(world):
    client = world.client(world.engineer_a)
    unauthorised = client.get(f"/api/v1/customers/{world.customer_b.id}/")
    unknown = client.get(f"/api/v1/customers/{uuid.uuid4()}/")
    malformed = client.get("/api/v1/customers/not-a-uuid/")
    assert unauthorised.status_code == unknown.status_code == malformed.status_code == 404
    strip = lambda r: {k: v for k, v in r.json()["error"].items() if k != "request_id"}  # noqa: E731
    assert strip(unauthorised) == strip(unknown) == strip(malformed)


def test_denials_are_audited(world):
    world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_b.id}/")
    event = AuditEvent.objects.get(action="authz.denied", actor=world.engineer_a)
    assert event.outcome == "denied" and event.target_id == str(world.customer_b.id)


def test_membership_alone_does_not_grant_cross_customer_capability(world):
    MembershipFactory(customer=world.customer_b, user=world.engineer_a, role=role("admin"))
    scope.invalidate_cache(world.engineer_a)
    assert not scope.has_global_capability(world.engineer_a, Cap.SYSTEM_CROSS_CUSTOMER)
    assert world.client(world.engineer_a).get("/api/v1/audit-events/").status_code == 403


def test_archived_and_suspended_customers_hidden_from_members(world):
    Customer.objects.filter(pk=world.customer_a.pk).update(status=Customer.Status.SUSPENDED)
    client = world.client(world.engineer_a)
    assert _codes(client.get("/api/v1/customers/")) == []
    assert client.get(f"/api/v1/customers/{world.customer_a.id}/").status_code == 404
    assert world.client(world.super_admin).get(f"/api/v1/customers/{world.customer_a.id}/").status_code == 200


def test_revoked_membership_loses_access_immediately(world):
    """AUTH-05 (portal side): revocation takes effect on the next request."""
    client = world.client(world.engineer_a)
    assert client.get(f"/api/v1/customers/{world.customer_a.id}/").status_code == 200
    CustomerMembership.objects.filter(user=world.engineer_a).update(is_active=False)
    assert client.get(f"/api/v1/customers/{world.customer_a.id}/").status_code == 404
    assert _codes(client.get("/api/v1/customers/")) == []


def test_customer_supplied_in_body_is_ignored(world):
    """Customer comes from the URL + DB, never the body: proposing a mapping 'for' B via body lands on A."""
    inst = MappingFactory(customer=world.customer_a).integration_instance
    resp = world.client(world.admin_a).post(
        f"/api/v1/customers/{world.customer_a.id}/mappings/",
        {"integration_instance": str(inst.id), "external_org_id": "4242", "customer": str(world.customer_b.id)},
    )
    assert resp.status_code == 201
    assert resp.json()["customer"]["id"] == str(world.customer_a.id)


def test_scope_queryset_fails_closed_for_anonymous_and_inactive(world):
    from django.contrib.auth.models import AnonymousUser

    qs = Customer.objects.all()
    assert scope.scope_queryset(qs, AnonymousUser(), Cap.CUSTOMER_READ, "self").count() == 0
    world.engineer_a.is_active = False
    assert scope.scope_queryset(qs, world.engineer_a, Cap.CUSTOMER_READ, "self").count() == 0


# ---------------------------------------------------------------- audit log isolation


def test_customer_audit_log_contains_only_that_customer(world):
    record_event(action="test.a", outcome="success", customer=world.customer_a)
    record_event(action="test.b", outcome="success", customer=world.customer_b)
    data = world.client(world.admin_a).get(f"/api/v1/customers/{world.customer_a.id}/audit-events/").json()
    actions = {e["action"] for e in data["results"]}
    assert "test.a" in actions and "test.b" not in actions


def test_engineer_and_viewer_cannot_read_customer_audit(world):
    for user in (world.engineer_a, world.viewer_a):
        assert world.client(user).get(f"/api/v1/customers/{world.customer_a.id}/audit-events/").status_code == 404


# ---------------------------------------------------------------- reports: export / job / artifact


def _make_report(world, client, customer, django_capture_on_commit_callbacks):
    record_event(action="seed.event", outcome="success", customer=customer)
    with django_capture_on_commit_callbacks(execute=True):
        resp = client.post(f"/api/v1/customers/{customer.id}/reports/", {"report_type": "customer_audit_log"})
    assert resp.status_code == 202, resp.content
    return ReportRun.objects.get(pk=resp.json()["id"])


def test_report_artifact_of_other_customer_denied_even_with_valid_id(world, django_capture_on_commit_callbacks):
    """AUTH-03."""
    run = _make_report(world, world.client(world.super_admin), world.customer_b, django_capture_on_commit_callbacks)
    run.refresh_from_db()
    assert run.state == "completed"
    client = world.client(world.admin_a)
    assert client.get(f"/api/v1/reports/{run.id}/").status_code == 404
    assert client.get(f"/api/v1/reports/{run.id}/download/").status_code == 404
    assert client.get(f"/api/v1/customers/{world.customer_a.id}/reports/").json()["results"] == []
    # Owner customer's engineer still lacks audit.read → cannot see an audit report either.
    assert world.client(world.engineer_b).get(f"/api/v1/reports/{run.id}/download/").status_code == 404


def test_report_download_requires_fresh_authorization(world, django_capture_on_commit_callbacks):
    """AUTH-05 / REP-03: download denied after membership revocation."""
    client = world.client(world.admin_a)
    run = _make_report(world, client, world.customer_a, django_capture_on_commit_callbacks)
    assert client.get(f"/api/v1/reports/{run.id}/download/").status_code == 200
    CustomerMembership.objects.filter(user=world.admin_a).update(is_active=False)
    assert client.get(f"/api/v1/reports/{run.id}/download/").status_code == 404


def test_job_for_wrong_customer_is_rejected_in_worker(world):
    """AUTH-04: a run crafted for Customer B on behalf of a Customer-A user is refused before any data read."""
    run = ReportRun.objects.create(
        customer=world.customer_b, requested_by=world.admin_a, report_type="customer_audit_log", filters_hash="x"
    )
    result = generate(str(run.id))
    assert result.state == "failed" and result.error_code == "authorization_revoked"
    assert not hasattr(result, "artifact") or result.artifact is None
    assert AuditEvent.objects.filter(action="report.generated", outcome="denied", target_id=str(run.id)).exists()


def test_pending_job_blocked_after_revocation(world, django_capture_on_commit_callbacks):
    """AUTH-05: membership revoked between request and execution → job refuses."""
    client = world.client(world.admin_a)
    resp = client.post(f"/api/v1/customers/{world.customer_a.id}/reports/", {"report_type": "customer_audit_log"})
    run_id = resp.json()["id"]  # on_commit not executed: job still queued
    CustomerMembership.objects.filter(user=world.admin_a).update(is_active=False)
    assert generate(run_id).error_code == "authorization_revoked"


def test_viewer_cannot_export_unless_granted(world):
    client = world.client(world.viewer_a)
    assert client.get(f"/api/v1/customers/{world.customer_a.id}/reports/").status_code == 404
    CustomerMembership.objects.filter(user=world.viewer_a).update(can_export=True)
    scope.invalidate_cache(world.viewer_a)
    assert world.client(world.viewer_a).get(f"/api/v1/customers/{world.customer_a.id}/reports/").status_code == 200


def test_engineer_cannot_request_audit_report(world):
    resp = world.client(world.engineer_a).post(
        f"/api/v1/customers/{world.customer_a.id}/reports/", {"report_type": "customer_audit_log"}
    )
    assert resp.status_code == 403
    assert not ReportRun.objects.exists()


def test_report_filters_are_allowlisted(world):
    resp = world.client(world.admin_a).post(
        f"/api/v1/customers/{world.customer_a.id}/reports/",
        {"report_type": "customer_audit_log", "filters": {"customer_id": str(world.customer_b.id)}},
    )
    assert resp.status_code == 400
    assert "Unknown filter keys" in str(resp.json())
