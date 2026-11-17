"""Reference versions from the VSA 10 Application Catalog (3rd-Party Patching), pasted by an administrator.

The catalog (https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm) lists
Application | Vendor | Tier | Version | Release Date: the version VSA's 3rd-Party Patching currently packages. The VSA X
API documents no endpoint for it, so the table is copied from that page and pasted here; nothing is fetched.

Only catalog programs that are actually installed on monitored devices become import rows, matched by normalised
name (editions/architecture markers removed) with exact aliases for the installed names seen. The rows then go
through the ordinary catalog import: preview, then approval by a different administrator. The version is "what VSA
deploys", which can trail the vendor's newest release; it is stated as such in the evidence.
"""

from __future__ import annotations

import csv
import re
from collections import Counter, defaultdict
from typing import Any

from django.db.models import Count
from django.utils import timezone
from rest_framework import serializers

from .catalog import MAX_ROWS, build_preview
from .comparator import compare_versions, parse_dotted
from .thirdparty import normalise

CATALOG_URL = "https://help.vsa10.kaseya.com/help/Content/1-Modules/patch-management/application-catalog.htm"
SOURCE_TYPE = "vsa_application_catalog"
MAX_TEXT = 2_000_000
MAX_LINES = 5000
MAX_ALIASES = 50
_ARCH = re.compile(r"\b(?:x64|x86|amd64|arm64|(?:32|64) ?bit)\b")


def key(name: str) -> str:
    """'7-zip (64-bit)' and '7-Zip 26.00 (x64)' -> '7 zip'."""
    return " ".join(_ARCH.sub(" ", normalise(name)).split())


def display_name(name: str) -> str:
    """Catalog name without architecture markers, for the product record."""
    text = re.sub(r"\((?:32|64)-bit\)", " ", name, flags=re.I)
    text = re.sub(r"\b(?:x64|x86)\b", " ", text, flags=re.I)
    return " ".join(text.split())


_SERIES = re.compile(r"(?<![\d.])(\d+\.\d+)(?![\d.]*\d)")
_CHANNEL = re.compile(r"\((?:current|monthly|semiannual)\)", re.I)
_DOTTED_ANY = re.compile(r"\d+(?:\.\d+)+")
_QUALIFIER_DROP = re.compile(r"\b(?:x64|x86|amd64|arm64|(?:32|64|86) ?bit|bit)\b")


def series(name: str) -> str | None:
    """'ASP.NET Core Runtime 8.0' -> '8.0'; 'PowerShell 7.4 (64-bit)' -> '7.4'; '7-zip (64-bit)' -> None."""
    found = _SERIES.findall(name)
    return found[0] if len(found) == 1 else None


def qualified_key(name: str) -> str:
    """Like :func:`key` but keeps words in brackets: 'Microsoft Teams (work or school)' stays distinct."""
    text = _DOTTED_ANY.sub(" ", name.casefold())
    text = re.sub(r"[^0-9a-z]+", " ", text)
    return " ".join(_QUALIFIER_DROP.sub(" ", text).split())


def _starts_with(version: str, prefix: str) -> bool:
    a, b = parse_dotted(version), parse_dotted(prefix)
    return a is not None and b is not None and a[: len(b)] == b


