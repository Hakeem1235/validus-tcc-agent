"""The Case: everything the checks need, assembled by S1-S4."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from app.schemas import AttachmentInfo, ExtractedRequest
from app.tools.policy import PolicySelection

PURCHASE_TYPES = {"NEW_FOLIO_PURCHASE", "ADDITIONAL_PURCHASE", "SIP_REGISTRATION", "SIP_INSTALMENT"}


@dataclass
class Case:
    request_id: str
    received_at: datetime
    sender: str
    subject: str
    body: str
    extracted: ExtractedRequest
    attachments: list[AttachmentInfo] = field(default_factory=list)
    request_type: str = "OTHER"
    folio: dict | None = None
    amc: str | None = None
    first_holder_pan: str | None = None
    investor_pans: list[str] = field(default_factory=list)  # PANs whose KYC must be checked
    txn: dict | None = None
    policy: PolicySelection | None = None
    identity_failure: str | None = None  # FOLIO_NOT_FOUND / FOLIO_PAN_MISMATCH
    identity_evidence: list = field(default_factory=list)
    identity_notes: list[str] = field(default_factory=list)
    referenced_folios: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def received_date(self) -> date:
        return self.received_at.date()

    @property
    def is_purchase(self) -> bool:
        return self.request_type in PURCHASE_TYPES

    @property
    def is_redemption(self) -> bool:
        return self.request_type == "REDEMPTION"

    def documents(self) -> dict[str, list]:
        """doc type -> list of DocumentRef that are actually enclosed (attachments)."""
        out: dict[str, list] = {}
        for d in self.extracted.documents_enclosed:
            if d.present_as_attachment:
                out.setdefault(d.type, []).append(d)
        return out

    def has_doc(self, doc_type: str) -> bool:
        return doc_type in self.documents()

    def mentioned_only(self, doc_type: str) -> bool:
        return any(d.type == doc_type and d.only_mentioned and not d.present_as_attachment
                   for d in self.extracted.documents_enclosed)

    def amount(self) -> float | None:
        if self.txn and self.txn.get("amount_inr") is not None:
            return float(self.txn["amount_inr"])
        return self.extracted.amount_inr

    def payment_mode(self) -> str | None:
        if self.txn and self.txn.get("payment_mode"):
            return self.txn["payment_mode"]
        pm = (self.extracted.payment_mode or "").upper()
        return pm or None

    def plan(self) -> str | None:
        if self.txn and self.txn.get("plan"):
            return self.txn["plan"]
        return self.extracted.plan

    def sop(self, clause_id: str) -> str:
        return self.policy.sop_ref(clause_id)
