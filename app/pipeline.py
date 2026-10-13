"""Orchestrator: S1 intake -> S2 understand -> S3 resolve -> S4 policy -> S5 checks -> S6 decide -> S7 reply -> S8 trace."""
from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta, timezone

from app import llm
from app.case import Case
from app.checks import REGISTRY
from app.normalise import names_match
from app.s1_intake import intake
from app.s2_extract import classify, heuristic_extract, llm_extract, merge, regex_pass
from app.s3_resolve import resolve
from app.s6_decide import Decision, decide
from app.s7_reply import _addressee, draft
from app.schemas import CHECK_ORDER, CheckResult, DocumentRef, Evidence, TCCRequest
from app.tools import bank
from app.tools import policy as policy_tool
from app.trace import TraceCollector

log = logging.getLogger("tcc")
IST = timezone(timedelta(hours=5, minutes=30))


def parse_received(s: str) -> datetime:
    try:
        d = datetime.fromisoformat((s or "").replace("Z", "+00:00"))
    except ValueError:
        d = None
    if d is None:
        raise ValueError(f"received_at not ISO-8601: {s!r}")
    return d if d.tzinfo else d.replace(tzinfo=IST)


def _enrich_after_resolve(case: Case) -> None:
    """Facts that need the resolved folio: who 'self' is, which bank proof is for which account."""
    x, f = case.extracted, case.folio
    if not f:
        return
    sender_name, _ = _addressee(case.sender)
    # "from my account" by a sender who is not the first holder (e.g. joint second holder) is not the investor's account
    if x.payer_relation_to_investor in ("self", None) and sender_name and sender_name != "Sir/Madam":
        first = [f["first_holder_name"]]
        if names_match(sender_name, f.get("second_holder_name")) and not any(names_match(sender_name, n) for n in first):
            if x.payer_relation_to_investor == "self" or (case.txn and names_match(sender_name, case.txn.get("remitter_name"))):
                x.payer_relation_to_investor = "second_holder"
                case.warnings.append("Sender is the second holder and says the payment came from their own account.")
    # bank proofs: a proof matching the folio's existing VALIDATED account is existing-account proof (6.3)
    rows = bank.accounts(f["folio_no"])
    validated = {m["account_last4"] for m in rows if m["status"] == "VALIDATED"}
    for a in case.attachments:
        if a.account_last4 and a.account_last4 in validated and set(a.doc_types) & {"CANCELLED_CHEQUE", "BANK_STATEMENT", "PASSBOOK", "BANK_LETTER"}:
            if not case.has_doc("EXISTING_BANK_PROOF"):
                x.documents_enclosed.append(DocumentRef(type="EXISTING_BANK_PROOF", present_as_attachment=True,
                                                        source=a.file_name, detail=f"account ending {a.account_last4}"))
        if "COB_FORM" in a.doc_types and a.flags.get("existing_proof_missing"):
            case.warnings.append(f"{a.file_name}: existing-account proof stated as not available.")


def _fallback_checks(done: dict[str, CheckResult], why: str) -> list[CheckResult]:
    out = []
    for cid in CHECK_ORDER:
        out.append(done.get(cid) or CheckResult(check_id=cid, result="UNABLE_TO_VERIFY",
                                                evidence=[Evidence(source="system", ref="not_run", value=why)]))
    return out


def process(raw: dict) -> dict:
    with TraceCollector() as trace:
        return _process(raw, trace)


