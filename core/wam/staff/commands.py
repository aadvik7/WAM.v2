"""Staff commands from their own WhatsApp.

Anything that cancels or messages many people needs 'YES <PIN>'. Every action goes in the audit log.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.agent.agent import ai_available, get_llm_client
from wam.audit import audit
from wam.config import get_settings
from wam.engine import appointments as appt_engine
from wam.engine import schedules as sched_engine
from wam.engine.appointments import BookingError
from wam.engine.schedules import ScheduleError
from wam.engine.slots import active_resources
from wam.flows import nudge_schedule, offer_rebook_after_cancel, plan_label, running_late
from wam.jobs.queue import schedule_job
from wam.messaging import Outgoing, send_to_staff
from wam.models import (
    Appointment,
    AppointmentStatus,
    Availability,
    Business,
    Contact,
    PendingAction,
    Resource,
    Schedule,
    ScheduleStatus,
    ScheduleTemplate,
    Staff,
)
from wam.packs import get_pack
from wam.phone import extract_phone
from wam.security import MAX_PIN_ATTEMPTS, PIN_LOCK_MINUTES, verify_secret
from wam.settings_defaults import get_setting
from wam.staff.dates import parse_date, parse_date_range, parse_offset_days, parse_time
from wam.staff.parser import HELP_TEXT, Command, parse_command
from wam.state import get_state, set_state
from wam.windows import in_send_window, next_nudge_label

log = logging.getLogger(__name__)

CONFIRM_TTL = dt.timedelta(minutes=10)
ALWAYS_ALLOWED = {"help", "confirm", "abort"}
NEEDS_PIN = {"cancel", "leave"}


class Ctx:
    def __init__(self, session: AsyncSession, business: Business, staff: Staff):
        self.session = session
        self.business = business
        self.staff = staff
        self.pack = get_pack(business.type)
        self.tz = business.timezone
        self.resources: list[Resource] = []
        self.templates: list[ScheduleTemplate] = []
        self.own_resource: Resource | None = None

    async def load(self) -> None:
        self.resources = await active_resources(self.session, self.business.id)
        self.templates = list(
            (
                await self.session.execute(
                    select(ScheduleTemplate).where(
                        ScheduleTemplate.business_id == self.business.id, ScheduleTemplate.is_active.is_(True)
                    )
                )
            )
            .scalars()
            .all()
        )
        self.own_resource = next((r for r in self.resources if r.staff_id == self.staff.id), None)

    @property
    def today(self) -> dt.date:
        return clock.local_today(self.tz)

    def resource_by_id(self, rid: int | None) -> Resource | None:
        return next((r for r in self.resources if r.id == rid), None) if rid else None

    def default_resource(self, rid: int | None) -> Resource | None:
        """Explicit doctor > the staff member's own resource > the only doctor."""
        return (
            self.resource_by_id(rid)
            or self.own_resource
            or (self.resources[0] if len(self.resources) == 1 else None)
        )

    async def reply(self, text: str) -> None:
        await send_to_staff(self.session, self.business, self.staff, Outgoing(text=text), handled_by="rule")

    async def audit(self, action: str, details: dict[str, Any]) -> None:
        await audit(
            self.session, business_id=self.business.id, action=action, details=details, staff=self.staff
        )


def allowed(staff: Staff, key: str) -> bool:
    if key in ALWAYS_ALLOWED:
        return True
    if staff.role is None:
        return key in ("today", "summary", "find")
    commands = staff.role.allowed_commands or []
    return "*" in commands or key in commands or (key == "find" and "today" in commands)


def _parse(ctx: Ctx, text: str) -> Command | None:
    """The pack's own commands first (so '… 10 min late' inside an announcement isn't 'running late')."""
    hooks = ctx.pack.hook_module()
    if hooks is not None:
        cmd = hooks.parse_staff(text)
        if cmd is not None:
            return cmd
    return parse_command(text, ctx.templates, ctx.resources)


async def handle_staff_message(session: AsyncSession, business: Business, staff: Staff, text: str) -> str:
    ctx = Ctx(session, business, staff)
    await ctx.load()
    hooks = ctx.pack.hook_module()
    cmd = _parse(ctx, text)
    if cmd is None and ai_available(business):
        rewritten = await _ai_rewrite(business, text, getattr(hooks, "REWRITE_FORMS", ""))
        if rewritten:
            cmd = _parse(ctx, rewritten)
    if cmd is None:
        await ctx.reply("Sorry, I didn't get that. Reply HELP to see what I can do.")
        return "rule"
    permission = getattr(hooks, "PERMISSION", {}).get(cmd.key, cmd.key) if hooks is not None else cmd.key
    if not allowed(staff, permission):
        await ctx.reply("Sorry, your role can't do that. Ask the owner to change it in WAM admin.")
        await ctx.audit("command_denied", {"command": cmd.key, "text": text[:200]})
        return "rule"
    if cmd.key in HANDLERS:
        await HANDLERS[cmd.key](ctx, cmd)
    elif hooks is None or not await hooks.handle_staff(ctx, cmd):
        await ctx.reply("Sorry, I didn't get that. Reply HELP to see what I can do.")
    return "rule"


