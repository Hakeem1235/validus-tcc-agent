# Artefact: Validus TCC Desk Compliance Agent

All numbers come from `python scripts/prepare_data.py` (`build/`) and the timestamped runs in [eval/results/](eval/results/). Design: [APPROACH.md](APPROACH.md) · Workflow: [FUTURE_WORKFLOW.md](FUTURE_WORKFLOW.md) · Setup: [README.md](README.md).

## 1. Record counts per extract (raw → loaded; no rows dropped)

| extract | rows |
|---|---|
| folio_master.csv | 83 → 83 |
| bank_mandates.csv | 105 → 105 |
| kra_kyc_snapshot.csv | 95 → 95 |
| transactions.csv | 522 → 522 |
| distributor_master.csv | 32 → 32 |
| policy clauses | 104 (SOP v4.1: 50, SOP v3.2: 50, TMF-ADD-02: 4) |

## 2. Data issues and handling

There are 44 entries in `build/data_issues.json`, grouped below. Raw files are never edited; every fix is applied in code.

| issue | where / count | handling |
|---|---|---|
| Negative units and NAV | T181000029 (units −682,982.356, NAV −0.8785), folio 40115267/30 | Flagged; units/NAV never used; warning on any request for that folio (R10) |
| Exact duplicate transactions (same folio, type, amount, date, UTR; ID differs by an inserted "5") | 4 pairs: T260200500/T260250500, T260300243/T260350243, T260700290/T260750290, **T261000021/T261050021 (pending, R06)** | Later ID marked `duplicate_of`; excluded from every aggregation; a pending match resolves to the first ID with a "process once" warning |
| Folio in non-canonical form (`40152726-27`, `4019387051`, `71178761 / 80`, trailing space) | 56 transaction rows | Normalised to `XXXXXXXX/XX`; raw kept in `folio_no_raw`; same normaliser for emails |
| Dates as DD-MM-YYYY | 53 transaction rows (e.g. T261000009, T261000044) | Parsed to ISO; raw kept in `txn_date_raw` |
| Regular plan with blank ARN/EUIN | 36 historical rows | Flagged; a pending Regular row with no ARN counts as invalid ARN (7.2) |
| KRA code lost its leading zeros (`7` for CVL `007`) | 8 PANs (e.g. URFPP\*\*04D, the minor who turned 18) | Left-padded; first digit checked against `kra_name` |
| KRA status text blank | 6 PANs (incl. HLZPR\*\*12H, code 203 = On Hold) | Status derived from the code (the code governs); eval case C05 |
| KRA text variants ("KYC VALIDATED" / "KYC Validated" / "Validated") | snapshot-wide | Case-insensitive synonym map. A code/text or agency contradiction would give UNABLE_TO_VERIFY (none in this snapshot; guard unit-tested) |
| All KRA lookups at 2026-10-09 06:00, after the R01–R10 receipt times | 95 rows | 24h staleness measured against `received_at`; a later lookup counts as fresh |
| Holder names abbreviated, salutation-prefixed or reversed vs KRA ("B. Gupta", "Mr. Yusuf Shah", "Hegde Ajay") | 17 folios | Identity by folio + PAN; tolerant name match used only to corroborate |
| Account masks of different lengths (11 vs 12 characters) | 13 of 105 mandates | Accounts matched on the last 4 digits within the folio |
| SOP v3.2 PDF "SUPERSEDED" watermark letters injected into the text | all pages | pdfplumber character filter (drops glyphs > 20pt and the grey header/footer); test asserts clean 5.4 text |
| Policy versions referenced but not supplied: SOP v4.0 (2026-06-01), TMF-ADD-01 (2026-03-01) | revision history / supersedes line | Requests in those windows use the previous version with a warning (eval C27) |

## 3. Policy documents, versions and selection

| document | version | effective | scope | source |
|---|---|---|---|---|
| TCC-SOP | 4.1 | 2026-08-01 | NMF, TMF | Validus_TCC_SOP_v4.1.docx |
| TCC-SOP | 4.0 | 2026-06-01 | NMF, TMF | *not supplied → v3.2 + warning* |
| TCC-SOP | 3.2 | 2025-01-01 | NMF, TMF | Validus_TCC_SOP_v3.2.pdf |
| TMF-ADD-02 | 02 | 2026-09-15 | TMF only, prevails | Tungabhadra_MF_Client_Addendum_TMF-ADD-02.pdf |

Selection ([tools/policy.select](app/tools/policy.py)): the latest SOP whose effective date is on or before `received_at`, plus the latest addendum for the folio's AMC in force on that date. Clause retrieval is filtered to those versions.

Key version differences encoded in [rules.yaml](app/policy/rules.yaml):
- **5.3/5.4:** grandparent payments for a minor are allowed up to ₹50k with documents under v3.2, and rejected under v4.1.
- **6.4:** 10-day COB cooling exists only under v4.1.
- **7.2:** an invalid ARN means Direct under v4.1, and stays Regular with 30 days to fix under v3.2.

## 4. Evaluation set

**44 cases** ([eval/cases/](eval/cases/)):
- R00 (CURRENT_WORKFLOW worked example)
- R01–R10 (inbox)
- 33 scenarios on real records

Expected outcomes by case:

| expected outcome | count |
|---|---|
| PROCEED | 15 |
| PEND | 13 |
| REJECT | 6 |
| HOLD_AND_REFER | 4 |
| PROCEED_MODIFIED | 3 |
| INVALID_REQUEST | 3 |

