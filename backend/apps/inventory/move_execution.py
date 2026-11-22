"""VSA5-EXEC: execute an approved group move in VSA X, at most once, and confirm it by reading the device back.

Order of guarantees:

1. Execution is available only with the server switch, the integration switch and a separate write token
   (``apps.integrations.vsa.writer.availability``).
2. Only an *approved*, not-yet-executed proposal whose approval is recent, executed by someone other than the
   requester, while the current inventory still shows the device in the source group and the destination group active.
3. The attempt row (``sending``) is committed before the request: one proposal = one PUT, even across crashes.
4. Timeouts, 5xx and unreadable answers become ``unknown``; acceptance without a matching read-back is ``unverified``.
   Both are resolved only by ``verify`` (a GET), never by sending again.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from apps.audit.services import record_event
from apps.integrations.vsa.writer import (
    MoveNotAvailable,
    MoveOutcomeUnknown,
    MoveRejected,
    VsaMoveWriter,
    availability,
)

from .models import GroupMoveExecution, GroupMoveRequest, GroupNode
from .queries import current_observations, stale_cutoff

logger = logging.getLogger("portal.inventory")

VERIFIABLE = ("unknown", "unverified", "sending")
SENDING_GRACE = timedelta(minutes=2)


def execution_status(proposal: GroupMoveRequest) -> tuple[bool, str]:
    """(can be executed now, reason when not) - for the UI; ``execute`` re-checks everything."""
    ok, reason = availability(proposal.asset.integration_instance)
    if not ok:
        return False, reason
    if proposal.state != "approved":
        return False, "Only approved proposals can be executed."
    if hasattr(proposal, "execution"):
        return False, "Already executed."
    if proposal.reviewed_at and proposal.reviewed_at + _window() <= timezone.now():
        return False, "The approval is too old. Submit a new proposal against fresh inventory."
    return True, ""


def _window() -> timedelta:
    return timedelta(hours=settings.GROUP_MOVE_EXECUTION_WINDOW_HOURS)


def _audit(action: str, outcome: str, user: Any, proposal: GroupMoveRequest, request: Any, **meta: Any) -> None:
    record_event(
        action=action,
        outcome=outcome,
        actor=user,
        customer=proposal.customer,
        target_type="group_move_request",
        target_id=str(proposal.id),
        request=request,
        metadata={"asset_id": str(proposal.asset_id), **meta},
    )


def _start(customer: Any, user: Any, proposal_id: Any, request: Any) -> tuple[GroupMoveRequest, GroupMoveExecution]:
    with transaction.atomic():
        proposal = (
            GroupMoveRequest.objects.select_for_update()
            .select_related("asset__integration_instance", "target_group", "customer")
            .filter(customer=customer, pk=proposal_id)
            .first()
        )
        if proposal is None:
            raise NotFound()
        if proposal.state != "approved":
            raise ValidationError({"execute": "Only approved proposals can be executed."})
        if GroupMoveExecution.objects.filter(proposal=proposal).exists():
            raise ValidationError({"execute": "This move was already sent to VSA X. Use Verify to check it."})
        if proposal.requested_by_id == user.id and settings.CATALOG_REQUIRE_SEPARATE_REVIEWER:
            raise ValidationError({"execute": "The person who proposed the move cannot execute it."})
        if proposal.reviewed_at is None or proposal.reviewed_at + _window() <= timezone.now():
            raise ValidationError(
                {"execute": "The approval is too old. Submit a new proposal against fresh inventory."}
            )
        observation = current_observations(customer.id).filter(asset_id=proposal.asset_id).first()
        if observation is None or observation.generation.published_at < stale_cutoff():
            raise ValidationError({"execute": "Inventory is missing or stale. Synchronize before executing."})
        if observation.group_external_id != proposal.source_group_id:
            raise ValidationError(
                {"execute": "The device is no longer in the group it was in when proposed. Nothing was sent."}
            )
        if not GroupNode.objects.filter(
            customer_id=customer.id,
            generation_id=observation.generation_id,
            external_id=proposal.target_group.external_id,
            organization_external_id=observation.organization_external_id,
            is_active=True,
        ).exists():
            raise ValidationError({"execute": "The destination group is no longer active in VSA X. Nothing was sent."})
        execution = GroupMoveExecution.objects.create(
            proposal=proposal, customer=customer, executed_by=user, started_at=timezone.now()
        )
        _audit(
            "group_move.execute_started",
            "success",
            user,
            proposal,
            request,
            target_group_id=proposal.target_group.external_id,
            source_group_id=proposal.source_group_id,
            by_requester=proposal.requested_by_id == user.id,
        )
    return proposal, execution


def _read_back(proposal: GroupMoveRequest) -> str | None:
    try:
        from apps.integrations.vsa.adapter import VsaXAdapter

        group_id, _ = VsaXAdapter(proposal.asset.integration_instance).get_device_group(proposal.asset.external_id)
    except Exception:  # read-back is best-effort; the state stays unverified/unknown
        logger.warning("group_move_read_back_failed", extra={"proposal": str(proposal.id)})
        return None
    return group_id


def execute_move(
    customer: Any, user: Any, proposal_id: Any, request: Any, *, transport: Any = None
) -> GroupMoveExecution:
    probe = GroupMoveRequest.objects.select_related("asset__integration_instance").filter(
        customer=customer, pk=proposal_id
    )
    found = probe.first()
    if found is None:
        raise NotFound()
    try:
        writer = VsaMoveWriter(found.asset.integration_instance, transport=transport)
    except MoveNotAvailable as exc:
        raise ValidationError({"execute": str(exc)}) from exc
    proposal, execution = _start(customer, user, proposal_id, request)
    target = proposal.target_group.external_id
    try:
        writer.move(proposal.asset.external_id, target)
    except MoveRejected as exc:
        execution.state, execution.http_status, execution.error_code = (
            "failed",
            exc.status,
            f"rejected_http_{exc.status}",
        )
    except MoveOutcomeUnknown as exc:
        execution.state, execution.http_status, execution.error_code = "unknown", exc.status, exc.code[:64]
    except Exception:  # anything else after the attempt row exists: never claim either way
        logger.exception("group_move_execute_error", extra={"proposal": str(proposal.id)})
        execution.state, execution.error_code = "unknown", "internal_error"
    else:
        execution.http_status = 200
        observed = _read_back(proposal)
        execution.observed_group_id = observed or ""
        if observed == target:
            execution.state, execution.verified_at = "succeeded", timezone.now()
        else:
            execution.state = "unverified"
    execution.finished_at = timezone.now()
    execution.save()
    _audit(
        f"group_move.execute_{execution.state}",
        "success" if execution.state == "succeeded" else "failure",
        user,
        proposal,
        request,
        http_status=execution.http_status,
        error_code=execution.error_code,
        target_group_id=target,
    )
    return execution


def verify(customer: Any, user: Any, proposal_id: Any, request: Any) -> GroupMoveExecution:
    """Read the device back (GET only) to resolve an unknown/unverified outcome. Never sends the move again."""
    execution = (
        GroupMoveExecution.objects.select_related(
            "proposal__asset__integration_instance", "proposal__target_group", "proposal__customer"
        )
        .filter(customer=customer, proposal_id=proposal_id)
        .first()
    )
    if execution is None:
        raise NotFound()
    if execution.state not in VERIFIABLE:
        return execution
    if execution.state == "sending" and timezone.now() - execution.started_at < SENDING_GRACE:
        raise ValidationError({"verify": "The move is still being sent. Try again in a minute."})
    proposal = execution.proposal
    observed = _read_back(proposal)
    if observed is None:
        raise ValidationError({"verify": "VSA X could not be read. Try again later."})
    previous = execution.state
    execution.observed_group_id = observed
    if observed == proposal.target_group.external_id:
        execution.state, execution.verified_at = "succeeded", timezone.now()
    elif observed == proposal.source_group_id:
        execution.state, execution.error_code = "failed", "still_in_source_group"
        execution.verified_at = timezone.now()
    execution.finished_at = execution.finished_at or timezone.now()
    execution.save()
    _audit(
        "group_move.verified",
        "success",
        user,
        proposal,
        request,
        previous_state=previous,
        state=execution.state,
        observed_group_id=observed,
    )
    return execution