# --------------------------------------------------------------------------------------
# Read-only commands
# --------------------------------------------------------------------------------------


async def cmd_help(ctx: Ctx, cmd: Command) -> None:
    hooks = ctx.pack.hook_module()
    await ctx.reply(getattr(hooks, "HELP_TEXT", HELP_TEXT) if hooks is not None else HELP_TEXT)


def _status_mark(status: str) -> str:
    return {"confirmed": " ✓", "done": " (came)", "missed": " (missed)"}.get(status, "")


async def build_day_list(
    ctx: Ctx, day: dt.date, resource: Resource | None, *, save_attendance: bool
) -> tuple[str, list[Appointment]]:
    """Numbered list of a day's appointments; for today, remembers the numbers for attendance replies."""
    appts = await appt_engine.day_list(ctx.session, ctx.business, day, resource.id if resource else None)
    title = "Today's list" if day == ctx.today else "List"
    who = f" – {resource.name}" if resource else ""
    if not appts:
        return f"{title} ({clock.fmt_date(day)}){who}: no appointments.", []
    multi = resource is None and len({a.resource_id for a in appts}) > 1
    lines = [f"{title} ({clock.fmt_date(day)}){who}:"]
    for i, a in enumerate(appts, start=1):
        name = a.contact.name or a.contact.phone or "Unknown"
        service = f" – {a.service}" if a.service else ""
        doc = f" [{a.resource.name}]" if multi else ""
        lines.append(
            f"{i}) {clock.fmt_time(a.start_at, ctx.tz)} {name}{service}{doc}{_status_mark(a.status)}"
        )
    if day == ctx.today and save_attendance:
        lines.append("\nReply with the numbers of anyone who didn't come (e.g. 2 5), or 'none'.")
        await set_state(
            ctx.session,
            business_id=ctx.business.id,
            staff_id=ctx.staff.id,
            key="attendance",
            data={"appointment_ids": [a.id for a in appts], "day": day.isoformat()},
            ttl=dt.timedelta(hours=18),
        )
    return "\n".join(lines), appts


async def cmd_today(ctx: Ctx, cmd: Command) -> None:
    day = ctx.today + dt.timedelta(days=int(cmd.args.get("day_offset") or 0))
    resource = ctx.resource_by_id(cmd.args.get("resource_id"))
    role_name = ctx.staff.role.name if ctx.staff.role else ""
    if resource is None and ctx.own_resource is not None and role_name == "doctor":
        resource = ctx.own_resource
    text, _ = await build_day_list(ctx, day, resource, save_attendance=True)
    await ctx.reply(text)


async def cmd_summary(ctx: Ctx, cmd: Command) -> None:
    session, business = ctx.session, ctx.business
    start, end = clock.day_bounds(ctx.today, ctx.tz)
    appts = await appt_engine.day_list(session, business, ctx.today)
    by_status: dict[str, int] = {}
    for a in appts:
        by_status[a.status] = by_status.get(a.status, 0) + 1
    new_bookings = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.business_id == business.id,
                Appointment.created_at >= start,
                Appointment.created_at < end,
            )
        )
    ).scalar_one()
    cancellations = (
        await session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.business_id == business.id,
                Appointment.status == AppointmentStatus.CANCELLED,
                Appointment.updated_at >= start,
                Appointment.updated_at < end,
            )
        )
    ).scalar_one()
    waiting = (
        await session.execute(
            select(func.count(Contact.id)).where(
                Contact.business_id == business.id, Contact.needs_staff.is_(True)
            )
        )
    ).scalar_one()
    overdue = (
        await session.execute(
            select(func.count(Schedule.id)).where(
                Schedule.business_id == business.id,
                Schedule.status == ScheduleStatus.ACTIVE,
                Schedule.next_due_date < ctx.today,
            )
        )
    ).scalar_one()
    parts = ", ".join(f"{v} {k}" for k, v in sorted(by_status.items())) or "none"
    await ctx.reply(
        f"Summary for {clock.fmt_date(ctx.today)}:\n"
        f"• Appointments today: {len(appts)} ({parts})\n"
        f"• New bookings made today: {new_bookings}\n"
        f"• Cancellations today: {cancellations}\n"
        f"• Chats waiting for staff: {waiting}\n"
        f"• Plans overdue: {overdue}"
    )


