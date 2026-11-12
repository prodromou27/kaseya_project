"""Report file renderers (P2-04). Every renderer receives the same provenance block and row set, so CSV, XLSX and
PDF artifacts of one run contain identical records.

Injection defences:
* CSV/XLSX — every cell is neutralised (formula prefixes), written as an explicit *string* cell, and XML-illegal
  control characters are removed (SECURITY.md §4, REP-02).
* PDF — all text is XML-escaped before reaching ReportLab's paragraph markup parser (SEC-02).
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Any
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE, WriteOnlyCell
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import LongTable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from apps.core.csv_safety import neutralize_cell

CONTENT_TYPES = {
    "csv": "text/csv",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "pdf": "application/pdf",
}
PDF_MAX_ROWS = 5000
BRAND = "Odyssey Kaseya Analytics & Reporting Portal"


class RenderLimitError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _cell(value: Any) -> str:
    return ILLEGAL_CHARACTERS_RE.sub("", neutralize_cell(value))


def render_csv(title: str, provenance: dict[str, str], columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, quoting=csv.QUOTE_MINIMAL)
    for key, value in provenance.items():
        writer.writerow([f"# {key}: {value}"])
    writer.writerow(columns)
    for row in rows:
        writer.writerow([neutralize_cell(v) for v in row])
    return buffer.getvalue().encode("utf-8-sig")


def render_xlsx(title: str, provenance: dict[str, str], columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    wb = Workbook(write_only=True)
    data = wb.create_sheet("Data")
    header_font, header_fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1E3A5F")

    def string_cell(ws: Any, value: Any, *, header: bool = False) -> WriteOnlyCell:
        c = WriteOnlyCell(ws, value=_cell(value))
        c.data_type = "s"  # never a formula, never coerced
        if header:
            c.font, c.fill = header_font, header_fill
        return c

    data.freeze_panes = "A2"
    for i, _col in enumerate(columns):
        data.column_dimensions[get_column_letter(i + 1)].width = 22
    data.append([string_cell(data, c, header=True) for c in columns])
    for row in rows:
        data.append([string_cell(data, v) for v in row])

    prov = wb.create_sheet("Provenance")
    prov.column_dimensions["A"].width = 34
    prov.column_dimensions["B"].width = 120
    title_cell = WriteOnlyCell(prov, value=_cell(title))
    title_cell.font = Font(bold=True, size=14)
    prov.append([title_cell])
    for key, value in provenance.items():
        k = string_cell(prov, key)
        k.font = Font(bold=True)
        v = string_cell(prov, value)
        v.alignment = Alignment(wrap_text=True, vertical="top")
        prov.append([k, v])
    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


def _p(text: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str("" if text is None else text)), style)


def render_pdf(title: str, provenance: dict[str, str], columns: Sequence[str], rows: Sequence[Sequence[Any]]) -> bytes:
    if len(rows) > PDF_MAX_ROWS:
        raise RenderLimitError("too_many_rows_for_pdf")
    styles = getSampleStyleSheet()
    small = ParagraphStyle("small", parent=styles["BodyText"], fontSize=7, leading=8.5)
    head = ParagraphStyle("head", parent=small, textColor=colors.white, fontName="Helvetica-Bold")
    label = ParagraphStyle("label", parent=styles["BodyText"], fontSize=8, leading=10, fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=8, leading=10)
    customer = provenance.get("Customer", "")
    generated = provenance.get("Generated", "")
    basis = provenance.get("Data basis", "")

    def on_page(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        w, h = landscape(A4)
        canvas.setFillColor(colors.HexColor("#1E3A5F"))
        canvas.rect(0, h - 14 * mm, w, 14 * mm, stroke=0, fill=1)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 10)
        canvas.drawString(12 * mm, h - 9 * mm, BRAND)
        canvas.setFont("Helvetica", 9)
        canvas.drawRightString(w - 12 * mm, h - 9 * mm, f"{customer}"[:110])
        canvas.setFillColor(colors.HexColor("#475569"))
        canvas.setFont("Helvetica", 7)
        canvas.drawString(
            12 * mm, 8 * mm, f"Generated {generated} · data basis: {basis} · Confidential — customer scoped"[:200]
        )
        canvas.drawRightString(w - 12 * mm, 8 * mm, f"Page {doc.page}")
        canvas.restoreState()

    out = io.BytesIO()
    doc = SimpleDocTemplate(
        out,
        pagesize=landscape(A4),
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=20 * mm,
        bottomMargin=14 * mm,
        title=title,
        author=BRAND,
    )
    story: list[Any] = [_p(title, styles["Title"]), Spacer(1, 4 * mm)]
    prov_table = Table([[_p(k, label), _p(v, body)] for k, v in provenance.items()], colWidths=[55 * mm, 210 * mm])
    prov_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
            ]
        )
    )
    story += [prov_table, PageBreak()]
    if rows:
        width = (landscape(A4)[0] - 24 * mm) / max(len(columns), 1)
        data = [[_p(c, head) for c in columns]] + [[_p(v, small) for v in row] for row in rows]
        table = LongTable(data, repeatRows=1, colWidths=[width] * len(columns))
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A5F")),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F1F5F9")]),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#CBD5E1")),
                ]
            )
        )
        story.append(table)
    else:
        story.append(_p("No records match this report's filters.", body))
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out.getvalue()


RENDERERS = {"csv": render_csv, "xlsx": render_xlsx, "pdf": render_pdf}
