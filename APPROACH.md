# Approach

The service automates the TCC maker's routine: open five screens and the rulebook, decide, write a reply. Code decides; the model only reads and writes text; a person approves wherever the SOP reserves the decision. Workflow: [FUTURE_WORKFLOW.md](FUTURE_WORKFLOW.md). Expected decisions and data findings: [docs/analysis.md](docs/analysis.md). Numbers: [ARTEFACT.md](ARTEFACT.md). Setup: [README.md](README.md).

## A. Request types handled, and not

**Handled:**
- New-folio purchase, additional purchase, SIP registration and SIP instalment
- Redemption, including payout account and change of bank in the same email
- Standalone change of bank

The request type is taken from the matched register transaction when there is one, and from the email otherwise ([s2_extract.classify](app/s2_extract.py)). An email that says "fresh purchase" on an existing folio with a pending ADD is therefore an additional purchase.

**Not handled:**
- Switches (SWI/SWO), exchange/demat transactions, transmission and nomination servicing (SOP 2.2)
- Any query that is not a transaction. These become `OTHER` → PEND for a person, never PROCEED ([s6_decide](app/s6_decide.py)).
- More than one transaction in a single email: only one transaction is proposed, and the rest go to warnings.

## B. Agent design

**Code vs model.** The LLM ([app/llm.py](app/llm.py)) does exactly three jobs:
1. Transcribing images and scanned PDFs ([s1_intake._vision](app/s1_intake.py))
2. Extracting intent, relationships, roles and enclosed documents ([s2_extract.llm_extract](app/s2_extract.py))
3. Polishing a reply that a deterministic template has already written ([s7_reply.draft](app/s7_reply.py))

Everything else is code:
- **Identifiers** come from regex over the literal text. A model-supplied folio, PAN or UTR that does not appear in the text is discarded ([merge](app/s2_extract.py)).
- **Identity** is exact folio lookup plus PAN, name and attachment cross-checks. There is no fuzzy matching ([s3_resolve](app/s3_resolve.py)).
- **Checks** are the eight pure functions in [app/checks/](app/checks/__init__.py).
- **Outcome** follows 9.2 precedence and **approver** follows Annexure A ([s6_decide](app/s6_decide.py)).

Every threshold, matrix, document list and clause reference is versioned data in [rules.yaml](app/policy/rules.yaml).

**Payer identification** uses the paying account, never the name ([checks/tpp.py](app/checks/tpp.py)):
1. Remitter account digits are matched against this folio's mandates, then against mandates on other folios of the same investor.
2. If the account is unregistered, the holder comes from an enclosed 5.6 proof (statement or transfer advice).
3. Names are only matched tolerantly to corroborate, handling initials, salutations and order ([normalise.names_match](app/normalise.py)).

**Version selection** is deterministic ([tools/policy.select](app/tools/policy.py)):
- the SOP in force on `received_at`
- plus the AMC addendum in force on that date
- if a version is listed in the revision history but missing from the library (SOP v4.0, TMF-ADD-01), the previous version is applied with a warning

Clause retrieval (exact clause and BM25 search) is filtered to the selected versions.

**Failure path:**
- An unavailable, stale (>24h before receipt), contradictory or missing source gives UNABLE_TO_VERIFY, which blocks PROCEED ([checks/kyc.py](app/checks/kyc.py), [decide](app/s6_decide.py)).
- An exception inside a check gives UTV for that check.
- LLM extraction that is invalid twice gives the safe fallback.
- Any unhandled error gives the safe fallback, never a 500 ([pipeline.process_safely](app/pipeline.py), [main.py](app/main.py)).

The safe fallback is PEND, all checks UNABLE_TO_VERIFY, CHECKER, and an `error` field. Without an LLM key the whole service runs on rules and templates, and the trace says so.

## C. Data and grounding

**Data prep.** [scripts/prepare_data.py](scripts/prepare_data.py) builds SQLite, clause JSON and a data-issue log from the read-only data room in one idempotent command. It:
- normalises roughly 60 non-canonical folio strings and DD-MM-YYYY dates
- left-pads KRA codes that lost their leading zeros (`7` → `007`) and derives KRA status from the code
- flags duplicate transactions (de-duplicated in every aggregation) and the negative units/NAV row
- strips the "SUPERSEDED" watermark from SOP v3.2 with a character-size filter

**Grounding.** Every check returns evidence as `{source file, row key, value}` and a clause in the form `TCC-SOP v4.1 5.4` or `TMF-ADD-02 A1`. The trace lists the documents and versions used ([trace.py](app/trace.py)). Replies quote the folio and state reasons in SOP terms.

**Reply guard.** The guard ([s7_reply.guard](app/s7_reply.py)) rejects any draft that:
- mentions referral, suspicion, compliance or reporting on held or pended cases (8.6)
- gives any reason other than KYC on a KYC on-hold reply (4.4)
- claims the transaction "has been processed"
- drops a number from the template

## D. Evaluation

**The eval set** has 44 cases ([eval/build_cases.py](eval/build_cases.py)):
- R00 (the worked example) and R01–R10
- 33 written scenarios on real records, covering:
  - every reachable reason code
  - rewording and Hindi-English mixes
  - a folio typo and a PAN conflict
  - KRA 99 and On Hold derived from a blank status text
  - Registered with a new AMC and with an AMC already held
  - On Hold on a purchase vs a redemption
  - grandparent and parent paying into a minor folio
  - employer payroll with all documents and with one missing
  - a joint account and an own unregistered account with and without proof
  - a minor who has turned 18
  - COB cooling, inside and outside the window
  - an ARN not empanelled with the AMC, a suspended ARN and a blank EUIN
  - STOP_LOCK and the cash FY aggregate
  - TMF A1, and the same pattern on NMF as a control
  - TMF COB without existing-account proof
  - pre-August requests (v3.2 and the missing v4.0)
  - an out-of-scope request

**The runner** ([eval/run_eval.py](eval/run_eval.py)) works in-process or against any URL. It scores outcome, reason codes (exact and partial), checks, approver and request type, plus unsafe errors (a stricter outcome expected but PROCEED or PROCEED_MODIFIED given, or a FAIL/UTV reported as PASS) and over-cautious errors. Each run writes timestamped JSON and Markdown to [eval/results/](eval/results/). There are also 113 unit and API tests in [tests/](tests/); synthetic rows such as the 25L/14-day window, A1 timing and stale or conflicting KRA rows are used in tests only.

**Bar before reducing human review** of an outcome class:
- zero unsafe errors on a held-out set of at least 200 real, labelled desk cases
- outcome accuracy ≥ 98%
- a shadow month in which checker overrides on that class are below 1%

The current 44 cases were written by the same person who wrote the rules, so they are a regression suite, not proof.

## E. Risks and trade-offs

- **Rules extraction without an LLM is brittle** for unusual wording. With a key, LLM extraction is added, but identifiers stay regex-anchored.
- **Image documents without vision** are typed from the file name only. Ticked boxes are never treated as enclosures, so this errs towards PEND.
- **Interpretations (D1–D8 in [analysis.md](docs/analysis.md))** are recorded in rules.yaml, for example On Hold purchase → REJECT and KRA staleness measured against `received_at`. They are easy to flip.
- **The 25L/14-day trigger** cannot occur in the provided data. It is unit-tested on synthetic rows.
- **Reply polish** is constrained by the guard. A rejected draft falls back to the template, trading fluency for safety.
- **Not built:** the S9 review queue, email sending, the persistent case log, and the policy-update assistant. These are designed in [FUTURE_WORKFLOW.md](FUTURE_WORKFLOW.md).
