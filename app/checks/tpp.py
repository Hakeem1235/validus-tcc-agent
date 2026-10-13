"""THIRD_PARTY_PAYMENT (SOP 5.1-5.7).

The payer is identified by the paying account (bank feed / gateway / mandate) matched against the
bank-mandate register, then by holder lists on registered accounts or on enclosed proof (5.6).
Names are only ever used to corroborate an account-level match, or to show that a payer is
someone other than the eligible holders.
"""
from __future__ import annotations

import re

from app.case import Case
from app.checks.base import R, ev, na
from app.normalise import last4, names_match
from app.schemas import AttachmentInfo, CheckResult
from app.tools import bank, kra
from app.tools import folio as folio_tool

SELF_RELATIONS = {"self", "own", "investor", "first_holder", "joint_with_investor", "joint"}
PARENT_RELATIONS = {"parent", "father", "mother", "guardian", "legal_guardian"}
RELATIVE_RELATIONS = {"grandparent", "grandfather", "grandmother", "relative", "other_relative", "uncle", "aunt",
                      "spouse", "husband", "wife", "sibling", "brother", "sister", "son", "daughter", "second_holder",
                      "friend", "other"}
COMPANY_RE = re.compile(r"\b(PVT|PRIVATE|LTD|LIMITED|LLP|INC|CORP|CORPORATION|COMPANY|CO|BANK|TRUST)\b", re.I)


def _norm_rel(rel: str | None) -> str | None:
    if not rel:
        return None
    r = rel.strip().lower().replace(" ", "_").replace("-", "_")
    for k in ("grand",):
        if k in r:
            return "grandparent"
    if r in ("father", "mother", "parent", "dad", "mom", "papa", "mummy"):
        return "parent"
    return r


def _eligible(case: Case) -> tuple[list[tuple[str, str]], bool]:
    """Names of people whose account is not third-party for this folio: [(name, role)], is_minor."""
    f = case.folio
    out: list[tuple[str, str]] = []
    if not f:
        return out, False
    minor = folio_tool.is_minor_folio(f)
    k = kra.lookup(f["first_holder_pan_masked"])
    out.append((f["first_holder_name"], "minor" if minor else "first holder"))
    if k and k.get("name_as_per_kra"):
        out.append((k["name_as_per_kra"], "minor" if minor else "first holder"))
    if minor:
        allowed = R()["tpp"]["minor_allowed_payers"].get(case.policy.sop_version, ["minor", "guardian"])
        if f.get("guardian_name") and ("guardian" in allowed or "parent" in allowed):
            role = "parent" if f.get("guardian_relation") in ("FATHER", "MOTHER") else "legal guardian"
            out.append((f["guardian_name"], role))
            gk = kra.lookup(f.get("guardian_pan_masked"))
            if gk and gk.get("name_as_per_kra"):
                out.append((gk["name_as_per_kra"], role))
    return out, minor


def _match_any(eligible: list[tuple[str, str]], holders: list[str]) -> tuple[str, str] | None:
    for name, role in eligible:
        for h in holders:
            if names_match(name, h):
                return h, role
    return None


def _proof_docs(case: Case, acct: str | None, utr: str | None) -> list[AttachmentInfo]:
    types = set(R()["tpp"]["proof_documents"])
    out = []
    for a in case.attachments:
        if not types.intersection(a.doc_types):
            continue
        if acct and a.account_last4 and a.account_last4 != acct:
            continue
        if not a.account_last4 and not (utr and a.utr and a.utr.upper() == utr.upper()):
            continue
        out.append(a)
    return out


def _category(case: Case, payer_name: str | None, rel: str | None) -> str:
    x = case.extracted
    if x.third_party_category and x.third_party_category != "other":
        return x.third_party_category
    if rel in ("employer",) or x.sender_role == "employer":
        return "employer"
    if rel in ("custodian",):
        return "custodian"
    if payer_name and COMPANY_RE.search(payer_name) and case.has_doc("EMPLOYER_DECLARATION"):
        return "employer"
    if rel in PARENT_RELATIONS or rel in RELATIVE_RELATIONS or rel == "grandparent":
        return "relative"
    return "other"


