"""S2 understand: regex pre-pass -> LLM structured extraction (retry once) -> merge -> request-type classification.

Identifiers (folio, PAN, UTR, ARN, EUIN, account digits) come from regex over the literal text; the LLM
adds intent, relationships, roles and documents. LLM values for identifiers that do not appear in the
text are discarded (they would be invented).
"""
from __future__ import annotations

import json
import re

from pydantic import ValidationError

from app import llm
from app.normalise import normalise_folio, parse_date
from app.schemas import AttachmentInfo, DocumentRef, ExtractedRequest

FOLIO_RE = re.compile(r"(?<![\dA-Z])(\d{8}\s*[/\-]\s*\d{2}|\d{10})(?!\d)")
FOLIO_CTX_RE = re.compile(r"folio\s*(?:no\.?|number|#)?\s*[:\-]?\s*([\d][\d\s/\-]{6,14}\d)", re.I)
PAN_RE = re.compile(r"\b([A-Z]{3}[PCHFATBLJG][A-Z](?:\d{4}|\*\*\d{2}|XX\d{2})[A-Z])\b")
UTR_RE = re.compile(r"\bUTR\s*(?:no\.?|number)?\s*[:\-]?\s*([A-Z0-9]{12,22})\b", re.I)
ARN_RE = re.compile(r"\bARN\s*[-:]?\s*(\d{3,7})\b", re.I)
EUIN_RE = re.compile(r"\bEUIN\s*(?:no\.?)?\s*[:\-]?\s*(E\s*\d{5,7})\b", re.I)
ACCT_RE = re.compile(r"(?:a/c|account|acct)\s*(?:no\.?\s*)?(?:ending|ending\s+with|ending\s+in|no\.?\s*xx+|number\s*xx+)?\s*(?:with\s+)?[:\-]?\s*(?:x+|\*+)?(\d{4})\b", re.I)
ACCT_END_RE = re.compile(r"ending\s*(?:with|in)?\s*[:\-]?\s*(\d{4})\b", re.I)
AMOUNT_RE = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)\s*(lakh|lac|crore|cr|k)?\b|([\d.]+)\s*(lakh|lac|crore)\b", re.I)

REQUEST_TYPES = ["NEW_FOLIO_PURCHASE", "ADDITIONAL_PURCHASE", "SIP_REGISTRATION", "SIP_INSTALMENT", "REDEMPTION",
                 "CHANGE_OF_BANK", "OTHER"]
DOC_TYPES = ["TPP_DECLARATION", "EMPLOYER_DECLARATION", "EMPLOYEE_LIST", "KYC_ACK_INVESTOR", "KYC_ACK_THIRD_PARTY",
             "CUSTODIAN_SEBI_REG", "DISTRIBUTOR_LIST", "CORPORATE_LIST", "KYC_PAYER", "BANK_STATEMENT",
             "TRANSFER_INSTRUCTION", "CANCELLED_CHEQUE", "PASSBOOK", "BANK_LETTER", "BANKER_CERTIFICATE", "COB_FORM",
             "EXISTING_BANK_PROOF", "EXECUTION_ONLY_DECLARATION", "CHANGE_OF_STATUS_FORM", "REDEMPTION_FORM", "OTHER"]
