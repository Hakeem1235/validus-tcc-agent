"""Helpers shared by checks."""
from __future__ import annotations

from app.schemas import CheckResult, Evidence
from app.tools.policy import rules


def ev(source: str, ref: str, value: str) -> Evidence:
    return Evidence(source=source, ref=str(ref), value=str(value))


def na(check_id: str, why: str, clause: str | None = None) -> CheckResult:
    return CheckResult(check_id=check_id, result="NOT_APPLICABLE", sop_clause=clause,
                       evidence=[ev("request", "scope", why)], notes=[why])


def utv(check_id: str, why: str, clause: str | None, reasons: list[str] | None = None,
        evidence: list[Evidence] | None = None) -> CheckResult:
    return CheckResult(check_id=check_id, result="UNABLE_TO_VERIFY", sop_clause=clause,
                       evidence=(evidence or []) + [ev("system", "unable_to_verify", why)],
                       reason_codes=reasons or [], notes=[why])


def R() -> dict:
    return rules()
