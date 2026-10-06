from io import BytesIO
from pathlib import Path

from pypdf import PdfWriter
from app.agents.document_agent import DocumentAgent
from app.document_processing.models import DocumentType, ProcessingStatus
from app.document_processing.pipeline import DocumentPipeline
from app.document_processing.reader import DocumentReader
from app.document_processing.models import PageText


def fixture_text(name: str) -> bytes:
    return (GROUND_TRUTH / name).read_bytes()


GROUND_TRUTH = Path(__file__).resolve().parents[3] / "data" / "ground_truth"


def test_w2_fixture_extracts_normalized_values_and_evidence():
    result = DocumentPipeline().process_bytes("sample_w2.txt", fixture_text("sample_w2.txt"))

    assert result.document_type == DocumentType.W2
    assert result.fields["annual_income"].value == "84250.00"
    assert result.fields["masked_ssn"].value == "***-**-6789"
    assert "123-45-6789" not in result.fields["masked_ssn"].evidence[0].snippet
    assert "***-**-6789" in result.fields["masked_ssn"].evidence[0].snippet
    assert result.fields["document_date"].value == "2025-12-31"
    assert result.fields["annual_income"].evidence[0].page_number == 1
    assert result.fields["annual_income"].evidence[0].source == "sample_w2.txt"
    assert result.processing_status == ProcessingStatus.PROCESSED


def test_classifies_target_document_set():
    expected = {
        "sample_w2.txt": DocumentType.W2,
        "sample_pay_stub.txt": DocumentType.PAY_STUB,
        "sample_1040.txt": DocumentType.TAX_RETURN_1040,
        "sample_bank_statement.txt": DocumentType.BANK_STATEMENT,
        "sample_1003.txt": DocumentType.FORM_1003,
        "sample_1008.txt": DocumentType.FORM_1008,
        "sample_voe.txt": DocumentType.EMPLOYMENT_VERIFICATION,
        "sample_asset_statement.txt": DocumentType.ASSET_STATEMENT,
        "sample_debt_statement.txt": DocumentType.DEBT_STATEMENT,
        "sample_appraisal.txt": DocumentType.PROPERTY_APPRAISAL,
        "sample_purchase_contract.txt": DocumentType.PURCHASE_CONTRACT,
    }
    for filename, document_type in expected.items():
        result = DocumentPipeline().process_bytes(filename, fixture_text(filename))
        assert result.document_type == document_type
        assert result.missing_fields == []


def test_surfaces_missing_required_fields():
    result = DocumentPipeline().process_bytes("partial_w2.txt", b"Form W-2\nEmployer: Northwind")

    assert "annual_income" in result.missing_fields
    assert "tax_year" in result.missing_fields
    assert result.processing_status == ProcessingStatus.NEEDS_REVIEW


def test_rejects_unsupported_and_corrupt_files():
    unsupported = DocumentPipeline().process_bytes("statement.csv", b"checking account")
    corrupt = DocumentPipeline().process_bytes("broken.pdf", b"%PDF-not really a PDF")

    assert unsupported.processing_status == ProcessingStatus.FAILED
    assert unsupported.validation_findings[0].code == "UNSUPPORTED_FILE_TYPE"
    assert corrupt.processing_status == ProcessingStatus.FAILED
    assert any(finding.code == "CORRUPT_PDF" for finding in corrupt.validation_findings)


def test_flags_duplicate_income_employer_and_identity_conflicts():
    w2 = fixture_text("sample_w2.txt")
    pay_stub = (
        fixture_text("sample_pay_stub.txt")
        .replace(b"Northstar Design LLC", b"Westbridge Payroll")
        .replace(b"123-45-6789", b"987-65-4321")
        .replace(b"Gross pay: $7,020.83", b"Gross pay: $6,000.00\nMonthly income: $6,000.00")
    )
    results = DocumentPipeline().process_many(
        [("w2.txt", w2), ("w2-copy.txt", w2), ("pay.txt", pay_stub)]
    )
    codes = {finding.code for result in results for finding in result.validation_findings}

    assert "DUPLICATE_DOCUMENT" in codes
    assert "INCOME_INCONSISTENCY" in codes
    assert "EMPLOYER_MISMATCH" in codes
    assert "IDENTITY_MISMATCH" in codes


def test_invalid_amount_is_preserved_and_flagged():
    result = DocumentPipeline().process_bytes(
        "bad_bank.txt", b"Bank Statement\nAccount balance: not-money"
    )

    assert result.fields["account_balance"].value == "not-money"
    assert any(finding.code == "INVALID_FIELD_VALUE" for finding in result.validation_findings)


def test_scanned_pdf_uses_injected_ocr_provider():
    class FakeOCR:
        def recognize(self, pdf_bytes: bytes) -> list[PageText]:
            return [PageText(page_number=1, text="Wage and Tax Statement\nEmployer: Example Co\nWages: $80,000\nTax year: 2025", confidence=0.91, source_kind="ocr")]

    reader = DocumentReader(ocr_provider=FakeOCR())
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    pdf_buffer = BytesIO()
    writer.write(pdf_buffer)
    read = reader.read("scan.pdf", pdf_buffer.getvalue())

    assert read.pages[0].source_kind == "ocr"
    assert "Employer: Example Co" in read.pages[0].text


def test_document_agent_returns_json_ready_contract():
    result = DocumentAgent().process_upload("sample_w2.txt", fixture_text("sample_w2.txt"))
    payload = result.model_dump(mode="json")

    assert payload["document_type"] == "w2"
    assert payload["processing_status"] == "processed"
    assert payload["fields"]["annual_income"]["evidence"][0]["page_number"] == 1