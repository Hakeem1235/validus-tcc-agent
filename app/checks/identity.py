"""FOLIO_IDENTITY: the result of S3 resolution expressed as a check (SOP 9.4)."""
from __future__ import annotations

from app.case import Case
from app.checks.base import ev
from app.schemas import CheckResult


def run(case: Case) -> CheckResult:
    clause = case.sop("9.4")
    if case.identity_failure:
        return CheckResult(check_id="FOLIO_IDENTITY", result="FAIL", sop_clause=clause,
                           evidence=list(case.identity_evidence) or [ev("request", "folio", "could not be identified")],
                           reason_codes=[case.identity_failure], notes=case.identity_notes)
    evidence = list(case.identity_evidence)
    if case.folio:
        f = case.folio
        evidence.insert(0, ev("folio_master.csv", f"folio_no={f['folio_no']}",
                              f"{f['amc_code']} {f['holding_mode']} {f['tax_status']}; first holder {f['first_holder_name']} "
                              f"({f['first_holder_pan_masked']}); flag {f['folio_flag']}"))
    if case.txn:
        t = case.txn
        evidence.append(ev("transactions.csv", f"txn_id={t['txn_id']}",
                           f"{t['txn_type']} Rs {t['amount_inr']:,.0f} {t['payment_mode']} {t['txn_date']} status {t['status']}"
                           + (f" UTR {t['utr']}" if t.get('utr') else "")))
    if not case.folio and not case.first_holder_pan:
        return CheckResult(check_id="FOLIO_IDENTITY", result="UNABLE_TO_VERIFY", sop_clause=clause,
                           evidence=evidence or [ev("request", "investor", "no folio or PAN to identify the investor")])
    return CheckResult(check_id="FOLIO_IDENTITY", result="PASS", sop_clause=clause, evidence=evidence,
                       notes=case.identity_notes)
