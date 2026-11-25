"""Custom field assignment jobs: create -> (resolve) -> preview -> confirm -> (approve) -> execute -> report.

The two input methods (selected devices, pasted/uploaded list) produce the same items and use this one engine.
Every write is confirmed by a person, re-checked immediately before sending, sent once and verified by reading the
value back from VSA X, which stays the source of truth.
"""

from __future__ import annotations

import logging
import time
from collections import Counter
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.accounts import scope
from apps.accounts.roles import Cap
from apps.audit.services import record_event

from . import definitions
from .models import AssignmentItem, AssignmentJob, CustomFieldDefinition

logger = logging.getLogger("portal.customfields")
Item, Job = AssignmentItem, AssignmentJob
BULK_USAGE_THRESHOLD = 25
READ_BACK_DELAYS = (0, 2, 5)  # seconds before each read-back attempt (eventual consistency, bounded)
RATE_LIMIT_DELAYS = (5, 15, 30)
STALE_RUN = timedelta(minutes=10)
ACTIVE = (Job.State.QUEUED, Job.State.RUNNING, Job.State.AWAITING_APPROVAL)
sleep = time.sleep  # replaced in tests


def _audit(job: Job, action: str, user: Any = None, request: Any = None, outcome: str = "success", **meta: Any) -> None:
    record_event(
        action=f"custom_field.{action}",
        outcome=outcome,
        actor=user,
        customer=job.customer,
        target_type="custom_field_job",
        target_id=str(job.id),
        request=request,
        metadata={"field_id": job.field.external_id, "field": job.field.name, **meta},
    )


# ------------------------------------------------------------------------------------------------ create


def create(
    customer: Any,
    user: Any,
    field: CustomFieldDefinition,
    *,
    value: str,
    source: str,
    items: list[dict[str, Any]],
    filename: str = "",
    retry_of: Job | None = None,
    only_if_empty: bool = False,
    request: Any = None,
) -> Job:
    ok, reason = definitions.eligibility(field)
    if not ok:
        raise serializers.ValidationError({"field": f"This field cannot be edited: {reason}."})
    per_device = any(i.get("requested_value") for i in items)
    if value:
        value = _normalise_or_400(field, value)
    elif not per_device:
        raise serializers.ValidationError({"value": "Enter a value."})
    if only_if_empty and per_device:
        raise serializers.ValidationError({"only_if_empty": "Filling empty values needs one value for every device."})
    with transaction.atomic():
        job = Job.objects.create(
            customer=customer,
            integration_instance=field.integration_instance,
            field=field,
            value=value,
            per_device_values=per_device,
            only_if_empty=only_if_empty,
            source=source,
            source_filename=filename[:255],
            retry_of=retry_of,
            created_by=user,
        )
        Item.objects.bulk_create(
            [
                Item(
                    job=job,
                    position=i["position"],
                    input_identifier=i.get("input_identifier", "")[:255],
                    input_kind=i.get("input_kind", "")[:16],
                    input_row=i.get("input_row"),
                    match_status=i["match_status"],
                    match_note=i.get("match_note", "")[:255],
                    candidates=i.get("candidates", []),
                    asset_id=i.get("asset_id"),
                    device_external_id=i.get("device_external_id", ""),
                    hostname=i.get("hostname", "")[:255],
                    site=(i.get("site") or "")[:255],
                    group=(i.get("group") or "")[:255],
                    requested_value=i.get("requested_value", ""),
                    included=i["match_status"] == Item.Match.MATCHED,
                    result=Item.Result.PENDING if i["match_status"] == Item.Match.MATCHED else Item.Result.NOT_RUN,
                )
                for i in items
            ],
            batch_size=1000,
        )
        _count(job)
    _audit(job, "job_created", user, request, source=source, items=len(items), value=value, only_if_empty=only_if_empty)
    return job


def _normalise_or_400(field: CustomFieldDefinition, raw: str) -> str:
    try:
        return definitions.normalise(field.type, raw)
    except definitions.ValueInvalid as exc:
        raise serializers.ValidationError({"value": str(exc)}) from exc


def _count(job: Job) -> None:
    items = job.items.all()
    job.counts = {
        "items": items.count(),
        "match": dict(Counter(items.values_list("match_status", flat=True))),
        "action": dict(Counter(items.filter(included=True).exclude(action="").values_list("action", flat=True))),
        "result": dict(Counter(items.values_list("result", flat=True))),
        "to_change": items.filter(included=True, action__in=(Item.Action.ASSIGN, Item.Action.UPDATE)).count(),
        # An overwrite replaces a non-empty value; filling an empty device-level value is not one.
        "updates": items.filter(included=True, action=Item.Action.UPDATE).exclude(current_value="").count(),
    }
    job.save(update_fields=["counts"])


