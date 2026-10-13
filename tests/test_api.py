"""API contract, never-500 guard, reply guard, inbox regression against docs/analysis.md."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas import TCCResponse
from tests.conftest import ROOT

client = TestClient(app)
INBOX = json.loads((ROOT / "Data" / "inbox" / "requests.json").read_text(encoding="utf-8"))
BANNED = ["referral", "refer ", "referred", "suspicious", "compliance", "fiu", "report"]

EXPECTED = {  # docs/analysis.md section 1
    "R01": ("SIP_REGISTRATION", "PROCEED", [], None),
    "R02": ("ADDITIONAL_PURCHASE", "REJECT", ["TPP_NO_EXCEPTION"], "CHECKER"),
    "R03": ("SIP_REGISTRATION", "PEND", ["TPP_DOCS_MISSING"], None),
    "R04": ("ADDITIONAL_PURCHASE", "REJECT", ["KYC_ON_HOLD"], "CHECKER"),
    "R05": ("NEW_FOLIO_PURCHASE", "PEND", ["KYC_REGISTERED_NEW_AMC"], None),
    "R06": ("ADDITIONAL_PURCHASE", "PROCEED", [], None),
    "R07": ("ADDITIONAL_PURCHASE", "REJECT", ["TPP_NO_EXCEPTION"], "CHECKER"),
    "R08": ("ADDITIONAL_PURCHASE", "PROCEED_MODIFIED", ["ARN_INVALID_DIRECT"], "CHECKER"),
    "R09": ("ADDITIONAL_PURCHASE", "PEND", ["KYC_UNABLE_TO_VERIFY"], None),
    "R10": ("REDEMPTION", "HOLD_AND_REFER", ["HIGH_RISK_CONTACT_COB", "COB_COOLING", "BANK_PROOF_REQUIRED"], "OPS_MANAGER"),
}


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


@pytest.mark.parametrize("req", INBOX, ids=[r["request_id"] for r in INBOX])
def test_inbox(req):
    r = client.post("/requests", json=req)
    assert r.status_code == 200
    out = r.json()
    TCCResponse.model_validate(out)
    rtype, outcome, codes, approver = EXPECTED[req["request_id"]]
    assert out["request_type"] == rtype
    assert out["outcome"] == outcome
    assert set(out["reason_codes"]) == set(codes)
    assert out["approver_role"] == approver
    assert [c["check_id"] for c in out["checks"]] and len(out["checks"]) == 8
    for c in out["checks"]:
        if c["result"] == "FAIL" or (outcome != "PROCEED" and c["result"] == "UNABLE_TO_VERIFY"):
            assert c["sop_clause"] and c["evidence"], c
    assert out["draft_reply"]["to"] and out["draft_reply"]["body"]
    if outcome in ("HOLD_AND_REFER", "PEND"):
        assert not any(w in out["draft_reply"]["body"].lower() for w in BANNED)
    assert out["trace"]["documents_used"] and out["trace"]["tools_called"]


@pytest.mark.parametrize("payload", [
    {}, {"request_id": "X"}, {"request_id": "X", "received_at": "not a date", "body": "hello"},
    {"request_id": "X", "received_at": "2026-10-08T10:00:00+05:30", "attachments": [{"file_name": "a.pdf",
     "content_type": "application/pdf", "content_base64": "!!!notbase64"}]},
    {"request_id": "X", "received_at": "2026-10-08T10:00:00+05:30", "attachments": "oops"},
])
def test_never_500(payload):
    r = client.post("/requests", json=payload)
    assert r.status_code == 200
    TCCResponse.model_validate(r.json())


def test_garbage_body_never_500():
    r = client.post("/requests", content=b"\x00not json", headers={"content-type": "application/json"})
    assert r.status_code == 200
    out = r.json()
    TCCResponse.model_validate(out)
    assert out["outcome"] == "PEND" and out["approver_role"] == "CHECKER" and "error" in out
    assert all(c["result"] == "UNABLE_TO_VERIFY" for c in out["checks"])


def _req(body, subject="Request", **kw):
    base = {"request_id": "T1", "received_at": "2026-10-08T10:00:00+05:30", "channel": "email",
            "from": "Some One <some@one.example>", "to": "tcc", "cc": "", "subject": subject, "body": body, "attachments": []}
    base.update(kw)
    return base


def test_typo_folio_invalid_not_nearest():
    out = client.post("/requests", json=_req("Please add Rs 75,000 to folio 40131574/18 by IMPS from my Satpura a/c ending 4455")).json()
    assert out["outcome"] == "INVALID_REQUEST" and out["reason_codes"] == ["FOLIO_NOT_FOUND"]
    assert out["resolved"]["folio_no"] is None


def test_hinglish_stop_lock_redemption():
    out = client.post("/requests", json=_req(
        "Namaste, mujhe folio 40161537/29 se Rs 1,20,000 ka redemption chahiye, Narmada Large Cap. Jaldi karo please.",
        subject="redemption")).json()
    assert out["outcome"] == "HOLD_AND_REFER" and "STOP_LOCK" in out["reason_codes"]
    assert out["approver_role"] == "OPS_MANAGER"
    assert "lock" not in out["draft_reply"]["body"].lower()
