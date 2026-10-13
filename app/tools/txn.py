"""Transaction register (transactions.csv)."""
from __future__ import annotations

from datetime import date, timedelta

from app.normalise import financial_year, parse_date
from app.trace import tool
from app.tools.db import query

SOURCE = "transactions.csv"
LIVE_STATUSES = ("PROCESSED", "PENDING_TCC")


def _clean(rows: list[dict]) -> list[dict]:
    for r in rows:
        r["flags"] = [f for f in (r.get("data_flags") or "").split(",") if f]
    return rows


@tool("txn.pending")
def pending(folio_no: str | None) -> list[dict]:
    if not folio_no:
        return []
    return _clean(query("SELECT * FROM transactions WHERE folio_no = ? AND status = 'PENDING_TCC' ORDER BY txn_id", (folio_no,)))


@tool("txn.by_utr")
def by_utr(utr: str | None) -> list[dict]:
    if not utr:
        return []
    return _clean(query("SELECT * FROM transactions WHERE utr = ? ORDER BY txn_id", (utr.strip().upper(),)))


@tool("txn.history")
def history(folio_no: str | None, since: date | None = None, until: date | None = None) -> list[dict]:
    """Live (processed/pending), de-duplicated transactions of a folio within [since, until]."""
    if not folio_no:
        return []
    rows = _clean(query("SELECT * FROM transactions WHERE folio_no = ? ORDER BY txn_date, txn_id", (folio_no,)))
    out = []
    for r in rows:
        if r["status"] not in LIVE_STATUSES or r.get("duplicate_of"):
            continue
        d = parse_date(r["txn_date"])
        if d is None:
            continue
        if since and d < since:
            continue
        if until and d > until:
            continue
        out.append(r)
    return out


@tool("txn.cash_total")
def cash_total(folio_nos: list[str], on: date, exclude_txn: str | None = None) -> tuple[float, list[dict]]:
    """Sum of processed (accepted), non-duplicate CASH purchases across the given folios in the FY of `on`."""
    if not folio_nos:
        return 0.0, []
    fy = financial_year(on)
    marks = ",".join("?" for _ in folio_nos)
    rows = _clean(query(f"SELECT * FROM transactions WHERE payment_mode = 'CASH' AND folio_no IN ({marks})", tuple(folio_nos)))
    hits = []
    for r in rows:
        d = parse_date(r["txn_date"])
        if (r["status"] != "PROCESSED" or r.get("duplicate_of") or r["txn_id"] == exclude_txn or d is None
                or financial_year(d) != fy or r["txn_type"] not in ("NEW", "ADD", "SIP_REG", "SIP")):
            continue
        hits.append(r)
    return sum(float(r["amount_inr"] or 0) for r in hits), hits


def window(d: date, days: int) -> tuple[date, date]:
    return d - timedelta(days=days), d + timedelta(days=days)
