"""S7 draft reply: deterministic template per outcome/reason (Annex B, 4.4, 8.6), optionally polished by the LLM,
then guarded (banned terms, required facts). Template is always the fallback."""
from __future__ import annotations

import re
from datetime import date, timedelta

from app import llm
from app.case import Case
from app.s6_decide import Decision
from app.schemas import CheckResult, DraftReply
from app.tools.policy import rules

REQ_DESC = {
    "NEW_FOLIO_PURCHASE": "new investment", "ADDITIONAL_PURCHASE": "additional purchase",
    "SIP_REGISTRATION": "SIP registration", "SIP_INSTALMENT": "SIP instalment", "REDEMPTION": "redemption request",
    "CHANGE_OF_BANK": "change of bank request", "OTHER": "request",
}


def working_days_after(d: date, n: int) -> date:
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _addressee(sender: str) -> tuple[str, str]:
    m = re.match(r"\s*\"?([^\"<]*?)\"?\s*<([^>]+)>", sender or "")
    if m:
        name, email = m.group(1).strip(), m.group(2).strip()
    else:
        name, email = "", (sender or "").strip()
    if not name or re.search(r"payroll|team|office|desk|hr\b|operations|support|info", name, re.I):
        return "Sir/Madam", email
    return name, email


def _money(v: float | None) -> str:
    if v is None:
        return ""
    s = f"{v:,.0f}"
    # Indian grouping
    n = str(int(round(v)))
    if len(n) > 3:
        head, tail = n[:-3], n[-3:]
        head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
        s = f"{head},{tail}"
    return f"Rs. {s}"


def _labels() -> dict:
    return rules()["tpp"]["document_labels"]


def _subject_bits(case: Case) -> tuple[str, str]:
    folio = case.folio["folio_no"] if case.folio else None
    desc = REQ_DESC.get(case.request_type, "request")
    amt = _money(case.amount())
    scheme = (case.txn or {}).get("scheme_name") or case.extracted.scheme_name or ""
    what = f"{desc}" + (f" of {amt}" if amt and case.request_type != "OTHER" else "") + (f" in {scheme}" if scheme else "")
    where = f" (folio {folio})" if folio else ""
    return what + where, folio or ""