def _process(raw: dict, trace: TraceCollector) -> dict:
    req = TCCRequest.model_validate(raw)
    warnings: list[str] = []
    stage = "S1"
    try:
        received = parse_received(req.received_at)
    except ValueError as e:
        warnings.append(str(e) + "; using current time")
        received = datetime.now(IST)

    # S1
    atts = intake(req.attachments)
    for a in atts:
        if a.error:
            warnings.append(f"{a.file_name}: {a.error}")
    # S2
    stage = "S2"
    rx = regex_pass(req.subject, req.body)
    heur = heuristic_extract(req.subject, req.body, req.from_, rx, atts)
    lx, extraction_method = None, "rules"
    if llm.available():
        try:
            lx = llm_extract(req.subject, req.body, req.from_, atts)
            extraction_method = "llm+rules"
        except ValueError as e:  # invalid twice -> safe fallback response
            return safe_response(raw, trace, f"extraction invalid twice: {e}", warnings)
        except llm.LLMUnavailable as e:
            warnings.append(f"LLM extraction unavailable ({str(e)[:120]}); rule-based extraction used.")
    text = req.subject + "\n" + req.body + "\n" + "\n".join(a.text for a in atts)
    x = merge(rx, heur, lx, text, warnings)
    case = Case(request_id=req.request_id, received_at=received, sender=req.from_, subject=req.subject, body=req.body,
                extracted=x, attachments=atts, request_type=x.request_type_hint or "OTHER", warnings=warnings)
    # S3
    stage = "S3"
    resolve(case, rx["folio_tokens"] + ([x.folio_raw] if x.folio_raw else []) + x.folio_candidates, rx["invalid_folio_tokens"])
    if not case.referenced_folios:
        case.request_type, basis = classify(x, case.txn, case.folio is not None)
    else:
        basis = "existing folio of another AMC quoted; request is for a new folio"
    _enrich_after_resolve(case)
    # S4
    stage = "S4"
    case.policy = policy_tool.select(case.received_date, case.amc or x.target_amc)
    warnings.extend(w for w in case.policy.warnings if w not in warnings)
    # S5
    stage = "S5"
    done: dict[str, CheckResult] = {}
    if case.identity_failure:
        done["FOLIO_IDENTITY"] = REGISTRY["FOLIO_IDENTITY"](case)
        checks = _fallback_checks(done, "not run: folio/investor not identified (INVALID_REQUEST)")
    else:
        for cid in CHECK_ORDER:
            try:
                done[cid] = REGISTRY[cid](case)
            except Exception as e:  # a failing check never passes
                log.exception("check %s failed", cid)
                done[cid] = CheckResult(check_id=cid, result="UNABLE_TO_VERIFY",
                                        evidence=[Evidence(source="system", ref="error", value=f"{type(e).__name__}: {e}")])
                warnings.append(f"{cid} could not run: {type(e).__name__}")
        checks = [done[c] for c in CHECK_ORDER]
    # S6
    stage = "S6"
    decision = decide(checks)
    # S7
    stage = "S7"
    reply, reply_meta = draft(case, decision, checks)
    # S8
    stage = "S8"
    related = policy_tool.search(" ".join(decision.reason_codes) or case.request_type,
                                 [("TCC-SOP", case.policy.sop_version)] + [(a["doc"], a["version"]) for a in case.policy.addenda], k=3)
    resp = {
        "request_id": req.request_id,
        "request_type": case.request_type,
        "resolved": {
            "folio_no": case.folio["folio_no"] if case.folio else None,
            "amc_code": case.amc if case.amc in ("NMF", "TMF") else None,
            "first_holder_pan_masked": case.first_holder_pan,
            "txn_id": case.txn["txn_id"] if case.txn else None,
        },
        "outcome": decision.outcome,
        "reason_codes": decision.reason_codes,
        "checks": [c.to_contract().model_dump() for c in checks],
        "human_approval_required": decision.human_approval_required,
        "approver_role": decision.approver_role,
        "draft_reply": reply.model_dump(),
        "trace": trace.to_contract(),
        # extra fields (documented in README)
        "extracted": x.model_dump(exclude_none=True),
        "classification_basis": basis,
        "extraction_method": extraction_method,
        "policy_selection": case.policy.as_dict(),
        "decision_rationale": decision.rationale,
        "missing_documents": sorted({m for c in checks for m in c.missing_documents}),
        "referenced_folios": case.referenced_folios,
        "attachments": [{"file_name": a.file_name, "method": a.method, "doc_types": a.doc_types,
                         "account_last4": a.account_last4, "account_holders": a.account_holders, "error": a.error}
                        for a in atts],
        "reply_method": reply_meta,
        "related_clauses": [{k: h[k] for k in ("doc", "version", "clause_id", "score")} for h in related],
        "warnings": list(dict.fromkeys(case.warnings)),
    }
    return resp


def safe_response(raw: dict, trace: TraceCollector | None, error: str, warnings: list[str] | None = None) -> dict:
    """Contract-valid fallback: PEND, all checks UNABLE_TO_VERIFY, checker approval, plus `error`."""
    rid = str((raw or {}).get("request_id", "")) if isinstance(raw, dict) else ""
    sender = str((raw or {}).get("from", "")) if isinstance(raw, dict) else ""
    subject = str((raw or {}).get("subject", "")) if isinstance(raw, dict) else ""
    name, email = _addressee(sender)
    body = (f"Dear {name},\n\nThank you for your email. Your request has been received and is being reviewed by our "
            f"team. We will write to you shortly with an update or with any document we need.\n\nRegards,\nTCC Desk, Validus")
    tr = trace.to_contract() if trace else {"model_calls": [], "tools_called": [], "documents_used": [], "cost_usd": 0.0}
    return {
        "request_id": rid,
        "request_type": "OTHER",
        "resolved": {"folio_no": None, "amc_code": None, "first_holder_pan_masked": None, "txn_id": None},
        "outcome": "PEND",
        "reason_codes": [],
        "checks": [{"check_id": c, "result": "UNABLE_TO_VERIFY", "sop_clause": None,
                    "evidence": [{"source": "system", "ref": "not_run", "value": "pipeline error; check not run"}]}
                   for c in CHECK_ORDER],
        "human_approval_required": True,
        "approver_role": "CHECKER",
        "draft_reply": {"to": email, "subject": f"Re: {subject}" if subject else "Your request", "body": body},
        "trace": tr,
        "error": error,
        "warnings": warnings or [],
    }


def process_safely(raw: dict) -> dict:
    trace = TraceCollector()
    try:
        with trace:
            return _process(raw, trace)
    except Exception as e:  # never 500
        log.error("pipeline failure: %s\n%s", e, traceback.format_exc())
        return safe_response(raw, trace, f"{type(e).__name__}: {e}")
