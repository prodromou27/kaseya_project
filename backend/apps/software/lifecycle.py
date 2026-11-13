"""VSA4-05: OS and software lifecycle classification against the reviewed lifecycle catalog.

Status per device OS / per software installation, as of a given date:

* ``end_of_support``  - an approved, official entry matches and its end of support is before the date;
* ``ending_soon``     - it ends within ``ENDING_SOON_DAYS``;
* ``supported``       - it ends later;
* ``unknown``         - no entry, only unverified (secondary) entries, conflicting entries, an unreported or
  unparsable version, or a software install without a reviewed catalog product.

Unknown is never counted as supported or unsupported. Nothing here infers a date: every status other than unknown
cites exactly one approved entry (source URL, checked date, reviewer).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

from apps.inventory.models import AssetObservation
from apps.inventory.queries import current_generations, current_observations

from .models import ComplianceResult, LifecycleEntry
from .queries import current_results

ALGORITHM_VERSION = "lifecycle-1"
ENDING_SOON_DAYS = 180
STATUSES = ("end_of_support", "ending_soon", "supported", "unknown")
LABELS = {
    "end_of_support": "End of support",
    "ending_soon": f"Ends within {ENDING_SOON_DAYS} days",
    "supported": "Supported",
    "unknown": "Unknown",
}
REASONS = {
    "matched": "Matched an approved official lifecycle entry.",
    "no_entry": "No approved lifecycle entry matches.",
    "unverified_only": "Only unverified (secondary-source) entries match.",
    "conflicting_entries": "Several equally specific approved entries with different dates match.",
    "os_not_reported": "The OS name was not reported.",
    "version_not_parsable": "The reported version/build could not be parsed.",
    "product_not_catalogued": "The installation is not matched to a reviewed catalog product.",
}

_LEADING_DOTTED = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def version_parts(value: str) -> tuple[int, ...] | None:
    """Leading dotted numbers, kept exactly (10.0.22631.0 -> (10, 0, 22631, 0)); None when there are none."""
    match = _LEADING_DOTTED.match(value or "")
    return tuple(int(p) for p in match.group(1).split(".")) if match else None


def prefix_matches(version: tuple[int, ...] | None, prefix: str) -> bool:
    if not prefix:
        return True
    wanted = version_parts(prefix)
    return version is not None and wanted is not None and version[: len(wanted)] == wanted


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str
    entry: LifecycleEntry | None = None


def classify(
    candidates: list[LifecycleEntry], version: tuple[int, ...] | None, has_version: bool, on: dt.date
) -> Verdict:
    """Pick the most specific matching approved entry; official entries only; conflicts -> unknown."""
    matching = [e for e in candidates if prefix_matches(version, e.version_prefix)]
    if not matching:
        if any(e.version_prefix for e in candidates) and not has_version:
            return Verdict("unknown", "version_not_parsable")
        return Verdict("unknown", "no_entry")
    official = [e for e in matching if e.confidence == LifecycleEntry.Confidence.OFFICIAL]
    if not official:
        return Verdict("unknown", "unverified_only")
    depth = max(len(version_parts(e.version_prefix) or ()) for e in official)
    best = [e for e in official if len(version_parts(e.version_prefix) or ()) == depth]
    if len({e.end_of_support for e in best}) > 1:
        return Verdict("unknown", "conflicting_entries")
    entry = best[0]
    if entry.end_of_support < on:
        return Verdict("end_of_support", "matched", entry)
    if entry.end_of_support <= on + dt.timedelta(days=ENDING_SOON_DAYS):
        return Verdict("ending_soon", "matched", entry)
    return Verdict("supported", "matched", entry)


def approved_entries(
    entry_ids: list[str] | None = None,
) -> tuple[list[LifecycleEntry], dict[Any, list[LifecycleEntry]]]:
    """Approved entries now, or exactly the pinned ones (immutable rows, possibly retired since) for a report."""
    qs = LifecycleEntry.objects.select_related("reviewed_by", "product")
    if entry_ids is None:
        qs = qs.filter(state=LifecycleEntry.State.APPROVED)
    else:
        qs = qs.filter(id__in=entry_ids, state__in=[LifecycleEntry.State.APPROVED, LifecycleEntry.State.RETIRED])
    rows = list(qs)
    by_product: dict[Any, list[LifecycleEntry]] = defaultdict(list)
    for e in rows:
        if e.kind == LifecycleEntry.Kind.SOFTWARE:
            by_product[e.product_id].append(e)
    return [e for e in rows if e.kind == LifecycleEntry.Kind.OS], by_product


def os_candidates(os_entries: list[LifecycleEntry], os_name: str) -> list[LifecycleEntry]:
    """Entries whose family is contained in the OS name; only the longest (most specific) family names are kept,
    so 'Windows Server 2016' wins over a hypothetical 'Windows Server'."""
    name = (os_name or "").casefold()
    hits = [e for e in os_entries if e.os_family.casefold() in name]
    if not hits:
        return []
    longest = max(len(e.os_family) for e in hits)
    return [e for e in hits if len(e.os_family) == longest]


def entry_dict(e: LifecycleEntry | None) -> dict[str, Any] | None:
    if e is None:
        return None
    return {
        "id": str(e.id),
        "label": f"{e.os_family or (str(e.product) if e.product else '')} {e.release_label}".strip(),
        "release_label": e.release_label,
        "version_prefix": e.version_prefix,
        "edition_note": e.edition_note,
        "release_date": e.release_date,
        "end_of_mainstream": e.end_of_mainstream,
        "end_of_support": e.end_of_support,
        "extended_until": e.extended_until,
        "source_url": e.source_url,
        "source_type": e.source_type,
        "source_checked_at": e.source_checked_at,
        "reviewed_by": e.reviewed_by.email if e.reviewed_by_id else None,
    }


def os_rows(
    customer_id: Any, on: dt.date, *, generation_ids: list[str] | None = None, entry_ids: list[str] | None = None
) -> list[dict[str, Any]]:
    os_entries, _ = approved_entries(entry_ids)
    observations = current_observations(customer_id)
    if generation_ids is not None:
        observations = AssetObservation.objects.filter(customer_id=customer_id, generation_id__in=generation_ids)
    rows = []
    for obs in observations.order_by("hostname", "id"):
        if not obs.os_name:
            verdict = Verdict("unknown", "os_not_reported")
        else:
            parts = version_parts(obs.os_version)
            verdict = classify(os_candidates(os_entries, obs.os_name), parts, parts is not None, on)
        rows.append(
            {
                "asset_id": str(obs.asset_id),
                "hostname": obs.hostname,
                "os_name": obs.os_name,
                "os_version": obs.os_version,
                "status": verdict.status,
                "reason": verdict.reason,
                "entry": entry_dict(verdict.entry),
            }
        )
    return rows


def software_rows(
    customer_id: Any,
    on: dt.date,
    *,
    generation_ids: list[str] | None = None,
    evaluation_ids: list[str] | None = None,
    entry_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    _, by_product = approved_entries(entry_ids)
    observations = current_observations(customer_id)
    results = current_results(customer_id)
    if generation_ids is not None:
        observations = AssetObservation.objects.filter(customer_id=customer_id, generation_id__in=generation_ids)
    if evaluation_ids is not None:
        results = ComplianceResult.objects.filter(customer_id=customer_id, evaluation_id__in=evaluation_ids)
        results = results.select_related("installation", "product")
    hosts = dict(observations.values_list("asset_id", "hostname"))
    rows = []
    for r in results.order_by("installation__raw_name", "id"):
        if r.product_id is None:
            verdict = Verdict("unknown", "product_not_catalogued")
        else:
            parts = version_parts(r.installation.raw_version)
            verdict = classify(by_product.get(r.product_id, []), parts, parts is not None, on)
        rows.append(
            {
                "asset_id": str(r.asset_id),
                "hostname": hosts.get(r.asset_id, ""),
                "name": r.installation.raw_name,
                "installed_version": r.installation.raw_version,
                "product": str(r.product) if r.product else None,
                "status": verdict.status,
                "reason": verdict.reason,
                "entry": entry_dict(verdict.entry),
            }
        )
    return rows


def _groups(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    """Aggregate rows by matched entry (or by reported value when unknown)."""
    grouped: dict[tuple, dict[str, Any]] = {}
    for r in rows:
        ident = (r["status"], r["entry"]["id"] if r["entry"] else f"{r['reason']}|{r.get(key) or ''}")
        g = grouped.setdefault(
            ident,
            {
                "status": r["status"],
                "reason": r["reason"],
                "entry": r["entry"],
                "reported": r.get(key) or "",
                "count": 0,
            },
        )
        g["count"] += 1
    order = {s: i for i, s in enumerate(STATUSES)}
    return sorted(grouped.values(), key=lambda g: (order[g["status"]], -g["count"], g["reported"]))


def summary(customer_id: Any, on: dt.date | None = None) -> dict[str, Any]:
    on = on or dt.date.today()
    oses = os_rows(customer_id, on)
    software = software_rows(customer_id, on)
    gens = list(current_generations(customer_id))
    return {
        "evaluated_on": on,
        "algorithm_version": ALGORITHM_VERSION,
        "ending_soon_days": ENDING_SOON_DAYS,
        "as_of": [g.published_at.isoformat() if g.published_at else None for g in gens],
        "data_basis": sorted({g.data_basis for g in gens}),
        "labels": LABELS,
        "reasons": REASONS,
        "os": {
            "devices": len(oses),
            "totals": {s: Counter(r["status"] for r in oses).get(s, 0) for s in STATUSES},
            "groups": _groups(oses, "os_name"),
        },
        "software": {
            "installations": len(software),
            "totals": {s: Counter(r["status"] for r in software).get(s, 0) for s in STATUSES},
            "devices_with_end_of_support": len({r["asset_id"] for r in software if r["status"] == "end_of_support"}),
            "groups": _groups(software, "name"),
        },
        "notes": [
            "Only approved lifecycle entries from official vendor sources classify a device; "
            "everything else is unknown.",
            "Unknown is never counted as supported.",
            "Lifecycle status is evaluated on the date shown against the latest snapshot; it is not a patch or "
            "vulnerability statement.",
        ],
    }
