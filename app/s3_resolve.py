"""S3: identify folio, investor and transaction. Exact matches only; conflicts -> INVALID_REQUEST (SOP 9.4)."""
from __future__ import annotations


from app.case import Case
from app.checks.base import ev
from app.normalise import last4, names_match, normalise_folio, parse_date
from app.tools import folio as folio_tool
from app.tools import kra
from app.tools import txn as txn_tool

TYPE_FOR_HINT = {
    "NEW_FOLIO_PURCHASE": {"NEW"}, "ADDITIONAL_PURCHASE": {"ADD", "NEW"}, "SIP_REGISTRATION": {"SIP_REG"},
    "SIP_INSTALMENT": {"SIP"}, "REDEMPTION": {"RED", "SWO"}, "CHANGE_OF_BANK": set(), "OTHER": set(),
}


def pan_compatible(a: str | None, b: str | None) -> bool:
    """Compare PANs position-wise, ignoring masked positions."""
    if not a or not b:
        return False
    a, b = a.strip().upper(), b.strip().upper()
    if len(a) != 10 or len(b) != 10:
        return False
    return all(x == y for x, y in zip(a, b) if x != "*" and y != "*")


def _folio_names(f: dict) -> list[str]:
    names = [f.get("first_holder_name"), f.get("second_holder_name"), f.get("guardian_name")]
    for p in (f.get("first_holder_pan_masked"), f.get("second_holder_pan_masked"), f.get("guardian_pan_masked")):
        k = kra.lookup(p) if p else None
        if k:
            names.append(k.get("name_as_per_kra"))
    return [n for n in names if n]


def _fail(case: Case, code: str, msg: str, evidence: list | None = None) -> Case:
    case.identity_failure = code
    case.identity_notes.append(msg)
    case.identity_evidence = (evidence or []) + [ev("request", "identity", msg)]
    return case


def resolve(case: Case, raw_folio_tokens: list[str], invalid_tokens: list[str]) -> Case:
    x = case.extracted
    candidates: list[str] = []
    for tok in raw_folio_tokens + ([x.folio_raw] if x.folio_raw else []) + x.folio_candidates:
        n = normalise_folio(tok)
        if n and n not in candidates:
            candidates.append(n)
    found = [(c, folio_tool.get(c)) for c in candidates]
    missing = [c for c, f in found if f is None]
    hits = [f for _, f in found if f is not None]
    target = x.target_amc

    if missing:
        return _fail(case, "FOLIO_NOT_FOUND",
                     f"folio {', '.join(missing)} not in folio master (no similar folio substituted)",
                     [ev("folio_master.csv", f"folio_no={m}", "no such folio") for m in missing])
    if not hits and invalid_tokens:
        return _fail(case, "FOLIO_NOT_FOUND", f"folio number(s) {', '.join(invalid_tokens)} are not valid 10-digit folio numbers",
                     [ev("request", "folio", t) for t in invalid_tokens])

    if len(hits) > 1:
        pans = {h["first_holder_pan_masked"] for h in hits}
        if target and len([h for h in hits if h["amc_code"] == target]) == 1 and len(pans) == 1:
            primary = next(h for h in hits if h["amc_code"] == target)
            case.referenced_folios = [h["folio_no"] for h in hits if h is not primary]
            hits = [primary]
        else:
            return _fail(case, "FOLIO_PAN_MISMATCH", f"request quotes several folios ({', '.join(h['folio_no'] for h in hits)})",
                         [ev("folio_master.csv", f"folio_no={h['folio_no']}", h["first_holder_name"]) for h in hits])

    f = hits[0] if hits else None
    if f is None:
        # No folio quoted: identify by PAN, or by exact UTR in the register.
        if x.pan:
            k = kra.lookup(x.pan)
            fol = folio_tool.by_pan(x.pan, role="first")
            if target:
                same = [z for z in fol if z["amc_code"] == target]
            else:
                same = fol
            if len(same) == 1 and case.request_type != "NEW_FOLIO_PURCHASE":
                f = same[0]
                case.warnings.append(f"Folio not quoted; identified as {f['folio_no']} from PAN {x.pan} (only folio of that investor at {f['amc_code']}).")
            elif k or fol:
                case.first_holder_pan = x.pan
                case.amc = target
                case.identity_evidence.append(ev("kra_kyc_snapshot.csv" if k else "folio_master.csv", f"pan_masked={x.pan}",
                                                 f"investor identified by PAN ({k['name_as_per_kra'] if k else fol[0]['first_holder_name']})"))
                return case
        if f is None and x.utr:
            rows = [r for r in txn_tool.by_utr(x.utr) if not r.get("duplicate_of")]
            if len(rows) == 1 and rows[0]["folio_no"]:
                f = folio_tool.get(rows[0]["folio_no"])
                if f:
                    case.warnings.append(f"Folio not quoted; identified from UTR {x.utr} in the transaction register.")
        if f is None:
            return _fail(case, "FOLIO_NOT_FOUND", "no folio number, PAN or matching UTR identifies the investor")

    # Folio of a different AMC than the one the request is for -> it only identifies the investor (new folio).
    if target and f["amc_code"] != target:
        if case.request_type in ("NEW_FOLIO_PURCHASE", "ADDITIONAL_PURCHASE", "SIP_REGISTRATION", "OTHER") and not _has_pending_for(f, x):
            if x.investor_name and not any(names_match(x.investor_name, n) for n in _folio_names(f)):
                return _fail(case, "FOLIO_PAN_MISMATCH", f"investor '{x.investor_name}' is not a holder of referenced folio {f['folio_no']}")
            case.referenced_folios.append(f["folio_no"])
            case.first_holder_pan = f["first_holder_pan_masked"]
            case.amc = target
            case.request_type = "NEW_FOLIO_PURCHASE"
            case.identity_evidence.append(ev("folio_master.csv", f"folio_no={f['folio_no']}",
                                             f"existing {f['amc_code']} folio identifies investor {f['first_holder_name']} "
                                             f"({f['first_holder_pan_masked']}); request is for a new {target} folio"))
            return case
        return _fail(case, "FOLIO_PAN_MISMATCH", f"folio {f['folio_no']} is a {f['amc_code']} folio but the request is for {target}")

    # PAN cross-check
    if x.pan:
        pans = [f.get("first_holder_pan_masked"), f.get("second_holder_pan_masked"), f.get("guardian_pan_masked")]
        if not any(pan_compatible(x.pan, p) for p in pans if p):
            return _fail(case, "FOLIO_PAN_MISMATCH", f"PAN {x.pan} in the request is not a holder/guardian PAN of folio {f['folio_no']}",
                         [ev("folio_master.csv", f"folio_no={f['folio_no']}", f"holder PANs {[p for p in pans if p]}")])
    # Name cross-check (tolerant; PAN and folio identify, names only flag clear conflicts)
    names = _folio_names(f)
    for label, nm in (("investor", x.investor_name), ("minor", x.minor_name)):
        if nm and not any(names_match(nm, n) for n in names):
            return _fail(case, "FOLIO_PAN_MISMATCH", f"{label} name '{nm}' does not match any holder of folio {f['folio_no']}",
                         [ev("folio_master.csv", f"folio_no={f['folio_no']}", f"holders {names}")])
    # Folio written on enclosed forms must agree
    for a in case.attachments:
        n = normalise_folio(a.folio_raw) if a.folio_raw else None
        if n and n != f["folio_no"]:
            return _fail(case, "FOLIO_PAN_MISMATCH", f"{a.file_name} quotes folio {n}, email quotes {f['folio_no']}")

    case.folio = f
    case.amc = f["amc_code"]
    case.first_holder_pan = f["first_holder_pan_masked"]
    _match_txn(case)
    return case


