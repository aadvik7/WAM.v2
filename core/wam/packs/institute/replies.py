"""Deterministic replies for students and parents: doubts, PTM booking, timetable, fee status, "already paid"."""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.flows import alert_staff
from wam.models import Business, Contact
from wam.packs.institute import doubts, fees, ptm, timetable
from wam.state import clear_state, get_state

GREETINGS = {"hi", "hii", "hello", "hey", "namaste", "good morning", "good evening", "menu", "help"}
PTM_WORDS = {
    "ptm",
    "book ptm",
    "ptm slot",
    "ptm booking",
    "parent teacher meeting",
    "parent-teacher meeting",
    "book a ptm",
}
FEE_QUESTION = re.compile(
    r"\b(fee|fees|installment|installments)\b.*\b(due|status|when|how much|kitna|kab|pending|balance|left)\b|\b(due|pending|balance)\b.*\b(fee|fees)\b",
    re.I,
)
PAID_CLAIM = re.compile(
    r"\b(already paid|i have paid|i've paid|we have paid|paid (the )?fees?|fees? (is |are )?paid|payment (is )?done|paid online)\b",
    re.I,
)


@dataclass
class Reply:
    text: str
    handled_by: str = "rule"


async def quick_reply(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    text: str,
    norm: str,
    conversation_id: int | None,
) -> Reply | None:
    if norm in GREETINGS:
        name = f" {contact.name.split(' ')[0]}" if contact.name else ""
        return Reply(
            f"Hi{name}! This is {business.name}. I can help with:\n"
            "• Timetable — e.g. 'timetable tomorrow'\n"
            "• Doubts — start with 'Doubt:' and your question; a teacher replies here\n"
            "• Fees — e.g. 'fees due?'\n"
            "• Parent-teacher meetings — reply PTM to book\n"
            "Or just ask your question."
        )

    # Waiting for the subject of a doubt
    pending = await get_state(session, key="doubt_subject", contact_id=contact.id)
    if pending is not None:
        subjects = await doubts.list_subjects(session, business.id)
        subject = doubts.match_subject(text, subjects)
        if subject is not None:
            _, reply = await doubts.raise_doubt(
                session,
                business,
                contact,
                pending.data["question"],
                subject=subject,
                conversation_id=conversation_id,
            )
            return Reply(reply, "staff")
        if norm in ("cancel", "no", "never mind", "nevermind"):
            await clear_state(session, key="doubt_subject", contact_id=contact.id)
            return Reply("Okay, cancelled.")

    question = doubts.strip_prefix(text)
    if question is not None:
        if not question:
            return Reply(
                "Please type your doubt after the word Doubt, e.g. 'Doubt: Physics — why is the sky blue?'"
            )
        doubt, reply = await doubts.raise_doubt(
            session, business, contact, question, conversation_id=conversation_id
        )
        return Reply(reply, "staff" if doubt is not None else "rule")

    if norm in PTM_WORDS:
        reply = await ptm.offer(session, business, contact)
        return Reply(
            reply
            or "There's no parent-teacher meeting scheduled for your batch right now. We'll message you when there is."
        )

    if PAID_CLAIM.search(text):
        who = contact.name or contact.phone
        await alert_staff(
            session, business, f'{who} says fees are paid: "{text[:200]}". Please check and record it.'
        )
        return Reply("Thanks for letting us know! Our office will check and update your record.", "staff")

    if FEE_QUESTION.search(text):
        return Reply(await fees.status_text(session, business, contact))

    if timetable.is_timetable_question(text):
        day = timetable.requested_day(text, clock.local_today(business.timezone))
        return Reply(await timetable.timetable_text(session, business, contact, day))
    return None