RELATIONS = ["self", "joint_with_investor", "spouse", "parent", "guardian", "grandparent", "other_relative",
             "second_holder", "employer", "custodian", "company", "friend", "unknown"]

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "request_type_hint": {"type": ["string", "null"], "enum": REQUEST_TYPES + [None]},
        "folio_raw": {"type": ["string", "null"], "description": "folio exactly as written for the folio this request is about"},
        "other_folios_mentioned": {"type": "array", "items": {"type": "string"}},
        "pan": {"type": ["string", "null"]},
        "investor_name": {"type": ["string", "null"], "description": "the folio holder / beneficiary investor (not the sender unless they are the investor)"},
        "minor_name": {"type": ["string", "null"]},
        "scheme_name": {"type": ["string", "null"]},
        "target_amc": {"type": ["string", "null"], "enum": ["NMF", "TMF", None], "description": "NMF=Narmada, TMF=Tungabhadra; the AMC of the transaction requested"},
        "plan": {"type": ["string", "null"], "enum": ["REGULAR", "DIRECT", None]},
        "option": {"type": ["string", "null"]},
        "amount_inr": {"type": ["number", "null"]},
        "payment_mode": {"type": ["string", "null"], "enum": ["NEFT", "RTGS", "IMPS", "UPI", "NETBANKING", "NACH", "OTM", "CHEQUE", "DD", "CASH", None]},
        "remitter_name": {"type": ["string", "null"]},
        "remitter_account_last4": {"type": ["string", "null"]},
        "payer_relation_to_investor": {"type": ["string", "null"], "enum": RELATIONS + [None],
                                       "description": "relationship of the person/entity whose bank account paid, to the first holder/beneficiary"},
        "utr": {"type": ["string", "null"]},
        "arn": {"type": ["string", "null"]},
        "euin": {"type": ["string", "null"]},
        "txn_date": {"type": ["string", "null"], "description": "YYYY-MM-DD"},
        "new_bank_account_last4": {"type": ["string", "null"]},
        "new_bank_ifsc": {"type": ["string", "null"]},
        "payout_account_last4": {"type": ["string", "null"], "description": "account the sender wants redemption proceeds paid to"},
        "documents_enclosed": {"type": "array", "items": {"type": "object", "properties": {
            "type": {"type": "string", "enum": DOC_TYPES},
            "present_as_attachment": {"type": "boolean"},
            "only_mentioned": {"type": "boolean"},
            "source": {"type": ["string", "null"]}},
            "required": ["type", "present_as_attachment", "only_mentioned"]}},
        "is_cash": {"type": ["boolean", "null"]},
        "execution_only_declaration": {"type": ["boolean", "null"]},
        "in_person_verification": {"type": ["boolean", "null"]},
        "contact_change_claimed": {"type": ["boolean", "null"]},
        "cob_mentioned": {"type": ["boolean", "null"]},
        "sender_role": {"type": ["string", "null"], "enum": ["investor", "distributor", "employer", "relative", "other", None]},
        "third_party_category": {"type": ["string", "null"], "enum": ["employer", "custodian", "amc_commission", "corporate_incentive", "relative", "other", None]},
    },
    "required": ["request_type_hint", "folio_raw", "documents_enclosed"],
}

SYSTEM = ("You extract facts from emails received by a mutual-fund registrar's transaction compliance desk. "
          "Return JSON matching the schema. Never invent values: use null when something is not stated. "
          "Emails may mix English with Hindi or other languages; interpret them. "
          "Do not decide whether the request is acceptable.")

PROMPT_RULES = """Rules:
- request_type_hint: NEW_FOLIO_PURCHASE (opening a folio / first investment with an AMC), ADDITIONAL_PURCHASE (lump sum into an existing folio), SIP_REGISTRATION, SIP_INSTALMENT, REDEMPTION, CHANGE_OF_BANK (only bank change, no redemption), OTHER (queries, nominations, anything else).
- documents_enclosed: one entry per document. present_as_attachment=true only if the file is actually attached (see ATTACHMENTS). A document only mentioned in the text, promised later, or a ticked checkbox on a form is only_mentioned=true, present_as_attachment=false.
  A TPP declaration form ticking "employer declaration" does not enclose the employer declaration; a separate letter does.
  KYC_ACK_THIRD_PARTY = KYC acknowledgement of employer/custodian/corporate; KYC_ACK_INVESTOR = of the investor.
  EXISTING_BANK_PROOF = proof of the currently registered (old) account in a change of bank.
- payer_relation_to_investor: relationship of the account holder who paid, to the folio's first holder (or the minor for a minor folio). "self" if the investor paid from their own account; "second_holder" if the joint second holder paid from their own account.
- remitter_account_last4 / payout_account_last4 / new_bank_account_last4: last 4 digits only.
- amounts in rupees as numbers (1.5 lakh = 150000).
"""


