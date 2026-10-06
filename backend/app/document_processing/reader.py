from __future__ import annotations

from dataclasses import dataclass, field
from io import BytesIO
from typing import Protocol

from pypdf import PdfReader

from .models import PageText


class OCRProvider(Protocol):
    def recognize(self, pdf_bytes: bytes) -> list[PageText]: ...


class TesseractOCRProvider:
    """Optional local OCR adapter; requires pypdfium2, pytesseract, and Tesseract."""

    def __init__(self, language: str = "eng") -> None:
        self.language = language

    def recognize(self, pdf_bytes: bytes) -> list[PageText]:
        import pypdfium2 as pdfium
        import pytesseract

        pdf = pdfium.PdfDocument(pdf_bytes)
        results: list[PageText] = []
        try:
            for page_index in range(len(pdf)):
                page = pdf[page_index]
                image = page.render(scale=2).to_pil()
                data = pytesseract.image_to_data(
                    image, lang=self.language, output_type=pytesseract.Output.DICT
                )
                words = [word.strip() for word in data["text"] if word.strip()]
                confidences = [
                    float(score) / 100
                    for score, word in zip(data["conf"], data["text"])
                    if word.strip() and str(score).replace(".", "", 1).isdigit()
                ]
                confidence = sum(confidences) / len(confidences) if confidences else 0.0
                results.append(
                    PageText(
                        page_number=page_index + 1,
                        text=" ".join(words),
                        confidence=max(0.0, min(1.0, confidence)),
                        source_kind="ocr",
                    )
                )
        finally:
            pdf.close()
        return results


@dataclass
class ReadResult:
    pages: list[PageText] = field(default_factory=list)
    findings: list[tuple[str, str, str]] = field(default_factory=list)


class DocumentReader:
    def __init__(self, ocr_provider: OCRProvider | None = None, min_text_chars: int = 30):
        self.ocr_provider = ocr_provider
        self.min_text_chars = min_text_chars

    def read(self, filename: str, content: bytes) -> ReadResult:
        if filename.lower().endswith(".pdf"):
            return self._read_pdf(content)
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            return ReadResult(findings=[("UNREADABLE_TEXT", "error", "Text file is not valid UTF-8.")])
        return ReadResult(pages=[PageText(page_number=1, text=text)])

    def _read_pdf(self, content: bytes) -> ReadResult:
        try:
            pdf = PdfReader(BytesIO(content), strict=True)
            if pdf.is_encrypted:
                return ReadResult(findings=[("ENCRYPTED_PDF", "error", "Encrypted PDFs are not supported.")])
            pages = [
                PageText(page_number=index + 1, text=page.extract_text() or "")
                for index, page in enumerate(pdf.pages)
            ]
        except Exception as exc:
            return ReadResult(
                findings=[("CORRUPT_PDF", "error", f"PDF could not be read: {type(exc).__name__}.")]
            )

        if sum(len(page.text.strip()) for page in pages) >= self.min_text_chars:
            return ReadResult(pages=pages)
        if self.ocr_provider is None:
            return ReadResult(
                pages=pages,
                findings=[(
                    "OCR_UNAVAILABLE",
                    "warning",
                    "PDF contains little extractable text and no OCR provider is configured.",
                )],
            )
        try:
            ocr_pages = self.ocr_provider.recognize(content)
            if not any(page.text.strip() for page in ocr_pages):
                return ReadResult(
                    pages=ocr_pages,
                    findings=[("UNREADABLE_DOCUMENT", "error", "OCR found no readable text.")],
                )
            return ReadResult(pages=ocr_pages)
        except Exception as exc:
            return ReadResult(
                pages=pages,
                findings=[("OCR_FAILED", "error", f"OCR processing failed: {type(exc).__name__}.")],
            )