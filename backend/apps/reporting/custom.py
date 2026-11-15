"""Custom report builder: pick a data source, columns, filter conditions and sort.

Every source reads the customer's pinned (or current) snapshot through the same read models as the portal pages,
so a custom report never shows data the customer's pages would not. The specification is allowlisted end to end:
source keys, field keys, operators and value types are validated here; nothing user-supplied reaches SQL.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.utils import timezone
from rest_framework import serializers

MAX_COLUMNS = 40
MAX_CONDITIONS = 20

TEXT_OPS = ("contains", "not_contains", "equals", "not_equals", "starts_with", "is_empty", "not_empty")
NUMBER_OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "is_empty", "not_empty")
ENUM_OPS = ("in", "not_in")
BOOL_OPS = ("is_true", "is_false", "is_empty")
DATE_OPS = ("before", "after", "within_days", "older_than_days", "is_empty", "not_empty")
OPS = {"text": TEXT_OPS, "number": NUMBER_OPS, "enum": ENUM_OPS, "bool": BOOL_OPS, "date": DATE_OPS}


@dataclass(frozen=True)
class F:
    label: str
    type: str = "text"  # text | number | enum | bool | date
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Source:
    label: str
    description: str
    fields: dict[str, F]
    default_columns: tuple[str, ...]
    load: Callable[[Any, dict[str, Any]], list[dict[str, Any]]]
    note: str = ""


# ------------------------------------------------------------------------------------------------ loaders


def _group_names(customer: Any, gens: list[Any]) -> dict[tuple[str, str], str]:
    from apps.inventory.models import GroupNode

    return {
        (str(g), e): n
        for g, e, n in GroupNode.objects.filter(customer=customer, generation_id__in=gens).values_list(
            "generation_id", "external_id", "name"
        )
    }


def _observations(customer: Any, pins: dict[str, Any]) -> list[Any]:
    from apps.inventory.models import AssetObservation

    return list(
        AssetObservation.objects.filter(customer=customer, generation_id__in=pins["generation_ids"]).select_related(
            "generation"
        )
    )


def _load_devices(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    groups = _group_names(customer, pins["generation_ids"])
    out = []
    for o in _observations(customer, pins):
        snapshot = o.generation.published_at or o.collected_at
        out.append(
            {
                "hostname": o.hostname,
                "description": o.description,
                "device_type": o.device_type,
                "os_name": o.os_name,
                "os_version": o.os_version,
                "site": o.site_name or o.site_external_id,
                "group": groups.get((str(o.generation_id), o.group_external_id)) or o.group_name,
                "group_id": o.group_external_id,
                "organization_id": o.organization_external_id,
                "agent_version": o.client_version,
                "agent_installed": o.is_agent_installed,
                "last_seen": o.last_seen_online,
                "days_since_seen": round((snapshot - o.last_seen_online).total_seconds() / 86400, 1)
                if o.last_seen_online
                else None,
                "manufacturer": o.manufacturer,
                "model": o.model,
                "serial_number": o.serial_number,
                "domain": o.domain,
                "public_ip": o.public_ip,
                "tags": ", ".join(str(t) for t in (o.tags or [])),
                "software_collected": o.software_status == "collected",
                "installed_programs": o.software_count,
                "cpu": o.cpu_name,
            }
        )
    return out


def _load_health(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.inventory.health import device_rows

    return [
        {
            "hostname": r["hostname"],
            "site": r["site_name"] or r["site_external_id"],
            "group": r["group_name"],
            "device_type": r["device_type"],
            "connectivity": r["connectivity"],
            "days_since_seen": r["days_since_seen"],
            "agent_installed": r["agent_installed"],
            "agent_version_state": r["agent_version"],
            "agent_version": r["client_version"],
            "disk": r["disk"],
            "worst_disk_free_pct": r["worst_disk_free_pct"],
            "antivirus": r["antivirus"],
            "firewall": r["firewall"],
            "patch_policy": r["patch_policy"],
        }
        for r in device_rows(customer.id, generation_ids=pins["generation_ids"])
    ]


def _hosts(customer: Any, pins: dict[str, Any]) -> dict[str, tuple[str, str]]:
    groups = _group_names(customer, pins["generation_ids"])
    return {
        str(o.asset_id): (o.hostname, groups.get((str(o.generation_id), o.group_external_id)) or o.group_name)
        for o in _observations(customer, pins)
    }


def _load_software(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.software.models import ComplianceResult, SoftwareInstallation

    hosts = _hosts(customer, pins)
    results = {
        i: (state, product, ref)
        for i, state, product, ref in ComplianceResult.objects.filter(
            customer=customer, evaluation__is_current=True, evaluation__generation_id__in=pins["generation_ids"]
        ).values_list("installation_id", "state", "product__product", "catalog_revision__reference_version")
    }
    out = []
    for iid, aid, name, publisher, version in SoftwareInstallation.objects.filter(
        customer=customer, generation_id__in=pins["generation_ids"]
    ).values_list("id", "asset_id", "raw_name", "raw_publisher", "raw_version"):
        state, product, ref = results.get(iid, ("unsupported", None, None))
        host, group = hosts.get(str(aid), ("", ""))
        out.append(
            {
                "hostname": host,
                "group": group,
                "program": name,
                "publisher": publisher,
                "version": version,
                "version_state": state,
                "catalog_product": product or "",
                "reference_version": ref or "",
            }
        )
    return out


def _load_os_updates(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.patching.models import DeviceOsUpdate

    hosts = _hosts(customer, pins)
    out = []
    for aid, state, severity, cvss, installed_at, kb, title, release in DeviceOsUpdate.objects.filter(
        customer=customer, generation_id__in=pins["generation_ids"]
    ).values_list(
        "asset_id",
        "state",
        "severity",
        "cvss_score",
        "installed_at_raw",
        "os_update__kb_article",
        "os_update__title",
        "os_update__release_date",
    ):
        host, group = hosts.get(str(aid), ("", ""))
        out.append(
            {
                "hostname": host,
                "group": group,
                "kb": f"KB{kb}" if kb else "",
                "title": title,
                "state": state,
                "severity": severity or "Unspecified",
                "cvss": float(cvss) if cvss is not None else None,
                "release_date": release,
                "installed_at": installed_at,
            }
        )
    return out


def _load_compliance(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.compliance import engine
    from apps.compliance.models import ComplianceBaseline

    baselines = list(ComplianceBaseline.objects.filter(customer=customer, enabled=True).prefetch_related("rules"))
    if not baselines:
        return []
    facts = engine.load_facts(customer.id)
    out = []
    for b in baselines:
        result = engine.evaluate(b, facts)
        labels = {r["id"]: r["label"] for r in result["rules"]}
        for d in result["devices"]:
            failed = [r for r in d["results"] if r["state"] == "fail"]
            unknown = [r for r in d["results"] if r["state"] == "unknown"]
            out.append(
                {
                    "baseline": b.name,
                    "hostname": d["hostname"],
                    "site": d["site_name"] or d["site_external_id"],
                    "group": d["group_name"],
                    "status": d["status"],
                    "failed_rules": len(failed),
                    "failed_high": d["failed_high"],
                    "failing": "; ".join(f"{labels[r['rule_id']]}: {r['reason']}" for r in failed),
                    "unknown": "; ".join(f"{labels[r['rule_id']]}: {r['reason']}" for r in unknown),
                }
            )
    return out


def _load_third_party(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.software import thirdparty

    return [
        {
            "hostname": r["hostname"],
            "group": r["group_name"],
            "program": r["program"],
            "publisher": r["publisher"],
            "installed_version": r["installed_version"],
            "reference_version": r["reference_version"] or "",
            "version_state": r["version_state"],
            "coverage": r["coverage"],
            "rule_action": r["rule_action"],
            "policy": r["policy_name"],
        }
        for r in thirdparty.rows(customer.id)
    ]


def _load_subnets(customer: Any, pins: dict[str, Any]) -> list[dict[str, Any]]:
    from apps.inventory import subnets

    return [
        {
            "cidr": r["cidr"],
            "kind": r["kind"],
            "devices": r["device_count"],
            "groups": ", ".join(g["group_name"] or g["group_external_id"] for g in r["groups"]),
            "group_count": len(r["groups"]),
            "dominant_group": r["dominant_group"]["group_name"],
            "dominant_share_pct": r["dominant_group"]["share_pct"],
            "sites": ", ".join(s["site_name"] or s["site_external_id"] for s in r["sites"]),
            "gateways": ", ".join(r["gateways"]),
            "approved_status": r["status"],
            "approved_scope": f"{r['expected']['scope_type']} {r['expected']['scope_external_id']}"
            if r["expected"]
            else "",
            "devices_outside": r["outside_expected"],
        }
        for r in subnets.collect(customer.id)
    ]


# ------------------------------------------------------------------------------------------------ catalog

STATE_VALUES = ("current", "outdated", "newer", "unknown", "unsupported", "excluded")
LIVE_NOTE = "Evaluated against the snapshot current when the report is generated (re-evaluated on regeneration)."

SOURCES: dict[str, Source] = {
    "devices": Source(
        "Devices",
        "One row per device: identity, placement, OS, agent and hardware.",
        {
            "hostname": F("Device"),
            "description": F("Description"),
            "device_type": F("Device type"),
            "os_name": F("Operating system"),
            "os_version": F("OS version"),
            "site": F("Site"),
            "group": F("Group"),
            "group_id": F("Group ID"),
            "organization_id": F("Organisation ID"),
            "agent_version": F("Agent version"),
            "agent_installed": F("Agent installed", "bool"),
            "last_seen": F("Last seen", "date"),
            "days_since_seen": F("Days since seen", "number"),
            "manufacturer": F("Manufacturer"),
            "model": F("Model"),
            "serial_number": F("Serial number"),
            "domain": F("Domain"),
            "public_ip": F("Public IP"),
            "tags": F("Tags"),
            "software_collected": F("Software collected", "bool"),
            "installed_programs": F("Installed programs", "number"),
            "cpu": F("CPU"),
        },
        ("hostname", "site", "group", "os_name", "os_version", "agent_version", "last_seen"),
        _load_devices,
    ),
    "health": Source(
        "Device health",
        "One row per device: connectivity, agent, disk, antivirus, firewall and patch policy.",
        {
            "hostname": F("Device"),
            "site": F("Site"),
            "group": F("Group"),
            "device_type": F("Device type"),
            "connectivity": F("Connectivity", "enum", ("seen_recently", "offline", "stale", "never_seen")),
            "days_since_seen": F("Days since seen", "number"),
            "agent_installed": F("Agent installed", "enum", ("installed", "not_installed", "unknown")),
            "agent_version_state": F(
                "Agent version state", "enum", ("current", "old", "missing", "unparseable", "not_evaluated")
            ),
            "agent_version": F("Agent version"),
            "disk": F(
                "Disk",
                "enum",
                ("ok", "warning", "critical", "no_disks_reported", "free_pct_not_reported", "not_collected"),
            ),
            "worst_disk_free_pct": F("Lowest disk free %", "number"),
            "antivirus": F(
                "Antivirus",
                "enum",
                (
                    "enabled_up_to_date",
                    "enabled_outdated",
                    "enabled_update_unknown",
                    "disabled",
                    "state_unknown",
                    "not_reported",
                    "not_collected",
                ),
            ),
            "firewall": F(
                "Firewall", "enum", ("enabled", "disabled", "state_unknown", "not_reported", "not_collected")
            ),
            "patch_policy": F("Patch policy", "enum", ("assigned", "explicit_none", "not_reported", "unknown")),
        },
        ("hostname", "group", "connectivity", "disk", "worst_disk_free_pct", "antivirus", "firewall"),
        _load_health,
    ),
    "software": Source(
        "Installed software",
        "One row per installed program per device, with the catalog version state.",
        {
            "hostname": F("Device"),
            "group": F("Group"),
            "program": F("Program"),
            "publisher": F("Publisher"),
            "version": F("Installed version"),
            "version_state": F("Version state", "enum", STATE_VALUES),
            "catalog_product": F("Catalog product"),
            "reference_version": F("Reference version"),
        },
        ("hostname", "program", "publisher", "version", "version_state", "reference_version"),
        _load_software,
    ),
    "os_updates": Source(
        "Windows updates",
        "One row per device and OS update (available or installed).",
        {
            "hostname": F("Device"),
            "group": F("Group"),
            "kb": F("KB"),
            "title": F("Title"),
            "state": F("State", "enum", ("available", "installed")),
            "severity": F("Severity", "enum", ("Critical", "Important", "Moderate", "Low", "Unspecified")),
            "cvss": F("CVSS", "number"),
            "release_date": F("Release date"),
            "installed_at": F("Installed at"),
        },
        ("hostname", "kb", "title", "state", "severity", "release_date"),
        _load_os_updates,
    ),
    "compliance": Source(
        "Compliance",
        "One row per device per enabled baseline, with failing and unknown rules.",
        {
            "baseline": F("Baseline"),
            "hostname": F("Device"),
            "site": F("Site"),
            "group": F("Group"),
            "status": F("Status", "enum", ("pass", "fail", "unknown")),
            "failed_rules": F("Failed rules", "number"),
            "failed_high": F("Failed high-severity rules", "number"),
            "failing": F("Failing rules"),
            "unknown": F("Unknown rules"),
        },
        ("baseline", "hostname", "group", "status", "failed_rules", "failing"),
        _load_compliance,
        LIVE_NOTE,
    ),
    "third_party": Source(
        "Third-party patching",
        "One row per installed program per device: version state and patch-rule coverage.",
        {
            "hostname": F("Device"),
            "group": F("Group"),
            "program": F("Program"),
            "publisher": F("Publisher"),
            "installed_version": F("Installed version"),
            "reference_version": F("Reference version"),
            "version_state": F("Version state", "enum", STATE_VALUES),
            "coverage": F("Patch-rule coverage", "enum", ("covered", "not_covered", "no_policy", "unknown")),
            "rule_action": F("Rule action"),
            "policy": F("Patch policy"),
        },
        ("hostname", "program", "installed_version", "reference_version", "version_state", "coverage", "policy"),
        _load_third_party,
        LIVE_NOTE + " Coverage is policy configuration, never deployment state.",
    ),
    "subnets": Source(
        "Subnets",
        "One row per observed subnet: devices, groups, gateways and approved-subnet match.",
        {
            "cidr": F("Subnet"),
            "kind": F("Address kind", "enum", ("private", "public", "other")),
            "devices": F("Devices", "number"),
            "groups": F("Groups"),
            "group_count": F("Group count", "number"),
            "dominant_group": F("Main group"),
            "dominant_share_pct": F("Main group share %", "number"),
            "sites": F("Sites"),
            "gateways": F("Gateways"),
            "approved_status": F("Approved subnet", "enum", ("assigned", "contained", "unassigned")),
            "approved_scope": F("Approved scope"),
            "devices_outside": F("Devices outside approved scope", "number"),
        },
        ("cidr", "devices", "groups", "dominant_group", "gateways", "approved_status"),
        _load_subnets,
        LIVE_NOTE + " Derived from endpoint-reported addresses, not network topology.",
    ),
}


def catalog() -> list[dict[str, Any]]:
    return [
        {
            "key": k,
            "label": s.label,
            "description": s.description,
            "note": s.note,
            "default_columns": list(s.default_columns),
            "fields": [
                {"key": fk, "label": f.label, "type": f.type, "values": list(f.values), "operators": list(OPS[f.type])}
                for fk, f in s.fields.items()
            ],
        }
        for k, s in SOURCES.items()
    ]


# ------------------------------------------------------------------------------------------------ validation


def clean_spec(spec: dict[str, Any]) -> dict[str, Any]:
    source = SOURCES.get(spec.get("source", ""))
    if source is None:
        raise serializers.ValidationError({"source": "Unknown data source."})
    columns = spec.get("columns") or list(source.default_columns)
    if not isinstance(columns, list) or not columns or len(columns) > MAX_COLUMNS:
        raise serializers.ValidationError({"columns": f"Choose 1 to {MAX_COLUMNS} columns."})
    bad = [c for c in columns if c not in source.fields]
    if bad or len(set(columns)) != len(columns):
        raise serializers.ValidationError({"columns": "Unknown or repeated column."})
    conditions = spec.get("conditions") or []
    if not isinstance(conditions, list) or len(conditions) > MAX_CONDITIONS:
        raise serializers.ValidationError({"conditions": f"At most {MAX_CONDITIONS} conditions."})
    cleaned = []
    for c in conditions:
        if not isinstance(c, dict) or c.get("field") not in source.fields:
            raise serializers.ValidationError({"conditions": "Unknown field in a condition."})
        f = source.fields[c["field"]]
        op = c.get("op")
        if op not in OPS[f.type]:
            raise serializers.ValidationError({"conditions": f"“{op}” is not valid for {f.label}."})
        value = c.get("value")
        if op in ("is_empty", "not_empty", "is_true", "is_false"):
            value = None
        elif f.type == "enum":
            if not isinstance(value, list) or not value or any(v not in f.values for v in value):
                raise serializers.ValidationError({"conditions": f"Pick one or more values for {f.label}."})
        elif f.type == "number" or op in ("within_days", "older_than_days"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise serializers.ValidationError({"conditions": f"{f.label} needs a number."})
        elif f.type == "date":
            try:
                datetime.fromisoformat(str(value))
            except ValueError as exc:
                raise serializers.ValidationError({"conditions": f"{f.label} needs a date (YYYY-MM-DD)."}) from exc
        else:
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise serializers.ValidationError({"conditions": f"{f.label} needs text (max 200 characters)."})
            value = value.strip()
        cleaned.append({"field": c["field"], "op": op, "value": value})
    sort = spec.get("sort") or columns[0]
    if sort not in source.fields:
        raise serializers.ValidationError({"sort": "Unknown sort field."})
    match = spec.get("match", "all")
    if match not in ("all", "any"):
        raise serializers.ValidationError({"match": "Use all or any."})
    title = str(spec.get("title") or "").strip()[:120]
    return {
        "source": spec["source"],
        "columns": columns,
        "conditions": cleaned,
        "match": match,
        "sort": sort,
        "descending": bool(spec.get("descending")),
        "title": title,
    }


# ------------------------------------------------------------------------------------------------ execution


def _as_dt(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        try:
            d = datetime.fromisoformat(v)
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.get_current_timezone())
    return None


def _test(f: F, op: str, actual: Any, value: Any, now: datetime) -> bool:
    empty = actual is None or actual == ""
    if op == "is_empty":
        return empty
    if op == "not_empty":
        return not empty
    if f.type == "bool":
        return actual is True if op == "is_true" else actual is False
    if f.type == "enum":
        return (str(actual) in value) if op == "in" else (str(actual) not in value)
    if f.type == "number":
        if empty:
            return op == "ne"
        a = float(actual)
        return {
            "eq": a == value,
            "ne": a != value,
            "gt": a > value,
            "gte": a >= value,
            "lt": a < value,
            "lte": a <= value,
        }[op]
    if f.type == "date":
        d = _as_dt(actual)
        if d is None:
            return False
        if op == "within_days":
            return d >= now - timedelta(days=value)
        if op == "older_than_days":
            return d < now - timedelta(days=value)
        ref = _as_dt(value)
        return d < ref if op == "before" else d > ref
    a, v = str(actual or "").casefold(), str(value).casefold()
    return {
        "contains": v in a,
        "not_contains": v not in a,
        "equals": a == v,
        "not_equals": a != v,
        "starts_with": a.startswith(v),
    }[op]


def execute(customer: Any, spec: dict[str, Any], pins: dict[str, Any]) -> tuple[list[str], list[dict[str, Any]]]:
    source = SOURCES[spec["source"]]
    rows = source.load(customer, pins)
    now = timezone.now()
    conds = spec["conditions"]
    if conds:
        check = all if spec["match"] == "all" else any
        rows = [
            r
            for r in rows
            if check(_test(source.fields[c["field"]], c["op"], r.get(c["field"]), c["value"], now) for c in conds)
        ]
    key = spec["sort"]
    present = [r for r in rows if r.get(key) not in (None, "")]
    missing = [r for r in rows if r.get(key) in (None, "")]
    present.sort(key=lambda r: r[key].casefold() if isinstance(r[key], str) else r[key], reverse=spec["descending"])
    return spec["columns"], present + missing


def cell(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if v is True:
        return "yes"
    if v is False:
        return "no"
    return "" if v is None else v


def labels(spec: dict[str, Any]) -> tuple[str, ...]:
    source = SOURCES[spec["source"]]
    return tuple(source.fields[c].label for c in spec["columns"])
