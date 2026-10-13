# Phase 1 analysis: expected decisions, policy diff, data issues

Sources: `Data/CURRENT_WORKFLOW.docx`, SOP v4.1 (docx), SOP v3.2 (pdf), TMF-ADD-02 (pdf), `DATA_DICTIONARY.md`, R01–R10 (docx + attachments + `requests.json`) and the five extracts (as of 2026-10-09).
Check abbreviations: **KYC** KYC_STATUS · **TPP** THIRD_PARTY_PAYMENT · **BANK** BANK_MANDATE · **COB** COB_COOLING · **DIST** DISTRIBUTOR_CODE · **MINOR** MINOR_RULES · **REF** REFERRAL · **ID** FOLIO_IDENTITY. Results: P=PASS, F=FAIL, NA=NOT_APPLICABLE, U=UNABLE_TO_VERIFY.

## 1. Summary

| Req | request_type | folio / amc | txn | outcome | reason_codes | approver |
|---|---|---|---|---|---|---|
| R00 | ADDITIONAL_PURCHASE | 40166450/93 NMF | T260900518 | PROCEED | — | none |
| R01 | SIP_REGISTRATION | 40118823/23 NMF | T261000007 | PROCEED | — | none |
| R02 | ADDITIONAL_PURCHASE | 40173612/78 NMF (minor) | T261000009 | REJECT | TPP_NO_EXCEPTION | CHECKER |
| R03 | SIP_REGISTRATION | 71138631/21 TMF | T261000011 | PEND | TPP_DOCS_MISSING | none |
| R04 | ADDITIONAL_PURCHASE | 40120238/73 NMF | T261000013 | REJECT | KYC_ON_HOLD | CHECKER |
| R05 | NEW_FOLIO_PURCHASE | null / TMF (PAN via NMF 40104822/68) | null | PEND | KYC_REGISTERED_NEW_AMC | none |
| R06 | ADDITIONAL_PURCHASE | 40159954/10 NMF | T261000021 (dup T261050021) | PROCEED | — | none |
| R07 | ADDITIONAL_PURCHASE | 40112665/21 NMF (AS) | T261000022 | REJECT | TPP_NO_EXCEPTION | CHECKER |
| R08 | ADDITIONAL_PURCHASE | 71167297/25 TMF | T261000025 | PROCEED_MODIFIED | ARN_INVALID_DIRECT | CHECKER |
| R09 | ADDITIONAL_PURCHASE | 40131574/17 NMF | T261000028 | PEND | KYC_UNABLE_TO_VERIFY | none |
| R10 | REDEMPTION | 40115267/30 NMF | T261000031 | HOLD_AND_REFER | HIGH_RISK_CONTACT_COB, COB_COOLING, BANK_PROOF_REQUIRED | OPS_MANAGER |

Policy: every request R00–R10 was received on or after 2026-08-01, so **SOP v4.1** applies. R03 and R08 are TMF folios received on or after 2026-09-15, so **TMF-ADD-02** is added. R05 is a new TMF folio, so TMF-ADD-02 is added there too.

## 2. Per-request reasoning

### R00: worked example (Kedia Wealth, Ravi Kumar Bhat), received 2026-09-22 11:05
- Folio `4016645093` → 40166450/93, NMF, SI, PAN YBZPB\*\*44W, flag NONE. Txn T260900518 (ADD ₹75,000, NEFT, UTR VNDYN2609229076583) matches on UTR. The row now reads PROCESSED because the case is closed, so the resolver must accept a non-pending row on an exact UTR match and add a warning.
- KYC P: 307 = CAMS / Validated, v4.1 4.2. TPP P: remitter a/c XXXXXXXX5475 is registered and VALIDATED, holders "RAVI KUMAR BHAT;SHOBHA BHAT", first holder is a holder (5.1). DIST P: ARN-145023 ACTIVE to 2028-03-31, empanelled NMF; EUIN E289730 belongs to this ARN, valid to 2028-03-31 (7.1). BANK NA, COB NA (not a redemption). MINOR NA. REF P (no STOP_LOCK, no cash, no ≥25L pair). ID P.
- **PROCEED**, no approval.

