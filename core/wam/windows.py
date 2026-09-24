"""When WAM may start conversations with patients (the business's send window)."""

from __future__ import annotations

import datetime as dt

from wam import clock
from wam.models import Business
from wam.settings_defaults import get_time_setting


def in_send_window(business: Business, local: dt.datetime | None = None) -> bool:
    local = local or clock.local_now(business.timezone)
    start = get_time_setting(business.settings, "send_window_start")
    end = get_time_setting(business.settings, "send_window_end")
    return start <= local.time() < end


def next_window_start(business: Business) -> dt.datetime:
    local = clock.local_now(business.timezone)
    start = get_time_setting(business.settings, "send_window_start")
    day = local.date() if local.time() < start else local.date() + dt.timedelta(days=1)
    return clock.combine(day, start, business.timezone)


def next_nudge_label(business: Business) -> str:
    """'10:00 AM tomorrow' / '10:00 AM today' — when the scheduler will send due nudges."""
    local = clock.local_now(business.timezone)
    at = get_time_setting(business.settings, "reminder_time")
    end = get_time_setting(business.settings, "send_window_end")
    when = "today" if local.time() < end else "tomorrow"
    return f"{dt.datetime.combine(local.date(), at).strftime('%I:%M %p').lstrip('0')} {when}"
