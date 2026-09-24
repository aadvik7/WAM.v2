"""Tools the AI agent can call. Shared tools (FAQ, handoff) plus booking tools.

Each tool is plain code; the AI only chooses which to call and with what arguments. Booking is
restricted to options produced by `find_slots` and is re-validated by the slot engine.
"""

from __future__ import annotations

import datetime as dt
import difflib
import json
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.engine import appointments as appt_engine
from wam.engine import schedules as sched_engine
from wam.engine.appointments import BookingError
from wam.engine.slots import active_resources
from wam.faq import business_info_text, search_faq
from wam.flows import book_from_offer, build_offer, plan_label
from wam.models import Appointment, AppointmentStatus, Business, Contact, Schedule, ScheduleStatus
from wam.packs.base import Pack
from wam.settings_defaults import get_setting
from wam.state import get_state


@dataclass
class ToolContext:
    session: AsyncSession
    business: Business
    contact: Contact
    pack: Pack
    handoff_reason: str | None = None
    booked: list[Appointment] = field(default_factory=list)
    cancelled: list[Appointment] = field(default_factory=list)


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_business_info",
        "description": "Get the clinic's name, address, map link, phone number and opening hours.",
        "input_schema": _schema({}),
    },
    {
        "name": "search_faq",
        "description": (
            "Search the clinic's own FAQ for questions about fees, services, reports, payment, parking, "
            "policies and similar. Use it before answering any such question."
        ),
        "input_schema": _schema(
            {"query": {"type": "string", "description": "The patient's question"}}, ["query"]
        ),
    },
    {
        "name": "get_my_appointments",
        "description": "Get this patient's upcoming appointments and active treatment plans (with their ids).",
        "input_schema": _schema({}),
    },
    {
        "name": "find_slots",
        "description": (
            "Find real free appointment slots. Returns up to 3 numbered options and remembers them, so the "
            "patient can reply with a number. Use for new bookings, plan visits and reschedules."
        ),
        "input_schema": _schema(
            {
                "date_from": {
                    "type": "string",
                    "description": "Earliest day wanted, YYYY-MM-DD (default today)",
                },
                "date_to": {"type": "string", "description": "Latest day wanted, YYYY-MM-DD (optional)"},
                "part_of_day": {"type": "string", "enum": ["any", "morning", "afternoon", "evening"]},
                "doctor_name": {"type": "string", "description": "Only if the patient asked for a doctor"},
                "plan_id": {"type": "integer", "description": "Treatment plan id this visit belongs to"},
                "reschedule_appointment_id": {
                    "type": "integer",
                    "description": "Id of the appointment being moved, when rescheduling",
                },
            }
        ),
    },
    {
        "name": "book_slot",
        "description": (
            "Book one of the numbered options from the latest find_slots result or the slots already offered "
            "in this chat. Call only after the patient clearly picked an option."
        ),
        "input_schema": _schema({"option": {"type": "integer", "minimum": 1, "maximum": 10}}, ["option"]),
    },
    {
        "name": "confirm_appointment",
        "description": "Mark an upcoming appointment as confirmed by the patient.",
        "input_schema": _schema({"appointment_id": {"type": "integer"}}, ["appointment_id"]),
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel an upcoming appointment. Only call after the patient explicitly confirmed the cancellation.",
        "input_schema": _schema(
            {"appointment_id": {"type": "integer"}, "reason": {"type": "string"}}, ["appointment_id"]
        ),
    },
    {
        "name": "save_patient_name",
        "description": "Save the patient's name when they tell you and it is not known yet.",
        "input_schema": _schema({"name": {"type": "string"}}, ["name"]),
    },
    {
        "name": "handoff_to_staff",
        "description": (
            "Hand this chat to a person at the clinic. Use for medical questions, complaints, billing disputes, "
            "requests to talk to a person, or anything you cannot handle with the other tools."
        ),
        "input_schema": _schema({"reason": {"type": "string"}}, ["reason"]),
    },
]


def _parse_date(value: Any) -> dt.date | None:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


async def _patient_summary(ctx: ToolContext) -> dict[str, Any]:
    tz = ctx.business.timezone
    upcoming = await appt_engine.upcoming_for_contact(ctx.session, ctx.contact.id)
    plans = await sched_engine.contact_schedules(ctx.session, ctx.contact.id)
    today = clock.local_today(tz)
    return {
        "upcoming_appointments": [
            {
                "id": a.id,
                "when": clock.fmt_slot(a.start_at, tz),
                "with": a.resource.name,
                "service": a.service,
                "status": a.status,
            }
            for a in upcoming
        ],
        "active_plans": [
            {
                "id": s.id,
                "plan": s.template.name,
                "next_visit": plan_label(s.template, s.sessions_done + 1),
                "sessions_done": s.sessions_done,
                "sessions_total": s.sessions_total,
                "next_due": clock.fmt_date(s.next_due_date) if s.next_due_date else None,
                "overdue": bool(s.next_due_date and s.next_due_date < today),
            }
            for s in plans
        ],
    }


async def _due_plan(ctx: ToolContext) -> Schedule | None:
    """The single active plan that is due soon and has nothing booked (auto-attach to bookings)."""
    today = clock.local_today(ctx.business.timezone)
    candidates = []
    for s in await sched_engine.contact_schedules(ctx.session, ctx.contact.id):
        if s.template.kind == "payment":
            continue
        if s.next_due_date is None or s.next_due_date > today + dt.timedelta(days=7):
            continue
        if await sched_engine.active_appointment_for_schedule(ctx.session, s.id) is None:
            candidates.append(s)
    return candidates[0] if len(candidates) == 1 else None


