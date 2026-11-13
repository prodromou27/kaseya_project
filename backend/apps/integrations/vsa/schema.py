"""Typed normalisation of documented VSA X ``/api/v3/assets`` and ``/api/v3/organizations`` payloads.

Only allowlisted fields are kept (see ``capabilities.json``). In particular, ``AssetInfo`` values such as
``Product Key``, ``Registered User``, ``Last Logged On User`` and ``Owner Name`` are dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

MAX_TEXT = 255


class RecordInvalid(Exception):
    """A single record failed validation; it is quarantined, not the whole page."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class PageInvalid(Exception):
    """The page envelope itself is malformed; the sync run must fail."""


@dataclass(frozen=True)
class InstalledSoftwareItem:
    name: str
    publisher: str
    version: str


@dataclass(frozen=True)
class OsUpdateItem:
    """One entry of ``AvailableUpdates`` / ``InstalledUpdates`` (fields per the documented examples)."""

    update_id: str
    revision_number: int | None
    title: str
    kb_article: str = ""
    severity: str = ""
    category: str = ""
    cvss_score: float | None = None
    cve_codes: tuple[str, ...] = ()
    release_date: str = ""
    installed_at_raw: str = ""  # documented without timezone — never assumed UTC
    installed_by_agent: bool | None = None


@dataclass(frozen=True)
class NetworkAdapter:
    """One reported adapter, merged from ``LocalIpAddresses`` (mask/gateway/DNS) and ``IpAddresses`` (all IPs)."""

    name: str
    mac: str  # 12 upper-case hex digits or ""
    dhcp_enabled: bool | None
    subnet_mask: str
    gateways: tuple[str, ...]
    dns_servers: tuple[str, ...]
    addresses: tuple[str, ...]  # raw address strings as reported (IPv6 may carry a %zone suffix)
    sources: frozenset[str]
    mask_address: str = ""  # the LocalIpAddresses.IpV4 value the SubnetMask was reported with


@dataclass(frozen=True)
class DiskItem:
    name: str
    is_system: bool | None
    free_percentage: float | None
    total_value_raw: str  # units are not documented by VSA X: kept verbatim, never converted


@dataclass(frozen=True)
class SecurityItem:
    type: str
    name: str
    enabled: bool | None  # tri-state: None = not reported
    up_to_date: bool | None


@dataclass(frozen=True)
class VsaSite:
    id: str
    name: str
    organization_id: str


@dataclass(frozen=True)
class VsaGroup:
    id: str
    name: str
    is_active: bool | None
    site_id: str
    site_name: str
    organization_id: str
    organization_name: str


@dataclass(frozen=True)
class VsaDeviceRef:
    identifier: str
    organization_id: str
    group_id: str
    group_name: str
    site_id: str
    site_name: str
    is_agent_installed: bool | None
    is_mdm_enrolled: bool | None


@dataclass(frozen=True)
class VsaAsset:
    identifier: str
    organization_id: str
    name: str = ""
    group_name: str = ""
    description: str = ""
    device_type: str = ""
    client_version: str = ""
    last_seen_online: datetime | None = None
    computer_id: str = ""
    site_id: str = ""
    os_name: str = ""
    os_version: str = ""
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    domain: str = ""
    tags: tuple[str, ...] = ()
    # None means the InstalledSoftware section was absent ("not collected"), [] means "collected, empty".
    installed_software: tuple[InstalledSoftwareItem, ...] | None = None
    # Same convention for OS update sections: None = section absent (not collected), () = collected, empty.
    update_counts: dict[str, int] | None = None
    available_updates: tuple[OsUpdateItem, ...] | None = None
    installed_updates: tuple[OsUpdateItem, ...] | None = None
    # None = section(s) absent (not collected); () = collected but empty.
    network_adapters: tuple[NetworkAdapter, ...] | None = None
    public_ip: str = ""
    disks: tuple[DiskItem, ...] | None = None
    security: tuple[SecurityItem, ...] | None = None
    sections: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class VsaOrganization:
    id: str
    name: str
    type: str


@dataclass(frozen=True)
class Page:
    records: list[dict[str, Any]]
    total_count: int | None


def _text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str | int | float):
        raise RecordInvalid("non_scalar_field")
    return str(value).strip()[:MAX_TEXT]


