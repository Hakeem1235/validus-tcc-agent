"""Unit tests per rule branch (SOP v4.1 / v3.2 / TMF-ADD-02)."""
from __future__ import annotations

from datetime import date

from app.checks import REGISTRY, bank_mandate, cob, distributor, kyc, minor, referral, tpp
from app.s6_decide import decide
from app.schemas import AttachmentInfo
from tests.conftest import SYNTH_FOLIO, SYNTH_TMF, make_case


def run_all(case):
    return decide([fn(case) for fn in REGISTRY.values()])


# ----------------------------------------------------------------------------- KYC
class TestKYC:
    def test_validated_pass(self):
        r = kyc.run(make_case("ADDITIONAL_PURCHASE", "40166450/93", "T260900518", received="2026-09-22T11:05:00+05:30"))
        assert r.result == "PASS" and r.sop_clause == "TCC-SOP v4.1 4.2"

    def test_on_hold_purchase_rejects(self):
        r = kyc.run(make_case("ADDITIONAL_PURCHASE", "40120238/73", "T261000013"))
        assert (r.result, r.reason_codes, r.data["outcome"]) == ("FAIL", ["KYC_ON_HOLD"], "REJECT")
        assert r.sop_clause.endswith("4.4")

    def test_on_hold_redemption_refers(self):
        r = kyc.run(make_case("REDEMPTION", "40120238/73"))
        assert r.reason_codes == ["KYC_ON_HOLD"] and r.data["outcome"] == "HOLD_AND_REFER"

    def test_registered_new_amc_pends(self):
        c = make_case("NEW_FOLIO_PURCHASE", target_amc="TMF")
        c.first_holder_pan = "XZDPV**82H"
        r = kyc.run(c)
        assert (r.result, r.reason_codes) == ("FAIL", ["KYC_REGISTERED_NEW_AMC"]) and r.sop_clause.endswith("4.3")

    def test_registered_amc_already_held_accepts(self):
        c = make_case("NEW_FOLIO_PURCHASE", target_amc="NMF")
        c.first_holder_pan = "XZDPV**82H"
        assert kyc.run(c).result == "PASS"

    def test_registered_additional_accepts(self):
        assert kyc.run(make_case("ADDITIONAL_PURCHASE", "40104822/68")).result == "PASS"

    def test_service_unreachable_utv(self):
        r = kyc.run(make_case("ADDITIONAL_PURCHASE", "40131574/17", "T261000028"))
        assert (r.result, r.reason_codes) == ("UNABLE_TO_VERIFY", ["KYC_UNABLE_TO_VERIFY"])

    def test_stale_lookup_utv(self):
        c = make_case("ADDITIONAL_PURCHASE", received="2026-10-08T12:00:00+05:30")
        c.first_holder_pan = "STALE**01S"
        r = kyc.run(c)
        assert r.result == "UNABLE_TO_VERIFY" and "older" in " ".join(r.notes)

    def test_code_text_conflict_utv(self):
        c = make_case("ADDITIONAL_PURCHASE")
        c.first_holder_pan = "CONFL**02C"
        assert kyc.run(c).result == "UNABLE_TO_VERIFY"

    def test_missing_kra_record_utv(self):
        c = make_case("ADDITIONAL_PURCHASE")
        c.first_holder_pan = "NOPAN**00X"
        assert kyc.run(c).result == "UNABLE_TO_VERIFY"

    def test_rejected_purchase_and_redemption(self):
        c = make_case("ADDITIONAL_PURCHASE")
        c.first_holder_pan = "REJEC**03R"
        r = kyc.run(c)
        assert r.reason_codes == ["KYC_REJECTED"] and decide([r]).outcome == "REJECT"
        c = make_case("REDEMPTION")
        c.first_holder_pan = "REJEC**03R"
        d = decide([kyc.run(c)])
        assert (d.outcome, d.approver_role) == ("HOLD_AND_REFER", "OPS_MANAGER")

    def test_under_process_and_not_available_utv(self):
        for pan in ("UNDPR**04U", "NOTAV**05N"):
            c = make_case("ADDITIONAL_PURCHASE")
            c.first_holder_pan = pan
            r = kyc.run(c)
            assert (r.result, r.reason_codes) == ("UNABLE_TO_VERIFY", ["KYC_UNABLE_TO_VERIFY"])

    def test_minor_checks_minor_pan(self):
        r = kyc.run(make_case("ADDITIONAL_PURCHASE", "40173612/78", "T261000009"))
        assert r.result == "PASS" and "minor RRBPK**06M" in r.evidence[0].value

    def test_padded_code_cvl(self):  # URFPP**04D has code '7' in the raw file
        r = kyc.run(make_case("SIP_INSTALMENT", "40149414/17", "T261000044"))
        assert r.result == "PASS" and "code 007" in r.evidence[0].value


