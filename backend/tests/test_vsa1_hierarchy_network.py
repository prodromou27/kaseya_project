"""VSA1-02 / VSA1-04 / VSA1-06 / VSA2-05: hierarchy, device list, network/disk/security observations.

Fixture-based only (documented examples from https://api.vsax.net/, 2026-11-13) — NOT live validation.
"""

from __future__ import annotations

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.customers.models import CustomerSourceMapping
from apps.integrations import sync
from apps.integrations.models import DatasetGeneration, IntegrationInstance
from apps.integrations.vsa.adapter import ALLOWED_PATHS, VsaXAdapter
from apps.integrations.vsa.fixtures import FakeResponse, FixtureVsaTransport
from apps.integrations.vsa.schema import (
    RecordInvalid,
    normalize_asset,
    normalize_device_ref,
    normalize_group,
    normalize_site,
)
from apps.inventory.models import (
    Asset,
    AssetObservation,
    GroupNode,
    IpAddressObservation,
    NetworkAdapterObservation,
    SiteNode,
)
from apps.inventory.network import CidrStatus, mac_is_locally_administered, mask_prefix, parse_address

pytestmark = pytest.mark.django_db

# Documented examples (abridged to the fields used): GET /api/v3/sites, /groups, /devices.
DOC_SITE = {
    "Id": 101,
    "Name": "MySite1",
    "ContactInformation": {"Phone": "123213123", "Email": "x@example.invalid"},
    "ParentId": 1,
    "ParentName": "MyOrg1",
    "HasCustomFields": False,
}
DOC_GROUP = {
    "Id": 101,
    "Name": "MyGroup1",
    "IsActive": True,
    "ParentSiteId": 6979,
    "ParentSiteName": "Some Site",
    "ParentOrganizationId": 6978,
    "ParentOrganizationName": "Some Org",
    "Notes": None,
}
DOC_DEVICE = {
    "Identifier": "11111111-2222-3333-9B2F-016B8D621AB5",
    "Name": "Computer1",
    "GroupId": 123,
    "GroupName": "Group1",
    "IsAgentInstalled": False,
    "IsMdmEnrolled": False,
    "SiteId": 123,
    "SiteName": "Site1",
    "OrganizationId": 123,
    "OrganizationName": "Organization1",
    "HasCustomFields": False,
}


# ---------------------------------------------------------------- network derivation (NET-01)


@pytest.mark.parametrize(
    ("raw", "mask", "applies", "expected"),
    [
        (
            "192.168.1.10",
            "255.255.255.0",
            True,
            ("192.168.1.10", 4, "private", 24, "192.168.1.0/24", CidrStatus.DERIVED),
        ),
        ("10.20.30.40", "255.255.240.0", True, ("10.20.30.40", 4, "private", 20, "10.20.16.0/20", CidrStatus.DERIVED)),
        ("10.0.0.5", "255.0.255.0", True, ("10.0.0.5", 4, "private", None, "", CidrStatus.INVALID_MASK)),
        ("10.0.0.5", "", True, ("10.0.0.5", 4, "private", None, "", CidrStatus.PREFIX_NOT_REPORTED)),
        ("10.0.0.6", "255.255.255.0", False, ("10.0.0.6", 4, "private", None, "", CidrStatus.PREFIX_NOT_REPORTED)),
        ("203.0.113.9", "255.255.255.0", True, ("203.0.113.9", 4, "private", 24, "203.0.113.0/24", CidrStatus.DERIVED)),
        (
            "169.254.10.1",
            "255.255.0.0",
            True,
            ("169.254.10.1", 4, "link_local", 16, "169.254.0.0/16", CidrStatus.DERIVED),
        ),
        (
            "fe80::b785:162b:b297:74d0%16",
            "255.255.255.0",
            True,
            ("fe80::b785:162b:b297:74d0", 6, "link_local", None, "", CidrStatus.PREFIX_NOT_REPORTED),
        ),
        ("2001:db8::10", "", False, ("2001:db8::10", 6, "private", None, "", CidrStatus.PREFIX_NOT_REPORTED)),
        ("127.0.0.1", "255.0.0.0", True, ("127.0.0.1", 4, "loopback", None, "", CidrStatus.NOT_APPLICABLE)),
        ("not-an-ip", "", False, ("", None, "invalid", None, "", CidrStatus.PREFIX_NOT_REPORTED)),
    ],
)
def test_parse_address(raw, mask, applies, expected):
    p = parse_address(raw, subnet_mask=mask, mask_applies=applies)
    assert (p.address, p.version, p.kind, p.prefix_length, p.network_cidr, p.cidr_status) == expected


