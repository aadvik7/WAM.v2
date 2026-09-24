"""Shared engine data model.

Every table uses generic names so the institute and business packs fit without a rewrite.
All timestamps are stored in UTC (timestamptz); local times (working hours) are interpreted
in the business's timezone.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wam import clock
from wam.db import Base


def _now() -> dt.datetime:
    return clock.now()


def _now_col() -> Mapped[dt.datetime]:
    # App clock (so frozen time in tests is consistent); server default covers raw SQL inserts.
    return mapped_column(DateTime(timezone=True), default=_now, server_default=func.now(), nullable=False)


class BusinessType:
    CLINIC = "clinic"
    INSTITUTE = "institute"
    BUSINESS = "business"
    ALL = (CLINIC, INSTITUTE, BUSINESS)


class AppointmentStatus:
    BOOKED = "booked"
    CONFIRMED = "confirmed"
    DONE = "done"
    MISSED = "missed"
    CANCELLED = "cancelled"
    ACTIVE = (BOOKED, CONFIRMED)
    ALL = (BOOKED, CONFIRMED, DONE, MISSED, CANCELLED)


class ScheduleStatus:
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ALL = (ACTIVE, PAUSED, COMPLETED, CANCELLED)


class JobStatus:
    SCHEDULED = "scheduled"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"
    ALL = (SCHEDULED, RUNNING, DONE, FAILED, CANCELLED)


# --------------------------------------------------------------------------------------
# Businesses, staff, roles
# --------------------------------------------------------------------------------------


class Business(Base):
    __tablename__ = "businesses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False, default=BusinessType.CLINIC)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Kolkata")
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    maps_url: Mapped[str | None] = mapped_column(String(500))
    emergency_number: Mapped[str | None] = mapped_column(String(32))
    # Opening hours shown to patients: {"mon": [["09:00","13:00"],["17:00","20:00"]], ...}
    hours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # Chatwoot mapping
    chatwoot_account_id: Mapped[int | None] = mapped_column(Integer)
    chatwoot_inbox_id: Mapped[int | None] = mapped_column(Integer)
    chatwoot_api_token: Mapped[str | None] = mapped_column(String(200))
    chatwoot_bot_token: Mapped[str | None] = mapped_column(String(200))
    # The agent bot's secret; when set, webhooks must carry a valid X-Chatwoot-Signature.
    chatwoot_webhook_secret: Mapped[str | None] = mapped_column(String(200))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (
        CheckConstraint("type IN ('clinic','institute','business')", name="ck_businesses_type"),
        UniqueConstraint("chatwoot_account_id", "chatwoot_inbox_id", name="uq_businesses_chatwoot_inbox"),
    )


class Role(Base):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    # List of command keys this role may run; ["*"] means everything.
    allowed_commands: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_roles_business_name"),)


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id", ondelete="SET NULL"))
    pin_hash: Mapped[str | None] = mapped_column(String(200))
    pin_failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    pin_locked_until: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    permissions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    receives_eod_list: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_inbound_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    chatwoot_contact_id: Mapped[int | None] = mapped_column(Integer)
    chatwoot_source_id: Mapped[str | None] = mapped_column(String(200))
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = _now_col()

    role: Mapped[Role | None] = relationship(lazy="selectin")

    __table_args__ = (UniqueConstraint("business_id", "phone", name="uq_staff_business_phone"),)


# --------------------------------------------------------------------------------------
# Contacts and groups
# --------------------------------------------------------------------------------------


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str | None] = mapped_column(String(120))
    # E.164 phone. Nullable: a child can be reached through a linked guardian contact.
    phone: Mapped[str | None] = mapped_column(String(32))
    language: Mapped[str | None] = mapped_column(String(10))
    date_of_birth: Mapped[dt.date | None] = mapped_column(Date)
    guardian_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    # Roll number / student ID (institute pack); unique per business
    external_id: Mapped[str | None] = mapped_column(String(50))
    consent_notice_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    consent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    opted_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    notes: Mapped[str | None] = mapped_column(Text)
    needs_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_inbound_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    chatwoot_contact_id: Mapped[int | None] = mapped_column(Integer)
    chatwoot_source_id: Mapped[str | None] = mapped_column(String(200))
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = _now_col()

    guardian: Mapped[Contact | None] = relationship(remote_side="Contact.id", lazy="selectin", join_depth=1)

    __table_args__ = (
        Index(
            "uq_contacts_business_phone",
            "business_id",
            "phone",
            unique=True,
            postgresql_where=text("phone IS NOT NULL AND guardian_id IS NULL"),
        ),
        Index("ix_contacts_business_name", "business_id", "name"),
        Index(
            "uq_contacts_business_external_id",
            "business_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="list")
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_groups_business_name"),)


class GroupMember(Base):
    __tablename__ = "group_members"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), primary_key=True)
    added_at: Mapped[dt.datetime] = _now_col()


# --------------------------------------------------------------------------------------
# Resources and availability
# --------------------------------------------------------------------------------------


class Resource(Base):
    """Who or what gets booked: doctor, teacher, stylist, room."""

    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="doctor")
    specialty: Mapped[str | None] = mapped_column(String(60))
    slot_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (CheckConstraint("slot_minutes BETWEEN 5 AND 480", name="ck_resources_slot_minutes"),)


class Availability(Base):
    """Working hours (weekly), breaks (weekly or every day), leave and extra one-off hours (date-time ranges)."""

    __tablename__ = "availability"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # weekly | break | leave | extra
    weekday: Mapped[int | None] = mapped_column(SmallInteger)  # 0=Monday … 6=Sunday; NULL break = every day
    start_time: Mapped[dt.time | None] = mapped_column(Time)
    end_time: Mapped[dt.time | None] = mapped_column(Time)
    start_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # leave
    end_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))  # leave
    reason: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (
        CheckConstraint("kind IN ('weekly','break','leave','extra')", name="ck_availability_kind"),
        CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="ck_availability_weekday"),
        CheckConstraint(
            "(kind IN ('leave','extra') AND start_at IS NOT NULL AND end_at IS NOT NULL AND end_at > start_at) OR "
            "(kind IN ('weekly','break') AND start_time IS NOT NULL AND end_time IS NOT NULL AND end_time > start_time)",
            name="ck_availability_shape",
        ),
        CheckConstraint("kind <> 'weekly' OR weekday IS NOT NULL", name="ck_availability_weekly_weekday"),
        Index("ix_availability_resource", "resource_id", "kind"),
    )


# --------------------------------------------------------------------------------------
# Recurring schedules
# --------------------------------------------------------------------------------------


class ScheduleTemplate(Base):
    """A recurring pattern: session count, gap between sessions, reminder rules."""

    __tablename__ = "schedule_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialty: Mapped[str | None] = mapped_column(String(60))
    # NULL session_count => ongoing (recall) plan
    session_count: Mapped[int | None] = mapped_column(Integer)
    gap_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    # Optional explicit offsets (days from the plan's anchor date) per session, e.g. vaccinations.
    offsets_days: Mapped[list[int] | None] = mapped_column(JSONB)
    session_labels: Mapped[list[str] | None] = mapped_column(JSONB)
    duration_minutes: Mapped[int | None] = mapped_column(SmallInteger)
    reminder_rules: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # visit = book a slot when due; payment = remind before each due date (fee installments)
    kind: Mapped[str] = mapped_column(String(10), nullable=False, default="visit", server_default="visit")
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (
        UniqueConstraint("business_id", "name", name="uq_schedule_templates_business_name"),
        CheckConstraint("gap_days >= 0", name="ck_schedule_templates_gap"),
        CheckConstraint("session_count IS NULL OR session_count >= 1", name="ck_schedule_templates_count"),
        CheckConstraint("kind IN ('visit','payment')", name="ck_schedule_templates_kind"),
    )

    @property
    def is_ongoing(self) -> bool:
        return self.session_count is None and not self.offsets_days

    @property
    def is_payment(self) -> bool:
        return self.kind == "payment"


class Schedule(Base):
    """One contact on one template: sessions done, next due date, status."""

    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    template_id: Mapped[int] = mapped_column(
        ForeignKey("schedule_templates.id", ondelete="RESTRICT"), nullable=False
    )
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("resources.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=ScheduleStatus.ACTIVE)
    anchor_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    sessions_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sessions_total: Mapped[int | None] = mapped_column(Integer)
    next_due_date: Mapped[dt.date | None] = mapped_column(Date)
    # Installment amount for payment plans (overrides the template's amount)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    nudge_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_nudged_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    missed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    needs_staff: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = _now_col()
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    template: Mapped[ScheduleTemplate] = relationship(lazy="selectin")
    contact: Mapped[Contact] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("status IN ('active','paused','completed','cancelled')", name="ck_schedules_status"),
        Index("ix_schedules_due", "business_id", "status", "next_due_date"),
        Index("ix_schedules_contact", "contact_id"),
    )


class Appointment(Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id", ondelete="RESTRICT"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    schedule_id: Mapped[int | None] = mapped_column(ForeignKey("schedules.id", ondelete="SET NULL"))
    session_number: Mapped[int | None] = mapped_column(Integer)
    service: Mapped[str | None] = mapped_column(String(120))
    start_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=AppointmentStatus.BOOKED)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="whatsapp")
    # True when the booking recovered an overdue or missed visit through WAM (headline metric).
    recovered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rebooked_from_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id", ondelete="SET NULL"))
    reminder_sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    marked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_reason: Mapped[str | None] = mapped_column(String(200))
    followup_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[dt.datetime] = _now_col()
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), onupdate=_now, nullable=False
    )

    contact: Mapped[Contact] = relationship(lazy="selectin")
    resource: Mapped[Resource] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint(
            "status IN ('booked','confirmed','done','missed','cancelled')", name="ck_appointments_status"
        ),
        CheckConstraint("end_at > start_at", name="ck_appointments_range"),
        Index("ix_appointments_resource_start", "resource_id", "start_at"),
        Index("ix_appointments_business_start", "business_id", "start_at"),
        Index("ix_appointments_contact", "contact_id"),
    )


# --------------------------------------------------------------------------------------
# Content, messaging, jobs, audit
# --------------------------------------------------------------------------------------


class Faq(Base):
    __tablename__ = "faqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[dt.datetime] = _now_col()


class Broadcast(Base):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    template_name: Mapped[str] = mapped_column(String(100), nullable=False)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    sender_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    created_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    message: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # parents | students | everyone
    audience: Mapped[str] = mapped_column(
        String(10), nullable=False, default="everyone", server_default="everyone"
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="draft"
    )  # draft|sending|sent|cancelled
    recipients_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    sent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    delivered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_at: Mapped[dt.datetime] = _now_col()
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class BroadcastRecipient(Base):
    """One person an announcement goes to (each person individually), with WhatsApp delivery status."""

    __tablename__ = "broadcast_recipients"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    broadcast_id: Mapped[int] = mapped_column(ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    # queued | sent | delivered | read | failed | skipped
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="queued")
    error: Mapped[str | None] = mapped_column(Text)
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(Integer)
    chatwoot_message_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_now, server_default=func.now(), onupdate=_now, nullable=False
    )

    contact: Mapped[Contact] = relationship(lazy="selectin")

    __table_args__ = (
        UniqueConstraint("broadcast_id", "contact_id", name="uq_broadcast_recipients_contact"),
        Index("ix_broadcast_recipients_status", "broadcast_id", "status"),
    )


class MessageLog(Base):
    __tablename__ = "message_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="SET NULL"))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # in | out
    phone: Mapped[str | None] = mapped_column(String(32))
    content: Mapped[str | None] = mapped_column(Text)
    template_name: Mapped[str | None] = mapped_column(String(100))
    # patient | staff | system
    audience: Mapped[str] = mapped_column(String(10), nullable=False, default="patient")
    # ai | rule | staff | system | none — who produced the reply (for "answered without staff")
    handled_by: Mapped[str | None] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ok")  # ok | failed | dry_run
    error: Mapped[str | None] = mapped_column(Text)
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(Integer)
    chatwoot_message_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (
        CheckConstraint("direction IN ('in','out')", name="ck_message_log_direction"),
        Index(
            "uq_message_log_chatwoot_in",
            "business_id",
            "chatwoot_message_id",
            unique=True,
            postgresql_where=text("direction = 'in' AND chatwoot_message_id IS NOT NULL"),
        ),
        Index("ix_message_log_business_created", "business_id", "created_at"),
        Index("ix_message_log_contact_created", "contact_id", "created_at"),
    )


class Job(Base):
    """Scheduled sends and their state."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    run_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=JobStatus.SCHEDULED)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    created_at: Mapped[dt.datetime] = _now_col()
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint(
            "status IN ('scheduled','running','done','failed','cancelled')", name="ck_jobs_status"
        ),
        Index("ix_jobs_due", "status", "run_at"),
    )


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    admin_user_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    phone: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (Index("ix_audit_log_business_created", "business_id", "created_at"),)