def _editable(job: Job) -> None:
    if job.state not in (Job.State.DRAFT, Job.State.PREVIEWED):
        raise serializers.ValidationError({"state": "This job can no longer be changed."})


def resolve(job: Job, item_id: str, asset_id: str | None, user: Any) -> Item:
    """Pick one of a 'multiple matches' item's candidates (or exclude the line)."""
    _editable(job)
    item = job.items.get(pk=item_id)
    if item.match_status != Item.Match.MULTIPLE:
        raise serializers.ValidationError({"item": "Only lines with several matching devices need a choice."})
    if asset_id is None:
        item.included = False
        item.save(update_fields=["included"])
    else:
        chosen = next((c for c in item.candidates if c["asset_id"] == str(asset_id)), None)
        if chosen is None:
            raise serializers.ValidationError({"asset": "Choose one of the listed devices."})
        from .matching import match_selected

        (fresh,) = match_selected(job.customer, job.integration_instance, [chosen["asset_id"]])
        taken = job.items.filter(asset_id=chosen["asset_id"], included=True).exclude(pk=item.pk).exists()
        if fresh["match_status"] != Item.Match.MATCHED or taken:
            raise serializers.ValidationError(
                {"asset": "That device cannot be used (not a workstation or already listed)."}
            )
        for key in ("device_external_id", "hostname", "site", "group"):
            setattr(item, key, fresh.get(key) or "")
        item.asset_id, item.match_status, item.included = chosen["asset_id"], Item.Match.MATCHED, True
        item.match_note, item.result = "Chosen by the engineer", Item.Result.PENDING
        item.save()
    _invalidate_preview(job)
    return item


def set_included(job: Job, item_ids: list[str], included: bool) -> int:
    _editable(job)
    n = job.items.filter(pk__in=item_ids, match_status=Item.Match.MATCHED).update(included=included)
    _invalidate_preview(job)
    return n


def _invalidate_preview(job: Job) -> None:
    if job.state == Job.State.PREVIEWED:
        job.state, job.previewed_at = Job.State.DRAFT, None
        job.save(update_fields=["state", "previewed_at"])
    _count(job)


# ------------------------------------------------------------------------------------------------ preview


def request_preview(job: Job, user: Any, request: Any = None) -> Job:
    _editable(job)
    if not job.items.filter(included=True, match_status=Item.Match.MATCHED).exists():
        raise serializers.ValidationError({"items": "No matched devices are included."})
    job.state, job.error_code = Job.State.PREVIEWING, ""
    job.save(update_fields=["state", "error_code"])
    from .tasks import preview_job

    transaction.on_commit(lambda: preview_job.delay(str(job.id)))
    return job


def run_preview(job_id: str, adapter: Any = None) -> Job:
    job = Job.objects.select_related("field", "integration_instance", "customer").get(pk=job_id)
    if job.state != Job.State.PREVIEWING:
        return job
    from apps.integrations.vsa.adapter import VsaXAdapter

    adapter = adapter or VsaXAdapter(job.integration_instance)
    field = job.field
    items = list(job.items.filter(included=True, match_status=Item.Match.MATCHED).order_by("position"))
    ok, reason = definitions.eligibility(field)
    live = _live_assets(job)
    usage: dict[str, str] | None = None
    if ok and len(items) > BULK_USAGE_THRESHOLD:
        try:
            usage = {
                str(r.get("ContextItemId")): str(r.get("Value") if r.get("Value") is not None else "")
                for r in adapter.custom_field_device_usage(field.external_id, max_pages=200)
            }
        except Exception:  # too many assignments or unavailable: fall back to one lookup per device
            usage = None
    for item in items:
        _preview_item(job, item, adapter, ok, reason, live, usage)
    job.state, job.previewed_at = Job.State.PREVIEWED, timezone.now()
    job.save(update_fields=["state", "previewed_at"])
    _count(job)
    _audit(job, "previewed", job.created_by, actions=job.counts.get("action"), to_change=job.counts.get("to_change"))
    return job


def _live_assets(job: Job) -> dict[str, bool]:
    """asset id -> still a workstation in the customer's current snapshot (and on this integration)."""
    from .matching import _rows

    return {str(r["asset_id"]): r["workstation"] for r in _rows(job.customer_id, job.integration_instance_id)}


