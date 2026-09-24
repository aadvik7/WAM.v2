"""Per-business settings with defaults. Stored in businesses.settings (JSONB)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from wam.clock import parse_hhmm

DEFAULT_BUSINESS_SETTINGS: dict[str, Any] = {
    # Booking
    "min_notice_minutes": 60,  # earliest bookable slot is now + this
    "booking_horizon_days": 30,  # how far ahead patients can book
    "offer_slot_count": 3,  # slots offered in nudges / follow-ups
    "reschedule_cutoff_minutes": 60,  # patients can't self-reschedule closer than this
    # Sending windows (local time); proactive messages only go out inside this window
    "send_window_start": "09:00",
    "send_window_end": "20:00",
    "reminder_time": "10:00",  # day-before reminders go out from this time
    "eod_time": "20:00",  # end-of-day attendance check sent to the front desk
    # Return-visit loop
    "followup_after_hours": 24,  # first missed-visit follow-up
    "second_followup_after_hours": 48,  # second try, after the first follow-up
    "renudge_after_days": 3,  # re-nudge an unanswered due nudge after this many days
    "max_nudges": 3,  # after this many unanswered nudges, flag the patient to staff
    "late_notify_window_hours": 4,  # "running late" tells patients booked within this window
    # Compliance
    "retention_days": 365,  # message_log rows older than this are deleted
    "privacy_url": "",
    "consent_text": (
        "Hi! This is the official WhatsApp assistant of {business}. We use your number and messages only to "
        "manage your bookings, reminders and updates. We never sell your data or use it for ads. Privacy policy: "
        "{privacy_url}. Reply STOP anytime to stop messages."
    ),
    # Emergency words (lowercase) that trigger an instant handoff, in addition to the built-in list
    "extra_emergency_words": [],
    # WhatsApp template language code exactly as approved in Meta (e.g. "en", "en_US", "hi")
    "template_language": "en",
    # AI
    "ai_enabled": True,
    "assistant_name": "WAM",
}


def get_setting(settings: dict[str, Any] | None, key: str) -> Any:
    if settings and key in settings and settings[key] is not None:
        return settings[key]
    return DEFAULT_BUSINESS_SETTINGS[key]


def merged_settings(settings: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(DEFAULT_BUSINESS_SETTINGS)
    for key, value in (settings or {}).items():
        if value is not None:
            out[key] = value
    return out


def get_time_setting(settings: dict[str, Any] | None, key: str) -> dt.time:
    return parse_hhmm(str(get_setting(settings, key)))
