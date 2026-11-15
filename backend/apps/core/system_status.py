"""P5-05 (in-portal part): operational status for super administrators.

Read-only aggregation over the portal's own tables (no vendor calls). Every signal becomes a finding with a level
(``ok`` / ``warn`` / ``error``), a stable code and a plain-language message, so the UI and alerting can use the
same output. Never includes credentials, tokens, payloads or personal data beyond counts.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db.models import Count
from django.utils import timezone

QUEUED_STUCK_MINUTES = 15
RUNNING_LONG_MINUTES = 120
EXPORTS_PER_USER_HOUR = 20  # a single user generating more exports than this in an hour is flagged for review
FAILED_LOGINS_DAY = 20

SYNC_HINTS = {
    "auth_failed": "VSA X rejected the API credentials. Re-enter them under Settings → Integrations.",
    "credential_unavailable": "No usable API credentials. Enter them under Settings → Integrations.",
    "egress_blocked": "The VSA host is not allowed or resolves to a private address (Allowed API hosts).",
    "vendor_unavailable": "VSA X did not answer or returned a server error (network, DNS, firewall or VSA itself).",
    "rate_limited": "VSA X rate limit reached; the sync resumes automatically.",
    "retry_budget_exhausted": "VSA X kept failing; the sync gave up after its retries.",
    "row_count_drop_guard": "Far fewer devices than last time, so the previous data was kept.",
    "malformed_page": "VSA X returned data in an unexpected shape; see the worker log.",
    "internal_error": "Unexpected error in the worker; see the worker log.",
}


def _worker_answering(timeout: float) -> int | None:
    """Number of Celery workers answering a ping; None when the broker cannot be reached. Bounded: a quick
    connection check first, so an unreachable Redis never holds the web request for long."""
    try:
        from config.celery import app

        with app.connection_for_write() as conn:
            conn.ensure_connection(max_retries=1, interval_start=0, interval_step=0, timeout=timeout)
        return len(app.control.ping(timeout=timeout) or [])
    except Exception:  # broker unreachable: report "unknown", never the exception text
        return None


def collect(*, check_worker: bool = True, worker_timeout: float = 1.5) -> dict[str, Any]:
    from apps.audit.models import AuditEvent
    from apps.customers.models import CustomerSourceMapping
    from apps.integrations.models import DatasetGeneration, IntegrationInstance, SyncRun
    from apps.reporting.models import ReportRun

    now = timezone.now()
    day = now - timedelta(hours=24)
    findings: list[dict[str, str]] = []

    def add(level: str, code: str, message: str) -> None:
        findings.append({"level": level, "code": code, "message": message})

    # Worker / queue
    # With eager tasks (development/tests) there is no worker by design.
    check_worker = check_worker and not settings.CELERY_TASK_ALWAYS_EAGER
    workers = _worker_answering(worker_timeout) if check_worker else None
    queued_stuck = SyncRun.objects.filter(
        state="queued", started_at__isnull=True, created_at__lt=now - timedelta(minutes=QUEUED_STUCK_MINUTES)
    ).count()
    running_long = SyncRun.objects.filter(
        state="running", started_at__lt=now - timedelta(minutes=RUNNING_LONG_MINUTES)
    ).count()
    oldest_queued = (
        SyncRun.objects.filter(state="queued", started_at__isnull=True)
        .order_by("created_at")
        .values_list("created_at", flat=True)
        .first()
    )
    queue_lag_minutes = int((now - oldest_queued).total_seconds() // 60) if oldest_queued else 0
    if check_worker and workers == 0:
        add("error", "worker_down", "No background worker answered: syncs and reports cannot run.")
    elif check_worker and workers is None:
        add("error", "broker_unreachable", "The task queue (Redis) could not be reached: syncs and reports cannot run.")
    if queued_stuck:
        add(
            "error", "queue_stuck", f"{queued_stuck} sync(s) waiting more than {QUEUED_STUCK_MINUTES} minutes to start."
        )
    if running_long:
        add(
            "warn", "sync_running_long", f"{running_long} sync(s) running for more than {RUNNING_LONG_MINUTES} minutes."
        )

    # Sync outcomes (last 24 h)
    runs = SyncRun.objects.filter(created_at__gte=day)
    by_state = dict(runs.values_list("state").annotate(n=Count("id")).values_list("state", "n"))
    errors = dict(
        runs.exclude(error_code="").values_list("error_code").annotate(n=Count("id")).values_list("error_code", "n")
    )
    for code, n in sorted(errors.items(), key=lambda kv: -kv[1]):
        level = "warn" if code in ("rate_limited",) else "error"
        add(level, f"sync_{code}", f"{n} sync(s) in the last 24 h: {SYNC_HINTS.get(code, code)}")

    # Data freshness per approved mapping
    stale_after = now - timedelta(hours=settings.DATA_STALE_AFTER_HOURS)
    stale: list[dict[str, Any]] = []
    approved = CustomerSourceMapping.objects.filter(mapping_status="approved").select_related(
        "customer", "integration_instance"
    )
    current = {
        g.mapping_id: g.published_at
        for g in DatasetGeneration.objects.filter(is_current=True, mapping__mapping_status="approved").only(
            "mapping_id", "published_at"
        )
    }
    for m in approved:
        published = current.get(m.id)
        if published is None or published < stale_after:
            stale.append(
                {
                    "customer": m.customer.code,
                    "integration": m.integration_instance.name,
                    "as_of": published.isoformat() if published else None,
                }
            )
    if stale:
        add(
            "warn",
            "data_stale",
            f"{len(stale)} customer source(s) older than {settings.DATA_STALE_AFTER_HOURS} h or never synced.",
        )

    # Integrations
    for inst in IntegrationInstance.objects.filter(enabled=True, is_fixture=False):
        if inst.last_test_outcome and inst.last_test_outcome != "ok":
            add(
                "warn",
                "connection_test_failed",
                f"Last connection test of “{inst.name}” failed ({inst.last_test_outcome}).",
            )

    # Exports and sign-in (security signals)
    hour = now - timedelta(hours=1)
    exports_24h = ReportRun.objects.filter(created_at__gte=day).count()
    heavy = list(
        ReportRun.objects.filter(created_at__gte=hour)
        .values("requested_by__email")
        .annotate(n=Count("id"))
        .filter(n__gt=EXPORTS_PER_USER_HOUR)
        .values_list("n", flat=True)
    )
    if heavy:
        add(
            "warn",
            "mass_export",
            f"{len(heavy)} user(s) generated more than {EXPORTS_PER_USER_HOUR} exports in the last hour.",
        )
    failed_logins = AuditEvent.objects.filter(action="auth.login", outcome="failure", created_at__gte=day).count()
    if failed_logins > FAILED_LOGINS_DAY:
        add("warn", "failed_logins", f"{failed_logins} failed sign-ins in the last 24 h.")

    level = "error" if any(f["level"] == "error" for f in findings) else "warn" if findings else "ok"
    return {
        "generated_at": now.isoformat(),
        "level": level,
        "worker": {"checked": check_worker, "answering": workers},
        "queue": {
            "queued_stuck": queued_stuck,
            "running_long": running_long,
            "oldest_queued_minutes": queue_lag_minutes,
        },
        "syncs_24h": {"by_state": by_state, "errors": errors},
        "stale_sources": stale,
        "exports_24h": exports_24h,
        "failed_logins_24h": failed_logins,
        "findings": findings,
    }
