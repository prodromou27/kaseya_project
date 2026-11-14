"""Internal proposal/approval only. These tests never execute a vendor write."""

from datetime import timedelta

import pytest
from django.db import DatabaseError, transaction
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.inventory.models import AssetObservation, GroupMoveRequest, GroupNode

from .test_vsa1_hierarchy_network import env, synced  # noqa: F401 - shared synthetic fixtures

pytestmark = pytest.mark.django_db


def base(customer):
    return f"/api/v1/customers/{customer.id}/group-moves/"


def payload(world):
    observation = AssetObservation.objects.get(customer=world.customer_a, hostname="SHARED-NAME")
    target = GroupNode.objects.get(generation=observation.generation, external_id="52")
    return {
        "asset": str(observation.asset_id),
        "target_group": str(target.id),
        "reason": "Correct onboarding placement",
    }


def test_propose_independent_review_and_safe_replay(world, synced):  # noqa: F811
    body = payload(world)
    response = world.client(world.engineer_a).post(base(world.customer_a), body)
    assert response.status_code == 201, response.content
    proposal = response.json()
    assert proposal["execution_enabled"] is False and proposal["state"] == "pending"
    assert "inheritance cannot be established" in proposal["policy_impact"]
    reviewer = world.client(world.admin_a)
    url = f"{base(world.customer_a)}{proposal['id']}/review/"
    decision = {"decision": "approved", "reason": "Reviewed source and destination policies"}
    assert reviewer.post(url, decision).status_code == 200
    assert reviewer.post(url, decision).status_code == 200
    assert AuditEvent.objects.filter(action="group_move.approved", customer=world.customer_a).count() == 1
    assert reviewer.post(f"{base(world.customer_a)}{proposal['id']}/execute/").status_code == 404
    assert GroupMoveRequest.objects.get(pk=proposal["id"]).state == "approved"


def test_self_approval_refused_even_in_single_admin_mode(world, synced, settings):  # noqa: F811
    settings.CATALOG_REQUIRE_SEPARATE_REVIEWER = False
    client = world.client(world.admin_a)
    response = client.post(base(world.customer_a), payload(world))
    assert response.status_code == 201
    review = client.post(
        f"{base(world.customer_a)}{response.json()['id']}/review/",
        {"decision": "approved", "reason": "Self approval must never work"},
    )
    assert review.status_code == 400


def test_customer_and_permission_boundaries(world, synced):  # noqa: F811
    body = payload(world)
    assert world.client(world.viewer_a).post(base(world.customer_a), body).status_code == 404
    assert world.client(world.engineer_b).post(base(world.customer_a), {}).status_code == 404
    assert world.client(world.engineer_b).get(base(world.customer_a)).status_code == 404
    assert (
        world.client(world.engineer_b).get(f"{base(world.customer_b)}options/", {"asset": body["asset"]}).status_code
        == 404
    )
    proposal = world.client(world.engineer_a).post(base(world.customer_a), body).json()
    assert (
        world.client(world.engineer_a).post(f"{base(world.customer_a)}{proposal['id']}/review/", {}).status_code == 404
    )
    assert world.client(world.engineer_b).get(f"{base(world.customer_b)}{proposal['id']}/").status_code == 404


def test_target_and_input_validation(world, synced):  # noqa: F811
    client = world.client(world.engineer_a)
    body = payload(world)
    assert client.post(base(world.customer_a), {**body, "reason": "short"}).status_code == 400
    assert client.post(base(world.customer_a), {**body, "asset": "invalid"}).status_code == 400
    foreign = GroupNode.objects.filter(customer=world.customer_b).first()
    assert client.post(base(world.customer_a), {**body, "target_group": str(foreign.id)}).status_code == 400
    observation = AssetObservation.objects.get(asset_id=body["asset"])
    current_group = GroupNode.objects.get(generation=observation.generation, external_id=observation.group_external_id)
    assert client.post(base(world.customer_a), {**body, "target_group": str(current_group.id)}).status_code == 400
    assert not GroupMoveRequest.objects.exists()


def test_expired_proposal_cannot_be_approved(world, synced, monkeypatch):  # noqa: F811
    created = world.client(world.engineer_a).post(base(world.customer_a), payload(world)).json()
    later = timezone.now() + timedelta(days=2)
    monkeypatch.setattr(timezone, "now", lambda: later)
    response = world.client(world.admin_a).post(
        f"{base(world.customer_a)}{created['id']}/review/",
        {"decision": "approved", "reason": "Review after expiry must fail"},
    )
    assert response.status_code == 400
    assert GroupMoveRequest.objects.get(pk=created["id"]).state == "pending"


def test_pending_duplicate_is_rejected(world, synced):  # noqa: F811
    client = world.client(world.engineer_a)
    assert client.post(base(world.customer_a), payload(world)).status_code == 201
    assert client.post(base(world.customer_a), payload(world)).status_code == 400
    assert GroupMoveRequest.objects.count() == 1


def test_proposal_content_and_final_decision_are_immutable(world, synced):  # noqa: F811
    created = world.client(world.engineer_a).post(base(world.customer_a), payload(world)).json()
    proposal = GroupMoveRequest.objects.get(pk=created["id"])
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        GroupMoveRequest.objects.filter(pk=proposal.id).update(reason="Replace an already submitted reason")
    with pytest.raises(DatabaseError, match="source mismatch"), transaction.atomic():
        GroupMoveRequest.objects.filter(pk=proposal.id).update(customer=world.customer_b)
    decision = {"decision": "rejected", "reason": "Destination policy needs more review"}
    response = world.client(world.admin_a).post(f"{base(world.customer_a)}{proposal.id}/review/", decision)
    assert response.status_code == 200
    with pytest.raises(DatabaseError, match="immutable"), transaction.atomic():
        GroupMoveRequest.objects.filter(pk=proposal.id).update(review_reason="Change the final review outcome")


def test_options_and_no_vendor_write_action(world, synced):  # noqa: F811
    client = world.client(world.engineer_a)
    options = client.get(f"{base(world.customer_a)}options/", {"asset": payload(world)["asset"]})
    assert options.status_code == 200 and options.json()["execution_enabled"] is False
    assert all(group["external_id"] != "51" for group in options.json()["groups"])
    assert client.get(f"{base(world.customer_a)}options/", {"asset": "invalid"}).status_code == 400
