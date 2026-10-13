# Validus TCC Desk Compliance Agent

An HTTP service that reads one email sent to the Transaction Compliance Check (TCC) desk and proposes the desk's decision. The email can carry attachments: NEFT advices, scanned declarations, cheques, statements. The proposal covers:

- the request type
- the folio, investor and transaction it concerns
- eight compliance checks, each with evidence and its SOP clause
- one outcome, with all reason codes
- whether a Checker or the Ops Manager must approve
- a draft reply
- a full trace

The service **proposes and never acts**: it sends no email, processes nothing and issues no refunds.

- Approach and design: [APPROACH.md](APPROACH.md) · Workflow: [FUTURE_WORKFLOW.md](FUTURE_WORKFLOW.md) · Results: [ARTEFACT.md](ARTEFACT.md)
- Phase 1 analysis (expected decisions, policy diff, data issues): [docs/analysis.md](docs/analysis.md)

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/prepare_data.py                        # raw Data/ -> build/ (one command, idempotent)
uvicorn app.main:app --port 8000                      # GET /health, POST /requests
pytest                                                # 113 tests
python eval/run_eval.py                               # in-process eval; or --base-url https://<deployed>
```

`scripts/prepare_data.py` reads the read-only data room in `Data/` and writes:
- `build/tcc.db`: SQLite with the five extracts, cleaned. Raw values are kept next to normalised ones: `folio_no_raw`, `txn_date_raw`, `kra_status_code_raw`.
- `build/clauses.json`: SOP v4.1, SOP v3.2 (watermark removed) and TMF-ADD-02, split into clauses tagged with document, version, effective date and AMC scope.
- `build/data_issues.json`: one entry per data-quality finding and how the code handles it.

## Environment variables

| var | default | purpose |
|---|---|---|
| `LLM_PROVIDER` | `gemini` | `gemini` or `none` |
| `LLM_MODEL` | `gemini-3.1-flash-lite` | any Gemini model id |
| `LLM_API_KEY` | — | Gemini key (`GEMINI_API_KEY` / `GOOGLE_API_KEY` also read). Without it the service runs fully on rules + templates |
| `LLM_PRICE_IN` / `LLM_PRICE_OUT` | price table in [app/config.py](app/config.py) | USD per 1M tokens for `trace.cost_usd` |
| `LLM_TIMEOUT_S` | `30` | per-call timeout |
| `PORT` | `8000` | port in Docker / Render |

Copy `.env.example` to `.env` for local use. Keys are never committed.

## Where rules and policy live

- **[app/policy/rules.yaml](app/policy/rules.yaml)** holds every rule as data, nothing hardcoded:
  - policy documents with versions, effective dates and AMC scope
  - the 9.2 precedence and the Annexure A approval matrix
  - reason code → outcome
  - the 4.2 KYC matrix and the 24h staleness limit
  - the 5.3 exception document lists per version, and who may pay into a minor folio per version
  - COB cooling days per version, distributor rules per version
  - referral thresholds, plus addendum triggers (TMF-ADD-02 A1/A2)
  - reply banned terms
- **Version selection:** [app/tools/policy.py](app/tools/policy.py) `select()` picks the SOP in force on `received_at`, then adds an AMC addendum if one is in force. A version listed in the revision history but missing from the library (SOP v4.0, TMF-ADD-01) falls back to the previous one with a warning.
- **Clause retrieval:** `clause()` and `search()` (BM25) are filtered to the selected document and version.

**Annexure A mapping:**

| Outcome | `human_approval_required` | `approver_role` |
|---|---|---|
| PROCEED, PEND, INVALID_REQUEST | `false` | `null` |
| PROCEED_MODIFIED, REJECT | `true` | `CHECKER` |
| HOLD_AND_REFER | `true` | `OPS_MANAGER` |

SOP §3: the service-automation role "may not approve an outcome reserved to a role", so the service only ever proposes.

## API

`GET /health` returns `{"status":"ok"}`.

`POST /requests` takes `{request_id, received_at, channel, from, to, cc, subject, body, attachments:[{file_name, content_type, content_base64}]}`. It returns the contract response: `request_id`, `request_type`, `resolved`, `outcome`, `reason_codes`, all 8 `checks` with `evidence` and `sop_clause`, `human_approval_required`, `approver_role`, `draft_reply`, `trace`.

`/requests` **never returns 5xx**. On an internal error it returns:
- outcome PEND
- every check UNABLE_TO_VERIFY
- `human_approval_required: true`, `approver_role: "CHECKER"`
- an extra `error` field

Invalid JSON gets the same treatment.

### Extra response fields

| field | meaning |
|---|---|
| `extracted` | the merged S2 extraction: regex identifiers plus LLM or rule semantics |
| `extraction_method` | `llm+rules` or `rules` |
| `classification_basis` | why the request type was chosen (matched txn type / email content) |
| `policy_selection` | SOP version and addenda chosen, with reasoning and warnings |
| `decision_rationale` | each check → reason → outcome, the precedence step and the approver |
| `missing_documents` | document codes that a PEND or HOLD needs |
| `referenced_folios` | folios quoted only to identify the investor (e.g. a new folio with another AMC) |
| `attachments` | per attachment: how it was read (pdf/docx/vision/none), detected document types, account digits, holders |
| `reply_method` | `llm`, `template`, or `template (LLM draft rejected by guard)`, plus any guard problems |
| `related_clauses` | top BM25 clauses from the selected version, for human context |
| `warnings` | data issues touched, missing policy versions, duplicates, unread scans |
| `trace.latency_ms`, `trace.tool_calls`, `trace.model_calls[].purpose` | finer-grained trace |
| `error` | only on the safe fallback path |

## Deploy

- **Render:** `render.yaml` (Docker). Set `LLM_API_KEY` in the dashboard.
- **Railway / Heroku-style hosts:** `Procfile`.

The image runs `prepare_data.py` at build time and serves on `$PORT`.

## Layout

```
app/        main.py pipeline.py schemas.py llm.py trace.py config.py case.py normalise.py
            s1_intake.py s2_extract.py s3_resolve.py s6_decide.py s7_reply.py
            tools/{kra,folio,bank,txn,distributor,policy,db}.py   checks/{8 checks}.py   policy/rules.yaml
scripts/prepare_data.py   eval/{build_cases.py,run_eval.py,cases/,results/}   tests/   docs/
```
