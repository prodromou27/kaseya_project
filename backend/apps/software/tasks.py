from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.software.tasks.reevaluate_compliance", acks_late=True, max_retries=0)
def reevaluate_compliance(customer_id: str | None = None) -> int:
    """Re-classify current generations after catalog or exception changes. Idempotent (catalog fingerprint)."""
    from .services import reevaluate_current

    return reevaluate_current(customer_id)


@shared_task(name="apps.software.tasks.update_vsa_catalog", acks_late=True, max_retries=0)
def update_vsa_catalog() -> str:
    """Daily (CAT-02): read the VSA application catalog page and update reference versions."""
    from .vsa_catalog_sync import run

    return run(trigger="schedule").outcome
