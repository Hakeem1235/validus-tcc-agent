"""BANK_MANDATE (SOP 6.1-6.3; TMF-ADD-02 A2): payout account and change-of-bank proof."""
from __future__ import annotations

from app.case import Case
from app.checks.base import R, ev, na
from app.normalise import names_match
from app.schemas import CheckResult
from app.tools import bank
from app.tools import folio as folio_tool


def cob_in_request(case: Case) -> bool:
    return case.request_type == "CHANGE_OF_BANK" or case.has_doc("COB_FORM") or bool(case.extracted.cob_mentioned and (
        case.extracted.new_bank_account_last4 or case.has_doc("CANCELLED_CHEQUE")))


def run(case: Case) -> CheckResult:
    cfg = R()["bank"]
    cid = "BANK_MANDATE"
    if case.request_type not in ("REDEMPTION", "CHANGE_OF_BANK"):
        return na(cid, "no payout or bank change on this request type", case.sop(cfg["clause_payout"]))
    if not case.folio:
        return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=case.sop(cfg["clause_payout"]),
                           evidence=[ev("request", "folio", "folio not resolved")])
    f = case.folio
    rows = bank.accounts(f["folio_no"])
    evidence, reasons, missing, notes = [], [], [], []
    for m in rows:
        evidence.append(ev("bank_mandates.csv", m["ref"],
                           f"{m['bank_name']} {m['status']} default={m['is_default']} holders '{m['account_holders']}'"
                           + (f" COB received {m['cob_request_received_on']}" if m.get("cob_request_received_on") else "")))
    result = "PASS"
    clause = case.sop(cfg["clause_payout"])

    if case.is_redemption:
        requested = case.extracted.payout_account_last4 or case.extracted.new_bank_account_last4
        payout = None
        if requested:
            req_rows = [m for m in rows if m["account_last4"] == requested]
            if req_rows and req_rows[0]["status"] == "VALIDATED":
                payout = req_rows[0]
            else:
                state = req_rows[0]["status"] if req_rows else "not registered"
                evidence.append(ev("bank_mandates.csv", f"{f['folio_no']}|...{requested}",
                                   f"requested payout account ending {requested} is {state}: disregarded, never paid to "
                                   f"a non-VALIDATED account (6.2/6.4); default account used"))
                notes.append(f"requested account ...{requested} disregarded ({state})")
        if payout is None:
            payout = bank.default_account(rows)
        if payout is None or payout["status"] != "VALIDATED":
            result = "UNABLE_TO_VERIFY"
            evidence.append(ev("bank_mandates.csv", f"folio_no={f['folio_no']}", "no VALIDATED default payout account"))
            reasons.append("BANK_PROOF_REQUIRED")
        else:
            evidence.append(ev("bank_mandates.csv", payout["ref"], f"payout account: {payout['account_no_masked']} VALIDATED"))
            if folio_tool.is_minor_folio(f) and not any(names_match(f["first_holder_name"], h) for h in payout["holders"]):
                result = "FAIL"
                clause = case.sop("5.4")
                reasons.append("BANK_PROOF_REQUIRED")
                evidence.append(ev("bank_mandates.csv", payout["ref"],
                                   "minor folio: proceeds only to the minor's verified account; minor not a holder"))

    if cob_in_request(case):
        add = next((cfg["addendum_overrides"][d] for d in case.policy.addendum_docs if d in cfg.get("addendum_overrides", {})), {})
        in_person_ok = add.get("in_person_accepted", True)
        proof_clause = (f"{case.policy.addenda[0]['doc']} {add['clause_cob_proof']}" if add
                        else case.sop(cfg["clause_cob_proof"]))
        new_ok = any(case.has_doc(d) for d in cfg["new_account_proof"])
        existing_ok = any(case.has_doc(d) for d in cfg["existing_account_proof"])
        in_person = bool(case.extracted.in_person_verification)
        evidence.append(ev("request", "COB proofs",
                           f"new-account proof {'enclosed' if new_ok else 'missing'}; existing-account proof "
                           f"{'enclosed' if existing_ok else 'missing'}; in-person verification "
                           f"{'recorded' if in_person else 'not recorded'}"
                           + ("" if in_person_ok else " (not accepted for this AMC)")))
        if not new_ok:
            missing.append("NEW_BANK_PROOF")
        if not (existing_ok or (in_person and in_person_ok)):
            missing.append("EXISTING_BANK_PROOF")
        if missing:
            result = "FAIL"
            clause = proof_clause
            reasons.append("BANK_PROOF_REQUIRED")
    reasons = list(dict.fromkeys(reasons))
    return CheckResult(check_id=cid, result=result, sop_clause=clause, evidence=evidence, reason_codes=reasons,
                       missing_documents=missing, notes=notes)
