"""Test fixtures: a copy of build/tcc.db plus synthetic rows (tests only; raw data untouched)."""
from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402
from app.case import Case  # noqa: E402
from app.schemas import AttachmentInfo, DocumentRef, ExtractedRequest  # noqa: E402
from app.tools import db  # noqa: E402
from app.tools import folio as folio_tool  # noqa: E402
from app.tools import policy  # noqa: E402


def _insert(con, table, template_where, overrides):
    cols = [r[1] for r in con.execute(f"PRAGMA table_info({table})")]
    row = con.execute(f"SELECT * FROM {table} WHERE {template_where}").fetchone()
    vals = dict(zip(cols, row))
    vals.update(overrides)
    con.execute(f"INSERT INTO {table} VALUES ({','.join('?' for _ in cols)})", [vals[c] for c in cols])


SYNTH_FOLIO = "40199999/11"   # NMF, used for synthetic history scenarios
SYNTH_TMF = "71199999/22"


@pytest.fixture(scope="session", autouse=True)
def test_db(tmp_path_factory):
    if not config.DB_PATH.exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "prepare_data.py")], check=True)
    path = tmp_path_factory.mktemp("db") / "tcc_test.db"
    shutil.copy(config.DB_PATH, path)
    con = sqlite3.connect(path)
    # Synthetic investor with NMF + TMF folios, stale/conflicting KRA variants
    _insert(con, "folio_master", "folio_no='40166450/93'",
            {"folio_no": SYNTH_FOLIO, "first_holder_name": "Test Investor", "first_holder_pan_masked": "TSTPI**11A",
             "folio_flag": "NONE", "contact_last_changed_on": None})
    _insert(con, "folio_master", "folio_no='71167297/25'",
            {"folio_no": SYNTH_TMF, "first_holder_name": "Tmf Investor", "first_holder_pan_masked": "TSTPT**22B",
             "contact_last_changed_on": "2026-09-20"})
    _insert(con, "kra_kyc_snapshot", "pan_masked='YBZPB**44W'",
            {"pan_masked": "TSTPI**11A", "name_as_per_kra": "TEST INVESTOR"})
    _insert(con, "kra_kyc_snapshot", "pan_masked='YBZPB**44W'",
            {"pan_masked": "TSTPT**22B", "name_as_per_kra": "TMF INVESTOR"})
    _insert(con, "kra_kyc_snapshot", "pan_masked='YBZPB**44W'",
            {"pan_masked": "STALE**01S", "name_as_per_kra": "STALE PERSON", "last_checked_at": "2026-10-01 06:00"})
    _insert(con, "kra_kyc_snapshot", "pan_masked='YBZPB**44W'",
            {"pan_masked": "CONFL**02C", "name_as_per_kra": "CONFLICT PERSON", "status_from_text": "ON_HOLD",
             "code_text_conflict": 1, "kra_status": "ON HOLD"})
    _insert(con, "bank_mandates", "folio_no='40166450/93'",
            {"folio_no": SYNTH_FOLIO, "account_no_masked": "XXXXXXXX1111", "account_last4": "1111",
             "account_holders": "TEST INVESTOR"})
    _insert(con, "bank_mandates", "folio_no='71167297/25'",
            {"folio_no": SYNTH_TMF, "account_no_masked": "XXXXXXXX2222", "account_last4": "2222",
             "account_holders": "TMF INVESTOR"})
    base_tx = "txn_id='T260900518'"
    for tid, folio, amc, typ, amt, d, status in [
        ("TS0000001", SYNTH_FOLIO, "NMF", "ADD", 3000000.0, "2026-10-01", "PROCESSED"),   # 30L purchase
        ("TS0000002", SYNTH_FOLIO, "NMF", "RED", 2600000.0, "2026-10-08", "PENDING_TCC"),  # 26L redemption within 14d
        ("TS0000003", SYNTH_TMF, "TMF", "ADD", 100000.0, "2026-09-25", "PROCESSED"),
        ("TS0000004", SYNTH_TMF, "TMF", "RED", 550000.0, "2026-10-08", "PENDING_TCC"),     # A1 trigger
        ("TS0000005", SYNTH_TMF, "TMF", "SIP", 600000.0, "2026-09-01", "PROCESSED"),
    ]:
        _insert(con, "transactions", base_tx,
                {"txn_id": tid, "folio_no": folio, "amc_code": amc, "txn_type": typ, "amount_inr": amt, "txn_date": d,
                 "status": status, "utr": f"UTR{tid}", "remitter_account_masked": None if typ == "RED" else "XXXXXXXX1111",
                 "plan": "DIRECT", "arn": "", "euin": "", "duplicate_of": None, "data_flags": ""})
    con.commit()
    con.close()
    db.use_database(path)
    yield path
    db.use_database(None)


def make_case(request_type: str, folio_no: str | None = None, txn_id: str | None = None,
              received: str = "2026-10-08T12:00:00+05:30", attachments: list[AttachmentInfo] | None = None,
              docs: list[str] | None = None, mentioned: list[str] | None = None, **extracted) -> Case:
    x = ExtractedRequest(**extracted)
    for d in docs or []:
        x.documents_enclosed.append(DocumentRef(type=d, present_as_attachment=True, source=f"{d.lower()}.pdf"))
    for d in mentioned or []:
        x.documents_enclosed.append(DocumentRef(type=d, only_mentioned=True, source="email body"))
    c = Case(request_id="T", received_at=datetime.fromisoformat(received), sender="a@b", subject="", body="",
             extracted=x, attachments=attachments or [], request_type=request_type)
    if folio_no:
        c.folio = folio_tool.get(folio_no)
        assert c.folio, folio_no
        c.amc = c.folio["amc_code"]
        c.first_holder_pan = c.folio["first_holder_pan_masked"]
    if txn_id:
        c.txn = db.query("SELECT * FROM transactions WHERE txn_id=?", (txn_id,))[0]
    c.policy = policy.select(c.received_date, c.amc or x.target_amc)
    if not c.amc:
        c.amc = x.target_amc
    return c
