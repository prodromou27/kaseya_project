from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.reporting.tasks.generate_report", acks_late=True, max_retries=0)
def generate_report(run_id: str) -> str:
    """Payload is only the run ID: customer scope is always re-resolved and re-authorised from the DB."""
    from .services import generate

    return generate(run_id).state


@shared_task(name="apps.reporting.tasks.dispatch_schedules", acks_late=True, max_retries=0)
def dispatch_schedules() -> dict[str, int]:
    """Celery Beat entry point (every minute). Idempotent per slot (DB unique constraint)."""
    from .scheduling import dispatch_due_report_schedules, dispatch_due_sync_schedules

    return {"reports": dispatch_due_report_schedules(), "syncs": dispatch_due_sync_schedules()}


@shared_task(name="apps.reporting.tasks.purge_expired_artifacts", acks_late=True, max_retries=0)
def purge_expired_artifacts() -> int:
    from .services import purge_expired_artifacts as purge

    return purge()