async def _find_contacts(ctx: Ctx, query: str, limit: int = 5) -> list[Contact]:
    phone, rest = extract_phone(query)
    stmt = select(Contact).where(Contact.business_id == ctx.business.id)
    if phone:
        stmt = stmt.where(Contact.phone == phone)
    else:
        name = rest.strip()
        if not name:
            return []
        exact = (
            (await ctx.session.execute(stmt.where(func.lower(Contact.name) == name.lower()).limit(limit)))
            .scalars()
            .unique()
            .all()
        )
        if exact:
            return list(exact)
        stmt = stmt.where(or_(Contact.name.ilike(f"{name}%"), Contact.name.ilike(f"% {name}%")))
    return list((await ctx.session.execute(stmt.order_by(Contact.id).limit(limit))).scalars().unique().all())


def _short(contact: Contact) -> str:
    phone = contact.phone or (contact.guardian.phone if contact.guardian else "") or ""
    tail = f" (…{phone[-4:]})" if phone else ""
    return f"{contact.name or 'Unknown'}{tail}"


async def cmd_find(ctx: Ctx, cmd: Command) -> None:
    contacts = await _find_contacts(ctx, cmd.args["query"], limit=3)
    if not contacts:
        await ctx.reply(f"No {ctx.pack.word('customer')} found for '{cmd.args['query']}'.")
        return
    lines = []
    for c in contacts:
        lines.append(f"{c.name or 'Unknown'} {c.phone or ''}".strip())
        for s in await sched_engine.contact_schedules(ctx.session, c.id):
            due = clock.fmt_date(s.next_due_date) if s.next_due_date else "-"
            total = f"/{s.sessions_total}" if s.sessions_total else ""
            lines.append(f"  • {s.template.name}: {s.sessions_done}{total} done, next due {due}")
        for a in await appt_engine.upcoming_for_contact(ctx.session, c.id):
            lines.append(f"  • Booked {clock.fmt_slot(a.start_at, ctx.tz)} with {a.resource.name}")
    await ctx.reply("\n".join(lines))


# --------------------------------------------------------------------------------------
# End-of-day attendance
# --------------------------------------------------------------------------------------


async def cmd_attendance(ctx: Ctx, cmd: Command) -> None:
    state = await get_state(ctx.session, key="attendance", staff_id=ctx.staff.id)
    if state is None:
        await ctx.reply("There's no list to mark right now. Send 'Today's list' first.")
        return
    ids: list[int] = state.data.get("appointment_ids", [])
    missed_numbers: list[int] = cmd.args.get("missed", [])
    bad = [n for n in missed_numbers if not 1 <= n <= len(ids)]
    if bad:
        await ctx.reply(f"The list only has numbers 1 to {len(ids)}. Please check and send again.")
        return
    now = clock.now()
    done_names: list[str] = []
    missed_names: list[str] = []
    not_yet: list[str] = []
    followup_hours = int(get_setting(ctx.business.settings, "followup_after_hours"))
    for idx, appt_id in enumerate(ids, start=1):
        appt = await ctx.session.get(Appointment, appt_id)
        if appt is None or appt.status == AppointmentStatus.CANCELLED:
            continue
        name = appt.contact.name or appt.contact.phone or f"#{appt.id}"
        if appt.start_at > now:
            if idx in missed_numbers:
                not_yet.append(name)
            continue
        try:
            if idx in missed_numbers:
                await appt_engine.mark(ctx.session, ctx.business, appt, AppointmentStatus.MISSED)
                missed_names.append(name)
                run_at = max(
                    appt.start_at + dt.timedelta(hours=followup_hours), now + dt.timedelta(minutes=30)
                )
                await schedule_job(
                    ctx.session,
                    ctx.business.id,
                    "missed_followup",
                    run_at,
                    {"appointment_id": appt.id},
                    dedupe_key=f"missed_followup:{appt.id}:1",
                )
            elif appt.status in (*AppointmentStatus.ACTIVE, AppointmentStatus.MISSED):
                # Everyone not listed came (this also corrects an earlier "missed").
                await appt_engine.mark(ctx.session, ctx.business, appt, AppointmentStatus.DONE)
                done_names.append(name)
        except BookingError as exc:
            log.warning("attendance mark failed: %s", exc)
    await ctx.audit(
        "attendance", {"done": len(done_names), "missed": missed_names, "day": state.data.get("day")}
    )
    parts = [f"Marked {len(done_names)} as came"]
    if missed_names:
        parts.append(
            f"{len(missed_names)} missed ({', '.join(missed_names)}). I'll follow up with them in {followup_hours} hours"
        )
    msg = ", ".join(parts) + "."
    if not_yet:
        msg += f" Not marked yet (visit time not reached): {', '.join(not_yet)}."
    await ctx.reply(msg)


