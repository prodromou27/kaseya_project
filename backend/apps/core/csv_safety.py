"""Spreadsheet formula-injection defence for CSV/XLSX exports (SECURITY.md §4, TESTING.md REP-02)."""

from __future__ import annotations

from typing import Any

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def neutralize_cell(value: Any) -> str:
    """Return a string safe to place in a spreadsheet cell.

    Any value beginning with a formula trigger character is prefixed with a single quote so that
    spreadsheet applications treat it as text. ``None`` becomes an empty string.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text
