"""Distributor master (distributor_master.csv)."""
from __future__ import annotations

import re
from datetime import date

from app.normalise import parse_date
from app.trace import tool
from app.tools.db import query

SOURCE = "distributor_master.csv"


def normalise_arn(arn: str | None) -> str | None:
    if not arn:
        return None
    digits = re.sub(r"\D", "", arn)
    return f"ARN-{digits}" if digits else None


def normalise_euin(euin: str | None) -> str | None:
    if not euin:
        return None
    m = re.search(r"E\s*-?\s*(\d{5,7})", euin.upper())
    return f"E{m.group(1)}" if m else None


@tool("distributor.validate")
def validate(arn: str | None, euin: str | None, amc: str | None, on_date: date) -> dict:
    """Validate ARN (status, validity at on_date, empanelment with amc) and EUIN (belongs to ARN, validity)."""
    arn_n, euin_n = normalise_arn(arn), normalise_euin(euin)
    out = {"arn": arn_n, "euin": euin_n, "arn_found": False, "arn_valid": False, "arn_problems": [],
           "euin_found": False, "euin_valid": False, "euin_problems": [], "rows": []}
    if not arn_n:
        out["arn_problems"].append("no ARN quoted")
        return out
    rows = query("SELECT * FROM distributor_master WHERE arn = ?", (arn_n,))
    out["rows"] = rows
    if not rows:
        out["arn_problems"].append("ARN not present in distributor master (AMFI data)")
        return out
    out["arn_found"] = True
    r0 = rows[0]
    out["distributor_name"] = r0["distributor_name"]
    out["arn_status"] = r0["arn_status"]
    out["arn_valid_till"] = r0["arn_valid_till"]
    if r0["arn_status"] != "ACTIVE":
        out["arn_problems"].append(f"ARN status {r0['arn_status']}")
    vt = parse_date(r0["arn_valid_till"])
    if vt is None or vt < on_date:
        out["arn_problems"].append(f"ARN validity ended {r0['arn_valid_till']} (request date {on_date.isoformat()})")
    emp_col = {"NMF": "empanelled_nmf", "TMF": "empanelled_tmf"}.get(amc or "")
    out["empanelled"] = r0.get(emp_col) if emp_col else None
    if emp_col and r0.get(emp_col) != "Y":
        out["arn_problems"].append(f"ARN not empanelled with {amc}")
    out["arn_valid"] = not out["arn_problems"]
    if euin_n:
        er = [r for r in rows if r["euin"] == euin_n]
        if not er:
            other = query("SELECT arn FROM distributor_master WHERE euin = ?", (euin_n,))
            out["euin_problems"].append(
                f"EUIN {euin_n} does not belong to {arn_n}" + (f" (belongs to {other[0]['arn']})" if other else " (not found)"))
        else:
            out["euin_found"] = True
            out["euin_holder_name"] = er[0]["euin_holder_name"]
            out["euin_valid_till"] = er[0]["euin_valid_till"]
            ev = parse_date(er[0]["euin_valid_till"])
            if ev is None or ev < on_date:
                out["euin_problems"].append(f"EUIN validity ended {er[0]['euin_valid_till']}")
        out["euin_valid"] = out["euin_found"] and not out["euin_problems"]
    else:
        out["euin_problems"].append("EUIN blank")
    return out