def template(case: Case, d: Decision, checks: list[CheckResult]) -> DraftReply:
    cfg = rules()["reply"]
    name, email = _addressee(case.sender)
    what, folio = _subject_bits(case)
    by_code = {c: chk for chk in checks for c in chk.reason_codes}
    lines: list[str] = []
    role = case.extracted.sender_role
    inv = (case.folio or {}).get("first_holder_name") or case.extracted.investor_name
    whose = {"distributor": "Your client's", "employer": "Your employee's"}.get(role or "", "Your")
    if role in ("relative", "other") and inv:
        whose = "The"
        what = what.replace(" (folio", f" for {inv} (folio", 1) if " (folio" in what else f"{what} for {inv}"
    kyc_whose = "your" if whose == "Your" else "the investor's"
    o = d.outcome
    if o == "PROCEED":
        lines.append(f"{whose} {what} has been checked and released for processing at the applicable NAV. "
                     "A confirmation will be sent to the investor's registered email address.")
        if "EUIN_MISSING" in d.reason_codes:
            lines.append("The EUIN was not quoted (or could not be validated). Please send a valid EUIN within 30 days; "
                         "commission is withheld until it is received, unless the investor's signed execution-only "
                         "declaration is provided.")
    elif o == "PROCEED_MODIFIED":
        chk = by_code.get("ARN_INVALID_DIRECT")
        why = "could not be validated on the date of the request"
        if chk and chk.data.get("problems"):
            why = f"could not be validated ({'; '.join(chk.data['problems'])})"
        arn = (case.txn or {}).get("arn") or case.extracted.arn or "quoted"
        lines.append(f"We have checked {whose.lower()} {what}. The distributor code {arn} {why}. As required by our procedure (TCC-SOP section 7.2), the investment will be made in the "
                     f"Direct plan of the same scheme and option, and no commission is payable on it.")
        lines.append("A confirmation will be sent to the investor's registered email address.")
    elif o == "REJECT":
        if {"KYC_ON_HOLD", "KYC_REJECTED"} & set(d.reason_codes):
            lines.append(f"We are unable to accept {whose.lower()} {what} at present. Please update {kyc_whose} KYC "
                         "with a KYC Registration Agency (KRA) or any SEBI-registered intermediary. Once the KYC "
                         "status is updated, the transaction can be submitted again.")
            lines.append(_refund_line(case))
        else:
            if "TPP_NO_EXCEPTION" in d.reason_codes:
                chk = by_code["TPP_NO_EXCEPTION"]
                if chk.sop_clause and chk.sop_clause.endswith("5.4"):
                    lines.append(f"We are unable to accept {whose.lower()} {what}. Under our procedure "
                                 "(TCC-SOP section 5.4), a payment into a minor's folio may be made only from the bank "
                                 "account of the minor, a parent or the legal guardian. A payment from any other "
                                 "relative, including a grandparent, is a third-party payment that cannot be accepted.")
                else:
                    lines.append(f"We are unable to accept {whose.lower()} {what}. The payment was made from a bank account "
                                 "of which the folio's first holder is not an account holder. Under our procedure "
                                 "(TCC-SOP sections 5.1 and 5.7), such third-party payments are accepted only in the "
                                 "specific cases listed in section 5.3, and this payment is not one of them.")
            if "CASH_LIMIT_BREACH" in d.reason_codes:
                lines.append(f"We are unable to accept {whose.lower()} {what}. Cash investments are limited to Rs. 50,000 "
                             "per investor per fund house in a financial year (TCC-SOP section 8.5), and this payment "
                             "would take the total above that limit.")
            lines.append(_refund_line(case))
            if case.folio and str(case.folio.get("tax_status", "")).startswith("02"):
                lines.append("A fresh investment may be made from the bank account of the minor, a parent or the legal guardian.")
            else:
                lines.append("A fresh investment may be made from a bank account held by the folio's first holder.")
    elif o == "HOLD_AND_REFER":
        upd = _next_update(case, checks)
        lines.append(f"{whose} {what} has been received and is under processing. We expect to send you an update by "
                     f"{upd.strftime('%d %B %Y')}.")
    elif o == "PEND":
        if case.request_type == "OTHER":
            lines.append(f"Thank you for your email{' regarding folio ' + folio if folio else ''}. It has been passed to "
                         "the team that handles this kind of request, who will reply to you shortly.")
            items = []
        else:
            lines.append(f"{whose} {what} has been received and is on hold pending the following:")
            items = _pend_items(case, d, by_code)
        for i, it in enumerate(items, 1):
            lines.append(f"  {i}. {it}")
        if any("send" in it.lower() for it in items):
            lines.append(f"Please send the above by reply to this email ({cfg['desk_address']}), quoting the folio number"
                         f"{' ' + folio if folio else ''}.")
        if "TPP_DOCS_MISSING" in d.reason_codes:
            lines.append("If the documents are not received within 30 days, the request will be rejected and the amount refunded.")
    elif o == "INVALID_REQUEST":
        if "FOLIO_NOT_FOUND" in d.reason_codes:
            lines.append("We could not identify the folio quoted in your email in our records. Please check the folio "
                         "number and reply with the correct folio number and the first holder's name and PAN, so that "
                         "we can take up your request.")
        else:
            lines.append("The details in your email (folio number and investor name/PAN) do not match our records. "
                         "Please reply confirming the correct folio number and the first holder's name and PAN, so that "
                         "we can take up your request.")
    body = f"Dear {name},\n\n" + "\n\n".join(l for l in lines if l) + f"\n\nRegards,\n{cfg['desk_signature']}"
    # indent list items onto consecutive lines
    body = re.sub(r"\n\n(  \d+\. )", r"\n\1", body)
    subj = f"Re: {case.subject}".strip() if case.subject else f"Your {REQ_DESC.get(case.request_type, 'request')}"
    if folio and folio not in subj and re.sub(r"\D", "", folio) not in re.sub(r"\D", "", subj):
        subj += f" [Folio {folio}]"
    return DraftReply(to=email, subject=subj, body=body)


def _refund_line(case: Case) -> str:
    acct = (case.txn or {}).get("remitter_account_masked")
    if (case.payment_mode() or "").upper() == "CASH":
        return "The amount received will be refunded to the investor."
    if acct:
        return f"The amount received will be refunded to the remitting bank account (a/c ending {acct[-4:]})."
    return "Any amount received will be refunded to the remitting bank account."


def _next_update(case: Case, checks: list[CheckResult]) -> date:
    n = rules()["reply"]["hold_update_working_days"]
    ends = [c.data.get("cooling_end") for c in checks if c.data.get("cooling_end")]
    if ends:
        return working_days_after(date.fromisoformat(max(ends)), 1)
    return working_days_after(case.received_date, n)