def _amounts(text: str) -> list[float]:
    vals = []
    for m in AMOUNT_RE.finditer(text):
        num, unit = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        try:
            v = float(num.replace(",", ""))
        except (ValueError, AttributeError):
            continue
        u = (unit or "").lower()
        v *= {"lakh": 1e5, "lac": 1e5, "crore": 1e7, "cr": 1e7, "k": 1e3}.get(u, 1)
        if v >= 100:
            vals.append(v)
    for m in re.finditer(r"\b([\d.]+)\s*(lakh|lac|crore)\b", text, re.I):
        v = float(m.group(1)) * (1e5 if m.group(2).lower() in ("lakh", "lac") else 1e7)
        vals.append(v)
    return vals


def regex_pass(subject: str, body: str) -> dict:
    """Literal identifiers from the email. Returns dict incl. folio tokens and invalid folio-like tokens."""
    text = f"{subject}\n{body}"
    folios, invalid = [], []
    for m in FOLIO_RE.finditer(text):
        tok = re.sub(r"\s", "", m.group(1))
        digits = re.sub(r"\D", "", tok)
        if len(digits) == 10 and digits[:3] in ("401", "711"):
            if tok not in folios:
                folios.append(tok)
    for m in FOLIO_CTX_RE.finditer(text):
        tok = re.sub(r"\s", "", m.group(1)).strip("/-")
        if normalise_folio(tok):
            if tok not in folios and normalise_folio(tok) not in [normalise_folio(f) for f in folios]:
                folios.append(tok)
        elif tok not in invalid:
            invalid.append(tok)
    # de-dup by canonical form
    seen, uniq = set(), []
    for f in folios:
        n = normalise_folio(f)
        if n not in seen:
            seen.add(n)
            uniq.append(f)
    out = {
        "folio_tokens": uniq, "invalid_folio_tokens": invalid,
        "pan": (PAN_RE.search(text) or [None, None])[1] if PAN_RE.search(text) else None,
        "utr": UTR_RE.search(text).group(1).upper() if UTR_RE.search(text) else None,
        "arn": f"ARN-{ARN_RE.search(text).group(1)}" if ARN_RE.search(text) else None,
        "euin": re.sub(r"\s", "", EUIN_RE.search(text).group(1)).upper() if EUIN_RE.search(text) else None,
        "amounts": _amounts(text),
        "accounts": list(dict.fromkeys(ACCT_END_RE.findall(text) + ACCT_RE.findall(text))),
    }
    return out


def _has(text: str, *pats: str) -> bool:
    return any(re.search(p, text, re.I) for p in pats)