def _device_level(adapter: Any, field_id: str, device: str) -> tuple[bool, str | None]:
    rows = adapter.custom_field_device_usage(field_id, device)
    hit = next((r for r in rows if str(r.get("ContextItemId")) == device), None)
    if hit is None:
        return False, None
    return True, str(hit.get("Value") if hit.get("Value") is not None else "")


def _preview_item(
    job: Job, item: Item, adapter: Any, ok: bool, reason: str, live: dict[str, bool], usage: dict[str, str] | None
) -> None:
    field = job.field
    item.current_value, item.current_source, item.device_assigned, item.action_note = None, "", None, ""
    if not ok:
        item.action, item.action_note = Item.Action.BLOCKED, f"Field cannot be edited: {reason}"
    elif not live.get(str(item.asset_id)):
        item.action, item.action_note = Item.Action.BLOCKED, "No longer a workstation in the current inventory"
    else:
        try:
            requested = definitions.normalise(field.type, item.requested_value or job.value)
        except definitions.ValueInvalid as exc:
            item.action, item.action_note = Item.Action.BLOCKED, f"Invalid value: {exc}"
            requested = None
        if requested is not None:
            item.requested_value = requested
            _classify(item, adapter, field, requested, usage, only_if_empty=job.only_if_empty)
    item.save()


def _empty(value: str | None) -> bool:
    return value is None or not str(value).strip()


def _classify(
    item: Item, adapter: Any, field: CustomFieldDefinition, requested: str, usage: dict | None, *, only_if_empty: bool
) -> None:
    """Assign / update / skip from the device-level assignment, then the effective (possibly inherited) value.

    ``only_if_empty`` (CFA-10, placeholder such as "TBD"): a device that already shows any value, set on the device or
    inherited from its organisation, site or group, is skipped and left unchanged.
    """
    device = item.device_external_id
    try:
        if usage is not None:
            assigned, current = (device in usage), usage.get(device)
        else:
            assigned, current = _device_level(adapter, field.external_id, device)
    except Exception:
        item.current_source, item.action = "unknown", Item.Action.REVIEW
        item.action_note = "The current assignment could not be read from VSA X"
        return
    item.device_assigned = assigned
    if assigned:
        item.current_value, item.current_source = current, "device"
        if definitions.same(field.type, current, requested):
            item.action, item.action_note = Item.Action.SKIP, "Already set on this device"
        elif only_if_empty and not _empty(current):
            item.action, item.action_note = Item.Action.SKIP, "Already has a value; left unchanged"
        elif _empty(current):
            item.action, item.action_note = Item.Action.UPDATE, "Fills the empty value on this device"
        else:
            item.action, item.action_note = Item.Action.UPDATE, "Overwrites the value set on this device"
        return
    try:
        effective = adapter.device_custom_field_value(device, field.external_id)
    except Exception:
        effective = "error"
    if effective == "error":
        item.current_source, item.action = "unknown", Item.Action.REVIEW
        item.action_note = "No device-level value; the inherited value could not be read"
    elif effective is None:
        item.current_source, item.action = "none", Item.Action.ASSIGN
    else:
        item.current_value = str(effective.get("Value") if effective.get("Value") is not None else "")
        item.current_source = "inherited"
        if definitions.same(field.type, item.current_value, requested):
            item.action, item.action_note = Item.Action.SKIP, "Already inherited from the organisation, site or group"
        elif only_if_empty and not _empty(item.current_value):
            item.action = Item.Action.SKIP
            item.action_note = "Has a value from the organisation, site or group; left unchanged"
        else:
            item.action, item.action_note = Item.Action.ASSIGN, "Sets a device value; inherited values are unchanged"


# ------------------------------------------------------------------------------------------------ confirm / approve