# ----------------------------------------------------------------------------- TPP
def neft_advice(acct, holder, utr=None):
    return AttachmentInfo(file_name="advice.pdf", doc_types=["TRANSFER_INSTRUCTION"], account_last4=acct,
                          account_holders=[holder], utr=utr)


class TestTPP:
    def test_registered_joint_account_pass(self):
        r = tpp.run(make_case("ADDITIONAL_PURCHASE", "40166450/93", "T260900518", received="2026-09-22T11:05:00+05:30"))
        assert r.result == "PASS" and r.sop_clause == "TCC-SOP v4.1 5.1"

    def test_grandparent_to_minor_rejected_v41(self):
        c = make_case("ADDITIONAL_PURCHASE", "40173612/78", "T261000009", payer_relation_to_investor="grandfather",
                      attachments=[neft_advice("9641", "VASANT GOVIND KULKARNI", "KNKMH2610065981253")])
        r = tpp.run(c)
        assert (r.result, r.reason_codes, r.sop_clause) == ("FAIL", ["TPP_NO_EXCEPTION"], "TCC-SOP v4.1 5.4")

    def test_grandparent_to_minor_v32_with_docs_pass(self):
        c = make_case("ADDITIONAL_PURCHASE", "40173612/78", "T261000009", received="2026-05-10T10:00:00+05:30",
                      payer_relation_to_investor="grandfather", docs=["TPP_DECLARATION", "KYC_PAYER"],
                      attachments=[neft_advice("9641", "VASANT GOVIND KULKARNI")])
        assert c.policy.sop_version == "3.2"
        assert tpp.run(c).result == "PASS"

    def test_grandparent_to_minor_v32_missing_docs(self):
        c = make_case("ADDITIONAL_PURCHASE", "40173612/78", "T261000009", received="2026-05-10T10:00:00+05:30",
                      payer_relation_to_investor="grandfather", attachments=[neft_advice("9641", "VASANT GOVIND KULKARNI")])
        r = tpp.run(c)
        assert r.reason_codes == ["TPP_DOCS_MISSING"] and set(r.missing_documents) == {"TPP_DECLARATION", "KYC_PAYER"}

    def test_guardian_unregistered_without_proof(self):
        r = tpp.run(make_case("ADDITIONAL_PURCHASE", "40129212/58", "T261000010", payer_relation_to_investor="mother"))
        assert (r.result, r.reason_codes) == ("FAIL", ["BANK_PROOF_REQUIRED"])

    def test_guardian_unregistered_with_proof_pass(self):
        c = make_case("ADDITIONAL_PURCHASE", "40129212/58", "T261000010",
                      attachments=[AttachmentInfo(file_name="stmt.pdf", doc_types=["BANK_STATEMENT"], account_last4="9986",
                                                  account_holders=["MEERA S DESHPANDE"])])
        assert tpp.run(c).result == "PASS"

    def test_second_holder_account_is_tpp(self):
        r = tpp.run(make_case("ADDITIONAL_PURCHASE", "40112665/21", "T261000022", payer_relation_to_investor="spouse"))
        assert (r.result, r.reason_codes) == ("FAIL", ["TPP_NO_EXCEPTION"])

    def test_own_unregistered_with_statement_pass(self):
        c = make_case("ADDITIONAL_PURCHASE", "40159954/10", "T261000021",
                      attachments=[AttachmentInfo(file_name="stmt.pdf", doc_types=["BANK_STATEMENT"], account_last4="5879",
                                                  account_holders=["NEHA AGARWAL"], utr="VNDYN2610073906590")])
        r = tpp.run(c)
        assert r.result == "PASS" and r.sop_clause.endswith("5.6")

    def test_own_unregistered_without_proof(self):
        r = tpp.run(make_case("ADDITIONAL_PURCHASE", "40159954/10", "T261000021", payer_relation_to_investor="self"))
        assert r.reason_codes == ["BANK_PROOF_REQUIRED"]

    def test_employer_missing_docs(self):
        c = make_case("SIP_REGISTRATION", "71138631/21", "T261000011", sender_role="employer",
                      third_party_category="employer", docs=["TPP_DECLARATION", "EMPLOYER_DECLARATION"],
                      mentioned=["EMPLOYEE_LIST"])
        r = tpp.run(c)
        assert r.reason_codes == ["TPP_DOCS_MISSING"]
        assert set(r.missing_documents) == {"EMPLOYEE_LIST", "KYC_ACK_INVESTOR", "KYC_ACK_THIRD_PARTY"}

    def test_employer_all_docs_pass(self):
        c = make_case("SIP_REGISTRATION", "71138631/21", "T261000011", third_party_category="employer",
                      docs=["TPP_DECLARATION", "EMPLOYER_DECLARATION", "EMPLOYEE_LIST", "KYC_ACK_INVESTOR", "KYC_ACK_THIRD_PARTY"])
        assert tpp.run(c).result == "PASS"

    def test_cash_not_applicable(self):
        assert tpp.run(make_case("ADDITIONAL_PURCHASE", "71173574/68", "T261000049")).result == "NOT_APPLICABLE"

    def test_nach_registered_pass(self):
        assert tpp.run(make_case("SIP_REGISTRATION", "40118823/23", "T261000007")).result == "PASS"

    def test_redemption_not_applicable(self):
        assert tpp.run(make_case("REDEMPTION", "40115267/30", "T261000031")).result == "NOT_APPLICABLE"