def _split(
    group: list[dict[str, str]], seen: list[tuple[str, str, str, int]]
) -> tuple[list[tuple[list[dict[str, str]], list[tuple[str, str, str, int]]]], str]:
    """Separate catalog lines that share a base name: by version series ('.NET 6.0' / '8.0') or by a qualifier in
    brackets ('Teams' / 'Teams (work or school)'). Returns (units, reason-if-unresolved)."""
    if len({e["version"] for e in group}) == 1:
        return [(group, seen)], ""
    units: dict[str, list[dict[str, str]]] = defaultdict(list)
    serieses = [series(e["application"]) for e in group]
    if all(serieses):
        for e, s_ in zip(group, serieses, strict=True):
            units[s_].append(e)  # type: ignore[index]

        def owner(item: tuple[str, str, str, int]) -> str | None:
            name, _, version, _ = item
            hits = [s_ for s_ in units if _starts_with(version, s_)]
            if len(hits) != 1:
                hits = [s_ for s_ in units if any(_starts_with(n, s_) for n in _DOTTED_ANY.findall(name))]
            return hits[0] if len(hits) == 1 else None

        how = "version series"
    else:
        for e in group:
            units[qualified_key(e["application"])].append(e)

        def owner(item: tuple[str, str, str, int]) -> str | None:
            k = qualified_key(item[0])
            return k if k in units else None

        how = "edition"
    if any(len({e["version"] for e in members}) > 1 for members in units.values()):
        if how == "edition" and all(
            re.search(r"\((?:current|monthly|semiannual)\)", e["application"], re.I) for e in group
        ):
            return [], "Office update channels have different versions and VSA X does not report the channel"
        return [], "Catalog versions differ by architecture (32/64-bit), which VSA X does not report; add it manually"
    assigned: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for item in seen:
        unit = owner(item)
        if unit is not None:
            assigned[unit].append(item)
    if not assigned:
        if all(_CHANNEL.search(e["application"]) for e in group):
            return [], "Office update channels have different versions and VSA X does not report the channel"
        return [], f"The installed program name matches none of the catalog's {how}s exactly; add it manually"
    # The same installed name in two units would match both products (aliases are by name): refuse instead.
    names_per_unit = [{(n, p) for n, p, _, _ in items} for items in assigned.values()]
    all_names: set[tuple[str, str]] = set().union(*names_per_unit)
    if sum(len(n) for n in names_per_unit) != len(all_names):
        return [], f"The installed program name does not tell the catalog's {how}s apart; add it manually"
    return [(units[u], items) for u, items in assigned.items()], ""


def _cells(line: str) -> list[str]:
    if "\t" in line:
        cells = line.split("\t")
    elif line.count("|") >= 4:
        cells = line.strip().strip("|").split("|")
    else:
        cells = next(csv.reader([line]), [])
    return [c.strip() for c in cells]


def parse(text: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    """(entries, skipped). Accepts the table copied from the page (tab separated), CSV or a pipe table."""
    if not isinstance(text, str) or not text.strip():
        raise serializers.ValidationError({"text": "Paste the catalog table."})
    if len(text) > MAX_TEXT:
        raise serializers.ValidationError({"text": "Too much text (2 MB maximum)."})
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) > MAX_LINES:
        raise serializers.ValidationError({"text": f"At most {MAX_LINES} lines."})
    entries, skipped = [], []
    for number, line in enumerate(lines, start=1):
        cells = _cells(line)
        if len(cells) < 4 or cells[0].casefold() == "application" or set(cells[0]) <= set("-: "):
            continue  # header, separator or a non-table line
        name, vendor, tier, version = cells[:4]
        if not name or not tier.isdigit():
            continue
        if "discontinued" in name.casefold():
            skipped.append({"line": number, "application": name, "reason": "Discontinued in the VSA catalog"})
            continue
        if parse_dotted(version) is None:
            skipped.append({"line": number, "application": name, "reason": f"Version '{version[:40]}' is not numeric"})
            continue
        entries.append(
            {
                "application": name[:160],
                "vendor": vendor[:120],
                "tier": tier,
                "version": version,
                "release_date": cells[4][:10] if len(cells) > 4 else "",
            }
        )
    if not entries:
        raise serializers.ValidationError(
            {"text": "No catalog rows found (expected Application, Vendor, Tier, Version)."}
        )
    return entries, skipped


def _installed() -> dict[str, list[tuple[str, str, str, int]]]:
    """Catalog key -> [(name, publisher, version, installs)] across every customer's current snapshot."""
    from apps.integrations.models import DatasetGeneration

    from .models import SoftwareInstallation

    current = DatasetGeneration.objects.filter(is_current=True, dataset="vsa_assets")
    out: dict[str, list[tuple[str, str, str, int]]] = defaultdict(list)
    for name, publisher, version, n in (
        SoftwareInstallation.objects.filter(generation__in=current)
        .values("raw_name", "raw_publisher", "raw_version")
        .annotate(n=Count("id"))
        .values_list("raw_name", "raw_publisher", "raw_version", "n")
        .iterator()
    ):
        k = key(name)
        if k:
            out[k].append((name, publisher, version, n))
    return out


