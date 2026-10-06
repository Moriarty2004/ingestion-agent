from decimal import Decimal

from .models import ProcessedDocument, ValidationFinding


def cross_document_findings(
    documents: list[ProcessedDocument], income_tolerance: Decimal = Decimal("0.10")
) -> dict[str, list[ValidationFinding]]:
    findings: dict[str, list[ValidationFinding]] = {document.document_id: [] for document in documents}
    by_hash: dict[str, list[ProcessedDocument]] = {}
    for document in documents:
        by_hash.setdefault(document.metadata.sha256, []).append(document)
    for duplicates in by_hash.values():
        if len(duplicates) < 2:
            continue
        names = [document.metadata.filename for document in duplicates]
        for document in duplicates:
            findings[document.document_id].append(
                ValidationFinding(
                    code="DUPLICATE_DOCUMENT",
                    severity="warning",
                    message="Identical file content was submitted more than once.",
                    related_documents=[name for name in names if name != document.metadata.filename],
                )
            )

    for field_name, code, message in (
        ("employer_name", "EMPLOYER_MISMATCH", "Employer names differ across submitted documents."),
        ("masked_ssn", "IDENTITY_MISMATCH", "Masked SSN references differ across submitted documents."),
    ):
        observed: dict[str, list[ProcessedDocument]] = {}
        for document in documents:
            value = document.fields.get(field_name)
            if value:
                observed.setdefault(value.value.casefold(), []).append(document)
        if len(observed) > 1:
            names = [document.metadata.filename for group in observed.values() for document in group]
            for group in observed.values():
                for document in group:
                    findings[document.document_id].append(
                        ValidationFinding(
                            code=code,
                            severity="warning",
                            field=field_name,
                            message=message,
                            related_documents=[name for name in names if name != document.metadata.filename],
                        )
                    )

    income_values: list[tuple[ProcessedDocument, Decimal, str]] = []
    for document in documents:
        for field_name in ("annual_income", "monthly_income"):
            field = document.fields.get(field_name)
            if field:
                try:
                    amount = Decimal(field.value)
                except Exception:
                    continue
                income_values.append((document, amount, field_name))
    for index, (first_document, first_amount, first_kind) in enumerate(income_values):
        for second_document, second_amount, second_kind in income_values[index + 1 :]:
            if first_document.document_id == second_document.document_id and first_kind == second_kind:
                continue
            first_monthly = first_amount / 12 if first_kind == "annual_income" else first_amount
            second_monthly = second_amount / 12 if second_kind == "annual_income" else second_amount
            baseline = max(abs(first_monthly), abs(second_monthly))
            if baseline and abs(first_monthly - second_monthly) / baseline > income_tolerance:
                for document in {first_document.document_id: first_document, second_document.document_id: second_document}.values():
                    findings[document.document_id].append(
                        ValidationFinding(
                            code="INCOME_INCONSISTENCY",
                            severity="warning",
                            field="income",
                            message="Annual and/or monthly income values differ by more than the configured tolerance.",
                            related_documents=[
                                name for name in (first_document.metadata.filename, second_document.metadata.filename)
                                if name != document.metadata.filename
                            ],
                        )
                    )
    return findings