class PendingAction(Base):
    """A staff action waiting for 'YES <PIN>' confirmation."""

    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = _now_col()


class ConversationState(Base):
    """Short-lived per-person state, e.g. the slots offered to a patient or today's list sent to staff."""

    __tablename__ = "conversation_states"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"))
    staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(50), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (
        Index("ix_conversation_states_contact", "contact_id", "key"),
        Index("ix_conversation_states_staff", "staff_id", "key"),
    )


class AdminUser(Base):
    """Web admin login. business_id NULL => super admin (all businesses)."""

    __tablename__ = "admin_users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(200), nullable=False)
    business_id: Mapped[int | None] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[dt.datetime] = _now_col()
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


# --------------------------------------------------------------------------------------
# Institute pack
# --------------------------------------------------------------------------------------


class ContactLink(Base):
    """Links a student to their parents (1–2 numbers per student)."""

    __tablename__ = "contact_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    linked_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    relation: Mapped[str] = mapped_column(String(20), nullable=False, default="parent")
    created_at: Mapped[dt.datetime] = _now_col()

    linked: Mapped[Contact] = relationship(foreign_keys=[linked_id], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("contact_id", "linked_id", name="uq_contact_links_pair"),
        CheckConstraint("contact_id <> linked_id", name="ck_contact_links_not_self"),
        Index("ix_contact_links_linked", "linked_id"),
    )


