"""Recurring schedules: enrolment, due dates and progression.

A 3-sitting root canal, 6 laser sessions, a vaccination schedule and a 6-monthly cleaning recall are
all the same thing: a series of due dates with reminders and follow-ups.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.models import (
    Appointment,
    AppointmentStatus,
    Business,
    Contact,
    Schedule,
    ScheduleStatus,
    ScheduleTemplate,
)


class ScheduleError(Exception):
    pass


def total_sessions(template: ScheduleTemplate) -> int | None:
    if template.offsets_days:
        return len(template.offsets_days)
    return template.session_count


def due_date_for_session(
    template: ScheduleTemplate, anchor: dt.date, session_number: int, last_visit: dt.date | None
) -> dt.date:
    """Due date for 1-based `session_number`.

    Offsets templates (e.g. vaccinations) are anchored to the plan's anchor date (date of birth).
    Payment plans (fee installments) fall due on fixed dates: anchor + (n − 1) × gap.
    Gap templates: session 1 is due on the anchor date, later sessions `gap_days` after the last visit.
    """
    if template.offsets_days:
        idx = min(session_number - 1, len(template.offsets_days) - 1)
        return anchor + dt.timedelta(days=int(template.offsets_days[idx]))
    if template.kind == "payment":
        return anchor + dt.timedelta(days=template.gap_days * max(session_number - 1, 0))
    if session_number <= 1 or last_visit is None:
        return anchor
    return last_visit + dt.timedelta(days=template.gap_days)


def session_label(template: ScheduleTemplate, session_number: int) -> str:
    labels = template.session_labels or []
    if template.kind == "payment":
        total = total_sessions(template)
        return f"{template.name} (installment {session_number}{f' of {total}' if total else ''})"
    if 0 < session_number <= len(labels) and labels[session_number - 1]:
        return f"{template.name} ({labels[session_number - 1]})"
    total = total_sessions(template)
    if total and total > 1:
        return f"{template.name} (visit {session_number} of {total})"
    return template.name


def ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


async def enrol(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    template: ScheduleTemplate,
    *,
    resource_id: int | None = None,
    anchor_date: dt.date | None = None,
    sessions_done: int = 0,
    first_due: dt.date | None = None,
    staff_id: int | None = None,
    notes: str | None = None,
    amount: Decimal | None = None,
) -> Schedule:
    """Put a contact on a plan. Session 1 is due on the anchor date (default: today)."""
    if template.business_id != business.id or contact.business_id != business.id:
        raise ScheduleError("Template and contact must belong to the business")
    if not template.is_active:
        raise ScheduleError(f"Plan '{template.name}' is not active")
    today = clock.local_today(business.timezone)
    anchor = anchor_date or today
    if template.kind == "payment" and not template.offsets_days and (first_due or not anchor_date):
        # Installments fall on anchor + (n − 1) × gap; anchor the series so the next one lands on
        # first_due (default: today) and later ones follow at the plan's gap.
        anchor = (first_due or today) - dt.timedelta(days=template.gap_days * sessions_done)
    total = total_sessions(template)
    if total is not None and sessions_done >= total:
        raise ScheduleError("All sessions are already done")

    existing = (
        await session.execute(
            select(Schedule).where(
                Schedule.contact_id == contact.id,
                Schedule.template_id == template.id,
                Schedule.status.in_([ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED]),
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        raise ScheduleError(f"{contact.name or 'This patient'} is already on '{template.name}'")

    next_session = sessions_done + 1
    if first_due is not None:
        next_due = first_due
    elif template.offsets_days or template.kind == "payment":
        next_due = due_date_for_session(template, anchor, next_session, None)
    elif sessions_done == 0:
        next_due = anchor
    else:
        next_due = today
    schedule = Schedule(
        business_id=business.id,
        contact_id=contact.id,
        template_id=template.id,
        resource_id=resource_id,
        status=ScheduleStatus.ACTIVE,
        anchor_date=anchor,
        sessions_done=sessions_done,
        sessions_total=total,
        next_due_date=next_due,
        created_by_staff_id=staff_id,
        notes=notes,
        amount=amount,
    )
    session.add(schedule)
    await session.flush()
    await session.refresh(schedule, ["template", "contact"])
    return schedule


async def on_appointment_done(session: AsyncSession, business: Business, appt: Appointment) -> None:
    """A visit happened: advance the plan to the next due date or complete it."""
    if appt.schedule_id is None:
        return
    schedule = await session.get(Schedule, appt.schedule_id, with_for_update=True)
    if schedule is None or schedule.status not in (ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED):
        return
    await session.refresh(schedule, ["template"])
    template = schedule.template
    schedule.sessions_done += 1
    schedule.nudge_count = 0
    schedule.last_nudged_at = None
    schedule.missed_count = 0
    schedule.needs_staff = False
    total = schedule.sessions_total
    if total is not None and schedule.sessions_done >= total:
        schedule.status = ScheduleStatus.COMPLETED
        schedule.next_due_date = None
        schedule.completed_at = clock.now()
        return
    visit_day = clock.to_local(appt.start_at, business.timezone).date()
    schedule.next_due_date = due_date_for_session(
        template, schedule.anchor_date, schedule.sessions_done + 1, visit_day
    )


async def record_payment(session: AsyncSession, schedule: Schedule) -> None:
    """One installment of a payment plan was paid: move to the next due date or complete the plan."""
    await session.refresh(schedule, ["template"])
    template = schedule.template
    if template.kind != "payment":
        raise ScheduleError("Only fee plans take payments")
    if schedule.status not in (ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED):
        raise ScheduleError("This plan is not active")
    schedule.sessions_done += 1
    schedule.nudge_count = 0
    schedule.last_nudged_at = None
    schedule.needs_staff = False
    total = schedule.sessions_total
    if total is not None and schedule.sessions_done >= total:
        schedule.status = ScheduleStatus.COMPLETED
        schedule.next_due_date = None
        schedule.completed_at = clock.now()
        return
    schedule.next_due_date = due_date_for_session(
        template, schedule.anchor_date, schedule.sessions_done + 1, None
    )


async def on_appointment_missed(session: AsyncSession, appt: Appointment) -> None:
    if appt.schedule_id is None:
        return
    schedule = await session.get(Schedule, appt.schedule_id, with_for_update=True)
    if schedule is None or schedule.status != ScheduleStatus.ACTIVE:
        return
    schedule.missed_count += 1


async def reopen_after_unmark(session: AsyncSession, business: Business, appt: Appointment) -> None:
    """Undo `on_appointment_done` when staff correct a visit from done back to missed/booked."""
    if appt.schedule_id is None:
        return
    schedule = await session.get(Schedule, appt.schedule_id, with_for_update=True)
    if schedule is None or schedule.sessions_done <= 0:
        return
    await session.refresh(schedule, ["template"])
    schedule.sessions_done -= 1
    if schedule.status == ScheduleStatus.COMPLETED:
        schedule.status = ScheduleStatus.ACTIVE
        schedule.completed_at = None
    schedule.next_due_date = clock.to_local(appt.start_at, business.timezone).date()


async def active_appointment_for_schedule(session: AsyncSession, schedule_id: int) -> Appointment | None:
    return (
        await session.execute(
            select(Appointment)
            .where(
                Appointment.schedule_id == schedule_id,
                Appointment.status.in_(AppointmentStatus.ACTIVE),
            )
            .order_by(Appointment.start_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def set_next_due(session: AsyncSession, schedule: Schedule, due: dt.date) -> None:
    template = await session.get(ScheduleTemplate, schedule.template_id)
    if template is not None and template.kind == "payment" and not template.offsets_days:
        # Moving an installment moves the ones after it too.
        schedule.anchor_date = due - dt.timedelta(days=template.gap_days * schedule.sessions_done)
    schedule.next_due_date = due
    schedule.nudge_count = 0
    schedule.last_nudged_at = None
    if schedule.status == ScheduleStatus.PAUSED:
        schedule.status = ScheduleStatus.ACTIVE


async def contact_schedules(
    session: AsyncSession, contact_id: int, only_active: bool = True
) -> list[Schedule]:
    stmt = select(Schedule).where(Schedule.contact_id == contact_id).order_by(Schedule.id)
    if only_active:
        stmt = stmt.where(Schedule.status == ScheduleStatus.ACTIVE)
    return list((await session.execute(stmt)).scalars().unique().all())