Reason codes covered:
- **All 17 codes** in SOP 9.3 are covered by the unit tests ([tests/](tests/), 113 tests, including KRA codes 01/04/05 on synthetic rows).
- **16 of 17** appear in the eval: KYC_ON_HOLD, KYC_REGISTERED_NEW_AMC, KYC_UNABLE_TO_VERIFY, TPP_NO_EXCEPTION, TPP_DOCS_MISSING, BANK_PROOF_REQUIRED, MINOR_ATTAINED_MAJORITY, COB_COOLING, HIGH_RISK_CONTACT_COB, ARN_INVALID_DIRECT, EUIN_MISSING, REFERRAL_TRIGGER, STOP_LOCK, CASH_LIMIT_BREACH, FOLIO_NOT_FOUND, FOLIO_PAN_MISMATCH.
- **KYC_REJECTED** has no record in the data room, so it is unit-tested only.
- **The 25L/14-day trigger** cannot occur in the data (no transaction ≥ ₹25L). It is unit-tested on synthetic rows, and the eval checks a ₹30L purchase does not raise a false referral (C29).

## 5. First run ("before", [20261013T065806Z_before.md](eval/results/20261013T065806Z_before.md))

| metric | before |
|---|---|
| outcome accuracy | **93.2%** (41/44) |
| reason codes exact | 88.6% |
| check-level accuracy | 92.3% |
| approver accuracy | 97.7% |
| request-type accuracy | 90.2% |
| **unsafe errors** | **1** (C24: TMF change of bank → PROCEED_MODIFIED instead of PEND BANK_PROOF_REQUIRED) |
| **over-cautious errors** | **2** (C14 joint-account proof misread → PEND; C26 v3.2 grandparent payer-KYC document not recognised → PEND) |

## 6. The one change

**Top failure class:** requests with no transaction of their own inherited an unrelated pending transaction on the same folio.
- Affected 4 of the 5 failures: C24, C25, C30, C31.
- C24 was the unsafe error: Aditi Menon's COB email picked up her pending ADD with an expired ARN, so it was classified as a purchase and proposed for PROCEED_MODIFIED.

**Change** ([s3_resolve._match_txn](app/s3_resolve.py)):
- A transaction is attached only with positive evidence: a UTR, amount or paying account that matches, or a compatible type.
- Change-of-bank and out-of-scope requests attach one only on an exact UTR.

**Follow-ups this exposed:**
- The first re-run ([fix1](eval/results/20261013T065848Z_fix1.md)) removed the unsafe error but showed that three purchases (C02 Hindi-English, C11, C21 cash) had only been classified correctly because of the stray match.
- The rule-based intent classifier was therefore changed to return "unknown", not OTHER, when it has no signal.
- Two parsing defects were also fixed: the single-line account regex (C14) and the KYC_PAYER document type (C26).

## 7. After ([20261013T065933Z_after.md](eval/results/20261013T065933Z_after.md); also over HTTP: [20261013T070020Z_http_local.md](eval/results/20261013T070020Z_http_local.md))

| metric | before | after |
|---|---|---|
| outcome accuracy | 93.2% | **100%** (44/44) |
| reason codes exact | 88.6% | 100% |
| check-level accuracy | 92.3% | 100% |
| approver accuracy | 97.7% | 100% |
| request-type accuracy | 90.2% | 100% |
| unsafe errors | 1 | **0** |
| over-cautious errors | 2 | **0** |
| HTTP non-200 | 0 | 0 |
| median latency | 8 ms | 8 ms in-process / 6 ms over local HTTP |

**Read with care:** I wrote these 44 cases alongside the rules, and the last fixes were made against them. 100% shows the regression suite passes; it does not predict accuracy on hidden requests.

## 8. Cost per request

Measured with Gemini enabled: `gemini-3.1-flash-lite`, priced at $0.25 / $1.50 per 1M input / output tokens from the [official pricing page](https://ai.google.dev/gemini-api/docs/pricing). Run: [20261013T072120Z_llm.md](eval/results/20261013T072120Z_llm.md), 44 cases, paced at 4s.

| metric | value |
|---|---|
| outcome / reason / check / approver accuracy | 100% / 100% / 100% / 100% |
| unsafe / over-cautious errors | 0 / 0 |
| cases where LLM extraction was used | 44 / 44 |
| LLM calls (extraction, vision per image, reply polish) / failed | 90 / 0 |
| **median cost per request** | **$0.000907** |
| total cost, 44 requests | $0.043 |
| median latency per request | 4.8 s (in-process; rules-only path: 8 ms) |

Notes:
- **A typical request makes two calls:** one extraction and one reply polish. Each scanned image adds a vision call: R03 cost $0.0026 and R10 $0.0017.
- **An earlier unpaced run** ([20261013T071234Z_llm.md](eval/results/20261013T071234Z_llm.md)) hit rate limits after 10 cases. Those requests fell back to rules and templates and still scored 44/44. That run is why the LLM wrapper now retries 429/503/504 with backoff.
- **`gemini-2.5-flash`** (the brief's default family) is no longer available to new keys. `gemini-3.5/3.8-flash` timed out or reported overload during testing.

## 9. Not built, fragile, next

**Not built:**
- S9 human review queue
- email sending and the persistent case log (SOP 9.5)
- policy-update assistant (S10)
- public deployment: Docker and the GitHub CLI were not available here. `Dockerfile` and `render.yaml` are written and a clean-copy production start was smoke-tested locally; the public URL step is still to do.

**Fragile:**
- Rule-based extraction of relationships, documents and intent on unusual wording when no LLM is configured.
- Scanned images without vision are typed from the file name only. The error goes towards PEND, never towards accepting.
- Single-transaction assumption per email.
- Interpretations D1–D8 in [docs/analysis.md](docs/analysis.md).

**Next:**
1. Add 200+ real labelled desk cases as a held-out set.
2. Shadow mode against makers for a month.
3. Then consider auto-sending maker-only outcomes with no warnings (see FUTURE_WORKFLOW §4).