# ----------------------------------------------------------------------------- bank / COB
R10_ATTACH = [AttachmentInfo(file_name="cob.pdf", doc_types=["COB_FORM"], doc_date="2026-10-04"),
              AttachmentInfo(file_name="chq.png", doc_types=["CANCELLED_CHEQUE"], account_last4="6801",
                             account_holders=["SUNITA IYER"])]


class TestBankCOB:
    def r10(self):
        return make_case("REDEMPTION", "40115267/30", "T261000031", received="2026-10-08T09:47:00+05:30",
                         attachments=R10_ATTACH, docs=["COB_FORM", "CANCELLED_CHEQUE"], payout_account_last4="6801",
                         cob_mentioned=True)

    def test_r10_bank_proof_and_disregard(self):
        r = bank_mandate.run(self.r10())
        assert r.result == "FAIL" and r.reason_codes == ["BANK_PROOF_REQUIRED"]
        assert r.missing_documents == ["EXISTING_BANK_PROOF"]
        assert any("disregarded" in e.value for e in r.evidence)

    def test_r10_cooling_and_high_risk(self):
        r = cob.run(self.r10())
        assert r.result == "FAIL" and set(r.reason_codes) == {"COB_COOLING", "HIGH_RISK_CONTACT_COB"}
        assert r.data["cooling_end"] == "2026-10-14"

    def test_r10_decision(self):
        d = run_all(self.r10())
        assert d.outcome == "HOLD_AND_REFER" and d.approver_role == "OPS_MANAGER"
        assert set(d.reason_codes) == {"HIGH_RISK_CONTACT_COB", "COB_COOLING", "BANK_PROOF_REQUIRED"}
        assert d.reason_codes[0] == "HIGH_RISK_CONTACT_COB"

    def test_redemption_after_cooling_pass(self):
        c = make_case("REDEMPTION", "40177095/71", "T261000033", received="2026-10-07T10:00:00+05:30")
        assert cob.run(c).result == "PASS" and bank_mandate.run(c).result == "PASS"
        assert run_all(c).outcome == "PROCEED"

    def test_cooling_v32_no_cooling(self):
        c = make_case("REDEMPTION", "40115267/30", received="2026-07-10T10:00:00+05:30", attachments=R10_ATTACH[:1],
                      docs=["COB_FORM"], cob_mentioned=True)
        r = cob.run(c)
        assert "COB_COOLING" not in r.reason_codes

    def test_tmf_cob_in_person_not_accepted(self):
        c = make_case("CHANGE_OF_BANK", "71167297/25", received="2026-10-08T10:00:00+05:30",
                      docs=["COB_FORM", "CANCELLED_CHEQUE"], in_person_verification=True)
        r = bank_mandate.run(c)
        assert r.reason_codes == ["BANK_PROOF_REQUIRED"] and r.sop_clause == "TMF-ADD-02 A2"

    def test_nmf_cob_in_person_accepted(self):
        c = make_case("CHANGE_OF_BANK", "40166450/93", received="2026-10-08T10:00:00+05:30",
                      docs=["COB_FORM", "CANCELLED_CHEQUE"], in_person_verification=True)
        assert bank_mandate.run(c).result == "PASS"


