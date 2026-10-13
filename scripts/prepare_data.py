"""Build reproducible artefacts from the read-only data room.

    python scripts/prepare_data.py [--data Data] [--out build]

Outputs:
    build/tcc.db            SQLite: five cleaned tables (raw values kept alongside normalised ones)
    build/clauses.json      [{doc, doc_id, version, effective_from, amc_scope, clause_id, title, text}]
    build/data_issues.json  one entry per data-quality finding and how the code handles it
Raw files are never modified. Running twice yields identical outputs.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.normalise import (  # noqa: E402
    amc_for_folio,
    iso,
    kra_text_status,
    names_match,
    normalise_folio,
    parse_date,
    parse_kra_code,
)

POLICY_DOCS = [
    # file, doc label, doc_id, version, effective_from, amc_scope
    ("Validus_TCC_SOP_v4.1.docx", "TCC-SOP", "VAL-OPS-TCC-SOP", "4.1", "2026-08-01", "ALL"),
    ("Validus_TCC_SOP_v3.2.pdf", "TCC-SOP", "VAL-OPS-TCC-SOP", "3.2", "2025-01-01", "ALL"),
    ("Tungabhadra_MF_Client_Addendum_TMF-ADD-02.pdf", "TMF-ADD-02", "TMF-ADD-02", "02", "2026-09-15", "TMF"),
]

issues: list[dict] = []


def issue(file: str, kind: str, ref: str, detail: str, handling: str) -> None:
    issues.append({"file": file, "issue": kind, "ref": ref, "detail": detail, "handling": handling})


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# --------------------------------------------------------------------------- tables
def build_folio(rows):
    out = []
    for r in rows:
        f = normalise_folio(r["folio_no"])
        if f != r["folio_no"]:
            issue("folio_master.csv", "folio_format", r["folio_no"], "non-canonical folio", "normalised")
        if r["folio_no"][:3] and amc_for_folio(f) != r["amc_code"]:
            issue("folio_master.csv", "amc_prefix_mismatch", r["folio_no"], r["amc_code"], "folio row trusted; flagged")
        if r["tax_status"].startswith("02") and not (r["guardian_name"] and r["minor_dob"]):
            issue("folio_master.csv", "minor_missing_guardian", r["folio_no"], "minor folio without guardian/DOB",
                  "MINOR_RULES returns UNABLE_TO_VERIFY")
        out.append({
            **r,
            "folio_no": f,
            "folio_no_raw": r["folio_no"],
            "minor_dob": iso(parse_date(r["minor_dob"])),
            "contact_last_changed_on": iso(parse_date(r["contact_last_changed_on"])),
            "opened_on": iso(parse_date(r["opened_on"])),
        })
    return out


def build_bank(rows, folios):
    out = []
    for r in rows:
        f = normalise_folio(r["folio_no"])
        if f not in folios:
            issue("bank_mandates.csv", "orphan_mandate", r["folio_no"], "folio not in folio master", "ignored by lookups")
        digits = re.sub(r"\D", "", r["account_no_masked"])
        if r["status"] == "VALIDATED" and not r["registered_on"]:
            issue("bank_mandates.csv", "validated_without_date", f"{r['folio_no']}|{r['account_no_masked']}",
                  "VALIDATED with blank registered_on", "status trusted; flagged")
        out.append({
            **r,
            "folio_no": f,
            "account_last4": digits[-4:],
            "registered_on": iso(parse_date(r["registered_on"])),
            "cob_request_received_on": iso(parse_date(r["cob_request_received_on"])),
        })
    masks = Counter(len(r["account_no_masked"]) for r in rows)
    if len(masks) > 1:
        odd = [f"{r['folio_no']}|{r['account_no_masked']}" for r in rows if len(r["account_no_masked"]) != masks.most_common(1)[0][0]]
        issue("bank_mandates.csv", "inconsistent_account_mask", "; ".join(odd), f"mask lengths {dict(masks)}",
              "accounts matched on last 4 digits within the folio")
    # first holder should be on every validated mandate (6.1)
    return out


def build_kra(rows):
    out = []
    for r in rows:
        code, agency, status_code = parse_kra_code(r["kra_status_code"])
        status_text = kra_text_status(r["kra_status"])
        flags = []
        if code and code != r["kra_status_code"].strip():
            flags.append("code_padded")
            issue("kra_kyc_snapshot.csv", "kra_code_leading_zero_lost", r["pan_masked"],
                  f"code '{r['kra_status_code']}' -> '{code}'", "left-padded to 3 digits")
        if agency and agency != r["kra_name"]:
            flags.append("agency_mismatch")
            issue("kra_kyc_snapshot.csv", "kra_agency_mismatch", r["pan_masked"],
                  f"code digit says {agency}, kra_name {r['kra_name']}", "KYC check returns UNABLE_TO_VERIFY")
        if not r["kra_status"].strip():
            flags.append("blank_text")
            issue("kra_kyc_snapshot.csv", "kra_status_text_blank", r["pan_masked"], f"code {code}",
                  "status derived from code")
        elif status_text is None:
            flags.append("unknown_text")
            issue("kra_kyc_snapshot.csv", "kra_status_text_unknown", r["pan_masked"], r["kra_status"],
                  "status derived from code")
        conflict = bool(status_text and status_code and status_text != status_code)
        if conflict:
            flags.append("code_text_conflict")
            issue("kra_kyc_snapshot.csv", "kra_code_text_conflict", r["pan_masked"],
                  f"code {code}={status_code} vs text '{r['kra_status']}'", "KYC check returns UNABLE_TO_VERIFY")
        if status_code is None:
            flags.append("unknown_code")
            issue("kra_kyc_snapshot.csv", "kra_code_invalid", r["pan_masked"], repr(r["kra_status_code"]),
                  "KYC check returns UNABLE_TO_VERIFY")
        out.append({
            **r,
            "kra_status_code_raw": r["kra_status_code"],
            "kra_status_code": code,
            "status_from_code": status_code,
            "status_from_text": status_text,
            "code_text_conflict": int(conflict),
            "dob": iso(parse_date(r["dob"])),
            "data_flags": ",".join(flags),
        })
    texts = Counter(r["kra_status"] for r in rows if r["kra_status"])
    variants = [t for t in texts if kra_text_status(t) == "VALIDATED"]
    if len(variants) > 1:
        issue("kra_kyc_snapshot.csv", "kra_status_text_variants", "", f"{variants}", "case-insensitive synonym map")
    stamps = Counter(r["last_checked_at"] for r in rows)
    issue("kra_kyc_snapshot.csv", "lookup_timestamps", "", f"{dict(stamps)}",
          "staleness measured against request received_at (24h rule, SOP 4.5)")
    return out


def build_txn(rows, folios):
    out = []
    for r in rows:
        f = normalise_folio(r["folio_no"])
        d = parse_date(r["txn_date"])
        flags = []
        if r["folio_no"] != f:
            flags.append("folio_format")
        if r["txn_date"] and d and r["txn_date"] != d.isoformat():
            flags.append("date_format")
        if f not in folios:
            flags.append("orphan_folio")
            issue("transactions.csv", "orphan_txn", r["txn_id"], r["folio_no"], "excluded from folio history")
        if f and amc_for_folio(f) != r["amc_code"]:
            flags.append("amc_prefix_mismatch")
            issue("transactions.csv", "amc_prefix_mismatch", r["txn_id"], f"{r['folio_no']} vs {r['amc_code']}", "flagged")
        for col in ("units", "nav", "amount_inr"):
            if r[col] and float(r[col]) <= 0:
                flags.append(f"nonpositive_{col}")
        if any(x.startswith("nonpositive") for x in flags):
            issue("transactions.csv", "negative_units_or_nav", r["txn_id"],
                  f"units={r['units']} nav={r['nav']} amount={r['amount_inr']}",
                  "flagged; units/NAV never used; warning when the folio is checked")
        if r["plan"] == "REGULAR" and not r["arn"]:
            flags.append("regular_without_arn")
        if r["plan"] == "DIRECT" and (r["arn"] or r["euin"]):
            flags.append("direct_with_arn")
        out.append({
            **r,
            "folio_no": f,
            "folio_no_raw": r["folio_no"],
            "txn_date": iso(d),
            "txn_date_raw": r["txn_date"],
            "amount_inr": float(r["amount_inr"]) if r["amount_inr"] else None,
            "units": float(r["units"]) if r["units"] else None,
            "nav": float(r["nav"]) if r["nav"] else None,
            "duplicate_of": None,
            "data_flags": flags,
        })
    # summary issues for format noise (one line each, with refs)
    for flag, kind, handling in [
        ("folio_format", "txn_folio_format", "normalised to XXXXXXXX/XX; raw kept in folio_no_raw"),
        ("date_format", "txn_date_format", "parsed DD-MM-YYYY to ISO; raw kept in txn_date_raw"),
        ("regular_without_arn", "regular_plan_without_arn",
         "flagged; a pending Regular txn with no ARN is treated as invalid ARN (SOP 7.2)"),
        ("direct_with_arn", "direct_plan_with_arn", "flagged; distributor check not applicable to Direct"),
    ]:
        refs = [t["txn_id"] for t in out if flag in t["data_flags"]]
        if refs:
            issue("transactions.csv", kind, ", ".join(refs), f"{len(refs)} rows", handling)
    # exact duplicates: same folio, type, amount, date, utr/remitter
    groups = defaultdict(list)
    for t in out:
        key = (t["folio_no"], t["txn_type"], t["amount_inr"], t["txn_date"], t["utr"], t["remitter_account_masked"], t["scheme_code"])
        groups[key].append(t)
    for key, grp in groups.items():
        if len(grp) > 1:
            grp.sort(key=lambda t: t["txn_id"])
            for dup in grp[1:]:
                dup["duplicate_of"] = grp[0]["txn_id"]
                dup["data_flags"].append("duplicate")
            issue("transactions.csv", "duplicate_transaction", ", ".join(t["txn_id"] for t in grp),
                  f"identical folio/type/amount/date/utr ({key[4] or 'no utr'}) status={[t['status'] for t in grp]}",
                  "flagged; later id marked duplicate_of; excluded from aggregations; pending match resolves to the first id with a warning")
    for t in out:
        t["data_flags"] = ",".join(t["data_flags"])
    return out


def build_distributor(rows):
    out = []
    for r in rows:
        out.append({**r, "arn_valid_till": iso(parse_date(r["arn_valid_till"])),
                    "euin_valid_till": iso(parse_date(r["euin_valid_till"]))})
    return out


def check_names(folios, kra, banks):
    kra_by_pan = {k["pan_masked"]: k for k in kra}
    pans = Counter()
    for f in folios:
        for pc, nc in (("first_holder_pan_masked", "first_holder_name"), ("second_holder_pan_masked", "second_holder_name"),
                       ("guardian_pan_masked", "guardian_name")):
            pan = f[pc]
            if not pan:
                continue
            pans[pan] += 1
            if not re.fullmatch(r"[A-Z]{3}[PCHFATBLJG][A-Z]\*\*\d{2}[A-Z]", pan):
                issue("folio_master.csv", "pan_mask_format", f"{f['folio_no']}|{pc}", pan, "flagged; PAN compared verbatim")
            k = kra_by_pan.get(pan)
            if not k:
                issue("folio_master.csv", "pan_not_in_kra", f"{f['folio_no']}|{pc}", pan, "KYC check returns UNABLE_TO_VERIFY")
            elif f[nc].strip().upper() != k["name_as_per_kra"].strip().upper():
                how = "tolerant match OK" if names_match(f[nc], k["name_as_per_kra"]) else "NO tolerant match"
                issue("folio_master.csv", "holder_name_differs_from_kra", f"{f['folio_no']}|{pc}",
                      f"'{f[nc]}' vs KRA '{k['name_as_per_kra']}' ({how})",
                      "identity by folio+PAN; names compared with tolerant matcher using folio and KRA names")
    for b in banks:
        f = next((x for x in folios if x["folio_no"] == b["folio_no"]), None)
        if not f or b["status"] != "VALIDATED":
            continue
        holders = [h.strip() for h in b["account_holders"].split(";")]
        cands = [f["first_holder_name"], kra_by_pan.get(f["first_holder_pan_masked"], {}).get("name_as_per_kra")]
        if f["tax_status"].startswith("02"):
            cands += [f["guardian_name"]]
        if not any(names_match(c, h) for c in cands if c for h in holders):
            issue("bank_mandates.csv", "first_holder_not_on_mandate", f"{b['folio_no']}|{b['account_no_masked']}",
                  f"holders '{b['account_holders']}' vs first holder '{f['first_holder_name']}'", "flagged")


# --------------------------------------------------------------------------- policies
CLAUSE_RE = re.compile(r"^(\d{1,2}\.\d{1,2})\s+(.*)$")
SECTION_RE = re.compile(r"^(\d{1,2})\.\s+([A-Z].*)$")
ANNEX_RE = re.compile(r"^Annexure\s+([A-D])\s*[—-]\s*(.*)$")
ADD_RE = re.compile(r"^(A\d)\s+(.*)$")


def docx_lines(path: Path) -> list[str]:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(str(path))
    lines = []
    for el in d.element.body.iterchildren():
        tag = el.tag.split("}")[-1]
        if tag == "p":
            t = Paragraph(el, d).text.strip()
            if t:
                lines.append(t)
        elif tag == "tbl":
            for row in Table(el, d).rows:
                cells, seen = [], set()
                for c in row.cells:
                    if id(c._tc) in seen:  # horizontally merged cell repeats the same element
                        continue
                    seen.add(id(c._tc))
                    cells.append(" ".join(c.text.split()))
                lines.append("    " + " | ".join(cells))
    return lines


def pdf_lines(path: Path) -> list[str]:
    import pdfplumber

    lines = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            # Drop the diagonal watermark (very large glyphs) and the grey running header/footer.
            clean = page.filter(lambda o: o.get("object_type") != "char" or (o.get("size", 0) < 20 and o.get("size", 0) > 8))
            text = clean.extract_text() or ""
            for ln in text.splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("Validus — Investor Services Operations") or ln.startswith("Uncontrolled when printed"):
                    continue
                lines.append(ln)
    return lines


def split_clauses(lines: list[str], doc_meta: tuple) -> list[dict]:
    file, doc, doc_id, version, eff, scope = doc_meta
    clauses: list[dict] = []
    cur = {"clause_id": "header", "title": "Document control", "lines": []}
    section_title = ""

    def flush():
        if cur["lines"]:
            clauses.append({
                "doc": doc, "doc_id": doc_id, "version": version, "effective_from": eff, "amc_scope": scope,
                "source_file": file, "clause_id": cur["clause_id"], "title": cur["title"],
                "text": "\n".join(cur["lines"]).strip(),
            })

    for ln in lines:
        raw = ln.strip()
        m_sec, m_cl, m_an = SECTION_RE.match(raw), CLAUSE_RE.match(raw), ANNEX_RE.match(raw)
        m_add = ADD_RE.match(raw) if doc != "TCC-SOP" else None
        if m_an:
            flush()
            cur = {"clause_id": f"Annex {m_an.group(1)}", "title": m_an.group(2), "lines": [raw]}
        elif m_add:
            flush()
            cur = {"clause_id": m_add.group(1), "title": m_add.group(2).split(".")[0], "lines": [raw]}
        elif m_cl and not ln.startswith("    ") and not cur["clause_id"].startswith("Annex"):
            flush()
            cur = {"clause_id": m_cl.group(1), "title": section_title, "lines": [raw]}
        elif m_sec and not ln.startswith("    ") and len(raw) < 60 and not cur["clause_id"].startswith("Annex"):
            flush()
            section_title = m_sec.group(2)
            cur = {"clause_id": m_sec.group(1), "title": section_title, "lines": [raw]}
        else:
            cur["lines"].append(ln.rstrip())
    flush()
    # Merge duplicate ids (e.g. a section intro split across pages)
    merged: dict[str, dict] = {}
    for c in clauses:
        if c["clause_id"] in merged:
            merged[c["clause_id"]]["text"] += "\n" + c["text"]
        else:
            merged[c["clause_id"]] = c
    return list(merged.values())


def build_clauses(policy_dir: Path) -> list[dict]:
    out = []
    for meta in POLICY_DOCS:
        path = policy_dir / meta[0]
        lines = docx_lines(path) if path.suffix == ".docx" else pdf_lines(path)
        cl = split_clauses(lines, meta)
        out.extend(cl)
    # sanity: watermark residue in v3.2
    for c in out:
        if c["version"] == "3.2" and re.search(r"\b[A-Z]\b\s*$", c["text"], re.M) and re.search(r"(?m)^[DESRUP]$", c["text"]):
            issue(c["source_file"], "watermark_residue", c["clause_id"], "single-letter lines remain", "review extraction")
    issue("Validus_TCC_SOP_v3.2.pdf", "pdf_watermark", "all pages",
          "diagonal 'SUPERSEDED' watermark glyphs (~72pt, red) interleave with body text in naive extraction",
          "pdfplumber char filter drops glyphs >20pt and the 7.5pt running header/footer")
    issue("policies/", "missing_policy_version", "SOP v4.0 (eff. 2026-06-01); TMF-ADD-01 (eff. 2026-03-01)",
          "referenced in revision history / supersedes line but not provided",
          "requests in those windows use the latest available earlier version with a warning")
    return out


# --------------------------------------------------------------------------- sqlite
def write_table(con, name, rows, pk=None):
    cols = list(rows[0].keys())
    con.execute(f"DROP TABLE IF EXISTS {name}")
    con.execute(f"CREATE TABLE {name} ({', '.join(f'\"{c}\"' for c in cols)})")
    con.executemany(f"INSERT INTO {name} VALUES ({', '.join('?' for _ in cols)})", [tuple(r[c] for c in cols) for r in rows])
    if pk:
        for col in pk:
            con.execute(f"CREATE INDEX idx_{name}_{col} ON {name}(\"{col}\")")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "Data"))
    ap.add_argument("--out", default=str(ROOT / "build"))
    a = ap.parse_args()
    data, out = Path(a.data), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    issues.clear()

    raw = {n: read_csv(data / "data" / f"{n}.csv") for n in
           ("folio_master", "bank_mandates", "kra_kyc_snapshot", "transactions", "distributor_master")}
    folios = build_folio(raw["folio_master"])
    folio_set = {f["folio_no"] for f in folios}
    banks = build_bank(raw["bank_mandates"], folio_set)
    kra = build_kra(raw["kra_kyc_snapshot"])
    txns = build_txn(raw["transactions"], folio_set)
    dist = build_distributor(raw["distributor_master"])
    check_names(folios, kra, banks)
    clauses = build_clauses(data / "policies")

    db = out / "tcc.db"
    if db.exists():
        db.unlink()
    con = sqlite3.connect(db)
    write_table(con, "folio_master", folios, ["folio_no", "first_holder_pan_masked"])
    write_table(con, "bank_mandates", banks, ["folio_no"])
    write_table(con, "kra_kyc_snapshot", kra, ["pan_masked"])
    write_table(con, "transactions", txns, ["folio_no", "utr"])
    write_table(con, "distributor_master", dist, ["arn"])
    con.commit()
    con.close()

    (out / "clauses.json").write_text(json.dumps(clauses, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "data_issues.json").write_text(json.dumps(issues, indent=1, ensure_ascii=False), encoding="utf-8")

    print("Record counts (raw -> loaded):")
    for name, rows in (("folio_master", folios), ("bank_mandates", banks), ("kra_kyc_snapshot", kra),
                       ("transactions", txns), ("distributor_master", dist)):
        print(f"  {name:20s} {len(raw[name]):4d} -> {len(rows):4d}")
    print(f"  clauses              {len(clauses)} ({', '.join(f'{d} v{v}: {n}' for (d, v), n in Counter((c['doc'], c['version']) for c in clauses).items())})")
    print(f"  data issues          {len(issues)} ({dict(Counter(i['issue'] for i in issues))})")
    print(f"Wrote {db}, {out / 'clauses.json'}, {out / 'data_issues.json'}")


if __name__ == "__main__":
    main()
