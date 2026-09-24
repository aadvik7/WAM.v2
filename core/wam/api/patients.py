"""Patients (contacts), their plans (schedules), appointments and today's list."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError

from wam import clock
from wam.api.deps import BusinessDep, SessionDep, UserDep, bad_request, not_found
from wam.api.schemas import (
    AppointmentIn,
    CancelIn,
    ContactIn,
    ContactPatch,
    EnrolIn,
    MarkIn,
    SchedulePatch,
    appointment_out,
    contact_out,
    message_out,
    schedule_out,
)
from wam.audit import audit
from wam.engine import appointments as appt_engine
from wam.engine import schedules as sched_engine
from wam.engine.appointments import BookingError
from wam.engine.schedules import ScheduleError
from wam.flows import booking_confirmation_text, nudge_schedule, offer_rebook_after_cancel
from wam.jobs.queue import schedule_job
from wam.messaging import Outgoing, send_to_contact
from wam.models import (
    Appointment,
    AppointmentStatus,
    Business,
    Contact,
    MessageLog,
    Resource,
    Schedule,
    ScheduleStatus,
    ScheduleTemplate,
)
from wam.phone import normalize_phone
from wam.settings_defaults import get_setting
from wam.windows import in_send_window

router = APIRouter(prefix="/api/businesses/{business_id}", tags=["patients"])


async def _contact(session: SessionDep, business: Business, contact_id: int) -> Contact:
    c = await session.get(Contact, contact_id)
    if c is None or c.business_id != business.id:
        raise not_found("Patient not found")
    return c


# --------------------------------------------------------------------------------------
# Contacts
# --------------------------------------------------------------------------------------


@router.get("/contacts")
async def list_contacts(
    business: BusinessDep,
    session: SessionDep,
    q: str | None = None,
    needs_staff: bool | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, Any]:
    stmt = select(Contact).where(Contact.business_id == business.id)
    if q:
        digits = "".join(ch for ch in q if ch.isdigit())
        conds = [Contact.name.ilike(f"%{q}%")]
        if len(digits) >= 3:
            conds.append(Contact.phone.like(f"%{digits}%"))
        stmt = stmt.where(or_(*conds))
    if needs_staff is not None:
        stmt = stmt.where(Contact.needs_staff.is_(needs_staff))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                stmt.order_by(Contact.id.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    ids = [c.id for c in rows]
    plan_counts: dict[int, int] = {}
    if ids:
        for cid, n in (
            await session.execute(
                select(Schedule.contact_id, func.count(Schedule.id))
                .where(Schedule.contact_id.in_(ids), Schedule.status == ScheduleStatus.ACTIVE)
                .group_by(Schedule.contact_id)
            )
        ).all():
            plan_counts[cid] = n
    tz = business.timezone
    return {
        "total": total,
        "page": page,
        "items": [{**contact_out(c, tz), "active_plans": plan_counts.get(c.id, 0)} for c in rows],
    }


@router.post("/contacts", status_code=201)
async def create_contact(
    body: ContactIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    phone = normalize_phone(body.phone) if body.phone else None
    if body.phone and phone is None:
        raise bad_request("Invalid phone number")
    guardian: Contact | None = None
    if body.guardian_phone:
        gphone = normalize_phone(body.guardian_phone)
        if gphone is None:
            raise bad_request("Invalid guardian phone number")
        guardian = (
            await session.execute(
                select(Contact).where(
                    Contact.business_id == business.id, Contact.phone == gphone, Contact.guardian_id.is_(None)
                )
            )
        ).scalar_one_or_none()
        if guardian is None:
            guardian = Contact(business_id=business.id, phone=gphone, name=body.guardian_name)
            session.add(guardian)
            await session.flush()
    if phone is None and guardian is None:
        raise bad_request("A phone number (or a guardian's phone) is needed to reach the patient on WhatsApp")
    contact = Contact(
        business_id=business.id,
        name=body.name,
        phone=None if guardian is not None else phone,
        guardian_id=guardian.id if guardian else None,
        date_of_birth=body.date_of_birth,
        language=body.language,
        notes=body.notes,
    )
    session.add(contact)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A patient with that phone already exists") from exc
    await session.refresh(contact, ["guardian"])
    await audit(
        session,
        business_id=business.id,
        action="contact_created",
        admin_user_id=user.id,
        details={"contact_id": contact.id},
    )
    return contact_out(contact, business.timezone)


@router.get("/contacts/{contact_id}")
async def get_contact(contact_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    c = await _contact(session, business, contact_id)
    tz = business.timezone
    schedules = (
        (
            await session.execute(
                select(Schedule).where(Schedule.contact_id == c.id).order_by(Schedule.id.desc())
            )
        )
        .scalars()
        .unique()
        .all()
    )
    appts = (
        (
            await session.execute(
                select(Appointment)
                .where(Appointment.contact_id == c.id)
                .order_by(Appointment.start_at.desc())
                .limit(100)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    msg_ids = [c.id] + ([c.guardian_id] if c.guardian_id else [])
    messages = (
        (
            await session.execute(
                select(MessageLog)
                .where(MessageLog.contact_id.in_(msg_ids))
                .order_by(MessageLog.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    children = (
        (await session.execute(select(Contact).where(Contact.guardian_id == c.id))).scalars().unique().all()
    )
    return {
        "contact": contact_out(c, tz),
        "children": [contact_out(k, tz) for k in children],
        "schedules": [schedule_out(s, tz) for s in schedules],
        "appointments": [appointment_out(a, tz) for a in appts],
        "messages": [message_out(m, tz) for m in reversed(messages)],
    }


@router.patch("/contacts/{contact_id}")
async def update_contact(
    contact_id: int, body: ContactPatch, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    c = await _contact(session, business, contact_id)
    data = body.model_dump(exclude_unset=True)
    if "phone" in data and data["phone"]:
        phone = normalize_phone(data["phone"])
        if phone is None:
            raise bad_request("Invalid phone number")
        data["phone"] = phone
    for key, value in data.items():
        setattr(c, key, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A patient with that phone already exists") from exc
    return contact_out(c, business.timezone)


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: int, business: BusinessDep, session: SessionDep, user: UserDep) -> None:
    """Erase a patient and their data (DPDP right to erasure)."""
    c = await _contact(session, business, contact_id)
    await session.execute(
        MessageLog.__table__.delete().where(MessageLog.contact_id == c.id)  # type: ignore[attr-defined]
    )
    await session.delete(c)
    await audit(
        session,
        business_id=business.id,
        action="contact_erased",
        admin_user_id=user.id,
        details={"contact_id": contact_id},
    )


# --------------------------------------------------------------------------------------
# Schedules (plans)
# --------------------------------------------------------------------------------------


@router.get("/schedules")
async def list_schedules(
    business: BusinessDep,
    session: SessionDep,
    status: str | None = "active",
    overdue: bool = False,
    needs_staff: bool | None = None,
) -> list[dict[str, Any]]:
    stmt = select(Schedule).where(Schedule.business_id == business.id)
    if status:
        stmt = stmt.where(Schedule.status == status)
    if overdue:
        stmt = stmt.where(Schedule.next_due_date < clock.local_today(business.timezone))
    if needs_staff is not None:
        stmt = stmt.where(Schedule.needs_staff.is_(needs_staff))
    rows = (
        (await session.execute(stmt.order_by(Schedule.next_due_date.nulls_last(), Schedule.id).limit(500)))
        .scalars()
        .unique()
        .all()
    )
    return [schedule_out(s, business.timezone) for s in rows]


@router.post("/contacts/{contact_id}/schedules", status_code=201)
async def enrol_contact(
    contact_id: int, body: EnrolIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    c = await _contact(session, business, contact_id)
    template = await session.get(ScheduleTemplate, body.template_id)
    if template is None or template.business_id != business.id:
        raise bad_request("Unknown plan")
    if body.resource_id is not None:
        r = await session.get(Resource, body.resource_id)
        if r is None or r.business_id != business.id:
            raise bad_request("Unknown doctor")
    anchor = body.anchor_date
    if template.offsets_days and anchor is None:
        anchor = c.date_of_birth
        if anchor is None:
            raise bad_request(
                "This plan is based on date of birth; set the patient's date of birth or an anchor date"
            )
    try:
        schedule = await sched_engine.enrol(
            session,
            business,
            c,
            template,
            resource_id=body.resource_id,
            anchor_date=anchor,
            sessions_done=body.sessions_done,
            first_due=body.first_due,
            notes=body.notes,
        )
    except ScheduleError as exc:
        raise bad_request(str(exc)) from exc
    nudged = False
    if (
        body.nudge_now
        and in_send_window(business)
        and schedule.next_due_date
        and schedule.next_due_date <= clock.local_today(business.timezone)
    ):
        nudged = await nudge_schedule(session, business, schedule)
    await audit(
        session,
        business_id=business.id,
        action="enrol",
        admin_user_id=user.id,
        details={"schedule_id": schedule.id, "contact_id": c.id, "template": template.name},
    )
    return {**schedule_out(schedule, business.timezone), "nudged": nudged}


@router.patch("/schedules/{schedule_id}")
async def update_schedule(
    schedule_id: int, body: SchedulePatch, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    s = await session.get(Schedule, schedule_id)
    if s is None or s.business_id != business.id:
        raise not_found()
    data = body.model_dump(exclude_unset=True)
    if "next_due_date" in data and data["next_due_date"] is not None:
        await sched_engine.set_next_due(session, s, data.pop("next_due_date"))
    if "resource_id" in data and data["resource_id"] is not None:
        r = await session.get(Resource, data["resource_id"])
        if r is None or r.business_id != business.id:
            raise bad_request("Unknown doctor")
    for key, value in data.items():
        setattr(s, key, value)
    if data.get("status") == ScheduleStatus.COMPLETED and s.completed_at is None:
        s.completed_at = clock.now()
    if data.get("status") in (ScheduleStatus.ACTIVE, ScheduleStatus.PAUSED):
        s.needs_staff = False if data.get("status") == ScheduleStatus.ACTIVE else s.needs_staff
    await audit(
        session,
        business_id=business.id,
        action="schedule_updated",
        admin_user_id=user.id,
        details={"schedule_id": s.id, "fields": sorted(body.model_dump(exclude_unset=True))},
    )
    return schedule_out(s, business.timezone)


@router.post("/schedules/{schedule_id}/nudge")
async def nudge_now(schedule_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    s = await session.get(Schedule, schedule_id)
    if s is None or s.business_id != business.id:
        raise not_found()
    if s.next_due_date is None:
        raise bad_request("This plan has no next visit due")
    sent = await nudge_schedule(session, business, s)
    return {"sent": sent}


# --------------------------------------------------------------------------------------
# Appointments
# --------------------------------------------------------------------------------------


@router.get("/appointments")
async def list_appointments(
    business: BusinessDep,
    session: SessionDep,
    date: dt.date | None = None,
    resource_id: int | None = None,
) -> list[dict[str, Any]]:
    day = date or clock.local_today(business.timezone)
    appts = await appt_engine.day_list(session, business, day, resource_id)
    return [appointment_out(a, business.timezone) for a in appts]


@router.post("/appointments", status_code=201)
async def create_appointment(
    body: AppointmentIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    c = await _contact(session, business, body.contact_id)
    start = body.start_at
    if start.tzinfo is None:
        start = start.replace(tzinfo=ZoneInfo(business.timezone))
    start = start.astimezone(dt.UTC)
    moving: Appointment | None = None
    if body.move_appointment_id is not None:
        moving = await _appointment(session, business, body.move_appointment_id)
        if moving.status not in AppointmentStatus.ACTIVE or moving.contact_id != c.id:
            raise bad_request("Only an active appointment of this patient can be moved")
    try:
        appt = await appt_engine.book(
            session,
            business,
            c,
            body.resource_id,
            start,
            duration_minutes=body.duration_minutes,
            schedule_id=body.schedule_id,
            source="admin",
            service=body.service,
            enforce_availability=body.enforce_availability,
            notes=body.notes,
            rebooked_from=moving,
        )
    except BookingError as exc:
        raise bad_request(str(exc)) from exc
    if body.notify:
        tz = business.timezone
        await send_to_contact(
            session,
            business,
            c,
            Outgoing(
                text=booking_confirmation_text(business, appt),
                template_key="booking_confirmation",
                template_values={
                    "service": appt.service or "Visit",
                    "date": clock.fmt_date(appt.start_at, tz),
                    "time": clock.fmt_time(appt.start_at, tz),
                },
            ),
            handled_by="staff",
            proactive=True,
        )
    await audit(
        session,
        business_id=business.id,
        action="appointment_created",
        admin_user_id=user.id,
        details={"appointment_id": appt.id},
    )
    return appointment_out(appt, business.timezone)


async def _appointment(session: SessionDep, business: Business, appointment_id: int) -> Appointment:
    a = await session.get(Appointment, appointment_id)
    if a is None or a.business_id != business.id:
        raise not_found("Appointment not found")
    return a


@router.post("/appointments/{appointment_id}/mark")
async def mark_appointment(
    appointment_id: int, body: MarkIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    a = await _appointment(session, business, appointment_id)
    if a.start_at > clock.now() + dt.timedelta(minutes=5):
        raise bad_request("You can only mark attendance once the visit time has passed")
    try:
        await appt_engine.mark(session, business, a, body.status)
    except BookingError as exc:
        raise bad_request(str(exc)) from exc
    if body.status == AppointmentStatus.MISSED:
        hours = int(get_setting(business.settings, "followup_after_hours"))
        run_at = max(a.start_at + dt.timedelta(hours=hours), clock.now() + dt.timedelta(minutes=30))
        await schedule_job(
            session,
            business.id,
            "missed_followup",
            run_at,
            {"appointment_id": a.id},
            dedupe_key=f"missed_followup:{a.id}:1",
        )
    await audit(
        session,
        business_id=business.id,
        action="attendance",
        admin_user_id=user.id,
        details={"appointment_id": a.id, "status": body.status},
    )
    return appointment_out(a, business.timezone)


@router.post("/appointments/{appointment_id}/confirm")
async def confirm_appointment(
    appointment_id: int, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    a = await _appointment(session, business, appointment_id)
    await appt_engine.confirm(session, a)
    return appointment_out(a, business.timezone)


@router.post("/appointments/{appointment_id}/cancel")
async def cancel_appointment(
    appointment_id: int, body: CancelIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    a = await _appointment(session, business, appointment_id)
    try:
        await appt_engine.cancel(session, a, body.reason or f"cancelled in admin by {user.email}")
    except BookingError as exc:
        raise bad_request(str(exc)) from exc
    offered = False
    if body.offer_rebook and a.start_at > clock.now():
        offered = await offer_rebook_after_cancel(session, business, a)
    await audit(
        session,
        business_id=business.id,
        action="cancel_appointment",
        admin_user_id=user.id,
        details={"appointment_id": a.id, "offered": offered},
    )
    return {**appointment_out(a, business.timezone), "offered_new_slots": offered}


# --------------------------------------------------------------------------------------
# Today
# --------------------------------------------------------------------------------------


@router.get("/today")
async def today(business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    tz = business.timezone
    day = clock.local_today(tz)
    appts = await appt_engine.day_list(session, business, day)
    counts: dict[str, int] = {}
    for a in appts:
        counts[a.status] = counts.get(a.status, 0) + 1
    waiting = (
        (
            await session.execute(
                select(Contact)
                .where(Contact.business_id == business.id, Contact.needs_staff.is_(True))
                .limit(50)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    due = (
        (
            await session.execute(
                select(Schedule)
                .where(
                    Schedule.business_id == business.id,
                    Schedule.status == ScheduleStatus.ACTIVE,
                    Schedule.next_due_date <= day,
                )
                .order_by(Schedule.next_due_date)
                .limit(100)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    due_unbooked = []
    for s in due:
        if await sched_engine.active_appointment_for_schedule(session, s.id) is None:
            due_unbooked.append(schedule_out(s, tz))
    return {
        "date": day.isoformat(),
        "now": clock.local_now(tz).isoformat(),
        "appointments": [appointment_out(a, tz) for a in appts],
        "counts": counts,
        "needs_staff": [contact_out(c, tz) for c in waiting],
        "due_unbooked": due_unbooked,
    }