def confirm(job: Job, user: Any, *, acknowledge_overwrite: bool, request: Any = None) -> Job:
    from apps.integrations.vsa.cf_writer import availability

    with transaction.atomic():
        job = Job.objects.select_for_update().select_related("field", "integration_instance").get(pk=job.pk)
        if job.state != Job.State.PREVIEWED or job.previewed_at is None:
            raise serializers.ValidationError({"state": "Preview the changes first."})
        if timezone.now() - job.previewed_at > timedelta(minutes=settings.CUSTOM_FIELD_PREVIEW_VALID_MINUTES):
            raise serializers.ValidationError({"state": "The preview is out of date. Preview again."})
        to_change = job.counts.get("to_change", 0)
        if not to_change:
            raise serializers.ValidationError(
                {"items": "Nothing to change: every device is already correct or blocked."}
            )
        caps = scope.capabilities_for_customer(user, job.customer_id)
        if to_change > settings.CUSTOM_FIELD_ENGINEER_MAX_DEVICES and Cap.CUSTOMER_CF_BULK not in caps:
            raise PermissionDenied(
                f"Changing more than {settings.CUSTOM_FIELD_ENGINEER_MAX_DEVICES} devices "
                "needs a customer administrator."
            )
        if job.counts.get("updates") and not acknowledge_overwrite:
            raise serializers.ValidationError(
                {
                    "acknowledge_overwrite": "Some devices already have a different value. "
                    "Confirm that it is overwritten."
                }
            )
        available, reason = availability(job.integration_instance)
        if not available:
            raise serializers.ValidationError({"state": reason})
        if Job.objects.filter(customer=job.customer, field=job.field, state__in=ACTIVE).exclude(pk=job.pk).exists():
            raise serializers.ValidationError(
                {"state": "Another job for this field is waiting or running. Let it finish."}
            )
        threshold = job.integration_instance.custom_field_approval_threshold
        job.approval_required = job.field.requires_approval or bool(threshold and to_change > threshold)
        job.confirmed_by, job.confirmed_at = user, timezone.now()
        # One authorization (product owner, 2026-11-24): an administrator who may approve confirms AND approves in one
        # step unless a second approver is required on this server. Engineers' jobs still wait for an administrator.
        self_approved = (
            job.approval_required and Cap.CUSTOMER_CF_APPROVE in caps and not settings.CATALOG_REQUIRE_SEPARATE_REVIEWER
        )
        if self_approved:
            job.approved_by, job.approved_at = user, job.confirmed_at
        job.state = Job.State.AWAITING_APPROVAL if job.approval_required and not self_approved else Job.State.QUEUED
        job.save(
            update_fields=["approval_required", "confirmed_by", "confirmed_at", "approved_by", "approved_at", "state"]
        )
        job.items.filter(included=True, action=Item.Action.SKIP).update(result=Item.Result.ALREADY_CORRECT)
        job.items.filter(result=Item.Result.PENDING).exclude(
            included=True, action__in=(Item.Action.ASSIGN, Item.Action.UPDATE)
        ).update(result=Item.Result.NOT_RUN)
        _count(job)
        if job.state == Job.State.QUEUED:
            _enqueue(job)
    _audit(
        job,
        "confirmed",
        user,
        request,
        to_change=to_change,
        approval_required=job.approval_required,
        self_approved=bool(self_approved),
    )
    return job


def _enqueue(job: Job) -> None:
    from .tasks import execute_job

    transaction.on_commit(lambda: execute_job.delay(str(job.id)))


def decide(job: Job, user: Any, *, approve: bool, request: Any = None) -> Job:
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job.pk)
        if job.state != Job.State.AWAITING_APPROVAL:
            raise serializers.ValidationError({"state": "This job is not waiting for approval."})
        own = user.pk in (job.created_by_id, job.confirmed_by_id)
        if own and settings.CATALOG_REQUIRE_SEPARATE_REVIEWER:
            raise PermissionDenied("A different administrator must approve this job.")
        job.approved_by, job.approved_at = user, timezone.now()
        job.state = Job.State.QUEUED if approve else Job.State.REJECTED
        job.save(update_fields=["approved_by", "approved_at", "state"])
        if approve:
            _enqueue(job)
        else:
            job.items.filter(result=Item.Result.PENDING).update(result=Item.Result.NOT_RUN)
            _count(job)
    _audit(job, "approved" if approve else "rejected", user, request, self_approved=own)
    return job


def cancel(job: Job, user: Any, request: Any = None) -> Job:
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job.pk)
        if job.state in (Job.State.QUEUED, Job.State.RUNNING):
            job.cancel_requested = True
            job.save(update_fields=["cancel_requested"])
        elif job.state in (Job.State.DRAFT, Job.State.PREVIEWING, Job.State.PREVIEWED, Job.State.AWAITING_APPROVAL):
            job.state, job.finished_at = Job.State.CANCELLED, timezone.now()
            job.save(update_fields=["state", "finished_at"])
            job.items.filter(result=Item.Result.PENDING).update(result=Item.Result.CANCELLED)
            _count(job)
        else:
            raise serializers.ValidationError({"state": "This job has already finished."})
    _audit(job, "cancel_requested", user, request)
    return job


