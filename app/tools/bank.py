"""Bank-mandate register (bank_mandates.csv)."""
from __future__ import annotations

from app.trace import tool
from app.tools.db import query

SOURCE = "bank_mandates.csv"


def _holders(row: dict) -> list[str]:
    return [h.strip() for h in (row.get("account_holders") or "").split(";") if h.strip()]


@tool("bank.accounts")
def accounts(folio_no: str | None) -> list[dict]:
    if not folio_no:
        return []
    rows = query("SELECT * FROM bank_mandates WHERE folio_no = ?", (folio_no,))
    for r in rows:
        r["holders"] = _holders(r)
        r["ref"] = f"{r['folio_no']}|{r['account_no_masked']}"
    return rows


@tool("bank.find_by_account")
def find_by_account(last4: str | None, folio_no: str | None = None) -> list[dict]:
    """Mandate rows whose account ends with last4 (optionally within one folio)."""
    if not last4:
        return []
    if folio_no:
        rows = query("SELECT * FROM bank_mandates WHERE account_last4 = ? AND folio_no = ?", (last4, folio_no))
    else:
        rows = query("SELECT * FROM bank_mandates WHERE account_last4 = ?", (last4,))
    for r in rows:
        r["holders"] = _holders(r)
        r["ref"] = f"{r['folio_no']}|{r['account_no_masked']}"
    return rows


def default_account(rows: list[dict]) -> dict | None:
    for r in rows:
        if r.get("is_default") == "Y" and r.get("status") != "DELETED":
            return r
    return None