def test_ipv6_zone_preserved_separately():
    p = parse_address("fe80::1%16")
    assert p.zone == "16" and p.raw == "fe80::1%16"


@pytest.mark.parametrize(
    ("mask", "prefix"),
    [
        ("255.255.255.255", 32),
        ("0.0.0.0", 0),  # noqa: S104 - a netmask, not a bind address
        ("255.255.254.0", 23),
        ("255.0.255.0", None),
        ("garbage", None),
        ("", None),
    ],
)
def test_mask_prefix(mask, prefix):
    assert mask_prefix(mask) == prefix


def test_locally_administered_mac():
    assert mac_is_locally_administered("0A0027000010") and not mac_is_locally_administered("001122334455")
    assert not mac_is_locally_administered("")


# ---------------------------------------------------------------- normalisation of documented examples


def test_documented_site_group_device_examples():
    site = normalize_site(DOC_SITE)
    assert (site.id, site.name, site.organization_id) == ("101", "MySite1", "1")
    assert "Phone" not in repr(site) and "example.invalid" not in repr(site)  # contact data dropped
    group = normalize_group(DOC_GROUP)
    assert (group.id, group.site_id, group.organization_id, group.is_active) == ("101", "6979", "6978", True)
    assert "Notes" not in repr(group)
    ref = normalize_device_ref(DOC_DEVICE)
    assert (ref.group_id, ref.site_id, ref.organization_id, ref.is_agent_installed) == ("123", "123", "123", False)
    for bad, fn in (
        (({**DOC_SITE, "Id": None}), normalize_site),
        (({**DOC_GROUP, "ParentOrganizationId": None}), normalize_group),
        (({**DOC_DEVICE, "Identifier": ""}), normalize_device_ref),
    ):
        with pytest.raises(RecordInvalid):
            fn(bad)


def test_multi_nic_merge_by_mac_and_sections_absent():
    item = {
        "Identifier": "x",
        "OrganizationId": 1,
        "LocalIpAddresses": [
            {
                "Name": "LAN",
                "PhysicalAddress": "00-11-22-33-44-55",
                "SubnetMask": "255.255.255.0",
                "IpV4": "10.0.0.5",
                "IpV6": "fe80::1%3",
                "DhcpEnabled": True,
                "Gateways": ["10.0.0.1"],
                "DnsServers": ["10.0.0.2"],
            },
            {"Name": "WiFi", "PhysicalAddress": "001122334466", "SubnetMask": "255.255.0.0", "IpV4": "172.16.5.5"},
        ],
        "IpAddresses": [
            {
                "Name": "LAN",
                "MAC": "001122334455",
                "IPs": [{"IP": "10.0.0.5", "V6": False}, {"IP": "10.0.0.99", "V6": False}],
            }
        ],
    }
    a = normalize_asset(item)
    lan = next(n for n in a.network_adapters if n.name == "LAN")
    assert lan.mac == "001122334455" and lan.addresses == ("10.0.0.5", "fe80::1%3", "10.0.0.99")
    assert lan.sources == frozenset({"LocalIpAddresses", "IpAddresses"}) and lan.mask_address == "10.0.0.5"
    assert len(a.network_adapters) == 2
    bare = normalize_asset({"Identifier": "y", "OrganizationId": 1})
    assert (bare.network_adapters, bare.disks, bare.security) == (None, None, None)
    with pytest.raises(RecordInvalid):
        normalize_asset({"Identifier": "z", "OrganizationId": 1, "Disks": "C:"})


def test_new_routes_are_read_only_and_exact():
    allowed = [p.pattern for p in ALLOWED_PATHS]
    assert {"/api/v3/sites", "/api/v3/groups", "/api/v3/devices"} <= set(allowed)
    assert not any(p.fullmatch("/api/v3/devices/abc/move") for p in ALLOWED_PATHS)  # move route never allowed


