"""Customer-keyed hierarchy and group-network read models (VSA1-06 / VSA2-05).

All queries start from the customer's *current* generations of *approved* mappings, so revocation hides data and
another customer's rows are unreachable. Counts always state their population; missing data is never a zero.
"""

from __future__ import annotations

import ipaddress
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


def _group_counts(customer_id: Any, gen_ids: list[Any], stale_days: int) -> dict[tuple[Any, str], dict[str, int]]:
    cutoff = timezone.now() - timedelta(days=stale_days)
    rows = (
        AssetObservation.objects.filter(customer_id=customer_id, generation_id__in=gen_ids)
        .values("generation_id", "group_external_id")
        .annotate(
            devices=Count("id"),
            stale=Count("id", filter=Q(last_seen_online__lt=cutoff)),
            never_seen=Count("id", filter=Q(last_seen_online__isnull=True)),
            agent_not_installed=Count("id", filter=Q(is_agent_installed=False)),
            no_network_data=Count("id", filter=Q(network_status="not_collected")),
            no_update_data=Count("id", filter=~Q(patch_observation__available_status="collected")),
        )
    )
    return {
        (r["generation_id"], r["group_external_id"]): {
            k: v for k, v in r.items() if k not in {"generation_id", "group_external_id"}
        }
        for r in rows
    }


def hierarchy(customer_id: Any, stale_days: int = 7) -> dict[str, Any]:
    gens = list(current_generations(customer_id).select_related("integration_instance"))
    gen_ids = [g.id for g in gens]
    counts = _group_counts(customer_id, gen_ids, stale_days)
    source_by_generation = {g.id: str(g.integration_instance_id) for g in gens}
    source_names = {g.id: g.integration_instance.name for g in gens}
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

    groups_by_site: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
    listed_groups = set()
    for g in GroupNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).order_by("name"):
        listed_groups.add((g.generation_id, g.external_id))
        groups_by_site[(g.generation_id, g.site_external_id)].append(
            {
                "external_id": g.external_id,
                "instance_id": source_by_generation[g.generation_id],
                "name": g.name,
                "is_active": g.is_active,
                "counts": counts.get((g.generation_id, g.external_id), dict(empty)),
            }
        )
    sites_by_org: dict[tuple[Any, str], list[dict[str, Any]]] = defaultdict(list)
    for s in SiteNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).order_by("name"):
        groups = groups_by_site.pop((s.generation_id, s.external_id), [])
        sites_by_org[(s.generation_id, s.organization_external_id)].append(
            {
                "external_id": s.external_id,
                "name": s.name,
                "groups": groups,
                "counts": total(groups),
            }
        )
    orgs = []
    for o in OrganizationNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).order_by("name"):
        sites = sites_by_org.get((o.generation_id, o.external_id), [])
        orgs.append(
            {
                "external_id": o.external_id,
                "instance_id": source_by_generation[o.generation_id],
                "source": source_names[o.generation_id],
                "name": o.name,
                "sites": sites,
                "counts": total(sites),
            }
        )
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


def group_network(customer_id: Any, group_external_id: str, instance_id: str | None = None) -> dict[str, Any] | None:
    gens = list(current_generations(customer_id))
    from rest_framework.exceptions import ValidationError

    if instance_id:
        gens = [g for g in gens if str(g.integration_instance_id) == str(instance_id)]
    else:
        available_ids = [g.id for g in gens]
        source_ids = set(
            GroupNode.objects.filter(
                customer_id=customer_id, generation_id__in=available_ids, external_id=group_external_id
            ).values_list("generation__integration_instance_id", flat=True)
        )
        source_ids.update(
            AssetObservation.objects.filter(
                customer_id=customer_id, generation_id__in=available_ids, group_external_id=group_external_id
            ).values_list("generation__integration_instance_id", flat=True)
        )
        if len(source_ids) > 1:
            raise ValidationError(
                {"instance": "This group ID exists in multiple VSA instances. Select a source instance."}
            )
        gens = [g for g in gens if g.integration_instance_id in source_ids]
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

    host_by_obs = {m.id: m.hostname for m in members}
    expected, outside, not_evaluated = _expected_subnet_review(
        customer_id, node, members, group_external_id, adapters, host_by_obs
    )
    changes = _address_changes(customer_id, gens, members)

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
        "instance_id": str(gens[0].integration_instance_id) if gens else None,
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
        "expected_subnets": expected,
        "expected_subnets_note": "Expected subnet rules whose source IDs collide across VSA instances are not applied.",
        "outside_expected_subnet": outside,
        "addresses_not_evaluated_against_expectation": not_evaluated,
        "address_changes": changes,
        "review_flags": [
            {"flag": "duplicate_ip", "count": len(duplicate_ips)},
            {"flag": "mac_reuse", "count": len(mac_reuse)},
            {"flag": "outside_expected_subnet", "count": len(outside), "evaluated": bool(expected)},
            {
                "flag": "address_changed_since_previous_snapshot",
                "count": len(changes["devices"]),
                "evaluated": changes["previous_generation"] is not None,
            },
            {"flag": "network_not_collected", "count": sum(1 for m in members if m.network_status == "not_collected")},
            {"flag": "address_without_derived_subnet", "count": sum(unknown_prefix.values())},
        ],
        "flags_note": "Duplicate addresses and MAC reuse are review flags (DHCP churn, VPN, cloned or virtual adapters "
        "are common causes), not proof of misconfiguration.",
    }