def _pend_items(case: Case, d: Decision, by_code: dict) -> list[str]:
    lab = _labels()
    items = []
    for code in d.reason_codes:
        chk = by_code.get(code)
        if code == "KYC_UNABLE_TO_VERIFY":
            items.append("We are re-verifying the investor's KYC status with the KYC Registration Agency. No action is "
                         "needed from you at this stage; we will update you after the next verification cycle.")
        elif code == "KYC_REGISTERED_NEW_AMC":
            items.append("Fresh KYC (Aadhaar-based where possible) so that the KYC status becomes 'KYC Validated'. Your "
                         "KYC is currently 'KYC Registered', which allows transactions only with fund houses where you "
                         "already hold a folio. Please complete it with a KRA or any SEBI-registered intermediary.")
        elif code == "TPP_DOCS_MISSING" and chk:
            for m in chk.missing_documents:
                items.append(f"{lab.get(m, m)} - please send.")
        elif code == "BANK_PROOF_REQUIRED" and chk:
            for m in chk.missing_documents or ["BANK_STATEMENT"]:
                items.append(f"{lab.get(m, m)} - please send.")
        elif code == "MINOR_ATTAINED_MAJORITY":
            items.append("The investor has attained majority, so transactions and SIPs in the folio are suspended until "
                         "the investor sends the change of status form (minor to major), their own KYC and their new "
                         "bank details - please send.")
        elif code == "COB_COOLING" and chk:
            end = chk.data.get("cooling_end")
            items.append(f"The payout is held until {date.fromisoformat(end).strftime('%d %B %Y') if end else 'the end of the cooling period'} "
                         "following the recent change of bank request; it will then be paid to the bank account "
                         "validated at that time. No action is needed from you.")
        elif code and chk is None and not items:
            items.append("A re-check of the request details. We will update you shortly.")
    if not items:
        items.append("A re-check of the request details by our team. We will update you shortly.")
    return list(dict.fromkeys(items))


# ----------------------------------------------------------------------------- guard + LLM polish
def guard(case: Case, d: Decision, reply: DraftReply) -> list[str]:
    cfg = rules()["reply"]
    problems = []
    body = reply.body.lower()
    if d.outcome in ("HOLD_AND_REFER", "PEND"):
        for w in cfg["banned_terms_hold"]:
            if re.search(rf"\b{re.escape(w.lower())}\w*", body):
                problems.append(f"banned term '{w}' in held/pended reply")
    else:
        for w in ("suspicious", "suspicion", "fiu", "money laundering", "referral", "compliance review"):
            if re.search(rf"\b{re.escape(w)}", body):
                problems.append(f"banned term '{w}'")
    if re.search(r"\b(has|have) been processed\b|\bprocessed successfully\b|\bunits (have been )?allotted\b", body):
        problems.append("claims the transaction was processed")
    if case.folio and case.folio["folio_no"] not in reply.body and case.folio["folio_no"] not in reply.subject:
        problems.append("folio not quoted")
    if d.outcome == "HOLD_AND_REFER" and re.search(r"\b(document|cooling|bank change|change of bank|kyc)\b", body):
        problems.append("hold reply gives reasons beyond processing status")
    if {"KYC_ON_HOLD", "KYC_REJECTED"} & set(d.reason_codes) and re.search(r"third[- ]party|cash|distributor|arn", body):
        problems.append("KYC on-hold reply states another reason (4.4)")
    return problems


POLISH_PROMPT = """Rewrite the draft reply below so it reads naturally and politely, in plain English, as an email from a
mutual-fund registrar's transaction desk. Keep EVERY fact, date, amount, account ending, folio number, document and
instruction exactly; add NO new facts, reasons, promises or policy statements; do not remove any listed item.
Never use the words: referral, refer, suspicious, compliance, FIU, report, investigation, flagged, processed.
Keep the greeting and the sign-off. Return only the email body text.

DRAFT:
{draft}
"""


def draft(case: Case, d: Decision, checks: list[CheckResult]) -> tuple[DraftReply, dict]:
    base = template(case, d, checks)
    meta = {"method": "template", "guard_problems": []}
    problems = guard(case, d, base)
    if problems:  # template should never fail; record if it does
        meta["template_guard"] = problems
    if not llm.available():
        return base, meta
    try:
        text = llm.generate(POLISH_PROMPT.format(draft=base.body), purpose="reply_drafting", max_output_tokens=1024).strip()
        candidate = DraftReply(to=base.to, subject=base.subject, body=text)
        problems = guard(case, d, candidate)
        # facts preserved? every number in the template must still be present
        for num in set(re.findall(r"\d[\d,./-]{2,}", base.body)):
            if num not in text:
                problems.append(f"lost fact '{num}'")
        if problems:
            meta["guard_problems"] = problems
            meta["method"] = "template (LLM draft rejected by guard)"
            return base, meta
        meta["method"] = "llm"
        return candidate, meta
    except llm.LLMUnavailable as e:
        meta["method"] = f"template (LLM unavailable: {str(e)[:80]})"
        return base, meta
