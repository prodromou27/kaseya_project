"""VSA2-02 deterministic expected-row → VSA device matching. Pure functions over one customer's pinned snapshot.

Precedence (docs/ONBOARDING_RECONCILIATION.md §Matching), each used only when it identifies exactly one device:

1. source device ID (VSA ``Identifier``);
2. serial number — non-placeholder and unique within the snapshot;
3. FQDN (VSA ``Name`` + reported domain);
4. hostname — narrowed by the row's expected org/site/group when several devices share it;
5. MAC — corroboration only; a MAC-only hit goes to **review** (never auto-confirmed; locally administered MACs
   are ignored);
6. IP — weak evidence; never confirms a match on its own. An IP-only hit goes to review.

Asset tags are accepted as input but VSA X reports no asset-tag field, so they never match (stated in evidence).
Nothing is fuzzy. The caller passes only the authorised customer's devices, so cross-customer matching is
impossible by construction.
"""

from __future__ import annotations

import ipaddress
import re
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

LOGIC_VERSION = "onboarding-match-1"

MATCHED = ("MATCHED_CORRECT", "MATCHED_WRONG_GROUP", "MATCHED_WRONG_SITE", "REVIEW_WRONG_ORGANIZATION")

_PLACEHOLDER_SERIALS = {
    "",
    "0",
    "NONE",
    "NULL",
    "NA",
    "N/A",
    "UNKNOWN",
    "DEFAULTSTRING",
    "TOBEFILLEDBYOEM",
    "TOBEFILLEDBYO.E.M.",
    "SYSTEMSERIALNUMBER",
    "CHASSISSERIALNUMBER",
    "123456789",
    "1234567890",
    "INVALID",
    "NOTAPPLICABLE",
    "NOTSPECIFIED",
}
_HOST_RE = re.compile(r"^[a-z0-9_][a-z0-9_-]{0,62}$")
_FQDN_LABEL_RE = re.compile(r"^[a-z0-9_]([a-z0-9_-]{0,61}[a-z0-9_])?$")


# ---------------------------------------------------------------------------------------------- normalisation


def norm_serial(value: str) -> str:
    """Upper-case without whitespace. Placeholders/repeated characters become '' (not an identifier)."""
    s = re.sub(r"\s+", "", value).upper()
    if s in _PLACEHOLDER_SERIALS or s.replace(".", "") in _PLACEHOLDER_SERIALS or (s and len(set(s)) == 1):
        return ""
    return s


def norm_mac(value: str) -> str | None:
    """12 upper-case hex digits, or ``None`` when malformed. All-zero/broadcast addresses are malformed."""
    s = re.sub(r"[\s:.\-]", "", value).upper()
    if not re.fullmatch(r"[0-9A-F]{12}", s) or s in {"000000000000", "FFFFFFFFFFFF"}:
        return None
    return s


def mac_locally_administered(mac: str) -> bool:
    return bool(int(mac[1], 16) & 0x2)


def norm_ip(value: str) -> str | None:
    try:
        return str(ipaddress.ip_address(value.strip().split("%", 1)[0]))
    except ValueError:
        return None


def norm_host(value: str) -> str | None:
    s = value.strip().casefold().rstrip(".")
    if "." in s:
        s = s.split(".", 1)[0]
    return s if _HOST_RE.fullmatch(s) else None


def norm_fqdn(value: str) -> str | None:
    s = value.strip().casefold().rstrip(".")
    labels = s.split(".")
    if len(labels) < 2 or len(s) > 253 or not all(_FQDN_LABEL_RE.fullmatch(lbl) for lbl in labels):
        return None
    return s


def norm_id(value: str) -> str:
    return value.strip().strip("{}").casefold()


# ---------------------------------------------------------------------------------------------- inputs


@dataclass(frozen=True)
class Device:
    """One VSA device in the pinned snapshot (already scoped to the authorised customer)."""

    asset_id: str
    external_id: str
    hostname: str
    domain: str = ""
    serial: str = ""
    macs: frozenset[str] = frozenset()
    ips: frozenset[str] = frozenset()
    org_id: str = ""
    org_name: str = ""
    site_id: str = ""
    site_name: str = ""
    group_id: str = ""
    group_name: str = ""
    last_seen_online: datetime | None = None
    is_agent_installed: bool | None = None
    network_status: str = "not_collected"

    @property
    def fqdn(self) -> str:
        return f"{self.hostname}.{self.domain}".casefold() if self.hostname and self.domain else ""

    def placement(self) -> dict[str, str]:
        return {
            "source_id": self.external_id,
            "hostname": self.hostname,
            "organization_id": self.org_id,
            "organization": self.org_name,
            "site_id": self.site_id,
            "site": self.site_name,
            "group_id": self.group_id,
            "group": self.group_name,
            "last_seen_online": self.last_seen_online.isoformat() if self.last_seen_online else "",
        }


