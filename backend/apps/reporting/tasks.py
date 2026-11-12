from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.reporting.tasks.generate_report", acks_late=True, max_retries=0)
def generate_report(run_id: str) -> str:
    """Payload is only the run ID: customer scope is always re-resolved and re-authorised from the DB."""
    from .services import generate

    return generate(run_id).state
