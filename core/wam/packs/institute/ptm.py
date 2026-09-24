"""Parent-teacher meetings: parents of a batch book short slots with its teachers."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.engine.slots import Slot, find_free_slots
from wam.flows import numbered, save_offer
from wam.models import (
    Appointment,
    AppointmentStatus,
    Availability,
    Broadcast,
    Business,
    Contact,
    Group,
    PtmEvent,
    Resource,
)
from wam.packs.institute import broadcasts
from wam.packs.institute.timetable import batches_for

OFFER_COUNT = 3


class PtmError(Exception):
    pass


def _fmt(t: dt.time) -> str:
    return dt.datetime.combine(dt.date(2000, 1, 1), t).strftime("%I:%M %p").lstrip("0")


def describe(ptm: PtmEvent) -> str:
    return f"{ptm.title} on {clock.fmt_date(ptm.date)}, {_fmt(ptm.start_time)}–{_fmt(ptm.end_time)}"


async def create(
    session: AsyncSession,
    business: Business,
    group: Group,
    date: dt.date,
    start: dt.time,
    end: dt.time,
    resource_ids: list[int],
    *,
    slot_minutes: int = 10,
    title: str = "Parent-teacher meeting",
) -> PtmEvent:
    if date < clock.local_today(business.timezone):
        raise PtmError("That date has passed.")
    if end <= start:
        raise PtmError("The end time must be after the start time.")
    if not 5 <= slot_minutes <= 60:
        raise PtmError("Slots must be 5 to 60 minutes long.")
    if not resource_ids:
        raise PtmError("Choose at least one teacher.")
    resources = (await session.execute(select(Resource).where(Resource.id.in_(resource_ids)))).scalars().all()
    if len(resources) != len(set(resource_ids)) or any(r.business_id != business.id for r in resources):
        raise PtmError("Unknown teacher.")
    ptm = PtmEvent(
        business_id=business.id,
        group_id=group.id,
        title=title.strip()[:120] or "Parent-teacher meeting",
        date=date,
        start_time=start,
        end_time=end,
        slot_minutes=slot_minutes,
        resource_ids=sorted(set(resource_ids)),
    )
    session.add(ptm)
    start_at = clock.combine(date, start, business.timezone)
    end_at = clock.combine(date, end, business.timezone)
    for r in resources:
        # Extra one-off hours so the slot engine offers the meeting time even outside normal hours.
        session.add(
            Availability(
                resource_id=r.id, kind="extra", start_at=start_at, end_at=end_at, reason=f"PTM {group.name}"
            )
        )
    await session.flush()
    return ptm


async def invite(
    session: AsyncSession, business: Business, ptm: PtmEvent, *, admin_user_id: int | None = None
) -> Broadcast:
    """A draft announcement to the batch's parents: 'Reply PTM to book'. Send it with broadcasts.start."""
    group = await session.get(Group, ptm.group_id)
    assert group is not None
    message = f"{describe(ptm)}. Reply PTM to book a {ptm.slot_minutes}-minute slot with the teachers"
    broadcast = await broadcasts.create_broadcast(
        session, business, group, message, "parents", admin_user_id=admin_user_id
    )
    ptm.broadcast_id = broadcast.id
    return broadcast


async def upcoming_for(session: AsyncSession, business: Business, contact: Contact) -> list[PtmEvent]:
    groups = await batches_for(session, contact)
    if not groups:
        return []
    today = clock.local_today(business.timezone)
    return list(
        (
            await session.execute(
                select(PtmEvent)
                .where(PtmEvent.group_id.in_([g.id for g in groups]), PtmEvent.date >= today)
                .order_by(PtmEvent.date, PtmEvent.start_time)
            )
        )
        .scalars()
        .all()
    )


async def free_slots(session: AsyncSession, business: Business, ptm: PtmEvent) -> list[Slot]:
    window_start = clock.combine(ptm.date, ptm.start_time, business.timezone)
    window_end = clock.combine(ptm.date, ptm.end_time, business.timezone)
    slots: list[Slot] = []
    for rid in ptm.resource_ids:
        resource = await session.get(Resource, rid)
        if resource is None or not resource.is_active:
            continue
        found = await find_free_slots(
            session,
            business,
            resource,
            ptm.date,
            ptm.date,
            duration_minutes=ptm.slot_minutes,
            step_minutes=ptm.slot_minutes,
            limit=500,
        )
        slots.extend(s for s in found if s.start >= window_start and s.end <= window_end)
    slots.sort(key=lambda s: (s.start, s.resource_id))
    return slots


async def offer(session: AsyncSession, business: Business, contact: Contact) -> str | None:
    """Reply to 'PTM': offer the next free slots. None if there is no upcoming meeting for this person."""
    events = await upcoming_for(session, business, contact)
    if not events:
        return None
    ptm = events[0]
    start_at = clock.combine(ptm.date, ptm.start_time, business.timezone)
    end_at = clock.combine(ptm.date, ptm.end_time, business.timezone)
    booked = (
        await session.execute(
            select(Appointment).where(
                Appointment.contact_id == contact.id,
                Appointment.status.in_(AppointmentStatus.ACTIVE),
                Appointment.start_at >= start_at,
                Appointment.start_at < end_at,
            )
        )
    ).scalar_one_or_none()
    if booked is not None:
        return (
            f"You're already booked for the {ptm.title.lower()} at {clock.fmt_time(booked.start_at, business.timezone)} "
            f"on {clock.fmt_date(ptm.date)} with {booked.resource.name}. Reply here if you need to change it."
        )
    slots = await free_slots(session, business, ptm)
    if not slots:
        return f"Sorry, all slots for the {describe(ptm)} are taken. Our office will contact you."
    chosen: list[Slot] = []
    for slot in slots:  # earliest times, one per start time, spread across teachers
        if all(slot.start != c.start for c in chosen):
            chosen.append(slot)
        if len(chosen) == OFFER_COUNT:
            break
    names = {rid: (await session.get(Resource, rid)) for rid in {s.resource_id for s in chosen}}
    labels = [
        f"{clock.fmt_time(s.start, business.timezone)} with {names[s.resource_id].name}"  # type: ignore[union-attr]
        for s in chosen
    ]
    await save_offer(
        session,
        business,
        contact,
        chosen,
        labels,
        purpose="ptm",
        duration_minutes=ptm.slot_minutes,
        service=ptm.title,
        step_minutes=ptm.slot_minutes,
    )
    return f"{describe(ptm)}. Free slots:\n{numbered(labels)}\n\nReply 1, 2 or 3 to book."