@dataclass
class Params:
    snapshot_at: datetime
    offline_hours: int = 24
    stale_agent_days: int = 7
    stale_source: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "offline_hours": self.offline_hours,
            "stale_agent_days": self.stale_agent_days,
            "stale_source": self.stale_source,
            "flags_not_evaluated": {
                "OLD_AGENT": "no approved agent-version baseline is configured",
                "NO_PATCH_POLICY": "applied patch policies are not collected yet (VSA3-04)",
            },
        }


@dataclass
class RowResult:
    row_number: int
    input: dict[str, str]
    classification: str
    device: Device | None = None
    candidates: list[Device] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Outcome:
    rows: list[RowResult]
    unexpected: list[tuple[Device, int | None]]  # (device, ambiguous row it is a pending candidate of)
    summary: dict[str, Any]


# ---------------------------------------------------------------------------------------------- engine


class _Index:
    def __init__(self, devices: Iterable[Device]):
        self.devices = list(devices)
        self.by_id: dict[str, list[Device]] = defaultdict(list)
        self.by_serial: dict[str, list[Device]] = defaultdict(list)
        self.by_fqdn: dict[str, list[Device]] = defaultdict(list)
        self.by_host: dict[str, list[Device]] = defaultdict(list)
        self.by_mac: dict[str, list[Device]] = defaultdict(list)
        self.by_ip: dict[str, list[Device]] = defaultdict(list)
        for d in self.devices:
            self.by_id[norm_id(d.external_id)].append(d)
            if s := norm_serial(d.serial):
                self.by_serial[s].append(d)
            if d.fqdn:
                self.by_fqdn[d.fqdn].append(d)
            if h := norm_host(d.hostname):
                self.by_host[h].append(d)
            for m in d.macs:
                if not mac_locally_administered(m):
                    self.by_mac[m].append(d)
            for ip in d.ips:
                self.by_ip[ip].append(d)


def _same(expected: str, ext_id: str, name: str) -> bool | None:
    """``None`` when nothing was expected; IDs and names compare case-insensitively (names are labels only)."""
    e = expected.strip().casefold()
    if not e:
        return None
    return e in {ext_id.casefold(), name.strip().casefold()} - {""}


def _narrow(hits: list[Device], values: dict[str, str]) -> list[Device]:
    out = hits
    for key, id_attr, name_attr in (
        ("expected_organization", "org_id", "org_name"),
        ("expected_site", "site_id", "site_name"),
        ("expected_group", "group_id", "group_name"),
    ):
        if values.get(key):
            narrowed = [d for d in out if _same(values[key], getattr(d, id_attr), getattr(d, name_attr))]
            if narrowed:
                out = narrowed
    return out