def _id(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value.strip()[:128]
    return ""


def _datetime(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str):
        raise RecordInvalid("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecordInvalid("invalid_timestamp") from exc
    if parsed.tzinfo is None:
        raise RecordInvalid("timestamp_without_timezone")
    return parsed


def parse_page(body: Any) -> Page:
    """Validate the documented envelope ``{Data: [...], Meta: {TotalCount, ResponseCode}}``."""
    if not isinstance(body, dict):
        raise PageInvalid("Response body is not an object.")
    data, meta = body.get("Data"), body.get("Meta")
    if not isinstance(data, list) or not isinstance(meta, dict):
        raise PageInvalid("Response is missing Data list or Meta object.")
    total = meta.get("TotalCount")
    if total is not None and (isinstance(total, bool) or not isinstance(total, int) or total < 0):
        raise PageInvalid("Meta.TotalCount is not a non-negative integer.")
    if any(not isinstance(item, dict) for item in data):
        raise PageInvalid("Data contains non-object items.")
    return Page(records=data, total_count=total)


_ASSET_INFO_ALLOWLIST: dict[str, dict[str, str]] = {
    "System": {"Manufacturer": "manufacturer", "Model": "model", "Domain": "domain"},
    "BIOS": {"Serial Number": "serial_number"},
    "Operating System": {"Name": "os_name", "Version": "os_version"},
}


def _asset_info(value: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    if not isinstance(value, list):
        return out
    for category in value:
        if not isinstance(category, dict):
            continue
        allowed = _ASSET_INFO_ALLOWLIST.get(str(category.get("CategoryName", "")))
        data = category.get("CategoryData")
        if not allowed or not isinstance(data, dict):
            continue
        for source_key, target in allowed.items():
            if source_key in data and target not in out:
                out[target] = _text(data[source_key])
    return out


def _software(value: Any) -> tuple[InstalledSoftwareItem, ...]:
    if not isinstance(value, list):
        raise RecordInvalid("invalid_installed_software")
    items = []
    for entry in value:
        if not isinstance(entry, dict):
            raise RecordInvalid("invalid_installed_software")
        name = _text(entry.get("Name"))
        if not name:
            continue  # nameless entries cannot be attributed to any product
        items.append(
            InstalledSoftwareItem(
                name=name, publisher=_text(entry.get("Publisher")), version=_text(entry.get("Version"))
            )
        )
    return tuple(items)


_KB = re.compile(r"^(?:KB)?([0-9]{4,10})$", re.IGNORECASE)
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_INSTALLED_AT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})?$"
)


def _update_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        raise RecordInvalid("invalid_update_counts")
    out: dict[str, int] = {}
    for key, count in list(value.items())[:10]:
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise RecordInvalid("invalid_update_counts")
        out[_text(key)[:32]] = count
    return out


def _os_updates(value: Any, *, installed: bool) -> tuple[OsUpdateItem, ...]:
    if not isinstance(value, list):
        raise RecordInvalid("invalid_os_updates")
    items = []
    for entry in value[:5000]:
        if not isinstance(entry, dict):
            raise RecordInvalid("invalid_os_updates")
        update_id = _id(entry.get("UpdateId"))
        if not update_id:
            raise RecordInvalid("os_update_missing_id")
        rev = entry.get("RevisionNumber")
        kb_match = _KB.match(_text(entry.get("KbArticle")))
        cvss = entry.get("CvssScore")
        cves = entry.get("CveCodes")
        release = _text(entry.get("ReleaseDate"))
        installed_at = _text(entry.get("InstalledAt")) if installed else ""
        by_agent = entry.get("InstalledByAgent") if installed else None
        items.append(
            OsUpdateItem(
                update_id=update_id,
                revision_number=rev if isinstance(rev, int) and not isinstance(rev, bool) else None,
                title=_text(entry.get("Title")),
                kb_article=kb_match.group(1) if kb_match else "",
                severity=_text(entry.get("Severity"))[:32],
                category=_text(entry.get("Category"))[:64],
                cvss_score=float(cvss)
                if isinstance(cvss, int | float) and not isinstance(cvss, bool) and 0 <= cvss <= 10
                else None,
                cve_codes=tuple(_text(c)[:32] for c in cves[:50] if isinstance(c, str))
                if isinstance(cves, list)
                else (),
                release_date=release if _DATE.match(release) else "",
                installed_at_raw=installed_at if _INSTALLED_AT.match(installed_at) else "",
                installed_by_agent=by_agent if isinstance(by_agent, bool) else None,
            )
        )
    return tuple(items)


