from __future__ import annotations

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger("portal.sync")


@shared_task(name="apps.integrations.tasks.run_sync", acks_late=True, max_retries=0)
def run_sync(run_id: str) -> str:
    """Payload is only the run ID; scope, mapping and requester authorisation are re-checked in the worker."""
    from .models import SyncRun
    from .sync import MAX_ATTEMPTS, InstanceBusy, execute

    try:
        run = execute(run_id)
    except InstanceBusy:
        if not settings.CELERY_TASK_ALWAYS_EAGER:
            run_sync.apply_async((run_id,), countdown=60)
        return "busy"
    if run.state == SyncRun.State.PARTIAL and run.attempts < MAX_ATTEMPTS and not settings.CELERY_TASK_ALWAYS_EAGER:
        # Rate limited / vendor unavailable: resume from the checkpoint later (bounded by MAX_ATTEMPTS).
        run_sync.apply_async((run_id,), countdown=min(300 * run.attempts, 1800))
    return run.state
