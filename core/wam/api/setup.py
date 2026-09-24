"""Setup screens: business profile, staff & roles, doctors & availability, plan templates, FAQ, admin users."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from wam import clock
from wam.api.deps import BusinessDep, SessionDep, UserDep, bad_request, not_found, require_super
from wam.api.schemas import (
    AdminUserIn,
    AvailabilityIn,
    BusinessIn,
    BusinessPatch,
    FaqIn,
    LeaveIn,
    PinIn,
    ResourceIn,
    ResourcePatch,
    RoleIn,
    StaffIn,
    StaffPatch,
    TemplateIn,
    TemplatePatch,
    admin_user_out,
    availability_out,
    business_out,
    faq_out,
    resource_out,
    role_out,
    staff_out,
    template_out,
)
from wam.audit import audit
from wam.engine import appointments as appt_engine
from wam.engine.slots import find_free_slots
from wam.flows import offer_rebook_after_cancel
from wam.models import (
    AdminUser,
    Appointment,
    AppointmentStatus,
    Availability,
    Business,
    Faq,
    Resource,
    Role,
    Schedule,
    ScheduleTemplate,
    Staff,
)
from wam.packs import PACKS, seed_business
from wam.phone import normalize_phone
from wam.security import hash_secret
from wam.settings_defaults import DEFAULT_BUSINESS_SETTINGS
from wam.staff.parser import HELP_TEXT
from wam.templates import TEMPLATES

router = APIRouter(prefix="/api", tags=["setup"])
B = "/businesses/{business_id}"

COMMAND_KEYS = [
    "today",
    "cancel",
    "late",
    "leave",
    "enrol",
    "followup",
    "attendance",
    "summary",
    "find",
    "help",
    # institute pack
    "announce",
    "announce_all",
    "absent",
    "paid",
]


# --------------------------------------------------------------------------------------
# Businesses
# --------------------------------------------------------------------------------------


@router.get("/businesses")
async def list_businesses(user: UserDep, session: SessionDep) -> list[dict[str, Any]]:
    stmt = select(Business).order_by(Business.id)
    if user.business_id is not None:
        stmt = stmt.where(Business.id == user.business_id)
    return [business_out(b) for b in (await session.execute(stmt)).scalars()]


@router.post("/businesses", status_code=201)
async def create_business(
    body: BusinessIn, session: SessionDep, user: Annotated[AdminUser, Depends(require_super)]
) -> dict[str, Any]:
    data = body.model_dump()
    data["hours"] = data["hours"] or {}
    data["settings"] = data["settings"] or {}
    business = Business(**data)
    session.add(business)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("That Chatwoot inbox is already linked to another business") from exc
    await seed_business(session, business)
    await audit(session, business_id=business.id, action="business_created", admin_user_id=user.id)
    return business_out(business)


@router.get(B)
async def get_business(business: BusinessDep) -> dict[str, Any]:
    return business_out(business)


@router.patch(B)
async def update_business(
    body: BusinessPatch, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    data = body.model_dump(exclude_unset=True)
    if "type" in data and user.business_id is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super admin can change the business type")
    if "settings" in data:
        merged = dict(business.settings or {})
        for key, value in (data.pop("settings") or {}).items():
            if key not in DEFAULT_BUSINESS_SETTINGS:
                raise bad_request(f"Unknown setting '{key}'")
            merged[key] = value
        business.settings = merged
    for key, value in data.items():
        if key in ("chatwoot_api_token", "chatwoot_bot_token", "chatwoot_webhook_secret") and not value:
            continue  # blank means "keep the current token"
        setattr(business, key, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("That Chatwoot inbox is already linked to another business") from exc
    if "type" in data:
        await seed_business(session, business)
    await audit(
        session,
        business_id=business.id,
        action="business_updated",
        admin_user_id=user.id,
        details={"fields": sorted(k for k in body.model_dump(exclude_unset=True) if "token" not in k)},
    )
    return business_out(business)


@router.get("/meta")
async def meta() -> dict[str, Any]:
    return {
        "default_settings": DEFAULT_BUSINESS_SETTINGS,
        "command_keys": COMMAND_KEYS,
        "packs": {k: {"label": p.label, "vocab": p.vocab} for k, p in PACKS.items()},
        "staff_help": HELP_TEXT,
    }


@router.get("/whatsapp-templates")
async def whatsapp_templates() -> list[dict[str, Any]]:
    return [
        {
            "key": t.key,
            "name": t.name,
            "pack": t.pack,
            "category": t.category,
            "language": t.language,
            "body": t.body,
            "params": list(t.params),
            "example": list(t.example),
        }
        for t in TEMPLATES.values()
    ]


# --------------------------------------------------------------------------------------
# Roles & staff
# --------------------------------------------------------------------------------------


@router.get(B + "/roles")
async def list_roles(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(Role).where(Role.business_id == business.id).order_by(Role.id))
    ).scalars()
    return [role_out(r) for r in rows]


def _check_commands(commands: list[str]) -> list[str]:
    for c in commands:
        if c != "*" and c not in COMMAND_KEYS:
            raise bad_request(f"Unknown command '{c}'")
    return commands


@router.post(B + "/roles", status_code=201)
async def create_role(body: RoleIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    role = Role(
        business_id=business.id, name=body.name, allowed_commands=_check_commands(body.allowed_commands)
    )
    session.add(role)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A role with that name exists") from exc
    return role_out(role)


@router.patch(B + "/roles/{role_id}")
async def update_role(
    role_id: int, body: RoleIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    role = await session.get(Role, role_id)
    if role is None or role.business_id != business.id:
        raise not_found()
    role.name = body.name
    role.allowed_commands = _check_commands(body.allowed_commands)
    await audit(
        session,
        business_id=business.id,
        action="role_updated",
        admin_user_id=user.id,
        details={"role": role.name, "commands": role.allowed_commands},
    )
    return role_out(role)


@router.get(B + "/staff")
async def list_staff(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(Staff).where(Staff.business_id == business.id).order_by(Staff.id))
    ).scalars()
    return [staff_out(s) for s in rows]


async def _check_role(session: SessionDep, business: Business, role_id: int | None) -> None:
    if role_id is None:
        return
    role = await session.get(Role, role_id)
    if role is None or role.business_id != business.id:
        raise bad_request("Unknown role")


@router.post(B + "/staff", status_code=201)
async def create_staff(
    body: StaffIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    phone = normalize_phone(body.phone)
    if phone is None:
        raise bad_request("Invalid phone number")
    await _check_role(session, business, body.role_id)
    member = Staff(
        business_id=business.id,
        name=body.name,
        phone=phone,
        role_id=body.role_id,
        receives_eod_list=body.receives_eod_list,
        is_active=body.is_active,
    )
    if body.pin:
        PinIn(pin=body.pin)
        member.pin_hash = hash_secret(body.pin)
    session.add(member)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A staff member with that phone already exists") from exc
    await session.refresh(member, ["role"])
    await audit(
        session,
        business_id=business.id,
        action="staff_created",
        admin_user_id=user.id,
        details={"staff_id": member.id, "name": member.name},
    )
    return staff_out(member)


@router.patch(B + "/staff/{staff_id}")
async def update_staff(
    staff_id: int, body: StaffPatch, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    member = await session.get(Staff, staff_id)
    if member is None or member.business_id != business.id:
        raise not_found()
    data = body.model_dump(exclude_unset=True)
    if "phone" in data:
        phone = normalize_phone(data["phone"])
        if phone is None:
            raise bad_request("Invalid phone number")
        data["phone"] = phone
    if "role_id" in data:
        await _check_role(session, business, data["role_id"])
    for key, value in data.items():
        setattr(member, key, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A staff member with that phone already exists") from exc
    await session.refresh(member, ["role"])
    await audit(
        session,
        business_id=business.id,
        action="staff_updated",
        admin_user_id=user.id,
        details={"staff_id": member.id, "fields": sorted(data)},
    )
    return staff_out(member)


@router.post(B + "/staff/{staff_id}/pin")
async def set_pin(
    staff_id: int, body: PinIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    member = await session.get(Staff, staff_id)
    if member is None or member.business_id != business.id:
        raise not_found()
    member.pin_hash = hash_secret(body.pin)
    member.pin_failed_count = 0
    member.pin_locked_until = None
    await audit(
        session,
        business_id=business.id,
        action="staff_pin_set",
        admin_user_id=user.id,
        details={"staff_id": member.id},
    )
    return staff_out(member)


@router.delete(B + "/staff/{staff_id}", status_code=204)
async def delete_staff(staff_id: int, business: BusinessDep, session: SessionDep, user: UserDep) -> None:
    member = await session.get(Staff, staff_id)
    if member is None or member.business_id != business.id:
        raise not_found()
    await session.delete(member)
    await audit(
        session,
        business_id=business.id,
        action="staff_deleted",
        admin_user_id=user.id,
        details={"staff_id": staff_id, "name": member.name},
    )


# --------------------------------------------------------------------------------------
# Resources (doctors) and availability
# --------------------------------------------------------------------------------------


async def _resource(session: SessionDep, business: Business, resource_id: int) -> Resource:
    r = await session.get(Resource, resource_id)
    if r is None or r.business_id != business.id:
        raise not_found("Doctor not found")
    return r


@router.get(B + "/resources")
async def list_resources(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(Resource).where(Resource.business_id == business.id).order_by(Resource.id)
        )
    ).scalars()
    return [resource_out(r) for r in rows]


@router.post(B + "/resources", status_code=201)
async def create_resource(body: ResourceIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    if body.staff_id is not None:
        member = await session.get(Staff, body.staff_id)
        if member is None or member.business_id != business.id:
            raise bad_request("Unknown staff member")
    r = Resource(business_id=business.id, **body.model_dump())
    session.add(r)
    await session.flush()
    return resource_out(r)


@router.patch(B + "/resources/{resource_id}")
async def update_resource(
    resource_id: int, body: ResourcePatch, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    r = await _resource(session, business, resource_id)
    data = body.model_dump(exclude_unset=True)
    if data.get("staff_id") is not None:
        member = await session.get(Staff, data["staff_id"])
        if member is None or member.business_id != business.id:
            raise bad_request("Unknown staff member")
    for key, value in data.items():
        setattr(r, key, value)
    return resource_out(r)


@router.get(B + "/resources/{resource_id}/availability")
async def get_availability(resource_id: int, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    r = await _resource(session, business, resource_id)
    rows = (
        (
            await session.execute(
                select(Availability).where(Availability.resource_id == r.id).order_by(Availability.id)
            )
        )
        .scalars()
        .all()
    )
    tz = business.timezone
    return {
        "weekly": [availability_out(a, tz) for a in rows if a.kind == "weekly"],
        "breaks": [availability_out(a, tz) for a in rows if a.kind == "break"],
        "leave": [
            availability_out(a, tz) for a in rows if a.kind == "leave" and a.end_at and a.end_at > clock.now()
        ],
    }


@router.put(B + "/resources/{resource_id}/availability")
async def set_availability(
    resource_id: int, body: AvailabilityIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    r = await _resource(session, business, resource_id)
    for block in [*body.weekly, *body.breaks]:
        if block.end <= block.start:
            raise bad_request("Each block must end after it starts")
    rows = (
        (
            await session.execute(
                select(Availability).where(
                    Availability.resource_id == r.id, Availability.kind.in_(["weekly", "break"])
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        await session.delete(row)
    await session.flush()
    for w in body.weekly:
        session.add(
            Availability(
                resource_id=r.id,
                kind="weekly",
                weekday=w.weekday,
                start_time=dt.time.fromisoformat(w.start),
                end_time=dt.time.fromisoformat(w.end),
            )
        )
    for b in body.breaks:
        session.add(
            Availability(
                resource_id=r.id,
                kind="break",
                weekday=b.weekday,
                start_time=dt.time.fromisoformat(b.start),
                end_time=dt.time.fromisoformat(b.end),
            )
        )
    await session.flush()
    await audit(
        session,
        business_id=business.id,
        action="availability_updated",
        admin_user_id=user.id,
        details={"resource_id": r.id},
    )
    return await get_availability(resource_id, business, session)


@router.post(B + "/resources/{resource_id}/leave", status_code=201)
async def add_leave(
    resource_id: int, body: LeaveIn, business: BusinessDep, session: SessionDep, user: UserDep
) -> dict[str, Any]:
    r = await _resource(session, business, resource_id)
    if body.end_date < body.start_date:
        raise bad_request("End date is before start date")
    start, _ = clock.day_bounds(body.start_date, business.timezone)
    _, end = clock.day_bounds(body.end_date, business.timezone)
    leave = Availability(resource_id=r.id, kind="leave", start_at=start, end_at=end, reason=body.reason)
    session.add(leave)
    await session.flush()
    moved = 0
    affected: list[int] = []
    if body.move_appointments:
        appts = (
            (
                await session.execute(
                    select(Appointment).where(
                        Appointment.resource_id == r.id,
                        Appointment.status.in_(AppointmentStatus.ACTIVE),
                        Appointment.start_at >= max(start, clock.now()),
                        Appointment.start_at < end,
                    )
                )
            )
            .scalars()
            .unique()
            .all()
        )
        for appt in appts:
            await appt_engine.cancel(session, appt, f"{r.name} on leave")
            affected.append(appt.id)
            if await offer_rebook_after_cancel(
                session, business, appt, date_from=body.end_date + dt.timedelta(days=1)
            ):
                moved += 1
    await audit(
        session,
        business_id=business.id,
        action="leave",
        admin_user_id=user.id,
        details={
            "resource_id": r.id,
            "start": body.start_date.isoformat(),
            "end": body.end_date.isoformat(),
            "cancelled": affected,
        },
    )
    return {
        "leave": availability_out(leave, business.timezone),
        "cancelled": len(affected),
        "offered_new_slots": moved,
    }


@router.delete(B + "/leave/{availability_id}", status_code=204)
async def delete_leave(availability_id: int, business: BusinessDep, session: SessionDep) -> None:
    row = await session.get(Availability, availability_id)
    if row is None or row.kind != "leave":
        raise not_found()
    await _resource(session, business, row.resource_id)
    await session.delete(row)


@router.get(B + "/resources/{resource_id}/slots")
async def list_slots(
    resource_id: int,
    business: BusinessDep,
    session: SessionDep,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    duration_minutes: Annotated[int | None, Query(ge=5, le=480)] = None,
) -> list[dict[str, Any]]:
    r = await _resource(session, business, resource_id)
    today = clock.local_today(business.timezone)
    date_from = date_from or today
    date_to = date_to or date_from
    slots = await find_free_slots(
        session, business, r, date_from, date_to, duration_minutes=duration_minutes, limit=300
    )
    tz = business.timezone
    return [
        {
            "start_at": clock.to_local(s.start, tz).isoformat(),
            "end_at": clock.to_local(s.end, tz).isoformat(),
            "label": clock.fmt_slot(s.start, tz),
        }
        for s in slots
    ]


# --------------------------------------------------------------------------------------
# Plan templates
# --------------------------------------------------------------------------------------


@router.get(B + "/templates")
async def list_templates(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(
            select(ScheduleTemplate)
            .where(ScheduleTemplate.business_id == business.id)
            .order_by(ScheduleTemplate.id)
        )
    ).scalars()
    return [template_out(t) for t in rows]


def _validate_template(
    session_count: int | None, offsets: list[int] | None, kind: str = "visit", gap_days: int = 7
) -> None:
    if offsets is not None:
        if not offsets:
            raise bad_request("Offsets can't be empty")
        if any(o < 0 for o in offsets) or offsets != sorted(offsets):
            raise bad_request("Offsets must be increasing day counts")
    if kind == "payment" and not offsets and session_count != 1 and gap_days < 1:
        raise bad_request("Installments need at least 1 day between them")


@router.post(B + "/templates", status_code=201)
async def create_template(body: TemplateIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    _validate_template(body.session_count, body.offsets_days, body.kind, body.gap_days)
    data = body.model_dump()
    days_before = data.pop("reminder_days_before")
    rules = {"days_before": days_before} if days_before is not None else {}
    t = ScheduleTemplate(business_id=business.id, reminder_rules=rules, **data)
    session.add(t)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A plan with that name exists") from exc
    return template_out(t)


@router.patch(B + "/templates/{template_id}")
async def update_template(
    template_id: int, body: TemplatePatch, business: BusinessDep, session: SessionDep
) -> dict[str, Any]:
    t = await session.get(ScheduleTemplate, template_id)
    if t is None or t.business_id != business.id:
        raise not_found()
    data = body.model_dump(exclude_unset=True)
    ongoing = data.pop("ongoing", None)
    if "reminder_days_before" in data:
        days_before = data.pop("reminder_days_before")
        rules = dict(t.reminder_rules or {})
        if days_before is None:
            rules.pop("days_before", None)
        else:
            rules["days_before"] = days_before
        t.reminder_rules = rules
    if ongoing:
        data["session_count"] = None
        data["offsets_days"] = None
    _validate_template(
        data.get("session_count", t.session_count),
        data.get("offsets_days", t.offsets_days),
        data.get("kind", t.kind),
        data.get("gap_days", t.gap_days),
    )
    for key, value in data.items():
        setattr(t, key, value)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("A plan with that name exists") from exc
    return template_out(t)


@router.delete(B + "/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, business: BusinessDep, session: SessionDep) -> None:
    t = await session.get(ScheduleTemplate, template_id)
    if t is None or t.business_id != business.id:
        raise not_found()
    used = (
        await session.execute(select(func.count(Schedule.id)).where(Schedule.template_id == t.id))
    ).scalar_one()
    if used:
        t.is_active = False  # keep history; just hide it
    else:
        await session.delete(t)


# --------------------------------------------------------------------------------------
# FAQ
# --------------------------------------------------------------------------------------


@router.get(B + "/faqs")
async def list_faqs(business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    rows = (
        await session.execute(select(Faq).where(Faq.business_id == business.id).order_by(Faq.id))
    ).scalars()
    return [faq_out(f) for f in rows]


@router.post(B + "/faqs", status_code=201)
async def create_faq(body: FaqIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    f = Faq(
        business_id=business.id,
        question=body.question,
        answer=body.answer,
        keywords=[k.strip().lower() for k in body.keywords if k.strip()],
    )
    session.add(f)
    await session.flush()
    return faq_out(f)


@router.patch(B + "/faqs/{faq_id}")
async def update_faq(faq_id: int, body: FaqIn, business: BusinessDep, session: SessionDep) -> dict[str, Any]:
    f = await session.get(Faq, faq_id)
    if f is None or f.business_id != business.id:
        raise not_found()
    f.question = body.question
    f.answer = body.answer
    f.keywords = [k.strip().lower() for k in body.keywords if k.strip()]
    return faq_out(f)


@router.delete(B + "/faqs/{faq_id}", status_code=204)
async def delete_faq(faq_id: int, business: BusinessDep, session: SessionDep) -> None:
    f = await session.get(Faq, faq_id)
    if f is None or f.business_id != business.id:
        raise not_found()
    await session.delete(f)


# --------------------------------------------------------------------------------------
# Admin users
# --------------------------------------------------------------------------------------


@router.get("/admin-users")
async def list_admin_users(user: UserDep, session: SessionDep) -> list[dict[str, Any]]:
    stmt = select(AdminUser).order_by(AdminUser.id)
    if user.business_id is not None:
        stmt = stmt.where(AdminUser.business_id == user.business_id)
    return [admin_user_out(u) for u in (await session.execute(stmt)).scalars()]


@router.post("/admin-users", status_code=201)
async def create_admin_user(body: AdminUserIn, user: UserDep, session: SessionDep) -> dict[str, Any]:
    business_id = body.business_id
    if user.business_id is not None:
        if business_id not in (None, user.business_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to that business")
        business_id = user.business_id
    elif business_id is not None and await session.get(Business, business_id) is None:
        raise bad_request("Unknown business")
    new = AdminUser(
        email=body.email.lower(),
        name=body.name,
        password_hash=hash_secret(body.password),
        business_id=business_id,
    )
    session.add(new)
    try:
        await session.flush()
    except IntegrityError as exc:
        raise bad_request("That email is already used") from exc
    await audit(
        session,
        business_id=business_id,
        action="admin_user_created",
        admin_user_id=user.id,
        details={"email": new.email},
    )
    return admin_user_out(new)


@router.delete("/admin-users/{user_id}", status_code=204)
async def delete_admin_user(user_id: int, user: UserDep, session: SessionDep) -> None:
    target = await session.get(AdminUser, user_id)
    if target is None or (user.business_id is not None and target.business_id != user.business_id):
        raise not_found()
    if target.id == user.id:
        raise bad_request("You can't remove yourself")
    target.is_active = False