def normalize_installed_updates(detail_body: Any, identifier: str) -> tuple[OsUpdateItem, ...] | None:
    """Validate a ``GET /api/v3/assets/:id`` envelope and return its InstalledUpdates (None if section absent)."""
    if not isinstance(detail_body, dict) or not isinstance(detail_body.get("Data"), dict):
        raise RecordInvalid("invalid_detail_envelope")
    data = detail_body["Data"]
    if _id(data.get("Identifier")) != identifier:
        raise RecordInvalid("detail_identifier_mismatch")
    if "InstalledUpdates" not in data:
        return None
    return _os_updates(data["InstalledUpdates"], installed=True)


_MAC = re.compile(r"[^0-9A-Fa-f]")


def _mac(value: Any) -> str:
    raw = _MAC.sub("", _text(value)).upper()
    return raw if len(raw) == 12 and raw != "000000000000" else ""


def _bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _str_list(value: Any, limit: int = 32) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(_text(v)[:64] for v in value[:limit] if isinstance(v, str) and v.strip())


def _network(item: dict[str, Any]) -> tuple[NetworkAdapter, ...] | None:
    local, addrs = item.get("LocalIpAddresses"), item.get("IpAddresses")
    if local is None and addrs is None:
        return None
    if (local is not None and not isinstance(local, list)) or (addrs is not None and not isinstance(addrs, list)):
        raise RecordInvalid("invalid_network_section")
    merged: dict[str, dict[str, Any]] = {}

    def slot(name: str, mac: str) -> dict[str, Any]:
        key = f"mac:{mac}" if mac else f"name:{name.casefold()}"
        return merged.setdefault(
            key,
            {
                "name": name,
                "mac": mac,
                "dhcp": None,
                "mask": "",
                "gw": (),
                "dns": (),
                "addresses": [],
                "sources": set(),
                "mask_addr": "",
            },
        )

    for entry in (local or [])[:64]:
        if not isinstance(entry, dict):
            raise RecordInvalid("invalid_network_section")
        s = slot(_text(entry.get("Name")), _mac(entry.get("PhysicalAddress")))
        s["sources"].add("LocalIpAddresses")
        s["dhcp"] = _bool(entry.get("DhcpEnabled"))
        s["mask"] = _text(entry.get("SubnetMask"))[:45]
        s["gw"], s["dns"] = _str_list(entry.get("Gateways")), _str_list(entry.get("DnsServers"))
        s["mask_addr"] = _text(entry.get("IpV4"))[:64]
        for key in ("IpV4", "IpV6"):
            v = _text(entry.get(key))[:64]
            if v and v not in s["addresses"]:
                s["addresses"].append(v)
    for entry in (addrs or [])[:64]:
        if not isinstance(entry, dict):
            raise RecordInvalid("invalid_network_section")
        s = slot(_text(entry.get("Name")), _mac(entry.get("MAC")))
        s["sources"].add("IpAddresses")
        ips = entry.get("IPs")
        for ip in (ips if isinstance(ips, list) else [])[:64]:
            v = _text(ip.get("IP"))[:64] if isinstance(ip, dict) else ""
            if v and v not in s["addresses"]:
                s["addresses"].append(v)
    return tuple(
        NetworkAdapter(
            name=v["name"],
            mac=v["mac"],
            dhcp_enabled=v["dhcp"],
            subnet_mask=v["mask"],
            gateways=v["gw"],
            dns_servers=v["dns"],
            addresses=tuple(v["addresses"]),
            sources=frozenset(v["sources"]),
            mask_address=v["mask_addr"],
        )
        for v in merged.values()
    )


def _disks(value: Any) -> tuple[DiskItem, ...]:
    if not isinstance(value, list):
        raise RecordInvalid("invalid_disks_section")
    out = []
    for d in value[:64]:
        if not isinstance(d, dict):
            raise RecordInvalid("invalid_disks_section")
        free = d.get("FreePercentage")
        total = d.get("TotalValue")
        out.append(
            DiskItem(
                name=_text(d.get("Name"))[:64],
                is_system=_bool(d.get("System")),
                free_percentage=float(free)
                if isinstance(free, int | float) and not isinstance(free, bool) and 0 <= free <= 100
                else None,
                total_value_raw=str(total) if isinstance(total, int | float) and not isinstance(total, bool) else "",
            )
        )
    return tuple(out)


