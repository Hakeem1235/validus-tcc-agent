"""DISTRIBUTOR_CODE (SOP 7.1-7.4)."""
from __future__ import annotations

from app.case import Case
from app.checks.base import R, ev, na
from app.schemas import CheckResult
from app.tools import distributor


def run(case: Case) -> CheckResult:
    cfg = R()["distributor"]
    cid = "DISTRIBUTOR_CODE"
    clause = case.sop(cfg["clause_validate"])
    if not case.is_purchase:
        return na(cid, "distributor codes apply to purchases and SIPs", clause)
    t, x = case.txn or {}, case.extracted
    arn = t.get("arn") or x.arn
    euin = t.get("euin") or x.euin
    plan = case.plan()
    if plan is None and arn:
        plan = "REGULAR"
    if plan != "REGULAR":
        return na(cid, f"{(plan or 'unspecified').title()} plan: no distributor code to validate", clause)
    src = ("transactions.csv", f"txn_id={t['txn_id']}") if t else ("email", "body")
    evidence = [ev(src[0], src[1], f"Regular plan; ARN {arn or 'blank'}; EUIN {euin or 'blank'}")]
    if case.request_type == "SIP_INSTALMENT" and arn:
        evidence.append(ev("policy", case.sop(cfg["clause_sip_tenure"]),
                           "instalment of an SIP registered under an ARN stays in the Regular plan for its tenure"))
        return CheckResult(check_id=cid, result="PASS", sop_clause=case.sop(cfg["clause_sip_tenure"]), evidence=evidence)

    v = distributor.validate(arn, euin, case.amc, case.received_date)
    if v["arn_found"]:
        evidence.append(ev("distributor_master.csv", f"arn={v['arn']}",
                           f"{v.get('distributor_name')} status {v.get('arn_status')} valid till {v.get('arn_valid_till')}; "
                           f"empanelled {case.amc}: {v.get('empanelled')}"))
    if not v["arn_valid"]:
        evidence.append(ev("distributor_master.csv", f"arn={v['arn'] or 'blank'}", "; ".join(v["arn_problems"])))
        reason = cfg["invalid_arn_reason"].get(case.policy.sop_version)
        if reason:
            evidence.append(ev("policy", case.sop(cfg["clause_invalid"]),
                               "invalid ARN: processed in the Direct plan of the same scheme/option; no commission"))
            return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_invalid"]), evidence=evidence,
                               reason_codes=[reason], data={"modification": "switch to Direct plan", "problems": v["arn_problems"]})
        case.warnings.append(f"Invalid ARN under SOP v{case.policy.sop_version} 7.2: processed in Regular; reprocess "
                             f"to Direct if a valid ARN is not received within 30 days.")
        return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_invalid"]), evidence=evidence,
                           data={"outcome": "PROCEED"})
    # ARN valid -> EUIN
    if v["euin_valid"]:
        evidence.append(ev("distributor_master.csv", f"euin={v['euin']}",
                           f"EUIN belongs to {v['arn']} ({v.get('euin_holder_name')}), valid till {v.get('euin_valid_till')}"))
        return CheckResult(check_id=cid, result="PASS", sop_clause=clause, evidence=evidence)
    evidence.append(ev("distributor_master.csv", f"euin={v['euin'] or 'blank'}", "; ".join(v["euin_problems"])))
    if x.execution_only_declaration or case.has_doc("EXECUTION_ONLY_DECLARATION"):
        evidence.append(ev("email", "execution-only", "investor's signed execution-only declaration accompanies the transaction"))
        return CheckResult(check_id=cid, result="PASS", sop_clause=case.sop(cfg["clause_euin"]), evidence=evidence)
    return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_euin"]), evidence=evidence,
                       reason_codes=["EUIN_MISSING"], data={"outcome": "PROCEED"})