# --------------------------------------------------------------------------------------
# Actions that need YES + PIN
# --------------------------------------------------------------------------------------


async def ask_confirmation(
    ctx: Ctx, action: str, payload: dict[str, Any], summary: str, *, prompt: str | None = None
) -> None:
    """Park an action until the staff member replies 'YES <PIN>'."""
    if not ctx.staff.pin_hash:
        await ctx.reply(
            "This needs your PIN, but you don't have one yet. Ask the owner to set it in WAM admin."
        )
        return
    pending_rows = (
        await ctx.session.execute(
            select(PendingAction).where(
                PendingAction.staff_id == ctx.staff.id, PendingAction.status == "pending"
            )
        )
    ).scalars()
    for row in pending_rows:
        row.status = "replaced"
    ctx.session.add(
        PendingAction(
            business_id=ctx.business.id,
            staff_id=ctx.staff.id,
            action=action,
            payload=payload,
            summary=summary,
            expires_at=clock.now() + CONFIRM_TTL,
        )
    )
    await ctx.session.flush()
    await ctx.reply(
        prompt or f"{summary}?\nReply YES and your PIN (e.g. YES 1234) within 10 minutes to confirm, or NO."
    )


def _resource_needed_msg(ctx: Ctx, example: str) -> str:
    names = ", ".join(r.name for r in ctx.resources) or "none set up"
    return f"Which {ctx.pack.word('resource')}? Say it like '{example}'. ({names})"


async def cmd_cancel(ctx: Ctx, cmd: Command) -> None:
    target: str = cmd.args.get("target") or ""
    resource = ctx.default_resource(cmd.args.get("resource_id"))
    t = parse_time(target)
    day = ctx.today
    words = target.lower().split()
    for n in range(len(words), 0, -1):  # "tomorrow 5 pm", "friday 5pm"
        d = parse_date(" ".join(words[:n]), ctx.today)
        if d is not None:
            day = d
            break
    candidates: list[Appointment] = []
    if t is not None:
        start = clock.combine(day, t, ctx.tz)
        stmt = select(Appointment).where(
            Appointment.business_id == ctx.business.id,
            Appointment.status.in_(AppointmentStatus.ACTIVE),
            Appointment.start_at <= start,
            Appointment.end_at > start,
        )
        if resource is not None:
            stmt = stmt.where(Appointment.resource_id == resource.id)
        candidates = list((await ctx.session.execute(stmt)).scalars().unique().all())
    else:
        name = target
        for w in ("today", "tomorrow", "tmrw"):
            name = name.replace(w, "")
        contacts = await _find_contacts(ctx, name.strip())
        for c in contacts:
            for a in await appt_engine.upcoming_for_contact(ctx.session, c.id):
                if resource is None or a.resource_id == resource.id or cmd.args.get("resource_id") is None:
                    candidates.append(a)
    if not candidates:
        await ctx.reply(
            f"I couldn't find an active appointment for '{target}'. Send 'Today's list' to check."
        )
        return
    if len(candidates) > 1:
        lines = [
            f"{clock.fmt_slot(a.start_at, ctx.tz)} {a.contact.name or ''} with {a.resource.name}"
            for a in candidates[:5]
        ]
        await ctx.reply(
            "I found more than one:\n"
            + "\n".join(lines)
            + "\nPlease be more specific, e.g. 'Cancel Dr Mehta 5 pm' or 'Cancel Rahul tomorrow'."
        )
        return
    appt = candidates[0]
    who = appt.contact.name or appt.contact.phone or "the patient"
    summary = f"Cancel {who}'s {clock.fmt_slot(appt.start_at, ctx.tz)} visit with {appt.resource.name} and offer 3 new slots"
    await ask_confirmation(ctx, "cancel", {"appointment_id": appt.id}, summary)


