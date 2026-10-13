"""KYC_STATUS (SOP 4.1-4.6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.case import Case
from app.checks.base import R, ev, na
from app.schemas import CheckResult
from app.tools import folio as folio_tool
from app.tools import kra

IST = timezone(timedelta(hours=5, minutes=30))
ACTION_RANK = {"ACCEPT": 0, "PEND_NEW_AMC": 2, "PEND_UTV": 2, "REFER": 3, "NOT_ACCEPT": 4}


def _column(case: Case, pan: str) -> str:
    if case.request_type == "NEW_FOLIO_PURCHASE":
        target = case.amc
        held = [f for f in folio_tool.by_pan(pan, role="any") if f["amc_code"] == target]
        return "new_folio_amc_held" if held else "new_folio_new_amc"
    if case.request_type in ("REDEMPTION", "CHANGE_OF_BANK"):
        return "redemption"
    return "additional"


def _assess(case: Case, pan: str, label: str) -> tuple[str, str | None, list, str]:
    """Return (action, status, evidence, note) for one PAN."""
    cfg = R()["kyc"]
    row = kra.lookup(pan)
    if row is None:
        return "PEND_UTV", None, [ev("kra_kyc_snapshot.csv", f"pan_masked={pan}", "no KRA record for PAN")], \
            f"{label}: no KRA record"
    flags = row.get("data_flags") or ""
    desc = (f"{label} {pan}: code {row['kra_status_code']} ({row['kra_name']}) -> {row['status'] or 'unknown'}; "
            f"text '{row['kra_status'] or ''}'; checked {row['last_checked_at']}")
    evidence = [ev("kra_kyc_snapshot.csv", row["ref"], desc)]
    if row["status"] is None or "unknown_code" in flags:
        return "PEND_UTV", None, evidence, f"{label}: KRA code not recognised"
    if row["code_text_conflict"] or "agency_mismatch" in flags:
        return "PEND_UTV", row["status"], evidence, f"{label}: KRA code and status text/agency disagree"
    checked = None
    try:
        checked = datetime.strptime(row["last_checked_at"], "%Y-%m-%d %H:%M").replace(tzinfo=IST)
    except (TypeError, ValueError):
        pass
    if checked is None:
        return "PEND_UTV", row["status"], evidence, f"{label}: lookup time unreadable"
    age_h = (case.received_at - checked).total_seconds() / 3600
    if age_h > cfg["stale_after_hours"]:
        return "PEND_UTV", row["status"], evidence, \
            f"{label}: latest KRA lookup is {age_h:.0f}h older than the request (>{cfg['stale_after_hours']}h)"
    action = cfg["matrix"][row["status"]][_column(case, pan)]
    return action, row["status"], evidence, f"{label}: {row['status']} -> {action}"


def run(case: Case) -> CheckResult:
    cfg = R()["kyc"]
    if case.request_type == "OTHER":
        return na("KYC_STATUS", "not a financial transaction request", case.sop("4.1"))
    targets: list[tuple[str, str]] = []
    f = case.folio
    if f:
        if folio_tool.is_minor_folio(f):
            targets.append((f["first_holder_pan_masked"], "minor"))
        else:
            targets.append((f["first_holder_pan_masked"], "first holder"))
            if case.request_type == "NEW_FOLIO_PURCHASE" and f.get("second_holder_pan_masked"):
                targets.append((f["second_holder_pan_masked"], "second holder"))
    elif case.first_holder_pan:
        targets.append((case.first_holder_pan, "investor"))
    for p in case.investor_pans:
        if p and p not in [t[0] for t in targets]:
            targets.append((p, "holder"))
    if not targets:
        return CheckResult(check_id="KYC_STATUS", result="UNABLE_TO_VERIFY", sop_clause=case.sop("4.5"),
                           reason_codes=["KYC_UNABLE_TO_VERIFY"],
                           evidence=[ev("request", "pan", "no PAN available to look up")])

    worst, worst_status, evidence, notes = "ACCEPT", None, [], []
    for pan, label in targets:
        action, status, e, note = _assess(case, pan, label)
        evidence += e
        notes.append(note)
        if ACTION_RANK[action] > ACTION_RANK[worst]:
            worst, worst_status = action, status

    clause = case.sop(cfg["clauses"][worst])
    if worst == "ACCEPT":
        return CheckResult(check_id="KYC_STATUS", result="PASS", sop_clause=clause, evidence=evidence, notes=notes)
    if worst == "PEND_UTV":
        return CheckResult(check_id="KYC_STATUS", result="UNABLE_TO_VERIFY", sop_clause=clause, evidence=evidence,
                           reason_codes=["KYC_UNABLE_TO_VERIFY"], notes=notes)
    if worst == "PEND_NEW_AMC":
        return CheckResult(check_id="KYC_STATUS", result="FAIL", sop_clause=clause, evidence=evidence,
                           reason_codes=["KYC_REGISTERED_NEW_AMC"], notes=notes,
                           data={"outcome": "PEND"})
    reason = cfg["status_reason"][worst_status]
    return CheckResult(check_id="KYC_STATUS", result="FAIL", sop_clause=clause, evidence=evidence,
                       reason_codes=[reason], notes=notes,
                       data={"outcome": cfg["action_outcome"][worst]})
