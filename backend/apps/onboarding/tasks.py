from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.onboarding.tasks.run_reconciliation", acks_late=True, max_retries=0)
def run_reconciliation(run_id: str) -> str:
    """Payload is only the run ID; customer, generation and authorisation are re-resolved from the DB."""
    from .services import execute

    return execute(run_id).state


@shared_task(name="apps.onboarding.tasks.purge_expired_uploads", acks_late=True, max_retries=0)
def purge_expired_uploads() -> int:
    from .services import purge_expired_uploads as purge

    return purge()
