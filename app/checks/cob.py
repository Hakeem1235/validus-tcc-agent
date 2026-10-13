"""COB_COOLING (SOP 6.4 cooling period, 6.5 high-risk contact change)."""
from __future__ import annotations

from datetime import date, timedelta

from app.case import Case
from app.checks.base import R, ev, na
from app.checks.bank_mandate import cob_in_request
from app.normalise import parse_date
from app.schemas import CheckResult
from app.tools import bank


def _cob_date(case: Case) -> tuple[date | None, str]:
    """Latest COB receipt date: register (cob_request_received_on) or a COB enclosed with this request."""
    best, src = None, ""
    for m in bank.accounts(case.folio["folio_no"]):
        d = parse_date(m.get("cob_request_received_on"))
        if d and d <= case.received_date and (best is None or d > best):
            best, src = d, f"bank_mandates.csv {m['ref']}"
    if cob_in_request(case):
        form_dates = [parse_date(a.doc_date) for a in case.attachments if "COB_FORM" in a.doc_types and a.doc_date]
        d = max([x for x in form_dates if x and x <= case.received_date], default=None) or case.received_date
        if best is None or d > best:
            best, src = d, "COB form enclosed with this request"
    return best, src


def run(case: Case) -> CheckResult:
    cfg = R()["cob"]
    cid = "COB_COOLING"
    clause = case.sop(cfg["clause_cooling"])
    if not case.is_redemption:
        return na(cid, "cooling period applies to redemption payouts only", clause)
    if not case.folio:
        return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=clause,
                           evidence=[ev("request", "folio", "folio not resolved")])
    cooling_days = cfg["cooling_days"].get(case.policy.sop_version, 0)
    red_date = case.received_date
    cob_d, src = _cob_date(case)
    if cob_d is None:
        return CheckResult(check_id=cid, result="PASS", sop_clause=clause,
                           evidence=[ev("bank_mandates.csv", f"folio_no={case.folio['folio_no']}", "no change-of-bank request on record")])
    gap = (red_date - cob_d).days
    in_cooling = 0 <= gap <= cooling_days if cooling_days else gap == 0
    cooling_end = cob_d + timedelta(days=cooling_days)
    evidence = [ev(src.split(" ")[0] if src.startswith("bank") else "request", src,
                   f"COB received {cob_d}; redemption received {red_date}; gap {gap} day(s); cooling period "
                   f"{cooling_days} day(s) under v{case.policy.sop_version}"
                   + (f" -> payout held until {cooling_end}" if in_cooling and cooling_days else ""))]
    reasons, data = [], {}
    if in_cooling and cooling_days:
        reasons.append("COB_COOLING")
        data["cooling_end"] = cooling_end.isoformat()
    # 6.5 high-risk: contact changed within 30 days before the COB and redemption during its cooling period
    changed = parse_date(case.folio.get("contact_last_changed_on"))
    if changed:
        delta = (cob_d - changed).days
        evidence.append(ev("folio_master.csv", f"folio_no={case.folio['folio_no']}",
                           f"registered contact last changed {changed} ({delta} day(s) before COB)"))
        if in_cooling and 0 <= delta <= cfg["contact_change_window_days"]:
            reasons.append("HIGH_RISK_CONTACT_COB")
            clause = case.sop(cfg["clause_high_risk"])
    elif case.extracted.contact_change_claimed:
        case.warnings.append("Email says contact details changed but folio master shows no change; registered details used.")
    if not reasons:
        return CheckResult(check_id=cid, result="PASS", sop_clause=clause, evidence=evidence)
    if "HIGH_RISK_CONTACT_COB" not in reasons and not cooling_days:
        return CheckResult(check_id=cid, result="PASS", sop_clause=clause, evidence=evidence)
    return CheckResult(check_id=cid, result="FAIL", sop_clause=clause, evidence=evidence, reason_codes=reasons, data=data)
