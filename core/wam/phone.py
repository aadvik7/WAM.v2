"""Phone number normalisation to E.164 (defaults to India, +91)."""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\D+")


def normalize_phone(raw: str | None, default_country_code: str = "91") -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    has_plus = raw.startswith("+")
    digits = _DIGITS.sub("", raw)
    if has_plus:
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if digits.startswith("00"):
        digits = digits[2:]
        return f"+{digits}" if 8 <= len(digits) <= 15 else None
    if len(digits) == 10 and default_country_code == "91":
        return f"+91{digits}"
    if len(digits) == 11 and digits.startswith("0"):
        return f"+{default_country_code}{digits[1:]}"
    if len(digits) == 12 and digits.startswith(default_country_code):
        return f"+{digits}"
    if 11 <= len(digits) <= 15:
        return f"+{digits}"
    if len(digits) == 10:
        return f"+{default_country_code}{digits}"
    return None


PHONE_IN_TEXT = re.compile(r"(\+?\d[\d\s-]{8,16}\d)")


def extract_phone(text: str) -> tuple[str | None, str]:
    """Find a phone number in free text; returns (e164 or None, text without it)."""
    match = PHONE_IN_TEXT.search(text)
    if not match:
        return None, text
    phone = normalize_phone(match.group(1))
    if phone is None:
        return None, text
    rest = (text[: match.start()] + " " + text[match.end() :]).strip()
    return phone, re.sub(r"\s{2,}", " ", rest)