def _security(value: Any) -> tuple[SecurityItem, ...]:
    if not isinstance(value, list):
        raise RecordInvalid("invalid_security_section")
    out = []
    for e in value[:64]:
        if not isinstance(e, dict):
            raise RecordInvalid("invalid_security_section")
        out.append(
            SecurityItem(
                type=_text(e.get("Type"))[:64],
                name=_text(e.get("Name"))[:128],
                enabled=_bool(e.get("Enabled")),
                up_to_date=_bool(e.get("UpToDate")),
            )
        )
    return tuple(out)


def normalize_site(item: dict[str, Any]) -> VsaSite:
    sid, org = _id(item.get("Id")), _id(item.get("ParentId"))
    if not sid or not org:
        raise RecordInvalid("site_missing_id")
    return VsaSite(id=sid, name=_text(item.get("Name")), organization_id=org)


def normalize_group(item: dict[str, Any]) -> VsaGroup:
    gid, site, org = _id(item.get("Id")), _id(item.get("ParentSiteId")), _id(item.get("ParentOrganizationId"))
    if not gid or not org:
        raise RecordInvalid("group_missing_id")
    return VsaGroup(
        id=gid,
        name=_text(item.get("Name")),
        is_active=_bool(item.get("IsActive")),
        site_id=site,
        site_name=_text(item.get("ParentSiteName")),
        organization_id=org,
        organization_name=_text(item.get("ParentOrganizationName")),
    )


def normalize_device_ref(item: dict[str, Any]) -> VsaDeviceRef:
    ident, org = _id(item.get("Identifier")), _id(item.get("OrganizationId"))
    if not ident or not org:
        raise RecordInvalid("device_missing_id")
    return VsaDeviceRef(
        identifier=ident,
        organization_id=org,
        group_id=_id(item.get("GroupId")),
        group_name=_text(item.get("GroupName")),
        site_id=_id(item.get("SiteId")),
        site_name=_text(item.get("SiteName")),
        is_agent_installed=_bool(item.get("IsAgentInstalled")),
        is_mdm_enrolled=_bool(item.get("IsMdmEnrolled")),
    )


def normalize_asset(item: dict[str, Any]) -> VsaAsset:
    identifier = _id(item.get("Identifier"))
    if not identifier:
        raise RecordInvalid("missing_identifier")
    org = _id(item.get("OrganizationId"))
    if not org:
        raise RecordInvalid("missing_organization_id")
    tags_raw = item.get("Tags")
    tags = tuple(_text(t) for t in tags_raw if isinstance(t, str)) if isinstance(tags_raw, list) else ()
    sections = frozenset(
        k
        for k in (
            "Tags",
            "AssetInfo",
            "InstalledSoftware",
            "Updates",
            "AvailableUpdates",
            "IpAddresses",
            "LocalIpAddresses",
            "Disks",
            "Security",
        )
        if k in item
    )
    info = _asset_info(item.get("AssetInfo"))
    return VsaAsset(
        identifier=identifier,
        organization_id=org,
        name=_text(item.get("Name")),
        group_name=_text(item.get("GroupName")),
        description=_text(item.get("Description")),
        device_type=_text(item.get("Type")),
        client_version=_text(item.get("ClientVersion")),
        last_seen_online=_datetime(item.get("LastSeenOnline")),
        computer_id=_id(item.get("ComputerId")),
        site_id=_id(item.get("SiteId")),
        tags=tags,
        installed_software=_software(item["InstalledSoftware"]) if "InstalledSoftware" in item else None,
        update_counts=_update_counts(item["Updates"]) if "Updates" in item else None,
        available_updates=(
            _os_updates(item["AvailableUpdates"], installed=False) if "AvailableUpdates" in item else None
        ),
        network_adapters=_network(item),
        public_ip=_text(item.get("PublicIpAddress"))[:64],
        disks=_disks(item["Disks"]) if "Disks" in item else None,
        security=_security(item["Security"]) if "Security" in item else None,
        sections=sections,
        **info,
    )


def normalize_organization(item: dict[str, Any]) -> VsaOrganization:
    org_id = _id(item.get("Id"))
    if not org_id:
        raise RecordInvalid("missing_id")
    return VsaOrganization(id=org_id, name=_text(item.get("Name")), type=_text(item.get("Type")))


