"""S3 identity resolution, S4 policy selection, normalisers."""
from __future__ import annotations

from datetime import date

import pytest

from app.normalise import names_match, normalise_folio, parse_kra_code
from app.s3_resolve import pan_compatible, resolve
from app.tools.policy import clause, search, select
from tests.conftest import make_case


@pytest.mark.parametrize("raw,expected", [
    ("4011882323", "40118823/23"), ("40118823/23", "40118823/23"), ("40115267 / 30", "40115267/30"),
    ("71167297 / 25", "71167297/25"), ("40131574-17", "40131574/17"), ("401188232", None), ("5011882323", None),
])
def test_normalise_folio(raw, expected):
    assert normalise_folio(raw) == expected


def test_kra_code_padding():
    assert parse_kra_code("7") == ("007", "CVL", "VALIDATED")
    assert parse_kra_code("399") == ("399", "CAMS", "NOT_REACHABLE")


@pytest.mark.parametrize("a,b,ok", [
    ("R K BHAT", "RAVI KUMAR BHAT", True), ("Hegde Ajay", "AJAY HEGDE", True), ("Mr. Yusuf Shah", "YUSUF SHAH", True),
    ("B. Gupta", "BHAVANA GUPTA", True), ("VASANT G KULKARNI", "ROHAN KULKARNI", False),
    ("RAGHAVAN SRINIVASAN", "PRIYA RAGHAVAN", False), ("LAKSHMI V", "LAKSHMI VENKATARAMAN", True),
])
def test_names_match(a, b, ok):
    assert names_match(a, b) is ok


def test_pan_compatible():
    assert pan_compatible("YBZPB**44W", "YBZPB**44W")
    assert pan_compatible("YBZPB1244W", "YBZPB**44W")
    assert not pan_compatible("YBZPB**45W", "YBZPB**44W")


class TestResolve:
    def test_canonical_and_txn(self):
        c = make_case("ADDITIONAL_PURCHASE", amount_inr=75000, utr="KNKMH2610083446586", request_type_hint="ADDITIONAL_PURCHASE")
        resolve(c, ["40131574-17"], [])
        assert c.folio["folio_no"] == "40131574/17" and c.txn["txn_id"] == "T261000028" and not c.identity_failure

    def test_typo_folio_is_not_found(self):
        c = make_case("ADDITIONAL_PURCHASE")
        resolve(c, ["4013157418"], [])
        assert c.identity_failure == "FOLIO_NOT_FOUND" and c.folio is None

    def test_short_folio_invalid(self):
        c = make_case("ADDITIONAL_PURCHASE")
        resolve(c, [], ["401315741"])
        assert c.identity_failure == "FOLIO_NOT_FOUND"

    def test_pan_mismatch(self):
        c = make_case("ADDITIONAL_PURCHASE", pan="ABCPD**12E")
        resolve(c, ["40131574/17"], [])
        assert c.identity_failure == "FOLIO_PAN_MISMATCH"

    def test_name_mismatch(self):
        c = make_case("ADDITIONAL_PURCHASE", investor_name="Vikram Shetty")
        resolve(c, ["40131574/17"], [])
        assert c.identity_failure == "FOLIO_PAN_MISMATCH"

    def test_duplicate_pending_resolves_first_with_warning(self):
        c = make_case("ADDITIONAL_PURCHASE", amount_inr=200000, utr="VNDYN2610073906590")
        resolve(c, ["40159954/10"], [])
        assert c.txn["txn_id"] == "T261000021" and any("T261050021" in w for w in c.warnings)

    def test_processed_txn_matched_by_utr(self):
        c = make_case("ADDITIONAL_PURCHASE", received="2026-09-22T11:05:00+05:30", utr="VNDYN2609229076583", amount_inr=75000)
        resolve(c, ["4016645093"], [])
        assert c.txn["txn_id"] == "T260900518" and any("PROCESSED" in w for w in c.warnings)

    def test_other_amc_folio_means_new_folio(self):
        c = make_case("NEW_FOLIO_PURCHASE", target_amc="TMF", investor_name="Lakshmi Venkataraman")
        resolve(c, ["40104822/68"], [])
        assert c.folio is None and c.amc == "TMF" and c.first_holder_pan == "XZDPV**82H"
        assert c.referenced_folios == ["40104822/68"]

    def test_attachment_folio_conflict(self):
        from app.schemas import AttachmentInfo
        c = make_case("SIP_REGISTRATION", attachments=[AttachmentInfo(file_name="f.jpg", folio_raw="71138631/22")])
        resolve(c, ["71138631/21"], [])
        assert c.identity_failure == "FOLIO_PAN_MISMATCH"


class TestPolicy:
    def test_v41_current(self):
        s = select(date(2026, 10, 6), "NMF")
        assert s.sop_version == "4.1" and s.addenda == []

    def test_tmf_addendum(self):
        s = select(date(2026, 10, 8), "TMF")
        assert s.sop_version == "4.1" and s.addendum_docs == ["TMF-ADD-02"]

    def test_tmf_before_addendum_warns_add01(self):
        s = select(date(2026, 9, 1), "TMF")
        assert s.addenda == [] and any("TMF-ADD-01" in w for w in s.warnings)

    def test_v32_window(self):
        assert select(date(2026, 3, 1), "NMF").sop_version == "3.2"

    def test_v40_gap_falls_back_with_warning(self):
        s = select(date(2026, 7, 1), "NMF")
        assert s.sop_version == "3.2" and any("v4.0" in w for w in s.warnings)

    def test_clause_retrieval_by_version(self):
        assert "grandparent" in clause("TCC-SOP", "4.1", "5.4")
        assert "Rs 50,000" in clause("TCC-SOP", "3.2", "5.4")
        assert "SUPERSEDED" not in clause("TCC-SOP", "3.2", "5.4")

    def test_search_filtered(self):
        hits = search("grandparent paying for minor", [("TCC-SOP", "4.1")])
        assert hits and all(h["version"] == "4.1" for h in hits) and hits[0]["clause_id"] in ("5.4", "5.3")