def _identifiers(values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    """Normalised identifiers and per-field problems (malformed values are reported, never silently dropped)."""
    ids: dict[str, str] = {}
    problems: dict[str, str] = {}
    if v := values.get("source_device_id", "").strip():
        ids["source_device_id"] = norm_id(v)
    if v := values.get("serial_number", "").strip():
        if s := norm_serial(v):
            ids["serial_number"] = s
        else:
            problems["serial_number"] = "placeholder or non-unique-looking serial ignored"
    fqdn_raw = values.get("fqdn", "").strip()
    host_raw = values.get("hostname", "").strip()
    if not fqdn_raw and "." in host_raw:
        fqdn_raw = host_raw
    if fqdn_raw:
        if f := norm_fqdn(fqdn_raw):
            ids["fqdn"] = f
        elif values.get("fqdn", "").strip():
            problems["fqdn"] = "malformed FQDN"
    if host_raw:
        if h := norm_host(host_raw):
            ids["hostname"] = h
        else:
            problems["hostname"] = "malformed hostname"
    if v := values.get("mac", "").strip():
        if m := norm_mac(v):
            ids["mac"] = m
        else:
            problems["mac"] = "malformed MAC address"
    if v := values.get("ip_address", "").strip():
        if ip := norm_ip(v):
            ids["ip_address"] = ip
        else:
            problems["ip_address"] = "malformed IP address"
    return ids, problems


def _identity_key(ids: dict[str, str], values: dict[str, str]) -> tuple[str, ...] | None:
    for key in ("source_device_id", "serial_number", "fqdn"):
        if key in ids:
            return (key, ids[key])
    if "hostname" in ids:
        return ("hostname", ids["hostname"], values.get("expected_site", "").strip().casefold())
    if "mac" in ids:
        return ("mac", ids["mac"])
    return None


def _placement_class(device: Device, values: dict[str, str]) -> tuple[str, dict[str, Any]]:
    org = _same(values.get("expected_organization", ""), device.org_id, device.org_name)
    site = _same(values.get("expected_site", ""), device.site_id, device.site_name)
    group = _same(values.get("expected_group", ""), device.group_id, device.group_name)
    checks = {"organization": org, "site": site, "group": group}
    evidence: dict[str, Any] = {"placement_checked": {k: v for k, v in checks.items() if v is not None}}
    unchecked = [k for k, v in checks.items() if v is None]
    if unchecked:
        evidence["placement_not_specified"] = unchecked
    if group is False and not device.group_id:
        evidence["group_note"] = "device is not in any listed active group"
    if org is False:
        return "REVIEW_WRONG_ORGANIZATION", evidence
    if site is False:
        return "MATCHED_WRONG_SITE", evidence
    if group is False:
        return "MATCHED_WRONG_GROUP", evidence
    return "MATCHED_CORRECT", evidence


def classify_match(device: Device, values: dict[str, str]) -> tuple[str, dict[str, Any]]:
    """Public for reviewer decisions: placement classification of a confirmed device."""
    return _placement_class(device, values)


def _secondary_flags(device: Device, params: Params) -> list[str]:
    flags = []
    seen = device.last_seen_online
    if seen is None or seen < params.snapshot_at - timedelta(hours=params.offline_hours):
        flags.append("OFFLINE")
    if seen is None or seen < params.snapshot_at - timedelta(days=params.stale_agent_days):
        flags.append("STALE_AGENT")
    if params.stale_source:
        flags.append("STALE_SOURCE")
    if device.network_status != "collected":
        flags.append("MISSING_NETWORK_DATA")
    return flags


def _match_one(index: _Index, values: dict[str, str], ids: dict[str, str]) -> tuple[str, list[Device], dict[str, Any]]:
    """Returns (kind, devices, evidence) with kind in matched | ambiguous | not_found."""
    steps: list[dict[str, Any]] = []
    plural: list[Device] = []
    strong = (
        ("source_device_id", index.by_id),
        ("serial_number", index.by_serial),
        ("fqdn", index.by_fqdn),
        ("hostname", index.by_host),
    )
    for key, table in strong:
        if key not in ids:
            continue
        hits = list(table.get(ids[key], []))
        step: dict[str, Any] = {"identifier": key, "candidates": len(hits)}
        if key == "hostname" and len(hits) > 1:
            hits = _narrow(hits, values)
            step["after_expected_placement"] = len(hits)
        steps.append(step)
        if len(hits) == 1:
            device = hits[0]
            # A weaker identifier that uniquely names a *different* device makes the row ambiguous.
            for weaker, wtable in strong[[k for k, _ in strong].index(key) + 1 :]:
                if weaker in ids:
                    others = wtable.get(ids[weaker], [])
                    if len(others) == 1 and others[0].asset_id != device.asset_id:
                        return (
                            "ambiguous",
                            [device, others[0]],
                            {"steps": steps, "reason": f"{key} and {weaker} identify different devices"},
                        )
                    if not others:
                        step.setdefault("not_corroborated_by", []).append(weaker)
            return "matched", [device], {"steps": steps, "basis": key}
        if len(hits) > 1:
            if key == "serial_number":
                step["note"] = "serial number is not unique in the snapshot; not used"
                continue
            plural = hits
            break
    if plural:
        return "ambiguous", plural, {"steps": steps, "reason": "several devices share the identifier"}
    if "mac" in ids:
        mac = ids["mac"]
        if mac_locally_administered(mac):
            steps.append({"identifier": "mac", "note": "locally administered MAC ignored"})
        else:
            hits = index.by_mac.get(mac, [])
            steps.append({"identifier": "mac", "candidates": len(hits)})
            if hits:
                return "ambiguous", list(hits), {"steps": steps, "reason": "MAC-only match requires review"}
    has_strong = any(k in ids for k, _ in strong)
    if "ip_address" in ids:
        hits = index.by_ip.get(ids["ip_address"], [])
        steps.append({"identifier": "ip_address", "candidates": len(hits), "note": "weak evidence"})
        if hits and not has_strong:
            return "ambiguous", list(hits), {"steps": steps, "reason": "IP-only match requires review"}
    return "not_found", [], {"steps": steps}


def reconcile(rows: list[tuple[int, dict[str, str]]], devices: Iterable[Device], params: Params) -> Outcome:
    index = _Index(devices)
    results: list[RowResult] = []
    seen_keys: dict[tuple[str, ...], int] = {}
    matched_by: dict[str, int] = {}
    pending: dict[str, int] = {}

    for number, values in rows:
        ids, problems = _identifiers(values)
        evidence: dict[str, Any] = {}
        if problems:
            evidence["input_problems"] = problems
        if values.get("asset_tag", "").strip():
            evidence["asset_tag"] = "not reported by VSA X; not used for matching"
        usable = {k: v for k, v in ids.items()}
        if not usable:
            evidence["reason"] = "no valid identifier"
            results.append(RowResult(number, values, "INVALID_INPUT", evidence=evidence))
            continue
        key = _identity_key(ids, values)
        if key is not None and key in seen_keys:
            evidence["duplicate_of_row"] = seen_keys[key]
            evidence["duplicate_identifier"] = key[0]
            results.append(RowResult(number, values, "DUPLICATE_INPUT", evidence=evidence))
            continue
        if key is not None:
            seen_keys[key] = number

        kind, found, match_evidence = _match_one(index, values, ids)
        evidence.update(match_evidence)
        if kind == "matched":
            device = found[0]
            if device.asset_id in matched_by:
                evidence["duplicate_of_row"] = matched_by[device.asset_id]
                evidence["duplicate_identifier"] = "same matched device"
                results.append(RowResult(number, values, "DUPLICATE_INPUT", evidence=evidence))
                continue
            matched_by[device.asset_id] = number
            cls, placement = _placement_class(device, values)
            evidence.update(placement)
            if "mac" in ids:
                evidence["mac_check"] = (
                    "corroborated"
                    if ids["mac"] in device.macs
                    else ("not reported by source" if device.network_status != "collected" else "differs")
                )
            if "ip_address" in ids:
                evidence["ip_check"] = "present" if ids["ip_address"] in device.ips else "absent (weak evidence)"
            if device.is_agent_installed is False:
                evidence["agent"] = "VSA device list reports no agent installed"
            results.append(
                RowResult(number, values, cls, device=device, flags=_secondary_flags(device, params), evidence=evidence)
            )
        elif kind == "ambiguous":
            for d in found:
                pending.setdefault(d.asset_id, number)
            results.append(RowResult(number, values, "AMBIGUOUS", candidates=found, evidence=evidence))
        else:
            evidence["note"] = (
                "No match in this complete snapshot. This does not prove the agent is not installed: the device may "
                "use another name, be in another tenant, or not have reported yet."
            )
            results.append(RowResult(number, values, "NOT_FOUND_IN_COMPLETE_SNAPSHOT", evidence=evidence))

    unexpected = [
        (d, pending.get(d.asset_id))
        for d in sorted(index.devices, key=lambda d: (d.hostname.casefold(), d.external_id))
        if d.asset_id not in matched_by
    ]
    return Outcome(results, unexpected, _summary(results, unexpected, len(index.devices), params))


def _summary(
    rows: list[RowResult], unexpected: list[tuple[Device, int | None]], devices: int, params: Params
) -> dict[str, Any]:
    by_class: dict[str, int] = defaultdict(int)
    flags: dict[str, int] = defaultdict(int)
    for r in rows:
        by_class[r.classification] += 1
        for f in r.flags:
            flags[f] += 1
    accepted = sum(by_class.get(c, 0) for c in MATCHED)
    return {
        "logic_version": LOGIC_VERSION,
        "expected_rows": len(rows),
        "classifications": dict(sorted(by_class.items())),
        "secondary_flags": dict(sorted(flags.items())),
        "matched_devices": accepted,
        "snapshot_devices": devices,
        "unexpected_vsa_assets": sum(1 for _, p in unexpected if p is None),
        "unexpected_pending_review": sum(1 for _, p in unexpected if p is not None),
        "parameters": params.as_dict(),
        "notes": [
            "NOT_FOUND_IN_COMPLETE_SNAPSHOT is not proof that an agent is not installed.",
            "Offline devices that matched remain onboarded; OFFLINE/STALE_AGENT are secondary flags.",
            "IP addresses never confirm a match on their own; MAC-only and IP-only hits require review.",
        ],
    }
