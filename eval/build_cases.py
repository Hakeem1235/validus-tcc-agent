"""Generate eval/cases/*.json: R00 (worked example), R01-R10 (inbox) and own scenario cases.

Each case: {id, description, tags, input (API payload) | input_ref ("inbox:R0x"), expected{...}}.
Expected values are reasoned from the SOP and the data room (see docs/analysis.md), not from system output.
Own cases use only real records from Data/ (the deployed service has no test fixtures), with emails and
text attachments written for the scenario.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

OUT = Path(__file__).parent / "cases"


def att(name: str, text: str, ctype: str = "text/plain") -> dict:
    return {"file_name": name, "content_type": ctype, "content_base64": base64.b64encode(text.encode()).decode()}


def req(rid, received, sender, subject, body, attachments=()):
    return {"request_id": rid, "received_at": received, "channel": "email", "from": sender,
            "to": "TCC Desk <tcc.desk@validus-rta.example>", "cc": "", "subject": subject, "body": body,
            "attachments": list(attachments)}


def exp(request_type, outcome, reasons, approver=None, checks=None, folio=None, txn=None, amc=None):
    e = {"request_type": request_type, "outcome": outcome, "reason_codes": reasons, "approver_role": approver,
         "human_approval_required": outcome in ("PROCEED_MODIFIED", "REJECT", "HOLD_AND_REFER")}
    if checks:
        e["checks"] = checks
    if folio is not None or txn is not None or amc is not None:
        e["resolved"] = {k: v for k, v in (("folio_no", folio), ("txn_id", txn), ("amc_code", amc)) if v is not None}
    return e


INBOX = {
    "R01": ("SIP registration, distributor, valid ARN/EUIN, NACH registered", ["inbox", "sip", "distributor"],
            exp("SIP_REGISTRATION", "PROCEED", [], None, {"KYC_STATUS": "PASS", "THIRD_PARTY_PAYMENT": "PASS", "DISTRIBUTOR_CODE": "PASS"}, "40118823/23", "T261000007")),
    "R02": ("Grandparent pays into minor folio (v4.1 5.4)", ["inbox", "tpp", "minor"],
            exp("ADDITIONAL_PURCHASE", "REJECT", ["TPP_NO_EXCEPTION"], "CHECKER", {"THIRD_PARTY_PAYMENT": "FAIL", "KYC_STATUS": "PASS", "MINOR_RULES": "PASS"}, "40173612/78", "T261000009")),
    "R03": ("Employer payroll SIP, 3 documents missing (scan + letter)", ["inbox", "tpp", "employer", "scan"],
            exp("SIP_REGISTRATION", "PEND", ["TPP_DOCS_MISSING"], None, {"THIRD_PARTY_PAYMENT": "FAIL", "DISTRIBUTOR_CODE": "NOT_APPLICABLE"}, "71138631/21", "T261000011")),
    "R04": ("KYC On Hold, additional purchase", ["inbox", "kyc"],
            exp("ADDITIONAL_PURCHASE", "REJECT", ["KYC_ON_HOLD"], "CHECKER", {"KYC_STATUS": "FAIL", "THIRD_PARTY_PAYMENT": "PASS"}, "40120238/73", "T261000013")),
    "R05": ("KYC Registered, new folio with a new AMC", ["inbox", "kyc", "new_folio"],
            exp("NEW_FOLIO_PURCHASE", "PEND", ["KYC_REGISTERED_NEW_AMC"], None, {"KYC_STATUS": "FAIL"}, amc="TMF")),
    "R06": ("Own unregistered account, bank statement enclosed; duplicate pending row", ["inbox", "tpp", "data_issue"],
            exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"THIRD_PARTY_PAYMENT": "PASS"}, "40159954/10", "T261000021")),
    "R07": ("Joint folio, second holder pays from own account", ["inbox", "tpp", "joint"],
            exp("ADDITIONAL_PURCHASE", "REJECT", ["TPP_NO_EXCEPTION"], "CHECKER", {"THIRD_PARTY_PAYMENT": "FAIL"}, "40112665/21", "T261000022")),
    "R08": ("Expired ARN, TMF, 'fresh purchase' wording on existing folio", ["inbox", "distributor", "tmf"],
            exp("ADDITIONAL_PURCHASE", "PROCEED_MODIFIED", ["ARN_INVALID_DIRECT"], "CHECKER", {"DISTRIBUTOR_CODE": "FAIL"}, "71167297/25", "T261000025")),
    "R09": ("KRA web service not reachable (399)", ["inbox", "kyc", "utv"],
            exp("ADDITIONAL_PURCHASE", "PEND", ["KYC_UNABLE_TO_VERIFY"], None, {"KYC_STATUS": "UNABLE_TO_VERIFY"}, "40131574/17", "T261000028")),
    "R10": ("Redemption + COB 4 days earlier + contact change; pending-validation payout account", ["inbox", "cob", "redemption"],
            exp("REDEMPTION", "HOLD_AND_REFER", ["HIGH_RISK_CONTACT_COB", "COB_COOLING", "BANK_PROOF_REQUIRED"], "OPS_MANAGER",
                {"COB_COOLING": "FAIL", "BANK_MANDATE": "FAIL", "KYC_STATUS": "PASS"}, "40115267/30", "T261000031")),
}

S = "2026-10-08T11:00:00+05:30"

CASES = [
    ("R00", "Worked example from CURRENT_WORKFLOW (Kedia Wealth / Ravi Kumar Bhat)", ["workflow", "proceed"],
     req("R00", "2026-09-22T11:05:00+05:30", "Ramesh Kedia <operations@kediawealth.example>",
         "Additional purchase - Ravi Kumar Bhat - Narmada Large Cap",
         "Dear Team, Our client Mr. Ravi Kumar Bhat has invested Rs. 75,000/- in Narmada Large Cap Fund - Regular - Growth, "
         "folio no. 4016645093, by NEFT today from his Konkan Mercantile Bank account ending 5475 (UTR VNDYN2609229076583). "
         "ARN-145023 / EUIN E289730. Kindly process.  Regards, Ramesh Kedia, Kedia Wealth Partners"),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None,
         {"KYC_STATUS": "PASS", "THIRD_PARTY_PAYMENT": "PASS", "DISTRIBUTOR_CODE": "PASS", "BANK_MANDATE": "NOT_APPLICABLE",
          "COB_COOLING": "NOT_APPLICABLE", "MINOR_RULES": "NOT_APPLICABLE", "REFERRAL": "PASS", "FOLIO_IDENTITY": "PASS"},
         "40166450/93", "T260900518")),
    ("C01", "Reworded SIP registration (R01 type), folio without slash", ["reworded", "sip"],
     req("C01", "2026-10-06T10:30:00+05:30", "Ramesh Kedia <operations@kediawealth.example>", "SIP for Mr Nair",
         "Hi team - kindly register Arjun Nair's monthly SIP, Rs 10000 on the 10th, Narmada Flexi Cap regular growth, "
         "folio 4011882323. First instalment went through NACH from his Aravali a/c ending 4908 on 6 Oct. "
         "ARN-145023, EUIN E289730. Thanks"),
     exp("SIP_REGISTRATION", "PROCEED", [], None, {"DISTRIBUTOR_CODE": "PASS", "THIRD_PARTY_PAYMENT": "PASS"}, "40118823/23", "T261000007")),
    ("C02", "Hindi-English mix, KRA not reachable", ["hinglish", "kyc", "utv"],
     req("C02", "2026-10-08T14:30:00+05:30", "Kiran Reddy <kiran.r****@gmail.com>", "paisa add kiya",
         "Namaste, maine aaj Narmada Flexi Cap mein Rs 75,000 IMPS se daale hain, folio 40131574/17, mere registered "
         "Satpura Bank account ending 4455 se. Kripya confirm karein. Dhanyavaad, Kiran"),
     exp("ADDITIONAL_PURCHASE", "PEND", ["KYC_UNABLE_TO_VERIFY"], None, {"KYC_STATUS": "UNABLE_TO_VERIFY"}, "40131574/17", "T261000028")),
    ("C03", "Folio typo (last digit wrong) must be INVALID, not nearest match", ["identity", "typo"],
     req("C03", S, "Kiran Reddy <kiran.r****@gmail.com>", "Additional purchase",
         "Additional purchase of Rs. 75,000 by IMPS today in Narmada Flexi Cap Fund, folio 40131574/18, from my "
         "registered Satpura Bank account ending 4455."),
     exp("OTHER_OK", "INVALID_REQUEST", ["FOLIO_NOT_FOUND"], None, {"FOLIO_IDENTITY": "FAIL"})),
    ("C04", "PAN in email belongs to someone else (folio/PAN conflict)", ["identity", "pan"],
     req("C04", S, "Kiran Reddy <kiran.r****@gmail.com>", "Additional purchase folio 40131574/17",
         "Please add Rs 75,000 (IMPS, Satpura a/c ending 4455) to folio 40131574/17. My PAN is YBZPB**44W."),
     exp("OTHER_OK", "INVALID_REQUEST", ["FOLIO_PAN_MISMATCH"], None, {"FOLIO_IDENTITY": "FAIL"})),
    ("C05", "KRA status text blank; code 203 = On Hold (derive from code)", ["kyc", "data_issue"],
     req("C05", S, "Tarun Reddy <ta****@rediffmail.com>", "Lump sum in short duration fund",
         "Hello, I have invested Rs 20,000 in Narmada Short Duration Fund - Direct - Growth, folio 40128306/90, by NEFT "
         "from my registered Konkan Mercantile Bank account ending 8313. Please confirm. Tarun Reddy"),
     exp("ADDITIONAL_PURCHASE", "REJECT", ["KYC_ON_HOLD"], "CHECKER", {"KYC_STATUS": "FAIL"}, "40128306/90")),
    ("C06", "KYC Registered investor opens folio with a new AMC (TMF)", ["kyc", "new_folio"],
     req("C06", S, "Gaurav Bhatia <ga****@yahoo.co.in>", "New folio in Tungabhadra Midcap",
         "Dear team, I want to start investing in Tungabhadra Midcap Fund - Direct - Growth, Rs 1,00,000 lump sum. "
         "I already have Narmada folio 40136263/98. Please open a new folio with Tungabhadra and tell me how to pay. Gaurav"),
     exp("NEW_FOLIO_PURCHASE", "PEND", ["KYC_REGISTERED_NEW_AMC"], None, {"KYC_STATUS": "FAIL"}, amc="TMF")),
    ("C07", "KYC Registered, additional purchase with an AMC already held (net banking)", ["kyc", "proceed"],
     req("C07", S, "Gaurav Bhatia <ga****@yahoo.co.in>", "Top up Narmada Large Cap",
         "Topped up Rs 25,000 into Narmada Large Cap Fund Direct Growth today via net banking from my Sindhu Commercial "
         "Bank account ending 7946. Folio 40136263/98."),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"KYC_STATUS": "PASS", "THIRD_PARTY_PAYMENT": "PASS"}, "40136263/98", "T261000020")),
    ("C08", "KYC On Hold, redemption -> refer to Operations Manager", ["kyc", "redemption"],
     req("C08", S, "Farhan Siddiqui <farhan.s****@gmail.com>", "Redeem short duration",
         "Hi, please redeem Rs 50,000 from Narmada Short Duration Fund, folio 40120238/73, to my registered account. Farhan"),
     exp("REDEMPTION", "HOLD_AND_REFER", ["KYC_ON_HOLD"], "OPS_MANAGER", {"KYC_STATUS": "FAIL"}, "40120238/73")),
    ("C09", "Mother (guardian) pays minor's folio from her own unregistered account, statement enclosed", ["tpp", "minor", "parent"],
     req("C09", "2026-10-07T18:00:00+05:30", "Meera Deshpande <me****@yahoo.co.in>", "Investment for Ananya - folio 40129212/58",
         "Dear Sir, I have sent Rs 40,000 by NEFT from my Kaveri Commercial Bank savings account ending 9986 for my "
         "daughter Ananya's folio 40129212/58, Narmada Flexi Cap Fund Direct Growth (UTR KVCBN2610071549174). "
         "My bank statement showing the debit is attached. Regards, Meera Deshpande (mother and guardian)",
         [att("Bank_statement_Meera.txt",
              "STATEMENT OF ACCOUNT (extract) 01/10/2026 to 07/10/2026\nKaveri Commercial Bank - Savings Account\n"
              "Account holder : MEERA S DESHPANDE\nAccount number : XXXXXXXX9986\nJoint holder(s): -\n"
              "07/10/2026 NEFT-KVCBN2610071549174-NARMADA MUTUAL FUND 40,000.00\n")]),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"THIRD_PARTY_PAYMENT": "PASS", "MINOR_RULES": "PASS"}, "40129212/58", "T261000010")),
    ("C10", "Mother pays minor's folio from unregistered account, no proof", ["tpp", "minor", "parent"],
     req("C10", "2026-10-07T18:00:00+05:30", "Meera Deshpande <me****@yahoo.co.in>", "Ananya folio top-up",
         "Hello, I am Ananya's mother. I transferred Rs 40,000 by NEFT from my account ending 9986 to her folio "
         "40129212/58 in Narmada Flexi Cap Direct. Please process. Meera"),
     exp("ADDITIONAL_PURCHASE", "PEND", ["BANK_PROOF_REQUIRED"], None, {"THIRD_PARTY_PAYMENT": "FAIL"}, "40129212/58", "T261000010")),
    ("C11", "Employer payroll SIP with every 5.3 document enclosed", ["tpp", "employer"],
     req("C11", "2026-10-07T15:02:00+05:30", "HR Payroll - Deccan Polymers <payroll@deccanpolymers.example>",
         "Payroll SIP - Sandeep Yadav (Emp DP-4471) - complete documents",
         "Dear Team, Please find our payroll-deduction SIP of Rs 5,000 for our employee Sandeep Yadav (DP-4471), "
         "Tungabhadra Large & Mid Cap Fund - Direct - Growth, folio 71138631/21, remitted by NEFT from our company "
         "account on 07-Oct-2026. All documents are attached. Regards, Kavya Rao, HR Operations",
         [att("TPP_declaration.txt", "THIRD PARTY PAYMENT DECLARATION FORM\nBeneficial investor: Sandeep Yadav\nFolio: 71138631/21\n"
              "Third party: Deccan Polymers Pvt Ltd\nRelationship: Employer\nSigned: Kavya Rao\n"),
          att("Employer_letter.txt", "DECCAN POLYMERS PVT LTD\nConfirmation of payroll deduction - employee SIP\nWe confirm payroll "
              "deduction for employee Sandeep Yadav (DP-4471), Rs 5,000 per month.\n"),
          att("Employee_list.txt", "LIST OF EMPLOYEES\nEmployee code | Name | PAN | KYC\nDP-4471 | Sandeep Yadav | BARPY**69Z | Validated\n"),
          att("KYC_ack_investor.txt", "KYC ACKNOWLEDGEMENT OF INVESTOR\nName: Sandeep Yadav  PAN: BARPY**69Z  Status: KYC Validated\n"),
          att("KYC_ack_employer.txt", "KYC ACKNOWLEDGEMENT OF EMPLOYER\nDeccan Polymers Pvt Ltd  PAN: RLVCL**88Y  Status: KYC Validated\n")]),
     exp("SIP_REGISTRATION", "PROCEED", [], None, {"THIRD_PARTY_PAYMENT": "PASS"}, "71138631/21", "T261000011")),
    ("C12", "Employer payroll SIP missing only the employee list", ["tpp", "employer"],
     req("C12", "2026-10-07T15:02:00+05:30", "HR Payroll - Deccan Polymers <payroll@deccanpolymers.example>",
         "Payroll SIP - Sandeep Yadav",
         "Dear Team, payroll SIP of Rs 5,000 for our employee Sandeep Yadav, folio 71138631/21, Tungabhadra Large & Mid "
         "Cap Direct Growth, paid by NEFT from our company account. Declaration, letter and KYC acknowledgements attached; "
         "the list of employees will follow next week.",
         [att("TPP_declaration.txt", "THIRD PARTY PAYMENT DECLARATION FORM\nBeneficial investor: Sandeep Yadav\nRelationship: Employer\n"),
          att("Employer_letter.txt", "DECCAN POLYMERS PVT LTD\nConfirmation of payroll deduction for employee Sandeep Yadav.\n"),
          att("KYC_ack_investor.txt", "KYC ACKNOWLEDGEMENT OF INVESTOR\nSandeep Yadav BARPY**69Z\n"),
          att("KYC_ack_employer.txt", "KYC ACKNOWLEDGEMENT OF EMPLOYER\nDeccan Polymers Pvt Ltd RLVCL**88Y\n")]),
     exp("SIP_REGISTRATION", "PEND", ["TPP_DOCS_MISSING"], None, {"THIRD_PARTY_PAYMENT": "FAIL"}, "71138631/21", "T261000011")),
    ("C13", "Own unregistered account without proof (R06 without the statement)", ["tpp", "proof"],
     req("C13", "2026-10-07T16:20:00+05:30", "Neha Agarwal <neha.a****@gmail.com>", "NEFT to folio 40159954/10",
         "I transferred Rs. 2,00,000 by NEFT today to Narmada Flexi Cap Fund for my folio 40159954/10 from my own Vindhya "
         "Bank savings account ending 5879 (UTR VNDYN2610073906590). Thanks, Neha"),
     exp("ADDITIONAL_PURCHASE", "PEND", ["BANK_PROOF_REQUIRED"], None, {"THIRD_PARTY_PAYMENT": "FAIL"}, "40159954/10", "T261000021")),
    ("C14", "First holder pays from a joint (unregistered) account she holds, statement enclosed", ["tpp", "joint"],
     req("C14", S, "Priya Raghavan <pr****@rediffmail.com>", "Investment in folio 40112665/21",
         "Dear team, I have invested Rs 60,000 in Narmada Large Cap Fund Direct Growth (folio 40112665/21) by NEFT from "
         "our joint savings account ending 7781 with my husband. Statement attached. Priya",
         [att("Joint_statement.txt", "STATEMENT OF ACCOUNT\nAccount holder : PRIYA RAGHAVAN\nJoint holder(s): RAGHAVAN SRINIVASAN\n"
              "Account number : XXXXXXXX7781\n08/10/2026 NEFT-CRMLN2610089999123-NARMADA MUTUAL FUND 60,000.00\n")]),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"THIRD_PARTY_PAYMENT": "PASS"}, "40112665/21")),
    ("C15", "Minor attained majority; SIP instalment falls due after 18th birthday", ["minor"],
     req("C15", "2026-10-08T10:00:00+05:30", "Sanjay Patil <sa****@gmail.com>", "SIP for Aditya folio 40149414-17",
         "Dear Sir, the monthly SIP instalment of Rs 5,000 for my son Aditya in Narmada Flexi Cap (folio 40149414-17) was "
         "debited by NACH today. Please confirm. Sanjay Patil (father)"),
     exp("SIP_INSTALMENT", "PEND", ["MINOR_ATTAINED_MAJORITY"], None, {"MINOR_RULES": "FAIL"}, "40149414/17", "T261000044")),
    ("C16", "Redemption submitted together with a COB (both proofs) -> 10-day cooling", ["cob", "redemption"],
     req("C16", S, "Gaurav Bhatia <ga****@yahoo.co.in>", "Redemption and bank change - folio 40136263/98",
         "Please redeem Rs 20,000 from Narmada Large Cap Fund, folio 40136263/98. I am also changing my bank: change of "
         "bank form, cancelled cheque of the new account and a statement of my existing Sindhu Commercial Bank account "
         "ending 7946 are attached.",
         [att("Change_of_bank_form.txt", "Request for Change of Bank Mandate\nFolio no. : 40136263/98\nExisting bank: Sindhu Commercial "
              "Bank XXXXXXXX7946\nNew bank: Aravali Bank\nAccount number : XXXXXXXX4410\nDate: 08/10/2026\n"),
          att("Cancelled_cheque_new.txt", "ARAVALI BANK\nCANCELLED\nA/c No. 7712004410\nGAURAV BHATIA\n"),
          att("Old_account_statement.txt", "STATEMENT OF ACCOUNT\nAccount holder : GAURAV BHATIA\nAccount number : XXXXXXXX7946\n")]),
     exp("REDEMPTION", "PEND", ["COB_COOLING"], None, {"COB_COOLING": "FAIL", "BANK_MANDATE": "PASS"}, "40136263/98")),
    ("C17", "Redemption 17 days after COB (outside cooling)", ["cob", "redemption", "proceed"],
     req("C17", "2026-10-07T10:00:00+05:30", "Vikram Shetty <vi****@outlook.com>", "Redemption folio 40177095/71",
         "Please redeem Rs 3,00,000 from Narmada Flexi Cap Fund, folio 40177095/71, to my registered Aravali Bank account."),
     exp("REDEMPTION", "PROCEED", [], None, {"COB_COOLING": "PASS", "BANK_MANDATE": "PASS"}, "40177095/71", "T261000033")),
    ("C18", "Active ARN not empanelled with TMF", ["distributor", "tmf"],
     req("C18", S, "Coastal Investment Services <ops@coastal.example>", "Additional purchase Rahul Joshi",
         "Dear Team, Rs 1,50,000 additional purchase in Tungabhadra Midcap Fund - Regular - Growth for our client Rahul "
         "Joshi, folio 71102387-42, NEFT from his registered Aravali account ending 6578. ARN-118460 / EUIN E821115."),
     exp("ADDITIONAL_PURCHASE", "PROCEED_MODIFIED", ["ARN_INVALID_DIRECT"], "CHECKER", {"DISTRIBUTOR_CODE": "FAIL"}, "71102387/42", "T261000026")),
    ("C19", "Regular plan, valid ARN, blank EUIN -> proceed with EUIN_MISSING follow-up", ["distributor", "euin"],
     req("C19", S, "Ramesh Kedia <operations@kediawealth.example>", "Additional purchase Ravi Kumar Bhat",
         "Our client Mr Ravi Kumar Bhat has invested Rs 50,000 in Narmada Large Cap Fund - Regular - Growth, folio "
         "40166450/93, by NEFT today from his registered Konkan Mercantile Bank account ending 5475. ARN-145023."),
     exp("ADDITIONAL_PURCHASE", "PROCEED", ["EUIN_MISSING"], None, {"DISTRIBUTOR_CODE": "FAIL"}, "40166450/93")),
    ("C20", "Redemption on a STOP_LOCK folio", ["referral", "stop_lock"],
     req("C20", S, "Harini Subramanian <ha****@yahoo.co.in>", "Redemption",
         "Please redeem Rs 1,20,000 from my Narmada Large Cap Fund holding, folio 40161537/29. Regards, Harini"),
     exp("REDEMPTION", "HOLD_AND_REFER", ["STOP_LOCK"], "OPS_MANAGER", {"REFERRAL": "FAIL"}, "40161537/29", "T261000046")),
    ("C21", "Cash purchase takes FY total above Rs 50,000 (aggregated with May cash)", ["referral", "cash"],
     req("C21", "2026-10-07T12:00:00+05:30", "Ramesh Chandra Gupta <ra****@gmail.com>", "Cash deposit",
         "I deposited Rs 35,000 in cash at your branch today for Tungabhadra Balanced Advantage Fund Direct, folio 71173574/68."),
     exp("ADDITIONAL_PURCHASE", "REJECT", ["CASH_LIMIT_BREACH"], "CHECKER", {"REFERRAL": "FAIL", "THIRD_PARTY_PAYMENT": "NOT_APPLICABLE"}, "71173574/68", "T261000049")),
    ("C22", "TMF redemption >= 5L within 30 days of an additional purchase (TMF-ADD-02 A1)", ["referral", "tmf", "addendum"],
     req("C22", S, "Deepak Choudhary <de****@rediffmail.com>", "Redeem corporate bond fund",
         "Please redeem Rs 6,00,000 from Tungabhadra Corporate Bond Fund, folio 71184287/96, to my registered account."),
     exp("REDEMPTION", "HOLD_AND_REFER", ["REFERRAL_TRIGGER"], "OPS_MANAGER", {"REFERRAL": "FAIL"}, "71184287/96", "T261000035")),
    ("C23", "Same pattern on NMF (no addendum) -> no referral", ["referral", "nmf", "control"],
     req("C23", S, "Anil Saxena <an****@yahoo.co.in>", "Redemption folio 40138985/28",
         "Please redeem Rs 5,50,000 from Narmada Short Duration Fund, folio 40138985/28, to my registered Kaveri account."),
     exp("REDEMPTION", "PROCEED", [], None, {"REFERRAL": "PASS"}, "40138985/28")),
    ("C24", "TMF change of bank without existing-account proof (A2)", ["cob", "tmf", "addendum"],
     req("C24", S, "Aditi Menon <ad****@outlook.com>", "Change of bank - folio 71167297/25",
         "Please change my bank mandate on folio 71167297/25 to my new Coromandel Bank account ending 3390. Change of bank "
         "form and cancelled cheque attached.",
         [att("COB_form.txt", "Request for Change of Bank Mandate\nFolio no. : 71167297/25\nNew bank: Coromandel Bank\nAccount number : "
              "XXXXXXXX3390\nOld bank proof: not available\nDate: 08/10/2026\n"),
          att("Cancelled_cheque.txt", "COROMANDEL BANK\nCANCELLED\nA/c No. 5501203390\nADITI MENON\n")]),
     exp("CHANGE_OF_BANK", "PEND", ["BANK_PROOF_REQUIRED"], None, {"BANK_MANDATE": "FAIL"}, "71167297/25")),
    ("C25", "TMF COB relying on in-person verification (not accepted for TMF)", ["cob", "tmf", "addendum"],
     req("C25", S, "Aditi Menon <ad****@outlook.com>", "Bank change folio 71167297/25",
         "I visited your Chennai branch for in-person verification of my existing account. Please register my new "
         "Coromandel Bank account ending 3390 on folio 71167297/25; cancelled cheque attached.",
         [att("Cancelled_cheque.txt", "COROMANDEL BANK\nCANCELLED\nA/c No. 5501203390\nADITI MENON\n")]),
     exp("CHANGE_OF_BANK", "PEND", ["BANK_PROOF_REQUIRED"], None, {"BANK_MANDATE": "FAIL"}, "71167297/25")),
    ("C26", "Grandparent -> minor dated May 2026: SOP v3.2 related-person exception with documents", ["tpp", "minor", "v3.2"],
     req("C26", "2026-05-15T11:00:00+05:30", "Vasant Kulkarni <vasantgk1951@rediffmail.example>", "Investment for grandson Ishaan",
         "Dear Sir, I have transferred Rs. 30,000 by NEFT from my Satpura Bank savings account ending 9641 for my grandson "
         "Ishaan Kulkarni (minor), folio 40173612/78, Narmada Flexi Cap Fund Direct. Third party payment declaration and my "
         "KYC are attached. Vasant G. Kulkarni",
         [att("TPP_declaration_Vasant.txt", "THIRD PARTY PAYMENT DECLARATION FORM\nBeneficial investor: Ishaan Kulkarni (minor)\n"
              "Third party: Vasant Govind Kulkarni\nRelationship: Grandfather\n"),
          att("KYC_of_payer_Vasant.txt", "KYC ACKNOWLEDGEMENT OF PAYER\nVasant Govind Kulkarni - KYC Validated\n")]),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"THIRD_PARTY_PAYMENT": "PASS"}, "40173612/78")),
    ("C27", "Expired ARN in July 2026 (v4.0 not available -> v3.2: stays Regular, no code)", ["distributor", "v3.2"],
     req("C27", "2026-07-15T11:00:00+05:30", "Nilgiri Finserv <ops@nilgiri.example>", "Purchase Ravi Kumar Bhat",
         "Additional purchase of Rs 40,000 in Narmada Large Cap Fund - Regular - Growth for our client Ravi Kumar Bhat, "
         "folio 40166450/93, NEFT from his registered Konkan Mercantile account ending 5475. ARN-297295 / EUIN E894442."),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"DISTRIBUTOR_CODE": "FAIL"}, "40166450/93")),
    ("C28", "Suspended ARN (NMF) under v4.1", ["distributor"],
     req("C28", S, "Nexa Capital Advisors <ops@nexa.example>", "Additional purchase",
         "Rs 40,000 in Narmada Large Cap Fund - Regular - Growth for client Ravi Kumar Bhat, folio 40166450/93, NEFT from "
         "registered Konkan Mercantile account ending 5475. ARN-176204 / EUIN E852697."),
     exp("ADDITIONAL_PURCHASE", "PROCEED_MODIFIED", ["ARN_INVALID_DIRECT"], "CHECKER", {"DISTRIBUTOR_CODE": "FAIL"}, "40166450/93")),
    ("C29", "Large Rs 30 lakh purchase with no large redemption nearby -> no false referral", ["referral", "control"],
     req("C29", S, "Ravi Kumar Bhat <ra****@outlook.com>", "Large investment",
         "I have invested Rs 30 lakh by RTGS today in Narmada Large Cap Fund Direct Growth, folio 40166450/93, from my "
         "registered Konkan Mercantile Bank account ending 5475."),
     exp("ADDITIONAL_PURCHASE", "PROCEED", [], None, {"REFERRAL": "PASS"}, "40166450/93")),
    ("C30", "Out-of-scope request (nomination update) -> not auto-proceeded", ["other"],
     req("C30", S, "Kiran Reddy <kiran.r****@gmail.com>", "Nomination update",
         "Hello, I want to update the nominee on my folio 40131574/17 to my wife. Please send me the form. Kiran"),
     exp("OTHER", "PEND", [], None, {"FOLIO_IDENTITY": "PASS"}, "40131574/17")),
    ("C31", "NMF change of bank with both proofs -> proceed to validation", ["cob"],
     req("C31", S, "Gaurav Bhatia <ga****@yahoo.co.in>", "Change of bank folio 40136263/98",
         "Please change my bank mandate on folio 40136263/98 to my new Aravali Bank account ending 4410. Form, cancelled "
         "cheque and a statement of my existing account ending 7946 are attached.",
         [att("Change_of_bank_form.txt", "Request for Change of Bank Mandate\nFolio no. : 40136263/98\nNew bank: Aravali Bank\n"
              "Account number : XXXXXXXX4410\nDate: 08/10/2026\n"),
          att("Cancelled_cheque_new.txt", "ARAVALI BANK\nCANCELLED\nA/c No. 7712004410\nGAURAV BHATIA\n"),
          att("Old_account_statement.txt", "STATEMENT OF ACCOUNT\nAccount holder : GAURAV BHATIA\nAccount number : XXXXXXXX7946\n")]),
     exp("CHANGE_OF_BANK", "PROCEED", [], None, {"BANK_MANDATE": "PASS"}, "40136263/98")),
    ("C32", "Redemption from a TMF scheme quoting an NMF folio -> identifiers conflict", ["identity"],
     req("C32", S, "Anil Saxena <an****@yahoo.co.in>", "Redemption",
         "Please redeem Rs 50,000 from Tungabhadra Midcap Fund, folio 40138985/28."),
     exp("OTHER_OK", "INVALID_REQUEST", ["FOLIO_PAN_MISMATCH"], None, {"FOLIO_IDENTITY": "FAIL"})),
    ("C33", "Grandparent -> minor, no attachment, reworded (v4.1)", ["tpp", "minor", "reworded"],
     req("C33", "2026-10-06T18:40:00+05:30", "Vasant Kulkarni <vasantgk1951@rediffmail.example>", "For Ishaan",
         "Sent forty thousand rupees (Rs 40,000) by NEFT from my Satpura account ending 9641 for my grandson's folio "
         "4017361278 in Narmada Flexi Cap. UTR KNKMH2610065981253. - Vasant (grandfather)"),
     exp("ADDITIONAL_PURCHASE", "REJECT", ["TPP_NO_EXCEPTION"], "CHECKER", {"THIRD_PARTY_PAYMENT": "FAIL"}, "40173612/78", "T261000009")),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.glob("*.json"):
        p.unlink()
    n = 0
    for rid, (desc, tags, e) in INBOX.items():
        (OUT / f"{rid}.json").write_text(json.dumps({"id": rid, "description": desc, "tags": tags,
                                                     "input_ref": f"inbox:{rid}", "expected": e}, indent=1), encoding="utf-8")
        n += 1
    for cid, desc, tags, payload, e in CASES:
        (OUT / f"{cid}.json").write_text(json.dumps({"id": cid, "description": desc, "tags": tags, "input": payload,
                                                     "expected": e}, indent=1, ensure_ascii=False), encoding="utf-8")
        n += 1
    print(f"wrote {n} cases to {OUT}")


if __name__ == "__main__":
    main()