def build(text: str) -> dict[str, Any]:
    """Parse, match to installed programs and return import rows plus the evidence a reviewer needs."""
    entries, skipped = parse(text)
    by_key: dict[str, list[dict[str, str]]] = defaultdict(list)
    for e in entries:
        k = key(e["application"])
        if k:
            by_key[k].append(e)
    installed = _installed()
    now = timezone.now().replace(microsecond=0)
    units = []
    for k, group in sorted(by_key.items()):
        seen = installed.get(k)
        if not seen:
            continue
        resolved, reason = _split(group, seen)
        if reason:
            skipped.append({"application": " / ".join(e["application"] for e in group), "reason": reason})
        units.extend(resolved)
    rows, matched = [], []
    for group, seen in units:
        names = [e["application"] for e in group]
        reference = group[0]["version"]
        entry = group[0]
        aliases = sorted({(name, publisher) for name, publisher, _, _ in seen})
        by_version: Counter[str] = Counter()
        for _, _, version, n in seen:
            by_version[version] += n
        installs = sum(by_version.values())
        comparable = {v: n for v, n in by_version.items() if parse_dotted(v) is not None}
        newer = sum(n for v, n in comparable.items() if compare_versions(v, reference) > 0)
        older = sum(n for v, n in comparable.items() if compare_versions(v, reference) < 0)
        warnings = []
        if comparable and newer * 2 > sum(comparable.values()):
            warnings.append(
                "Most installations report a HIGHER version than the catalog - the version formats may differ; "
                "check before approving."
            )
        if len(aliases) > MAX_ALIASES:
            warnings.append(f"Only the first {MAX_ALIASES} of {len(aliases)} installed names are added as aliases.")
        rows.append(
            {
                "vendor": entry["vendor"] or (aliases[0][1] or "Unknown vendor")[:120],
                "product": display_name(entry["application"])[:160],
                "architecture": "any",
                "reference_version": reference,
                "vendor_url": CATALOG_URL,
                "source_type": SOURCE_TYPE,
                "source_checked_at": now.isoformat(),
                "aliases": [
                    {"name_pattern": name[:255], "publisher_pattern": publisher[:255], "match_type": "exact"}
                    for name, publisher in aliases[:MAX_ALIASES]
                ],
            }
        )
        matched.append(
            {
                "catalog_names": names,
                "vendor": entry["vendor"],
                "tier": entry["tier"],
                "reference_version": reference,
                "release_date": entry["release_date"],
                "installed_names": [n for n, _ in aliases[:5]],
                "installs": installs,
                "older": older,
                "newer": newer,
                "top_versions": [{"version": v, "installs": n} for v, n in by_version.most_common(5)],
                "warnings": warnings,
            }
        )
    # Drop rows whose published reference is already this version (nothing to approve).
    preview, _ = build_preview(rows) if rows else ([], True)
    unchanged = {p["index"] for p in preview if p.get("change") == "same_version"}
    rows = [r for i, r in enumerate(rows) if i not in unchanged]
    matched = [m for i, m in enumerate(matched) if i not in unchanged]
    if len(rows) > MAX_ROWS:
        raise serializers.ValidationError(
            {"text": f"{len(rows)} programs matched; at most {MAX_ROWS} per import. Paste the table in parts."}
        )
    preview, valid = build_preview(rows) if rows else ([], True)
    return {
        "source_url": CATALOG_URL,
        "stats": {
            "catalog_entries": len(entries),
            "matched_programs": len(rows),
            "already_current": len(unchanged),
            "catalog_programs": len(by_key),
            "not_installed": sum(1 for k in by_key if k not in installed),
            "skipped": len(skipped),
        },
        "rows": rows,
        "matched": matched,
        "skipped": skipped[:200],
        "not_installed_programs": sorted(
            {display_name(g[0]["application"]) for k, g in by_key.items() if k not in installed}, key=str.casefold
        )[:400],
        "preview": preview,
        "valid": valid,
    }