def heuristic_extract(subject: str, body: str, sender: str, rx: dict, atts: list[AttachmentInfo]) -> ExtractedRequest:
    """Deterministic fallback extraction (used when the LLM is unavailable, and as a cross-check)."""
    text = f"{subject}\n{body}"
    low = text.lower()
    x = ExtractedRequest()
    x.folio_raw = rx["folio_tokens"][0] if rx["folio_tokens"] else None
    x.folio_candidates = rx["folio_tokens"][1:]
    x.pan, x.utr, x.arn, x.euin = rx["pan"], rx["utr"], rx["arn"], rx["euin"]
    x.amount_inr = rx["amounts"][0] if rx["amounts"] else None
    # target AMC from scheme / fund names
    nmf = len(re.findall(r"narmada|\bnmf\b", low))
    tmf = len(re.findall(r"tungabhadra|\btmf\b", low))
    m = re.search(r"((?:narmada|tungabhadra)\s+[a-z&\s]+?fund)", low)
    if m:
        x.scheme_name = m.group(1).title()
        x.target_amc = "NMF" if m.group(1).startswith("narmada") else "TMF"
    elif nmf or tmf:
        x.target_amc = "NMF" if nmf >= tmf else "TMF"
    if _has(low, r"\bdirect\b"):
        x.plan = "DIRECT"
    if _has(low, r"\bregular\b") or (x.arn and not x.plan):
        x.plan = "REGULAR"
    for mode, pat in [("NEFT", r"\bneft\b"), ("RTGS", r"\brtgs\b"), ("IMPS", r"\bimps\b"), ("UPI", r"\bupi\b"),
                      ("NACH", r"\bnach\b|\botm\b|auto[\s-]*debit"), ("NETBANKING", r"net\s*banking"),
                      ("CHEQUE", r"\bcheque\b(?!.*cancel)"), ("DD", r"demand draft|\bdd\b"), ("CASH", r"\bcash\b|nakad")]:
        if re.search(pat, low):
            x.payment_mode = mode
            break
    x.is_cash = x.payment_mode == "CASH" or None
    # request type hint
    redemption = _has(low, r"redeem|redemption|withdraw|nikal", r"sell (my )?units")
    cob = _has(low, r"change of bank|change bank|bank mandate change|new bank account|update (my )?bank|cob\b")
    if redemption:
        x.request_type_hint = "REDEMPTION"
    elif cob:
        x.request_type_hint = "CHANGE_OF_BANK"
    elif _has(low, r"sip") and _has(low, r"register|registration|start(ed)?|new sip|first instal"):
        x.request_type_hint = "SIP_REGISTRATION"
    elif _has(low, r"sip instal|instalment"):
        x.request_type_hint = "SIP_INSTALMENT"
    elif _has(low, r"open (a |the )?(new )?folio|new folio|new investment|fresh purchase|first investment"):
        x.request_type_hint = "NEW_FOLIO_PURCHASE" if not rx["folio_tokens"] or _has(low, r"open|new folio") else "ADDITIONAL_PURCHASE"
    elif _has(low, r"additional|added|top[\s-]*up|invest|transferred|purchase|sent rs|paid|nivesh"):
        x.request_type_hint = "ADDITIONAL_PURCHASE"
    else:
        x.request_type_hint = "OTHER"
    x.cob_mentioned = cob or any("COB_FORM" in a.doc_types for a in atts)
    x.contact_change_claimed = _has(low, r"(mobile|email|phone|contact).{0,40}(changed|updated|new)")
    x.execution_only_declaration = _has(low, r"execution[\s-]*only") or None
    x.in_person_verification = _has(low, r"in[\s-]*person verif") or None
    # accounts
    accts = rx["accounts"]
    if redemption or cob:
        m = re.search(r"(?:credit|pay|transfer|send).{0,80}?(?:account|a/c).{0,40}?ending\s*(?:with|in)?\s*(\d{4})", low, re.S)
        if m:
            x.payout_account_last4 = m.group(1)
        m = re.search(r"new\s+[a-z\s]*?(?:bank\s+)?(?:account|a/c)\s*(?:ending\s*(?:with|in)?\s*)?(\d{4})", low)
        if m:
            x.new_bank_account_last4 = m.group(1)
    elif accts:
        x.remitter_account_last4 = accts[0]
    # roles & relations
    sender_l = sender.lower()
    if _has(low, r"\bour client\b|\bARN\b.*\bkindly\b|our customer") or (x.arn and _has(low, r"our client|client")):
        x.sender_role = "distributor"
    if _has(low, r"\bour employee|employee code|payroll|employee investment"):
        x.sender_role = "employer"
        x.third_party_category = "employer"
        x.payer_relation_to_investor = "employer"
    if _has(low, r"grand(son|daughter|child)|pota|poti|nati"):
        x.payer_relation_to_investor = "grandparent"
        x.sender_role = "relative"
        x.third_party_category = "relative"
    elif _has(low, r"\bmy (son|daughter|child)\b|beta|beti"):
        x.payer_relation_to_investor = "parent"
    elif _has(low, r"\bmy (wife|husband)\b.{0,80}first holder|first holder.{0,80}\bmy (wife|husband)"):
        x.payer_relation_to_investor = "spouse" if _has(low, r"from my .{0,30}account|my savings account") else None
    elif _has(low, r"this is my own account|from my (own )?(\w+\s){0,3}(account|a/c)|my registered|from my"):
        x.payer_relation_to_investor = "self"
    if not x.sender_role:
        x.sender_role = "investor" if x.payer_relation_to_investor in ("self", None) else "other"
    # documents from attachments + mentions
    for a in atts:
        for t in a.doc_types:
            if t != "OTHER":
                x.documents_enclosed.append(DocumentRef(type=t, present_as_attachment=True, source=a.file_name))
    mention_rules = [("EMPLOYEE_LIST", r"list of employees"), ("KYC_ACK_INVESTOR", r"kyc acknowledg\w* (of )?(the )?(investor|employee)"),
                     ("KYC_ACK_THIRD_PARTY", r"kyc acknowledg\w* (of )?(the )?(employer|company|third party)"),
                     ("TPP_DECLARATION", r"third party payment declaration|tpp declaration")]
    all_text = text + "\n" + "\n".join(a.text for a in atts)
    for t, pat in mention_rules:
        if re.search(pat, all_text, re.I) and not any(d.type == t and d.present_as_attachment for d in x.documents_enclosed):
            x.documents_enclosed.append(DocumentRef(type=t, only_mentioned=True, source="email/attachment text"))
    for a in atts:
        if "COB_FORM" in a.doc_types:
            if a.flags.get("in_person"):
                x.in_person_verification = True
            if a.flags.get("new_account_last4"):
                x.new_bank_account_last4 = x.new_bank_account_last4 or a.flags["new_account_last4"]
    m = re.search(r"\b(\d{1,2}[-/]\d{1,2}[-/]\d{4}|\d{1,2}[-\s](?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*[-\s]\d{4})\b", low)
    if m:
        d = parse_date(m.group(1).replace(" ", "-").title()) or parse_date(m.group(1))
        x.txn_date = d.isoformat() if d else None
    return x


