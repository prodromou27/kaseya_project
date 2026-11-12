"""Typed normalisation of documented VSA X ``/api/v3/assets`` and ``/api/v3/organizations`` payloads.

Only allowlisted fields are kept (see ``capabilities.json``). In particular, ``AssetInfo`` values such as
``Product Key``, ``Registered User``, ``Last Logged On User`` and ``Owner Name`` are dropped.
"""

from __future__ import annotations

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
        k for k in ("Tags", "AssetInfo", "InstalledSoftware", "Updates", "AvailableUpdates") if k in item
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
        sections=sections,
        **info,
    )


def normalize_organization(item: dict[str, Any]) -> VsaOrganization:
    org_id = _id(item.get("Id"))
    if not org_id:
        raise RecordInvalid("missing_id")
    return VsaOrganization(id=org_id, name=_text(item.get("Name")), type=_text(item.get("Type")))
