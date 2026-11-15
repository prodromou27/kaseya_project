"""P5-05 in-portal status: super-admin only, findings for stuck queue, failures, stale data; no secrets."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.customers.models import CustomerSourceMapping
from apps.integrations.models import IntegrationInstance, SyncRun

URL = "/api/v1/system/status/?worker=0"


@pytest.fixture
def mapping(world):
    inst = IntegrationInstance.objects.create(
        name="VSA", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True, enabled=True
    )
    return CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=timezone.now(),
    )


def codes(body):
    return {f["code"] for f in body["findings"]}


def test_only_super_admins_can_read_status(world):
    for user in (world.admin_a, world.engineer_a):
        assert world.client(user).get(URL).status_code == 403
    assert world.client(world.super_admin).get(URL).status_code == 200


def test_never_synced_source_is_reported_stale(world, mapping):
    body = world.client(world.super_admin).get(URL).json()
    assert body["level"] == "warn" and "data_stale" in codes(body)
    assert body["stale_sources"] == [{"customer": "ACME", "integration": "VSA", "as_of": None}]


def test_stuck_queue_and_failed_syncs_are_errors(world, mapping):
    old = timezone.now() - timedelta(minutes=30)
    stuck = SyncRun.objects.create(
        integration_instance=mapping.integration_instance,
        customer=world.customer_a,
        mapping=mapping,
        state="queued",
        idempotency_key="k1",
    )
    SyncRun.objects.filter(pk=stuck.pk).update(created_at=old)
    SyncRun.objects.create(
        integration_instance=mapping.integration_instance,
        customer=world.customer_a,
        mapping=mapping,
        state="failed",
        idempotency_key="k2",
        error_code="auth_failed",
    )
    body = world.client(world.super_admin).get(URL).json()
    assert body["level"] == "error"
    assert {"queue_stuck", "sync_auth_failed"} <= codes(body)
    assert body["queue"]["queued_stuck"] == 1 and body["queue"]["oldest_queued_minutes"] >= 29
    assert body["syncs_24h"]["errors"] == {"auth_failed": 1}


def test_worker_down_is_an_error(world, monkeypatch, settings):
    from apps.core import system_status

    settings.CELERY_TASK_ALWAYS_EAGER = False

    monkeypatch.setattr(system_status, "_worker_answering", lambda timeout: 0)
    body = world.client(world.super_admin).get("/api/v1/system/status/").json()
    assert "worker_down" in codes(body) and body["worker"] == {"checked": True, "answering": 0}


def test_eager_mode_skips_the_worker_check(world, settings):
    settings.CELERY_TASK_ALWAYS_EAGER = True
    body = world.client(world.super_admin).get("/api/v1/system/status/").json()
    assert body["worker"] == {"checked": False, "answering": None} and "worker_down" not in codes(body)