def _literal(value: str | None, haystack: str) -> bool:
    if not value:
        return False
    v = re.sub(r"[\s/\-]", "", value).upper()
    return v in re.sub(r"[\s/\-]", "", haystack).upper()


def llm_extract(subject: str, body: str, sender: str, atts: list[AttachmentInfo]) -> ExtractedRequest:
    att_desc = "\n".join(
        f"--- ATTACHMENT {a.file_name} (detected: {', '.join(a.doc_types)}; read via {a.method}"
        + (f"; ticked boxes: {a.ticked}" if a.ticked else "") + ")\n" + (a.text[:3000] or "[no text available]")
        for a in atts) or "(none)"
    prompt = (f"{PROMPT_RULES}\nFROM: {sender}\nSUBJECT: {subject}\nBODY:\n{body}\n\nATTACHMENTS:\n{att_desc}\n")
    last_err = None
    for attempt in range(2):
        p = prompt if attempt == 0 else prompt + f"\nYour previous output was invalid ({last_err}). Return only valid JSON."
        try:
            raw = llm.generate_json(p, purpose="extraction", json_schema=EXTRACTION_SCHEMA, system=SYSTEM)
            raw["folio_candidates"] = raw.pop("other_folios_mentioned", []) or []
            return ExtractedRequest.model_validate(raw)
        except (json.JSONDecodeError, ValidationError) as e:
            last_err = str(e)[:300]
    raise ValueError(f"extraction invalid twice: {last_err}")


