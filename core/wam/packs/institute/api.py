"""Admin API for the institute pack: batches & students, subjects, doubts, uploads, timetable,
announcements and parent-teacher meetings."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from wam import clock
from wam.api.deps import BusinessDep, SessionDep, UserDep, bad_request, not_found
from wam.audit import audit
from wam.models import (
    Appointment,
    AppointmentStatus,
    Availability,
    Broadcast,
    BroadcastRecipient,
    Business,
    Contact,
    ContactLink,
    Doubt,
    Group,
    GroupMember,
    GroupStaff,
    Import,
    PtmEvent,
    Staff,
    Subject,
    TimetableEntry,
)
from wam.packs.institute import batches as batch_mod
from wam.packs.institute import broadcasts, imports, ptm
from wam.packs.institute.batches import StudentError, StudentInput
from wam.people import link_parent
from wam.phone import normalize_phone

router = APIRouter(prefix="/api/businesses/{business_id}/institute", tags=["institute"])
MAX_UPLOAD_BYTES = 5 * 1024 * 1024


# --------------------------------------------------------------------------------------
# Bodies
# --------------------------------------------------------------------------------------


class BatchIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeachersIn(BaseModel):
    staff_ids: list[int] = Field(default_factory=list)


class StudentIn(BaseModel):
    name: str | None = None
    roll: str | None = Field(default=None, max_length=50)
    phone: str | None = None
    parent_phones: list[str] = Field(default_factory=list, max_length=2)
    parent_names: list[str | None] = Field(default_factory=list, max_length=2)


class StudentPatch(BaseModel):
    name: str | None = None
    roll: str | None = Field(default=None, max_length=50)


class ParentIn(BaseModel):
    phone: str
    name: str | None = None


class SubjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    aliases: list[str] = Field(default_factory=list)
    chatwoot_team_id: int | None = None


class BroadcastIn(BaseModel):
    group_id: int
    message: str = Field(min_length=1, max_length=broadcasts.MAX_MESSAGE)
    audience: Literal["everyone", "parents", "students"] = "everyone"


class PtmIn(BaseModel):
    group_id: int
    date: dt.date
    start: dt.time
    end: dt.time
    resource_ids: list[int] = Field(min_length=1)
    slot_minutes: int = Field(default=10, ge=5, le=60)
    title: str = "Parent-teacher meeting"
    invite: bool = True


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


async def _batch(session: SessionDep, business: Business, group_id: int) -> Group:
    group = await session.get(Group, group_id)
    if group is None or group.business_id != business.id or group.kind != batch_mod.BATCH:
        raise not_found("Batch not found")
    return group


async def _student(session: SessionDep, business: Business, contact_id: int) -> Contact:
    contact = await session.get(Contact, contact_id)
    if contact is None or contact.business_id != business.id:
        raise not_found("Student not found")
    return contact


# --------------------------------------------------------------------------------------
# Batches and students
# --------------------------------------------------------------------------------------


@router.get("/batches")
async def list_batches(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    groups = await batch_mod.list_batches(session, business.id)
    students = dict(
        (
            await session.execute(
                select(GroupMember.group_id, func.count(GroupMember.contact_id)).group_by(
                    GroupMember.group_id
                )
            )
        ).all()
    )
    teachers = dict(
        (
            await session.execute(
                select(GroupStaff.group_id, func.count(GroupStaff.staff_id)).group_by(GroupStaff.group_id)
            )
        ).all()
    )
    return [
        {"id": g.id, "name": g.name, "students": students.get(g.id, 0), "teachers": teachers.get(g.id, 0)}
        for g in groups
    ]


@router.post("/batches", status_code=201)
async def create_batch(body: BatchIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    existing = batch_mod.match_batch(body.name, await batch_mod.list_batches(session, business.id))
    if existing is not None and batch_mod._key(existing.name) == batch_mod._key(body.name):
        raise bad_request("A batch with that name exists")
    group = Group(business_id=business.id, name=body.name.strip(), kind=batch_mod.BATCH)
    session.add(group)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A group with that name exists") from exc
    return {"id": group.id, "name": group.name, "students": 0, "teachers": 0}


@router.patch("/batches/{group_id}")
async def rename_batch(
    group_id: int, body: BatchIn, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    group = await _batch(session, business, group_id)
    group.name = body.name.strip()
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A group with that name exists") from exc
    return {"id": group.id, "name": group.name}


@router.delete("/batches/{group_id}", status_code=204)
async def delete_batch(group_id: int, business: BusinessDep, session: SessionDep, user: UserDep) -> None:
    group = await _batch(session, business, group_id)
    events = (await session.execute(select(PtmEvent).where(PtmEvent.group_id == group.id))).scalars().all()
    for event in events:
        await _remove_ptm_hours(session, business, event)
    await session.delete(group)
    await audit(
        session,
        business_id=business.id,
        action="batch_deleted",
        admin_user_id=user.id,
        details={"batch": group.name},
    )


@router.get("/batches/{group_id}")
async def get_batch(group_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    group = await _batch(session, business, group_id)
    members = (
        (
            await session.execute(
                select(Contact)
                .join(GroupMember, GroupMember.contact_id == Contact.id)
                .where(GroupMember.group_id == group.id)
                .order_by(Contact.external_id.nulls_last(), Contact.name)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    teacher_ids = await batch_mod.batch_teacher_ids(session, group.id)
    teachers = (
        (await session.execute(select(Staff).where(Staff.id.in_(teacher_ids)))).scalars().unique().all()
        if teacher_ids
        else []
    )
    return {
        "id": group.id,
        "name": group.name,
        "students": [await batch_mod.student_summary(session, m) for m in members],
        "teachers": [{"id": t.id, "name": t.name, "phone": t.phone} for t in teachers],
    }


@router.put("/batches/{group_id}/teachers")
async def set_teachers(
    group_id: int, body: TeachersIn, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    group = await _batch(session, business, group_id)
    if body.staff_ids:
        found = (
            await session.execute(
                select(func.count(Staff.id)).where(
                    Staff.id.in_(body.staff_ids), Staff.business_id == business.id
                )
            )
        ).scalar_one()
        if found != len(set(body.staff_ids)):
            raise bad_request("Unknown staff member")
    await batch_mod.set_batch_teachers(session, group, body.staff_ids)
    return {"ok": True, "staff_ids": body.staff_ids}


@router.post("/batches/{group_id}/students", status_code=201)
async def add_student(
    group_id: int, body: StudentIn, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    group = await _batch(session, business, group_id)
    try:
        student, created, notes = await batch_mod.upsert_student(
            session,
            business,
            StudentInput(
                name=body.name,
                roll=body.roll,
                phone=body.phone,
                parent_phones=tuple(body.parent_phones),
                parent_names=tuple(body.parent_names),
            ),
        )
    except StudentError as exc:
        raise bad_request(str(exc)) from exc
    except IntegrityError as exc:
        raise bad_request("That roll number or phone belongs to someone else") from exc
    await batch_mod.add_to_batch(session, group, student)
    return {**await batch_mod.student_summary(session, student), "created": created, "notes": notes}


@router.delete("/batches/{group_id}/students/{contact_id}", status_code=204)
async def remove_student(group_id: int, contact_id: int, business: BusinessDep, session: SessionDep) -> None:
    group = await _batch(session, business, group_id)
    await batch_mod.remove_from_batch(session, group, contact_id)


@router.patch("/students/{contact_id}")
async def update_student(
    contact_id: int, body: StudentPatch, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    student = await _student(session, business, contact_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        student.name = data["name"] or None
    if "roll" in data:
        student.external_id = (data["roll"] or "").strip() or None
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("That roll number is already used") from exc
    return await batch_mod.student_summary(session, student)


@router.post("/students/{contact_id}/parents", status_code=201)
async def add_parent(
    contact_id: int, body: ParentIn, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    student = await _student(session, business, contact_id)
    phone = normalize_phone(body.phone)
    if phone is None:
        raise bad_request("Invalid phone number")
    if phone == student.phone:
        raise bad_request("That is the student's own number")
    parent = await batch_mod.contact_by_phone(session, business.id, phone)
    if parent is None:
        parent = Contact(business_id=business.id, phone=phone, name=body.name or None)
        session.add(parent)
        await session.flush()
    elif body.name and not parent.name:
        parent.name = body.name
    if not await link_parent(session, student, parent):
        raise bad_request("Already linked, or the student already has two parent numbers")
    return await batch_mod.student_summary(session, student)


@router.delete("/students/{contact_id}/parents/{parent_id}", status_code=204)
async def remove_parent(contact_id: int, parent_id: int, business: BusinessDep, session: SessionDep) -> None:
    student = await _student(session, business, contact_id)
    await batch_mod.unlink_parent(session, student, parent_id)


# --------------------------------------------------------------------------------------
# Subjects and doubts
# --------------------------------------------------------------------------------------


def _subject_out(s: Subject) -> dict[str, Any]:
    return {"id": s.id, "name": s.name, "aliases": s.aliases, "chatwoot_team_id": s.chatwoot_team_id}


@router.get("/subjects")
async def list_subjects(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Subject).where(Subject.business_id == business.id).order_by(Subject.name)
        )
    ).scalars()
    return [_subject_out(s) for s in rows]


@router.post("/subjects", status_code=201)
async def create_subject(body: SubjectIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    subject = Subject(
        business_id=business.id,
        name=body.name.strip(),
        aliases=[a.strip().lower() for a in body.aliases if a.strip()],
        chatwoot_team_id=body.chatwoot_team_id,
    )
    session.add(subject)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("That subject exists") from exc
    return _subject_out(subject)


@router.patch("/subjects/{subject_id}")
async def update_subject(
    subject_id: int, body: SubjectIn, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    subject = await session.get(Subject, subject_id)
    if subject is None or subject.business_id != business.id:
        raise not_found()
    subject.name = body.name.strip()
    subject.aliases = [a.strip().lower() for a in body.aliases if a.strip()]
    subject.chatwoot_team_id = body.chatwoot_team_id
    return _subject_out(subject)


@router.delete("/subjects/{subject_id}", status_code=204)
async def delete_subject(subject_id: int, business: BusinessDep, session: SessionDep) -> None:
    subject = await session.get(Subject, subject_id)
    if subject is None or subject.business_id != business.id:
        raise not_found()
    await session.delete(subject)


@router.get("/doubts")
async def list_doubts(
    business: BusinessDep, session: SessionDep, status: Literal["open", "closed", "all"] = "open"
) -> list[dict[str, Any]]:
    stmt = select(Doubt).where(Doubt.business_id == business.id)
    if status != "all":
        stmt = stmt.where(Doubt.status == status)
    rows = (await session.execute(stmt.order_by(Doubt.id.desc()).limit(300))).scalars().unique().all()
    groups = {g.id: g.name for g in await batch_mod.list_batches(session, business.id)}
    tz = business.timezone
    return [
        {
            "id": d.id,
            "contact_id": d.contact_id,
            "student": d.contact.name or d.contact.phone,
            "subject": d.subject.name if d.subject else None,
            "batch": groups.get(d.group_id or 0),
            "question": d.question,
            "status": d.status,
            "created_at": clock.to_local(d.created_at, tz).isoformat(),
            "closed_at": clock.to_local(d.closed_at, tz).isoformat() if d.closed_at else None,
        }
        for d in rows
    ]


@router.post("/doubts/{doubt_id}/close")
async def close_doubt(doubt_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    doubt = await session.get(Doubt, doubt_id)
    if doubt is None or doubt.business_id != business.id:
        raise not_found()
    doubt.status = "closed"
    doubt.closed_at = clock.now()
    contact = await session.get(Contact, doubt.contact_id)
    if contact is not None:
        still_open = (
            await session.execute(
                select(func.count(Doubt.id)).where(
                    Doubt.contact_id == contact.id, Doubt.status == "open", Doubt.id != doubt.id
                )
            )
        ).scalar_one()
        if not still_open:
            contact.needs_staff = False
    return {"ok": True}


# --------------------------------------------------------------------------------------
# Uploads (students, attendance, results, timetable)
# --------------------------------------------------------------------------------------


@router.post("/uploads", status_code=201)
async def upload(
    business: BusinessDep,
    session: SessionDep,
    user: UserDep,
    kind: Annotated[Literal["students", "attendance", "results", "timetable"], Form()],
    file: Annotated[UploadFile, File()],
    label: Annotated[str | None, Form()] = None,
    group_id: Annotated[int | None, Form()] = None,
) -> dict[str, Any]:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise bad_request("The file is larger than 5 MB")
    group = await _batch(session, business, group_id) if group_id else None
    try:
        imp = await imports.create_import(
            session,
            business,
            kind,
            file.filename or "upload",
            data,
            label=(label or "").strip() or None,
            group=group,
            admin_user_id=user.id,
        )
    except imports.UploadError as exc:
        raise bad_request(str(exc)) from exc
    return {**imports.summary_out(imp, business.timezone), "rows": imp.rows}


@router.get("/uploads")
async def list_uploads(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Import).where(Import.business_id == business.id).order_by(Import.id.desc()).limit(100)
        )
    ).scalars()
    return [imports.summary_out(i, business.timezone) for i in rows]


@router.get("/uploads/{import_id}")
async def get_upload(import_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    imp = await imports.get_import(session, business.id, import_id)
    if imp is None:
        raise not_found()
    return {**imports.summary_out(imp, business.timezone), "rows": imp.rows}


@router.post("/uploads/{import_id}/apply")
async def apply_upload(
    import_id: int, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    imp = await imports.get_import(session, business.id, import_id)
    if imp is None:
        raise not_found()
    try:
        result = await imports.apply(session, business, imp)
    except imports.UploadError as exc:
        raise bad_request(str(exc)) from exc
    await audit(
        session,
        business_id=business.id,
        action=f"upload_{imp.kind}",
        admin_user_id=user.id,
        details={"import_id": imp.id, "result": {k: v for k, v in result.items() if k != "notes"}},
    )
    return {**imports.summary_out(imp, business.timezone), "result": result}


@router.post("/uploads/{import_id}/cancel")
async def cancel_upload(import_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    imp = await imports.get_import(session, business.id, import_id)
    if imp is None:
        raise not_found()
    if imp.status != "preview":
        raise bad_request("Only a preview can be cancelled")
    imp.status = "cancelled"
    return imports.summary_out(imp, business.timezone)


# --------------------------------------------------------------------------------------
# Timetable
# --------------------------------------------------------------------------------------


@router.get("/timetable")
async def get_timetable(
    business: BusinessDep, session: SessionDep, group_id: int | None = None
) -> list[dict[str, Any]]:
    stmt = select(TimetableEntry).where(TimetableEntry.business_id == business.id)
    if group_id:
        stmt = stmt.where(TimetableEntry.group_id == group_id)
    rows = (
        await session.execute(
            stmt.order_by(
                TimetableEntry.group_id,
                TimetableEntry.date.nulls_first(),
                TimetableEntry.weekday,
                TimetableEntry.start_time,
            )
        )
    ).scalars()
    return [
        {
            "id": e.id,
            "group_id": e.group_id,
            "weekday": e.weekday,
            "date": e.date.isoformat() if e.date else None,
            "start": e.start_time.strftime("%H:%M"),
            "end": e.end_time.strftime("%H:%M") if e.end_time else None,
            "subject": e.subject,
            "teacher": e.teacher,
            "room": e.room,
        }
        for e in rows
    ]


@router.delete("/timetable/{entry_id}", status_code=204)
async def delete_timetable_entry(entry_id: int, business: BusinessDep, session: SessionDep) -> None:
    entry = await session.get(TimetableEntry, entry_id)
    if entry is None or entry.business_id != business.id:
        raise not_found()
    await session.delete(entry)


# --------------------------------------------------------------------------------------
# Announcements
# --------------------------------------------------------------------------------------


async def _broadcast(session: SessionDep, business: Business, broadcast_id: int) -> Broadcast:
    b = await session.get(Broadcast, broadcast_id)
    if b is None or b.business_id != business.id:
        raise not_found("Announcement not found")
    return b


@router.get("/broadcasts")
async def list_broadcasts(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(Broadcast)
                .where(Broadcast.business_id == business.id)
                .order_by(Broadcast.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    groups = {g.id: g for g in await batch_mod.list_batches(session, business.id)}
    return [broadcasts.summary(b, groups.get(b.group_id or 0), business.timezone) for b in rows]


@router.post("/broadcasts", status_code=201)
async def create_broadcast(
    body: BroadcastIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    group = await _batch(session, business, body.group_id)
    try:
        b = await broadcasts.create_broadcast(
            session, business, group, body.message, body.audience, admin_user_id=user.id
        )
    except broadcasts.BroadcastError as exc:
        raise bad_request(str(exc)) from exc
    return broadcasts.summary(b, group, business.timezone)


@router.get("/broadcasts/{broadcast_id}")
async def get_broadcast(broadcast_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    b = await _broadcast(session, business, broadcast_id)
    group = await session.get(Group, b.group_id) if b.group_id else None
    rows = (
        (
            await session.execute(
                select(BroadcastRecipient)
                .where(BroadcastRecipient.broadcast_id == b.id)
                .order_by(BroadcastRecipient.id)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    # Unnamed parents are shown as "Parent of <student>".
    child_names: dict[int, list[str]] = {}
    ids = [r.contact_id for r in rows]
    if ids:
        links = await session.execute(
            select(ContactLink.linked_id, Contact.name, Contact.external_id)
            .join(Contact, Contact.id == ContactLink.contact_id)
            .where(ContactLink.linked_id.in_(ids), ContactLink.relation == "parent")
        )
        for parent_id, name, roll in links.all():
            child_names.setdefault(parent_id, []).append(name or f"roll {roll}")
    return {
        **broadcasts.summary(b, group, business.timezone),
        "recipients": [
            {
                "contact_id": r.contact_id,
                "name": r.contact.name
                or (
                    f"Parent of {', '.join(child_names[r.contact_id])}"
                    if r.contact_id in child_names
                    else None
                ),
                "phone": r.phone,
                "status": r.status,
                "error": r.error,
            }
            for r in rows
        ],
    }


@router.post("/broadcasts/{broadcast_id}/send")
async def send_broadcast(
    broadcast_id: int, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    b = await _broadcast(session, business, broadcast_id)
    try:
        await broadcasts.start(session, business, b)
    except broadcasts.BroadcastError as exc:
        raise bad_request(str(exc)) from exc
    await audit(
        session,
        business_id=business.id,
        action="announce",
        admin_user_id=user.id,
        details={"broadcast_id": b.id, "recipients": b.recipients_count},
    )
    group = await session.get(Group, b.group_id) if b.group_id else None
    return broadcasts.summary(b, group, business.timezone)


@router.post("/broadcasts/{broadcast_id}/cancel")
async def cancel_broadcast(broadcast_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    b = await _broadcast(session, business, broadcast_id)
    try:
        await broadcasts.cancel(session, b)
    except broadcasts.BroadcastError as exc:
        raise bad_request(str(exc)) from exc
    await broadcasts.recount(session, b)
    group = await session.get(Group, b.group_id) if b.group_id else None
    return broadcasts.summary(b, group, business.timezone)


@router.post("/broadcasts/{broadcast_id}/refresh")
async def refresh_broadcast(broadcast_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    b = await _broadcast(session, business, broadcast_id)
    changed = await broadcasts.refresh_status(session, business, b)
    group = await session.get(Group, b.group_id) if b.group_id else None
    return {**broadcasts.summary(b, group, business.timezone), "changed": changed}


# --------------------------------------------------------------------------------------
# Parent-teacher meetings
# --------------------------------------------------------------------------------------


@router.get("/ptm")
async def list_ptm(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(PtmEvent)
                .where(PtmEvent.business_id == business.id)
                .order_by(PtmEvent.date.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    groups = {g.id: g.name for g in await batch_mod.list_batches(session, business.id)}
    out = []
    for e in rows:
        start = clock.combine(e.date, e.start_time, business.timezone)
        end = clock.combine(e.date, e.end_time, business.timezone)
        booked = (
            await session.execute(
                select(func.count(Appointment.id)).where(
                    Appointment.resource_id.in_(e.resource_ids),
                    Appointment.status.in_(AppointmentStatus.ACTIVE + (AppointmentStatus.DONE,)),
                    Appointment.start_at >= start,
                    Appointment.start_at < end,
                )
            )
        ).scalar_one()
        free = (
            len(await ptm.free_slots(session, business, e))
            if e.date >= clock.local_today(business.timezone)
            else 0
        )
        out.append(
            {
                "id": e.id,
                "group_id": e.group_id,
                "batch": groups.get(e.group_id),
                "title": e.title,
                "date": e.date.isoformat(),
                "start": e.start_time.strftime("%H:%M"),
                "end": e.end_time.strftime("%H:%M"),
                "slot_minutes": e.slot_minutes,
                "resource_ids": e.resource_ids,
                "booked": booked,
                "free": free,
                "broadcast_id": e.broadcast_id,
            }
        )
    return out


@router.post("/ptm", status_code=201)
async def create_ptm(
    body: PtmIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    group = await _batch(session, business, body.group_id)
    try:
        event = await ptm.create(
            session,
            business,
            group,
            body.date,
            body.start,
            body.end,
            body.resource_ids,
            slot_minutes=body.slot_minutes,
            title=body.title,
        )
        invite = await ptm.invite(session, business, event, admin_user_id=user.id) if body.invite else None
    except (ptm.PtmError, broadcasts.BroadcastError) as exc:
        raise bad_request(str(exc)) from exc
    await audit(
        session,
        business_id=business.id,
        action="ptm_created",
        admin_user_id=user.id,
        details={"ptm_id": event.id, "batch": group.name},
    )
    return {
        "id": event.id,
        "invite": broadcasts.summary(invite, group, business.timezone) if invite else None,
    }


@router.delete("/ptm/{ptm_id}", status_code=204)
async def delete_ptm(ptm_id: int, business: BusinessDep, session: SessionDep) -> None:
    event = await session.get(PtmEvent, ptm_id)
    if event is None or event.business_id != business.id:
        raise not_found()
    await _remove_ptm_hours(session, business, event)
    await session.delete(event)


async def _remove_ptm_hours(session: SessionDep, business: Business, event: PtmEvent) -> None:
    """Drop the extra teacher hours a meeting added, so they don't stay bookable."""
    start = clock.combine(event.date, event.start_time, business.timezone)
    end = clock.combine(event.date, event.end_time, business.timezone)
    await session.execute(
        delete(Availability).where(
            Availability.resource_id.in_(event.resource_ids),
            Availability.kind == "extra",
            Availability.start_at == start,
            Availability.end_at == end,
        )
    )