RETRYABLE = (
    Item.Result.FAILED,
    Item.Result.UNKNOWN,
    Item.Result.VERIFICATION_FAILED,
    Item.Result.VERIFICATION_PENDING,
    Item.Result.SKIPPED,
    Item.Result.CANCELLED,
)


def retry_failed(job: Job, user: Any, request: Any = None) -> Job:
    """A new draft job for the devices that did not end verified; it must be previewed and confirmed again."""
    from .matching import match_selected

    ids = list(
        job.items.filter(result__in=RETRYABLE, asset__isnull=False).values_list("asset_id", flat=True).distinct()
    )
    if not ids:
        raise serializers.ValidationError({"items": "No failed devices to retry."})
    items = match_selected(job.customer, job.integration_instance, [str(i) for i in ids])
    values = dict(job.items.filter(asset_id__in=ids).values_list("asset_id", "requested_value"))
    for i in items:
        i["requested_value"] = values.get(i.get("asset_id"), "") if job.per_device_values else ""
    return create(
        job.customer,
        user,
        job.field,
        value=job.value,
        source=Job.Source.RETRY,
        items=items,
        retry_of=job,
        only_if_empty=job.only_if_empty,
        request=request,
    )


# ------------------------------------------------------------------------------------------------ execute


def execute(job_id: str, *, adapter: Any = None, writer: Any = None) -> Job:
    from apps.integrations.vsa.adapter import VsaXAdapter
    from apps.integrations.vsa.cf_writer import VsaCustomFieldWriter, WriteNotAvailable

    now = timezone.now()
    with transaction.atomic():
        job = Job.objects.select_for_update().select_related("field", "integration_instance", "customer").get(pk=job_id)
        resumable = job.state == Job.State.RUNNING and (job.heartbeat_at is None or now - job.heartbeat_at > STALE_RUN)
        if job.state != Job.State.QUEUED and not resumable:
            return job  # duplicate delivery of a running/finished job is ignored
        job.state, job.heartbeat_at = Job.State.RUNNING, now
        job.started_at = job.started_at or now
        job.save(update_fields=["state", "heartbeat_at", "started_at"])
    _audit(job, "execution_started", job.confirmed_by, resumed=resumable)
    try:
        writer = writer or VsaCustomFieldWriter(job.integration_instance)
    except WriteNotAvailable as exc:
        job.items.filter(result__in=(Item.Result.PENDING, Item.Result.SENDING)).update(result=Item.Result.NOT_RUN)
        return _finish(job, Job.State.FAILED, "writes_unavailable", note=str(exc))
    adapter = adapter or VsaXAdapter(job.integration_instance)
    # A write that was being sent when a previous run stopped: never resend, find out from VSA X.
    for item in job.items.filter(result=Item.Result.SENDING):
        _settle_uncertain(job, item, adapter, "interrupted_run")
    pace = 1.0 / float(job.integration_instance.max_rps or 1)
    live = _live_assets(job)
    ok, reason = definitions.eligibility(CustomFieldDefinition.objects.get(pk=job.field_id))
    for item in job.items.filter(result=Item.Result.PENDING).order_by("position"):
        job.refresh_from_db(fields=["cancel_requested"])
        if job.cancel_requested:
            job.items.filter(result=Item.Result.PENDING).update(result=Item.Result.CANCELLED)
            return _finish(job, Job.State.CANCELLED, "")
        _execute_item(job, item, adapter, writer, ok, reason, live)
        Job.objects.filter(pk=job.pk).update(heartbeat_at=timezone.now())
        sleep(pace)
    return _finish(job, Job.State.COMPLETED, "")


def _done(item: Item, result: str, code: str = "", **fields: Any) -> None:
    item.result, item.error_code, item.finished_at = result, code[:40], timezone.now()
    for key, value in fields.items():
        setattr(item, key, value)
    item.save()


