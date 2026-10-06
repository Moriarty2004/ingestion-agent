import re
from datetime import datetime
from decimal import Decimal, InvalidOperation


_MONEY_FIELDS = {
    "annual_income",
    "monthly_income",
    "gross_pay",
    "ytd_income",
    "account_balance",
    "asset_value",
    "monthly_debt",
    "loan_amount",
    "property_value",
    "purchase_price",
}
_DATE_FORMATS = ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%B %d, %Y", "%b %d, %Y")


def normalize_field(field_name: str, raw_value: str) -> tuple[str, str | None]:
    """Return a normalized value and an error message, if the value is invalid."""
    value = raw_value.strip()

    if field_name in _MONEY_FIELDS:
        cleaned = re.sub(r"[$,\s]", "", value)
        if cleaned.startswith("(") and cleaned.endswith(")"):
            cleaned = f"-{cleaned[1:-1]}"
        try:
            amount = Decimal(cleaned)
            if not amount.is_finite():
                raise InvalidOperation
            return f"{amount:.2f}", None
        except (InvalidOperation, ValueError):
            return value, f"'{value}' is not a valid numeric amount."

    if field_name in {"document_date", "employment_start_date"}:
        for date_format in _DATE_FORMATS:
            try:
                return datetime.strptime(value, date_format).date().isoformat(), None
            except ValueError:
                continue
        return value, f"'{value}' is not a recognized date."

    if field_name == "tax_year":
        if re.fullmatch(r"\d{4}", value):
            return value, None
        return value, f"'{value}' is not a valid four-digit tax year."

    if field_name == "interest_rate":
        cleaned = value.rstrip("% ").strip()
        try:
            rate = Decimal(cleaned)
            if Decimal("0") <= rate <= Decimal("100"):
                return f"{rate.normalize()}%", None
        except InvalidOperation:
            pass
        return value, f"'{value}' is not a valid percentage."

    if field_name == "masked_ssn":
        digits = re.sub(r"\D", "", value)
        if len(digits) == 9:
            return f"***-**-{digits[-4:]}", None
        if len(digits) == 4 and re.search(r"[*Xx]", value):
            return f"***-**-{digits}", None
        return value, "SSN must contain nine digits or a masked value ending in four digits."

    return re.sub(r"\s+", " ", value).strip(), None