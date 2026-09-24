"""Request bodies (validated) and response serialisers for the admin API."""

from __future__ import annotations

import datetime as dt
import re
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from wam import clock
from wam.engine import schedules as sched_engine
from wam.models import (
    AdminUser,
    Appointment,
    Availability,
    Business,
    Contact,
    Faq,
    MessageLog,
    Resource,
    Role,
    Schedule,
    ScheduleTemplate,
    Staff,
)
from wam.settings_defaults import merged_settings

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _check_email(value: str) -> str:
    value = value.strip().lower()
    if not EMAIL.match(value) or len(value) > 200:
        raise ValueError("invalid email address")
    return value


DAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


def _check_hhmm(value: str) -> str:
    if not HHMM.match(value):
        raise ValueError("time must be HH:MM (24h)")
    return value


# --------------------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------------------


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


def _validate_tz(v: str | None) -> str | None:
    if v is None:
        return v
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    try:
        ZoneInfo(v)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("unknown timezone") from exc
    return v


def _validate_hours(v: dict[str, list[list[str]]] | None) -> dict[str, list[list[str]]] | None:
    if v is None:
        return v
    for day, blocks in v.items():
        if day not in DAY_KEYS:
            raise ValueError(f"unknown day {day}")
        for block in blocks:
            if len(block) != 2:
                raise ValueError("each block is [start, end]")
            _check_hhmm(block[0])
            _check_hhmm(block[1])
            if block[1] <= block[0]:
                raise ValueError("block end must be after start")
    return v


class BusinessIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    type: Literal["clinic", "institute", "business"] = "clinic"
    timezone: str = "Asia/Kolkata"
    language: str = "en"
    phone: str | None = None
    address: str | None = None
    maps_url: str | None = None
    emergency_number: str | None = None
    hours: dict[str, list[list[str]]] | None = None
    settings: dict[str, Any] | None = None
    chatwoot_account_id: int | None = None
    chatwoot_inbox_id: int | None = None
    chatwoot_api_token: str | None = None
    chatwoot_bot_token: str | None = None
    chatwoot_webhook_secret: str | None = None

    _tz = field_validator("timezone")(classmethod(lambda cls, v: _validate_tz(v)))
    _hours = field_validator("hours")(classmethod(lambda cls, v: _validate_hours(v)))


class BusinessPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    type: Literal["clinic", "institute", "business"] | None = None
    timezone: str | None = None
    language: str | None = None
    phone: str | None = None
    address: str | None = None
    maps_url: str | None = None
    emergency_number: str | None = None
    hours: dict[str, list[list[str]]] | None = None
    settings: dict[str, Any] | None = None
    chatwoot_account_id: int | None = None
    chatwoot_inbox_id: int | None = None
    chatwoot_api_token: str | None = None
    chatwoot_bot_token: str | None = None
    chatwoot_webhook_secret: str | None = None

    _tz = field_validator("timezone")(classmethod(lambda cls, v: _validate_tz(v)))
    _hours = field_validator("hours")(classmethod(lambda cls, v: _validate_hours(v)))


class StaffIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    phone: str
    role_id: int | None = None
    receives_eod_list: bool = False
    is_active: bool = True
    pin: str | None = None


class StaffPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    role_id: int | None = None
    receives_eod_list: bool | None = None
    is_active: bool | None = None


class PinIn(BaseModel):
    pin: str

    @field_validator("pin")
    @classmethod
    def _pin(cls, v: str) -> str:
        if not re.fullmatch(r"\d{4,6}", v):
            raise ValueError("PIN must be 4 to 6 digits")
        return v


class RoleIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    allowed_commands: list[str] = Field(default_factory=list)


class ResourceIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = "doctor"
    specialty: str | None = None
    slot_minutes: int = Field(default=15, ge=5, le=480)
    staff_id: int | None = None
    is_active: bool = True


class ResourcePatch(BaseModel):
    name: str | None = None
    kind: str | None = None
    specialty: str | None = None
    slot_minutes: int | None = Field(default=None, ge=5, le=480)
    staff_id: int | None = None
    is_active: bool | None = None


class WeeklyBlockIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _t(cls, v: str) -> str:
        return _check_hhmm(v)


class BreakBlockIn(BaseModel):
    weekday: int | None = Field(default=None, ge=0, le=6)
    start: str
    end: str

    @field_validator("start", "end")
    @classmethod
    def _t(cls, v: str) -> str:
        return _check_hhmm(v)


class AvailabilityIn(BaseModel):
    weekly: list[WeeklyBlockIn] = Field(default_factory=list)
    breaks: list[BreakBlockIn] = Field(default_factory=list)


class LeaveIn(BaseModel):
    start_date: dt.date
    end_date: dt.date
    reason: str | None = None
    move_appointments: bool = True


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["visit", "payment"] = "visit"
    amount: Decimal | None = Field(default=None, ge=0)
    reminder_days_before: int | None = Field(default=None, ge=0, le=60)
    specialty: str | None = None
    session_count: int | None = Field(default=None, ge=1, le=200)
    gap_days: int = Field(default=7, ge=0, le=3650)
    offsets_days: list[int] | None = None
    session_labels: list[str] | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    aliases: list[str] = Field(default_factory=list)
    is_active: bool = True


