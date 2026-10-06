from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from decimal import Decimal

from .extractors import classify_document, extract_fields, required_fields
from .models import (
    DocumentMetadata,
    DocumentType,
    ProcessingStatus,
    ProcessedDocument,
    ValidationFinding,
)
from .reader import DocumentReader, OCRProvider
from .validation import cross_document_findings


class DocumentPipeline:
    def __init__(
        self,
        ocr_provider: OCRProvider | None = None,
        max_file_bytes: int = 20 * 1024 * 1024,
        confidence_threshold: float = 0.65,
        income_tolerance: float = 0.10,
    ) -> None:
        self.reader = DocumentReader(ocr_provider=ocr_provider)
        self.max_file_bytes = max_file_bytes
        self.confidence_threshold = confidence_threshold
        self.income_tolerance = income_tolerance

    def process_file(self, path: str | Path) -> ProcessedDocument:
        file_path = Path(path)
        try:
            return self.process_bytes(file_path.name, file_path.read_bytes())
        except OSError as exc:
            return self._failed_result(file_path.name, b"", "FILE_READ_ERROR", str(exc))

    def process_bytes(self, filename: str, content: bytes) -> ProcessedDocument:
        file_hash = hashlib.sha256(content).hexdigest()
        mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        metadata = DocumentMetadata(
            filename=Path(filename).name,
            mime_type=mime_type,
            size_bytes=len(content),
            sha256=file_hash,
        )
        document_id = file_hash
        findings: list[ValidationFinding] = []

        if not content:
            return self._result(metadata, document_id, DocumentType.UNKNOWN, {}, findings + [
                ValidationFinding(code="EMPTY_FILE", severity="error", message="Uploaded file is empty.")
            ], [], 0.0, ProcessingStatus.FAILED)
        if len(content) > self.max_file_bytes:
            return self._result(metadata, document_id, DocumentType.UNKNOWN, {}, findings + [
                ValidationFinding(code="FILE_TOO_LARGE", severity="error", message="File exceeds the configured size limit.")
            ], [], 0.0, ProcessingStatus.FAILED)
        suffix = Path(filename).suffix.lower()
        if suffix not in {".pdf", ".txt"}:
            return self._result(metadata, document_id, DocumentType.UNKNOWN, {}, findings + [
                ValidationFinding(code="UNSUPPORTED_FILE_TYPE", severity="error", message="Only PDF and UTF-8 text files are supported.")
            ], [], 0.0, ProcessingStatus.FAILED)
        if suffix == ".pdf" and not content.startswith(b"%PDF-"):
            return self._result(metadata, document_id, DocumentType.UNKNOWN, {}, findings + [
                ValidationFinding(code="CORRUPT_PDF", severity="error", message="File extension is PDF but the content signature is invalid.")
            ], [], 0.0, ProcessingStatus.FAILED)

        read_result = self.reader.read(filename, content)
        findings.extend(
            ValidationFinding(code=code, severity=severity, message=message)
            for code, severity, message in read_result.findings
        )
        text = "\n".join(page.text for page in read_result.pages)
        document_type, classification_confidence = classify_document(text)
        fields, extraction_findings = extract_fields(read_result.pages, metadata.filename)
        findings.extend(extraction_findings)
        missing = [name for name in required_fields(document_type) if name not in fields]
        if missing:
            findings.append(
                ValidationFinding(
                    code="MISSING_REQUIRED_FIELDS",
                    severity="warning",
                    message="One or more document-type-specific fields were not found.",
                    related_documents=missing,
                )
            )
        if document_type == DocumentType.UNKNOWN:
            findings.append(
                ValidationFinding(code="UNKNOWN_DOCUMENT_TYPE", severity="warning", message="Document type could not be classified confidently.")
            )
        if not text.strip():
            findings.append(
                ValidationFinding(code="UNREADABLE_DOCUMENT", severity="error", message="No readable document text was extracted.")
            )
        if any(page.source_kind == "ocr" and page.confidence < self.confidence_threshold for page in read_result.pages):
            findings.append(
                ValidationFinding(code="LOW_OCR_CONFIDENCE", severity="warning", message="OCR confidence is below the configured threshold.")
            )

        field_confidences = [field.confidence for field in fields.values()]
        text_confidences = [page.confidence for page in read_result.pages if page.text.strip()]
        observed_confidences = field_confidences or text_confidences
        confidence = (
            classification_confidence * (sum(observed_confidences) / len(observed_confidences))
            if classification_confidence and observed_confidences
            else 0.0
        )
        if confidence < self.confidence_threshold:
            findings.append(
                ValidationFinding(code="LOW_CONFIDENCE", severity="warning", message="Document extraction confidence is below the configured threshold.")
            )
        has_error = any(finding.severity == "error" for finding in findings)
        needs_review = bool(findings) or confidence < self.confidence_threshold
        status = ProcessingStatus.FAILED if has_error else ProcessingStatus.NEEDS_REVIEW if needs_review else ProcessingStatus.PROCESSED
        return self._result(metadata, document_id, document_type, fields, findings, missing, confidence, status)

    def process_many(self, files: list[tuple[str, bytes]]) -> list[ProcessedDocument]:
        documents = [self.process_bytes(filename, content) for filename, content in files]
        findings_by_document = cross_document_findings(
            documents, income_tolerance=Decimal(str(self.income_tolerance))
        )
        results: list[ProcessedDocument] = []
        for document in documents:
            findings = document.validation_findings + findings_by_document[document.document_id]
            status = document.processing_status
            if status == ProcessingStatus.PROCESSED and findings:
                status = ProcessingStatus.NEEDS_REVIEW
            results.append(document.model_copy(update={"validation_findings": findings, "processing_status": status}))
        return results

    @staticmethod
    def _result(metadata, document_id, document_type, fields, findings, missing, confidence, status):
        return ProcessedDocument(
            document_id=document_id,
            metadata=metadata,
            document_type=document_type,
            fields=fields,
            missing_fields=missing,
            validation_findings=findings,
            confidence_score=confidence,
            processing_status=status,
        )

    @staticmethod
    def _failed_result(filename: str, content: bytes, code: str, message: str) -> ProcessedDocument:
        digest = hashlib.sha256(content).hexdigest()
        metadata = DocumentMetadata(
            filename=Path(filename).name,
            mime_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            size_bytes=len(content),
            sha256=digest,
        )
        return DocumentPipeline._result(
            metadata,
            digest,
            DocumentType.UNKNOWN,
            {},
            [ValidationFinding(code=code, severity="error", message=message)],
            [],
            0.0,
            ProcessingStatus.FAILED,
        )