# ---------------------------------------------------------------- sync (VSA1-02/04)


def asset(
    i: int,
    org: int,
    *,
    site: int = 5,
    group: int = 51,
    ip: str | None = None,
    mac: str | None = None,
    hostname: str | None = None,
    extra_nic: bool = False,
) -> dict:
    a = {
        "Identifier": f"{org}-dev-{i:03d}",
        "Name": hostname or f"PC{i}",
        "OrganizationId": org,
        "SiteId": site,
        "Type": "windows",
        "LastSeenOnline": "2026-11-12T08:00:00Z",
        "InstalledSoftware": [],
        "_GroupId": group,
        "_GroupName": f"G{group}",
        "PublicIpAddress": "198.51.100.7",
        "Disks": [{"Name": "C:", "System": True, "FreePercentage": 12, "TotalValue": 1000}],
        "Security": [{"Type": "Antivirus", "Name": "AV", "Enabled": True}],
    }
    if ip is not None:
        a["LocalIpAddresses"] = [
            {
                "Name": "LAN",
                "PhysicalAddress": mac or f"00AA00{org % 100:02d}{i:04d}"[:12],
                "SubnetMask": "255.255.255.0",
                "IpV4": ip,
                "IpV6": f"fe80::{i}%2",
            }
        ]
        if extra_nic:
            a["LocalIpAddresses"].append(
                {"Name": "VPN", "PhysicalAddress": "0A0000000001", "SubnetMask": "255.255.0.0", "IpV4": "172.20.1.1"}
            )
    return a


@pytest.fixture
def env(world):
    inst = IntegrationInstance.objects.create(
        name="VSA", provider="vsa_x", base_url="https://vsa.invalid", is_fixture=True, enabled=True, max_rps=20
    )
    now = timezone.now()
    ma = CustomerSourceMapping.objects.create(
        customer=world.customer_a,
        integration_instance=inst,
        external_org_id="11",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=now,
    )
    mb = CustomerSourceMapping.objects.create(
        customer=world.customer_b,
        integration_instance=inst,
        external_org_id="22",
        mapping_status="approved",
        reviewed_by=world.super_admin,
        reviewed_at=now,
    )
    return {"inst": inst, "ma": ma, "mb": mb}


def run(mapping, user, transport):
    r, _ = sync.request_sync(mapping, requested_by=user)
    return sync.execute(str(r.id), adapter_factory=lambda i: VsaXAdapter(i, transport=transport, sleeper=lambda s: 0))


def test_sync_collects_hierarchy_and_group_membership(world, env):
    data = [asset(1, 11, ip="10.0.1.10"), asset(2, 11, ip="10.0.1.11", group=52), asset(3, 11, site=6, group=61)]
    t = FixtureVsaTransport(data)
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "completed", r.error_code
    gen = DatasetGeneration.objects.get(pk=r.generation_id)
    assert gen.hierarchy_status == "collected" and gen.device_list_count == 3 and gen.devices_without_asset == 0
    assert set(SiteNode.objects.filter(generation=gen).values_list("external_id", flat=True)) == {"5", "6"}
    assert set(GroupNode.objects.filter(generation=gen).values_list("external_id", flat=True)) == {"51", "52", "61"}
    obs = {o.asset.external_id: o for o in AssetObservation.objects.filter(generation=gen).select_related("asset")}
    assert obs["11-dev-002"].group_external_id == "52" and obs["11-dev-001"].is_agent_installed is True
    calls = [p for p, params in t.calls]
    assert {"/api/v3/sites", "/api/v3/groups", "/api/v3/devices"} <= set(calls)
    for path, params in t.calls:
        if path == "/api/v3/devices":
            assert params["$filter"] == "OrganizationId eq 11" and params["$count"] == "true"
        if path == "/api/v3/groups":
            assert params["$filter"] == "ParentOrganizationId eq 11"


