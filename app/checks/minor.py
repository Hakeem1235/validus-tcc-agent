"""MINOR_RULES (SOP 5.5 minor attaining majority; guardian data present)."""
from __future__ import annotations

from datetime import date

from app.case import Case
from app.checks.base import R, ev, na
from app.normalise import parse_date
from app.schemas import CheckResult
from app.tools import folio as folio_tool


def majority_date(dob: date, age: int) -> date:
    try:
        return dob.replace(year=dob.year + age)
    except ValueError:  # 29 Feb
        return date(dob.year + age, 3, 1)


def run(case: Case) -> CheckResult:
    cfg = R()["minor"]
    cid = "MINOR_RULES"
    clause = case.sop(cfg["clause"])
    if not case.folio or not folio_tool.is_minor_folio(case.folio):
        return na(cid, "not a minor folio", clause)
    if case.request_type == "OTHER":
        return na(cid, "not a transaction request", clause)
    f = case.folio
    dob = parse_date(f.get("minor_dob"))
    ref = f"folio_no={f['folio_no']}"
    if dob is None or not f.get("guardian_name"):
        return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=clause, reason_codes=["MINOR_ATTAINED_MAJORITY"],
                           evidence=[ev("folio_master.csv", ref, "minor folio without minor DOB / guardian on record")])
    maj = majority_date(dob, cfg["majority_age"])
    on = case.received_date
    txn_d = parse_date((case.txn or {}).get("txn_date"))
    if case.request_type == "SIP_INSTALMENT" and txn_d:
        on = txn_d  # instalments falling due after the majority date
    desc = (f"minor {f['first_holder_name']} DOB {dob}; guardian {f['guardian_name']} ({f.get('guardian_relation')}); "
            f"majority on {maj}; request/instalment date {on}")
    if on >= maj:
        return CheckResult(check_id=cid, result="FAIL", sop_clause=clause, evidence=[ev("folio_master.csv", ref, desc)],
                           reason_codes=["MINOR_ATTAINED_MAJORITY"], missing_documents=["CHANGE_OF_STATUS_FORM"])
    return CheckResult(check_id=cid, result="PASS", sop_clause=clause, evidence=[ev("folio_master.csv", ref, desc)])