def _expected_subnet_review(
    customer_id: Any,
    node: GroupNode | None,
    members: list[AssetObservation],
    group_external_id: str,
    adapters: list[NetworkAdapterObservation],
    host_by_obs: dict[Any, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    """VSA2-05: compare reported addresses with *approved* expected subnets of this group and its site.

    Addresses are evaluated only against expectations of the same IP version; others are counted as not evaluated.
    """
    from .models import ExpectedSubnet

    site_ids = {node.site_external_id} if node is not None and node.site_external_id else set()
    site_ids |= {m.site_external_id for m in members if m.site_external_id}
    rows = list(
        ExpectedSubnet.objects.filter(customer_id=customer_id, state=ExpectedSubnet.State.APPROVED).filter(
            Q(scope_type="group", scope_external_id=group_external_id)
            | Q(scope_type="site", scope_external_id__in=site_ids)
        )
    )
    # Existing expectations have customer-local IDs, not instance keys. Ambiguous rules cannot certify this source.
    generations = current_generations(customer_id)
    counts_by_scope = {
        kind: dict(
            model.objects.filter(
                customer_id=customer_id,
                generation__in=generations,
                external_id__in=[rule.scope_external_id for rule in rows if rule.scope_type == kind],
            )
            .values("external_id")
            .annotate(sources=Count("generation__integration_instance_id", distinct=True))
            .values_list("external_id", "sources")
        )
        for kind, model in (("group", GroupNode), ("site", SiteNode))
    }
    rows = [rule for rule in rows if counts_by_scope[rule.scope_type].get(rule.scope_external_id) == 1]
    nets = [ipaddress.ip_network(e.cidr) for e in rows]
    outside: list[dict[str, Any]] = []
    not_evaluated = 0
    for a in adapters:
        for ip in a.ips.all():
            if not ip.address or not is_review_relevant(ip.kind):
                continue
            addr = ipaddress.ip_address(ip.address)
            same_version = [n for n in nets if n.version == addr.version]
            if not same_version:
                not_evaluated += 1
                continue
            if not any(addr in n for n in same_version):
                outside.append(
                    {
                        "asset_id": str(a.asset_id),
                        "hostname": host_by_obs.get(a.observation_id, ""),
                        "address": ip.address,
                        "adapter": a.name,
                        "mac_locally_administered": a.mac_locally_administered,
                    }
                )
    expected = [
        {"id": str(e.id), "scope_type": e.scope_type, "scope_external_id": e.scope_external_id, "cidr": e.cidr}
        for e in rows
    ]
    return expected, sorted(outside, key=lambda o: (o["hostname"], o["address"])), not_evaluated


def _address_changes(customer_id: Any, gens: list[Any], members: list[AssetObservation]) -> dict[str, Any]:
    """NET-02: review-relevant addresses that differ from the previous *complete* snapshot of the same scope.

    Only devices whose network section was collected in both snapshots are compared. Evaluated for a single current
    generation (one VSA instance); otherwise reported as not evaluated rather than half-compared.
    """
    from apps.integrations.models import DatasetGeneration

    if len(gens) != 1:
        return {"previous_generation": None, "devices": [], "not_evaluated_reason": "several or no current snapshots"}
    current_gen = gens[0]
    previous = (
        DatasetGeneration.objects.filter(
            customer_id=customer_id,
            integration_instance_id=current_gen.integration_instance_id,
            dataset=current_gen.dataset,
            state=DatasetGeneration.State.SUPERSEDED,
            published_at__lt=current_gen.published_at,
        )
        .order_by("-published_at")
        .first()
    )
    if previous is None:
        return {"previous_generation": None, "devices": [], "not_evaluated_reason": "no previous complete snapshot"}
    current = {m.asset_id: m for m in members if m.network_status == "collected"}
    compared = set(
        AssetObservation.objects.filter(
            customer_id=customer_id, generation=previous, asset_id__in=current, network_status="collected"
        ).values_list("asset_id", flat=True)
    )

    def addresses(gen_id: Any) -> dict[Any, set[str]]:
        out: dict[Any, set[str]] = defaultdict(set)
        for asset_id, address, kind in IpAddressObservation.objects.filter(
            customer_id=customer_id, generation_id=gen_id, asset_id__in=compared
        ).values_list("asset_id", "address", "kind"):
            if address and is_review_relevant(kind):
                out[asset_id].add(address)
        return out

    before, after = addresses(previous.id), addresses(current_gen.id)
    devices = []
    for asset_id in sorted(compared, key=str):
        added = after.get(asset_id, set()) - before.get(asset_id, set())
        removed = before.get(asset_id, set()) - after.get(asset_id, set())
        if added or removed:
            devices.append(
                {
                    "asset_id": str(asset_id),
                    "hostname": current[asset_id].hostname,
                    "added": sorted(added),
                    "removed": sorted(removed),
                }
            )
    return {
        "previous_generation": {"id": str(previous.id), "published_at": previous.published_at},
        "compared_devices": len(compared),
        "devices": devices,
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
