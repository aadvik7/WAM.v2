"""Parse the dates and times staff type on WhatsApp ("Friday", "tomorrow", "12 Oct", "5 pm", "17:30")."""

from __future__ import annotations

import datetime as dt
import re

WEEKDAYS = {
    "monday": 0,
    "mon": 0,
    "tuesday": 1,
    "tue": 1,
    "tues": 1,
    "wednesday": 2,
    "wed": 2,
    "thursday": 3,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "friday": 4,
    "fri": 4,
    "saturday": 5,
    "sat": 5,
    "sunday": 6,
    "sun": 6,
}
MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_TIME = re.compile(r"\b(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?\b", re.I)


def parse_time(text: str) -> dt.time | None:
    """'5 pm', '5pm', '5:30 pm', '17:30', '5.30'. Bare '5' → 5 PM if 1–7 (clinic evening), else as-is."""
    for match in _TIME.finditer(text):
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        ampm = (match.group(3) or "").lower().replace(".", "")
        if not match.group(2) and not ampm:
            # A bare number is only a time when the whole text is basically that number.
            if not re.fullmatch(r"\s*(at\s+)?\d{1,2}\s*(o'?clock)?\s*", text, re.I):
                continue
        if minute > 59 or hour > 23:
            continue
        if ampm == "pm" and hour < 12:
            hour += 12
        elif ampm == "am" and hour == 12:
            hour = 0
        elif not ampm and 1 <= hour <= 7:
            hour += 12  # "cancel my 5" in a clinic means 5 PM
        return dt.time(hour, minute)
    return None


def _next_weekday(today: dt.date, weekday: int, allow_today: bool = True) -> dt.date:
    days = (weekday - today.weekday()) % 7
    if days == 0 and not allow_today:
        days = 7
    return today + dt.timedelta(days=days)


def parse_date(text: str, today: dt.date) -> dt.date | None:
    t = text.strip().lower()
    if t in ("today", "aaj"):
        return today
    if t in ("tomorrow", "tmrw", "tmr", "kal"):
        return today + dt.timedelta(days=1)
    if t in ("day after tomorrow", "parso"):
        return today + dt.timedelta(days=2)
    m = re.fullmatch(r"(?:this |next )?([a-z]+)", t)
    if m and m.group(1) in WEEKDAYS:
        # "Friday" on a Friday means today; "next Friday" means the coming one, never today.
        return _next_weekday(today, WEEKDAYS[m.group(1)], allow_today=not t.startswith("next "))
    # 12 oct / 12th october / oct 12
    m = re.fullmatch(r"(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)(?:\s+(\d{4}))?", t) or None
    if m and m.group(2) in MONTHS:
        return _year_fix(int(m.group(1)), MONTHS[m.group(2)], m.group(3), today)
    m = re.fullmatch(r"([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?", t)
    if m and m.group(1) in MONTHS:
        return _year_fix(int(m.group(2)), MONTHS[m.group(1)], m.group(3), today)
    # 12/10, 12-10-2026 (day first, Indian format)
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})(?:[/-](\d{2,4}))?", t)
    if m:
        year = m.group(3)
        if year and len(year) == 2:
            year = "20" + year
        return _year_fix(int(m.group(1)), int(m.group(2)), year, today)
    # ISO
    try:
        return dt.date.fromisoformat(t)
    except ValueError:
        return None


def _year_fix(day: int, month: int, year: str | None, today: dt.date) -> dt.date | None:
    try:
        if year:
            return dt.date(int(year), month, day)
        candidate = dt.date(today.year, month, day)
        if candidate < today - dt.timedelta(days=60):
            candidate = dt.date(today.year + 1, month, day)
        return candidate
    except ValueError:
        return None


def parse_date_range(text: str, today: dt.date) -> tuple[dt.date, dt.date] | None:
    """'Friday', 'tomorrow', '12 oct to 14 oct', 'friday - monday', 'next 3 days'."""
    t = text.strip().lower()
    m = re.fullmatch(r"(?:for )?(?:the )?next (\d{1,2}) days?", t)
    if m:
        n = int(m.group(1))
        return today, today + dt.timedelta(days=max(n, 1) - 1)
    parts = re.split(r"\s+(?:to|till|until|-|–)\s+|\s*[-–]\s*(?=[a-z])", t)
    if len(parts) == 2:
        a = parse_date(parts[0], today)
        if a is not None:
            b = parse_date(parts[1], a)
            if b is not None and b >= a:
                return a, b
    single = parse_date(t, today)
    if single is not None:
        return single, single
    return None


_DURATION = re.compile(r"(\d{1,3})\s*(day|days|d|week|weeks|wk|wks|w|month|months|mo)\b", re.I)


def parse_offset_days(text: str) -> int | None:
    m = _DURATION.search(text)
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    if unit.startswith("w"):
        return n * 7
    if unit.startswith("mo") or unit.startswith("month"):
        return n * 30
    return n