### R01: SIP registration, Arjun Nair
- `40118823/23` NMF SI, PAN GDHPN\*\*79U. Pending T261000007 SIP_REG ₹10,000 NACH from XXXXXXXX4908, REGULAR, ARN-145023/E289730.
- KYC P (307). TPP P: NACH account 4908 is the registered VALIDATED mandate, holder ARJUN NAIR (5.6 NACH row, 5.1). DIST P (ARN active, NMF empanelled, EUIN belongs to the ARN and is valid). REF P. Others NA. ID P.
- **PROCEED**, no approval. The reply goes to the distributor (sender).

### R02: grandfather paying into a minor folio
- `4017361278` → 40173612/78, minor Ishaan (DOB 2015-03-02, aged 11), guardian Rohan (FATHER). Pending T261000009 ADD ₹40,000 NEFT from **XXXXXXXX9641**, remitter "VASANT G KULKARNI", UTR KNKMH2610065981253 (matches the email and the NEFT advice). The txn date is written `06-10-2026`, which is a data issue.
- The only registered account is XXXXXXXX1198 (ISHAAN KULKARNI;ROHAN KULKARNI). 9641 is not registered. The NEFT advice shows remitter VASANT GOVIND KULKARNI, who is not the minor, a parent or the guardian.
- TPP **F**: v4.1 5.4 says a payment from any other relative, including a grandparent, is a third-party payment and is not covered by 5.3. Per 5.7 → TPP_NO_EXCEPTION, refund to the remitting account. The sender's claim ("grandparents allowed up to ₹50,000") quotes the superseded v3.2 5.3/5.4.
- KYC P: the minor's PAN RRBPK\*\*06M has 007 = CVL Validated (4.1, minor's KYC). The guardian is also Validated. MINOR P (not yet 18). DIST NA (Direct). REF P. ID P.
- **REJECT [TPP_NO_EXCEPTION]**, CHECKER.

### R03: employer payroll SIP (TMF)
- `71138631 / 21` TMF, Sandeep Yadav, PAN BARPY\*\*69Z. Pending T261000011 SIP_REG ₹5,000 NEFT from XXXXXXX6073, "DECCAN POLYMERS PVT LTD", DIRECT.
- TPP **F (exception, docs missing)**: the payer is the employer, which is the 5.3 "employer paying for employee(s)" exception. The documents needed are:
  - Third Party Payment Declaration: **present** (scan, Employer ticked, signed).
  - Employer declaration on letterhead: **present** (payroll letter on company letterhead).
  - List of employees with code, PAN and KYC: **missing**. The email says it will be "shared separately". The letter lists it as an enclosure but it is not attached, and its box on the form is unticked.
  - KYC acknowledgement of the investor: **missing** (unticked, not attached).
  - KYC acknowledgement of the employer: **missing**. It is ticked on the form but not enclosed, and per 5.7 a ticked box is not an enclosure.
  - Result: TPP_DOCS_MISSING. Per 5.7 the reply lists each missing document.
- KYC P (507 KFIN Validated). The employer RLVCL\*\*88Y is Validated in the KRA, but the SOP needs the acknowledgement document itself. DIST NA (Direct). REF P: TMF-ADD-02 A1 covers redemptions only. MINOR NA. ID P (the folio on the form matches).
- **PEND [TPP_DOCS_MISSING]**, no approval.

### R04: KYC On Hold, additional purchase
- `40120238/73` NMF, Farhan Siddiqui, PAN UXFPS\*\*09F. KRA code **303 = CAMS / On Hold**, text "ON HOLD" (consistent). Pending T261000013 ADD ₹1,50,000 UPI from XXXXXXXX6855.
- KYC **F**: 4.2 matrix, On Hold × additional purchase = "Do not accept (4.4)" → KYC_ON_HOLD. TPP P: UPI debit account 6855 is registered and VALIDATED in the investor's name (5.6 UPI row). DIST NA (Direct). REF P.
- **REJECT [KYC_ON_HOLD]**, CHECKER (see decision D1). Per 4.4 the reply only asks him to update his KYC with a KRA or intermediary and gives no other reason. It also answers his SMS question in those terms.

