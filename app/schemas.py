"""API contract (request/response) and internal models."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RequestType = Literal[
    "NEW_FOLIO_PURCHASE", "ADDITIONAL_PURCHASE", "SIP_REGISTRATION", "SIP_INSTALMENT",
    "REDEMPTION", "CHANGE_OF_BANK", "OTHER",
]
Outcome = Literal["PROCEED", "PROCEED_MODIFIED", "PEND", "REJECT", "HOLD_AND_REFER", "INVALID_REQUEST"]
CheckId = Literal[
    "KYC_STATUS", "THIRD_PARTY_PAYMENT", "BANK_MANDATE", "COB_COOLING",
    "DISTRIBUTOR_CODE", "MINOR_RULES", "REFERRAL", "FOLIO_IDENTITY",
]
CheckResultValue = Literal["PASS", "FAIL", "NOT_APPLICABLE", "UNABLE_TO_VERIFY"]
ApproverRole = Literal["CHECKER", "OPS_MANAGER"]

CHECK_ORDER: list[str] = [
    "FOLIO_IDENTITY", "KYC_STATUS", "THIRD_PARTY_PAYMENT", "BANK_MANDATE",
    "COB_COOLING", "DISTRIBUTOR_CODE", "MINOR_RULES", "REFERRAL",
]


# ----------------------------------------------------------------------------- request
class Attachment(BaseModel):
    model_config = ConfigDict(extra="allow")
    file_name: str = ""
    content_type: str = ""
    content_base64: str = ""


class TCCRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    request_id: str = ""
    received_at: str = ""
    channel: str = "email"
    from_: str = Field(default="", alias="from")
    to: str = ""
    cc: str = ""
    subject: str = ""
    body: str = ""
    attachments: list[Attachment] = Field(default_factory=list)


# ----------------------------------------------------------------------------- response
class Evidence(BaseModel):
    source: str
    ref: str
    value: str


class Resolved(BaseModel):
    folio_no: Optional[str] = None
    amc_code: Optional[Literal["NMF", "TMF"]] = None
    first_holder_pan_masked: Optional[str] = None
    txn_id: Optional[str] = None


class Check(BaseModel):
    check_id: CheckId
    result: CheckResultValue
    evidence: list[Evidence] = Field(default_factory=list)
    sop_clause: Optional[str] = None


class DraftReply(BaseModel):
    to: str = ""
    subject: str = ""
    body: str = ""


class ModelCall(BaseModel):
    model_config = ConfigDict(extra="allow")
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class DocumentUsed(BaseModel):
    document: str
    version: str


class Trace(BaseModel):
    model_config = ConfigDict(extra="allow")
    model_calls: list[ModelCall] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    documents_used: list[DocumentUsed] = Field(default_factory=list)
    cost_usd: float = 0.0


class TCCResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    request_id: str
    request_type: RequestType
    resolved: Resolved
    outcome: Outcome
    reason_codes: list[str] = Field(default_factory=list)
    checks: list[Check]
    human_approval_required: bool
    approver_role: Optional[ApproverRole] = None
    draft_reply: DraftReply
    trace: Trace


# ----------------------------------------------------------------------------- internal
DocType = Literal[
    "TPP_DECLARATION", "EMPLOYER_DECLARATION", "EMPLOYEE_LIST", "KYC_ACK_INVESTOR", "KYC_ACK_THIRD_PARTY",
    "CUSTODIAN_SEBI_REG", "DISTRIBUTOR_LIST", "CORPORATE_LIST", "KYC_PAYER", "BANK_STATEMENT",
    "TRANSFER_INSTRUCTION", "CANCELLED_CHEQUE", "PASSBOOK", "BANK_LETTER", "BANKER_CERTIFICATE", "COB_FORM",
    "EXISTING_BANK_PROOF", "EXECUTION_ONLY_DECLARATION", "CHANGE_OF_STATUS_FORM", "REDEMPTION_FORM", "OTHER",
]


class DocumentRef(BaseModel):
    type: str
    present_as_attachment: bool = False
    only_mentioned: bool = False
    source: Optional[str] = None  # attachment file name or "email body"
    detail: Optional[str] = None


class AttachmentInfo(BaseModel):
    """What S1 learned about one attachment (deterministic parse + optional vision transcription)."""
    file_name: str
    content_type: str = ""
    method: str = "none"  # pdf | docx | vision | text | none
    text: str = ""
    doc_types: list[str] = Field(default_factory=list)
    account_last4: Optional[str] = None
    account_holders: list[str] = Field(default_factory=list)
    ifsc: Optional[str] = None
    amount_inr: Optional[float] = None
    utr: Optional[str] = None
    doc_date: Optional[str] = None
    folio_raw: Optional[str] = None
    ticked: list[str] = Field(default_factory=list)  # boxes ticked on a form (informational only)
    flags: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None


class ExtractedRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    request_type_hint: Optional[str] = None
    folio_raw: Optional[str] = None
    folio_candidates: list[str] = Field(default_factory=list)
    pan: Optional[str] = None
    investor_name: Optional[str] = None
    minor_name: Optional[str] = None
    scheme_name: Optional[str] = None
    target_amc: Optional[str] = None
    plan: Optional[Literal["REGULAR", "DIRECT"]] = None
    option: Optional[str] = None
    amount_inr: Optional[float] = None
    payment_mode: Optional[str] = None
    remitter_name: Optional[str] = None
    remitter_account_last4: Optional[str] = None
    payer_relation_to_investor: Optional[str] = None
    utr: Optional[str] = None
    arn: Optional[str] = None
    euin: Optional[str] = None
    txn_date: Optional[str] = None
    new_bank_account_last4: Optional[str] = None
    new_bank_ifsc: Optional[str] = None
    payout_account_last4: Optional[str] = None
    documents_enclosed: list[DocumentRef] = Field(default_factory=list)
    is_cash: Optional[bool] = None
    execution_only_declaration: Optional[bool] = None
    in_person_verification: Optional[bool] = None
    contact_change_claimed: Optional[bool] = None
    cob_mentioned: Optional[bool] = None
    sender_role: Optional[Literal["investor", "distributor", "employer", "relative", "other"]] = None
    third_party_category: Optional[Literal["employer", "custodian", "amc_commission", "corporate_incentive", "relative", "other"]] = None
    language_notes: Optional[str] = None


class CheckResult(BaseModel):
    check_id: str
    result: CheckResultValue
    evidence: list[Evidence] = Field(default_factory=list)
    sop_clause: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    def to_contract(self) -> Check:
        return Check(check_id=self.check_id, result=self.result, evidence=self.evidence, sop_clause=self.sop_clause)
