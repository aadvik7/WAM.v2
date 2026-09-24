"""Appointments: book (with a database lock), reschedule, cancel, confirm, mark done / missed.

Plain code makes every booking decision. The AI can only propose a slot; `book` re-validates it.
"""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.engine import schedules as sched_engine
from wam.engine.slots import find_free_slots, load_busy
from wam.models import (
    Appointment,
    AppointmentStatus,
    Business,
    Contact,
    Resource,
    Schedule,
    ScheduleStatus,
)


class BookingError(Exception):
    """A booking could not be made; the message is safe to show to a patient or staff member."""


class SlotUnavailable(BookingError):
    pass


async def _lock_resource(session: AsyncSession, resource_id: int) -> Resource | None:
    # Row lock on the resource serialises all bookings for that doctor/room.
    return (
        await session.execute(select(Resource).where(Resource.id == resource_id).with_for_update())
    ).scalar_one_or_none()


def _is_recovered(
    schedule: Schedule | None, business: Business, source: str, rebooked_from: Appointment | None
) -> bool:
    """A visit is 'recovered' when a patient who was overdue or missed a visit rebooks through WAM."""
    if source != "whatsapp":
        return False
    if rebooked_from is not None and rebooked_from.status == AppointmentStatus.MISSED:
        return True
    if schedule is None:
        return False
    today = clock.local_today(business.timezone)
    overdue = schedule.next_due_date is not None and schedule.next_due_date < today
    return overdue or schedule.missed_count > 0 or schedule.nudge_count > 1


