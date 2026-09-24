"""AI tools of the institute pack (added to the shared FAQ / booking / handoff tools)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from wam import clock
from wam.agent.tools import ToolContext, _schema
from wam.packs.institute import doubts, fees, ptm, timetable

TOOLS: list[dict[str, Any]] = [
    {
        "name": "raise_doubt",
        "description": (
            "Send a student's subject doubt to the subject teachers, who answer in this chat. Use for any academic "
            "question (maths, physics, chemistry, biology…). Never answer doubts yourself."
        ),
        "input_schema": _schema(
            {
                "question": {"type": "string", "description": "The doubt in the student's words"},
                "subject": {"type": "string", "description": "Subject if clear, e.g. Physics"},
            },
            ["question"],
        ),
    },
    {
        "name": "get_timetable",
        "description": "The timetable of this student's batch (or their child's) for a day.",
        "input_schema": _schema({"date": {"type": "string", "description": "YYYY-MM-DD (default today)"}}),
    },
    {
        "name": "get_fee_status",
        "description": "Fee installments of this student (or their children): next due date, amount, paid so far.",
        "input_schema": _schema({}),
    },
    {
        "name": "offer_ptm_slots",
        "description": "Free slots for the next parent-teacher meeting of the student's batch; remembers them for book_slot.",
        "input_schema": _schema({}),
    },
]

NAMES = {t["name"] for t in TOOLS}


async def run_tool(ctx: ToolContext, name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    if name not in NAMES:
        return None
    session, business, contact = ctx.session, ctx.business, ctx.contact
    if name == "raise_doubt":
        subjects = await doubts.list_subjects(session, business.id)
        subject = (
            doubts.match_subject(str(args.get("subject") or ""), subjects) if args.get("subject") else None
        )
        doubt, reply = await doubts.raise_doubt(
            session, business, contact, str(args.get("question") or "")[:4000], subject=subject
        )
        if doubt is None:
            return {"routed": False, "ask_student": reply}
        ctx.handoff_reason = None  # raise_doubt already handed the chat to the subject team
        return {"routed": True, "tell_student": reply}
    if name == "get_timetable":
        today = clock.local_today(business.timezone)
        try:
            day = dt.date.fromisoformat(str(args.get("date"))[:10]) if args.get("date") else today
        except ValueError:
            day = today
        return {"timetable": await timetable.timetable_text(session, business, contact, day)}
    if name == "get_fee_status":
        return {"fees": await fees.status_text(session, business, contact)}
    if name == "offer_ptm_slots":
        reply = await ptm.offer(session, business, contact)
        return {"reply": reply or "No parent-teacher meeting is scheduled for this batch right now."}
    return None
