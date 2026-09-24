"""The return-visit loop: offers, nudges, reminders, missed-visit follow-ups and rebooking.

Every step here is plain code. The AI agent calls into these functions; it never books on its own.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.engine import appointments as appt_engine
from wam.engine import schedules as sched_engine
from wam.engine.appointments import BookingError, SlotUnavailable
from wam.engine.slots import Slot, active_resources, offer_slots
from wam.messaging import Outgoing, send_to_contact, send_to_staff
from wam.models import (
    Appointment,
    AppointmentStatus,
    Business,
    Contact,
    Resource,
    Role,
    Schedule,
    ScheduleStatus,
    ScheduleTemplate,
    Staff,
)
from wam.packs import get_pack
from wam.settings_defaults import get_setting
from wam.state import clear_state, get_state, set_state
from wam.templates import slots_param

log = logging.getLogger(__name__)

OFFER_TTL = dt.timedelta(days=3)


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


def greeting_name(contact: Contact) -> str:
    if contact.guardian is not None and not contact.phone:
        return contact.guardian.name or "there"
    return (contact.name or "there").split(" ")[0]


def plan_label(template: ScheduleTemplate, session_number: int) -> str:
    """'Root canal (2nd sitting)', 'Physio course (visit 3 of 10)', 'Cleaning recall'."""
    return sched_engine.session_label(template, session_number)


def for_whom(contact: Contact, label: str) -> str:
    """'Aarav's Vaccination schedule (6-week doses)' when messaging a guardian."""
    if contact.guardian is not None and not contact.phone and contact.name:
        return f"{contact.name.split(' ')[0]}'s {label}"
    return f"your {label}"


async def resources_for(
    session: AsyncSession, business: Business, template: ScheduleTemplate | None, preferred_id: int | None
) -> list[Resource]:
    resources = await active_resources(session, business.id)
    if preferred_id is not None:
        preferred = [r for r in resources if r.id == preferred_id]
        if preferred:
            return preferred
    if template is not None and template.specialty:
        matching = [r for r in resources if (r.specialty or "").lower() == template.specialty.lower()]
        if matching:
            return matching
    return resources


def slot_labels(
    slots: Sequence[Slot], business: Business, resources: dict[int, Resource], multi: bool
) -> list[str]:
    labels = []
    for s in slots:
        label = clock.fmt_slot(s.start, business.timezone)
        if multi and s.resource_id in resources:
            label += f" ({resources[s.resource_id].name})"
        labels.append(label)
    return labels


def numbered(labels: Sequence[str]) -> str:
    return "\n".join(f"{i}) {label}" for i, label in enumerate(labels, start=1))


async def save_offer(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    slots: Sequence[Slot],
    labels: Sequence[str],
    *,
    purpose: str,
    schedule_id: int | None = None,
    move_appointment_id: int | None = None,
    rebooked_from_id: int | None = None,
    duration_minutes: int | None = None,
) -> None:
    await set_state(
        session,
        business_id=business.id,
        contact_id=contact.id,
        key="offer",
        data={
            "purpose": purpose,
            "slots": [s.key for s in slots],
            "ends": [s.end.isoformat() for s in slots],
            "labels": list(labels),
            "schedule_id": schedule_id,
            "move_appointment_id": move_appointment_id,
            "rebooked_from_id": rebooked_from_id,
            "duration_minutes": duration_minutes,
        },
        ttl=OFFER_TTL,
    )


