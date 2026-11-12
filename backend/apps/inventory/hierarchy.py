"""Customer-keyed hierarchy and group-network read models (VSA1-06 / VSA2-05).

All queries start from the customer's *current* generations of *approved* mappings, so revocation hides data and
another customer's rows are unreachable. Counts always state their population; missing data is never a zero.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from django.db.models import Count, Q
from django.utils import timezone

from .models import (
    AssetObservation,
    GroupNode,
    IpAddressObservation,
    NetworkAdapterObservation,
    OrganizationNode,
    SiteNode,
)
from .network import is_review_relevant
from .queries import current_generations

NETWORK_NOTE = (
    "Reported adapter data per device from VSA X. Subnets are derived only from a reported IPv4 address and its "
    "reported subnet mask. This is not discovered topology, VLAN or authoritative subnet data."
)


def _group_counts(customer_id: Any, gen_ids: list[Any], stale_days: int) -> dict[str, dict[str, int]]:
    cutoff = timezone.now() - timedelta(days=stale_days)
    rows = (
        AssetObservation.objects.filter(customer_id=customer_id, generation_id__in=gen_ids)
        .values("group_external_id")
        .annotate(
            devices=Count("id"),
            stale=Count("id", filter=Q(last_seen_online__lt=cutoff)),
            never_seen=Count("id", filter=Q(last_seen_online__isnull=True)),
            agent_not_installed=Count("id", filter=Q(is_agent_installed=False)),
            no_network_data=Count("id", filter=Q(network_status="not_collected")),
            no_update_data=Count("id", filter=~Q(patch_observation__available_status="collected")),
        )
    )
    return {r["group_external_id"]: {k: v for k, v in r.items() if k != "group_external_id"} for r in rows}


def hierarchy(customer_id: Any, stale_days: int = 7) -> dict[str, Any]:
    gens = list(current_generations(customer_id))
    gen_ids = [g.id for g in gens]
    counts = _group_counts(customer_id, gen_ids, stale_days)
    empty = {
        "devices": 0,
        "stale": 0,
        "never_seen": 0,
        "agent_not_installed": 0,
        "no_network_data": 0,
        "no_update_data": 0,
    }

    def total(items: list[dict[str, Any]]) -> dict[str, int]:
        out = dict(empty)
        for it in items:
            for k in out:
                out[k] += it["counts"][k]
        return out

    groups_by_site: dict[str, list[dict[str, Any]]] = defaultdict(list)
    listed_groups = set()
    for g in GroupNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).order_by("name"):
        listed_groups.add(g.external_id)
        groups_by_site[g.site_external_id].append(
            {
                "external_id": g.external_id,
                "name": g.name,
                "is_active": g.is_active,
                "counts": counts.get(g.external_id, dict(empty)),
            }
        )
    sites_by_org: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for s in SiteNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).order_by("name"):
        groups = groups_by_site.pop(s.external_id, [])
        sites_by_org[s.organization_external_id].append(
            {
                "external_id": s.external_id,
                "name": s.name,
                "groups": groups,
                "counts": total(groups),
            }
        )
    orgs = []
    for o in OrganizationNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).order_by("name"):
        sites = sites_by_org.get(o.external_id, [])
        orgs.append({"external_id": o.external_id, "name": o.name, "sites": sites, "counts": total(sites)})
    # Devices whose group was not in the active group list, or that were absent from the device list.
    unassigned = dict(empty)
    for gid, c in counts.items():
        if gid not in listed_groups:
            for k in unassigned:
                unassigned[k] += c[k]
    return {
        "as_of": [g.published_at for g in gens],
        "generation_ids": [str(g.id) for g in gens],
        "data_basis": sorted({g.data_basis for g in gens}),
        "hierarchy_status": sorted({g.hierarchy_status for g in gens}),
        "devices_without_asset": sum(g.devices_without_asset or 0 for g in gens),
        "stale_days": stale_days,
        "organizations": orgs,
        "unassigned": unassigned,
        "note": "Names are labels; VSA IDs are the keys. Counts cover devices in the current published inventory.",
    }


def group_network(customer_id: Any, group_external_id: str) -> dict[str, Any] | None:
    gens = list(current_generations(customer_id))
    gen_ids = [g.id for g in gens]
    node = GroupNode.objects.filter(
        customer_id=customer_id, generation_id__in=gen_ids, external_id=group_external_id
    ).first()
    members = list(
        AssetObservation.objects.filter(
            customer_id=customer_id, generation_id__in=gen_ids, group_external_id=group_external_id
        )
        .select_related("asset")
        .order_by("hostname")
    )
    if node is None and not members:
        return None
    member_ids = [m.id for m in members]
    adapters = list(NetworkAdapterObservation.objects.filter(observation_id__in=member_ids).prefetch_related("ips"))
    by_obs: dict[Any, list[NetworkAdapterObservation]] = defaultdict(list)
    for a in adapters:
        by_obs[a.observation_id].append(a)

    subnets: dict[str, dict[str, Any]] = {}
    unknown_prefix = Counter()
    member_addresses: set[str] = set()
    member_macs: set[str] = set()
    gateways, dns = Counter(), Counter()
    for a in adapters:
        if a.mac:
            member_macs.add(a.mac)
        gateways.update(a.gateways)
        dns.update(a.dns_servers)
        for ip in a.ips.all():
            if ip.network_cidr:
                entry = subnets.setdefault(ip.network_cidr, {"cidr": ip.network_cidr, "devices": set(), "addresses": 0})
                entry["devices"].add(a.asset_id)
                entry["addresses"] += 1
            elif ip.version is not None:
                unknown_prefix[f"ipv{ip.version}_{ip.cidr_status}"] += 1
            else:
                unknown_prefix["unparseable"] += 1
            if ip.address and is_review_relevant(ip.kind):
                member_addresses.add(ip.address)

    # Duplicate-address review: the same address on more than one device anywhere in THIS customer's inventory.
    dupes = defaultdict(set)
    hostnames: dict[Any, tuple[str, str]] = {}
    for row in IpAddressObservation.objects.filter(
        customer_id=customer_id, generation_id__in=gen_ids, address__in=member_addresses
    ).values("address", "asset_id", "adapter__observation__hostname", "adapter__observation__group_external_id"):
        dupes[row["address"]].add(row["asset_id"])
        hostnames[row["asset_id"]] = (
            row["adapter__observation__hostname"],
            row["adapter__observation__group_external_id"],
        )
    duplicate_ips = [
        {
            "address": addr,
            "devices": [
                {"asset_id": str(a), "hostname": hostnames[a][0], "group_external_id": hostnames[a][1]}
                for a in sorted(assets, key=str)
            ],
        }
        for addr, assets in sorted(dupes.items())
        if len(assets) > 1
    ]
    mac_rows = defaultdict(set)
    for row in NetworkAdapterObservation.objects.filter(
        customer_id=customer_id, generation_id__in=gen_ids, mac__in=member_macs
    ).values("mac", "asset_id"):
        mac_rows[row["mac"]].add(row["asset_id"])
    mac_reuse = [{"mac": mac, "device_count": len(a)} for mac, a in sorted(mac_rows.items()) if len(a) > 1]

    devices = []
    for m in members:
        nics = by_obs.get(m.id, [])
        devices.append(
            {
                "asset_id": str(m.asset_id),
                "hostname": m.hostname,
                "last_seen_online": m.last_seen_online,
                "network_status": m.network_status,
                "public_ip": m.public_ip,
                "adapters": [adapter_payload(a) for a in nics],
            }
        )
    with_addresses = sum(1 for d in devices if any(a["addresses"] for a in d["adapters"]))
    return {
        "group": None
        if node is None
        else {
            "external_id": node.external_id,
            "name": node.name,
            "is_active": node.is_active,
            "site_external_id": node.site_external_id,
            "organization_external_id": node.organization_external_id,
        },
        "group_listed": node is not None,
        "as_of": [g.published_at for g in gens],
        "data_basis": sorted({g.data_basis for g in gens}),
        "counts": {
            "devices": len(members),
            "with_reported_addresses": with_addresses,
            "network_not_collected": sum(1 for m in members if m.network_status == "not_collected"),
            "multi_adapter": sum(1 for d in devices if sum(1 for a in d["adapters"] if a["addresses"]) > 1),
        },
        "subnets": sorted(
            ({"cidr": s["cidr"], "devices": len(s["devices"]), "addresses": s["addresses"]} for s in subnets.values()),
            key=lambda s: (-s["devices"], s["cidr"]),
        ),
        "addresses_without_derived_subnet": dict(unknown_prefix),
        "duplicate_ips": duplicate_ips,
        "mac_reuse": mac_reuse,
        "gateways": [{"value": k, "adapters": v} for k, v in gateways.most_common(20)],
        "dns_servers": [{"value": k, "adapters": v} for k, v in dns.most_common(20)],
        "public_ips": [
            {"value": k, "devices": v} for k, v in Counter(m.public_ip for m in members if m.public_ip).most_common(20)
        ],
        "devices": devices,
        "note": NETWORK_NOTE,
        "flags_note": "Duplicate addresses and MAC reuse are review flags (DHCP churn, VPN, cloned or virtual adapters "
        "are common causes), not proof of misconfiguration.",
    }


def adapter_payload(a: NetworkAdapterObservation) -> dict[str, Any]:
    return {
        "name": a.name,
        "mac": a.mac,
        "mac_locally_administered": a.mac_locally_administered,
        "dhcp_enabled": a.dhcp_enabled,
        "subnet_mask": a.subnet_mask,
        "gateways": a.gateways,
        "dns_servers": a.dns_servers,
        "sources": a.sources,
        "addresses": [
            {
                "raw": ip.raw,
                "address": ip.address,
                "version": ip.version,
                "kind": ip.kind,
                "network_cidr": ip.network_cidr,
                "cidr_status": ip.cidr_status,
            }
            for ip in a.ips.all()
        ],
    }
