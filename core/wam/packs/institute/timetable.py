"""Timetable questions ("What's my timetable tomorrow?") answered from the uploaded timetable."""

from __future__ import annotations

import datetime as dt
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.models import Business, Contact, Group, TimetableEntry
from wam.people import children_of, groups_of
from wam.staff.dates import parse_date

QUESTION = re.compile(
    r"\b(time ?table|schedule|classes|lectures?|class kab|kal ki class|aaj ki class)\b", re.I
)


def is_timetable_question(text: str) -> bool:
    return bool(QUESTION.search(text))


def requested_day(text: str, today: dt.date) -> dt.date:
    low = text.lower()
    if "day after tomorrow" in low or "parso" in low:
        return today + dt.timedelta(days=2)
    if re.search(r"\b(tomorrow|tmrw|tmr|kal)\b", low):
        return today + dt.timedelta(days=1)
    for word in re.findall(r"[a-z]+|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?", low):
        if word in ("today", "aaj"):
            return today
        day = parse_date(word, today) if word not in ("a", "an", "on", "in", "the", "my") else None
        if day is not None and day >= today:
            return day
    match = re.search(r"\b(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9})\b", low)
    if match:
        day = parse_date(match.group(1), today)
        if day is not None:
            return day
    return today


async def entries_for(session: AsyncSession, group: Group, day: dt.date) -> list[TimetableEntry]:
    """Dated entries for that day replace the weekly plan for that batch."""
    dated = (
        (
            await session.execute(
                select(TimetableEntry)
                .where(TimetableEntry.group_id == group.id, TimetableEntry.date == day)
                .order_by(TimetableEntry.start_time)
            )
        )
        .scalars()
        .all()
    )
    if dated:
        return list(dated)
    return list(
        (
            await session.execute(
                select(TimetableEntry)
                .where(TimetableEntry.group_id == group.id, TimetableEntry.weekday == day.weekday())
                .order_by(TimetableEntry.start_time)
            )
        )
        .scalars()
        .all()
    )


def _fmt(t: dt.time) -> str:
    return dt.datetime.combine(dt.date(2000, 1, 1), t).strftime("%I:%M %p").lstrip("0")


async def batches_for(session: AsyncSession, contact: Contact) -> list[Group]:
    ids = [contact.id] + [c.id for c in await children_of(session, contact)]
    return await groups_of(session, ids)


async def timetable_text(session: AsyncSession, business: Business, contact: Contact, day: dt.date) -> str:
    groups = await batches_for(session, contact)
    if not groups:
        return "I couldn't find your batch yet. Please ask the office to add your number to your batch."
    parts = []
    for group in groups:
        entries = await entries_for(session, group, day)
        header = f"{group.name} — {clock.fmt_date(day)}:"
        if not entries:
            parts.append(f"{header} no classes on the timetable.")
            continue
        lines = [header]
        for e in entries:
            span = f"{_fmt(e.start_time)}–{_fmt(e.end_time)}" if e.end_time else _fmt(e.start_time)
            extra = ", ".join(x for x in (e.teacher, e.room) if x)
            lines.append(f"{span} {e.subject}" + (f" ({extra})" if extra else ""))
        parts.append("\n".join(lines))
    return "\n\n".join(parts)
