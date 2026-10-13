"""KRA lookup screen (kra_kyc_snapshot.csv)."""
from __future__ import annotations

from app.trace import tool
from app.tools.db import query

SOURCE = "kra_kyc_snapshot.csv"


@tool("kra.lookup")
def lookup(pan: str | None) -> dict | None:
    """Return the KRA row for a masked PAN with status derived from the code, or None."""
    if not pan:
        return None
    rows = query("SELECT * FROM kra_kyc_snapshot WHERE pan_masked = ?", (pan.strip().upper(),))
    if not rows:
        return None
    r = rows[0]
    r["status"] = r["status_from_code"]
    r["ref"] = f"pan_masked={r['pan_masked']}"
    return r
