# Mortgage Document Intelligence (Member 2)

This workspace implements the Member 2 document-ingestion ownership described in the team allocation guide. The pipeline supports PDF and UTF-8 text input and returns Pydantic-validated JSON with a classified type, normalized extracted fields, evidence references, missing fields, validation findings, confidence, metadata, and processing status.

## Setup and tests

```powershell
python -m pip install -r requirements.txt
$env:PYTHONPATH = "$PWD\backend"
python -m pytest backend/tests/unit/test_document_processing.py -q
```

## Use

```python
from app.document_processing.pipeline import DocumentPipeline

result = DocumentPipeline().process_file("application_w2.pdf")
payload = result.model_dump(mode="json")
```

For an API upload, call `process_bytes(filename, content)`. For a group of documents, use `process_many([(filename, content), ...])` to add duplicate and cross-document income, employer, and masked-SSN consistency checks. The workflow-facing adapter is `app.agents.document_agent.DocumentAgent`.

## OCR

The default reader extracts embedded PDF text with pypdf. For scanned PDFs, configure `TesseractOCRProvider`; install the optional Python packages `pypdfium2` and `pytesseract`, plus the Tesseract OCR executable and its language data. If no OCR provider is configured, the result explicitly reports `OCR_UNAVAILABLE` and requires review when the PDF has little extractable text.

## Current boundaries

- Supported inputs are local PDF and UTF-8 `.txt` files; uploads are not persisted by this package.
- Extractors use labeled text fields. A document type can be recognized even when a value is absent; required omissions are reported, not filled in.
- The 11 supported types and required-field rules are explicit in the package and should be aligned with the team's final PRD scope.
- Confidence is a transparent heuristic based on classification and text/OCR confidence, not a calibrated probability. Thresholds, maximum input size, and income tolerance are configurable.
- Synthetic examples only. Do not place real borrower documents or unmasked identifiers in `data/ground_truth/` or source control.
