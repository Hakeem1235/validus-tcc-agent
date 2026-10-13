"""Pure normalisation helpers shared by data prep and the runtime pipeline."""
from __future__ import annotations

import re
from datetime import date, datetime

AMC_PREFIX = {"401": "NMF", "711": "TMF"}

KRA_AGENCY = {"0": "CVL", "1": "NDML", "2": "DOTEX", "3": "CAMS", "5": "KFIN"}
KRA_STATUS = {
    "07": "VALIDATED",
    "02": "REGISTERED",
    "03": "ON_HOLD",
    "04": "REJECTED",
    "01": "UNDER_PROCESS",
    "05": "NOT_AVAILABLE",
    "99": "NOT_REACHABLE",
}
# Status text as returned by the KRA -> canonical status (checked by substring, longest first)
KRA_TEXT_SYNONYMS = [
    ("WEB SERVICE NOT REACHABLE", "NOT_REACHABLE"),
    ("NOT REACHABLE", "NOT_REACHABLE"),
    ("UNDER PROCESS", "UNDER_PROCESS"),
    ("NOT AVAILABLE", "NOT_AVAILABLE"),
    ("ON HOLD", "ON_HOLD"),
    ("REJECTED", "REJECTED"),
    ("REGISTERED", "REGISTERED"),
    ("VALIDATED", "VALIDATED"),
]

SALUTATIONS = {"MR", "MRS", "MS", "MISS", "SMT", "SHRI", "SRI", "DR", "KUM", "M/S", "MASTER", "BABY"}


def normalise_folio(raw: str | None) -> str | None:
    """Strip everything but digits; valid only if exactly 10 digits with a known AMC prefix."""
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) != 10 or digits[:3] not in AMC_PREFIX:
        return None
    return f"{digits[:8]}/{digits[8:]}"


def amc_for_folio(folio: str | None) -> str | None:
    if not folio:
        return None
    return AMC_PREFIX.get(re.sub(r"\D", "", folio)[:3])


def parse_date(raw: str | None) -> date | None:
    """Accept YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY (with or without time)."""
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d", "%Y-%m-%d %H:%M", "%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def iso(d: date | None) -> str | None:
    return d.isoformat() if d else None


def parse_kra_code(raw: str | None) -> tuple[str | None, str | None, str | None]:
    """Return (padded_code, agency_from_code, status_from_code)."""
    if raw is None or str(raw).strip() == "":
        return None, None, None
    s = re.sub(r"\D", "", str(raw))
    if not s or len(s) > 3:
        return None, None, None
    code = s.zfill(3)
    return code, KRA_AGENCY.get(code[0]), KRA_STATUS.get(code[1:])


def kra_text_status(text: str | None) -> str | None:
    if not text:
        return None
    t = text.upper()
    for needle, status in KRA_TEXT_SYNONYMS:
        if needle in t:
            return status
    return None


def name_tokens(name: str | None) -> list[str]:
    if not name:
        return []
    s = re.sub(r"[^A-Za-z/ ]", " ", name.upper().replace(".", " "))
    return [t for t in s.split() if t and t not in SALUTATIONS]


def names_match(a: str | None, b: str | None) -> bool:
    """Tolerant person-name match: ignores salutations, order, and allows initials.

    Every token of the shorter name must match a token of the longer one, where a
    single-letter token matches any token with that initial. Surname-like full tokens
    must match exactly, and at least one full (len>1) token must be shared.
    """
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    short, long_ = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    remaining = list(long_)
    shared_full = False
    for t in short:
        hit = None
        if len(t) > 1 and t in remaining:
            hit, shared_full = t, True
        else:
            for r in remaining:
                if (len(t) == 1 and r.startswith(t)) or (len(r) == 1 and t.startswith(r)):
                    hit = r
                    break
        if hit is None:
            return False
        remaining.remove(hit)
    return shared_full


def last4(account: str | None) -> str | None:
    if not account:
        return None
    d = re.sub(r"\D", "", str(account))
    return d[-4:] if len(d) >= 4 else None


def financial_year(d: date) -> str:
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-{str(start + 1)[2:]}"
