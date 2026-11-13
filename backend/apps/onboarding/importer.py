"""VSA2-01 secure expected-inventory importer (.xlsx / .csv only).

Defences (docs/ONBOARDING_RECONCILIATION.md §Security):
* extension allowlist + magic bytes; ``.xlsm``/``.xls``/``.xlsb`` and anything else are refused;
* hard limits on bytes, rows, columns, sheets and cell length;
* XLSX container inspection *before* parsing: member count, total uncompressed size and per-member compression
  ratio (zip bombs), macro/VBA parts, ActiveX/OLE embeddings, external links and DTD/entity declarations are
  refused; openpyxl then parses with defusedxml (installed dependency) and ``keep_links=False``;
* formulas are **never evaluated** and cached results are not trusted: a formula cell is read as empty and
  counted, so its value can never become an identifier;
* all values are returned as plain text. Nothing here is rendered as HTML; exports neutralise formula prefixes.
"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from typing import Any

from django.conf import settings

MAX_SHEETS = 20
MAX_COLUMNS = 64
MAX_CELL_CHARS = 512
MAX_HEADER_ROW = 50
ZIP_MAX_MEMBERS = 2000
ZIP_MAX_UNCOMPRESSED = 64 * 1024 * 1024
ZIP_MAX_RATIO = 200
_FORBIDDEN_PARTS = ("xl/vbaproject.bin", "xl/externallinks/", "xl/activex/", "xl/embeddings/", "xl/macrosheets/")


class ImportRejected(Exception):
    """A file or request that must be refused. ``code`` is stable and safe to show; no file content is echoed."""

    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code = code
        self.message = message


# ---------------------------------------------------------------------------------------------- portal fields

FIELDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "source_device_id": ("Source device ID", ("sourcedeviceid", "deviceid", "vsaid", "identifier", "deviceidentifier")),
    "hostname": ("Hostname", ("hostname", "computername", "devicename", "computer", "machinename", "host", "name")),
    "fqdn": ("FQDN", ("fqdn", "fullyqualifieddomainname", "dnsname", "dnshostname")),
    "serial_number": ("Serial number", ("serialnumber", "serial", "serialno", "sn", "servicetag")),
    "asset_tag": ("Asset tag", ("assettag", "inventorynumber", "assetnumber")),
    "mac": ("MAC address", ("mac", "macaddress", "physicaladdress")),
    "ip_address": ("IP address", ("ipaddress", "ip", "ipv4", "ipv4address")),
    "expected_organization": (
        "Expected organisation",
        ("expectedorganization", "expectedorganisation", "organization", "organisation", "org"),
    ),
    "expected_site": ("Expected site", ("expectedsite", "site", "location")),
    "expected_group": ("Expected group", ("expectedgroup", "group", "devicegroup")),
    "device_type": ("Device type", ("devicetype", "type")),
    "department": ("Department", ("department", "dept")),
    "notes": ("Notes", ("notes", "note", "comments", "comment")),
}
IDENTIFIER_FIELDS = ("source_device_id", "hostname", "fqdn", "serial_number", "asset_tag", "mac", "ip_address")


def normalize_header(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", text).casefold())


def suggest_mapping(headers: list[str]) -> dict[str, int]:
    """Exact synonym matches only (no fuzzy guessing). Each column is used at most once."""
    norm = [normalize_header(h) for h in headers]
    mapping: dict[str, int] = {}
    used: set[int] = set()
    for key, (_label, synonyms) in FIELDS.items():
        for syn in synonyms:
            idx = next((i for i, h in enumerate(norm) if h == syn and i not in used), None)
            if idx is not None:
                mapping[key] = idx
                used.add(idx)
                break
    return mapping


# ---------------------------------------------------------------------------------------------- parsed data


@dataclass
class Sheet:
    name: str
    rows: list[tuple[int, list[str]]]  # (1-based sheet row number, cell texts) — empty rows dropped
    formula_cells: int = 0
    truncated_cells: int = 0

    @property
    def width(self) -> int:
        return max((len(r) for _, r in self.rows), default=0)


@dataclass
class Workbook:
    file_format: str
    sheets: list[Sheet] = field(default_factory=list)

    def sheet(self, name: str) -> Sheet:
        for s in self.sheets:
            if s.name == name:
                return s
        raise ImportRejected("unknown_sheet", "The selected worksheet does not exist in this upload.")


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    return str(value)


def _clean(value: Any, sheet: Sheet) -> str:
    text = unicodedata.normalize("NFC", _text(value)).replace("\x00", "").strip()
    if len(text) > MAX_CELL_CHARS:
        sheet.truncated_cells += 1
        text = text[:MAX_CELL_CHARS]
    return text


def _add_row(sheet: Sheet, number: int, cells: list[str]) -> None:
    if len(cells) > MAX_COLUMNS:
        if any(cells[MAX_COLUMNS:]):
            raise ImportRejected("too_many_columns", f"Worksheets may have at most {MAX_COLUMNS} columns.")
        cells = cells[:MAX_COLUMNS]
    while cells and not cells[-1]:
        cells.pop()
    if not cells:
        return
    if len(sheet.rows) >= settings.ONBOARDING_MAX_ROWS + MAX_HEADER_ROW:
        raise ImportRejected("too_many_rows", f"Worksheets may have at most {settings.ONBOARDING_MAX_ROWS} rows.")
    sheet.rows.append((number, cells))


# ---------------------------------------------------------------------------------------------- entry point


def sniff_format(filename: str, data: bytes) -> str:
    lower = filename.casefold().strip()
    if len(data) == 0:
        raise ImportRejected("empty_file", "The file is empty.")
    if len(data) > settings.ONBOARDING_MAX_UPLOAD_BYTES:
        raise ImportRejected("file_too_large", "The file exceeds the upload size limit.")
    if lower.endswith(".xlsx"):
        if not data.startswith(b"PK\x03\x04"):
            raise ImportRejected("content_mismatch", "The file content is not an Excel workbook.")
        return "xlsx"
    if lower.endswith(".csv"):
        if data.startswith(b"PK") or data.startswith(b"\xd0\xcf\x11\xe0"):
            raise ImportRejected("content_mismatch", "The file content is not CSV text.")
        return "csv"
    raise ImportRejected(
        "unsupported_file_type", "Only .xlsx and .csv files are accepted (macro-enabled and legacy formats are not)."
    )


def parse(filename: str, data: bytes) -> Workbook:
    fmt = sniff_format(filename, data)
    return _parse_xlsx(data) if fmt == "xlsx" else _parse_csv(data)


def _inspect_zip(data: bytes) -> None:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ImportRejected("corrupt_workbook", "The workbook could not be opened.") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > ZIP_MAX_MEMBERS:
            raise ImportRejected("workbook_too_complex", "The workbook contains too many parts.")
        total = 0
        names = set()
        for info in infos:
            name = info.filename.replace("\\", "/").casefold()
            names.add(name)
            if name.startswith("/") or ".." in name.split("/"):
                raise ImportRejected("corrupt_workbook", "The workbook contains an invalid part name.")
            if any(name.startswith(p) or name == p for p in _FORBIDDEN_PARTS):
                raise ImportRejected(
                    "active_content", "Workbooks with macros, embedded objects or external links are not accepted."
                )
            total += info.file_size
            if total > ZIP_MAX_UNCOMPRESSED:
                raise ImportRejected("workbook_too_large", "The workbook expands beyond the size limit.")
            if info.compress_size and info.file_size / info.compress_size > ZIP_MAX_RATIO and info.file_size > 1 << 20:
                raise ImportRejected("workbook_too_large", "The workbook has a suspicious compression ratio.")
        if "xl/workbook.xml" not in names:
            raise ImportRejected("content_mismatch", "The file is not an Excel workbook.")
        content_types = zf.read("[Content_Types].xml") if "[content_types].xml" in names else b""
        if b"macroEnabled" in content_types or b"vbaProject" in content_types:
            raise ImportRejected("active_content", "Macro-enabled workbooks are not accepted.")
        for info in infos:
            if info.filename.casefold().endswith((".xml", ".rels")):
                with zf.open(info) as fh:
                    head = fh.read(4096)
                if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
                    raise ImportRejected("active_content", "Workbooks with XML document type declarations are refused.")


def _parse_xlsx(data: bytes) -> Workbook:
    _inspect_zip(data)
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=False, keep_links=False, keep_vba=False)
    except Exception as exc:  # openpyxl raises many types for malformed input; none are surfaced verbatim
        raise ImportRejected("corrupt_workbook", "The workbook could not be read.") from exc
    out = Workbook("xlsx")
    try:
        worksheets = [ws for ws in wb.worksheets if getattr(ws, "sheet_state", "visible") == "visible"]
        if len(worksheets) > MAX_SHEETS:
            raise ImportRejected("too_many_sheets", f"Workbooks may have at most {MAX_SHEETS} visible worksheets.")
        for ws in worksheets:
            sheet = Sheet(name=str(ws.title)[:64], rows=[])
            for number, row in enumerate(ws.iter_rows(), start=1):
                cells: list[str] = []
                for cell in row:
                    if getattr(cell, "data_type", None) == "f":
                        sheet.formula_cells += 1  # never evaluated, never trusted
                        cells.append("")
                    else:
                        cells.append(_clean(getattr(cell, "value", None), sheet))
                _add_row(sheet, number, cells)
            out.sheets.append(sheet)
    finally:
        wb.close()
    if not out.sheets:
        raise ImportRejected("no_worksheets", "The workbook has no visible worksheets.")
    return out


def _decode(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ImportRejected("encoding_not_supported", "CSV files must be UTF-8 or UTF-16 encoded.") from exc


def _parse_csv(data: bytes) -> Workbook:
    text = _decode(data)
    if "\x00" in text:
        raise ImportRejected("content_mismatch", "The file content is not CSV text.")
    try:
        dialect: Any = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    sheet = Sheet(name="CSV", rows=[])
    previous = csv.field_size_limit(MAX_CELL_CHARS * 8)
    try:
        for number, row in enumerate(csv.reader(io.StringIO(text, newline=""), dialect), start=1):
            _add_row(sheet, number, [_clean(v, sheet) for v in row])
    except csv.Error as exc:
        raise ImportRejected("malformed_csv", "The CSV file could not be parsed.") from exc
    finally:
        csv.field_size_limit(previous)
    return Workbook("csv", [sheet])


# ---------------------------------------------------------------------------------------------- mapping


def headers_for(sheet: Sheet, header_row: int) -> list[str]:
    row = next((cells for n, cells in sheet.rows if n == header_row), [])
    width = max(sheet.width, len(row))
    return [(row[i] if i < len(row) and row[i] else f"Column {i + 1}") for i in range(width)]


def validate_mapping(mapping: dict[str, Any], width: int) -> dict[str, int]:
    clean: dict[str, int] = {}
    used: set[int] = set()
    for key, value in mapping.items():
        if key not in FIELDS:
            raise ImportRejected("invalid_mapping", f"Unknown field '{str(key)[:40]}'.")
        if value is None or value == "":
            continue
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < width:
            raise ImportRejected("invalid_mapping", f"Column for '{key}' is out of range.")
        if value in used:
            raise ImportRejected("invalid_mapping", "A column may be mapped to only one field.")
        used.add(value)
        clean[key] = value
    if not any(k in clean for k in IDENTIFIER_FIELDS):
        raise ImportRejected("invalid_mapping", "Map at least one identifier column (hostname, serial, MAC, ...).")
    return clean


def mapped_rows(sheet: Sheet, header_row: int, mapping: dict[str, int]) -> list[tuple[int, dict[str, str]]]:
    if not 1 <= header_row <= MAX_HEADER_ROW:
        raise ImportRejected("invalid_header_row", f"Header row must be between 1 and {MAX_HEADER_ROW}.")
    out = []
    for number, cells in sheet.rows:
        if number <= header_row:
            continue
        values = {k: (cells[i] if i < len(cells) else "") for k, i in mapping.items()}
        if any(values.values()):
            out.append((number, values))
    if len(out) > settings.ONBOARDING_MAX_ROWS:
        raise ImportRejected("too_many_rows", f"Worksheets may have at most {settings.ONBOARDING_MAX_ROWS} rows.")
    return out
