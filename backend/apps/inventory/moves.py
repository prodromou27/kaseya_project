"""Internal propose/review workflow. Approval never executes a VSA write."""

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit.services import record_event

from .models import Asset, GroupMoveRequest, GroupNode
from .queries import current_observations, stale_cutoff

POLICY_IMPACT = (
    "Moving a device may change inherited patch, security and automation policies. "
    "Destination effective policy inheritance cannot be established from this inventory. "
    "A reviewer must assess it in VSA before any separately authorized execution. "
    "Approval here records a proposal only; execution and vendor write credentials are disabled."
)


def options(customer_id: Any, asset_id: Any) -> tuple[Any, Any]:
    observation = current_observations(customer_id).filter(asset_id=asset_id).first()
    if observation is None:
        raise NotFound()
    if not observation.group_external_id:
        raise ValidationError({"asset": "Source group identity is not reported; a move cannot be proposed."})
    if observation.generation.published_at < stale_cutoff():
        raise ValidationError({"asset": "Source inventory is stale. Synchronize before proposing a change."})
    groups = (
        GroupNode.objects.filter(
            customer_id=customer_id,
            generation_id=observation.generation_id,
            organization_external_id=observation.organization_external_id,
            is_active=True,
        )
        .exclude(external_id=observation.group_external_id)
        .order_by("name", "external_id")
    )
    return observation, groups


@transaction.atomic
def propose(customer: Any, user: Any, asset_id: Any, target_id: Any, reason: str, request: Any) -> GroupMoveRequest:
    # Serialize concurrent proposals for this customer's device; a client cannot lock another customer's asset.
    if not Asset.objects.select_for_update().filter(customer=customer, pk=asset_id).exists():
        raise NotFound()
    observation, groups = options(customer.id, asset_id)
    target = groups.filter(pk=target_id).first()
    if target is None:
        raise ValidationError(
            {"target_group": "Choose an active destination in the same customer, VSA source and organization."}
        )
    if GroupMoveRequest.objects.filter(
        customer=customer, asset_id=asset_id, state="pending", expires_at__gt=timezone.now()
    ).exists():
        raise ValidationError({"asset": "This device already has a pending move proposal."})
    proposal = GroupMoveRequest.objects.create(
        customer=customer,
        asset_id=asset_id,
        generation=observation.generation,
        target_group=target,
        source_group_id=observation.group_external_id,
        source_group_name=observation.group_name,
        device_name=observation.hostname,
        reason=reason,
        policy_impact=POLICY_IMPACT,
        requested_by=user,
        expires_at=timezone.now() + timedelta(hours=24),
    )
    record_event(
        action="group_move.proposed",
        outcome="success",
        actor=user,
        customer=customer,
        target_type="group_move_request",
        target_id=str(proposal.id),
        request=request,
        metadata={"asset_id": str(asset_id), "target_group_id": target.external_id, "execution_enabled": False},
    )
    return proposal


@transaction.atomic
def review(customer: Any, user: Any, proposal_id: Any, decision: str, reason: str, request: Any) -> GroupMoveRequest:
    proposal = GroupMoveRequest.objects.select_for_update().filter(customer=customer, pk=proposal_id).first()
    if proposal is None:
        raise NotFound()
    if proposal.requested_by_id == user.id:
        raise ValidationError({"review": "A different authorized administrator must review this request."})
    if proposal.state != "pending":
        if proposal.state == decision and proposal.reviewed_by_id == user.id:
            return proposal  # safe replay of the same review
        raise ValidationError({"review": "The request already has a final decision."})
    if decision == "approved":
        if proposal.expires_at <= timezone.now():
            raise ValidationError({"review": "The proposal expired. Submit a new proposal against fresh inventory."})
        observation, groups = options(customer.id, proposal.asset_id)
        if (
            observation.generation_id != proposal.generation_id
            or not groups.filter(pk=proposal.target_group_id).exists()
        ):
            raise ValidationError(
                {"review": "The inventory changed. Submit a new proposal against the current snapshot."}
            )
    proposal.state, proposal.reviewed_by = decision, user
    proposal.review_reason, proposal.reviewed_at = reason, timezone.now()
    proposal.save(update_fields=["state", "reviewed_by", "review_reason", "reviewed_at"])
    record_event(
        action=f"group_move.{decision}",
        outcome="success",
        actor=user,
        customer=customer,
        target_type="group_move_request",
        target_id=str(proposal.id),
        request=request,
        metadata={"execution_enabled": False},
    )
    return proposal
