"""Cleanup centre: duplicates (placeholders excluded), stale/never seen, placement and data gaps. Fixture-based."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.inventory.models import AssetObservation, GroupSetting, NetworkAdapterObservation

from .test_vsa1_hierarchy_network import env, synced  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db


def url(customer):
    return f"/api/v1/customers/{customer.id}/cleanup/"


def obs(world, hostname):
    return AssetObservation.objects.get(customer=world.customer_a, hostname=hostname, generation__is_current=True)


def by_category(body):
    out = {}
    for item in body["results"]:
        out.setdefault(item["category"], set()).add(item["hostname"])
    return out


def test_cleanup_findings(world, synced):  # noqa: F811
    AssetObservation.objects.filter(pk=obs(world, "PC2").pk).update(serial_number="ABC123", hostname="PC5")
    AssetObservation.objects.filter(pk=obs(world, "PC3").pk).update(serial_number="abc123 ")
    AssetObservation.objects.filter(pk=obs(world, "PC4").pk).update(
        serial_number="To be filled by O.E.M.", last_seen_online=timezone.now() - timedelta(days=200)
    )
    AssetObservation.objects.filter(pk=obs(world, "SHARED-NAME").pk).update(serial_number="To be filled by O.E.M.")
    pc3 = obs(world, "PC3")
    NetworkAdapterObservation.objects.filter(observation=pc3).update(mac="00AA00110001")  # same MAC as device 1
    GroupSetting.objects.create(
        customer=world.customer_a, integration_instance=synced["inst"], group_external_id="61", is_onboarding=True
    )
    body = world.client(world.viewer_a).get(url(world.customer_a), {"days": 90}).json()
    found = by_category(body)
    assert found["duplicate_hostname"] == {"PC5"}  # two devices now named PC5
    assert found["duplicate_serial"] == {"PC5", "PC3"}  # case/space-insensitive; placeholder ignored
    assert found["duplicate_mac"] == {"SHARED-NAME", "PC3"}
    assert found["not_seen"] == {"PC4"}
    assert found["in_onboarding"] == {"PC4"}
    assert "PC4" in found["missing_serial"] and "SHARED-NAME" in found["missing_serial"]
    detail = next(
        i["detail"] for i in body["results"] if i["category"] == "duplicate_serial" and i["hostname"] == "PC3"
    )
    assert detail == "Serial ABC123 also on PC5"
    counts = {c["key"]: c["count"] for c in body["categories"]}
    assert counts["not_seen"] == 1 and counts["duplicate_mac"] == 2
    only = world.client(world.viewer_a).get(url(world.customer_a), {"category": "not_seen"}).json()
    assert {i["hostname"] for i in only["results"]} == {"PC4"}


def test_cleanup_is_scoped_and_validates_days(world, synced):  # noqa: F811
    assert world.client(world.engineer_b).get(url(world.customer_a)).status_code == 404
    assert world.client(world.viewer_a).get(url(world.customer_a), {"days": 1}).status_code == 400
    b = world.client(world.engineer_b).get(url(world.customer_b)).json()
    assert {i["hostname"] for i in b["results"]} == {"SHARED-NAME"}  # B's own device only