def merge(rx: dict, heur: ExtractedRequest, lx: ExtractedRequest | None, text: str, warnings: list[str]) -> ExtractedRequest:
    """Regex identifiers win; LLM supplies semantics. LLM identifiers not present in the text are dropped."""
    if lx is None:
        return heur
    x = lx.model_copy(deep=True)
    for fld in ("pan", "utr", "arn", "euin"):
        rv, lv = getattr(heur, fld), getattr(x, fld)
        if rv and lv and re.sub(r"\W", "", rv).upper() != re.sub(r"\W", "", lv).upper():
            warnings.append(f"Extraction disagreement on {fld}: text has {rv}, model said {lv}; using text value.")
        if rv:
            setattr(x, fld, rv)
        elif lv and not _literal(lv, text):
            warnings.append(f"Model {fld} '{lv}' not found in the email text; discarded.")
            setattr(x, fld, None)
    # folios: union of literal tokens; model-only folios that are not literal are discarded
    lits = rx["folio_tokens"]
    model_folios = [f for f in [x.folio_raw] + x.folio_candidates if f]
    for f in model_folios:
        if not _literal(f, text):
            warnings.append(f"Model folio '{f}' not found in the email text; discarded.")
    model_lit = [f for f in model_folios if _literal(f, text)]
    primary = None
    if x.folio_raw and _literal(x.folio_raw, text):
        primary = x.folio_raw
    elif lits:
        primary = lits[0]
    x.folio_raw = primary
    others = []
    for f in lits + model_lit:
        if f != primary and normalise_folio(f) != normalise_folio(primary) and normalise_folio(f) not in [normalise_folio(o) for o in others]:
            others.append(f)
    x.folio_candidates = others
    for fld in ("remitter_account_last4", "payout_account_last4", "new_bank_account_last4"):
        v = getattr(x, fld)
        if v and not _literal(v, text):
            setattr(x, fld, getattr(heur, fld))
        elif not v and getattr(heur, fld):
            setattr(x, fld, getattr(heur, fld))
    # documents: attachments are ground truth for presence
    att_types = {(d.type, d.source) for d in heur.documents_enclosed if d.present_as_attachment}
    docs: list[DocumentRef] = [d for d in heur.documents_enclosed if d.present_as_attachment]
    present = {d.type for d in docs}
    att_names = {d.source for d in docs}
    for d in x.documents_enclosed:
        if d.type in present or d.type == "OTHER":
            continue
        if d.present_as_attachment and d.source in att_names:
            docs.append(DocumentRef(type=d.type, present_as_attachment=True, source=d.source, detail="model"))
            present.add(d.type)
        else:
            docs.append(DocumentRef(type=d.type, only_mentioned=True, source=d.source or "email"))
    for d in heur.documents_enclosed:
        if d.only_mentioned and d.type not in present and not any(z.type == d.type for z in docs):
            docs.append(d)
    x.documents_enclosed = docs
    del att_types
    for fld in ("amount_inr", "payment_mode", "plan", "target_amc", "txn_date", "is_cash", "cob_mentioned",
                "in_person_verification", "execution_only_declaration", "contact_change_claimed", "scheme_name"):
        if getattr(x, fld) in (None, "") and getattr(heur, fld) not in (None, ""):
            setattr(x, fld, getattr(heur, fld))
    return x


TXN_TO_TYPE = {"NEW": "NEW_FOLIO_PURCHASE", "ADD": "ADDITIONAL_PURCHASE", "SIP_REG": "SIP_REGISTRATION",
               "SIP": "SIP_INSTALMENT", "RED": "REDEMPTION", "SWI": "OTHER", "SWO": "OTHER"}


def classify(x: ExtractedRequest, txn: dict | None, folio_exists: bool) -> tuple[str, str]:
    """Rules first (matched transaction type), then extracted hint. Returns (request_type, basis)."""
    if txn and txn.get("txn_type") in TXN_TO_TYPE:
        t = TXN_TO_TYPE[txn["txn_type"]]
        return t, f"matched transaction {txn['txn_id']} type {txn['txn_type']}"
    hint = x.request_type_hint if x.request_type_hint in REQUEST_TYPES else None
    if hint == "NEW_FOLIO_PURCHASE" and folio_exists:
        return "ADDITIONAL_PURCHASE", "existing folio quoted for a purchase"
    if hint:
        return hint, "email content"
    return "OTHER", "no recognisable request"
