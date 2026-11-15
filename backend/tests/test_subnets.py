"""Customer-wide subnet inventory: observed subnets, group spread and approved-subnet match. Fixture-based."""

from __future__ import annotations

import pytest

from apps.inventory.models import ExpectedSubnet

from .test_vsa1_hierarchy_network import env, synced  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db


def url(customer, tail=""):
    return f"/api/v1/customers/{customer.id}/subnets/{tail}"


def approve(world, scope_type, scope_id, cidr):
    return ExpectedSubnet.objects.create(
        customer=world.customer_a,
        scope_type=scope_type,
        scope_external_id=scope_id,
        cidr=cidr,
        reason="plan",
        state="approved",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
    )


def by_cidr(body):
    return {r["cidr"]: r for r in body["results"]}


def test_observed_subnets_with_group_spread(world, synced):  # noqa: F811
    body = world.client(world.viewer_a).get(url(world.customer_a)).json()
    rows = by_cidr(body)
    # IPv6 link-local and devices without addresses are not subnets
    assert set(rows) == {"10.0.1.0/24", "10.0.2.0/24", "172.20.0.0/16"}
    lan = rows["10.0.1.0/24"]
    assert lan["device_count"] == 3 and lan["mixed_groups"] is True
    assert lan["dominant_group"] == {"group_external_id": "51", "group_name": "G51", "share_pct": 66.7}
    assert all(r["status"] == "unassigned" for r in rows.values())
    assert body["by_status"] == {"assigned": 0, "contained": 0, "unassigned": 3} and body["mixed_groups"] == 1


def test_approved_subnets_mark_assigned_contained_and_outside_devices(world, synced):  # noqa: F811
    approve(world, "group", "51", "10.0.1.0/24")
    approve(world, "site", "5", "10.0.0.0/16")
    body = world.client(world.viewer_a).get(url(world.customer_a)).json()
    rows = by_cidr(body)
    assert rows["10.0.1.0/24"]["status"] == "assigned" and rows["10.0.1.0/24"]["outside_expected"] == 1
    assert rows["10.0.2.0/24"]["status"] == "contained"
    assert rows["10.0.2.0/24"]["expected"]["cidr"] == "10.0.0.0/16"
    assert rows["172.20.0.0/16"]["status"] == "unassigned"
    # Outside first in the list
    assert body["results"][0]["cidr"] == "10.0.1.0/24" and body["devices_outside_expected"] == 1

    devices = world.client(world.viewer_a).get(url(world.customer_a, "devices/"), {"cidr": "10.0.1.0/24"}).json()
    first = devices["results"][0]
    assert first["hostname"] == "PC3" and first["group_external_id"] == "52" and first["outside_expected"] is True
    assert sum(d["outside_expected"] for d in devices["results"]) == 1

    filtered = world.client(world.viewer_a).get(url(world.customer_a), {"status": "unassigned"}).json()
    assert [r["cidr"] for r in filtered["results"]] == ["172.20.0.0/16"]
    assert world.client(world.viewer_a).get(url(world.customer_a), {"outside": "true"}).json()["count"] == 1


def test_retired_or_proposed_subnets_do_not_count(world, synced):  # noqa: F811
    e = approve(world, "group", "51", "10.0.1.0/24")
    ExpectedSubnet.objects.filter(pk=e.pk).update(state="retired")
    rows = by_cidr(world.client(world.viewer_a).get(url(world.customer_a)).json())
    assert rows["10.0.1.0/24"]["status"] == "unassigned"


def test_subnets_are_customer_scoped(world, synced):  # noqa: F811
    assert world.client(world.engineer_b).get(url(world.customer_a)).status_code == 404
    b = world.client(world.engineer_b).get(url(world.customer_b)).json()
    assert [r["cidr"] for r in b["results"]] == ["10.0.1.0/24"] and b["results"][0]["device_count"] == 1
    assert (
        world.client(world.viewer_a).get(url(world.customer_a, "devices/"), {"cidr": "192.0.2.0/24"}).status_code == 404
    )


def test_a_proposed_subnet_shows_as_pending_until_approved(world, synced):  # noqa: F811
    resp = world.client(world.admin_a).post(
        f"/api/v1/customers/{world.customer_a.id}/expected-subnets/",
        {"scope_type": "group", "scope_external_id": "51", "cidr": "10.0.1.0/24", "reason": "Identified from subnets"},
        format="json",
    )
    assert resp.status_code == 201, resp.content
    row = by_cidr(world.client(world.viewer_a).get(url(world.customer_a)).json())["10.0.1.0/24"]
    assert row["status"] == "unassigned"
    assert row["proposed"] == [{"id": resp.json()["id"], "scope_type": "group", "scope_external_id": "51"}]
