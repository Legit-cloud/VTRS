"""Contact normalization, so blind indexes match however a number or address is typed."""

import re
from collections.abc import Iterable

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_PHONE_SEPARATORS = re.compile(r"[\s\-().]")
NIGERIA = "234"


def normalize_email(raw: str) -> str:
    value = raw.strip().lower()
    if len(value) > 254 or not _EMAIL.match(value):
        raise ValueError("Enter a valid email address.")
    return value


def normalize_phone(raw: str, default_country_code: str = NIGERIA) -> str:
    """Return E.164. Local Nigerian numbers (0803...) get +234."""
    value = _PHONE_SEPARATORS.sub("", raw.strip())
    if value.startswith("+"):
        digits = value[1:]
    elif value.startswith("00"):
        digits = value[2:]
    elif value.startswith("0"):
        digits = default_country_code + value[1:]
    else:
        digits = value
    if not digits.isdigit() or not 8 <= len(digits) <= 15:
        raise ValueError("Enter a valid phone number.")
    if digits.startswith(NIGERIA) and len(digits) != 13:
        raise ValueError("Nigerian numbers have 10 digits after +234.")
    return f"+{digits}"


def is_allowed_sms_destination(phone: str, allowed_prefixes: Iterable[str]) -> bool:
    return any(phone.startswith(prefix) for prefix in allowed_prefixes)


def looks_like_email(identifier: str) -> bool:
    return "@" in identifier


def mask_phone(phone: str) -> str:
    return "*" * max(len(phone) - 3, 0) + phone[-3:]


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    return f"{local[:1]}***@{domain}"