def _execute_item(
    job: Job, item: Item, adapter: Any, writer: Any, ok: bool, reason: str, live: dict[str, bool]
) -> None:
    from apps.integrations.vsa.cf_writer import WriteOutcomeUnknown, WriteRejected

    field, device, requested = job.field, item.device_external_id, item.requested_value
    if not ok:
        return _record(job, item, Item.Result.SKIPPED, "field_not_editable", note=reason)
    if item.asset_id is None or not live.get(str(item.asset_id)):
        return _record(job, item, Item.Result.SKIPPED, "device_no_longer_eligible")
    # Re-read right before the write: VSA X may have changed since the preview.
    try:
        assigned, current = _device_level(adapter, field.external_id, device)
    except Exception:
        return _record(job, item, Item.Result.SKIPPED, "read_failed_before_write")
    if assigned and definitions.same(field.type, current, requested):
        return _record(job, item, Item.Result.ALREADY_CORRECT, "", final_value=current)
    if job.only_if_empty and assigned and not _empty(current):
        return _record(job, item, Item.Result.SKIPPED, "has_value_now", final_value=current)
    if assigned != bool(item.device_assigned) or (assigned and current != item.current_value):
        return _record(job, item, Item.Result.SKIPPED, "changed_since_preview", final_value=current)
    item.result, item.started_at = Item.Result.SENDING, timezone.now()
    item.save(update_fields=["result", "started_at"])  # committed before the request: a crash is never resent
    for attempt, delay in enumerate((0, *RATE_LIMIT_DELAYS)):
        if delay:
            sleep(delay)
        try:
            writer.write(field.external_id, device, requested, update=assigned)
            break
        except WriteRejected as exc:
            if exc.status == 429 and attempt < len(RATE_LIMIT_DELAYS):
                continue  # refused without being applied: safe to try again after backing off
            return _record(job, item, Item.Result.FAILED, f"vsa_rejected_{exc.status}", http_status=exc.status)
        except WriteOutcomeUnknown as exc:
            item.http_status = exc.status
            return _settle_uncertain(job, item, adapter, exc.code)
    _verify(job, item, adapter)


def _read_back(job: Job, item: Item, adapter: Any) -> tuple[str, str | None]:
    """('equal'|'different'|'error', observed value) after bounded retries."""
    observed: str | None = None
    status = "error"
    for delay in READ_BACK_DELAYS:
        if delay:
            sleep(delay)
        try:
            assigned, observed = _device_level(adapter, job.field.external_id, item.device_external_id)
        except Exception:
            status = "error" if status == "error" else status
            continue
        if assigned and definitions.same(job.field.type, observed, item.requested_value):
            return "equal", observed
        status = "different"
    return status, observed


def _verify(job: Job, item: Item, adapter: Any) -> None:
    status, observed = _read_back(job, item, adapter)
    if status == "equal":
        return _record(job, item, Item.Result.VERIFIED, "", final_value=observed)
    if status == "different":
        return _record(job, item, Item.Result.VERIFICATION_FAILED, "value_not_confirmed", final_value=observed)
    return _record(job, item, Item.Result.VERIFICATION_PENDING, "read_back_failed")


def _settle_uncertain(job: Job, item: Item, adapter: Any, code: str) -> None:
    status, observed = _read_back(job, item, adapter)
    if status == "equal":
        return _record(job, item, Item.Result.VERIFIED, f"confirmed_after_{code}"[:40], final_value=observed)
    return _record(job, item, Item.Result.UNKNOWN, code, final_value=observed)


def _record(job: Job, item: Item, result: str, code: str, note: str = "", **fields: Any) -> None:
    _done(item, result, code, **fields)
    _audit(
        job,
        "assignment",
        job.confirmed_by,
        outcome="success" if result in (Item.Result.VERIFIED, Item.Result.ALREADY_CORRECT) else "failure",
        device=item.device_external_id,
        hostname=item.hostname,
        operation="update" if item.device_assigned else "assign",
        previous_value=item.current_value,
        requested_value=item.requested_value,
        final_value=item.final_value,
        result=result,
        error_code=code,
        note=note,
        instance=str(job.integration_instance_id),
    )


def _finish(job: Job, state: str, code: str, note: str = "") -> Job:
    job.state, job.error_code, job.finished_at = state, code, timezone.now()
    job.save(update_fields=["state", "error_code", "finished_at"])
    # CFA-10: the next sync re-reads the details of every device a write was sent to, so device lists and filters show
    # the new value without waiting for the weekly custom field refresh.
    from apps.inventory.models import Asset

    sent = job.items.exclude(started_at=None).exclude(asset=None).values("asset_id")
    Asset.objects.filter(pk__in=sent).update(details_refresh_requested_at=job.finished_at)
    _count(job)
    _audit(
        job,
        "execution_finished",
        job.confirmed_by,
        state=state,
        error_code=code,
        note=note,
        results=job.counts.get("result"),
    )
    return job