async def cmd_leave(ctx: Ctx, cmd: Command) -> None:
    resource = ctx.default_resource(cmd.args.get("resource_id"))
    if resource is None:
        await ctx.reply(_resource_needed_msg(ctx, "Dr Mehta on leave Friday"))
        return
    rng = parse_date_range(cmd.args.get("when", ""), ctx.today)
    if rng is None:
        await ctx.reply(
            "I couldn't read the date. Try 'On leave Friday', 'On leave tomorrow' or 'On leave 12 Oct to 14 Oct'."
        )
        return
    start_day, end_day = rng
    if start_day < ctx.today:
        await ctx.reply("That date has passed. Please send a date from today onwards.")
        return
    if (end_day - start_day).days > 60:
        await ctx.reply("That's more than 60 days. Please set long leave in WAM admin.")
        return
    start, _ = clock.day_bounds(start_day, ctx.tz)
    _, end = clock.day_bounds(end_day, ctx.tz)
    affected = (
        await ctx.session.execute(
            select(func.count(Appointment.id)).where(
                Appointment.resource_id == resource.id,
                Appointment.status.in_(AppointmentStatus.ACTIVE),
                Appointment.start_at >= max(start, clock.now()),
                Appointment.start_at < end,
            )
        )
    ).scalar_one()
    days = (
        clock.fmt_date(start_day)
        if start_day == end_day
        else f"{clock.fmt_date(start_day)} to {clock.fmt_date(end_day)}"
    )
    customers = ctx.pack.word("customers")
    summary = f"Block {resource.name} on {days} and move {affected} booked {customers}"
    await ask_confirmation(
        ctx,
        "leave",
        {"resource_id": resource.id, "start": start_day.isoformat(), "end": end_day.isoformat()},
        summary,
    )