class TemplatePatch(BaseModel):
    name: str | None = None
    kind: Literal["visit", "payment"] | None = None
    amount: Decimal | None = Field(default=None, ge=0)
    reminder_days_before: int | None = Field(default=None, ge=0, le=60)
    specialty: str | None = None
    session_count: int | None = Field(default=None, ge=1, le=200)
    ongoing: bool | None = None
    gap_days: int | None = Field(default=None, ge=0, le=3650)
    offsets_days: list[int] | None = None
    session_labels: list[str] | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    aliases: list[str] | None = None
    is_active: bool | None = None


class FaqIn(BaseModel):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    keywords: list[str] = Field(default_factory=list)


class ContactIn(BaseModel):
    name: str | None = None
    phone: str | None = None
    guardian_phone: str | None = None
    guardian_name: str | None = None
    date_of_birth: dt.date | None = None
    language: str | None = None
    notes: str | None = None


class ContactPatch(BaseModel):
    name: str | None = None
    phone: str | None = None
    date_of_birth: dt.date | None = None
    language: str | None = None
    notes: str | None = None
    opted_out: bool | None = None
    needs_staff: bool | None = None


class EnrolIn(BaseModel):
    template_id: int
    amount: Decimal | None = Field(default=None, ge=0)
    resource_id: int | None = None
    anchor_date: dt.date | None = None
    sessions_done: int = Field(default=0, ge=0)
    first_due: dt.date | None = None
    notes: str | None = None
    nudge_now: bool = True


class SchedulePatch(BaseModel):
    status: Literal["active", "paused", "completed", "cancelled"] | None = None
    next_due_date: dt.date | None = None
    resource_id: int | None = None
    notes: str | None = None


class AppointmentIn(BaseModel):
    contact_id: int
    resource_id: int
    start_at: dt.datetime  # naive = business local time
    duration_minutes: int | None = Field(default=None, ge=5, le=480)
    schedule_id: int | None = None
    service: str | None = None
    enforce_availability: bool = False
    notify: bool = True
    notes: str | None = None
    move_appointment_id: int | None = None  # move this booking instead of creating a second one


class MarkIn(BaseModel):
    status: Literal["done", "missed"]


class CancelIn(BaseModel):
    reason: str | None = None
    offer_rebook: bool = True


class AdminUserIn(BaseModel):
    email: str
    password: str = Field(min_length=8, max_length=200)
    name: str | None = None
    business_id: int | None = None

    _email = field_validator("email")(classmethod(lambda cls, v: _check_email(v)))


class SimMessageIn(BaseModel):
    phone: str
    text: str = Field(min_length=1, max_length=4000)
    name: str | None = None


# --------------------------------------------------------------------------------------
# Serialisers
# --------------------------------------------------------------------------------------


def iso_local(value: dt.datetime | None, tz: str) -> str | None:
    return clock.to_local(value, tz).isoformat() if value is not None else None


def business_out(b: Business) -> dict[str, Any]:
    return {
        "id": b.id,
        "name": b.name,
        "type": b.type,
        "timezone": b.timezone,
        "language": b.language,
        "phone": b.phone,
        "address": b.address,
        "maps_url": b.maps_url,
        "emergency_number": b.emergency_number,
        "hours": b.hours or {},
        "settings": merged_settings(b.settings),
        "chatwoot_account_id": b.chatwoot_account_id,
        "chatwoot_inbox_id": b.chatwoot_inbox_id,
        "chatwoot_api_token_set": bool(b.chatwoot_api_token),
        "chatwoot_bot_token_set": bool(b.chatwoot_bot_token),
        "chatwoot_webhook_secret_set": bool(b.chatwoot_webhook_secret),
        "is_active": b.is_active,
    }


def role_out(r: Role) -> dict[str, Any]:
    return {"id": r.id, "name": r.name, "allowed_commands": r.allowed_commands}


def staff_out(s: Staff) -> dict[str, Any]:
    return {
        "id": s.id,
        "name": s.name,
        "phone": s.phone,
        "role_id": s.role_id,
        "role": s.role.name if s.role else None,
        "pin_set": bool(s.pin_hash),
        "pin_locked": bool(s.pin_locked_until and s.pin_locked_until > clock.now()),
        "receives_eod_list": s.receives_eod_list,
        "is_active": s.is_active,
    }


def resource_out(r: Resource) -> dict[str, Any]:
    return {
        "id": r.id,
        "name": r.name,
        "kind": r.kind,
        "specialty": r.specialty,
        "slot_minutes": r.slot_minutes,
        "staff_id": r.staff_id,
        "is_active": r.is_active,
    }


