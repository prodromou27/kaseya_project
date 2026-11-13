"""VSA2-05 reviewed expected subnets and NET-02 address changes (review flags only). Fixture-based — NOT live."""

from __future__ import annotations

import pytest

from apps.audit.models import AuditEvent
from apps.integrations.vsa.fixtures import FixtureVsaTransport
from apps.inventory.models import ExpectedSubnet

from .test_vsa1_hierarchy_network import asset, env, run, synced  # noqa: F401 - fixtures

pytestmark = pytest.mark.django_db


def url(customer, tail):
    return f"/api/v1/customers/{customer.id}/{tail}"


def flags(body):
    return {f["flag"]: f for f in body["review_flags"]}


def test_no_expectation_means_not_evaluated(world, synced):  # noqa: F811
    body = world.client(world.viewer_a).get(url(world.customer_a, "groups/51/network/")).json()
    assert body["expected_subnets"] == [] and body["outside_expected_subnet"] == []
    assert flags(body)["outside_expected_subnet"] == {"flag": "outside_expected_subnet", "count": 0, "evaluated": False}
    assert body["addresses_not_evaluated_against_expectation"] > 0
    assert body["address_changes"]["not_evaluated_reason"] == "no previous complete snapshot"


def test_two_person_approval_then_outside_addresses_flagged(world, synced):  # noqa: F811
    admin = world.client(world.admin_a)
    base = url(world.customer_a, "expected-subnets/")
    body = {"scope_type": "site", "scope_external_id": "5", "cidr": "10.0.1.0/24", "reason": "HQ LAN"}
    assert world.client(world.engineer_a).post(base, body, format="json").status_code == 404
    assert admin.post(base, {**body, "cidr": "10.0.1.5/24"}, format="json").status_code == 400  # host bits
    assert admin.post(base, {**body, "cidr": "0.0.0.0/0"}, format="json").status_code == 400
    assert admin.post(base, {**body, "scope_external_id": "8"}, format="json").status_code == 400  # B's site
    created = admin.post(base, body, format="json")
    assert created.status_code == 201, created.content
    sid = created.json()["id"]
    assert admin.post(base, body, format="json").status_code == 400  # duplicate active
    net = world.client(world.viewer_a).get(url(world.customer_a, "groups/51/network/")).json()
    assert flags(net)["outside_expected_subnet"]["evaluated"] is False  # proposals do not count
    assert admin.post(f"{base}{sid}/approve/").status_code == 400  # proposer cannot approve
    assert world.client(world.super_admin).post(f"{base}{sid}/approve/").status_code == 200

    net = world.client(world.viewer_a).get(url(world.customer_a, "groups/51/network/")).json()
    outside = {(o["hostname"], o["address"]) for o in net["outside_expected_subnet"]}
    # PC5 has 10.0.2.5 and a VPN adapter 172.20.1.1; IPv6 link-local addresses are never evaluated.
    assert outside == {("PC5", "10.0.2.5"), ("PC5", "172.20.1.1")}
    assert flags(net)["outside_expected_subnet"] == {"flag": "outside_expected_subnet", "count": 2, "evaluated": True}
    assert world.client(world.engineer_b).get(url(world.customer_b, "expected-subnets/")).json() == []
    assert AuditEvent.objects.filter(action__startswith="expected_subnet.", customer=world.customer_a).count() == 2

    assert world.client(world.super_admin).post(f"{base}{sid}/retire/").status_code == 200
    net = world.client(world.viewer_a).get(url(world.customer_a, "groups/51/network/")).json()
    assert flags(net)["outside_expected_subnet"]["evaluated"] is False
    assert ExpectedSubnet.objects.get(pk=sid).state == "retired"


def test_ipv6_expectation_does_not_judge_ipv4(world, synced):  # noqa: F811
    ExpectedSubnet.objects.create(
        customer=world.customer_a,
        scope_type="group",
        scope_external_id="51",
        cidr="2001:db8::/32",
        reason="v6 plan",
        state="approved",
        proposed_by=world.admin_a,
        reviewed_by=world.super_admin,
    )
    net = world.client(world.viewer_a).get(url(world.customer_a, "groups/51/network/")).json()
    assert net["outside_expected_subnet"] == []  # only link-local v6 present; IPv4 not judged by a v6 expectation
    assert net["addresses_not_evaluated_against_expectation"] > 0


def test_address_changes_since_previous_complete_snapshot(world, synced):  # noqa: F811
    a = [
        asset(1, 11, ip="10.0.1.10", hostname="SHARED-NAME"),
        asset(2, 11, ip="10.0.1.99"),  # changed from 10.0.1.11
        asset(3, 11, ip="10.0.1.10", group=52, mac="00AA00110099"),
        asset(4, 11, site=6, group=61),
        asset(5, 11, ip="10.0.2.5", extra_nic=True),
    ]
    run(synced["ma"], world.engineer_a, FixtureVsaTransport(a))
    net = world.client(world.viewer_a).get(url(world.customer_a, "groups/51/network/")).json()
    ch = net["address_changes"]
    assert ch["previous_generation"] is not None
    assert ch["devices"] == [
        {"asset_id": ch["devices"][0]["asset_id"], "hostname": "PC2", "added": ["10.0.1.99"], "removed": ["10.0.1.11"]}
    ]
    assert flags(net)["address_changed_since_previous_snapshot"]["count"] == 1
