"""Evaluate compliance baselines against the current published inventory of one customer.

Pure read model: facts come from the same current-generation queries as the rest of the portal (still-approved
mappings only). Every rule returns ``pass`` / ``fail`` / ``unknown`` plus a short reason. Missing source data is
``unknown`` (never a silent pass or fail). Device status: ``fail`` if any rule fails, else ``unknown`` if any rule
is unknown, else ``pass``. Score = pass / (pass + fail); unknown devices are reported separately.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from rest_framework.exceptions import ValidationError

from .models import BaselineRule, ComplianceBaseline

Kind = BaselineRule.Kind
PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"
_VERSION = re.compile(r"^\d+(?:\.\d+){0,5}$")


# ------------------------------------------------------------------------------------------------ validation


def _text(params: dict[str, Any], key: str, *, required: bool = True, max_len: int = 120) -> str:
    value = params.get(key, "")
    if not isinstance(value, str):
        raise ValidationError({"params": f"{key} must be text."})
    value = value.strip()
    if required and not value:
        raise ValidationError({"params": f"{key} is required."})
    if len(value) > max_len:
        raise ValidationError({"params": f"{key} is too long."})
    return value


def _number(params: dict[str, Any], key: str, low: int, high: int) -> int:
    value = params.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ValidationError({"params": f"{key} must be a number from {low} to {high}."})
    return int(value)


def _version(value: str) -> str:
    if value and not _VERSION.fullmatch(value):
        raise ValidationError({"params": "Versions are dotted numbers, e.g. 10.0.22631."})
    return value


def clean_params(kind: str, params: Any) -> dict[str, Any]:
    """Allowlisted parameters per rule kind; anything else is rejected."""
    if not isinstance(params, dict):
        raise ValidationError({"params": "Parameters must be an object."})
    if kind == Kind.REQUIRED_SOFTWARE:
        return {"name": _text(params, "name"), "min_version": _version(_text(params, "min_version", required=False))}
    if kind == Kind.FORBIDDEN_SOFTWARE:
        return {"name": _text(params, "name")}
    if kind == Kind.OS_MIN_VERSION:
        return {"version": _version(_text(params, "version"))}
    if kind == Kind.DISK_FREE_MIN:
        return {"percent": _number(params, "percent", 1, 99)}
    if kind == Kind.MAX_DAYS_OFFLINE:
        return {"days": _number(params, "days", 1, 365)}
    if kind == Kind.SCRIPT_VALUE:
        from apps.automation.models import ScriptCollector

        collector = ScriptCollector.objects.filter(pk=_text(params, "collector", max_len=36)).first()
        variable = _text(params, "variable", max_len=100)
        if collector is None or variable not in collector.allowed_variables:
            raise ValidationError({"params": "Pick a script collector and one of its allowed variables."})
        op = _text(params, "op", max_len=16)
        if op not in ("equals", "not_equals", "contains", "at_least"):
            raise ValidationError({"params": "Use equals, not_equals, contains or at_least."})
        value = _text(params, "value", max_len=200)
        if op == "at_least":
            try:
                float(value)
            except ValueError as exc:
                raise ValidationError({"params": "at_least needs a number."}) from exc
        return {
            "collector": str(collector.id),
            "label": collector.label,
            "variable": variable,
            "op": op,
            "value": value,
        }
    if kind in Kind.values:
        return {}
    raise ValidationError({"kind": "Unknown rule kind."})


def describe(kind: str, params: dict[str, Any]) -> str:
    if kind == Kind.REQUIRED_SOFTWARE:
        v = f" (version {params['min_version']} or later)" if params.get("min_version") else ""
        return f"“{params['name']}” is installed{v}"
    if kind == Kind.FORBIDDEN_SOFTWARE:
        return f"“{params['name']}” is not installed"
    if kind == Kind.OS_MIN_VERSION:
        return f"OS version {params['version']} or later"
    if kind == Kind.DISK_FREE_MIN:
        return f"System disk at least {params['percent']}% free"
    if kind == Kind.MAX_DAYS_OFFLINE:
        return f"Seen within {params['days']} days"
    if kind == Kind.SCRIPT_VALUE:
        words = {"equals": "is", "not_equals": "is not", "contains": "contains", "at_least": "is at least"}
        return f"{params.get('label', 'Script')}: {params['variable']} {words[params['op']]} “{params['value']}”"
    return Kind(kind).label


# ------------------------------------------------------------------------------------------------ facts


def _vt(value: str) -> tuple[int, ...] | None:
    value = (value or "").strip()
    match = re.match(r"^v?(\d+(?:\.\d+){0,5})", value)
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def _at_least(actual: str, minimum: str) -> bool | None:
    a, m = _vt(actual), _vt(minimum)
    if a is None or m is None:
        return None
    width = max(len(a), len(m))
    return a + (0,) * (width - len(a)) >= m + (0,) * (width - len(m))


@dataclass
class DeviceFacts:
    asset_id: str
    hostname: str
    site_external_id: str
    site_name: str
    group_external_id: str
    group_name: str
    device_type: str
    health: dict[str, Any]
    os_name: str = ""
    os_version: str = ""
    software_collected: bool = False
    software: list[tuple[str, str]] = field(default_factory=list)  # (name, version)
    outdated: list[str] = field(default_factory=list)
    updates_collected: bool = False
    critical_available: int = 0
    script_values: dict[str, dict[str, Any]] = field(default_factory=dict)  # collector id -> {state, values}


def load_facts(customer_id: Any) -> list[DeviceFacts]:
    from apps.inventory.health import device_rows
    from apps.inventory.queries import current_generations, current_observations
    from apps.patching.models import DeviceOsUpdate, PatchObservation
    from apps.software.models import SoftwareInstallation
    from apps.software.queries import current_results

    gens = list(current_generations(customer_id))
    facts: dict[str, DeviceFacts] = {}
    for row in device_rows(customer_id):
        facts[row["asset_id"]] = DeviceFacts(
            asset_id=row["asset_id"],
            hostname=row["hostname"],
            site_external_id=row["site_external_id"],
            site_name=row["site_name"],
            group_external_id=row["group_external_id"],
            group_name=row["group_name"],
            device_type=row["device_type"],
            health=row,
        )
    for asset_id, os_name, os_version, sw_status in current_observations(customer_id).values_list(
        "asset_id", "os_name", "os_version", "software_status"
    ):
        f = facts.get(str(asset_id))
        if f:
            f.os_name, f.os_version, f.software_collected = os_name, os_version, sw_status == "collected"
    for asset_id, name, version in (
        SoftwareInstallation.objects.filter(customer_id=customer_id, generation__in=gens)
        .values_list("asset_id", "raw_name", "raw_version")
        .iterator()
    ):
        f = facts.get(str(asset_id))
        if f:
            f.software.append((name, version))
    for asset_id, name in (
        current_results(customer_id).filter(state="outdated").values_list("asset_id", "installation__raw_name")
    ):
        f = facts.get(str(asset_id))
        if f:
            f.outdated.append(name)
    for asset_id, status in PatchObservation.objects.filter(customer_id=customer_id, generation__in=gens).values_list(
        "asset_id", "available_status"
    ):
        f = facts.get(str(asset_id))
        if f:
            f.updates_collected = status in ("collected", "carried_forward")
    critical: dict[str, int] = defaultdict(int)
    for (asset_id,) in DeviceOsUpdate.objects.filter(
        customer_id=customer_id, generation__in=gens, state="available", severity__iexact="critical"
    ).values_list("asset_id"):
        critical[str(asset_id)] += 1
    for asset_id, n in critical.items():
        if asset_id in facts:
            facts[asset_id].critical_available = n
    from apps.automation.models import DeviceScriptValue

    for v in DeviceScriptValue.objects.filter(customer_id=customer_id, collector__enabled=True):
        f = facts.get(str(v.asset_id))
        if f:
            f.script_values[str(v.collector_id)] = {"state": v.state, "values": v.values}
    return list(facts.values())


# ------------------------------------------------------------------------------------------------ rules


def _matching(software: list[tuple[str, str]], needle: str) -> list[tuple[str, str]]:
    n = needle.casefold()
    return [(name, version) for name, version in software if n in name.casefold()]


def evaluate_rule(kind: str, params: dict[str, Any], f: DeviceFacts) -> tuple[str, str]:
    h = f.health
    if (
        kind in (Kind.REQUIRED_SOFTWARE, Kind.FORBIDDEN_SOFTWARE, Kind.NO_OUTDATED_SOFTWARE)
        and not f.software_collected
    ):
        return UNKNOWN, "Installed software not collected"
    if kind == Kind.REQUIRED_SOFTWARE:
        found = _matching(f.software, params["name"])
        if not found:
            return FAIL, "Not installed"
        minimum = params.get("min_version") or ""
        if not minimum:
            return PASS, f"Installed: {found[0][0]} {found[0][1]}".strip()
        checks = [(_at_least(v, minimum), n, v) for n, v in found]
        if any(ok for ok, _, _ in checks):
            return PASS, "Installed at the required version"
        if all(ok is None for ok, _, _ in checks):
            return UNKNOWN, "Installed, version not comparable"
        n, v = found[0]
        return FAIL, f"{n} {v} is older than {minimum}"
    if kind == Kind.FORBIDDEN_SOFTWARE:
        found = _matching(f.software, params["name"])
        return (FAIL, f"Installed: {found[0][0]}") if found else (PASS, "Not installed")
    if kind == Kind.OS_MIN_VERSION:
        ok = _at_least(f.os_version, params["version"])
        if ok is None:
            return (
                UNKNOWN,
                "OS version not reported" if not f.os_version else f"OS version {f.os_version} not comparable",
            )
        return (PASS, f"OS {f.os_version}") if ok else (FAIL, f"OS {f.os_version} is older than {params['version']}")
    if kind == Kind.ANTIVIRUS_HEALTHY:
        state = h["antivirus"]
        if state == "enabled_up_to_date":
            return PASS, "Enabled and up to date"
        if state in ("disabled", "enabled_outdated"):
            return FAIL, state.replace("_", " ").capitalize()
        return UNKNOWN, "Antivirus state not reported"
    if kind == Kind.FIREWALL_ENABLED:
        state = h["firewall"]
        if state == "enabled":
            return PASS, "Enabled"
        if state == "disabled":
            return FAIL, "At least one profile disabled"
        return UNKNOWN, "Firewall state not reported"
    if kind == Kind.DISK_FREE_MIN:
        free = h["worst_disk_free_pct"]
        if free is None:
            return UNKNOWN, "System disk free space not reported"
        return (PASS, f"{free:g}% free") if free >= params["percent"] else (FAIL, f"Only {free:g}% free")
    if kind == Kind.MAX_DAYS_OFFLINE:
        days = h["days_since_seen"]
        if days is None:
            return UNKNOWN, "Last seen time not reported"
        return (PASS, f"Seen {days:g} days ago") if days <= params["days"] else (FAIL, f"Not seen for {days:g} days")
    if kind == Kind.AGENT_CURRENT:
        state = h["agent_version"]
        if state == "current":
            return PASS, f"Agent {h['client_version']}"
        if state == "old":
            return FAIL, f"Agent {h['client_version']} is below the approved minimum"
        if state == "missing":
            return UNKNOWN, "Agent version not reported"
        if state == "not_evaluated":
            return UNKNOWN, "No approved minimum agent version (Device health → Thresholds)"
        return UNKNOWN, "Agent version not comparable"
    if kind == Kind.NO_OUTDATED_SOFTWARE:
        if f.outdated:
            more = f" and {len(f.outdated) - 1} more" if len(f.outdated) > 1 else ""
            return FAIL, f"Outdated: {f.outdated[0]}{more}"
        return PASS, "No outdated catalogued software"
    if kind == Kind.NO_CRITICAL_UPDATES:
        if not f.updates_collected:
            return UNKNOWN, "Available updates not collected"
        n = f.critical_available
        return (FAIL, f"{n} Critical update(s) available") if n else (PASS, "No Critical updates available")
    if kind == Kind.SCRIPT_VALUE:
        entry = f.script_values.get(params["collector"])
        if not entry or entry["state"] != "collected":
            return UNKNOWN, "Script result not collected for this device"
        actual = (entry["values"].get(params["variable"]) or {}).get("value")
        if actual is None:
            return UNKNOWN, f"{params['variable']} not reported by the script"
        want, op = params["value"], params["op"]
        if op == "at_least":
            try:
                ok = float(actual) >= float(want)
            except ValueError:
                return UNKNOWN, f"{params['variable']} = “{actual}” is not a number"
        elif op == "contains":
            ok = want.casefold() in actual.casefold()
        else:
            ok = (actual.casefold() == want.casefold()) == (op == "equals")
        return (PASS if ok else FAIL), f"{params['variable']} = “{actual}”"
    if kind == Kind.PATCH_POLICY_ASSIGNED:
        state = h["patch_policy"]
        if state == "assigned":
            return PASS, "Policy assigned"
        if state in ("explicit_none", "not_reported"):
            return (
                FAIL,
                "No Policy (explicitly configured)" if state == "explicit_none" else "No Patch Management entry",
            )
        return UNKNOWN, "Policy assignment not collected"
    return UNKNOWN, "Unsupported rule"


def in_scope(baseline: ComplianceBaseline, f: DeviceFacts) -> bool:
    if baseline.scope_device_type and f.device_type.casefold() != baseline.scope_device_type.casefold():
        return False
    if baseline.scope_site_external_id and f.site_external_id != baseline.scope_site_external_id:
        return False
    return not (baseline.scope_group_external_id and f.group_external_id != baseline.scope_group_external_id)


def evaluate(baseline: ComplianceBaseline, facts: list[DeviceFacts]) -> dict[str, Any]:
    rules = list(baseline.rules.all())
    devices: list[dict[str, Any]] = []
    rule_counts = {str(r.id): {PASS: 0, FAIL: 0, UNKNOWN: 0} for r in rules}
    for f in facts:
        if not in_scope(baseline, f):
            continue
        results = []
        for r in rules:
            state, reason = evaluate_rule(r.kind, r.params, f)
            rule_counts[str(r.id)][state] += 1
            results.append({"rule_id": str(r.id), "state": state, "reason": reason, "severity": r.severity})
        states = {x["state"] for x in results}
        status = FAIL if FAIL in states else UNKNOWN if UNKNOWN in states else PASS
        devices.append(
            {
                "asset_id": f.asset_id,
                "hostname": f.hostname,
                "site_external_id": f.site_external_id,
                "site_name": f.site_name,
                "group_external_id": f.group_external_id,
                "group_name": f.group_name,
                "device_type": f.device_type,
                "status": status,
                "failed": sum(1 for x in results if x["state"] == FAIL),
                "failed_high": sum(1 for x in results if x["state"] == FAIL and x["severity"] == "high"),
                "results": results,
            }
        )
    totals = {s: sum(1 for d in devices if d["status"] == s) for s in (PASS, FAIL, UNKNOWN)}
    decided = totals[PASS] + totals[FAIL]
    return {
        "baseline_id": str(baseline.id),
        "devices_in_scope": len(devices),
        "totals": totals,
        "score_pct": round(100 * totals[PASS] / decided, 1) if decided else None,
        "rules": [
            {
                "id": str(r.id),
                "kind": r.kind,
                "label": describe(r.kind, r.params),
                "severity": r.severity,
                "counts": rule_counts[str(r.id)],
            }
            for r in rules
        ],
        "devices": devices,
    }


def group_breakdown(devices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by: dict[tuple[str, str, str], dict[str, int]] = defaultdict(lambda: {PASS: 0, FAIL: 0, UNKNOWN: 0})
    for d in devices:
        by[(d["site_name"] or d["site_external_id"], d["group_external_id"], d["group_name"])][d["status"]] += 1
    rows = []
    for (site, gid, gname), c in by.items():
        decided = c[PASS] + c[FAIL]
        rows.append(
            {
                "site": site,
                "group_external_id": gid,
                "group_name": gname,
                **c,
                "score_pct": round(100 * c[PASS] / decided, 1) if decided else None,
            }
        )
    rows.sort(key=lambda r: (r["score_pct"] if r["score_pct"] is not None else 101, r["site"], r["group_name"]))
    return rows