# ---------------------------------------------------------------------------------------------- VSA3-04 policies

POLICY_TYPES = ("Device Configuration", "Monitoring", "Antivirus", "Ransomware Detection", "Patch Management")
PATCH_POLICY_TYPE = "Patch Management"
# Documented GeneralSettings keys kept; NotificationSettings and anything undocumented are dropped (may hold contacts).
PATCH_GENERAL_SETTINGS_KEPT = (
    "CreateRestorePoint",
    "RebootIfRequire",
    "NotifyLoggedInUsers",
    "Schedule",
    "RandomizeUpdateInterval",
    "StartPatchingIfScheduledMissed",
    "RebootOption",
    "AutomaticUpdate",
    "DeferQualityUpdates",
    "QualityUpdatesDeferPeriod",
    "DeferFeatureUpdates",
    "FeatureUpdatesDeferPeriod",
    "IncludeDriversUpdate",
    "PreventFromExecutingAndConfiguringWindowsUpdates",
    "RebootImmediatelyIfScheduledMissed",
)


@dataclass(frozen=True)
class AppliedPolicyItem:
    policy_type: str
    policy_id: str  # "" when null (explicitly configured No Policy)
    policy_name: str
    profiles: tuple[tuple[str, str, str], ...]  # (id, name, category) — profile Settings are not stored

    @property
    def explicit_none(self) -> bool:
        return self.policy_id == ""


@dataclass(frozen=True)
class PatchPolicyDefinitionData:
    policy_id: str
    name: str
    description: str
    general_settings: dict[str, Any]
    os_rules: list[dict[str, Any]]
    software_rules: list[dict[str, Any]]


def _json_safe(value: Any, depth: int = 0) -> Any:
    """Bounded copy of plain JSON (configuration values only)."""
    if depth > 4:
        raise RecordInvalid("nesting_too_deep")
    if value is None or isinstance(value, bool | int | float):
        return value
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, list):
        return [_json_safe(v, depth + 1) for v in value[:200]]
    if isinstance(value, dict):
        return {str(k)[:64]: _json_safe(v, depth + 1) for k, v in list(value.items())[:100]}
    raise RecordInvalid("unsupported_value")


def normalize_applied_policies(rows: list[dict[str, Any]]) -> tuple[AppliedPolicyItem, ...]:
    items = []
    for row in rows:
        ptype = _text(row.get("PolicyType"))
        if not ptype:
            raise RecordInvalid("missing_policy_type")
        pid = row.get("PolicyId")
        if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int) or pid < 0):
            raise RecordInvalid("invalid_policy_id")
        profiles = []
        for prof in row.get("Profiles") or []:
            if isinstance(prof, dict):
                profiles.append((_text(prof.get("Id")), _text(prof.get("Name")), _text(prof.get("Category"))))
        items.append(
            AppliedPolicyItem(
                policy_type=ptype[:64],
                policy_id="" if pid is None else str(pid),
                policy_name=_text(row.get("PolicyName")),
                profiles=tuple(profiles),
            )
        )
    return tuple(items)


def normalize_patch_policy(body: Any, policy_id: str) -> PatchPolicyDefinitionData:
    if not isinstance(body, dict) or not isinstance(body.get("Data"), dict):
        raise RecordInvalid("invalid_policy_envelope")
    data = body["Data"]
    if str(data.get("Id")) != policy_id:
        raise RecordInvalid("policy_id_mismatch")
    general = data.get("GeneralSettings") if isinstance(data.get("GeneralSettings"), dict) else {}
    os_rules = data.get("OsRules") if isinstance(data.get("OsRules"), list) else []
    sw_rules = data.get("SoftwareRules") if isinstance(data.get("SoftwareRules"), list) else []
    return PatchPolicyDefinitionData(
        policy_id=policy_id,
        name=_text(data.get("Name")),
        description=_text(data.get("Description")),
        general_settings={k: _json_safe(general[k]) for k in PATCH_GENERAL_SETTINGS_KEPT if k in general},
        os_rules=[_json_safe(r) for r in os_rules if isinstance(r, dict)],
        software_rules=[
            {k: _json_safe(r.get(k)) for k in ("ProductId", "ProductName", "Action")}
            for r in sw_rules
            if isinstance(r, dict)
        ],
    )
