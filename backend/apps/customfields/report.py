"""Job results as CSV (one sheet) or XLSX (Summary, Successful, Skipped, Failed, Not found, Ambiguous).

Every cell is formula-neutralised and written as text; nothing from VSA X or an uploaded file can run in Excel.
"""

from __future__ import annotations

import csv
import io
from typing import Any

from apps.core.csv_safety import neutralize_cell

from .models import AssignmentItem as Item
from .models import AssignmentJob as Job

COLUMNS = (
    "Input identifier",
    "Input row",
    "Match",
    "Matched VSA device",
    "Hostname",
    "Customer",
    "Site",
    "Group",
    "Field",
    "Previous value",
    "Value source",
    "Requested value",
    "Final verified value",
    "Action",
    "Result",
    "Timestamp (UTC)",
    "Details",
)
SUCCESS = {Item.Result.VERIFIED}
SKIPPED = {Item.Result.ALREADY_CORRECT, Item.Result.SKIPPED, Item.Result.NOT_RUN, Item.Result.CANCELLED}
FAILED = {Item.Result.FAILED, Item.Result.UNKNOWN, Item.Result.VERIFICATION_FAILED, Item.Result.VERIFICATION_PENDING}


def _row(job: Job, i: Item) -> list[str]:
    details = "; ".join(x for x in (i.match_note, i.action_note, i.error_code) if x)
    when = i.finished_at or job.finished_at
    return [
        i.input_identifier,
        str(i.input_row or ""),
        i.get_match_status_display(),
        i.device_external_id,
        i.hostname,
        job.customer.name,
        i.site,
        i.group,
        job.field.name,
        "" if i.current_value is None else i.current_value,
        i.current_source,
        i.requested_value or job.value,
        "" if i.final_value is None else i.final_value,
        i.get_action_display() if i.action else "",
        i.get_result_display(),
        when.strftime("%Y-%m-%d %H:%M:%S") if when else "",
        details,
    ]


def _items(job: Job) -> list[Item]:
    return list(job.items.all().order_by("position"))


def summary_rows(job: Job) -> list[tuple[str, str]]:
    counts = job.counts or {}
    rows = [
        ("Customer", job.customer.name),
        ("VSA X integration", job.integration_instance.name),
        ("Field", f"{job.field.name} (ID {job.field.external_id}, {job.field.type})"),
        ("Value", job.value or "per device"),
        ("Source", job.get_source_display() + (f": {job.source_filename}" if job.source_filename else "")),
        ("Requested by", job.created_by.email),
        ("Confirmed by", job.confirmed_by.email if job.confirmed_by else ""),
        ("Approved by", job.approved_by.email if job.approved_by else ""),
        ("State", job.get_state_display()),
        ("Started (UTC)", job.started_at.strftime("%Y-%m-%d %H:%M:%S") if job.started_at else ""),
        ("Finished (UTC)", job.finished_at.strftime("%Y-%m-%d %H:%M:%S") if job.finished_at else ""),
        ("Devices listed", str(counts.get("items", 0))),
    ]
    labels = dict(Item.Result.choices)
    rows += [(f"Result: {labels.get(k, k)}", str(v)) for k, v in sorted((counts.get("result") or {}).items())]
    rows.append(("Data basis", "Fixture (demo) integration" if job.integration_instance.is_fixture else "VSA X"))
    return rows


def render_csv(job: Job) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    for i in _items(job):
        writer.writerow([neutralize_cell(c) for c in _row(job, i)])
    return out.getvalue().encode("utf-8-sig")


def render_xlsx(job: Job) -> bytes:
    from openpyxl import Workbook
    from openpyxl.cell import WriteOnlyCell

    wb = Workbook(write_only=True)

    def sheet(title: str, header: tuple[str, ...], rows: list[list[Any]]) -> None:
        ws = wb.create_sheet(title)
        for row in [list(header), *rows]:
            cells = []
            for value in row:
                c = WriteOnlyCell(ws, value=neutralize_cell(value))
                c.data_type = "s"
                cells.append(c)
            ws.append(cells)

    items = _items(job)
    sheet("Summary", ("Item", "Value"), [list(r) for r in summary_rows(job)])
    groups = (
        ("Successful", lambda i: i.result in SUCCESS),
        ("Skipped", lambda i: i.match_status == Item.Match.MATCHED and i.result in SKIPPED),
        ("Failed", lambda i: i.result in FAILED),
        (
            "Not found",
            lambda i: (
                i.match_status
                in (
                    Item.Match.NOT_FOUND,
                    Item.Match.INVALID,
                    Item.Match.OTHER_CUSTOMER,
                    Item.Match.UNSUPPORTED,
                    Item.Match.DUPLICATE,
                )
            ),
        ),
        ("Ambiguous", lambda i: i.match_status == Item.Match.MULTIPLE),
    )
    for title, pick in groups:
        sheet(title, COLUMNS, [_row(job, i) for i in items if pick(i)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