# ----------------------------------------------------------------------------- distributor
class TestDistributor:
    def test_expired_arn_direct(self):
        r = distributor.run(make_case("ADDITIONAL_PURCHASE", "71167297/25", "T261000025"))
        assert (r.result, r.reason_codes) == ("FAIL", ["ARN_INVALID_DIRECT"]) and r.sop_clause.endswith("7.2")
        d = run_all(make_case("ADDITIONAL_PURCHASE", "71167297/25", "T261000025"))
        assert (d.outcome, d.approver_role) == ("PROCEED_MODIFIED", "CHECKER")

    def test_expired_arn_v32_stays_regular(self):
        c = make_case("ADDITIONAL_PURCHASE", "71167297/25", "T261000025", received="2026-05-01T10:00:00+05:30")
        r = distributor.run(c)
        assert r.result == "FAIL" and r.reason_codes == [] and decide([r]).outcome == "PROCEED"

    def test_not_empanelled_tmf(self):
        r = distributor.run(make_case("ADDITIONAL_PURCHASE", "71102387/42", "T261000026"))
        assert r.reason_codes == ["ARN_INVALID_DIRECT"] and "not empanelled with TMF" in " ".join(e.value for e in r.evidence)

    def test_valid_arn_euin_pass(self):
        assert distributor.run(make_case("SIP_REGISTRATION", "40118823/23", "T261000007")).result == "PASS"

    def test_blank_euin(self):
        c = make_case("ADDITIONAL_PURCHASE", "40166450/93", plan="REGULAR", arn="ARN-145023")
        r = distributor.run(c)
        assert r.reason_codes == ["EUIN_MISSING"] and decide([r]).outcome == "PROCEED"

    def test_blank_euin_execution_only(self):
        c = make_case("ADDITIONAL_PURCHASE", "40166450/93", plan="REGULAR", arn="ARN-145023", execution_only_declaration=True)
        assert distributor.run(c).result == "PASS"

    def test_euin_of_other_arn(self):
        c = make_case("ADDITIONAL_PURCHASE", "40166450/93", plan="REGULAR", arn="ARN-145023", euin="E424168")
        assert distributor.run(c).reason_codes == ["EUIN_MISSING"]

    def test_direct_na(self):
        assert distributor.run(make_case("ADDITIONAL_PURCHASE", "40131574/17", "T261000028")).result == "NOT_APPLICABLE"

    def test_unknown_arn(self):
        c = make_case("ADDITIONAL_PURCHASE", "40166450/93", plan="REGULAR", arn="ARN-999999", euin="E1")
        assert distributor.run(c).reason_codes == ["ARN_INVALID_DIRECT"]


# ----------------------------------------------------------------------------- minor
class TestMinor:
    def test_attained_majority(self):
        r = minor.run(make_case("SIP_INSTALMENT", "40149414/17", "T261000044"))
        assert (r.result, r.reason_codes) == ("FAIL", ["MINOR_ATTAINED_MAJORITY"])
        assert run_all(make_case("SIP_INSTALMENT", "40149414/17", "T261000044")).outcome == "PEND"

    def test_still_minor(self):
        assert minor.run(make_case("ADDITIONAL_PURCHASE", "40173612/78")).result == "PASS"

    def test_not_minor_na(self):
        assert minor.run(make_case("ADDITIONAL_PURCHASE", "40166450/93")).result == "NOT_APPLICABLE"

    def test_majority_date_leap(self):
        assert minor.majority_date(date(2008, 2, 29), 18) == date(2026, 3, 1)


