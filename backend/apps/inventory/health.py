"""VSA4-01 agent health and VSA4-02 hardware/disk/security observations for one already-authorised customer.

Rules:
* Everything is a **snapshot fact** at the generation's publish time — never live telemetry.
* Every dimension partitions the *whole* device population: per-dimension counts always sum to ``devices``, and
  ``unknown`` / ``not_collected`` / ``not_reported`` buckets are explicit (unknown is neither healthy nor unhealthy).
* Agent-version age is evaluated only against an **approved** minimum version; otherwise ``not_evaluated``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from apps.software.comparator import compare_versions, parse_dotted

from .models import AssetObservation, GroupNode, HealthThresholds
from .queries import current_generations, current_observations

DIMENSIONS: dict[str, tuple[str, ...]] = {
    "connectivity": ("seen_recently", "offline", "stale", "never_seen"),
    "agent_installed": ("installed", "not_installed", "unknown"),
    "agent_version": ("current", "old", "unparseable", "missing", "not_evaluated"),
    "disk": ("ok", "warning", "critical", "free_pct_not_reported", "no_disks_reported", "not_collected"),
    "antivirus": (
        "enabled_up_to_date",
        "enabled_outdated",
        "enabled_update_unknown",
        "disabled",
        "state_unknown",
        "not_reported",
        "not_collected",
    ),
    "firewall": ("enabled", "disabled", "state_unknown", "not_reported", "not_collected"),
}
LABELS: dict[str, dict[str, str]] = {
    "connectivity": {
        "seen_recently": "Seen within the offline threshold",
        "offline": "Offline (past offline threshold, not yet stale)",
        "stale": "Stale (past stale threshold)",
        "never_seen": "No last-seen time reported",
    },
    "agent_installed": {"installed": "Agent installed", "not_installed": "Agent not installed", "unknown": "Unknown"},
    "agent_version": {
        "current": "At or above approved minimum",
        "old": "Below approved minimum",
        "unparseable": "Version not comparable",
        "missing": "No version reported",
        "not_evaluated": "No approved minimum version",
    },
    "disk": {
        "ok": "Free space above warning",
        "warning": "Below warning threshold",
        "critical": "Below critical threshold",
        "free_pct_not_reported": "Disks reported without free %",
        "no_disks_reported": "Section present, no disks",
        "not_collected": "Disk section not collected",
    },
    "antivirus": {
        "enabled_up_to_date": "Enabled, up to date",
        "enabled_outdated": "Enabled, not up to date",
        "enabled_update_unknown": "Enabled, update state unknown",
        "disabled": "Disabled",
        "state_unknown": "Reported, state unknown",
        "not_reported": "No antivirus item reported",
        "not_collected": "Security section not collected",
    },
    "firewall": {
        "enabled": "All reported profiles enabled",
        "disabled": "At least one profile disabled",
        "state_unknown": "Reported, state unknown",
        "not_reported": "No firewall item reported",
        "not_collected": "Security section not collected",
    },
}
NOTES = [
    "Health is derived from the VSA X inventory snapshot at its publish time. It is not live monitoring telemetry.",
    "Unknown, not reported and not collected are separate from healthy/unhealthy and are never counted as either.",
    "Disk TotalValue and MemoryTotal units are not documented by VSA X and are shown as reported.",
]


@dataclass(frozen=True)
class Thresholds:
    offline_hours: int = 24
    stale_days: int = 7
    disk_warning_free_pct: int = 15
    disk_critical_free_pct: int = 5
    minimum_agent_version: str = ""
    source: str = "default"  # default | approved
    approved_id: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "offline_hours": self.offline_hours,
            "stale_days": self.stale_days,
            "disk_warning_free_pct": self.disk_warning_free_pct,
            "disk_critical_free_pct": self.disk_critical_free_pct,
            "minimum_agent_version": self.minimum_agent_version,
            "source": self.source,
            "approved_id": self.approved_id,
        }


def effective_thresholds(customer_id: Any) -> Thresholds:
    t = HealthThresholds.objects.filter(customer_id=customer_id, state=HealthThresholds.State.APPROVED).first()
    if t is None:
        return Thresholds()
    return Thresholds(
        t.offline_hours,
        t.stale_days,
        t.disk_warning_free_pct,
        t.disk_critical_free_pct,
        t.minimum_agent_version,
        "approved",
        str(t.pk),
    )


# ---------------------------------------------------------------------------------------------- classifiers


def connectivity(last_seen: datetime | None, snapshot_at: datetime, t: Thresholds) -> str:
    if last_seen is None:
        return "never_seen"
    if last_seen < snapshot_at - timedelta(days=t.stale_days):
        return "stale"
    if last_seen < snapshot_at - timedelta(hours=t.offline_hours):
        return "offline"
    return "seen_recently"


def agent_installed(value: bool | None) -> str:
    return "unknown" if value is None else ("installed" if value else "not_installed")


def agent_version(version: str, t: Thresholds) -> str:
    if not t.minimum_agent_version:
        return "not_evaluated"
    if not version.strip():
        return "missing"
    if parse_dotted(version) is None:
        return "unparseable"
    return "old" if compare_versions(version, t.minimum_agent_version) < 0 else "current"


def disk(status: str, disks: list[tuple[bool | None, Decimal | None]], t: Thresholds) -> tuple[str, Decimal | None]:
    """Worst free % across system disks (all disks when none is flagged as system)."""
    if status != "collected":
        return "not_collected", None
    if not disks:
        return "no_disks_reported", None
    pool = [d for d in disks if d[0] is True] or disks
    values = [d[1] for d in pool if d[1] is not None]
    if not values:
        return "free_pct_not_reported", None
    worst = min(values)
    if worst < t.disk_critical_free_pct:
        return "critical", worst
    if worst < t.disk_warning_free_pct:
        return "warning", worst
    return "ok", worst


def antivirus(status: str, items: list[tuple[bool | None, bool | None]]) -> str:
    if status != "collected":
        return "not_collected"
    if not items:
        return "not_reported"
    if any(e is False for e, _ in items):
        return "disabled"
    enabled = [u for e, u in items if e is True]
    if not enabled:
        return "state_unknown"
    if any(u is False for u in enabled):
        return "enabled_outdated"
    if all(u is True for u in enabled):
        return "enabled_up_to_date"
    return "enabled_update_unknown"


def firewall(status: str, items: list[bool | None]) -> str:
    if status != "collected":
        return "not_collected"
    if not items:
        return "not_reported"
    if any(e is False for e in items):
        return "disabled"
    if all(e is True for e in items):
        return "enabled"
    return "state_unknown"


# ---------------------------------------------------------------------------------------------- read model


def _row(o: AssetObservation, t: Thresholds, group_name: str, patch_policy: str) -> dict[str, Any]:
    snapshot_at = o.generation.published_at or o.collected_at
    disk_state, worst = disk(o.disks_status, [(d.is_system, d.free_percentage) for d in o.disks.all()], t)
    sec = list(o.security_items.all())
    av = [(s.enabled, s.up_to_date) for s in sec if s.type.casefold() == "antivirus"]
    fw = [s.enabled for s in sec if s.type.casefold() == "firewall"]
    return {
        "asset_id": str(o.asset_id),
        "hostname": o.hostname,
        "site_external_id": o.site_external_id,
        "site_name": o.site_name,
        "group_external_id": o.group_external_id,
        "group_name": group_name,
        "device_type": o.device_type,
        "last_seen_online": o.last_seen_online.isoformat() if o.last_seen_online else None,
        "days_since_seen": round((snapshot_at - o.last_seen_online).total_seconds() / 86400, 1)
        if o.last_seen_online
        else None,
        "snapshot_at": snapshot_at.isoformat(),
        "client_version": o.client_version,
        "connectivity": connectivity(o.last_seen_online, snapshot_at, t),
        "agent_installed": agent_installed(o.is_agent_installed),
        "agent_version": agent_version(o.client_version, t),
        "disk": disk_state,
        "worst_disk_free_pct": None if worst is None else float(worst),
        "antivirus": antivirus(o.security_status, av),
        "firewall": firewall(o.security_status, fw),
        "patch_policy": patch_policy,
        "reported_aggregates": {
            "FirewallEnabled": o.firewall_enabled,
            "AntivirusEnabled": o.antivirus_enabled_raw or None,
            "AntivirusUpToDate": o.antivirus_up_to_date_raw or None,
            "UacEnabled": o.uac_enabled,
        },
        "hardware": {
            "cpu": o.cpu_name,
            "cores": o.cpu_cores_raw,
            "logical_processors": o.logical_processors_raw,
            "memory_total_raw": o.memory_total_raw,
        },
    }


def device_for(o: AssetObservation) -> dict[str, Any]:
    """Health of a single observation (asset detail)."""
    from apps.patching.models import AppliedPolicyObservation

    t = effective_thresholds(o.customer_id)
    group = GroupNode.objects.filter(generation_id=o.generation_id, external_id=o.group_external_id).first()
    pol = AppliedPolicyObservation.objects.filter(observation=o).first()
    return {**_row(o, t, group.name if group else "", pol.patch_state if pol else "unknown"), "thresholds": t.as_dict()}


def device_rows(
    customer_id: Any, t: Thresholds | None = None, generation_ids: list[Any] | None = None
) -> list[dict[str, Any]]:
    from apps.patching.models import AppliedPolicyObservation

    t = t or effective_thresholds(customer_id)
    if generation_ids is None:
        obs = current_observations(customer_id)
    else:
        obs = AssetObservation.objects.filter(customer_id=customer_id, generation_id__in=generation_ids).select_related(
            "asset", "generation"
        )
    obs = list(obs.prefetch_related("disks", "security_items").order_by("hostname", "asset_id"))
    gen_ids = {o.generation_id for o in obs}
    groups = {
        (g.generation_id, g.external_id): g.name
        for g in GroupNode.objects.filter(customer_id=customer_id, generation_id__in=gen_ids)
    }
    policy = dict(
        AppliedPolicyObservation.objects.filter(customer_id=customer_id, generation_id__in=gen_ids).values_list(
            "observation_id", "patch_state"
        )
    )
    return [
        _row(o, t, groups.get((o.generation_id, o.group_external_id), ""), policy.get(o.pk, "unknown")) for o in obs
    ]


def summary(customer_id: Any) -> dict[str, Any]:
    t = effective_thresholds(customer_id)
    rows = device_rows(customer_id, t)
    dims = {}
    for dim, values in DIMENSIONS.items():
        c = Counter(r[dim] for r in rows)
        dims[dim] = {v: c.get(v, 0) for v in values}
    by_group: dict[tuple[str, str, str], Counter[str]] = defaultdict(Counter)
    for r in rows:
        key = (
            r["group_external_id"],
            r["group_name"] or ("(no group)" if not r["group_external_id"] else ""),
            r["site_name"] or r["site_external_id"],
        )
        g = by_group[key]
        g["devices"] += 1
        for dim, bad in (
            ("connectivity", ("offline", "stale", "never_seen")),
            ("agent_version", ("old",)),
            ("disk", ("warning", "critical")),
            ("antivirus", ("disabled", "enabled_outdated")),
            ("firewall", ("disabled",)),
        ):
            if r[dim] in bad:
                g[f"{dim}_attention"] += 1
        if r["agent_installed"] == "not_installed":
            g["agent_not_installed"] += 1
        if r["patch_policy"] in ("explicit_none",):
            g["no_patch_policy"] += 1
    gens = list(current_generations(customer_id))
    return {
        "as_of": [g.published_at.isoformat() if g.published_at else None for g in gens],
        "data_basis": sorted({g.data_basis for g in gens}),
        "devices": len(rows),
        "thresholds": t.as_dict(),
        "dimensions": dims,
        "labels": LABELS,
        "by_group": [
            {"group_external_id": gid, "group_name": name, "site": site, **dict(c)}
            for (gid, name, site), c in sorted(
                by_group.items(), key=lambda kv: (kv[0][2].casefold(), kv[0][1].casefold())
            )
        ],
        "notes": NOTES,
    }


def filter_rows(rows: list[dict[str, Any]], params: Any) -> list[dict[str, Any]]:
    for dim, values in DIMENSIONS.items():
        if (v := params.get(dim)) and v in values:
            rows = [r for r in rows if r[dim] == v]
    if gid := params.get("group_id"):
        rows = [r for r in rows if r["group_external_id"] == gid[:20]]
    if q := params.get("q", "").strip().casefold()[:100]:
        rows = [r for r in rows if q in r["hostname"].casefold()]
    return rows
