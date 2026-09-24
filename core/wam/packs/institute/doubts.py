"""Doubt queue: a student's doubt becomes a Chatwoot conversation assigned to the subject teacher's team."""

from __future__ import annotations

import datetime as dt
import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.chatwoot import ChatwootError
from wam.messaging import chatwoot_for, handoff
from wam.models import Business, Contact, Doubt, Subject
from wam.people import groups_of
from wam.state import clear_state, set_state

log = logging.getLogger(__name__)

DOUBT_PREFIX = re.compile(
    r"^\s*(?:doubt|dout|question for (?:the )?teacher|sir,? doubt|ma'?am,? doubt)\b[\s:,.-]*", re.I
)


async def list_subjects(session: AsyncSession, business_id: int) -> list[Subject]:
    return list(
        (
            await session.execute(
                select(Subject).where(Subject.business_id == business_id).order_by(Subject.name)
            )
        )
        .scalars()
        .all()
    )


def match_subject(text: str, subjects: list[Subject]) -> Subject | None:
    """Longest subject name or alias found as a word in the text."""
    low = text.lower()
    best: tuple[int, Subject] | None = None
    for subject in subjects:
        for alias in [subject.name, *(subject.aliases or [])]:
            a = alias.lower().strip()
            if (
                a
                and re.search(r"(?<![\w])" + re.escape(a) + r"(?![\w])", low)
                and (best is None or len(a) > best[0])
            ):
                best = (len(a), subject)
    return best[1] if best else None


def strip_prefix(text: str) -> str | None:
    """'Doubt: why is the sky blue?' -> 'why is the sky blue?'; None if it isn't a doubt message."""
    match = DOUBT_PREFIX.match(text)
    if not match:
        return None
    return text[match.end() :].strip()


async def raise_doubt(
    session: AsyncSession,
    business: Business,
    contact: Contact,
    question: str,
    *,
    subject: Subject | None = None,
    conversation_id: int | None = None,
) -> tuple[Doubt | None, str]:
    """Route a doubt to its subject team. If the subject is unclear, ask for it (returns None)."""
    subjects = await list_subjects(session, business.id)
    subject = subject or match_subject(question, subjects)
    if subject is None and len(subjects) > 1:
        await set_state(
            session,
            business_id=business.id,
            contact_id=contact.id,
            key="doubt_subject",
            data={"question": question},
            ttl=dt.timedelta(hours=2),
        )
        names = ", ".join(s.name for s in subjects)
        return None, f"Which subject is this doubt for? Reply with one of: {names}."
    if subject is None and subjects:
        subject = subjects[0]
    batches = await groups_of(session, [contact.id])
    doubt = Doubt(
        business_id=business.id,
        contact_id=contact.id,
        subject_id=subject.id if subject else None,
        group_id=batches[0].id if batches else None,
        question=question[:4000],
        chatwoot_conversation_id=conversation_id or contact.chatwoot_conversation_id,
    )
    session.add(doubt)
    await session.flush()
    await clear_state(session, key="doubt_subject", contact_id=contact.id)
    # WAM stays quiet in this chat until a teacher resolves it in the inbox.
    contact.needs_staff = True
    who = contact.name or contact.phone or "A student"
    batch = f" ({batches[0].name})" if batches else ""
    label = subject.name if subject else "General"
    conv = doubt.chatwoot_conversation_id
    client = chatwoot_for(business)
    if client is not None and conv is not None and subject is not None and subject.chatwoot_team_id:
        try:
            await client.assign_team(conv, subject.chatwoot_team_id)
        except ChatwootError as exc:
            log.warning("team assignment failed: %s", exc)
    labels = ["doubt"] + ([re.sub(r"[^a-z0-9_-]+", "-", subject.name.lower())] if subject else [])
    await handoff(business, conv, f"{label} doubt from {who}{batch}: {question[:300]}", labels=labels)
    teachers = f"the {subject.name} teachers" if subject else "our teachers"
    return doubt, f"Got it! Your {label} doubt is with {teachers}. A teacher will reply here."


async def close_open_doubts(session: AsyncSession, business_id: int, contact_id: int) -> int:
    rows = (
        (
            await session.execute(
                select(Doubt).where(
                    Doubt.business_id == business_id, Doubt.contact_id == contact_id, Doubt.status == "open"
                )
            )
        )
        .scalars()
        .all()
    )
    for row in rows:
        row.status = "closed"
        row.closed_at = clock.now()
    return len(rows)
