"""Customer-wide subnet inventory (read model).

Built only from addresses the source reported with a mask (``IpAddressObservation.network_cidr``, status
``derived``) in the current snapshot. A subnet is an *observation* of endpoint configuration, not network topology.

For each observed subnet: devices, the groups and sites they sit in, gateways, DHCP use and how it relates to
approved expected subnets (VSA2-05):

* ``assigned``  - an approved expected subnet has exactly this CIDR;
* ``contained`` - it lies inside a larger approved expected subnet;
* ``unassigned`` - no approved expected subnet covers it.

When the matching approved subnet is scoped to a group, devices of the subnet that sit in another group are
listed as *outside the approved group* - a review signal (possible misplacement), never an automatic move.
"""

from __future__ import annotations

import ipaddress
from collections import Counter
from typing import Any

from .models import ExpectedSubnet, GroupNode, IpAddressObservation
from .network import is_review_relevant
from .queries import current_generations, current_observations


def _approved(customer_id: Any) -> list[tuple[Any, ExpectedSubnet]]:
    out = []
    for e in ExpectedSubnet.objects.filter(customer_id=customer_id, state=ExpectedSubnet.State.APPROVED):
        try:
            out.append((ipaddress.ip_network(e.cidr, strict=False), e))
        except ValueError:
            continue
    return out


def _match(net: Any, approved: list[tuple[Any, ExpectedSubnet]]) -> tuple[str, ExpectedSubnet | None]:
    exact = next((e for n, e in approved if n == net), None)
    if exact:
        return "assigned", exact
    parents = [(n, e) for n, e in approved if n.version == net.version and net.subnet_of(n)]
    if parents:
        _, e = max(parents, key=lambda p: p[0].prefixlen)  # most specific
        return "contained", e
    return "unassigned", None


def collect(customer_id: Any) -> list[dict[str, Any]]:
    gens = list(current_generations(customer_id))
    # Group names come from the hierarchy (GroupNode); the asset list's GroupName is only a fallback.
    group_names = {
        (g, e): n
        for g, e, n in GroupNode.objects.filter(customer_id=customer_id, generation__in=gens).values_list(
            "generation_id", "external_id", "name"
        )
    }
    obs = {
        str(a): (h, gid, group_names.get((gen, gid)) or gname, sid, sname)
        for a, gen, h, gid, gname, sid, sname in current_observations(customer_id).values_list(
            "asset_id", "generation_id", "hostname", "group_external_id", "group_name", "site_external_id", "site_name"
        )
    }
    approved = _approved(customer_id)
    proposed: dict[str, list[dict[str, str]]] = {}
    for e in ExpectedSubnet.objects.filter(customer_id=customer_id, state=ExpectedSubnet.State.PROPOSED):
        proposed.setdefault(e.cidr, []).append(
            {"id": str(e.id), "scope_type": e.scope_type, "scope_external_id": e.scope_external_id}
        )
    subnets: dict[str, dict[str, Any]] = {}
    for asset_id, cidr, kind, address, gateways, dhcp in (
        IpAddressObservation.objects.filter(customer_id=customer_id, generation__in=gens, cidr_status="derived")
        .exclude(network_cidr="")
        .values_list("asset_id", "network_cidr", "kind", "address", "adapter__gateways", "adapter__dhcp_enabled")
        .iterator()
    ):
        if not is_review_relevant(kind):
            continue
        aid = str(asset_id)
        if aid not in obs:
            continue
        s = subnets.setdefault(
            cidr,
            {"cidr": cidr, "kind": kind, "devices": {}, "gateways": Counter(), "dhcp": Counter()},
        )
        s["devices"].setdefault(aid, address)
        for g in gateways or []:
            if isinstance(g, str) and g:
                s["gateways"][g] += 1
        s["dhcp"]["yes" if dhcp else "no" if dhcp is False else "unknown"] += 1
    rows = []
    for cidr, s in subnets.items():
        try:
            net = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            continue
        status, expected = _match(net, approved)
        groups: Counter[tuple[str, str]] = Counter()
        sites: Counter[tuple[str, str]] = Counter()
        devices = []
        for aid, address in s["devices"].items():
            host, gid, gname, sid, sname = obs[aid]
            groups[(gid, gname)] += 1
            sites[(sid, sname)] += 1
            devices.append(
                {
                    "asset_id": aid,
                    "hostname": host,
                    "address": address,
                    "group_external_id": gid,
                    "group_name": gname,
                    "site_external_id": sid,
                    "site_name": sname,
                }
            )
        expected_group = expected.scope_external_id if expected and expected.scope_type == "group" else ""
        expected_site = expected.scope_external_id if expected and expected.scope_type == "site" else ""
        outside = [
            d
            for d in devices
            if (expected_group and d["group_external_id"] != expected_group)
            or (expected_site and d["site_external_id"] != expected_site)
        ]
        (dominant_gid, dominant_gname), dominant_n = groups.most_common(1)[0]
        rows.append(
            {
                "cidr": cidr,
                "version": net.version,
                "kind": s["kind"],
                "prefix_length": net.prefixlen,
                "device_count": len(devices),
                "groups": [
                    {"group_external_id": g, "group_name": n, "devices": c} for (g, n), c in groups.most_common()
                ],
                "sites": [{"site_external_id": i, "site_name": n, "devices": c} for (i, n), c in sites.most_common()],
                "dominant_group": {
                    "group_external_id": dominant_gid,
                    "group_name": dominant_gname,
                    "share_pct": round(100 * dominant_n / len(devices), 1),
                },
                "gateways": [g for g, _ in s["gateways"].most_common(3)],
                "dhcp": dict(s["dhcp"]),
                "status": status,
                "expected": None
                if expected is None
                else {
                    "id": str(expected.id),
                    "cidr": expected.cidr,
                    "scope_type": expected.scope_type,
                    "scope_external_id": expected.scope_external_id,
                },
                "proposed": proposed.get(cidr, []),
                "outside_expected": len(outside),
                "mixed_groups": len(groups) > 1,
                "_devices": devices,
                "_outside": {d["asset_id"] for d in outside},
            }
        )
    rows.sort(key=lambda r: (-r["outside_expected"], r["status"] != "unassigned", -r["device_count"], r["cidr"]))
    return rows


def public(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_status = Counter(r["status"] for r in rows)
    return {
        "subnets": len(rows),
        "by_status": {k: by_status.get(k, 0) for k in ("assigned", "contained", "unassigned")},
        "mixed_groups": sum(1 for r in rows if r["mixed_groups"]),
        "devices_outside_expected": sum(r["outside_expected"] for r in rows),
    }


def devices(row: dict[str, Any]) -> list[dict[str, Any]]:
    out = [{**d, "outside_expected": d["asset_id"] in row["_outside"]} for d in row["_devices"]]
    return sorted(out, key=lambda d: (not d["outside_expected"], d["hostname"].casefold()))


def filter_rows(rows: list[dict[str, Any]], params: Any) -> list[dict[str, Any]]:
    status = params.get("status", "")
    search = str(params.get("search", ""))[:64].strip().casefold()
    out = rows
    if status in ("assigned", "contained", "unassigned"):
        out = [r for r in out if r["status"] == status]
    if params.get("mixed") == "true":
        out = [r for r in out if r["mixed_groups"]]
    if params.get("outside") == "true":
        out = [r for r in out if r["outside_expected"]]
    if search:
        out = [
            r
            for r in out
            if search in r["cidr"]
            or any(search in g["group_name"].casefold() for g in r["groups"])
            or any(search in g for g in r["gateways"])
        ]
    return out