# ----------------------------------------------------------------------------- referral
class TestReferral:
    def test_stop_lock(self):
        c = make_case("REDEMPTION", "40161537/29", "T261000046")
        r = referral.run(c)
        assert r.reason_codes == ["STOP_LOCK"] and r.sop_clause.endswith("8.4")
        d = run_all(c)
        assert (d.outcome, d.approver_role) == ("HOLD_AND_REFER", "OPS_MANAGER")

    def test_cash_limit_breach_fy_aggregate(self):
        c = make_case("ADDITIONAL_PURCHASE", "71173574/68", "T261000049")
        r = referral.run(c)
        assert r.reason_codes == ["CASH_LIMIT_BREACH"]
        assert run_all(c).outcome == "REJECT"

    def test_cash_under_limit(self):
        c = make_case("ADDITIONAL_PURCHASE", "71173574/68", is_cash=True, amount_inr=10000)
        c.txn = None
        assert referral.run(c).result == "PASS"

    def test_tmf_a1_real(self):
        c = make_case("REDEMPTION", "71184287/96", "T261000035")
        r = referral.run(c)
        assert r.reason_codes == ["REFERRAL_TRIGGER"] and r.sop_clause == "TMF-ADD-02 A1"

    def test_tmf_a1_before_addendum_effective(self):
        c = make_case("REDEMPTION", SYNTH_TMF, "TS0000004", received="2026-09-10T10:00:00+05:30")
        assert referral.run(c).result == "PASS"

    def test_tmf_a1_synthetic_sip_excluded(self):
        c = make_case("REDEMPTION", SYNTH_TMF, "TS0000004")
        r = referral.run(c)
        assert "TS0000003" in " ".join(e.ref for e in r.evidence) and "TS0000005" not in " ".join(e.ref for e in r.evidence)

    def test_nmf_large_redemption_no_a1(self):
        c = make_case("REDEMPTION", "40115267/30", "T261000031")
        assert referral.run(c).result == "PASS"

    def test_25l_within_14_days(self):
        c = make_case("REDEMPTION", SYNTH_FOLIO, "TS0000002")
        r = referral.run(c)
        assert r.reason_codes == ["REFERRAL_TRIGGER"] and r.sop_clause.endswith("8.3")


# ----------------------------------------------------------------------------- decide
class TestDecide:
    def test_precedence_and_all_codes(self):
        from app.schemas import CheckResult
        checks = [CheckResult(check_id="KYC_STATUS", result="UNABLE_TO_VERIFY", reason_codes=["KYC_UNABLE_TO_VERIFY"]),
                  CheckResult(check_id="THIRD_PARTY_PAYMENT", result="FAIL", reason_codes=["TPP_NO_EXCEPTION"]),
                  CheckResult(check_id="DISTRIBUTOR_CODE", result="FAIL", reason_codes=["ARN_INVALID_DIRECT"])]
        d = decide(checks)
        assert d.outcome == "REJECT" and d.reason_codes == ["TPP_NO_EXCEPTION", "KYC_UNABLE_TO_VERIFY", "ARN_INVALID_DIRECT"]
        assert d.approver_role == "CHECKER" and d.human_approval_required

    def test_utv_without_code_blocks_proceed(self):
        from app.schemas import CheckResult
        d = decide([CheckResult(check_id="BANK_MANDATE", result="UNABLE_TO_VERIFY")])
        assert d.outcome == "PEND"

    def test_all_pass_proceed(self):
        d = run_all(make_case("ADDITIONAL_PURCHASE", "40166450/93", "T260900518", received="2026-09-22T11:05:00+05:30"))
        assert (d.outcome, d.reason_codes, d.human_approval_required, d.approver_role) == ("PROCEED", [], False, None)

    def test_invalid_beats_everything(self):
        from app.schemas import CheckResult
        d = decide([CheckResult(check_id="FOLIO_IDENTITY", result="FAIL", reason_codes=["FOLIO_NOT_FOUND"]),
                    CheckResult(check_id="REFERRAL", result="FAIL", reason_codes=["STOP_LOCK"])])
        assert d.outcome == "INVALID_REQUEST" and not d.human_approval_required
