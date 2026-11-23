"""PERF-01: per-device detail calls only when needed (apps/integrations/freshness.py). Fixture-based, not live."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.audit.models import AuditEvent
from apps.integrations.models import IntegrationInstance, SyncRun
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import Asset
from apps.patching.models import PatchObservation

from .test_patching import device, run, upd, vsa  # noqa: F401 - vsa is a fixture

pytestmark = pytest.mark.django_db


def _data(seen: dict[int, str] | None = None) -> list[dict]:
    rows = [device(i, available=[], installed=[upd(f"60{i:05d}", "Unspecified", f"inst-{i}")]) for i in range(1, 5)]
    for i, value in (seen or {}).items():
        rows[i - 1]["LastSeenOnline"] = value
    return rows


def _detail_ids(transport: FixtureVsaTransport) -> set[str]:
    return {p.split("/")[-1] for p, _ in transport.calls if p.startswith("/api/v3/assets/")}


def _age_collection(ext_id: str, hours: float) -> None:
    PatchObservation.objects.filter(asset__external_id=ext_id, installed_status="collected").update(
        installed_collected_at=timezone.now() - timedelta(hours=hours)
    )


def test_second_sync_skips_recently_collected_devices_and_keeps_their_values(world, vsa):  # noqa: F811
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=100)
    t1 = FixtureVsaTransport(_data())
    run(mapping, world.engineer_a, t1)
    assert len(_detail_ids(t1)) == 4  # new devices: fetched right away

    t2 = FixtureVsaTransport(_data())
    r2 = run(mapping, world.engineer_a, t2)
    assert r2.state == "completed"
    assert _detail_ids(t2) == set()  # nothing due: only the device list was read
    statuses = PatchObservation.objects.filter(generation=r2.generation).values_list("installed_status", flat=True)
    assert sorted(statuses) == ["carried_forward"] * 4
    assert r2.api_requests < 4


def test_stale_details_refetched_only_for_devices_seen_online_since(world, vsa, settings):  # noqa: F811
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=100)
    run(mapping, world.engineer_a, FixtureVsaTransport(_data()))
    for i in range(1, 5):
        _age_collection(f"d-{i:03d}", 25)  # older than the 24 h interval
    _age_collection("d-004", 8 * 24)  # older than the 7-day ceiling
    now = timezone.now().isoformat().replace("+00:00", "Z")
    old = (timezone.now() - timedelta(days=30)).isoformat().replace("+00:00", "Z")
    # d-001 seen online after its last fetch; d-002 unknown last seen; d-003 and d-004 offline for 30 days.
    data = _data({1: now, 3: old, 4: old})
    data[1].pop("LastSeenOnline")
    t = FixtureVsaTransport(data)
    run(mapping, world.engineer_a, t)
    assert _detail_ids(t) == {"d-001", "d-002", "d-004"}  # d-003 is offline and within the ceiling: skipped


def test_interval_is_configurable(world, vsa, settings):  # noqa: F811
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=100)
    run(mapping, world.engineer_a, FixtureVsaTransport(_data()))
    _age_collection("d-001", 2)
    settings.DETAIL_REFRESH_HOURS_INSTALLED_UPDATES = 1
    now = timezone.now().isoformat().replace("+00:00", "Z")
    t = FixtureVsaTransport(_data({1: now}))
    run(mapping, world.engineer_a, t)
    assert _detail_ids(t) == {"d-001"}


def test_refresh_details_now_fetches_one_device_on_the_next_sync(world, vsa):  # noqa: F811
    inst, mapping = vsa
    IntegrationInstance.objects.filter(pk=inst.pk).update(installed_updates_budget=100)
    run(mapping, world.engineer_a, FixtureVsaTransport(_data()))
    asset = Asset.objects.get(external_id="d-002")

    resp = world.client(world.engineer_a).post(f"/api/v1/assets/{asset.id}/refresh-details/")
    assert resp.status_code == 202, resp.content
    asset.refresh_from_db()
    assert asset.details_refresh_requested_at is not None
    event = AuditEvent.objects.get(action="asset.details_refresh_requested")
    assert event.target_id == str(asset.id) and event.customer_id == world.customer_a.id
    queued = SyncRun.objects.get(pk=resp.json()["sync_run_id"])
    assert queued.customer_id == world.customer_a.id

    from apps.integrations import sync
    from apps.integrations.vsa.adapter import VsaXAdapter

    t = FixtureVsaTransport(_data())
    sync.execute(str(queued.id), adapter_factory=lambda i: VsaXAdapter(i, transport=t, sleeper=lambda s: 0))
    assert _detail_ids(t) == {"d-002"}
    # Fetched once: the following sync does not fetch it again.
    t2 = FixtureVsaTransport(_data())
    run(mapping, world.engineer_a, t2)
    assert _detail_ids(t2) == set()


@pytest.mark.parametrize("who", ["viewer_a", "engineer_b", "outsider"])
def test_refresh_details_needs_sync_permission_on_the_devices_customer(world, vsa, who):  # noqa: F811
    _, mapping = vsa
    run(mapping, world.engineer_a, FixtureVsaTransport(_data()))
    asset = Asset.objects.get(external_id="d-001")
    resp = world.client(getattr(world, who)).post(f"/api/v1/assets/{asset.id}/refresh-details/")
    assert resp.status_code == 404
    asset.refresh_from_db()
    assert asset.details_refresh_requested_at is None
    assert not AuditEvent.objects.filter(action="asset.details_refresh_requested").exists()


def test_new_integrations_default_to_five_calls_per_second():
    field = IntegrationInstance._meta.get_field("max_rps")
    assert field.default == Decimal("5.00")
