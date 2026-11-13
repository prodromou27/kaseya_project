"""Sync must work after the documented setup without hidden steps, and operators can see why it does not.

Regression for the first host deployment: approving a mapping never created a sync schedule, so nothing synced
automatically; and run counters reported 0 accepted devices.
"""

from __future__ import annotations

from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.integrations.models import IntegrationInstance, SyncSchedule
from apps.reporting.scheduling import dispatch_due_sync_schedules

from .factories import IntegrationFactory
from .test_vsa1_hierarchy_network import env  # noqa: F401 - fixture

pytestmark = pytest.mark.django_db


def _propose_and_approve(world, inst) -> str:
    mid = (
        world.client(world.admin_a)
        .post(
            f"/api/v1/customers/{world.customer_a.id}/mappings/",
            {"integration_instance": str(inst.id), "external_org_id": "11"},
        )
        .json()["id"]
    )
    resp = world.client(world.super_admin).post(f"/api/v1/mappings/{mid}/approve/", {})
    assert resp.status_code == 200
    return mid


def test_approving_a_mapping_creates_a_due_daily_schedule(world, settings):
    settings.SYNC_DEFAULT_INTERVAL_HOURS = 24
    inst = IntegrationFactory()
    mid = _propose_and_approve(world, inst)
    sched = SyncSchedule.objects.get(mapping_id=mid)
    assert sched.enabled and sched.interval_hours == 24 and sched.next_run_at <= timezone.now()


def test_existing_schedule_is_left_as_configured(world):
    inst = IntegrationFactory()
    mid = _propose_and_approve(world, inst)
    SyncSchedule.objects.filter(mapping_id=mid).update(interval_hours=6, enabled=False)
    world.client(world.super_admin).post(f"/api/v1/mappings/{mid}/revoke/", {})
    from apps.customers.models import CustomerSourceMapping

    CustomerSourceMapping.objects.filter(pk=mid).update(mapping_status="proposed")
    world.client(world.super_admin).post(f"/api/v1/mappings/{mid}/approve/", {})
    sched = SyncSchedule.objects.get(mapping_id=mid)
    assert (sched.interval_hours, sched.enabled) == (6, False)


def test_enabling_an_integration_brings_its_schedules_forward(world, env):  # noqa: F811
    inst: IntegrationInstance = env["inst"]
    inst.enabled = False
    inst.save(update_fields=["enabled"])
    later = timezone.now() + timedelta(hours=20)
    sched = SyncSchedule.objects.create(mapping=env["ma"], interval_hours=24, next_run_at=later)
    world.client(world.super_admin).patch(f"/api/v1/integrations/{inst.id}/", {"enabled": True}, format="json")
    sched.refresh_from_db()
    assert sched.next_run_at <= timezone.now()
    assert dispatch_due_sync_schedules() == 1  # the scheduler now starts a run straight away


def test_sync_status_explains_what_blocks_syncing(world, env):  # noqa: F811
    inst: IntegrationInstance = env["inst"]
    inst.enabled = False
    inst.save(update_fields=["enabled"])
    out = StringIO()
    call_command("sync_status", "--no-worker-check", stdout=out)
    text = out.getvalue()
    assert "Integration 'VSA' is disabled." in text
    assert "has no schedule" in text  # env mappings were created directly, without the approve endpoint
    assert "No sync has ever been requested" in text
    assert "token_secret" not in text and "password" not in text.lower()


def test_a_lost_queued_run_is_resent_instead_of_blocking_sync_now(world, env, settings, monkeypatch):  # noqa: F811
    """First host boot: the broker refused connections, the run stayed queued forever and every Sync now returned it."""
    from apps.audit.models import AuditEvent
    from apps.integrations import tasks
    from apps.integrations.models import SyncRun
    from apps.integrations.sync import request_sync

    settings.SYNC_REQUEUE_AFTER_MINUTES = 10
    sent = []
    monkeypatch.setattr(tasks.run_sync, "delay", lambda run_id: sent.append(run_id))
    run, created = request_sync(env["ma"], requested_by=world.engineer_a)
    assert created
    # Fresh queued run: returned as-is, not re-sent.
    again, created = request_sync(env["ma"], requested_by=world.engineer_a)
    assert again.pk == run.pk and not created and not AuditEvent.objects.filter(action="sync.requeued").exists()
    # Queued for 30 minutes and never started: re-sent (on commit) and audited.
    SyncRun.objects.filter(pk=run.pk).update(created_at=timezone.now() - timedelta(minutes=30))
    from django.test import TestCase

    with TestCase.captureOnCommitCallbacks(execute=True):
        again, created = request_sync(env["ma"], requested_by=world.engineer_a)
    assert again.pk == run.pk and not created and sent[-1] == str(run.pk)
    assert AuditEvent.objects.filter(action="sync.requeued", target_id=str(run.pk)).exists()
    # A run that already started is never re-sent.
    SyncRun.objects.filter(pk=run.pk).update(state="running", started_at=timezone.now())
    sent.clear()
    with TestCase.captureOnCommitCallbacks(execute=True):
        request_sync(env["ma"], requested_by=world.engineer_a)
    assert sent == []


def test_broker_outage_does_not_fail_the_request(world, env, monkeypatch):  # noqa: F811
    from apps.integrations import tasks

    def boom(run_id):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(tasks.run_sync, "delay", boom)
    from django.test import TestCase

    with TestCase.captureOnCommitCallbacks(execute=True):
        resp = world.client(world.engineer_a).post(
            f"/api/v1/customers/{world.customer_a.id}/sync-runs/", {}, format="json"
        )
    assert resp.status_code == 202
