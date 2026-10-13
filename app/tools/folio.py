"""Folio master screen (folio_master.csv)."""
from __future__ import annotations

from app.trace import tool
from app.tools.db import query

SOURCE = "folio_master.csv"


@tool("folio.get")
def get(folio_no: str | None) -> dict | None:
    """Exact lookup by canonical folio. Never fuzzy."""
    if not folio_no:
        return None
    rows = query("SELECT * FROM folio_master WHERE folio_no = ?", (folio_no,))
    return rows[0] if rows else None


@tool("folio.by_pan")
def by_pan(pan: str | None, role: str = "any") -> list[dict]:
    """Folios where the PAN is first holder (role='first') or any holder/guardian (role='any')."""
    if not pan:
        return []
    if role == "first":
        return query("SELECT * FROM folio_master WHERE first_holder_pan_masked = ?", (pan,))
    return query(
        "SELECT * FROM folio_master WHERE first_holder_pan_masked = ? OR second_holder_pan_masked = ? "
        "OR guardian_pan_masked = ?", (pan, pan, pan))


def is_minor_folio(f: dict) -> bool:
    return str(f.get("tax_status", "")).startswith("02")


def holder_pans(f: dict) -> list[str]:
    return [p for p in (f.get("first_holder_pan_masked"), f.get("second_holder_pan_masked")) if p]
