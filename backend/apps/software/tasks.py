from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.software.tasks.reevaluate_compliance", acks_late=True, max_retries=0)
def reevaluate_compliance(customer_id: str | None = None) -> int:
    """Re-classify current generations after catalog or exception changes. Idempotent (catalog fingerprint)."""
    from .services import reevaluate_current

    return reevaluate_current(customer_id)
