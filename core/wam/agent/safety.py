"""Emergency detection. Emergency words hand the chat to staff immediately (checked before the AI)."""

from __future__ import annotations

import re
from collections.abc import Iterable

# English, Hindi (Devanagari) and common Hinglish. Kept conservative: false positives only cause a
# handoff to a human, which is the safe direction.
EMERGENCY_PHRASES: tuple[str, ...] = (
    "emergency",
    "urgent help",
    "chest pain",
    "heart attack",
    "can't breathe",
    "cant breathe",
    "cannot breathe",
    "not breathing",
    "difficulty breathing",
    "unconscious",
    "fainted",
    "collapsed",
    "seizure",
    "having fits",
    "stroke",
    "heavy bleeding",
    "bleeding heavily",
    "bleeding a lot",
    "won't stop bleeding",
    "severe bleeding",
    "severe pain",
    "accident",
    "poison",
    "overdose",
    "suicide",
    "kill myself",
    "want to die",
    "swallowed",
    "choking",
    "allergic reaction",
    "face swelling",
    "throat swelling",
    "high fever with fits",
    "baby not breathing",
    "saans nahi",
    "sans nahi",
    "behosh",
    "khoon band nahi",
    "bahut khoon",
    "dil ka daura",
    "bachao",
    "आपातकाल",
    "सांस नहीं",
    "बेहोश",
    "खून बंद नहीं",
    "सीने में दर्द",
    "दिल का दौरा",
    "बचाओ",
)


def _normalise(text: str) -> str:
    text = text.lower().replace("’", "'")
    return re.sub(r"\s+", " ", text)


def is_emergency(text: str, extra: Iterable[str] = ()) -> bool:
    norm = _normalise(text)
    for phrase in (*EMERGENCY_PHRASES, *(e.lower() for e in extra if e)):
        if phrase.isascii():
            if re.search(r"(?<![a-z])" + re.escape(phrase) + r"(?![a-z])", norm):
                return True
        elif phrase in norm:
            return True
    return False


def emergency_reply(business_name: str, emergency_number: str | None) -> str:
    clinic_line = f" or {business_name} on {emergency_number}" if emergency_number else ""
    return (
        "This sounds urgent. Please call 112 (or 108 for an ambulance) right now"
        f"{clinic_line}, or go to the nearest hospital emergency. I've alerted our team and someone will "
        "reply here as soon as possible."
    )