def test_device_list_entries_without_asset_and_foreign_org_are_not_attributed(world, env):
    data = [asset(1, 11, ip="10.0.1.10")]
    devices = [
        {"Identifier": "11-dev-001", "OrganizationId": 11, "GroupId": 51, "SiteId": 5},
        {"Identifier": "mdm-only", "OrganizationId": 11, "GroupId": 51, "SiteId": 5, "IsMdmEnrolled": True},
        {"Identifier": "22-dev-009", "OrganizationId": 22, "GroupId": 99, "SiteId": 9},
    ]
    t = FixtureVsaTransport(data, devices=devices)
    r = run(env["ma"], world.engineer_a, t)
    gen = DatasetGeneration.objects.get(pk=r.generation_id)
    assert gen.devices_without_asset == 1  # the MDM-only entry; org 22 is filtered out entirely
    assert not Asset.objects.filter(external_id__in=["mdm-only", "22-dev-009"]).exists()


def test_hierarchy_failure_keeps_last_good_generation(world, env):
    run(env["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10")]))
    good = DatasetGeneration.objects.get(customer=world.customer_a, is_current=True)
    t = FixtureVsaTransport([asset(1, 11, ip="10.0.1.10")])
    original = t.get
    t.get = lambda url, **kw: FakeResponse(503) if url.endswith("/api/v3/groups") else original(url, **kw)  # type: ignore[method-assign]
    r = run(env["ma"], world.engineer_a, t)
    assert r.state == "partial" and r.error_code == "vendor_unavailable"
    assert DatasetGeneration.objects.get(customer=world.customer_a, is_current=True) == good


def test_multi_nic_device_is_one_device_with_all_addresses(world, env):
    """INV-02."""
    r = run(env["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10", extra_nic=True)]))
    gen = r.generation_id
    assert AssetObservation.objects.filter(generation_id=gen).count() == 1
    assert NetworkAdapterObservation.objects.filter(generation_id=gen).count() == 2
    cidrs = set(IpAddressObservation.objects.filter(generation_id=gen).values_list("network_cidr", flat=True))
    assert cidrs == {"10.0.1.0/24", "172.20.0.0/16", ""}  # IPv6 link-local has no derived prefix


def test_db_rejects_network_row_with_mismatched_customer(world, env):
    r = run(env["ma"], world.engineer_a, FixtureVsaTransport([asset(1, 11, ip="10.0.1.10")]))
    with pytest.raises(IntegrityError, match="customer mismatch"), transaction.atomic():
        IpAddressObservation.objects.filter(generation_id=r.generation_id).update(customer=world.customer_b)


# ---------------------------------------------------------------- API (VSA1-05/06, VSA2-05)


@pytest.fixture
def synced(world, env):
    a = [
        asset(1, 11, ip="10.0.1.10", hostname="SHARED-NAME"),
        asset(2, 11, ip="10.0.1.11"),
        asset(3, 11, ip="10.0.1.10", group=52, mac="00AA00110099"),  # duplicate IP inside customer A
        asset(4, 11, site=6, group=61),
        asset(5, 11, ip="10.0.2.5", extra_nic=True),
    ]
    b = [asset(1, 22, ip="10.0.1.10", hostname="SHARED-NAME", site=8, group=81)]  # same hostname/IP in B
    run(env["ma"], world.engineer_a, FixtureVsaTransport(a))
    run(env["mb"], world.engineer_b, FixtureVsaTransport(b))
    return env


def test_hierarchy_tree_counts_and_scoping(world, synced):
    c = world.client(world.engineer_a)
    data = c.get(f"/api/v1/customers/{world.customer_a.id}/hierarchy/").json()
    (org,) = data["organizations"]
    assert org["external_id"] == "11" and org["counts"]["devices"] == 5
    groups = {g["external_id"]: g for s in org["sites"] for g in s["groups"]}
    assert groups["51"]["counts"]["devices"] == 3 and groups["61"]["counts"]["no_network_data"] == 1
    assert data["unassigned"]["devices"] == 0 and data["hierarchy_status"] == ["collected"]
    assert "81" not in groups  # customer B's group never appears
    assert c.get(f"/api/v1/customers/{world.customer_b.id}/hierarchy/").status_code == 404
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/hierarchy/", {"stale_days": "x"}).status_code == 400


