# Implementation plan — Validus TCC Desk Compliance Agent

Source brief: [ANTIGRAVITY_BUILD_PROMPT.md](../ANTIGRAVITY_BUILD_PROMPT.md). Phase 1 output: [analysis.md](analysis.md).

## Guiding constraints
- The LLM extracts, classifies (as a fallback) and drafts. It never decides. Checks, outcome, reason codes and approver are deterministic Python driven by `app/policy/rules.yaml`.
- No fuzzy folio matching. Any missing or conflicting identity gives INVALID_REQUEST.
- UNABLE_TO_VERIFY never passes.
- `/requests` always returns a contract-valid body. On an internal error it returns PEND with every unrun check UNABLE_TO_VERIFY, approval CHECKER and an `error` field.
- Raw `Data/` is read-only. One command builds `build/` (SQLite, clauses, data issues).
- Nothing special-cases R01–R10. Behaviour comes only from records and rules.

## Phases

| # | Phase | Deliverables | Gate |
|---|---|---|---|
| 1 | Understand (no code) | `docs/analysis.md`: expected result per R00–R10, v3.2 vs v4.1 diff, data issues, open decisions | **User review** |
| 2 | Data prep | `scripts/prepare_data.py` → `build/tcc.db`, `build/clauses.json`, `build/data_issues.json`, printed counts. Normalises folio formats, DD-MM-YYYY dates, zero-pads KRA codes and derives KRA status from the code. Flags duplicates and negatives. Cleans the v3.2 PDF watermark by filtering characters | Idempotent rerun produces identical output |
| 3 | Tools + checks + decide | `app/tools/*`, `app/checks/*`, `app/s6_decide.py`, `rules.yaml`, pytest per rule branch, including UNABLE_TO_VERIFY paths | `pytest` green |
| 4 | LLM layers | `app/llm.py` (Gemini default, real token usage, price table), S1 intake (pdfplumber / python-docx / vision), S2 regex + JSON extraction (retry once), classifier, S7 reply plus banned-word guard and template fallback, S8 trace | Works offline with an LLM stub. With a key, uses real calls |
| 5 | API | FastAPI `/health` and `/requests`, contract model, never-500 guard. Run R01–R10 and diff against analysis.md | 10/10 match, or each difference explained |
| 6 | Eval | ≥30 cases (R00–R10 plus ≥20 synthetic, covering every reason code in 9.3 and the listed edge cases), `eval/run_eval.py` with unsafe and over-cautious metrics. Commit "before", fix the top failure class, commit "after" | Zero unsafe errors, or each one explained |
| 7 | Deploy | Dockerfile, render.yaml, smoke test, eval against the public URL | Public `/health` + `/requests` |
| 8 | Docs | README, FUTURE_WORKFLOW.md (from template), APPROACH.md, ARTEFACT.md/.html (real numbers only) | — |

## Key design decisions (details in analysis.md §5)
1. **KYC On Hold / Rejected on a purchase or SIP gives REJECT.** The SOP says "not accepted", the money has been received, and 9.1 defines REJECT as "not acceptable… refund". On a redemption it gives HOLD_AND_REFER, because the 4.2 matrix says "refer to Operations Manager".
2. **KRA staleness reference = the request's `received_at`.** The snapshot is "the latest". A lookup taken after receipt (the extract is dated 2026-10-09 06:00) counts as fresh. A lookup more than 24h before `received_at` gives UNABLE_TO_VERIFY.
3. **Policy selection by date.** v4.1 applies from 2026-08-01. v3.2 applies from 2025-01-01 to 2026-07-31. v4.0 (2026-06-01) is not in the data room, so v3.2 is used with a warning; per Annex D, v4.0 changed only Annex A and the automation role. TMF-ADD-02 is added for TMF when `received_at` ≥ 2026-09-15. TMF-ADD-01 is not in the data room, so the system warns.
4. **The payer is identified by account number**, never by name. Names are matched tolerantly (salutations, initials, order) and only as a corroborating signal, using both the folio-master name and the KRA name for the PAN.
5. **Duplicates are flagged and not deleted.** Aggregations (cash per FY, 25L/14-day and 5L/30-day windows) de-duplicate on (folio, utr, amount, date, type). A request matching two identical pending rows resolves to the lowest txn_id and adds a warning.
6. **Check scope.** BANK_MANDATE and COB_COOLING apply to redemptions and COB only. The pay-in source for purchases belongs to THIRD_PARTY_PAYMENT, including the 5.6 proof for an unregistered own account. This matches the worked example (step 5 → 5.1, step 7 "payout checks N/A").

## Repository layout (target)
```
app/ main.py schemas.py pipeline.py llm.py trace.py s1_intake.py s2_extract.py s3_resolve.py s4_policy.py
     s6_decide.py s7_reply.py tools/{kra,folio,bank,txn,distributor,policy}.py
     checks/{kyc,tpp,bank_mandate,cob,distributor,minor,referral,identity}.py policy/rules.yaml
scripts/prepare_data.py   eval/{cases,results,run_eval.py}   tests/   docs/
Dockerfile render.yaml requirements.txt .env.example README.md FUTURE_WORKFLOW.md APPROACH.md ARTEFACT.md ARTEFACT.html
```
