"""Clinic info and FAQ search (used by the AI tool and by the no-AI fallback)."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam.models import Business, Faq

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DAY_NAMES = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"}

STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "what",
    "your",
    "you",
    "do",
    "does",
    "i",
    "my",
    "me",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "and",
    "or",
    "can",
    "how",
    "much",
    "please",
    "hi",
    "hello",
    "kya",
    "hai",
    "ka",
    "ki",
    "ke",
    "se",
    "mein",
    "main",
    "aap",
    "tell",
    "about",
    "there",
    "any",
    "it",
    "be",
    "have",
    "has",
    "with",
}

TIMING_WORDS = {
    "time",
    "timing",
    "timings",
    "open",
    "opening",
    "hours",
    "close",
    "closing",
    "closed",
    "kab",
    "samay",
    "sunday",
    "holiday",
    "khula",
    "band",
}
ADDRESS_WORDS = {
    "where",
    "address",
    "location",
    "located",
    "direction",
    "directions",
    "map",
    "maps",
    "kaha",
    "kahan",
    "reach",
    "parking",
    "landmark",
}


def _fmt_12h(hhmm: str) -> str:
    h, m = (int(x) for x in hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {suffix}" if m else f"{h12} {suffix}"


def hours_text(business: Business) -> str:
    hours = business.hours or {}
    if not hours:
        return ""
    groups: list[tuple[list[str], str]] = []
    for day in DAYS:
        blocks = hours.get(day) or []
        text = ", ".join(f"{_fmt_12h(a)}–{_fmt_12h(b)}" for a, b in blocks) if blocks else "Closed"
        if groups and groups[-1][1] == text:
            groups[-1][0].append(day)
        else:
            groups.append(([day], text))
    parts = []
    for days, text in groups:
        label = DAY_NAMES[days[0]] if len(days) == 1 else f"{DAY_NAMES[days[0]]}–{DAY_NAMES[days[-1]]}"
        parts.append(f"{label}: {text}")
    return "; ".join(parts)


def business_info_text(business: Business) -> str:
    lines = [f"Name: {business.name}"]
    if business.address:
        lines.append(f"Address: {business.address}")
    if business.maps_url:
        lines.append(f"Map: {business.maps_url}")
    if business.phone:
        lines.append(f"Phone: {business.phone}")
    hours = hours_text(business)
    if hours:
        lines.append(f"Timings: {hours}")
    if business.emergency_number:
        lines.append(f"Emergency number: {business.emergency_number}")
    return "\n".join(lines)


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[\w']+", text.lower()) if t not in STOPWORDS and len(t) > 1}


async def search_faq(session: AsyncSession, business_id: int, query: str, limit: int = 3) -> list[Faq]:
    faqs = (await session.execute(select(Faq).where(Faq.business_id == business_id))).scalars().all()
    q = _tokens(query)
    if not q:
        return []
    scored: list[tuple[float, Faq]] = []
    for faq in faqs:
        keywords = {k.lower().strip() for k in (faq.keywords or []) if k}
        qtokens = _tokens(faq.question)
        score = 2.0 * len(q & keywords) + len(q & qtokens)
        # multi-word keywords
        low = query.lower()
        score += sum(2.0 for k in keywords if " " in k and k in low)
        if score > 0:
            scored.append((score, faq))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:limit]]


def quick_answer(business: Business, text: str) -> str | None:
    """Answer timings / address questions from the business profile (no AI needed)."""
    tokens = _tokens(text)
    if tokens & TIMING_WORDS:
        hours = hours_text(business)
        if hours:
            return f"Our timings: {hours}."
    if tokens & ADDRESS_WORDS:
        if business.address or business.maps_url:
            parts = [p for p in (business.address, business.maps_url) if p]
            return f"We're at: {' — '.join(parts)}"
    return None
