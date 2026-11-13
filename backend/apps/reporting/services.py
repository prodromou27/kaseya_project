from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.accounts import scope
from apps.audit.services import record_event

from .models import ReportArtifact, ReportRun
from .registry import REPORT_TYPES, ReportType
from .renderers import RENDERERS, RenderLimitError

logger = logging.getLogger("portal.reporting")


class ReportAuthorizationError(Exception):
    pass


def user_may_access_report(user: Any, run: ReportRun) -> bool:
    report_type = REPORT_TYPES.get(run.report_type)
    if report_type is None:
        return False
    caps = scope.capabilities_for_customer(user, run.customer_id)
    if not user.is_super_admin:
        # Re-check membership visibility (status) via the same policy used everywhere else.
        from apps.customers.models import Customer

        if not Customer.objects.filter(pk=run.customer_id, status__in=Customer.MEMBER_VISIBLE_STATUSES).exists():
            return False
    return report_type.required_capabilities.issubset(caps)


def filters_hash(report_type: str, filters: dict[str, Any]) -> str:
    canonical = json.dumps({"type": report_type, "filters": filters}, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()


def storage_path(storage_key: str) -> Path:
    base = Path(settings.REPORT_STORAGE_DIR).resolve()
    path = (base / storage_key).resolve()
    if path.parent != base:  # storage_key is validated opaque, but never trust path joins
        raise ValueError("Invalid storage key.")
    return path


def request_report(
    user: Any,
    customer: Any,
    report_type_key: str,
    fmt: str,
    filters: dict[str, Any],
    request: Any,
    *,
    regenerated_from: ReportRun | None = None,
) -> ReportRun:
    report_type = REPORT_TYPES[report_type_key]
    run = ReportRun.objects.create(
        customer=customer,
        requested_by=user,
        report_type=report_type.key,
        format=fmt,
        filters=filters,
        filters_hash=filters_hash(report_type.key, filters),
        data_basis=report_type.data_basis,
        # A regeneration is pinned to the original snapshot IDs (validated against the customer at generation).
        as_of_generation_ids=dict(regenerated_from.as_of_generation_ids) if regenerated_from else {},
        regenerated_from=regenerated_from,
    )
    record_event(
        action="report.requested",
        outcome="success",
        actor=user,
        customer=customer,
        target_type="report_run",
        target_id=str(run.id),
        request=request,
        metadata={"report_type": run.report_type, "format": fmt},
    )
    from .tasks import generate_report

    transaction.on_commit(lambda: generate_report.delay(str(run.id)))
    return run


def _render(report_type: ReportType, run: ReportRun, pins: dict[str, Any]) -> tuple[bytes, int]:
    rows = list(_limited(report_type.rows(run.customer, run.filters, pins)))
    provenance = {
        "Report": report_type.title,
        "Customer": f"{run.customer.name} ({run.customer.code})",
        "Generated": timezone.now().isoformat(),
        "Report run": str(run.id),
        **({"Regenerated from run": str(run.regenerated_from_id)} if run.regenerated_from_id else {}),
        "Data basis": run.data_basis,
        **pins.get("provenance", {}),
        "Filters": json.dumps(run.filters, sort_keys=True) if run.filters else "none",
        "Records included": str(len(rows)),
        "Limitations": report_type.limitations or "none",
    }
    renderer = RENDERERS[run.format]
    return renderer(report_type.title, provenance, report_type.columns, rows), len(rows)


def _limited(rows: Any) -> Any:
    for count, row in enumerate(rows, start=1):
        if count > settings.REPORT_MAX_ROWS:
            raise OverflowError("row_limit_exceeded")
        yield row


def generate(run_id: str) -> ReportRun:
    """Worker entry point. Re-resolves the run from DB and re-authorises the requester before reading data."""
    with transaction.atomic():
        run = ReportRun.objects.select_for_update().select_related("customer", "requested_by").get(pk=run_id)
        if run.state != ReportRun.State.QUEUED:
            return run  # idempotent: duplicate deliveries are ignored
        run.state, run.started_at = ReportRun.State.RUNNING, timezone.now()
        run.save(update_fields=["state", "started_at"])

    requester = run.requested_by
    scope.invalidate_cache(requester)
    if not requester.is_active or not user_may_access_report(requester, run):
        return _fail(run, "authorization_revoked", outcome="denied")
    report_type = REPORT_TYPES.get(run.report_type)
    if report_type is None:
        return _fail(run, "unknown_report_type")

    if run.format not in report_type.formats or run.format not in RENDERERS:
        return _fail(run, "unsupported_format")
    pins: dict[str, Any] = {}
    if report_type.pin is not None:
        pinned = run.as_of_generation_ids or None
        pins = report_type.pin(run.customer, pinned)
        run.as_of_generation_ids = {
            "generations": pins["generation_ids"],
            "evaluations": pins["evaluation_ids"],
            # Report-specific pins (e.g. R17's evaluation date and lifecycle entry IDs) so regeneration is exact.
            **pins.get("extra_pins", {}),
        }
        run.data_basis = pins["data_basis"]
        run.save(update_fields=["as_of_generation_ids", "data_basis"])
    try:
        content, count = _render(report_type, run, pins)
    except OverflowError:
        return _fail(run, "row_limit_exceeded")
    except RenderLimitError as exc:
        return _fail(run, exc.code)
    except Exception:
        logger.exception("report_generation_failed", extra={"report_run_id": str(run.id)})
        return _fail(run, "generation_failed")

    storage_key = f"{uuid.uuid4().hex}.{run.format}"
    path = storage_path(storage_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    with transaction.atomic():
        ReportArtifact.objects.create(
            report_run=run,
            storage_key=storage_key,
            format=run.format,
            sha256=hashlib.sha256(content).hexdigest(),
            bytes=len(content),
            expires_at=timezone.now() + timedelta(hours=settings.REPORT_ARTIFACT_TTL_HOURS),
        )
        run.state, run.row_count, run.completed_at = ReportRun.State.COMPLETED, count, timezone.now()
        run.save(update_fields=["state", "row_count", "completed_at"])
    record_event(
        action="report.generated",
        outcome="success",
        actor=requester,
        customer=run.customer,
        target_type="report_run",
        target_id=str(run.id),
        metadata={"rows": count, "report_type": run.report_type},
    )
    return run


def _fail(run: ReportRun, code: str, outcome: str = "failure") -> ReportRun:
    run.state, run.error_code, run.completed_at = ReportRun.State.FAILED, code, timezone.now()
    run.save(update_fields=["state", "error_code", "completed_at"])
    record_event(
        action="report.generated",
        outcome=outcome,
        actor=run.requested_by,
        customer=run.customer,
        target_type="report_run",
        target_id=str(run.id),
        metadata={"error_code": code},
    )
    return run


def purge_expired_artifacts(now: Any = None) -> int:
    """Delete expired report files from private storage. Rows are kept (purged_at set) as audit evidence."""
    now = now or timezone.now()
    purged = 0
    for artifact in ReportArtifact.objects.filter(expires_at__lte=now, purged_at__isnull=True).select_related(
        "report_run", "report_run__customer"
    ):
        try:
            storage_path(artifact.storage_key).unlink(missing_ok=True)
        except (OSError, ValueError):
            logger.exception("artifact_purge_failed", extra={"artifact_id": str(artifact.id)})
            continue
        artifact.purged_at = now
        artifact.save(update_fields=["purged_at"])
        record_event(
            action="report.artifact_purged",
            outcome="success",
            actor_label="system:retention",
            customer=artifact.report_run.customer,
            target_type="report_run",
            target_id=str(artifact.report_run_id),
            metadata={"sha256": artifact.sha256, "expired_at": artifact.expires_at.isoformat()},
        )
        purged += 1
    return purged
