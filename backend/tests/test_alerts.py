"""OPS-04 alerts & watchlists: transitions only, primed on creation, per-user, access re-checked at evaluation."""

from __future__ import annotations

import pytest

from apps.alerts.models import Alert
from apps.customers.models import CustomerMembership

from .test_p1_api import do_sync, synced, vsa_assets  # noqa: F401

pytestmark = pytest.mark.django_db


def subscribe(world, user, customer, kind, params=None):
    return world.client(user).post(
        "/api/v1/alert-subscriptions/",
        {"customer": str(customer.id), "kind": kind, "params": params or {}},
        format="json",
    )


def test_new_devices_raise_one_alert_per_sync_and_only_once(world, synced):  # noqa: F811
    resp = subscribe(world, world.engineer_a, world.customer_a, "new_device")
    assert resp.status_code == 201, resp.content
    assert resp.json()["label"] == "New device appears"
    assert not Alert.objects.exists()  # primed: existing devices never alert

    assert do_sync(synced["mapping_a"], world.engineer_a, vsa_assets(8, 11, "a")).state == "completed"
    alerts = world.client(world.engineer_a).get("/api/v1/alerts/").json()["results"]
    assert len(alerts) == 1
    assert alerts[0]["title"] == "ACME: New device appears (2)" and alerts[0]["body"] == "A-PC6, A-PC7"
    assert alerts[0]["link"] == "/assets"

    assert do_sync(synced["mapping_a"], world.engineer_a, vsa_assets(8, 11, "a")).state == "completed"
    assert Alert.objects.count() == 1  # nothing new, nothing raised
    client = world.client(world.engineer_a)
    assert client.get("/api/v1/alerts/unread-count/").json() == {"unread": 1}
    client.post(f"/api/v1/alerts/{alerts[0]['id']}/read/")
    assert client.get("/api/v1/alerts/unread-count/").json() == {"unread": 0}


def test_forbidden_software_watch(world, synced):  # noqa: F811
    assert (
        subscribe(world, world.viewer_a, world.customer_a, "forbidden_software", {"name": "TeamViewer"}).status_code
        == 201
    )
    data = vsa_assets(6, 11, "a")
    data[2]["InstalledSoftware"].append({"Name": "TeamViewer 15", "Publisher": "TeamViewer", "Version": "15.1"})
    assert do_sync(synced["mapping_a"], world.engineer_a, data).state == "completed"
    alert = Alert.objects.get(user=world.viewer_a)
    assert alert.title == "ACME: “TeamViewer” appears on a device (1)" and alert.body == "A-PC2"


def test_subscriptions_are_scoped_and_access_is_rechecked(world, synced):  # noqa: F811
    resp = subscribe(world, world.engineer_b, world.customer_a, "new_device")
    assert resp.status_code == 400  # no access to customer A: not found
    assert subscribe(world, world.engineer_a, world.customer_a, "offline", {"days": 0}).status_code == 400
    assert subscribe(world, world.engineer_a, world.customer_a, "run_command").status_code == 400
    assert subscribe(world, world.engineer_a, world.customer_a, "new_device").status_code == 201
    CustomerMembership.objects.filter(user=world.engineer_a, customer=world.customer_a).delete()
    assert do_sync(synced["mapping_a"], world.admin_a, vsa_assets(8, 11, "a")).state == "completed"
    assert not Alert.objects.filter(user=world.engineer_a).exists()  # lost access: nothing delivered
    assert world.client(world.engineer_a).get("/api/v1/alert-subscriptions/").json() == []


def test_watch_can_be_paused_and_resumed(world, synced):  # noqa: F811
    sid = subscribe(world, world.engineer_a, world.customer_a, "new_device").json()["id"]
    client = world.client(world.engineer_a)
    resp = client.patch(f"/api/v1/alert-subscriptions/{sid}/", {"enabled": False}, format="json")
    assert resp.status_code == 200, resp.content
    assert resp.json()["enabled"] is False
    assert subscribe(world, world.engineer_a, world.customer_a, "new_device").status_code == 400  # duplicate
    assert client.delete(f"/api/v1/alert-subscriptions/{sid}/").status_code == 204
