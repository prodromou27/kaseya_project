"""Cleanup centre: VSA housekeeping findings for one customer from the current snapshot (read-only).

Every finding is an observation to review in VSA X, never an action. Placeholder serials and locally administered
(virtual/randomised) MAC addresses are excluded from duplicate detection because they collide by design.
"""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from .models import GroupNode, GroupSetting, NetworkAdapterObservation
from .queries import current_generations, current_observations

PLACEHOLDER_SERIALS = re.compile(
    r"^(|0+|none|n/?a|null|default( string)?|to be filled by o\.?e\.?m\.?|system serial number|"
    r"chassis serial number|not specified|not applicable|123456789|serial|oem|invalid)$",
    re.IGNORECASE,
)
CATEGORIES = {
    "duplicate_hostname": "Same hostname on several devices",
    "duplicate_serial": "Same serial number on several devices",
    "duplicate_mac": "Same MAC address on several devices",
    "not_seen": "Not seen recently",
    "never_seen": "Never seen online",
    "no_group": "Not in any group",
    "in_onboarding": "Still in an onboarding group",
    "no_agent": "Agent not installed",
    "missing_serial": "No usable serial number",
}


def _placeholder(serial: str) -> bool:
    return bool(PLACEHOLDER_SERIALS.fullmatch(serial.strip()))


def findings(customer_id: Any, days: int = 90) -> list[dict[str, Any]]:
    gens = list(current_generations(customer_id))
    group_names = {
        (str(g), e): n
        for g, e, n in GroupNode.objects.filter(customer_id=customer_id, generation__in=gens).values_list(
            "generation_id", "external_id", "name"
        )
    }
    onboarding = {
        (str(i), g)
        for i, g in GroupSetting.objects.filter(customer_id=customer_id, is_onboarding=True).values_list(
            "integration_instance_id", "group_external_id"
        )
    }
    obs = list(current_observations(customer_id))
    devices = {}
    for o in obs:
        snapshot = o.generation.published_at or o.collected_at
        devices[str(o.asset_id)] = {
            "asset_id": str(o.asset_id),
            "hostname": o.hostname,
            "site": o.site_name or o.site_external_id,
            "group": group_names.get((str(o.generation_id), o.group_external_id)) or o.group_name,
            "group_external_id": o.group_external_id,
            "serial_number": o.serial_number,
            "last_seen": o.last_seen_online.isoformat() if o.last_seen_online else None,
            "days_since_seen": round((snapshot - o.last_seen_online).total_seconds() / 86400, 1)
            if o.last_seen_online
            else None,
            "_instance": str(o.generation.integration_instance_id),
            "_agent": o.is_agent_installed,
        }
    out: list[dict[str, Any]] = []

    def add(category: str, d: dict[str, Any], detail: str) -> None:
        out.append({"category": category, **{k: v for k, v in d.items() if not k.startswith("_")}, "detail": detail})

    def duplicates(category: str, key_of: dict[str, list[str]], what: str) -> None:
        for value, ids in key_of.items():
            if len(ids) < 2:
                continue
            for aid in ids:
                others = sorted(devices[x]["hostname"] for x in ids if x != aid)
                add(
                    category,
                    devices[aid],
                    f"{what} {value} also on {', '.join(others[:3])}"
                    + (f" and {len(others) - 3} more" if len(others) > 3 else ""),
                )

    by_host: dict[str, list[str]] = defaultdict(list)
    by_serial: dict[str, list[str]] = defaultdict(list)
    for aid, d in devices.items():
        if d["hostname"]:
            by_host[d["hostname"].casefold()].append(aid)
        if d["serial_number"] and not _placeholder(d["serial_number"]):
            by_serial[d["serial_number"].strip().upper()].append(aid)
    by_mac: dict[str, set[str]] = defaultdict(set)
    for aid, mac in (
        NetworkAdapterObservation.objects.filter(
            customer_id=customer_id, generation__in=gens, mac_locally_administered=False
        )
        .exclude(mac="")
        .values_list("asset_id", "mac")
    ):
        if str(aid) in devices and mac.strip("0"):
            by_mac[mac.upper()].add(str(aid))
    duplicates("duplicate_hostname", {devices[v[0]]["hostname"]: v for v in by_host.values()}, "Hostname")
    duplicates("duplicate_serial", by_serial, "Serial")
    duplicates("duplicate_mac", {m: sorted(ids) for m, ids in by_mac.items()}, "MAC")

    for d in devices.values():
        if d["days_since_seen"] is None:
            add("never_seen", d, "No last-seen time reported")
        elif d["days_since_seen"] > days:
            add("not_seen", d, f"Last seen {d['days_since_seen']:g} days before the snapshot")
        if not d["group_external_id"]:
            add("no_group", d, "Not in the source device list / no group reported")
        elif (d["_instance"], d["group_external_id"]) in onboarding:
            add("in_onboarding", d, f"In onboarding group {d['group'] or d['group_external_id']}")
        if d["_agent"] is False:
            add("no_agent", d, "Source reports the agent as not installed")
        if not d["serial_number"] or _placeholder(d["serial_number"]):
            add(
                "missing_serial",
                d,
                f"Serial reported as '{d['serial_number']}'" if d["serial_number"] else "No serial reported",
            )
    order = list(CATEGORIES)
    out.sort(key=lambda f: (order.index(f["category"]), f["hostname"].casefold()))
    return out
