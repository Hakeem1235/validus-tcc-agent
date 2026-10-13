"""REFERRAL (SOP 8.3-8.5 and addendum triggers such as TMF-ADD-02 A1)."""
from __future__ import annotations

from datetime import timedelta

from app.case import Case
from app.checks.base import R, ev, na
from app.normalise import parse_date
from app.schemas import CheckResult
from app.tools import folio as folio_tool
from app.tools import txn as txn_tool

PURCHASE_TXN = {"NEW", "ADD", "SIP_REG", "SIP"}


def _current_type(case: Case) -> str | None:
    if case.txn:
        return case.txn["txn_type"]
    return {"NEW_FOLIO_PURCHASE": "NEW", "ADDITIONAL_PURCHASE": "ADD", "SIP_REGISTRATION": "SIP_REG",
            "SIP_INSTALMENT": "SIP", "REDEMPTION": "RED"}.get(case.request_type)


def run(case: Case) -> CheckResult:
    cfg = R()["referral"]
    cid = "REFERRAL"
    if case.request_type in ("OTHER",):
        return na(cid, "not a financial transaction", case.sop(cfg["clause_triggers"]))
    f = case.folio
    evidence, reasons, outcome_by_reason, clause = [], [], {}, case.sop(cfg["clause_triggers"])
    ctype = _current_type(case)
    amount = case.amount()
    cur_date = parse_date((case.txn or {}).get("txn_date")) or case.received_date
    cur_id = (case.txn or {}).get("txn_id")

    # 8.4 STOP/LOCK
    if f:
        evidence.append(ev("folio_master.csv", f"folio_no={f['folio_no']}", f"folio_flag={f['folio_flag']}"))
        if f.get("folio_flag") == "STOP_LOCK":
            reasons.append("STOP_LOCK")
            clause = case.sop(cfg["clause_stop_lock"])

    # 8.5 cash limit per first-holder PAN per AMC per FY
    is_cash = (case.payment_mode() or "").upper() == "CASH" or bool(case.extracted.is_cash)
    if is_cash and ctype in PURCHASE_TXN:
        pan = case.first_holder_pan
        folios = [x["folio_no"] for x in folio_tool.by_pan(pan, role="first") if x["amc_code"] == case.amc] if pan else []
        if f and f["folio_no"] not in folios:
            folios.append(f["folio_no"])
        prior, rows = txn_tool.cash_total(folios, cur_date, exclude_txn=cur_id)
        total = prior + (amount or 0)
        evidence.append(ev("transactions.csv", ", ".join(r["txn_id"] for r in rows) or "no prior cash",
                           f"cash this FY for PAN {pan} at {case.amc}: prior Rs {prior:,.0f} + this Rs {amount or 0:,.0f} "
                           f"= Rs {total:,.0f} (limit Rs {cfg['cash_limit_inr']:,.0f})"))
        if amount is None:
            reasons.append("CASH_LIMIT_BREACH") if prior > cfg["cash_limit_inr"] else None
        elif total > cfg["cash_limit_inr"]:
            reasons.append("CASH_LIMIT_BREACH")
            clause = case.sop(cfg["clause_cash"])

    if f and ctype and amount is not None:
        # 8.3 purchase(s) and redemption(s) each >= 25L within 14 days, same folio
        big = cfg["large_txn_inr"]
        if amount >= big and ctype in PURCHASE_TXN | {"RED"}:
            want = {"RED"} if ctype in PURCHASE_TXN else {"NEW", "ADD", "SIP_REG", "SIP", "SWI"}
            lo, hi = txn_tool.window(cur_date, cfg["large_txn_window_days"])
            hits = [r for r in txn_tool.history(f["folio_no"], lo, hi)
                    if r["txn_id"] != cur_id and r["txn_type"] in want and float(r["amount_inr"] or 0) >= big]
            if hits:
                reasons.append("REFERRAL_TRIGGER")
                clause = case.sop(cfg["clause_triggers"])
                evidence.append(ev("transactions.csv", ", ".join(h["txn_id"] for h in hits),
                                   f"Rs {amount:,.0f} {ctype} with opposite-side txn(s) >= Rs {big:,.0f} within "
                                   f"{cfg['large_txn_window_days']} days"))
        # Addendum triggers (e.g. TMF-ADD-02 A1)
        for doc, a in cfg.get("addenda", {}).items():
            if not case.policy.has(doc) or ctype != "RED" or amount < a["redemption_min_inr"]:
                continue
            since = cur_date - timedelta(days=a["window_days"])
            hits = [r for r in txn_tool.history(f["folio_no"], since, cur_date)
                    if r["txn_id"] != cur_id and r["txn_type"] in a["purchase_types"]]
            if hits:
                reasons.append("REFERRAL_TRIGGER")
                clause = f"{doc} {a['clause']}"
                evidence.append(ev("transactions.csv", ", ".join(h["txn_id"] for h in hits),
                                   f"redemption Rs {amount:,.0f} >= Rs {a['redemption_min_inr']:,.0f} within "
                                   f"{a['window_days']} days of purchase(s) "
                                   + "; ".join(f"{h['txn_type']} Rs {float(h['amount_inr']):,.0f} on {h['txn_date']}" for h in hits)))
            else:
                evidence.append(ev("transactions.csv", f"folio_no={f['folio_no']}",
                                   f"{doc} {a['clause']}: no fresh/additional purchase in the {a['window_days']} days before"))
    elif not f and not is_cash:
        return na(cid, "no folio or transaction history yet (new folio)", clause)

    reasons = list(dict.fromkeys(reasons))
    if not reasons:
        return CheckResult(check_id=cid, result="PASS", sop_clause=case.sop(cfg["clause_triggers"]), evidence=evidence)
    if "STOP_LOCK" in reasons:
        clause = case.sop(cfg["clause_stop_lock"])
    return CheckResult(check_id=cid, result="FAIL", sop_clause=clause, evidence=evidence, reason_codes=reasons)