def test_group_network_view_subnets_and_review_flags(world, synced):
    c = world.client(world.engineer_a)
    data = c.get(f"/api/v1/customers/{world.customer_a.id}/groups/51/network/").json()
    assert data["counts"]["devices"] == 3 and data["counts"]["multi_adapter"] == 1
    assert {"cidr": "10.0.1.0/24", "devices": 2, "addresses": 2} in data["subnets"]  # dev 3 (dup IP) is in group 52
    dup = next(d for d in data["duplicate_ips"] if d["address"] == "10.0.1.10")
    assert len(dup["devices"]) == 2 and {d["group_external_id"] for d in dup["devices"]} == {"51", "52"}
    # Customer B has the same IP and hostname: never included in A's duplicate review.
    assert all(d["hostname"] != "SHARED-NAME" or d["group_external_id"] != "81" for d in dup["devices"])
    assert data["addresses_without_derived_subnet"]["ipv6_prefix_not_reported"] >= 2
    assert "not discovered topology" in data["note"]


def test_group_network_idor_and_unknown_group(world, synced):
    c = world.client(world.engineer_a)
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/groups/81/network/").status_code == 404  # B's group
    assert c.get(f"/api/v1/customers/{world.customer_b.id}/groups/81/network/").status_code == 404
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/groups/9999/network/").status_code == 404
    assert c.get(f"/api/v1/customers/{world.customer_a.id}/groups/abc/network/").status_code == 404
    assert (
        world.client(world.engineer_b).get(f"/api/v1/customers/{world.customer_b.id}/groups/81/network/").status_code
        == 200
    )


def test_device_search_by_mac_ip_and_group_filter(world, synced):
    base = f"/api/v1/customers/{world.customer_a.id}/assets/"
    c = world.client(world.viewer_a)
    assert c.get(base, {"search": "00:AA:00:11:00:99"}).json()["count"] == 1
    assert c.get(base, {"search": "00aa.0011.0099"}).json()["count"] == 1
    assert c.get(base, {"search": "10.0.1.10"}).json()["count"] == 2  # two A devices; B's identical IP excluded
    assert c.get(base, {"group_id": "61"}).json()["count"] == 1
    row = c.get(base, {"group_id": "52"}).json()["results"][0]
    assert row["group_external_id"] == "52"


def test_asset_detail_network_hardware_security(world, synced):
    asset_obj = Asset.objects.get(external_id="11-dev-005")
    d = world.client(world.engineer_a).get(f"/api/v1/assets/{asset_obj.id}/").json()["details"]
    assert d["network_status"] == "collected" and len(d["adapters"]) == 2
    assert d["disks"][0]["total_value_raw"] == "1000" and "not documented" in d["units_note"]
    assert d["security"][0] == {"type": "Antivirus", "name": "AV", "enabled": True, "up_to_date": None}
    no_net = Asset.objects.get(external_id="11-dev-004")
    d = world.client(world.engineer_a).get(f"/api/v1/assets/{no_net.id}/").json()["details"]
    assert d["network_status"] == "not_collected" and d["adapters"] == []


def test_demo_tenant_hierarchy_and_network(world, env):
    CustomerSourceMapping.objects.filter(pk=env["ma"].pk).update(external_org_id="1001")
    env["ma"].refresh_from_db()
    r, _ = sync.request_sync(env["ma"], requested_by=world.engineer_a)
    r = sync.execute(str(r.id))
    assert r.state == "completed", r.error_code
    data = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/hierarchy/").json()
    assert data["organizations"][0]["counts"]["devices"] == 130
    gid = next(
        g["external_id"] for s in data["organizations"][0]["sites"] for g in s["groups"] if g["name"] == "Servers"
    )
    net = world.client(world.engineer_a).get(f"/api/v1/customers/{world.customer_a.id}/groups/{gid}/network/").json()
    assert net["counts"]["devices"] > 0 and net["subnets"]


def test_third_party_patch_status_is_explicitly_unavailable(world, synced):
    """VSA3-07 / PATCH-01: no fabricated pending/failed/reboot state, explicit unavailable label."""
    c = world.client(world.engineer_a)
    s = c.get(f"/api/v1/customers/{world.customer_a.id}/software/summary/").json()
    assert s["third_party_patch_status"]["state"] == "UNAVAILABLE"
    assert s["third_party_patch_status"]["live_validation"] == "LIVE_VALIDATION_PENDING"
    a = Asset.objects.get(external_id="11-dev-001")
    assert c.get(f"/api/v1/assets/{a.id}/").json()["third_party_patch_status"]["state"] == "UNAVAILABLE"
