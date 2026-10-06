from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class DocumentType(StrEnum):
    W2 = "w2"
    PAY_STUB = "pay_stub"
    TAX_RETURN_1040 = "tax_return_1040"
    BANK_STATEMENT = "bank_statement"
    FORM_1003 = "form_1003"
    FORM_1008 = "form_1008"
    EMPLOYMENT_VERIFICATION = "employment_verification"
    ASSET_STATEMENT = "asset_statement"
    DEBT_STATEMENT = "debt_statement"
    PROPERTY_APPRAISAL = "property_appraisal"
    PURCHASE_CONTRACT = "purchase_contract"
    UNKNOWN = "unknown"


class ProcessingStatus(StrEnum):
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class DocumentMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    sha256: str


class EvidenceReference(BaseModel):
    source: str
    page_number: int | None = Field(default=None, ge=1)
    snippet: str


class ExtractedField(BaseModel):
    value: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[EvidenceReference] = Field(min_length=1)


class ValidationFinding(BaseModel):
    code: str
    severity: str
    message: str
    field: str | None = None
    related_documents: list[str] = Field(default_factory=list)


class ProcessedDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    metadata: DocumentMetadata
    document_type: DocumentType
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    missing_fields: list[str] = Field(default_factory=list)
    validation_findings: list[ValidationFinding] = Field(default_factory=list)
    confidence_score: float = Field(ge=0, le=1)
    processing_status: ProcessingStatus


class PageText(BaseModel):
    page_number: int = Field(ge=1)
    text: str
    confidence: float = Field(default=1.0, ge=0, le=1)
    source_kind: str = "text"