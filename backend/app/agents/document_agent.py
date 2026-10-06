from pathlib import Path

from app.document_processing.models import ProcessedDocument
from app.document_processing.pipeline import DocumentPipeline
from app.document_processing.reader import OCRProvider


class DocumentAgent:
    """Member 5 adapter around deterministic document processing."""

    def __init__(self, pipeline: DocumentPipeline | None = None, ocr_provider: OCRProvider | None = None):
        self.pipeline = pipeline or DocumentPipeline(ocr_provider=ocr_provider)

    def process_document(self, path: str | Path) -> ProcessedDocument:
        return self.pipeline.process_file(path)

    def process_upload(self, filename: str, content: bytes) -> ProcessedDocument:
        return self.pipeline.process_bytes(filename, content)

    def process_documents(self, files: list[tuple[str, bytes]]) -> list[ProcessedDocument]:
        return self.pipeline.process_many(files)