"""Formula-safe spreadsheet cells (DH11).

Scraped text and model text end up in CSV files people open in Excel, Google
Sheets or Notion. A cell that starts with = + - @ (or a tab / carriage return
before one) can run as a formula ("CSV injection"); such a cell gets a leading
apostrophe, which spreadsheets show as plain text. Line breaks inside a cell
stay (the csv module quotes them); control characters are removed.
"""

from __future__ import annotations

import re

_TRIGGERS = ("=", "+", "-", "@", "\t", "\r")
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def safe_cell(value: object) -> str:
    """One cell as text that a spreadsheet will never evaluate."""
    text = _CONTROL.sub("", "" if value is None else str(value))
    if text.lstrip(" ").startswith(_TRIGGERS) or text.startswith(_TRIGGERS):
        return "'" + text
    return text


def safe_row(values: list[object]) -> list[str]:
    return [safe_cell(v) for v in values]