async def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any]:
    business = ctx.business
    session = ctx.session
    tz = business.timezone

    if name == "get_business_info":
        return {"info": business_info_text(business)}

    if name == "search_faq":
        results = await search_faq(session, business.id, str(args.get("query", "")))
        if not results:
            return {"results": [], "note": "No FAQ entry matches. Don't guess; offer handoff_to_staff."}
        return {"results": [{"question": f.question, "answer": f.answer} for f in results]}

    if name == "get_my_appointments":
        return await _patient_summary(ctx)

    if name == "find_slots":
        if not ctx.pack.booking_enabled:
            return {"error": "Booking is not available here. Offer handoff_to_staff."}
        today = clock.local_today(tz)
        date_from = _parse_date(args.get("date_from")) or today
        if date_from < today:
            date_from = today
        horizon = int(get_setting(business.settings, "booking_horizon_days"))
        date_to = _parse_date(args.get("date_to"))
        days = 14 if date_to is None else max(0, min((date_to - date_from).days, horizon))
        move: Appointment | None = None
        schedule: Schedule | None = None
        if args.get("reschedule_appointment_id"):
            move = await session.get(Appointment, int(args["reschedule_appointment_id"]))
            if (
                move is None
                or move.contact_id != ctx.contact.id
                or move.status not in AppointmentStatus.ACTIVE
            ):
                return {"error": "That appointment can't be rescheduled (not found or not active)."}
            cutoff = int(get_setting(business.settings, "reschedule_cutoff_minutes"))
            if move.start_at - clock.now() < dt.timedelta(minutes=cutoff):
                return {
                    "error": "Too close to the appointment time to reschedule here. Offer handoff_to_staff."
                }
            if move.schedule_id:
                schedule = await session.get(Schedule, move.schedule_id)
        elif args.get("plan_id"):
            schedule = await session.get(Schedule, int(args["plan_id"]))
            if (
                schedule is None
                or schedule.contact_id != ctx.contact.id
                or schedule.status != ScheduleStatus.ACTIVE
            ):
                return {"error": "Unknown plan id."}
            if schedule.template.kind == "payment":
                return {"error": "That is a fee plan, not a visit. Use get_fee_status."}
        else:
            schedule = await _due_plan(ctx)
        resource_ids = None
        if args.get("doctor_name"):
            resources = await active_resources(session, business.id)
            names = {r.name.lower(): r.id for r in resources}
            wanted = str(args["doctor_name"]).lower().replace("dr.", "").replace("dr ", "").strip()
            match = [rid for n, rid in names.items() if wanted and wanted in n]
            if not match:
                close = difflib.get_close_matches(
                    str(args["doctor_name"]).lower(), list(names), n=1, cutoff=0.5
                )
                match = [names[close[0]]] if close else []
            if not match:
                return {"error": "No doctor by that name.", "doctors": [r.name for r in resources]}
            resource_ids = match
        part = args.get("part_of_day")
        slots, labels = await build_offer(
            session,
            business,
            ctx.contact,
            date_from=date_from,
            purpose="reschedule" if move else "book",
            schedule=schedule,
            resource_ids=resource_ids,
            move_appointment=move,
            days=days,
            part_of_day=None if part in (None, "any") else part,
        )
        if not slots:
            return {
                "options": [],
                "note": "No free slots in that range. Suggest other days or handoff_to_staff.",
            }
        return {
            "options": [{"option": i, "slot": label} for i, label in enumerate(labels, start=1)],
            "for_plan": plan_label(schedule.template, schedule.sessions_done + 1) if schedule else None,
            "note": "Show these exact options as a numbered list and ask the patient to reply with a number.",
        }

    if name == "book_slot":
        state = await get_state(session, key="offer", contact_id=ctx.contact.id)
        if state is None:
            return {"error": "No slots are on offer. Call find_slots first."}
        appt, reply = await book_from_offer(session, business, ctx.contact, int(args.get("option", 0)))
        if appt is None:
            return {"booked": False, "message": reply}
        ctx.booked.append(appt)
        return {
            "booked": True,
            "appointment_id": appt.id,
            "confirmation": reply,
        }

    if name == "confirm_appointment":
        appt = await session.get(Appointment, int(args.get("appointment_id", 0)))
        if appt is None or appt.contact_id != ctx.contact.id or appt.status not in AppointmentStatus.ACTIVE:
            return {"error": "Appointment not found."}
        await appt_engine.confirm(session, appt)
        return {"confirmed": True, "when": clock.fmt_slot(appt.start_at, tz)}

    if name == "cancel_appointment":
        appt = await session.get(Appointment, int(args.get("appointment_id", 0)))
        if appt is None or appt.contact_id != ctx.contact.id or appt.status not in AppointmentStatus.ACTIVE:
            return {"error": "Appointment not found."}
        try:
            await appt_engine.cancel(
                session, appt, f"patient: {args.get('reason') or 'cancelled on WhatsApp'}"
            )
        except BookingError as exc:
            return {"error": str(exc)}
        ctx.cancelled.append(appt)
        return {"cancelled": True, "when": clock.fmt_slot(appt.start_at, tz)}

    if name == "save_patient_name":
        new_name = str(args.get("name", "")).strip()[:120]
        if new_name and not ctx.contact.name:
            ctx.contact.name = new_name
        return {"saved": bool(new_name)}

    if name == "handoff_to_staff":
        ctx.handoff_reason = str(args.get("reason") or "patient needs a person")[:300]
        return {
            "handed_off": True,
            "note": "Tell the patient a team member will reply here soon. Do not promise a time.",
        }

    hooks = ctx.pack.hook_module()
    if hooks is not None:
        result = await hooks.run_tool(ctx, name, args)
        if result is not None:
            return result
    return {"error": f"Unknown tool {name}"}


def dump(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=False, default=str)