async def book(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    resource_id: int,
    start_at: dt.datetime,
    *,
    duration_minutes: int | None = None,
    schedule_id: int | None = None,
    source: str = "whatsapp",
    service: str | None = None,
    enforce_availability: bool = True,
    rebooked_from: Appointment | None = None,
    notes: str | None = None,
) -> Appointment:
    """Book one slot. Takes a lock on the resource so two patients can't get the same slot.

    With `enforce_availability` (patients, AI) the start must be an exact free slot from the slot
    engine (working hours, breaks, leave, notice period). Staff/admin bookings may skip that check but
    can never overlap another active appointment.
    """
    if start_at.tzinfo is None:
        raise BookingError("Internal error: naive datetime")
    resource = await _lock_resource(session, resource_id)
    if resource is None or resource.business_id != business.id or not resource.is_active:
        raise BookingError("That doctor is not available for booking.")
    if contact.business_id != business.id:
        raise BookingError("Unknown patient.")

    schedule: Schedule | None = None
    if schedule_id is not None:
        schedule = await session.get(Schedule, schedule_id, with_for_update=True)
        if schedule is None or schedule.contact_id != contact.id or schedule.status != ScheduleStatus.ACTIVE:
            raise BookingError("That treatment plan is not active.")
        await session.refresh(schedule, ["template"])
        if duration_minutes is None and schedule.template.duration_minutes:
            duration_minutes = schedule.template.duration_minutes
        service = service or sched_engine.session_label(schedule.template, schedule.sessions_done + 1)

    length = dt.timedelta(minutes=duration_minutes or resource.slot_minutes)
    start_at = start_at.astimezone(dt.UTC).replace(second=0, microsecond=0)
    end_at = start_at + length

    # An existing active booking for the same plan is moved rather than duplicated.
    previous: Appointment | None = None
    if schedule is not None:
        previous = await sched_engine.active_appointment_for_schedule(session, schedule.id)
    if rebooked_from is not None and rebooked_from.status in AppointmentStatus.ACTIVE:
        previous = rebooked_from

    exclude_id = previous.id if previous is not None else None
    if enforce_availability:
        day = clock.to_local(start_at, business.timezone).date()
        free = await find_free_slots(
            session,
            business,
            resource,
            day,
            day,
            duration_minutes=int(length.total_seconds() // 60),
            exclude_appointment_id=exclude_id,
        )
        if not any(s.start == start_at for s in free):
            raise SlotUnavailable("Sorry, that slot is no longer free.")
    else:
        if start_at < clock.now() - dt.timedelta(minutes=5):
            raise BookingError("That time is in the past.")
        busy = await load_busy(session, resource.id, (start_at, end_at), exclude_appointment_id=exclude_id)
        if busy:
            raise SlotUnavailable("That time overlaps another appointment.")

    appt = Appointment(
        business_id=business.id,
        resource_id=resource.id,
        contact_id=contact.id,
        schedule_id=schedule.id if schedule else None,
        session_number=(schedule.sessions_done + 1) if schedule else None,
        service=service,
        start_at=start_at,
        end_at=end_at,
        status=AppointmentStatus.BOOKED,
        source=source,
        recovered=_is_recovered(schedule, business, source, rebooked_from),
        rebooked_from_id=(rebooked_from.id if rebooked_from else (previous.id if previous else None)),
        notes=notes,
    )
    try:
        # Savepoint: if the insert fails, the old booking stays active and nothing half-applies.
        async with session.begin_nested():
            if previous is not None:
                previous.status = AppointmentStatus.CANCELLED
                previous.cancelled_reason = "rescheduled"
                await session.flush()
            session.add(appt)
            await session.flush()
    except IntegrityError as exc:  # exclusion constraint: last line of defence against double booking
        raise SlotUnavailable("Sorry, that slot was just taken.") from exc
    if schedule is not None:
        schedule.needs_staff = False
    contact.needs_staff = False
    await session.refresh(appt, ["contact", "resource"])
    return appt


async def cancel(session: AsyncSession, appt: Appointment, reason: str) -> None:
    if appt.status not in AppointmentStatus.ACTIVE:
        raise BookingError("That appointment is not active.")
    appt.status = AppointmentStatus.CANCELLED
    appt.cancelled_reason = reason[:200]


async def confirm(session: AsyncSession, appt: Appointment) -> None:
    if appt.status == AppointmentStatus.BOOKED:
        appt.status = AppointmentStatus.CONFIRMED
        appt.confirmed_at = clock.now()


async def mark(session: AsyncSession, business: Business, appt: Appointment, status: str) -> None:
    """Mark attendance. Moving to done advances the plan; corrections are handled."""
    if status not in (AppointmentStatus.DONE, AppointmentStatus.MISSED):
        raise BookingError("Attendance must be done or missed.")
    if appt.status == status:
        return
    if appt.status == AppointmentStatus.CANCELLED:
        raise BookingError("That appointment was cancelled.")
    previous = appt.status
    appt.status = status
    appt.marked_at = clock.now()
    if previous == AppointmentStatus.DONE:
        await sched_engine.reopen_after_unmark(session, business, appt)
    if status == AppointmentStatus.DONE:
        await sched_engine.on_appointment_done(session, business, appt)
    else:
        await sched_engine.on_appointment_missed(session, appt)


async def upcoming_for_contact(session: AsyncSession, contact_id: int) -> list[Appointment]:
    return list(
        (
            await session.execute(
                select(Appointment)
                .where(
                    Appointment.contact_id == contact_id,
                    Appointment.status.in_(AppointmentStatus.ACTIVE),
                    Appointment.end_at > clock.now(),
                )
                .order_by(Appointment.start_at)
            )
        )
        .scalars()
        .unique()
        .all()
    )


async def day_list(
    session: AsyncSession, business: Business, day: dt.date, resource_id: int | None = None
) -> list[Appointment]:
    start, end = clock.day_bounds(day, business.timezone)
    stmt = (
        select(Appointment)
        .where(
            Appointment.business_id == business.id,
            Appointment.start_at >= start,
            Appointment.start_at < end,
            Appointment.status != AppointmentStatus.CANCELLED,
        )
        .order_by(Appointment.start_at, Appointment.id)
    )
    if resource_id is not None:
        stmt = stmt.where(Appointment.resource_id == resource_id)
    return list((await session.execute(stmt)).scalars().unique().all())


async def ensure_exclusion_constraint(session: AsyncSession) -> None:
    """Used by tests/dev when tables are created without migrations."""
    await session.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
    await session.execute(
        text(
            """
            DO $$ BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ex_appointments_no_overlap') THEN
                ALTER TABLE appointments ADD CONSTRAINT ex_appointments_no_overlap
                  EXCLUDE USING gist (resource_id WITH =, tstzrange(start_at, end_at) WITH &&)
                  WHERE (status IN ('booked','confirmed'));
              END IF;
            END $$;
            """
        )
    )
