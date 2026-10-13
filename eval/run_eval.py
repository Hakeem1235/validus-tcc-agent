"""Run the eval set against a deployed URL (or in-process) and score it.

    python eval/run_eval.py                       # in-process (FastAPI TestClient)
    python eval/run_eval.py --base-url https://...  # deployed service
    python eval/run_eval.py --label before

Writes eval/results/<UTC timestamp>[_label].json and .md
Metrics: outcome accuracy, reason-code exact / partial match, check-level accuracy, approver accuracy,
request-type accuracy, unsafe errors, over-cautious errors, median latency, median cost.
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
CASES = ROOT / "eval" / "cases"
RESULTS = ROOT / "eval" / "results"
INBOX = ROOT / "Data" / "inbox" / "requests.json"
STRICTNESS = {"PROCEED": 0, "PROCEED_MODIFIED": 1, "PEND": 2, "HOLD_AND_REFER": 3, "REJECT": 3, "INVALID_REQUEST": 3}


def load_cases() -> list[dict]:
    inbox = {r["request_id"]: r for r in json.loads(INBOX.read_text(encoding="utf-8"))}
    cases = []
    for p in sorted(CASES.glob("*.json")):
        c = json.loads(p.read_text(encoding="utf-8"))
        if "input_ref" in c:
            c["input"] = inbox[c["input_ref"].split(":", 1)[1]]
        cases.append(c)
    return cases


def poster(base_url: str | None):
    if base_url:
        import httpx

        cl = httpx.Client(base_url=base_url.rstrip("/"), timeout=120)
        return lambda payload: cl.post("/requests", json=payload)
    from fastapi.testclient import TestClient

    from app.main import app

    cl = TestClient(app)
    return lambda payload: cl.post("/requests", json=payload)


def score(case: dict, out: dict, status: int, latency: float) -> dict:
    e = case["expected"]
    got_outcome = out.get("outcome")
    exp_codes, got_codes = set(e["reason_codes"]), set(out.get("reason_codes") or [])
    checks = {c["check_id"]: c["result"] for c in out.get("checks", [])}
    check_hits, check_total, check_unsafe = 0, 0, []
    for cid, want in (e.get("checks") or {}).items():
        check_total += 1
        got = checks.get(cid)
        if got == want:
            check_hits += 1
        elif want in ("FAIL", "UNABLE_TO_VERIFY") and got == "PASS":
            check_unsafe.append(f"{cid}: expected {want}, got PASS")
    unsafe = []
    if e["outcome"] not in ("PROCEED", "PROCEED_MODIFIED") and got_outcome in ("PROCEED", "PROCEED_MODIFIED"):
        unsafe.append(f"outcome {e['outcome']} -> {got_outcome}")
    if e["outcome"] == "PROCEED_MODIFIED" and got_outcome == "PROCEED":
        unsafe.append("PROCEED_MODIFIED -> PROCEED (modification lost)")
    unsafe += check_unsafe
    over = e["outcome"] == "PROCEED" and got_outcome not in ("PROCEED", None)
    resolved_ok = all((out.get("resolved") or {}).get(k) == v for k, v in (e.get("resolved") or {}).items())
    rt = e.get("request_type")
    return {
        "id": case["id"], "description": case["description"], "tags": case.get("tags", []), "http_status": status,
        "expected_outcome": e["outcome"], "got_outcome": got_outcome,
        "outcome_ok": got_outcome == e["outcome"],
        "expected_reasons": sorted(exp_codes), "got_reasons": sorted(got_codes),
        "reasons_exact": exp_codes == got_codes,
        "reasons_partial": (exp_codes == got_codes) or bool(exp_codes & got_codes),
        "approver_ok": out.get("approver_role") == e["approver_role"] and out.get("human_approval_required") == e["human_approval_required"],
        "request_type_ok": None if rt in (None, "OTHER_OK") else out.get("request_type") == rt,
        "got_request_type": out.get("request_type"),
        "resolved_ok": resolved_ok,
        "check_hits": check_hits, "check_total": check_total,
        "check_mismatches": {cid: {"expected": want, "got": checks.get(cid)} for cid, want in (e.get("checks") or {}).items() if checks.get(cid) != want},
        "unsafe": unsafe, "over_cautious": over,
        "latency_ms": round(latency * 1000), "cost_usd": (out.get("trace") or {}).get("cost_usd", 0.0),
        "model_calls": len((out.get("trace") or {}).get("model_calls", [])),
        "failed_model_calls": sum(1 for m in (out.get("trace") or {}).get("model_calls", []) if not (m.get("input_tokens") or m.get("output_tokens"))),
        "extraction_method": out.get("extraction_method"),
        "error": out.get("error"),
    }


def summarise(rows: list[dict]) -> dict:
    n = len(rows)
    rt = [r for r in rows if r["request_type_ok"] is not None]
    ct = sum(r["check_total"] for r in rows)
    return {
        "cases": n,
        "outcome_accuracy": round(sum(r["outcome_ok"] for r in rows) / n, 4),
        "reason_exact": round(sum(r["reasons_exact"] for r in rows) / n, 4),
        "reason_partial": round(sum(r["reasons_partial"] for r in rows) / n, 4),
        "check_accuracy": round(sum(r["check_hits"] for r in rows) / ct, 4) if ct else None,
        "approver_accuracy": round(sum(r["approver_ok"] for r in rows) / n, 4),
        "request_type_accuracy": round(sum(r["request_type_ok"] for r in rt) / len(rt), 4) if rt else None,
        "resolved_accuracy": round(sum(r["resolved_ok"] for r in rows) / n, 4),
        "unsafe_errors": sum(1 for r in rows if r["unsafe"]),
        "over_cautious_errors": sum(1 for r in rows if r["over_cautious"]),
        "http_non_200": sum(1 for r in rows if r["http_status"] != 200),
        "median_latency_ms": statistics.median(r["latency_ms"] for r in rows),
        "median_cost_usd": statistics.median(r["cost_usd"] for r in rows),
        "total_cost_usd": round(sum(r["cost_usd"] for r in rows), 6),
        "llm_calls": sum(r["model_calls"] for r in rows),
        "llm_failed_calls": sum(r.get("failed_model_calls", 0) for r in rows),
        "cases_with_llm_extraction": sum(1 for r in rows if r.get("extraction_method") == "llm+rules"),
    }


def to_markdown(meta: dict, summary: dict, rows: list[dict]) -> str:
    lines = [f"# Eval run {meta['timestamp']} {meta.get('label') or ''}".rstrip(), "",
             f"Target: `{meta['target']}` · LLM: {meta.get('llm')} · cases: {summary['cases']}", "",
             "| metric | value |", "|---|---|"]
    for k, v in summary.items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "## Cases", "", "| id | expected | got | reasons exp → got | checks | unsafe | over-cautious |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        mark = "" if r["outcome_ok"] and r["reasons_exact"] else " ✗"
        lines.append(f"| {r['id']}{mark} | {r['expected_outcome']} | {r['got_outcome']} | {', '.join(r['expected_reasons']) or '—'} → "
                     f"{', '.join(r['got_reasons']) or '—'} | {r['check_hits']}/{r['check_total']} | "
                     f"{'; '.join(r['unsafe']) or ''} | {'yes' if r['over_cautious'] else ''} |")
    fails = [r for r in rows if not (r["outcome_ok"] and r["reasons_exact"]) or r["check_mismatches"]]
    if fails:
        lines += ["", "## Mismatches", ""]
        for r in fails:
            lines.append(f"- **{r['id']}** {r['description']}: outcome {r['expected_outcome']}→{r['got_outcome']}; "
                         f"reasons {r['expected_reasons']}→{r['got_reasons']}; checks {r['check_mismatches'] or 'ok'}"
                         + (f"; error {r['error']}" if r['error'] else ""))
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url")
    ap.add_argument("--label", default="")
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between requests (LLM rate limits)")
    a = ap.parse_args()
    post = poster(a.base_url)
    rows = []
    for case in load_cases():
        if a.only and case["id"] not in a.only:
            continue
        if a.delay and rows:
            time.sleep(a.delay)
        t0 = time.perf_counter()
        try:
            resp = post(case["input"])
            status, out = resp.status_code, resp.json()
        except Exception as e:
            status, out = 0, {"error": f"{type(e).__name__}: {e}"}
        rows.append(score(case, out, status, time.perf_counter() - t0))
    summary = summarise(rows)
    try:
        from app import config, llm

        llm_state = config.LLM_MODEL if llm.available() else "disabled (rules + templates)"
    except Exception:
        llm_state = "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    meta = {"timestamp": ts, "label": a.label, "target": a.base_url or "in-process", "llm": llm_state if not a.base_url else "remote"}
    RESULTS.mkdir(parents=True, exist_ok=True)
    stem = f"{ts}{'_' + a.label if a.label else ''}"
    (RESULTS / f"{stem}.json").write_text(json.dumps({"meta": meta, "summary": summary, "cases": rows}, indent=1, ensure_ascii=False), encoding="utf-8")
    (RESULTS / f"{stem}.md").write_text(to_markdown(meta, summary, rows), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    for r in rows:
        if not (r["outcome_ok"] and r["reasons_exact"]) or r["check_mismatches"] or r["unsafe"]:
            print(f"  {r['id']}: {r['expected_outcome']}->{r['got_outcome']} {r['expected_reasons']}->{r['got_reasons']} "
                  f"checks={r['check_mismatches']} unsafe={r['unsafe']} {r['error'] or ''}")
    print(f"wrote {RESULTS / stem}.json/.md")


if __name__ == "__main__":
    main()