def availability_out(a: Availability, tz: str) -> dict[str, Any]:
    return {
        "id": a.id,
        "kind": a.kind,
        "weekday": a.weekday,
        "start": a.start_time.strftime("%H:%M") if a.start_time else None,
        "end": a.end_time.strftime("%H:%M") if a.end_time else None,
        "start_at": iso_local(a.start_at, tz),
        "end_at": iso_local(a.end_at, tz),
        "reason": a.reason,
    }


def template_out(t: ScheduleTemplate) -> dict[str, Any]:
    return {
        "id": t.id,
        "name": t.name,
        "specialty": t.specialty,
        "session_count": t.session_count,
        "total_sessions": sched_engine.total_sessions(t),
        "ongoing": t.is_ongoing,
        "gap_days": t.gap_days,
        "offsets_days": t.offsets_days,
        "session_labels": t.session_labels,
        "duration_minutes": t.duration_minutes,
        "aliases": t.aliases,
        "is_active": t.is_active,
        "kind": t.kind,
        "amount": float(t.amount) if t.amount is not None else None,
        "reminder_days_before": (t.reminder_rules or {}).get("days_before"),
    }


def faq_out(f: Faq) -> dict[str, Any]:
    return {"id": f.id, "question": f.question, "answer": f.answer, "keywords": f.keywords}


def contact_out(c: Contact, tz: str) -> dict[str, Any]:
    return {
        "id": c.id,
        "name": c.name,
        "phone": c.phone,
        "roll": c.external_id,
        "guardian": (
            {"id": c.guardian.id, "name": c.guardian.name, "phone": c.guardian.phone} if c.guardian else None
        ),
        "date_of_birth": c.date_of_birth.isoformat() if c.date_of_birth else None,
        "language": c.language,
        "notes": c.notes,
        "opted_out": c.opted_out,
        "needs_staff": c.needs_staff,
        "consent_at": iso_local(c.consent_at, tz),
        "consent_notice_sent_at": iso_local(c.consent_notice_sent_at, tz),
        "last_inbound_at": iso_local(c.last_inbound_at, tz),
        "created_at": iso_local(c.created_at, tz),
    }


def schedule_out(s: Schedule, tz: str) -> dict[str, Any]:
    today = clock.local_today(tz)
    return {
        "id": s.id,
        "contact_id": s.contact_id,
        "contact_name": s.contact.name if s.contact else None,
        "template_id": s.template_id,
        "template": s.template.name if s.template else None,
        "kind": s.template.kind if s.template else "visit",
        "amount": _amount(s),
        "resource_id": s.resource_id,
        "status": s.status,
        "anchor_date": s.anchor_date.isoformat(),
        "sessions_done": s.sessions_done,
        "sessions_total": s.sessions_total,
        "next_due_date": s.next_due_date.isoformat() if s.next_due_date else None,
        "overdue": bool(s.status == "active" and s.next_due_date and s.next_due_date < today),
        "nudge_count": s.nudge_count,
        "last_nudged_at": iso_local(s.last_nudged_at, tz),
        "missed_count": s.missed_count,
        "needs_staff": s.needs_staff,
        "notes": s.notes,
        "created_at": iso_local(s.created_at, tz),
        "completed_at": iso_local(s.completed_at, tz),
    }


def _amount(s: Schedule) -> float | None:
    if s.amount is not None:
        return float(s.amount)
    if s.template is not None and s.template.amount is not None:
        return float(s.template.amount)
    return None


def appointment_out(a: Appointment, tz: str) -> dict[str, Any]:
    return {
        "id": a.id,
        "contact_id": a.contact_id,
        "contact_name": a.contact.name if a.contact else None,
        "contact_phone": (a.contact.phone or (a.contact.guardian.phone if a.contact.guardian else None))
        if a.contact
        else None,
        "resource_id": a.resource_id,
        "resource_name": a.resource.name if a.resource else None,
        "schedule_id": a.schedule_id,
        "session_number": a.session_number,
        "service": a.service,
        "start_at": iso_local(a.start_at, tz),
        "end_at": iso_local(a.end_at, tz),
        "status": a.status,
        "source": a.source,
        "recovered": a.recovered,
        "reminder_sent": a.reminder_sent_at is not None,
        "confirmed_at": iso_local(a.confirmed_at, tz),
        "cancelled_reason": a.cancelled_reason,
        "notes": a.notes,
        "created_at": iso_local(a.created_at, tz),
    }


def message_out(m: MessageLog, tz: str) -> dict[str, Any]:
    return {
        "id": m.id,
        "contact_id": m.contact_id,
        "staff_id": m.staff_id,
        "direction": m.direction,
        "phone": m.phone,
        "content": m.content,
        "template_name": m.template_name,
        "audience": m.audience,
        "handled_by": m.handled_by,
        "status": m.status,
        "error": m.error,
        "created_at": iso_local(m.created_at, tz),
    }


def admin_user_out(u: AdminUser) -> dict[str, Any]:
    return {
        "id": u.id,
        "email": u.email,
        "name": u.name,
        "business_id": u.business_id,
        "is_active": u.is_active,
    }