### R05: new TMF folio, KYC Registered
- No folio is quoted for TMF. The email cites NMF folio 40104822/68 (Lakshmi Venkataraman, PAN XZDPV\*\*82H), and the name matches. `folio.by_pan` shows the PAN holds **no TMF folio**. KRA **502 = KFIN / KYC REGISTERED**.
- KYC **F**: 4.3, a new folio with an AMC where the investor holds no folio → KYC_REGISTERED_NEW_AMC. Ask for fresh (Aadhaar-based) KYC.
- TPP NA (no payment yet; she asks where to pay). DIST NA (Direct). BANK/COB/MINOR NA. REF NA (no transaction and no TMF folio to be locked). ID P (investor identified by the referenced folio, the PAN and a name match; no conflict).
- resolved: folio_no **null**, amc_code TMF, PAN XZDPV\*\*82H, txn null (decision D3).
- **PEND [KYC_REGISTERED_NEW_AMC]**, no approval. The reply can confirm that her existing NMF ELSS SIP is not affected by this request.

### R06: own unregistered account with a bank statement
- `40159954/10` NMF, Neha Agarwal, PAN RBKPA\*\*61M. There are **two identical pending rows**, T261000021 and T261050021 (same UTR VNDYN2610073906590, ₹2,00,000, same date). This is a data issue: resolve to T261000021 and add a warning so the duplicate is not processed twice.
- Remitter account XXXXXXXX5879 is not registered; the only registered account is XXXXXXXX0496 Aravali. The attached bank statement shows **holder NEHA AGARWAL, a/c XXXXXXXX5879, debit NEFT-VNDYN2610073906590 ₹2,00,000 on 07/10/2026**. The account matches the bank feed and the UTR matches the txn.
- TPP P: 5.1 says the first holder's own account is not a third-party payment, and 5.6 is satisfied because a statement showing the debit is enclosed. KYC P (307). DIST NA. REF P.
- **PROCEED**, no approval. Warnings: duplicate pending row, and the account is not registered (the investor intends to add it).

