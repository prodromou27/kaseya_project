"""Report and sync schedules (P2-05). Driven by one Celery Beat task that runs every minute.

* Next-run times are computed in the schedule's IANA timezone and stored in UTC. A local time that does not exist
  (DST spring-forward) maps through ``zoneinfo``'s fold rules; ambiguous times use the first occurrence.
* Each due slot creates a ``ScheduledExecution`` with a unique ``(schedule, slot_at)``: a duplicate Beat tick, a
  second Beat instance or a retried task cannot run the same slot twice.
* Missed slots (e.g. downtime) are coalesced: the overdue slot runs once, then the next future slot is scheduled.
* Owner and recipients are re-authorised at execution time. Delivery is **in-portal only** (DEC-09).
"""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts import scope
from apps.audit.services import record_event

from .models import ReportRun, ReportSchedule, ScheduledExecution

logger = logging.getLogger("portal.scheduling")


def validate_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown IANA timezone.") from exc


def _matches(schedule: ReportSchedule, day: date) -> bool:
    if schedule.frequency == ReportSchedule.Frequency.DAILY:
        return True
    if schedule.frequency == ReportSchedule.Frequency.WEEKLY:
        return day.weekday() == schedule.weekday
    return day.day == schedule.day_of_month


def compute_next_run(schedule: ReportSchedule, after: datetime) -> datetime:
    """Earliest slot strictly after ``after`` (UTC-aware), expressed in UTC."""
    tz = validate_timezone(schedule.timezone)
    local_day = after.astimezone(tz).date()
    for offset in range(0, 400):
        day = local_day + timedelta(days=offset)
        if not _matches(schedule, day):
            continue
        local = datetime.combine(day, schedule.time_of_day, tzinfo=tz)
        candidate = local.astimezone(UTC)
        if candidate > after:
            return candidate
    raise ValueError("No slot found within 400 days.")


def user_may_receive(user: Any, schedule: ReportSchedule) -> bool:
    from .services import user_may_access_report

    if not user.is_active:
        return False
    scope.invalidate_cache(user)
    probe = ReportRun(customer_id=schedule.definition.customer_id, report_type=schedule.definition.report_type)
    return user_may_access_report(user, probe)


def execute_slot(schedule: ReportSchedule, slot_at: datetime) -> ScheduledExecution | None:
    """Run one slot. Returns None if this slot was already executed (duplicate suppressed)."""
    from .services import request_report

    definition = schedule.definition
    owner = definition.owner
    try:
        with transaction.atomic():
            execution = ScheduledExecution.objects.create(
                schedule=schedule, slot_at=slot_at, state=ScheduledExecution.State.SKIPPED, reason="pending"
            )
    except IntegrityError:
        logger.info("schedule_slot_duplicate_suppressed", extra={"schedule_id": str(schedule.id)})
        return None

    if not user_may_receive(owner, schedule):
        execution.reason = "owner_access_revoked"
        execution.save(update_fields=["reason"])
        record_event(
            action="report.schedule_skipped",
            outcome="denied",
            actor=owner,
            customer=definition.customer,
            target_type="report_schedule",
            target_id=str(schedule.id),
            metadata={"reason": execution.reason, "slot_at": slot_at.isoformat()},
        )
        return execution

    allowed, removed = [], []
    for recipient in schedule.recipients.all():
        (allowed if user_may_receive(recipient, schedule) else removed).append(recipient)
    with transaction.atomic():
        run = request_report(
            owner, definition.customer, definition.report_type, definition.format, definition.filters, None
        )
        execution.state, execution.reason, execution.report_run = ScheduledExecution.State.STARTED, "", run
        execution.delivered_to = sorted({str(owner.id), *(str(u.id) for u in allowed)})
        execution.save(update_fields=["state", "reason", "report_run", "delivered_to"])
    if removed:
        record_event(
            action="report.schedule_recipients_removed",
            outcome="denied",
            actor=owner,
            customer=definition.customer,
            target_type="report_schedule",
            target_id=str(schedule.id),
            metadata={"recipients": [u.email for u in removed]},
        )
    return execution


def dispatch_due_report_schedules(now: datetime | None = None) -> int:
    now = now or timezone.now()
    executed = 0
    due = ReportSchedule.objects.filter(enabled=True, next_run_at__lte=now).select_related(
        "definition", "definition__owner", "definition__customer"
    )
    for schedule in due:
        with transaction.atomic():
            locked = ReportSchedule.objects.select_for_update(skip_locked=True).filter(pk=schedule.pk).first()
            if locked is None or locked.next_run_at is None or locked.next_run_at > now:
                continue  # another dispatcher holds it, or already advanced
            slot = locked.next_run_at
            locked.last_run_at = slot
            locked.next_run_at = compute_next_run(locked, max(slot, now))
            locked.save(update_fields=["last_run_at", "next_run_at"])
        if execute_slot(schedule, slot) is not None:
            executed += 1
    return executed


def dispatch_due_sync_schedules(now: datetime | None = None) -> int:
    from apps.integrations.models import SyncRun, SyncSchedule
    from apps.integrations.sync import SyncRefused, request_sync

    now = now or timezone.now()
    started = 0
    for schedule in SyncSchedule.objects.filter(enabled=True, next_run_at__lte=now).select_related("mapping"):
        with transaction.atomic():
            locked = SyncSchedule.objects.select_for_update(skip_locked=True).filter(pk=schedule.pk).first()
            if locked is None or locked.next_run_at > now:
                continue
            slot = locked.next_run_at
            nxt = slot + timedelta(hours=locked.interval_hours)
            locked.next_run_at = nxt if nxt > now else now + timedelta(hours=locked.interval_hours)
            locked.last_run_at = slot
            locked.save(update_fields=["next_run_at", "last_run_at"])
        try:
            _, created = request_sync(
                schedule.mapping,
                requested_by=None,
                trigger=SyncRun.Trigger.SCHEDULE,
                idempotency_key=f"sched:{schedule.id}:{slot.isoformat()}",
            )
            started += int(created)
        except SyncRefused as exc:
            record_event(
                action="sync.schedule_skipped",
                outcome="denied",
                actor_label="system:scheduler",
                customer=schedule.mapping.customer,
                target_type="sync_schedule",
                target_id=str(schedule.id),
                metadata={"reason": exc.code},
            )
    return started


def inbox_runs(user: Any) -> list[ReportRun]:
    """Scheduled report runs delivered to ``user`` that they are *still* authorised to see."""
    from .services import user_may_access_report

    executions = (
        ScheduledExecution.objects.filter(state=ScheduledExecution.State.STARTED, delivered_to__contains=[str(user.id)])
        .select_related("report_run", "report_run__customer", "report_run__requested_by")
        .order_by("-slot_at")[:200]
    )
    return [e.report_run for e in executions if e.report_run and user_may_access_report(user, e.report_run)]


def utc_now() -> datetime:
    return datetime.now(UTC)