def _has_pending_for(f: dict, x) -> bool:
    if not x.utr:
        return False
    return any(r["txn_id"] for r in txn_tool.pending(f["folio_no"]) if r.get("utr") == x.utr)


def _match_txn(case: Case) -> None:
    f, x = case.folio, case.extracted
    pend = txn_tool.pending(f["folio_no"])
    want_types = TYPE_FOR_HINT.get(x.request_type_hint or "", set())
    req_date = parse_date(x.txn_date) or case.received_date
    acct = x.remitter_account_last4

    def score(r: dict) -> int:
        s = 0
        if x.utr and r.get("utr"):
            s += 100 if r["utr"].upper() == x.utr.upper() else -100
        if x.amount_inr and r.get("amount_inr"):
            s += 10 if abs(float(r["amount_inr"]) - x.amount_inr) < 1 else -10
        if want_types:
            s += 3 if r["txn_type"] in want_types else -3
        d = parse_date(r.get("txn_date"))
        if d and abs((d - req_date).days) <= 1:
            s += 2
        if acct and r.get("remitter_account_masked"):
            s += 5 if last4(r["remitter_account_masked"]) == acct else -5
        return s

    primary = [r for r in pend if not r.get("duplicate_of")]
    scored = sorted(((score(r), r) for r in primary), key=lambda z: (-z[0], z[1]["txn_id"]))
    chosen = None
    if scored:
        top = scored[0]
        tied = [r for s, r in scored if s == top[0]]
        if top[0] >= 0 and (len(tied) == 1):
            chosen = top[1]
        elif top[0] >= 0 and len(tied) > 1:
            case.warnings.append(f"Several pending transactions match equally ({', '.join(r['txn_id'] for r in tied)}); "
                                 f"none selected - checks use the email details.")
    if chosen is None and x.utr:
        rows = [r for r in txn_tool.by_utr(x.utr) if r["folio_no"] == f["folio_no"] and not r.get("duplicate_of")]
        if rows:
            chosen = rows[0]
            if chosen["status"] != "PENDING_TCC":
                case.warnings.append(f"Matched {chosen['txn_id']} by UTR but its status is {chosen['status']} (not PENDING_TCC).")
    if chosen:
        dups = [r["txn_id"] for r in pend if r.get("duplicate_of") == chosen["txn_id"]]
        if dups:
            case.warnings.append(f"Duplicate pending entry {', '.join(dups)} mirrors {chosen['txn_id']} (same UTR/amount/date): "
                                 f"process once only; data issue logged.")
        if "nonpositive_units" in (chosen.get("data_flags") or ""):
            case.warnings.append(f"{chosen['txn_id']} has negative units/NAV (data issue).")
        case.txn = chosen
    # folio-level data issues worth surfacing
    bad = [r["txn_id"] for r in txn_tool.history(f["folio_no"]) if "nonpositive" in (r.get("data_flags") or "")]
    if bad:
        case.warnings.append(f"Folio history contains transactions with negative units/NAV ({', '.join(bad)}); holdings not relied on.")