### R07: second holder pays for a joint folio
- `40112665/21` NMF, AS. First holder Priya Raghavan (ERUPR\*\*36W); second holder Raghavan Srinivasan (SVYPS\*\*57A). Pending T261000022 ADD ₹1,20,000 NEFT from **XXXXXXXX9241**, "RAGHAVAN SRINIVASAN". 9241 is not registered; the only mandate is 4961 (PRIYA RAGHAVAN).
- TPP **F**: 5.1 says the first holder must be a holder of the paying account. The sender states it is "my savings account" (the second holder's), and the bank feed name is his. A spouse or second holder is not a 5.3 exception → TPP_NO_EXCEPTION, refund. KYC P (first holder 307).
- **REJECT [TPP_NO_EXCEPTION]**, CHECKER.

### R08: expired ARN (TMF)
- `71167297 / 25` TMF, Aditi Menon. The email says "fresh purchase", but the folio exists (opened 2024, prior NEW T240500024) and pending T261000025 has txn_type **ADD**. The matched txn type wins, so the type is ADDITIONAL_PURCHASE.
- DIST **F**: ARN-207791 (Sunrise Finserv) EXPIRED on 2026-08-14, before the request date 2026-10-08. "Renewal in process" does not make it valid. EUIN E424168 also expired on 2026-08-14. Per v4.1 7.2 the purchase is processed in Direct → ARN_INVALID_DIRECT (PROCEED_MODIFIED).
- KYC P (007 CVL). TPP P: RTGS from registered VALIDATED 5959, ADITI MENON. REF P: A1 does not apply to purchases, and ₹3L < 25L.
- **PROCEED_MODIFIED [ARN_INVALID_DIRECT]**, CHECKER. The reply tells the distributor the purchase will go into the Direct plan and no commission is payable.

### R09: KRA service not reachable
- `40131574-17` → 40131574/17 (hyphen format), Kiran Reddy, PAN HMAPR\*\*16L. KRA code **399 = CAMS / web service not reachable**. Pending T261000028 ADD ₹75,000 IMPS from registered 4455.
- KYC **U** → KYC_UNABLE_TO_VERIFY (4.5, never a pass). TPP P. DIST NA. REF P.
- **PEND [KYC_UNABLE_TO_VERIFY]**, no approval. The reply says the request is being re-checked; no document is required from the investor.

### R10: redemption + COB + contact change
- `40115267 / 30` NMF, Sunita Iyer, PAN MYGPI\*\*72Y, **contact_last_changed_on 2026-10-02**. Pending T261000031 RED ₹8,50,000.
- Mandates: XXXXXXXX5300 Satpura VALIDATED, default. XXXXXXXX6801 Konkan **PENDING_VALIDATION**, COB received **2026-10-04**. The attachments are the COB form (existing-account proof "not available (account closed)") and a cancelled cheque showing a/c 991182156801 and SUNITA IYER, IFSC KNKM0266850, which matches the new account.
- COB **F**: the COB was received 4 days before the redemption (within 10), so the payout is held until 2026-10-14 (6.4, COB_COOLING). The contact changed 2 days before the COB (within 30) and the redemption falls inside the cooling period, so the request is high risk (6.5, HIGH_RISK_CONTACT_COB → HOLD_AND_REFER).
- BANK **F**: the requested account 6801 is PENDING_VALIDATION, so it is disregarded and never paid (6.2, 6.4). The COB lacks proof of the existing account, and there is no evidence of in-person verification (6.3) → BANK_PROOF_REQUIRED.
- KYC P (007). REF P: no ≥25L purchase within 14 days (8.3); NMF, so A1 does not apply. MINOR/TPP/DIST NA. ID P.
- **HOLD_AND_REFER [HIGH_RISK_CONTACT_COB, COB_COOLING, BANK_PROOF_REQUIRED]**, OPS_MANAGER. The reply only says the request is under processing and gives the next update date (Annex B, 8.6). It never mentions a referral, compliance or suspicion.
- Folio data issue: T181000029 (the NEW purchase on this folio) has negative units and NAV. Holdings are not computed, so the system flags it and adds a warning.

### Other pending items in the register (seeds for hidden-test types, used in the Phase 6 eval)
| txn | situation | expected |
|---|---|---|
| T261000010 40129212/58 | Mother (guardian) pays the minor's folio from unregistered a/c 9986 | PROCEED if proof shows the account is the mother's (5.4 + 5.6). Otherwise PEND BANK_PROOF_REQUIRED |
| T261000026 71102387/42 | ARN-118460 ACTIVE but **not empanelled with TMF** | PROCEED_MODIFIED ARN_INVALID_DIRECT |
| T261000033 40177095/71 | Redemption 17 days after the COB (09-20) | PROCEED (outside the 10-day cooling period) |
| T261000049 71173574/68 | TMF cash ₹35,000 + ₹20,000 cash in May 2026 (same FY) = ₹55,000 | REJECT CASH_LIMIT_BREACH |
| T261000020 40136263/98 | Net banking from the registered account | PROCEED |
| T261000035 71184287/96 | TMF redemption ₹6L, 18 days after an ADD of ₹6.2L | HOLD_AND_REFER REFERRAL_TRIGGER (A1) |
| T261000044 40149414/17 | SIP instalment; the minor (DOB 2008-09-15) turned 18 on 2026-09-15 | PEND MINOR_ATTAINED_MAJORITY |
| T261000046 40161537/29 | Redemption on a STOP_LOCK folio | HOLD_AND_REFER STOP_LOCK |

## 3. SOP v3.2 vs v4.1

| Clause | v3.2 (eff. 2025-01-01, superseded) | v4.1 (eff. 2026-08-01) | Effect on the engine |
|---|---|---|---|
| 5.3 table | Includes "Parent, grandparent or related person paying for a minor, up to ₹50,000 per purchase/SIP instalment: TPP declaration stating the relationship + payer KYC" | Row removed | Under v3.2 a grandparent payment ≤ ₹50k with docs → PROCEED (missing docs → TPP_DOCS_MISSING; > ₹50k → TPP_NO_EXCEPTION) |
| 5.4 | Minor's own account or joint minor+guardian account accepted. Parent/grandparent/related person accepted up to ₹50k under 5.3 | Minor, **parent or legal guardian**, or joint minor + parent/guardian are not TPP. **Any other relative, including a grandparent, is TPP and not covered by 5.3.** Redemption proceeds go only to the minor's verified account | Grandparent → REJECT TPP_NO_EXCEPTION. A parent's account is not TPP |
| 6.4 | COB received **with** a redemption is processed separately, and the redemption is paid to the existing registered account. No cooling period | Cooling of **10 calendar days** from COB receipt when the COB arrives ≤10 days before or with the redemption. Payout goes to the account VALIDATED at that time. Never to PENDING_VALIDATION | COB_COOLING exists only under v4.1 |
| 7.2 | Expired/invalid ARN: processed in **Regular**; reprocessed into Direct if no valid ARN within 30 days | Invalid ARN (expired, suspended, cancelled, terminated, deceased, IA-non-compliant, debarred, not in AMFI, **not empanelled with the AMC**): processed **in Direct**, no commission → PROCEED_MODIFIED ARN_INVALID_DIRECT | Under v3.2 → PROCEED (Regular) with a follow-up warning. ARN_INVALID_DIRECT is not raised (decision D5) |
| 5.5, 8.4, 8.5 | Same rules | "Restated" (wording only) | No change |
| Annex A / §3 | Same approval matrix and automation role | v4.0 revised Annex A; v4.1 text is identical to v3.2's | No change |
| Annex D | Lists up to 3.2 | Adds 4.0 (2026-06-01) and 4.1 | v4.0 is **not in the data room** (decision D4) |

TMF-ADD-02 (from 2026-09-15, TMF only, prevails): **A1** a redemption of ≥ ₹5,00,000 within 30 calendar days of a NEW or ADD purchase (any scheme, same folio; SIP instalments excluded) → HOLD_AND_REFER REFERRAL_TRIGGER. **A2** every TMF COB needs proof of the existing account; in-person verification is not accepted. **A3** routing contact (included in the trace, not in the reply). It supersedes TMF-ADD-01 (from 2026-03-01), which is not in the data room.

## 4. Data issues (each will be logged in `build/data_issues.json` and handled in code; raw files untouched)

| # | File | Issue | Example | Handling |
|---|---|---|---|---|
| 1 | transactions | Negative units and NAV | T181000029 (units −682982.356, NAV −0.8785) | Flag. Exclude from unit/NAV use. Amount still counts in history windows. Warn when that folio is touched |
| 2 | transactions | Exact duplicate rows with the same UTR, amount and date; IDs differ by an inserted "5" | T261000021/T261050021 (pending), T260200500/T260250500, T260300243/T260350243, T260700290/T260750290 | Flag. De-duplicate in aggregations. Resolve a pending match to the lowest id and warn |
| 3 | transactions | Folio written in non-canonical forms: `40152726-27`, `4019387051`, `71178761 / 80`, trailing space | ~60 rows (e.g. T261000026 `71102387-42`, T260900019 `40104822/68 `) | Normalise (strip non-digits, 10 digits → `XXXXXXXX/XX`). Keep the raw value |
| 4 | transactions | Dates as DD-MM-YYYY | T261000009 `06-10-2026`, T261000044, T260500002 … (~50 rows) | Parse both formats into ISO. Keep the raw value |
| 5 | transactions | Regular plan with blank ARN/EUIN | 36 rows (e.g. T251000054) | Flag. A pending Regular row with no ARN gives an invalid ARN under 7.2 |
| 6 | kra_kyc_snapshot | Status code missing the leading zeros (`7` instead of `007`) | 8 CVL rows, e.g. URFPP\*\*04D | Left-pad to 3 digits. Confirm the first digit matches kra_name (0 = CVL) |
| 7 | kra_kyc_snapshot | Blank status text | JAHPD\*\*63H (007), HLZPR\*\*12H (203), JUCPD\*\*61Y (207), 3 × 507 | Derive the status from the code (the code governs). Log it |
| 8 | kra_kyc_snapshot | Inconsistent text ("KYC Validated" / "KYC VALIDATED" / "Validated") | SVYPS\*\*57A "Validated" | Case-insensitive synonym map. A true code/text contradiction gives UNABLE_TO_VERIFY (none found in this snapshot; the guard is kept for hidden data) |
| 9 | kra_kyc_snapshot | All lookups 2026-10-09 06:00, after the R01–R10 receipt dates | — | Staleness is measured against received_at (D2) |
| 10 | folio_master | Holder names abbreviated or prefixed with a salutation or reversed vs KRA and bank | `B. Gupta` vs BHAVANA GUPTA, `Mr. Yusuf Shah`, `Hegde Ajay` (17 folios) | Never identify by name. A tolerant name matcher (salutations, initials, order) uses folio name ∪ KRA name, and only to corroborate the account match |
| 11 | bank_mandates | Account masks of different length (`XXXXXXX3121` vs `XXXXXXXX8169`) | 40177095/71 | Match on the last 4 digits within the folio |
| 12 | inbox | Email folio formats `4011882323`, `40115267 / 30`, `40131574-17` | R01, R10, R09 | Same normaliser as #3 |
| 13 | policies | v3.2 PDF watermark ("SUPERSEDED") letters injected into the text (`AMCsS`, `paymenRts`, lone letters) | — | Extract with a pdfplumber character filter (drop watermark-sized or rotated characters). Verify the clause texts after cleaning |

## 5. Decisions for your review

- **D1. KYC On Hold/Rejected on a purchase or SIP → REJECT, not PEND.** 4.2 says "Do not accept"; 4.4 says "not accepted". Money has already been received. 9.1 defines REJECT as "not acceptable under this procedure; refund where money was received", while PEND is for "a document, a re-check or a period", and an On Hold status is not a re-check cycle. On a redemption, 4.2 says "Refer to Operations Manager" → HOLD_AND_REFER with reason KYC_ON_HOLD/KYC_REJECTED, approver OPS_MANAGER. For a new folio with no money received, it is still REJECT (do not accept).
- **D2. KRA staleness reference = `received_at`.** Age = received_at − last_checked_at. If age > 24h → UNABLE_TO_VERIFY. A negative age (a later snapshot) counts as fresh. Using wall-clock time would make every request UTV, because the extract is static.
- **D3. R05 `resolved.folio_no = null`.** The request is for a new TMF folio, and the NMF folio only identifies the investor. It is recorded in `extracted.referenced_folio`. amc_code = TMF (the target AMC).
- **D4. Missing documents.** For received_at in [2026-06-01, 2026-08-01), v4.0 governs but is not provided. The system applies v3.2 rules, adds `warnings: ["SOP v4.0 not in data room…"]`, and `documents_used` lists v3.2. Likewise, a TMF request between 2026-03-01 and 2026-09-14 adds a warning that TMF-ADD-01 is missing. Before 2025-01-01 → v3.2 + warning.
- **D5. Invalid ARN under v3.2 → PROCEED (Regular)** with warning "valid ARN required within 30 days, else reprocessed to Direct", and DIST = FAIL citing v3.2 7.2. The v3.2 reason-code list has no code for this, so none is recorded. **Tell me if you'd rather use PROCEED_MODIFIED.**
- **D6. Hold replies** follow Annex B strictly: the processing status and the next update date only (cooling end + 1 working day for COB holds; otherwise +3 working days). No document requests in hold replies, even when BANK_PROOF_REQUIRED is also present. The document request is placed in `extracted`/`warnings` for the Ops Manager.
- **D7. EUIN validity.** A EUIN that does not belong to the quoted ARN, or that has expired, is treated like a blank EUIN → EUIN_MISSING (proceed Regular, follow up). The ARN itself is still validated separately.
- **D8. Cash rule.** The total is the sum of CASH purchases (PROCESSED + the current request; REJECTED/REVERSED excluded; de-duplicated) per first-holder PAN per AMC per FY. If it exceeds ₹50,000 → REJECT CASH_LIMIT_BREACH.