class GroupStaff(Base):
    """Teachers assigned to a batch (a teacher can message and see only their own batches)."""

    __tablename__ = "group_staff"

    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    staff_id: Mapped[int] = mapped_column(ForeignKey("staff.id", ondelete="CASCADE"), primary_key=True)


class Subject(Base):
    """A subject whose doubts go to one Chatwoot team (e.g. Physics → Physics teachers)."""

    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    chatwoot_team_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (UniqueConstraint("business_id", "name", name="uq_subjects_business_name"),)


class Doubt(Base):
    __tablename__ = "doubts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id", ondelete="CASCADE"), nullable=False)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"))
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="open")  # open | closed
    chatwoot_conversation_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[dt.datetime] = _now_col()
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    contact: Mapped[Contact] = relationship(lazy="selectin")
    subject: Mapped[Subject | None] = relationship(lazy="selectin")

    __table_args__ = (
        CheckConstraint("status IN ('open','closed')", name="ck_doubts_status"),
        Index("ix_doubts_business_status", "business_id", "status"),
    )


class Import(Base):
    """An uploaded sheet (students, attendance, test results, timetable): parsed, previewed, then sent."""

    __tablename__ = "imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # students | attendance | results | timetable
    filename: Mapped[str | None] = mapped_column(String(200))
    label: Mapped[str | None] = mapped_column(String(200))  # class name / test name
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"))
    rows: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    summary: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="preview"
    )  # preview|applied|cancelled
    created_by_staff_id: Mapped[int | None] = mapped_column(ForeignKey("staff.id", ondelete="SET NULL"))
    created_by_admin_id: Mapped[int | None] = mapped_column(ForeignKey("admin_users.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = _now_col()
    applied_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("kind IN ('students','attendance','results','timetable')", name="ck_imports_kind"),
        CheckConstraint("status IN ('preview','applied','cancelled')", name="ck_imports_status"),
    )


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    weekday: Mapped[int | None] = mapped_column(SmallInteger)  # 0=Mon; NULL when `date` is set
    date: Mapped[dt.date | None] = mapped_column(Date)  # one-off entry that overrides the weekday plan
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time | None] = mapped_column(Time)
    subject: Mapped[str] = mapped_column(String(80), nullable=False)
    teacher: Mapped[str | None] = mapped_column(String(120))
    room: Mapped[str | None] = mapped_column(String(60))

    __table_args__ = (
        CheckConstraint("(weekday IS NOT NULL) <> (date IS NOT NULL)", name="ck_timetable_day"),
        CheckConstraint("weekday IS NULL OR weekday BETWEEN 0 AND 6", name="ck_timetable_weekday"),
        Index("ix_timetable_group", "group_id", "weekday"),
    )


class PtmEvent(Base):
    """A parent-teacher meeting session: parents of a batch book short slots with its teachers."""

    __tablename__ = "ptm_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    business_id: Mapped[int] = mapped_column(ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="Parent-teacher meeting")
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    start_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    end_time: Mapped[dt.time] = mapped_column(Time, nullable=False)
    slot_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=10)
    resource_ids: Mapped[list[int]] = mapped_column(JSONB, nullable=False, default=list)
    broadcast_id: Mapped[int | None] = mapped_column(ForeignKey("broadcasts.id", ondelete="SET NULL"))
    created_at: Mapped[dt.datetime] = _now_col()

    __table_args__ = (
        CheckConstraint("end_time > start_time", name="ck_ptm_events_range"),
        CheckConstraint("slot_minutes BETWEEN 5 AND 60", name="ck_ptm_events_slot"),
        Index("ix_ptm_events_group_date", "group_id", "date"),
    )
