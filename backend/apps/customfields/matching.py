"""Device matching for custom field jobs: pasted lists, uploaded files and selected devices.

Precedence per input (first that finds a device wins): VSA device ID -> serial number (mapped column only, must be
unique) -> FQDN (hostname.domain) -> hostname. Exact, case-insensitive comparisons only - never fuzzy. Only the
selected customer's current snapshot is searched; a device found in another customer the user may see is reported as
"outside the selected customer", anything else as "not found" (so nothing about other customers leaks).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from rest_framework import serializers

from apps.inventory.queries import current_observations

from .models import AssignmentItem

ROLES = (
    "device_id",
    "serial",
    "fqdn",
    "hostname",
    "asset_tag",
    "expected_org",
    "expected_site",
    "expected_group",
    "value",
)
WORKSTATION_TYPES = {"windows", "mac", "linux"}
_DEVICE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_GUID = re.compile(r"^[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$")
_HOST = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,253}$")
_SPLIT = re.compile(r"[\r\n,;]+")
MAX_TEXT_BYTES = 1_000_000


@dataclass
class InputRecord:
    raw: str
    row: int | None = None
    ids: dict[str, str] = field(default_factory=dict)  # role -> value (identifier roles only)
    expected: dict[str, str] = field(default_factory=dict)
    value: str | None = None


def from_text(text: str) -> list[InputRecord]:
    """Pasted names: one per line, or separated by commas/semicolons. Kind is inferred per token."""
    if not isinstance(text, str) or len(text.encode("utf-8", "replace")) > MAX_TEXT_BYTES:
        raise serializers.ValidationError({"text": "Paste at most 1 MB of text."})
    out = []
    for token in _SPLIT.split(text):
        raw = token.strip()
        if raw:
            out.append(InputRecord(raw=raw, ids={_infer(raw): raw}))
    return _capped(out)


def _infer(raw: str) -> str:
    if _GUID.fullmatch(raw):
        return "device_id"
    return "fqdn" if "." in raw else "hostname"


def read_file(filename: str, data: bytes) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """(header, rows) of the first visible sheet. TXT = one identifier per line (no header)."""
    from apps.onboarding.importer import ImportRejected, parse

    lower = (filename or "").casefold()
    if len(data) > settings.ONBOARDING_MAX_UPLOAD_BYTES:
        raise serializers.ValidationError({"file": "The file is too large."})
    if lower.endswith(".txt"):
        try:
            text = data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise serializers.ValidationError({"file": "Text files must be UTF-8."}) from exc
        rows = [(n, [line.strip()]) for n, line in enumerate(text.splitlines(), start=1) if line.strip()]
        return ["Identifier"], rows
    try:
        workbook = parse(filename, data)
    except ImportRejected as exc:
        raise serializers.ValidationError({"file": exc.message}) from exc
    sheet = workbook.sheets[0]
    if not sheet.rows:
        raise serializers.ValidationError({"file": "The file has no rows."})
    (_, header), *rows = sheet.rows
    return [h.strip() for h in header], rows


def guess_mapping(header: list[str]) -> dict[str, int]:
    names = {
        "device_id": ("device id", "vsa device id", "identifier", "deviceid", "id"),
        "serial": ("serial", "serial number", "serialnumber"),
        "fqdn": ("fqdn", "dns name"),
        "hostname": ("hostname", "host name", "computer", "computer name", "name", "device", "workstation"),
        "asset_tag": ("asset tag", "assettag"),
        "expected_org": ("organization", "organisation", "expected organization"),
        "expected_site": ("site", "expected site"),
        "expected_group": ("group", "agent group", "expected group"),
        "value": ("value", "new value"),
    }
    out: dict[str, int] = {}
    for index, h in enumerate(header):
        key = h.casefold().strip()
        for role, options in names.items():
            if key in options and role not in out:
                out[role] = index
                break
    if header == ["Identifier"]:
        return {"hostname": 0}
    return out


def from_rows(rows: list[tuple[int, list[str]]], mapping: dict[str, int]) -> list[InputRecord]:
    bad = [r for r in mapping if r not in ROLES]
    if bad or not any(r in mapping for r in ("device_id", "serial", "fqdn", "hostname", "asset_tag")):
        raise serializers.ValidationError(
            {"mapping": "Map at least one identifier column (device ID, serial, FQDN or hostname)."}
        )
    out = []
    for number, cells in rows:

        def cell(role: str, cells: list[str] = cells) -> str:
            i = mapping.get(role)
            return cells[i].strip() if i is not None and i < len(cells) else ""

        ids = {r: cell(r) for r in ("device_id", "serial", "fqdn", "hostname", "asset_tag") if cell(r)}
        raw = next(iter(ids.values()), "")
        expected = {r: cell(r) for r in ("expected_org", "expected_site", "expected_group") if cell(r)}
        out.append(InputRecord(raw=raw, row=number, ids=ids, expected=expected, value=cell("value") or None))
    return _capped(out)


def _capped(records: list[InputRecord]) -> list[InputRecord]:
    if len(records) > settings.CUSTOM_FIELD_MAX_JOB_ITEMS:
        raise serializers.ValidationError({"input": f"At most {settings.CUSTOM_FIELD_MAX_JOB_ITEMS} devices per job."})
    if not records:
        raise serializers.ValidationError({"input": "No devices were supplied."})
    return records


# ------------------------------------------------------------------------------------------------ inventory index


def _rows(customer_id: Any, instance_id: Any) -> list[dict[str, Any]]:
    from apps.servers.models import ServerDesignation
    from apps.servers.status import server_source

    marks = dict(ServerDesignation.objects.filter(customer_id=customer_id).values_list("asset_id", "is_server"))
    rows = []
    for o in (
        current_observations(customer_id)
        .select_related(None)
        .filter(asset__integration_instance_id=instance_id)
        .values(
            "asset_id",
            "asset__external_id",
            "hostname",
            "domain",
            "serial_number",
            "site_name",
            "site_external_id",
            "group_name",
            "organization_external_id",
            "os_name",
            "device_type",
        )
    ):
        server = server_source(o["os_name"], marks.get(o["asset_id"])) in ("marked", "detected")
        host = (o["hostname"] or "").casefold()
        rows.append(
            {
                **o,
                "host": host,
                "fqdn": f"{host}.{o['domain'].casefold()}" if host and o["domain"] else "",
                "serial": (o["serial_number"] or "").strip().casefold(),
                "workstation": not server and (o["device_type"] or "").casefold() in WORKSTATION_TYPES,
                "why_not": "Server" if server else f"Device type {o['device_type'] or 'unknown'}",
            }
        )
    return rows


def _valid(role: str, value: str) -> bool:
    if not value or len(value) > 255 or any(ord(c) < 32 for c in value):
        return False
    if role == "device_id":
        return bool(_DEVICE_ID.fullmatch(value))
    if role in ("hostname", "fqdn"):
        return bool(_HOST.fullmatch(value))
    return True


def _narrow(cands: list[dict[str, Any]], expected: dict[str, str]) -> list[dict[str, Any]]:
    def ok(c: dict[str, Any]) -> bool:
        site, group, org = expected.get("expected_site"), expected.get("expected_group"), expected.get("expected_org")
        return (
            (not site or site.casefold() in ((c["site_name"] or "").casefold(), str(c["site_external_id"])))
            and (not group or group.casefold() == (c["group_name"] or "").casefold())
            and (not org or org == str(c["organization_external_id"]))
        )

    return [c for c in cands if ok(c)]


def candidate(c: dict[str, Any]) -> dict[str, str]:
    return {
        "asset_id": str(c["asset_id"]),
        "device_id": c["asset__external_id"],
        "hostname": c["hostname"],
        "site": c["site_name"] or c["site_external_id"],
        "group": c["group_name"],
    }


def match(customer: Any, user: Any, instance: Any, records: list[InputRecord]) -> list[dict[str, Any]]:
    """One item dict per input record (see ``AssignmentItem`` fields)."""
    rows = _rows(customer.id, instance.id)
    index: dict[str, dict[str, list[dict[str, Any]]]] = {k: {} for k in ("device_id", "serial", "fqdn", "hostname")}
    for r in rows:
        for role, key in (
            ("device_id", r["asset__external_id"].casefold()),
            ("serial", r["serial"]),
            ("fqdn", r["fqdn"]),
            ("hostname", r["host"]),
        ):
            if key:
                index[role].setdefault(key, []).append(r)
    seen_inputs: set[tuple[str, str]] = set()
    seen_assets: set[str] = set()
    out = []
    for position, rec in enumerate(records):
        item: dict[str, Any] = {
            "position": position,
            "input_identifier": rec.raw[:255],
            "input_row": rec.row,
            "requested_value": (rec.value or "")[:255],
        }
        out.append(item)
        if "asset_tag" in rec.ids and len(rec.ids) == 1:
            item.update(
                match_status=AssignmentItem.Match.UNSUPPORTED,
                input_kind="asset_tag",
                match_note="Asset tags are not collected from VSA X",
            )
            continue
        ids = {k: v for k, v in rec.ids.items() if k != "asset_tag"}
        bad = [k for k, v in ids.items() if not _valid(k, v)]
        if not ids or bad:
            item.update(
                match_status=AssignmentItem.Match.INVALID,
                input_kind=(bad or ["hostname"])[0],
                match_note="Not a valid identifier",
            )
            continue
        key = tuple(sorted((k, v.casefold()) for k, v in ids.items()))
        if key in seen_inputs:
            item.update(
                match_status=AssignmentItem.Match.DUPLICATE,
                input_kind=next(iter(ids)),
                match_note="Already listed above",
            )
            continue
        seen_inputs.add(key)  # type: ignore[arg-type]
        found: list[dict[str, Any]] = []
        kind = next(iter(ids))
        for role in ("device_id", "serial", "fqdn", "hostname"):
            if role in ids:
                kind = role
                found = index[role].get(ids[role].casefold(), [])
                if role == "serial" and len(found) > 1:
                    item.update(
                        match_status=AssignmentItem.Match.MULTIPLE,
                        input_kind=role,
                        match_note="Serial number is not unique",
                        candidates=[candidate(c) for c in found],
                    )
                    break
                if found:
                    break
        if item.get("match_status"):
            continue
        item["input_kind"] = kind
        narrowed = _narrow(found, rec.expected) if rec.expected else found
        if found and not narrowed:
            item.update(match_status=AssignmentItem.Match.NOT_FOUND, match_note="Found, but not in the expected scope")
            continue
        if not narrowed:
            item.update(match_status=AssignmentItem.Match.NOT_FOUND)
            if _elsewhere(user, customer, kind, ids[kind]):
                item.update(
                    match_status=AssignmentItem.Match.OTHER_CUSTOMER,
                    match_note="Belongs to another customer you can see",
                )
            continue
        if len(narrowed) > 1:
            item.update(
                match_status=AssignmentItem.Match.MULTIPLE,
                match_note="Choose the right device",
                candidates=[candidate(c) for c in narrowed],
            )
            continue
        _set_device(item, narrowed[0], seen_assets)
    return out


def _set_device(item: dict[str, Any], c: dict[str, Any], seen_assets: set[str]) -> None:
    item.update(
        asset_id=c["asset_id"],
        device_external_id=c["asset__external_id"],
        hostname=c["hostname"],
        site=c["site_name"] or c["site_external_id"],
        group=c["group_name"],
    )
    if str(c["asset_id"]) in seen_assets:
        item.update(match_status=AssignmentItem.Match.DUPLICATE, match_note="Same device as an earlier line")
    elif not c["workstation"]:
        item.update(match_status=AssignmentItem.Match.UNSUPPORTED, match_note=f"{c['why_not']}: workstations only")
    else:
        item["match_status"] = AssignmentItem.Match.MATCHED
        seen_assets.add(str(c["asset_id"]))


def _elsewhere(user: Any, customer: Any, kind: str, value: str) -> bool:
    """Whether the identifier exists in another customer the user may read (only those are named)."""
    from apps.accounts import scope
    from apps.accounts.roles import Cap
    from apps.inventory.models import AssetObservation

    allowed = scope.accessible_customer_ids(user, Cap.CUSTOMER_READ)
    qs = AssetObservation.objects.filter(
        generation__is_current=True, generation__dataset="vsa_assets", generation__mapping__mapping_status="approved"
    ).exclude(customer_id=customer.id)
    if allowed is not None:
        if not allowed:
            return False
        qs = qs.filter(customer_id__in=allowed)
    v = value.casefold()
    if kind == "device_id":
        return qs.filter(asset__external_id__iexact=v).exists()
    if kind == "serial":
        return qs.filter(serial_number__iexact=v).exists()
    host = v.split(".", 1)[0] if kind == "fqdn" else v
    return qs.filter(hostname__iexact=host).exists()


def match_selected(customer: Any, instance: Any, asset_ids: list[str]) -> list[dict[str, Any]]:
    """Selected devices (inventory page or device page): every ID must be in the customer's current snapshot."""
    if not isinstance(asset_ids, list) or not asset_ids:
        raise serializers.ValidationError({"assets": "Select at least one device."})
    if len(asset_ids) > settings.CUSTOM_FIELD_MAX_JOB_ITEMS:
        raise serializers.ValidationError({"assets": f"At most {settings.CUSTOM_FIELD_MAX_JOB_ITEMS} devices per job."})
    rows = {str(r["asset_id"]): r for r in _rows(customer.id, instance.id)}
    out, seen = [], set()
    for position, aid in enumerate(dict.fromkeys(str(a) for a in asset_ids)):
        r = rows.get(aid)
        if r is None:
            raise serializers.ValidationError(
                {"assets": "A selected device is not in this customer's current inventory."}
            )
        item = {
            "position": position,
            "input_identifier": r["hostname"] or r["asset__external_id"],
            "input_kind": "selected",
        }
        _set_device(item, r, seen)
        out.append(item)
    return out
