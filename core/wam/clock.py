"""Time helpers. `now()` can be frozen in tests with `freeze()`."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

_frozen: dt.datetime | None = None


def now() -> dt.datetime:
    """Current time in UTC (timezone-aware)."""
    if _frozen is not None:
        return _frozen
    return dt.datetime.now(dt.UTC)


def freeze(value: dt.datetime | None) -> None:
    global _frozen
    if value is not None and value.tzinfo is None:
        raise ValueError("freeze() needs a timezone-aware datetime")
    _frozen = value.astimezone(dt.UTC) if value is not None else None


def tz(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_now(tz_name: str) -> dt.datetime:
    return now().astimezone(ZoneInfo(tz_name))


def local_today(tz_name: str) -> dt.date:
    return local_now(tz_name).date()


def to_local(value: dt.datetime, tz_name: str) -> dt.datetime:
    return value.astimezone(ZoneInfo(tz_name))


def combine(day: dt.date, t: dt.time, tz_name: str) -> dt.datetime:
    """Local date + local time -> aware datetime in UTC."""
    return dt.datetime.combine(day, t, tzinfo=ZoneInfo(tz_name)).astimezone(dt.UTC)


def day_bounds(day: dt.date, tz_name: str) -> tuple[dt.datetime, dt.datetime]:
    """Start and end (exclusive) of a local day, in UTC."""
    start = combine(day, dt.time(0, 0), tz_name)
    end = combine(day + dt.timedelta(days=1), dt.time(0, 0), tz_name)
    return start, end


def parse_hhmm(value: str) -> dt.time:
    hours, minutes = value.strip().split(":")
    return dt.time(int(hours), int(minutes))


def fmt_time(value: dt.datetime, tz_name: str) -> str:
    """'5:30 PM' in local time."""
    local = to_local(value, tz_name)
    return local.strftime("%I:%M %p").lstrip("0")


def fmt_date(value: dt.date | dt.datetime, tz_name: str | None = None) -> str:
    """'Mon 12 Oct'."""
    if isinstance(value, dt.datetime):
        value = to_local(value, tz_name or "UTC").date()
    return f"{value.strftime('%a')} {value.day} {value.strftime('%b')}"


def fmt_slot(value: dt.datetime, tz_name: str) -> str:
    """'Mon 12 Oct, 5:30 PM'."""
    return f"{fmt_date(value, tz_name)}, {fmt_time(value, tz_name)}"
