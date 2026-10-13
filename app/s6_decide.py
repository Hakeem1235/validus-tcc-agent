"""S6: outcome by SOP 9.2 precedence, all reason codes, approver by Annexure A. Deterministic."""
from __future__ import annotations

from dataclasses import dataclass, field

from app.schemas import CheckResult
from app.tools.policy import rules


@dataclass
class Decision:
    outcome: str
    reason_codes: list[str]
    human_approval_required: bool
    approver_role: str | None
    rationale: list[str] = field(default_factory=list)


def outcome_for(check: CheckResult, reason: str) -> str:
    r = rules()
    if check.data.get("outcome"):
        return check.data["outcome"]
    return r["reason_outcome"].get(reason, "PEND")


def decide(checks: list[CheckResult]) -> Decision:
    r = rules()
    order = r["outcome_precedence"]
    candidates: list[tuple[str, str, str]] = []  # (outcome, reason, check)
    rationale = []
    for c in checks:
        if c.result in ("PASS", "NOT_APPLICABLE") and not c.reason_codes:
            continue
        if c.result == "UNABLE_TO_VERIFY" and not c.reason_codes:
            # UTV is never a pass: with no specific code it still blocks PROCEED
            candidates.append(("PEND", "", c.check_id))
            rationale.append(f"{c.check_id} UNABLE_TO_VERIFY -> PEND")
            continue
        for code in c.reason_codes:
            o = outcome_for(c, code)
            candidates.append((o, code, c.check_id))
            rationale.append(f"{c.check_id} {c.result} {code} -> {o} ({c.sop_clause})")
        if c.result == "FAIL" and not c.reason_codes and c.data.get("outcome"):
            candidates.append((c.data["outcome"], "", c.check_id))
            rationale.append(f"{c.check_id} FAIL -> {c.data['outcome']} ({c.sop_clause})")
    if not candidates:
        outcome = "PROCEED"
        rationale.append("all checks PASS / NOT_APPLICABLE -> PROCEED")
    else:
        outcome = min((o for o, _, _ in candidates), key=order.index)
    # reason codes: ordered by outcome severity, then check order; de-duplicated
    codes = [code for o, code, _ in sorted(candidates, key=lambda x: order.index(x[0])) if code]
    codes = list(dict.fromkeys(codes))
    appr = r["approval"][outcome]
    rationale.append(f"9.2 precedence -> {outcome}; Annexure A -> "
                     f"{'approval by ' + appr['role'] if appr['required'] else 'no approval'}")
    return Decision(outcome=outcome, reason_codes=codes, human_approval_required=appr["required"],
                    approver_role=appr["role"], rationale=rationale)