def run(case: Case) -> CheckResult:
    cfg = R()["tpp"]
    cid = "THIRD_PARTY_PAYMENT"
    if not case.is_purchase:
        return na(cid, "no pay-in on this request type", case.sop(cfg["clause_definition"]))
    t, x = case.txn or {}, case.extracted
    mode = (case.payment_mode() or "").upper()
    acct = last4(t.get("remitter_account_masked")) or x.remitter_account_last4
    payer_name = t.get("remitter_name") or x.remitter_name
    utr = t.get("utr") or x.utr
    if not t and not acct and not mode and x.amount_inr is None:
        return na(cid, "no payment received yet", case.sop(cfg["clause_definition"]))
    if mode == "CASH" or x.is_cash:
        return CheckResult(check_id=cid, result="NOT_APPLICABLE", sop_clause=case.sop(cfg["clause_proof"]),
                           evidence=[ev("transactions.csv" if t else "email", f"txn_id={t.get('txn_id')}" if t else "body",
                                        "cash payment: not a means of verifying the payer; cash limit checked under 8.5")])
    if not case.folio:
        return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=case.sop(cfg["clause_definition"]),
                           reason_codes=["BANK_PROOF_REQUIRED"],
                           evidence=[ev("request", "folio", "no folio to compare the paying account against")])

    eligible, minor = _eligible(case)
    rel = _norm_rel(x.payer_relation_to_investor)
    def_clause = case.sop(cfg["clause_minor"] if minor else cfg["clause_definition"])
    evidence = []
    if t:
        evidence.append(ev("transactions.csv", f"txn_id={t['txn_id']}",
                           f"{t['payment_mode']} from {t.get('remitter_account_masked') or '-'} "
                           f"remitter '{t.get('remitter_name') or '-'}'" + (f" UTR {t['utr']}" if t.get('utr') else "")))
    elif acct or payer_name:
        evidence.append(ev("email", "body", f"{mode or 'payment'} from account ending {acct or '?'} payer '{payer_name or '?'}'"))

    if not acct:
        if mode in ("NACH", "OTM"):
            mand = [m for m in bank.accounts(case.folio["folio_no"]) if m["status"] == "VALIDATED"]
            if mand:
                evidence.append(ev("bank_mandates.csv", mand[0]["ref"], "registered NACH/OTM mandate account"))
                return CheckResult(check_id=cid, result="PASS", sop_clause=case.sop(cfg["clause_proof"]), evidence=evidence)
        return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=case.sop(cfg["clause_proof"]),
                           reason_codes=["BANK_PROOF_REQUIRED"], evidence=evidence + [
                               ev("system", "paying_account", "paying account not identified in bank feed or request")],
                           missing_documents=["BANK_STATEMENT"])

    # 1. registered on this folio
    rows = bank.find_by_account(acct, case.folio["folio_no"])
    for m in rows:
        evidence.append(ev("bank_mandates.csv", m["ref"],
                           f"{m['status']} holders '{m['account_holders']}' default={m['is_default']}"))
        if m["status"] == "VALIDATED":
            hit = _match_any(eligible, m["holders"])
            if hit:
                evidence.append(ev("bank_mandates.csv", m["ref"], f"{hit[1]} '{hit[0]}' is a holder of the paying account"))
                return CheckResult(check_id=cid, result="PASS", sop_clause=def_clause, evidence=evidence)
    if not rows:
        evidence.append(ev("bank_mandates.csv", f"folio_no={case.folio['folio_no']}",
                           f"account ending {acct} is not registered on the folio"))

    # 2. registered & validated on another folio of the same investor (same first-holder / guardian PAN)
    pans = {case.folio.get("first_holder_pan_masked"), case.folio.get("guardian_pan_masked")} - {None, ""}
    for m in bank.find_by_account(acct):
        if m["folio_no"] == case.folio["folio_no"] or m["status"] != "VALIDATED":
            continue
        other = folio_tool.get(m["folio_no"])
        if other and (pans & {other.get("first_holder_pan_masked"), other.get("guardian_pan_masked")}):
            hit = _match_any(eligible, m["holders"])
            if hit:
                evidence.append(ev("bank_mandates.csv", m["ref"],
                                   f"same account registered and VALIDATED on the investor's folio {m['folio_no']}; holder '{hit[0]}'"))
                return CheckResult(check_id=cid, result="PASS", sop_clause=def_clause, evidence=evidence)

    # 3. unregistered account: who holds it?
    proofs = _proof_docs(case, acct, utr)
    holders_from_proof = [h for p in proofs for h in p.account_holders]
    for p in proofs:
        evidence.append(ev(p.file_name, "/".join(p.doc_types),
                           f"account ending {p.account_last4 or '?'} holder(s) {p.account_holders or '?'}"
                           + (f"; debit UTR {p.utr}" if p.utr else "") + (f"; Rs {p.amount_inr:,.0f}" if p.amount_inr else "")))
    if holders_from_proof:
        hit = _match_any(eligible, holders_from_proof)
        if hit:
            evidence.append(ev(proofs[0].file_name, "5.6 proof", f"{hit[1]} '{hit[0]}' holds the paying account"))
            return CheckResult(check_id=cid, result="PASS", sop_clause=case.sop(cfg["clause_proof"]), evidence=evidence,
                               notes=["own account not registered on folio; 5.6 proof enclosed"])
        third_party_name = holders_from_proof[0]
    else:
        name_hit = _match_any(eligible, [payer_name]) if payer_name else None
        if name_hit or rel in SELF_RELATIONS or (minor and rel in PARENT_RELATIONS):
            who = name_hit[1] if name_hit else ("parent/guardian" if rel in PARENT_RELATIONS else "investor")
            evidence.append(ev("bank_mandates.csv", f"folio_no={case.folio['folio_no']}",
                               f"payer appears to be the {who} but the account is unregistered and no statement/"
                               f"transfer instruction showing the debit is enclosed"))
            return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_proof"]), evidence=evidence,
                               reason_codes=["BANK_PROOF_REQUIRED"], missing_documents=["BANK_STATEMENT"])
        if not payer_name and rel is None:
            return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=case.sop(cfg["clause_proof"]),
                               reason_codes=["BANK_PROOF_REQUIRED"], evidence=evidence, missing_documents=["BANK_STATEMENT"])
        third_party_name = payer_name

    # 4. third-party payment: exception?
    category = _category(case, third_party_name, rel)
    version = case.policy.sop_version
    exceptions = cfg["exceptions"].get(version, {})
    amount = case.amount() or 0
    evidence.append(ev("request", "payer", f"payer '{third_party_name or 'unknown'}' relation '{rel or 'unstated'}' "
                                           f"is not an eligible holder -> third-party payment (category: {category})"))
    allowed = cfg["minor_allowed_payers"].get(version, [])
    if minor and rel in PARENT_RELATIONS and "parent" in allowed:
        evidence.append(ev("folio_master.csv", f"folio_no={case.folio['folio_no']}",
                           f"payer stated as parent but is not the recorded guardian ({case.folio.get('guardian_name')}); "
                           f"relationship and account holding cannot be verified from records"))
        return CheckResult(check_id=cid, result="UNABLE_TO_VERIFY", sop_clause=case.sop(cfg["clause_minor"]),
                           evidence=evidence, reason_codes=["BANK_PROOF_REQUIRED"], missing_documents=["BANK_STATEMENT"])
    if minor and category == "relative":
        if "minor_related" in exceptions:
            cap = cfg["minor_related_cap_inr"].get(version)
            if cap is not None and amount > cap:
                evidence.append(ev("policy", case.sop("5.4"), f"related-person payment Rs {amount:,.0f} exceeds Rs {cap:,.0f}"))
                return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop("5.4"), evidence=evidence,
                                   reason_codes=["TPP_NO_EXCEPTION"])
            category = "minor_related"
        else:
            evidence.append(ev("policy", case.sop(cfg["clause_minor"]),
                               "minor folio: only minor / parent / legal guardian accounts allowed; any other relative "
                               "including a grandparent is third-party and not covered by 5.3"))
            return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_minor"]), evidence=evidence,
                               reason_codes=["TPP_NO_EXCEPTION"])
    if category in exceptions:
        required = exceptions[category]
        missing = [d for d in required if not case.has_doc(d)]
        for d in required:
            refs = case.documents().get(d)
            state = f"enclosed ({refs[0].source})" if refs else ("mentioned only, not enclosed" if case.mentioned_only(d) else "not enclosed")
            evidence.append(ev(refs[0].source if refs else "email", d, state))
        clause = case.sop("5.3")
        if missing:
            return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_outcome"]), evidence=evidence,
                               reason_codes=["TPP_DOCS_MISSING"], missing_documents=missing,
                               data={"exception": category})
        return CheckResult(check_id=cid, result="PASS", sop_clause=clause, evidence=evidence,
                           notes=[f"third-party payment within 5.3 exception '{category}', all documents enclosed"])
    return CheckResult(check_id=cid, result="FAIL", sop_clause=case.sop(cfg["clause_outcome"]), evidence=evidence,
                       reason_codes=["TPP_NO_EXCEPTION"])
