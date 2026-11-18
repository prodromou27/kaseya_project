from __future__ import annotations

from celery import shared_task


@shared_task(name="apps.customfields.tasks.preview_job", acks_late=True, max_retries=0)
def preview_job(job_id: str) -> str:
    """Read current values from VSA X for every included device (read-only)."""
    from .jobs import run_preview

    return run_preview(job_id).state


@shared_task(name="apps.customfields.tasks.execute_job", acks_late=True, max_retries=0)
def execute_job(job_id: str) -> str:
    """Write a confirmed job, one device at a time, with read-back verification. Resume-safe; never resends."""
    from .jobs import execute

    return execute(job_id).state
