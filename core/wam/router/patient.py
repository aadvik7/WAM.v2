"""Patient / customer conversations.

Order of handling:
1. Emergency words -> instant handoff + emergency-number reply (before anything else).
2. STOP / START (opt out / in).
3. Consent notice on the first chat (DPDP).
4. Deterministic quick replies: picking an offered slot ("2"), confirming/rescheduling a reminder.
5. AI agent with tools (if enabled), else a rule-based fallback (FAQ, timings, booking offer, handoff).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.agent.agent import AgentUnavailable, ai_available, run_agent
from wam.agent.safety import emergency_reply, is_emergency
from wam.engine import appointments as appt_engine
from wam.faq import quick_answer, search_faq
from wam.flows import book_from_offer, build_offer, numbered
from wam.messaging import Outgoing, handoff, send_to_contact
from wam.models import Appointment, AppointmentStatus, Business, Contact, Schedule
from wam.packs import get_pack
from wam.settings_defaults import get_setting
from wam.state import clear_state, get_state

log = logging.getLogger(__name__)

STOP_WORDS = {"stop", "unsubscribe", "stop messages", "band karo", "opt out", "optout"}
START_WORDS = {"start", "subscribe", "resume", "unstop"}
YES_WORDS = {
    "1",
    "yes",
    "y",
    "confirm",
    "confirmed",
    "ok",
    "okay",
    "haan",
    "ha",
    "han",
    "ji",
    "done",
    "sure",
    "👍",
}
RESCHEDULE_WORDS = {"2", "reschedule", "change", "change time", "another time", "postpone", "badlo"}
BOOK_WORDS = (
    "book",
    "appointment",
    "slot",
    "visit",
    "available",
    "availability",
    "come in",
    "milna",
    "time mil",
)
HUMAN_WORDS = ("talk to", "speak to", "call me", "human", "person", "doctor se baat", "staff", "receptionist")

_CHOICE = re.compile(
    r"^\s*(?:option|no\.?|number|#)?\s*([1-9])\s*(?:st|nd|rd|th)?\s*[.!)]?\s*(?:please|pls|plz)?\s*$", re.I
)
_WORD_CHOICE = {
    "first": 1,
    "second": 2,
    "third": 3,
    "pehla": 1,
    "doosra": 2,
    "dusra": 2,
    "teesra": 3,
    "tisra": 3,
}


@dataclass
class PatientOutcome:
    handled_by: str  # rule | ai | staff | none
    replies: int = 0


def parse_choice(text: str) -> int | None:
    match = _CHOICE.match(text)
    if match:
        return int(match.group(1))
    word = text.strip().lower().rstrip(".!")
    for key, value in _WORD_CHOICE.items():
        if word in (key, f"the {key}", f"{key} one", f"{key} slot"):
            return value
    return None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).strip(" .!")


async def _reply(
    session: AsyncSession, business: Business, contact: Contact, text: str, handled_by: str
) -> None:
    await send_to_contact(
        session, business, contact, Outgoing(text=text), handled_by=handled_by, proactive=False
    )


async def handle_patient_message(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    text: str,
    *,
    conversation_id: int | None,
    conversation_status: str | None = None,
    conversation_assigned: bool = False,
    inbound_log_id: int | None = None,
) -> PatientOutcome:
    pack = get_pack(business.type)
    norm = _norm(text)

    # 1. Emergency — always first, even if staff are handling the chat.
    if pack.medical and is_emergency(text, get_setting(business.settings, "extra_emergency_words")):
        await _reply(
            session, business, contact, emergency_reply(business.name, business.emergency_number), "staff"
        )
        contact.needs_staff = True
        await handoff(
            business, conversation_id, "EMERGENCY words in patient message", urgent=True, labels=["emergency"]
        )
        from wam.flows import alert_staff

        await alert_staff(
            session,
            business,
            f'EMERGENCY message from {contact.name or contact.phone}: "{text[:200]}". Please call now.',
        )
        return PatientOutcome("staff", 1)

    # A human is handling this chat in the inbox (someone is assigned, or WAM handed it over): stay
    # quiet until staff resolve it. Chatwoot re-opens resolved chats as "pending" for the bot.
    if conversation_status == "open" and (conversation_assigned or contact.needs_staff):
        return PatientOutcome("staff", 0)

    # 2. Opt out / in
    if norm in STOP_WORDS:
        contact.opted_out = True
        await _reply(
            session,
            business,
            contact,
            "Okay, you won't get reminders or updates from us any more. Reply START anytime to turn them back on.",
            "rule",
        )
        return PatientOutcome("rule", 1)
    if norm in START_WORDS and contact.opted_out:
        contact.opted_out = False
        await _reply(session, business, contact, "Welcome back! Reminders are on again.", "rule")
        return PatientOutcome("rule", 1)

    # 3. Consent notice on first chat; continuing the chat after the notice records consent.
    if contact.consent_notice_sent_at is None:
        consent = str(get_setting(business.settings, "consent_text")).format(
            business=business.name,
            privacy_url=get_setting(business.settings, "privacy_url") or "available on request",
        )
        await _reply(session, business, contact, consent, "rule")
        contact.consent_notice_sent_at = clock.now()
    elif contact.consent_at is None:
        contact.consent_at = clock.now()

    # 4. Deterministic quick replies
    outcome = await _quick_replies(session, business, contact, text, norm, conversation_id)
    if outcome is not None:
        return outcome

    # 5. AI agent
    if ai_available(business):
        try:
            result = await run_agent(session, business, contact, pack, text, inbound_log_id=inbound_log_id)
            await _reply(session, business, contact, result.reply, "ai")
            if result.handoff_reason:
                contact.needs_staff = True
                await handoff(business, conversation_id, result.handoff_reason)
                return PatientOutcome("staff", 1)
            return PatientOutcome("ai", 1)
        except AgentUnavailable as exc:
            log.warning("AI unavailable for business %s: %s", business.id, exc)

    return await _fallback(session, business, contact, text, norm, conversation_id)


async def _quick_replies(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    text: str,
    norm: str,
    conversation_id: int | None = None,
) -> PatientOutcome | None:
    tz = business.timezone
    # Picking an offered slot
    offer = await get_state(session, key="offer", contact_id=contact.id)
    choice = parse_choice(text)
    reminder = await get_state(session, key="reminder", contact_id=contact.id)

    # A pending reminder takes priority for 1/2 answers ("1 to confirm, 2 to reschedule"),
    # unless slots were offered after the reminder was sent.
    reminder_first = reminder is not None and (offer is None or reminder.created_at >= offer.created_at)
    if reminder_first and reminder is not None:
        appt = await session.get(Appointment, reminder.data.get("appointment_id"))
        if appt is None or appt.status not in AppointmentStatus.ACTIVE:
            await clear_state(session, key="reminder", contact_id=contact.id)
        elif norm in YES_WORDS:
            await appt_engine.confirm(session, appt)
            await clear_state(session, key="reminder", contact_id=contact.id)
            await _reply(
                session,
                business,
                contact,
                f"Thanks, confirmed! See you {clock.fmt_date(appt.start_at, tz)} at {clock.fmt_time(appt.start_at, tz)}.",
                "rule",
            )
            return PatientOutcome("rule", 1)
        elif norm in RESCHEDULE_WORDS:
            await clear_state(session, key="reminder", contact_id=contact.id)
            schedule = await session.get(Schedule, appt.schedule_id) if appt.schedule_id else None
            slots, labels = await build_offer(
                session,
                business,
                contact,
                date_from=clock.local_today(tz),
                purpose="reschedule",
                schedule=schedule,
                move_appointment=appt,
            )
            if not slots:
                await _reply(
                    session,
                    business,
                    contact,
                    "I couldn't find another free slot soon. Our team will contact you.",
                    "staff",
                )
                contact.needs_staff = True
                return PatientOutcome("staff", 1)
            await _reply(
                session,
                business,
                contact,
                f"Sure. Here are the next free slots:\n{numbered(labels)}\n\nReply 1, 2 or 3 to move your visit.",
                "rule",
            )
            return PatientOutcome("rule", 1)

    if offer is not None and choice is not None:
        appt, reply = await book_from_offer(session, business, contact, choice)
        await _reply(session, business, contact, reply, "rule")
        return PatientOutcome("rule", 1)

    # The pack's own quick replies (institute: doubts, PTM, timetable, fees)
    hooks = get_pack(business.type).hook_module()
    if hooks is not None:
        pack_reply = await hooks.quick_reply(session, business, contact, text, norm, conversation_id)
        if pack_reply is not None:
            await _reply(session, business, contact, pack_reply.text, pack_reply.handled_by)
            return PatientOutcome(pack_reply.handled_by, 1)
    return None


async def _fallback(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    text: str,
    norm: str,
    conversation_id: int | None,
) -> PatientOutcome:
    """No AI: FAQ, timings/address, booking offer, else hand to staff."""
    if any(w in norm for w in HUMAN_WORDS):
        await _reply(session, business, contact, "Sure, a team member will reply here soon.", "staff")
        contact.needs_staff = True
        await handoff(business, conversation_id, "patient asked for a person")
        return PatientOutcome("staff", 1)

    answer = quick_answer(business, text)
    if answer:
        await _reply(session, business, contact, answer, "rule")
        return PatientOutcome("rule", 1)

    faqs = await search_faq(session, business.id, text, limit=1)
    if faqs:
        await _reply(session, business, contact, faqs[0].answer, "rule")
        return PatientOutcome("rule", 1)

    if any(w in norm for w in BOOK_WORDS) or norm in {"hi", "hello", "hey", "namaste", "hii"}:
        slots, labels = await build_offer(
            session, business, contact, date_from=clock.local_today(business.timezone), purpose="book"
        )
        greeting = f"Hi{(' ' + contact.name.split(' ')[0]) if contact.name else ''}! "
        if slots:
            await _reply(
                session,
                business,
                contact,
                f"{greeting}Here are the next free slots at {business.name}:\n{numbered(labels)}\n\n"
                "Reply 1, 2 or 3 to book, or ask me about timings and directions.",
                "rule",
            )
            return PatientOutcome("rule", 1)

    await _reply(
        session, business, contact, "Thanks for your message. A team member will reply here soon.", "staff"
    )
    contact.needs_staff = True
    await handoff(business, conversation_id, "WAM could not answer automatically")
    return PatientOutcome("staff", 1)