async def cmd_abort(ctx: Ctx, cmd: Command) -> None:
    rows = (
        (
            await ctx.session.execute(
                select(PendingAction).where(
                    PendingAction.staff_id == ctx.staff.id, PendingAction.status == "pending"
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "aborted"
    await ctx.reply("Okay, nothing was changed." if rows else "There's nothing waiting for confirmation.")


async def cmd_confirm(ctx: Ctx, cmd: Command) -> None:
    staff = ctx.staff
    pending = (
        await ctx.session.execute(
            select(PendingAction)
            .where(
                PendingAction.staff_id == staff.id,
                PendingAction.status == "pending",
                PendingAction.expires_at > clock.now(),
            )
            .order_by(PendingAction.id.desc())
            .limit(1)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if pending is None:
        await ctx.reply("There's nothing waiting for confirmation (requests expire after 10 minutes).")
        return
    now = clock.now()
    if staff.pin_locked_until and staff.pin_locked_until > now:
        await ctx.reply(
            f"Too many wrong PINs. Try again after {clock.fmt_time(staff.pin_locked_until, ctx.tz)}."
        )
        return
    pin = cmd.args.get("pin")
    if not pin:
        await ctx.reply("Please reply YES followed by your PIN, e.g. YES 1234.")
        return
    if not verify_secret(pin, staff.pin_hash):
        staff.pin_failed_count += 1
        await ctx.audit("pin_failed", {"action": pending.action, "attempt": staff.pin_failed_count})
        if staff.pin_failed_count >= MAX_PIN_ATTEMPTS:
            staff.pin_locked_until = now + dt.timedelta(minutes=PIN_LOCK_MINUTES)
            staff.pin_failed_count = 0
            pending.status = "aborted"
            await ctx.reply(
                f"Wrong PIN too many times. PIN confirmations are locked for {PIN_LOCK_MINUTES} minutes."
            )
            return
        await ctx.reply(f"Wrong PIN. {MAX_PIN_ATTEMPTS - staff.pin_failed_count} tries left.")
        return
    staff.pin_failed_count = 0
    staff.pin_locked_until = None
    pending.status = "done"
    if pending.action == "cancel":
        await _do_cancel(ctx, pending.payload)
    elif pending.action == "leave":
        await _do_leave(ctx, pending.payload)
    else:
        hooks = ctx.pack.hook_module()
        if hooks is None or not await hooks.execute_pending(ctx, pending):
            await ctx.reply("Unknown action.")


async def _do_cancel(ctx: Ctx, payload: dict[str, Any]) -> None:
    appt = await ctx.session.get(Appointment, int(payload["appointment_id"]))
    if appt is None or appt.status not in AppointmentStatus.ACTIVE:
        await ctx.reply("That appointment is no longer active; nothing to cancel.")
        return
    await appt_engine.cancel(ctx.session, appt, f"cancelled by {ctx.staff.name}")
    offered = await offer_rebook_after_cancel(ctx.session, ctx.business, appt)
    who = appt.contact.name or appt.contact.phone or "the patient"
    await ctx.audit(
        "cancel_appointment",
        {"appointment_id": appt.id, "contact_id": appt.contact_id, "start_at": appt.start_at.isoformat()},
    )
    if offered:
        await ctx.reply(
            f"Cancelled {who}'s {clock.fmt_slot(appt.start_at, ctx.tz)}. I've sent {who} 3 new slots and will rebook on reply."
        )
    else:
        await ctx.reply(
            f"Cancelled {who}'s {clock.fmt_slot(appt.start_at, ctx.tz)}. No free slots were found to offer, so I've flagged {who} for a call."
        )


async def _do_leave(ctx: Ctx, payload: dict[str, Any]) -> None:
    resource = await ctx.session.get(Resource, int(payload["resource_id"]))
    if resource is None:
        await ctx.reply("That doctor no longer exists.")
        return
    start_day = dt.date.fromisoformat(payload["start"])
    end_day = dt.date.fromisoformat(payload["end"])
    start, _ = clock.day_bounds(start_day, ctx.tz)
    _, end = clock.day_bounds(end_day, ctx.tz)
    ctx.session.add(
        Availability(
            resource_id=resource.id,
            kind="leave",
            start_at=start,
            end_at=end,
            reason=f"leave via WhatsApp by {ctx.staff.name}",
        )
    )
    await ctx.session.flush()
    appts = (
        (
            await ctx.session.execute(
                select(Appointment)
                .where(
                    Appointment.resource_id == resource.id,
                    Appointment.status.in_(AppointmentStatus.ACTIVE),
                    Appointment.start_at >= max(start, clock.now()),
                    Appointment.start_at < end,
                )
                .order_by(Appointment.start_at)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    moved = 0
    for appt in appts:
        await appt_engine.cancel(ctx.session, appt, f"{resource.name} on leave")
        if await offer_rebook_after_cancel(
            ctx.session, ctx.business, appt, date_from=end_day + dt.timedelta(days=1)
        ):
            moved += 1
    await ctx.audit(
        "leave",
        {
            "resource_id": resource.id,
            "start": payload["start"],
            "end": payload["end"],
            "cancelled": [a.id for a in appts],
        },
    )
    days = (
        clock.fmt_date(start_day)
        if start_day == end_day
        else f"{clock.fmt_date(start_day)} to {clock.fmt_date(end_day)}"
    )
    msg = f"Blocked {resource.name} on {days}."
    if appts:
        msg += f" Cancelled {len(appts)} visit(s); {moved} {ctx.pack.word('customers')} got 3 new slots each and will be rebooked on reply."
        if moved < len(appts):
            msg += f" {len(appts) - moved} couldn't be offered slots and were flagged for a call."
    await ctx.reply(msg)


# --------------------------------------------------------------------------------------
# Other actions
# --------------------------------------------------------------------------------------


async def cmd_late(ctx: Ctx, cmd: Command) -> None:
    resource = ctx.default_resource(cmd.args.get("resource_id"))
    if resource is None:
        await ctx.reply(_resource_needed_msg(ctx, "Dr Mehta running 20 min late"))
        return
    minutes = int(cmd.args.get("minutes") or 0)
    if not 1 <= minutes <= 240:
        await ctx.reply("Please send the delay in minutes, e.g. 'Running 20 min late'.")
        return
    told = await running_late(ctx.session, ctx.business, resource, minutes)
    await ctx.audit(
        "running_late", {"resource_id": resource.id, "minutes": minutes, "told": [a.id for a in told]}
    )
    if not told:
        await ctx.reply(
            f"No {ctx.pack.word('customers')} are booked with {resource.name} in the next few hours."
        )
        return
    names = ", ".join(
        f"{a.contact.name or a.contact.phone} {clock.fmt_time(a.start_at, ctx.tz)}" for a in told
    )
    await ctx.reply(
        f"Told {len(told)} {ctx.pack.word('customers')} {resource.name} is running {minutes} min late: {names}."
    )


async def _resolve_or_create_contact(
    ctx: Ctx, name: str, phone: str | None, *, child: bool = False
) -> tuple[Contact | None, str | None]:
    """Returns (contact, error message)."""
    session, business = ctx.session, ctx.business
    if phone:
        owner = (
            await session.execute(
                select(Contact).where(
                    Contact.business_id == business.id, Contact.phone == phone, Contact.guardian_id.is_(None)
                )
            )
        ).scalar_one_or_none()
        if child:
            # Phone belongs to a parent; the child is a linked contact without its own phone.
            if owner is None:
                owner = Contact(business_id=business.id, phone=phone)
                session.add(owner)
                await session.flush()
            if not name:
                return None, "Please include the child's name."
            kid = (
                await session.execute(
                    select(Contact).where(
                        Contact.business_id == business.id,
                        Contact.guardian_id == owner.id,
                        func.lower(Contact.name) == name.lower(),
                    )
                )
            ).scalar_one_or_none()
            if kid is None:
                kid = Contact(business_id=business.id, name=name, guardian_id=owner.id)
                session.add(kid)
                await session.flush()
                await session.refresh(kid, ["guardian"])
            return kid, None
        if owner is None:
            owner = Contact(business_id=business.id, phone=phone, name=name or None)
            session.add(owner)
            await session.flush()
        elif name and not owner.name:
            owner.name = name
        return owner, None
    if not name:
        return None, "Please include the patient's name."
    matches = await _find_contacts(ctx, name)
    if len(matches) == 1:
        return matches[0], None
    customer = ctx.pack.word("customer")
    if not matches:
        return (
            None,
            f"I don't have a {customer} called {name} yet. Send the number too, e.g. '{name} 98xxxxxxxx, root canal'.",
        )
    options = ", ".join(_short(c) for c in matches[:4])
    return (
        None,
        f"I found {len(matches)} called {name}: {options}. Send the number too, e.g. '{name} 98xxxxxxxx, …'.",
    )


async def cmd_enrol(ctx: Ctx, cmd: Command) -> None:
    template = next((t for t in ctx.templates if t.id == cmd.args.get("template_id")), None)
    if template is None:
        await ctx.reply("I don't know that plan. Check the plan names in WAM admin.")
        return
    anchor: dt.date | None = None
    if template.offsets_days:
        born = parse_date(str(cmd.args.get("born") or ""), ctx.today) if cmd.args.get("born") else None
        if born is not None and born > ctx.today:
            born = born.replace(year=born.year - 1)
        if born is None:
            await ctx.reply(
                f"Please add the date of birth, e.g. 'Aarav 98xxxxxxxx, {template.name.lower()}, born 12/03/2026'."
            )
            return
        anchor = born
    contact, error = await _resolve_or_create_contact(
        ctx,
        cmd.args.get("name", ""),
        cmd.args.get("phone"),
        child=bool(template.offsets_days and cmd.args.get("phone")),
    )
    if contact is None:
        await ctx.reply(error or "I couldn't find that patient.")
        return
    resource = ctx.resource_by_id(cmd.args.get("resource_id")) or ctx.own_resource
    sessions_done = int(cmd.args.get("sessions_done") or 0)
    if template.offsets_days and anchor is not None and sessions_done == 0:
        # Skip doses whose due date is long past (they were given elsewhere or earlier).
        cutoff = ctx.today - dt.timedelta(days=14)
        sessions_done = sum(
            1 for off in template.offsets_days if anchor + dt.timedelta(days=int(off)) < cutoff
        )
        sessions_done = min(sessions_done, len(template.offsets_days) - 1)
    first_due = None
    if not template.offsets_days and sessions_done > 0:
        first_due = ctx.today + dt.timedelta(days=template.gap_days)
    try:
        schedule = await sched_engine.enrol(
            ctx.session,
            ctx.business,
            contact,
            template,
            resource_id=resource.id if resource else None,
            anchor_date=anchor,
            sessions_done=sessions_done,
            first_due=first_due,
            staff_id=ctx.staff.id,
        )
    except ScheduleError as exc:
        await ctx.reply(str(exc))
        return
    await ctx.audit(
        "enrol", {"schedule_id": schedule.id, "contact_id": contact.id, "template": template.name}
    )
    who = contact.name or contact.phone or "the patient"
    total = sched_engine.total_sessions(template)
    unit = "installments" if template.kind == "payment" else "visits"
    plan_desc = template.name if total is None else f"{template.name} ({total} {unit})"
    next_label = plan_label(template, schedule.sessions_done + 1)
    if template.kind == "payment":
        due = clock.fmt_date(schedule.next_due_date) if schedule.next_due_date else "-"
        days = int((template.reminder_rules or {}).get("days_before", 3))
        await ctx.reply(
            f"Enrolled {who} in {plan_desc}. {next_label} is due {due}; I'll remind the family {days} days "
            "before each due date. Send '<name> paid' when an installment is paid."
        )
    elif (
        schedule.next_due_date is not None
        and schedule.next_due_date <= ctx.today
        and not in_send_window(ctx.business)
    ):
        await ctx.reply(
            f"Enrolled {who} in {plan_desc}. {next_label} is due now; it's outside messaging hours, so I'll "
            f"send {who} free slots at {next_nudge_label(ctx.business)}."
        )
    elif schedule.next_due_date is not None and schedule.next_due_date <= ctx.today:
        sent = await nudge_schedule(ctx.session, ctx.business, schedule)
        if sent:
            await ctx.reply(
                f"Enrolled {who} in {plan_desc}. {next_label} is due now — I've sent {who} 3 free slots."
            )
        else:
            await ctx.reply(
                f"Enrolled {who} in {plan_desc}. {next_label} is due now, but I couldn't send slots (no free slots or no WhatsApp number). I've flagged it."
            )
    else:
        due = clock.fmt_date(schedule.next_due_date) if schedule.next_due_date else "-"
        await ctx.reply(
            f"Enrolled {who} in {plan_desc}. {next_label} is due {due}; I'll message {who} with free slots then."
        )


async def cmd_followup(ctx: Ctx, cmd: Command) -> None:
    prep = cmd.args.get("prep")
    when = cmd.args.get("when", "")
    if prep in ("in", "after"):
        days = parse_offset_days(when)
        due = ctx.today + dt.timedelta(days=days) if days is not None else None
    else:
        due = parse_date(when, ctx.today)
    if due is None or due < ctx.today:
        await ctx.reply(
            "I couldn't read when. Try 'Follow-up for Rahul in 7 days' or 'Follow-up for Rahul on 12 Oct'."
        )
        return
    phone, name = extract_phone(cmd.args.get("who", ""))
    contact, error = await _resolve_or_create_contact(ctx, name.strip(" ,"), phone)
    if contact is None:
        await ctx.reply(error or "I couldn't find that patient.")
        return
    schedules = await sched_engine.contact_schedules(ctx.session, contact.id)
    who = contact.name or contact.phone or "the patient"
    if schedules:
        schedule = max(schedules, key=lambda s: s.id)
        await sched_engine.set_next_due(ctx.session, schedule, due)
        label = schedule.template.name
    else:
        template = next((t for t in ctx.templates if t.name.lower() in ("follow-up", "follow up")), None)
        if template is None:
            template = ScheduleTemplate(
                business_id=ctx.business.id,
                name="Follow-up",
                session_count=1,
                gap_days=0,
                aliases=["follow up", "followup"],
                reminder_rules={},
            )
            ctx.session.add(template)
            await ctx.session.flush()
        try:
            schedule = await sched_engine.enrol(
                ctx.session,
                ctx.business,
                contact,
                template,
                resource_id=ctx.own_resource.id if ctx.own_resource else None,
                first_due=due,
                staff_id=ctx.staff.id,
            )
        except ScheduleError as exc:
            await ctx.reply(str(exc))
            return
        label = template.name
    await ctx.audit(
        "followup", {"schedule_id": schedule.id, "contact_id": contact.id, "due": due.isoformat()}
    )
    if due == ctx.today and not in_send_window(ctx.business):
        await ctx.reply(
            f"Done — {label} for {who} is due today; I'll send {who} free slots at {next_nudge_label(ctx.business)}."
        )
    elif due == ctx.today:
        await nudge_schedule(ctx.session, ctx.business, schedule)
        await ctx.reply(f"Done — {label} for {who} is due today; I've sent {who} free slots.")
    else:
        await ctx.reply(
            f"Done — I'll message {who} on {clock.fmt_date(due)} with free slots for the {label.lower()}."
        )


HANDLERS = {
    "help": cmd_help,
    "today": cmd_today,
    "summary": cmd_summary,
    "find": cmd_find,
    "attendance": cmd_attendance,
    "cancel": cmd_cancel,
    "leave": cmd_leave,
    "confirm": cmd_confirm,
    "abort": cmd_abort,
    "late": cmd_late,
    "enrol": cmd_enrol,
    "followup": cmd_followup,
}


# --------------------------------------------------------------------------------------
# AI rewrite for free-form staff messages (the deterministic parser still decides)
# --------------------------------------------------------------------------------------

_REWRITE_PROMPT = """You convert a clinic staff member's WhatsApp message into exactly one canonical command, \
or UNKNOWN. Output only the command text, nothing else.
Canonical forms:
- today's list | tomorrow's list | today's list for dr <name>
- summary
- cancel <time like 5 pm> | cancel dr <name> <time> | cancel <patient name> | cancel <patient name> tomorrow
- running <N> min late | dr <name> running <N> min late
- on leave <day or date> | dr <name> on leave <day or date> | on leave <date> to <date>
- <patient name> <phone if given>, <plan name> [, <N> done] [, born <date>]
- follow-up for <patient name> in <N> days | follow-up for <patient name> on <date>
- find <patient name>
- help
Never invent names, numbers, PINs or dates that are not in the message. Never output YES.
Copy any announcement text word for word."""


async def _ai_rewrite(business: Business, text: str, extra_forms: str = "") -> str | None:
    system = _REWRITE_PROMPT
    if extra_forms:
        system = system.replace("- help\n", "- help\n" + extra_forms.rstrip() + "\n", 1)
    try:
        client = get_llm_client()
        response = await client.messages.create(
            model=get_settings().ai_model,
            max_tokens=300,
            system=system,
            messages=[{"role": "user", "content": text[:500]}],
        )
    except Exception as exc:  # AI is optional here
        log.info("staff rewrite unavailable: %s", exc)
        return None
    out = "".join(
        getattr(b, "text", "") for b in response.content if getattr(b, "type", None) == "text"
    ).strip()
    if not out or out.upper().startswith("UNKNOWN") or out.lower().startswith("yes"):
        return None
    return " ".join(line.strip() for line in out.splitlines() if line.strip())[:900]
