"""VSA2-04 onboarding reconciliation exports: multi-tab XLSX and CSV, both built from the immutable stored results."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable
from typing import Any

from django.utils import timezone

from apps.reporting.renderers import render_csv, render_xlsx_sheets

from .models import ReconciliationResult, ReconciliationRun

TABS = [
    ("Matched Correct", {"MATCHED_CORRECT"}),
    ("Wrong Group", {"MATCHED_WRONG_GROUP"}),
    ("Wrong Site", {"MATCHED_WRONG_SITE", "REVIEW_WRONG_ORGANIZATION"}),
    ("Not Found", {"NOT_FOUND_IN_COMPLETE_SNAPSHOT"}),
    ("Ambiguous", {"AMBIGUOUS"}),
    ("Duplicate-Invalid", {"DUPLICATE_INPUT", "INVALID_INPUT"}),
]
EXPECTED_COLUMNS = [
    "Row",
    "Classification",
    "Reviewed classification",
    "Review state",
    "Reviewer",
    "Review note",
    "Secondary flags",
    "Match basis",
    "Candidates",
    "Evidence",
    "Matched source ID",
    "Input hostname",
    "Input FQDN",
    "Input serial",
    "Input MAC",
    "Input IP",
    "Input asset tag",
    "Input source ID",
    "Expected organisation",
    "Expected site",
    "Expected group",
    "Actual hostname",
    "Actual organisation",
    "Actual site",
    "Actual group",
    "Last seen online",
    "Device type",
    "Department",
    "Notes",
    "Source generation",
    "Snapshot published",
]
UNEXPECTED_COLUMNS = [
    "Source ID",
    "Hostname",
    "Organisation",
    "Site",
    "Group",
    "Last seen online",
    "Agent installed",
    "Candidate of ambiguous row (pending review)",
    "Source generation",
]


def _expected_row(r: ReconciliationResult, run: ReconciliationRun) -> list[Any]:
    i, a, ev = r.input, r.actual, r.evidence
    return [
        r.row_number,
        r.classification,
        r.reviewed_classification,
        r.review_state,
        r.reviewed_by.email if r.reviewed_by_id and r.reviewed_by else "",
        r.review_note,
        ", ".join(r.flags),
        ev.get("basis", ""),
        len(r.candidate_asset_ids) or "",
        json.dumps(ev, sort_keys=True),
        a.get("source_id", ""),
        i.get("hostname", ""),
        i.get("fqdn", ""),
        i.get("serial_number", ""),
        i.get("mac", ""),
        i.get("ip_address", ""),
        i.get("asset_tag", ""),
        i.get("source_device_id", ""),
        i.get("expected_organization", ""),
        i.get("expected_site", ""),
        i.get("expected_group", ""),
        a.get("hostname", ""),
        a.get("organization", "") or a.get("organization_id", ""),
        a.get("site", "") or a.get("site_id", ""),
        a.get("group", "") or a.get("group_id", ""),
        a.get("last_seen_online", ""),
        i.get("device_type", ""),
        i.get("department", ""),
        i.get("notes", ""),
        str(run.generation_id),
        run.summary.get("generation", {}).get("published_at", ""),
    ]


def _unexpected_row(r: ReconciliationResult, run: ReconciliationRun) -> list[Any]:
    a = r.actual
    agent = a.get("agent_installed")
    return [
        a.get("source_id", ""),
        a.get("hostname", ""),
        a.get("organization", "") or a.get("organization_id", ""),
        a.get("site", "") or a.get("site_id", ""),
        a.get("group", "") or a.get("group_id", ""),
        a.get("last_seen_online", ""),
        "unknown" if agent is None else ("yes" if agent else "no"),
        r.pending_review_row or "",
        str(run.generation_id),
    ]


def provenance(run: ReconciliationRun) -> dict[str, str]:
    s = run.summary
    return {
        "Customer": f"{run.customer.name} ({run.customer.code})",
        "Generated": timezone.now().isoformat(),
        "Reconciliation run": str(run.id),
        "Upload": f"{run.upload_name} (sha256 {run.upload_sha256})",
        "Worksheet / header row": f"{run.sheet} / {run.header_row}",
        "Mapping hash": run.mapping_hash,
        "Matching logic": run.logic_version,
        "VSA snapshot (generation)": f"{run.generation_id} published {s.get('generation', {}).get('published_at', '')}",
        "Data basis": run.data_basis,
        "Stale source acknowledged": "yes" if run.stale_source_acknowledged else "no",
        "Device moves": "Not performed. This portal is read-only toward VSA X; moving devices is disabled.",
    }


def _recommendations(counts: Counter[str], run: ReconciliationRun) -> list[list[Any]]:
    s = run.summary
    recs = []

    def add(n: int, text: str) -> None:
        if n:
            recs.append([n, text])

    add(
        counts["MATCHED_WRONG_GROUP"],
        "Device(s) are in a different VSA group than expected. Review and move them in VSA X through the approved "
        "change process (moves are not performed by this portal).",
    )
    add(
        counts["MATCHED_WRONG_SITE"],
        "Device(s) are in a different site than expected. Confirm the expected site or correct placement in VSA X.",
    )
    add(
        counts["REVIEW_WRONG_ORGANIZATION"],
        "Device(s) matched under a different organisation than expected. An authorised reviewer must confirm.",
    )
    add(
        counts["NOT_FOUND_IN_COMPLETE_SNAPSHOT"],
        "Expected device(s) were not found in the snapshot. Check naming/serials and whether the agent was deployed; "
        "absence is not proof the agent is missing.",
    )
    add(
        counts["AMBIGUOUS"],
        "Row(s) matched several devices or only by MAC/IP. Resolve them in the portal review queue.",
    )
    add(
        counts["DUPLICATE_INPUT"] + counts["INVALID_INPUT"],
        "Spreadsheet row(s) are duplicated or lack a valid identifier. Correct the source spreadsheet.",
    )
    add(
        s.get("unexpected_vsa_assets", 0),
        "VSA device(s) are not represented in the expected inventory. Confirm whether they belong to this "
        "customer's estate.",
    )
    flags = s.get("secondary_flags", {})
    add(
        flags.get("STALE_AGENT", 0),
        f"Matched device(s) have not reported for {s.get('parameters', {}).get('stale_agent_days', 7)}+ days "
        "(still counted as onboarded).",
    )
    add(flags.get("MISSING_NETWORK_DATA", 0), "Matched device(s) have no reported network data in the snapshot.")
    if not recs:
        recs.append(["", "No follow-up actions identified."])
    return recs


def results(run: ReconciliationRun) -> tuple[list[ReconciliationResult], list[ReconciliationResult]]:
    qs = ReconciliationResult.objects.filter(run=run, customer_id=run.customer_id).select_related("reviewed_by")
    expected = [r for r in qs if r.kind == "expected"]
    expected.sort(key=lambda r: r.row_number or 0)
    unexpected = [r for r in qs if r.kind == "unexpected"]
    return expected, unexpected


def build_xlsx(run: ReconciliationRun) -> tuple[bytes, int]:
    expected, unexpected = results(run)
    counts = Counter(r.effective_classification for r in expected)
    s = run.summary
    summary_rows: list[list[Any]] = [["Expected rows", len(expected)]]
    summary_rows += [[cls, counts.get(cls, 0)] for cls in sorted({*counts, *s.get("classifications", {})})]
    summary_rows += [
        ["Unexpected VSA assets", s.get("unexpected_vsa_assets", 0)],
        ["Unexpected (candidate of a pending review)", s.get("unexpected_pending_review", 0)],
        ["Devices in snapshot", s.get("snapshot_devices", 0)],
        ["Pending reviews", sum(1 for r in expected if r.review_state == "pending")],
    ]
    summary_rows += [[f"Flag {k}", v] for k, v in s.get("secondary_flags", {}).items()]
    summary_rows += [
        [f"Not evaluated: {k}", v] for k, v in s.get("parameters", {}).get("flags_not_evaluated", {}).items()
    ]
    summary_rows += [["Note", n] for n in s.get("notes", [])]

    sheets: list[tuple[str, list[str], Iterable[list[Any]]]] = [
        ("Summary", ["Measure", "Value"], summary_rows),
        ("All Expected", EXPECTED_COLUMNS, [_expected_row(r, run) for r in expected]),
    ]
    for name, classes in TABS:
        sheets.append(
            (name, EXPECTED_COLUMNS, [_expected_row(r, run) for r in expected if r.effective_classification in classes])
        )
    sheets.append(("Unexpected VSA", UNEXPECTED_COLUMNS, [_unexpected_row(r, run) for r in unexpected]))
    sheets.append(("Recommendations", ["Count", "Recommendation"], _recommendations(counts, run)))
    title = f"Onboarding reconciliation — {run.customer.code}"
    return render_xlsx_sheets(title, provenance(run), sheets), len(expected) + len(unexpected)


def build_csv(run: ReconciliationRun, part: str) -> tuple[bytes, int]:
    expected, unexpected = results(run)
    title = f"Onboarding reconciliation — {run.customer.code} — {part}"
    if part == "unexpected":
        rows = [_unexpected_row(r, run) for r in unexpected]
        return render_csv(title, provenance(run), UNEXPECTED_COLUMNS, rows), len(rows)
    rows = [_expected_row(r, run) for r in expected]
    return render_csv(title, provenance(run), EXPECTED_COLUMNS, rows), len(rows)