async def build_offer(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    *,
    date_from: dt.date,
    purpose: str,
    schedule: Schedule | None = None,
    resource_ids: list[int] | None = None,
    move_appointment: Appointment | None = None,
    rebooked_from: Appointment | None = None,
    count: int | None = None,
    days: int = 14,
    part_of_day: str | None = None,
) -> tuple[list[Slot], list[str]]:
    """Find well-spread free slots, remember them as the contact's current offer, return labels."""
    template = schedule.template if schedule is not None else None
    preferred = schedule.resource_id if schedule is not None else None
    if move_appointment is not None:
        preferred = move_appointment.resource_id
    resources = await resources_for(session, business, template, preferred)
    if resource_ids:
        resources = [r for r in resources if r.id in resource_ids] or [
            r for r in await active_resources(session, business.id) if r.id in resource_ids
        ]
    duration = None
    if template is not None and template.duration_minutes:
        duration = template.duration_minutes
    elif move_appointment is not None:
        duration = int((move_appointment.end_at - move_appointment.start_at).total_seconds() // 60)
    exclude_id = move_appointment.id if move_appointment is not None else None
    if part_of_day:
        pool = await offer_slots(
            session,
            business,
            resources,
            date_from,
            count=60,
            duration_minutes=duration,
            days=days,
            exclude_appointment_id=exclude_id,
        )
        pool = [s for s in pool if _in_part_of_day(s, business, part_of_day)]
        from wam.engine.slots import pick_spread

        slots = pick_spread(
            pool, count or int(get_setting(business.settings, "offer_slot_count")), business.timezone
        )
    else:
        slots = await offer_slots(
            session,
            business,
            resources,
            date_from,
            count=count,
            duration_minutes=duration,
            days=days,
            exclude_appointment_id=exclude_id,
        )
    by_id = {r.id: r for r in resources}
    labels = slot_labels(slots, business, by_id, multi=len({s.resource_id for s in slots}) > 1)
    if slots:
        await save_offer(
            session,
            business,
            contact,
            slots,
            labels,
            purpose=purpose,
            schedule_id=schedule.id if schedule is not None else None,
            move_appointment_id=move_appointment.id if move_appointment is not None else None,
            rebooked_from_id=rebooked_from.id if rebooked_from is not None else None,
            duration_minutes=duration,
        )
    return slots, labels


def _in_part_of_day(slot: Slot, business: Business, part: str) -> bool:
    hour = clock.to_local(slot.start, business.timezone).hour
    part = part.lower()
    if part == "morning":
        return hour < 12
    if part == "afternoon":
        return 12 <= hour < 17
    if part == "evening":
        return hour >= 17
    return True


async def staff_to_alert(session: AsyncSession, business: Business) -> list[Staff]:
    """Front desk / owners who get alerts and the end-of-day list."""
    rows = (
        (
            await session.execute(
                select(Staff)
                .where(Staff.business_id == business.id, Staff.is_active.is_(True))
                .order_by(Staff.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    chosen = [s for s in rows if s.receives_eod_list]
    if not chosen:
        chosen = [s for s in rows if s.role is not None and s.role.name in ("front_desk", "owner")]
    return chosen


async def alert_staff(session: AsyncSession, business: Business, text: str) -> int:
    count = 0
    for member in await staff_to_alert(session, business):
        await send_to_staff(session, business, member, Outgoing(text=text))
        count += 1
    return count


async def flag_to_staff(
    session: AsyncSession, business: Business, contact: Contact, reason: str, schedule: Schedule | None = None
) -> None:
    contact.needs_staff = True
    if schedule is not None:
        schedule.needs_staff = True
    who = contact.name or contact.phone or f"contact #{contact.id}"
    phone = contact.phone or (contact.guardian.phone if contact.guardian else "") or ""
    await alert_staff(session, business, f"Please call {who} {phone}: {reason}".strip())


# --------------------------------------------------------------------------------------
# Return-visit loop
# --------------------------------------------------------------------------------------


async def nudge_schedule(session: AsyncSession, business: Business, schedule: Schedule) -> bool:
    """Send the 'session due' (or 'recall') message with free slots. Returns True if sent."""
    if schedule.status != ScheduleStatus.ACTIVE or schedule.next_due_date is None:
        return False
    if await sched_engine.active_appointment_for_schedule(session, schedule.id) is not None:
        return False
    contact = schedule.contact
    template = schedule.template
    today = clock.local_today(business.timezone)
    date_from = max(today, schedule.next_due_date)
    slots, labels = await build_offer(
        session, business, contact, date_from=date_from, purpose="nudge", schedule=schedule
    )
    schedule.nudge_count += 1
    schedule.last_nudged_at = clock.now()
    if not slots:
        await flag_to_staff(
            session,
            business,
            contact,
            f"{template.name} is due but no free slots were found in the next 2 weeks.",
            schedule,
        )
        return False
    label = plan_label(template, schedule.sessions_done + 1)
    resources = await resources_for(session, business, template, schedule.resource_id)
    resource_name = resources[0].name if len(resources) == 1 else business.name
    name = greeting_name(contact)
    if template.is_ongoing:
        text = (
            f"Hi {name}, it's time for {for_whom(contact, template.name)} at {business.name}. Free slots:\n"
            f"{numbered(labels)}\n\nReply 1, 2 or 3 and I'll book it, or tell me a time that suits you."
        )
        out = Outgoing(
            text=text,
            template_key="recall",
            template_values={"name": name, "service": template.name, "slots": slots_param(labels)},
        )
    else:
        text = (
            f"Hi {name}, {for_whom(contact, label)} with {resource_name} is due. Free slots:\n"
            f"{numbered(labels)}\n\nReply 1, 2 or 3 to book, or tell me a time that suits you."
        )
        out = Outgoing(
            text=text,
            template_key="session_due",
            template_values={
                "name": name,
                "session": label,
                "resource": resource_name,
                "slots": slots_param(labels),
            },
        )
    sent = await send_to_contact(session, business, contact, out, handled_by="system", proactive=True)
    return sent is not None and sent.status in ("ok", "dry_run")


async def send_reminder(session: AsyncSession, business: Business, appt: Appointment) -> bool:
    """Day-before reminder with confirm / reschedule options."""
    contact = appt.contact
    service = appt.service or get_pack(business.type).word("visit").capitalize()
    when = clock.fmt_time(appt.start_at, business.timezone)
    day = clock.fmt_date(appt.start_at, business.timezone)
    text = (
        f"Reminder: {service} with {appt.resource.name} tomorrow ({day}) at {when}.\n"
        "Reply 1 to confirm or 2 to reschedule."
    )
    out = Outgoing(
        text=text,
        template_key="day_before_reminder",
        template_values={"service": service, "resource": appt.resource.name, "time": when},
    )
    appt.reminder_sent_at = clock.now()
    await set_state(
        session,
        business_id=business.id,
        contact_id=contact.id,
        key="reminder",
        data={"appointment_id": appt.id},
        ttl=max(appt.start_at - clock.now(), dt.timedelta(hours=1)),
    )
    sent = await send_to_contact(session, business, contact, out, handled_by="system", proactive=True)
    return sent is not None and sent.status in ("ok", "dry_run")


async def has_rebooked(session: AsyncSession, appt: Appointment) -> bool:
    """Did the contact book anything after this appointment?"""
    stmt = select(func.count(Appointment.id)).where(
        Appointment.contact_id == appt.contact_id,
        Appointment.id != appt.id,
        Appointment.status.in_(AppointmentStatus.ACTIVE + (AppointmentStatus.DONE,)),
        Appointment.created_at > appt.start_at,
    )
    if appt.schedule_id is not None:
        stmt = stmt.where(Appointment.schedule_id == appt.schedule_id)
    return ((await session.execute(stmt)).scalar_one() or 0) > 0


async def followup_missed(session: AsyncSession, business: Business, appt: Appointment) -> str:
    """Missed-visit follow-up. Returns 'sent', 'skipped' or 'flagged'."""
    if appt.status != AppointmentStatus.MISSED or await has_rebooked(session, appt):
        return "skipped"
    max_followups = 2
    contact = appt.contact
    schedule = await session.get(Schedule, appt.schedule_id) if appt.schedule_id else None
    if appt.followup_count >= max_followups:
        when = clock.fmt_slot(appt.start_at, business.timezone)
        await flag_to_staff(
            session,
            business,
            contact,
            f"missed the {when} visit and hasn't rebooked after 2 follow-ups.",
            schedule,
        )
        appt.followup_count += 1
        return "flagged"
    if schedule is not None and schedule.status != ScheduleStatus.ACTIVE:
        return "skipped"
    today = clock.local_today(business.timezone)
    slots, labels = await build_offer(
        session,
        business,
        contact,
        date_from=today,
        purpose="followup",
        schedule=schedule,
        resource_ids=None if schedule else [appt.resource_id],
        rebooked_from=appt,
    )
    appt.followup_count += 1
    if not slots:
        await flag_to_staff(
            session, business, contact, "missed a visit and no free slots were found.", schedule
        )
        return "flagged"
    name = greeting_name(contact)
    text = (
        f"Hi {name}, we missed you at your visit on {clock.fmt_slot(appt.start_at, business.timezone)}. "
        f"Next free slots:\n{numbered(labels)}\n\nReply 1, 2 or 3 to book."
    )
    out = Outgoing(
        text=text,
        template_key="missed_followup",
        template_values={"name": name, "slots": slots_param(labels)},
    )
    await send_to_contact(session, business, contact, out, handled_by="system", proactive=True)
    return "sent"


async def offer_rebook_after_cancel(
    session: AsyncSession, business: Business, appt: Appointment, *, date_from: dt.date | None = None
) -> bool:
    """The clinic cancelled (doctor unavailable): offer 3 new slots and rebook on reply."""
    contact = appt.contact
    schedule = await session.get(Schedule, appt.schedule_id) if appt.schedule_id else None
    today = clock.local_today(business.timezone)
    start_from = max(date_from or today, today)
    old_label = clock.fmt_slot(appt.start_at, business.timezone)
    slots, labels = await build_offer(
        session,
        business,
        contact,
        date_from=start_from,
        purpose="rebook",
        schedule=schedule,
        resource_ids=[appt.resource_id],
        rebooked_from=appt,
    )
    if not slots:
        slots, labels = await build_offer(
            session,
            business,
            contact,
            date_from=start_from,
            purpose="rebook",
            schedule=schedule,
            rebooked_from=appt,
        )
    if not slots:
        await flag_to_staff(
            session,
            business,
            contact,
            f"{appt.resource.name} cancelled the {old_label} visit and no new slots were found.",
            schedule,
        )
        return False
    text = (
        f"Sorry, {appt.resource.name} can't make your {old_label} visit. New slots:\n{numbered(labels)}\n\n"
        "Reply 1, 2 or 3 to rebook."
    )
    out = Outgoing(
        text=text,
        template_key="doctor_unavailable",
        template_values={"resource": appt.resource.name, "time": old_label, "slots": slots_param(labels)},
    )
    await send_to_contact(session, business, contact, out, handled_by="system", proactive=True)
    return True


async def book_from_offer(
    session: AsyncSession, business: Business, contact: Contact, choice: int
) -> tuple[Appointment | None, str]:
    """Book option `choice` (1-based) from the contact's current offer. Returns (appointment, reply)."""
    state = await get_state(session, key="offer", contact_id=contact.id)
    if state is None:
        return (
            None,
            "I don't have any slots saved for you right now. Tell me a day that suits you and I'll check.",
        )
    keys: list[str] = state.data.get("slots", [])
    if not 1 <= choice <= len(keys):
        return None, f"Please reply with a number from 1 to {len(keys)}."
    resource_id, start = Slot.parse_key(keys[choice - 1])
    data: dict[str, Any] = state.data
    rebooked_from = (
        await session.get(Appointment, data["rebooked_from_id"]) if data.get("rebooked_from_id") else None
    )
    move = (
        await session.get(Appointment, data["move_appointment_id"])
        if data.get("move_appointment_id")
        else None
    )
    if move is not None and move.status in AppointmentStatus.ACTIVE:
        rebooked_from = move
    schedule_id = data.get("schedule_id")
    if schedule_id is not None:
        schedule = await session.get(Schedule, schedule_id)
        if schedule is None or schedule.status != ScheduleStatus.ACTIVE:
            schedule_id = None
    try:
        appt = await appt_engine.book(
            session,
            business,
            contact,
            resource_id,
            start,
            duration_minutes=data.get("duration_minutes"),
            schedule_id=schedule_id,
            source="whatsapp",
            rebooked_from=rebooked_from,
        )
    except SlotUnavailable:
        schedule = await session.get(Schedule, schedule_id) if schedule_id else None
        slots, labels = await build_offer(
            session,
            business,
            contact,
            date_from=clock.local_today(business.timezone),
            purpose=data.get("purpose", "book"),
            schedule=schedule,
            move_appointment=move if move is not None and move.status in AppointmentStatus.ACTIVE else None,
            rebooked_from=rebooked_from,
        )
        if not slots:
            await flag_to_staff(session, business, contact, "wanted to book but no free slots were found.")
            return (
                None,
                "Sorry, that slot was just taken and I can't find another free one. Our team will contact you.",
            )
        return (
            None,
            f"Sorry, that slot was just taken. Here are the next free ones:\n{numbered(labels)}\n\nReply 1, 2 or 3.",
        )
    except BookingError as exc:
        return None, str(exc)
    await clear_state(session, key="offer", contact_id=contact.id)
    return appt, booking_confirmation_text(business, appt)


def booking_confirmation_text(business: Business, appt: Appointment) -> str:
    service = appt.service or get_pack(business.type).word("visit").capitalize()
    return (
        f"Booked: {service} with {appt.resource.name}, {clock.fmt_date(appt.start_at, business.timezone)} at "
        f"{clock.fmt_time(appt.start_at, business.timezone)}. Reply here if you need to change it."
    )


async def running_late(
    session: AsyncSession, business: Business, resource: Resource, minutes: int
) -> list[Appointment]:
    """Tell the next patients that the doctor is running late."""
    window = dt.timedelta(hours=int(get_setting(business.settings, "late_notify_window_hours")))
    now = clock.now()
    _, day_end = clock.day_bounds(clock.local_today(business.timezone), business.timezone)
    rows = (
        (
            await session.execute(
                select(Appointment)
                .where(
                    Appointment.resource_id == resource.id,
                    Appointment.status.in_(AppointmentStatus.ACTIVE),
                    Appointment.start_at >= now - dt.timedelta(minutes=minutes),
                    Appointment.start_at < min(now + window, day_end),
                )
                .order_by(Appointment.start_at)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    for appt in rows:
        when = clock.fmt_time(appt.start_at, business.timezone)
        out = Outgoing(
            text=(
                f"{resource.name} is running about {minutes} minutes late today, so your {when} visit may start a "
                "little later. Thank you for your patience."
            ),
            template_key="running_late",
            template_values={"resource": resource.name, "minutes": str(minutes), "time": when},
        )
        await send_to_contact(session, business, appt.contact, out, handled_by="system", proactive=True)
    return list(rows)


async def find_role(session: AsyncSession, business_id: int, name: str) -> Role | None:
    return (
        await session.execute(select(Role).where(Role.business_id == business_id, Role.name == name))
    ).scalar_one_or_none()
