import re

from .models import DocumentType, EvidenceReference, ExtractedField, PageText, ValidationFinding
from .normalization import normalize_field


_TYPE_MARKERS: tuple[tuple[DocumentType, tuple[str, ...]], ...] = (
    (DocumentType.FORM_1003, ("form 1003", "uniform residential loan application")),
    (DocumentType.FORM_1008, ("form 1008", "uniform underwriting and transmittal")),
    (DocumentType.TAX_RETURN_1040, ("form 1040", "1040 u.s. individual income tax return", "tax return")),
    (DocumentType.EMPLOYMENT_VERIFICATION, ("verification of employment", "employment verification", "voe")),
    (DocumentType.PROPERTY_APPRAISAL, ("appraisal report", "property appraisal", "appraised value")),
    (DocumentType.PURCHASE_CONTRACT, ("purchase contract", "purchase agreement", "sales contract")),
    (DocumentType.DEBT_STATEMENT, ("debt statement", "loan statement", "monthly payment due")),
    (DocumentType.ASSET_STATEMENT, ("asset statement", "investment account statement")),
    (DocumentType.BANK_STATEMENT, ("bank statement", "checking account", "savings account")),
    (DocumentType.PAY_STUB, ("pay stub", "paystub", "pay statement", "earnings statement")),
    (DocumentType.W2, ("form w-2", "w-2", "wage and tax statement")),
)

_FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "applicant_name": ("applicant name", "borrower name", "employee name", "taxpayer name"),
    "employer_name": ("employer name", "employer", "company name"),
    "job_title": ("job title", "position", "occupation"),
    "employment_start_date": ("employment start date", "date hired", "hire date"),
    "annual_income": ("annual income", "gross annual income", "wages", "total income"),
    "monthly_income": ("monthly income", "gross monthly income"),
    "gross_pay": ("gross pay", "current gross pay", "gross earnings"),
    "ytd_income": ("year to date income", "ytd income", "ytd gross"),
    "account_balance": ("ending balance", "account balance", "available balance"),
    "asset_value": ("asset value", "total assets", "vested balance"),
    "monthly_debt": ("monthly debt", "monthly payment due", "monthly payment", "payment due"),
    "loan_amount": ("loan amount", "mortgage amount", "amount financed"),
    "property_value": ("property value", "appraised value"),
    "purchase_price": ("purchase price", "sales price", "contract price"),
    "interest_rate": ("interest rate", "note rate"),
    "document_date": ("statement date", "document date", "pay date", "closing date"),
    "tax_year": ("tax year", "year"),
    "masked_ssn": ("social security number", "ssn", "taxpayer identification number"),
}

_REQUIRED_FIELDS: dict[DocumentType, tuple[str, ...]] = {
    DocumentType.W2: ("employer_name", "annual_income", "tax_year"),
    DocumentType.PAY_STUB: ("employer_name", "gross_pay"),
    DocumentType.TAX_RETURN_1040: ("applicant_name", "tax_year"),
    DocumentType.BANK_STATEMENT: ("account_balance",),
    DocumentType.FORM_1003: ("applicant_name", "loan_amount"),
    DocumentType.FORM_1008: ("applicant_name", "loan_amount"),
    DocumentType.EMPLOYMENT_VERIFICATION: ("employer_name", "applicant_name"),
    DocumentType.ASSET_STATEMENT: ("asset_value",),
    DocumentType.DEBT_STATEMENT: ("monthly_debt",),
    DocumentType.PROPERTY_APPRAISAL: ("property_value",),
    DocumentType.PURCHASE_CONTRACT: ("purchase_price",),
}


def _redact_identifiers(text: str) -> str:
    return re.sub(
        r"(?<!\d)(\d{3})-?(\d{2})-?(\d{4})(?!\d)",
        r"***-**-\3",
        text,
    )


def classify_document(text: str) -> tuple[DocumentType, float]:
    normalized = text.lower()
    for document_type, markers in _TYPE_MARKERS:
        if any(marker in normalized for marker in markers):
            return document_type, 0.92
    return DocumentType.UNKNOWN, 0.0


def required_fields(document_type: DocumentType) -> list[str]:
    return list(_REQUIRED_FIELDS.get(document_type, ()))


def extract_fields(
    pages: list[PageText], source: str
) -> tuple[dict[str, ExtractedField], list[ValidationFinding]]:
    fields: dict[str, ExtractedField] = {}
    findings: list[ValidationFinding] = []
    labels = sorted(
        ((label, field_name) for field_name, names in _FIELD_LABELS.items() for label in names),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    label_pattern = "|".join(re.escape(label) for label, _ in labels)
    pattern = re.compile(rf"^\s*(?P<label>{label_pattern})\s*[:=]\s*(?P<value>[^\r\n|;]+)", re.IGNORECASE)
    field_by_label = {label.lower(): field_name for label, field_name in labels}

    for page in pages:
        for line in page.text.splitlines():
            match = pattern.search(line)
            if not match:
                continue
            label = match.group("label").lower()
            field_name = field_by_label[label]
            raw_value = match.group("value").strip()
            value, error = normalize_field(field_name, raw_value)
            if error:
                findings.append(
                    ValidationFinding(
                        code="INVALID_FIELD_VALUE",
                        severity="warning",
                        field=field_name,
                        message=error,
                    )
                )
            fields[field_name] = ExtractedField(
                value=value,
                confidence=max(0.0, min(1.0, page.confidence * 0.96)),
                evidence=[
                    EvidenceReference(
                        source=source,
                        page_number=page.page_number,
                        snippet=_redact_identifiers(line.strip())[:240],
                    )
                ],
            )
    return fields, findings