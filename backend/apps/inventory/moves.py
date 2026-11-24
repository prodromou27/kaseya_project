"""Internal propose/review workflow. Approval never executes a VSA write; execution is a separate gated step."""

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit.services import record_event

from .models import Asset, GroupMoveRequest, GroupNode
from .queries import current_observations, stale_cutoff

POLICY_IMPACT = (
    "Moving a device may change inherited patch, security and automation policies. "
    "Destination effective policy inheritance cannot be established from this inventory. "
    "A reviewer must assess it in VSA before any separately authorized execution. "
    "Approval records a decision only, unless the reviewer chooses Approve and move, which also executes it in VSA X "
    "where an administrator has enabled execution."
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
    self_review = proposal.requested_by_id == user.id
    # Same rule as every other approval (product owner, 2026-11-22): one administrator may approve their own proposal
    # unless REQUIRE_SECOND_APPROVER is set. Always audited with self_approved.
    if self_review and settings.CATALOG_REQUIRE_SEPARATE_REVIEWER:
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
        metadata={"execution_enabled": False, "self_approved": self_review},
    )
    return proposal


DIRECT_REASON = "Moved directly by an administrator."


def move_now(customer: Any, user: Any, asset_id: Any, target_id: Any, reason: str, request: Any) -> GroupMoveRequest:
    """One step for administrators (product owner, 2026-11-24): record, approve and send the move to VSA X, then read
    the device back. Uses the same propose/review/execute steps, so every check and audit event still applies.

    Refused (nothing recorded) when executing moves is not available, or when the server requires a second approver.
    An engineer's open suggestion for the same device is reused when it has the same destination, otherwise it is
    closed as superseded.
    """
    from . import move_execution

    if settings.CATALOG_REQUIRE_SEPARATE_REVIEWER:
        raise ValidationError(
            {"move": "This server requires a second administrator (REQUIRE_SECOND_APPROVER). Suggest the move instead."}
        )
    asset = Asset.objects.select_related("integration_instance").filter(customer=customer, pk=asset_id).first()
    if asset is None:
        raise NotFound()
    ok, why = move_execution.availability(asset.integration_instance)
    if not ok:
        raise ValidationError({"move": f"Nothing was sent: {why}"})
    reason = (reason or "").strip() or DIRECT_REASON
    now = timezone.now()
    open_ones = GroupMoveRequest.objects.filter(customer=customer, asset_id=asset_id)
    reusable = (
        open_ones.filter(target_group_id=target_id)
        .filter(
            models.Q(state="pending", expires_at__gt=now)
            | models.Q(state="approved", execution__isnull=True)
            | models.Q(
                state="approved",
                execution__state="failed",
                execution__error_code__in=move_execution.RETRYABLE_ERRORS,
            )
        )
        .order_by("-created_at")
        .first()
    )
    for stale in open_ones.filter(state="pending", expires_at__gt=now).exclude(pk=getattr(reusable, "pk", None)):
        review(customer, user, stale.id, "rejected", "Superseded by a direct move by an administrator.", request)
    proposal = reusable or propose(customer, user, asset_id, target_id, reason, request)
    if proposal.state == "pending":
        proposal = review(customer, user, proposal.id, "approved", reason, request)
    elif (
        proposal.reviewed_at
        and proposal.reviewed_at + timedelta(hours=settings.GROUP_MOVE_EXECUTION_WINDOW_HOURS) <= now
    ):
        # An old approval cannot be executed; record a fresh one for the same device and destination.
        proposal = review(
            customer,
            user,
            propose(customer, user, asset_id, target_id, reason, request).id,
            "approved",
            reason,
            request,
        )
    move_execution.execute_move(customer, user, proposal.id, request)
    return GroupMoveRequest.objects.get(pk=proposal.pk)
