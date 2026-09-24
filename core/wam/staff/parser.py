"""Deterministic parser for staff WhatsApp commands.

Examples: "Today's list", "Cancel my 5 pm", "Running 20 min late", "On leave Friday",
"Rahul, root canal", "Follow-up for Rahul in 7 days", "YES 1234".
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from wam.models import Resource, ScheduleTemplate
from wam.phone import extract_phone


@dataclass
class Command:
    key: str
    args: dict[str, Any] = field(default_factory=dict)


def clean(text: str) -> str:
    text = text.strip().replace("’", "'").replace("‘", "'")
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .!")


def _resource_tokens(resource: Resource) -> list[str]:
    name = resource.name.lower().replace(".", " ")
    tokens = [t for t in name.split() if t not in ("dr", "doctor", "mr", "ms", "mrs")]
    out = [" ".join(tokens)] if tokens else []
    if tokens:
        out.append(tokens[-1])
        out.append(tokens[0])
    return [t for t in out if len(t) >= 3]


def match_resource(
    text: str, resources: Sequence[Resource], require_prefix: bool = False
) -> tuple[Resource | None, str]:
    """Find a doctor mentioned in the text ("dr mehta", "mehta"); returns (resource, text without it).

    With `require_prefix`, only "dr mehta" / "doctor mehta" / "with mehta" count, so a patient called
    "Rahul Mehta" isn't mistaken for Dr. Mehta.
    """
    low = text.lower()
    prefix = r"(?:\bdr\.?\s*|\bdoctor\s+|\bwith\s+(?:dr\.?\s*)?)" + ("" if require_prefix else "?")
    best: tuple[int, Resource, re.Match[str]] | None = None
    for r in resources:
        for token in _resource_tokens(r):
            m = re.search(prefix + r"\b" + re.escape(token) + r"\b", low)
            if m and (best is None or len(m.group(0)) > best[0]):
                best = (len(m.group(0)), r, m)
    if best is None:
        return None, text
    _, res, m = best
    rest = (text[: m.start()] + text[m.end() :]).strip()
    return res, re.sub(r"\s{2,}", " ", rest)


def match_template(text: str, templates: Sequence[ScheduleTemplate]) -> tuple[ScheduleTemplate | None, str]:
    """Longest template name/alias found in the text (word boundaries)."""
    low = text.lower()
    best: tuple[int, ScheduleTemplate, re.Match[str]] | None = None
    for tpl in templates:
        for alias in [tpl.name, *(tpl.aliases or [])]:
            alias_l = alias.lower().strip()
            if not alias_l:
                continue
            m = re.search(r"(?<![\w])" + re.escape(alias_l) + r"(?![\w])", low)
            if m and (best is None or len(alias_l) > best[0]):
                best = (len(alias_l), tpl, m)
    if best is None:
        return None, text
    _, tpl, m = best
    rest = (text[: m.start()] + " " + text[m.end() :]).strip()
    return tpl, re.sub(r"\s{2,}", " ", rest)


_CONFIRM = re.compile(r"^(?:yes|y|confirm|haan|ha|ok)\b[\s,:\-]*(\d{4,6})?$", re.I)
_ABORT = re.compile(r"^(?:no|n|abort|nahi|nope|dont|don't|stop)$", re.I)
_HELP = re.compile(r"^(?:help|commands|menu|\?|hi|hello|hey|start)$", re.I)
_SUMMARY = re.compile(r"^(?:today'?s?\s+)?summary$", re.I)
_TODAY = re.compile(
    r"^(?:(?P<day>today|tomorrow|tmrw)'?s?\s*)?(?:list|appointments|schedule|patients)?(?:\s+(?:for|of)\s+(?P<who>.+))?$",
    re.I,
)
_LATE = [
    re.compile(
        r"(?:running|am|i'm|im)?\s*(?:about\s+)?(\d{1,3})\s*(?:min|mins|minute|minutes|m)\s*late", re.I
    ),
    re.compile(r"(?:running\s+)?late\s+(?:by\s+)?(\d{1,3})\s*(?:min|mins|minute|minutes|m)?", re.I),
]
_LEAVE = re.compile(
    r"^(?:(?P<who>.+?)\s+)?(?:is\s+|am\s+|i'm\s+|im\s+|will be\s+)?on\s+leave\s+(?P<when>.+)$", re.I
)
_LEAVE2 = re.compile(r"^leave\s+(?P<when>.+)$", re.I)
_CANCEL = re.compile(r"^cancel\s+(?P<target>.+)$", re.I)
_FOLLOW = re.compile(
    r"^(?:follow[\s-]?up|next visit|review)\s+(?:for\s+|with\s+|of\s+)?(?P<who>.+?)\s+(?P<prep>in|after|on)\s+(?P<when>.+)$",
    re.I,
)
_FIND = re.compile(r"^(?:find|search|patient|lookup|look up)\s+(?P<q>.+)$", re.I)
_MISSED = re.compile(r"^(?:missed|no[\s-]?show|absent)\s+(?P<nums>[\d\s,&and]+)$", re.I)
_NUMBERS = re.compile(r"^[\d\s,&]+(?:and\s+\d+)*$", re.I)
_NONE_MISSED = re.compile(
    r"^(?:none|0|nobody|no one|all came|everyone came|all present|all done|sab aaye)$", re.I
)
_DONE_N = re.compile(
    r"\b(?:(\d{1,2})\s*(?:st|nd|rd|th)?\s*(?:sitting|session|visit)?s?\s+done|done\s+(\d{1,2}))\b", re.I
)
_BORN = re.compile(
    r"\b(?:born|dob|d\.o\.b\.?|birth)\s*(?:on\s*)?[:\-]?\s*(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?"
    r"|\d{1,2}(?:st|nd|rd|th)?\s+[a-z]{3,9}(?:\s+\d{4})?|[a-z]{3,9}\s+\d{1,2}(?:,?\s+\d{4})?)",
    re.I,
)


def parse_numbers(text: str) -> list[int]:
    return sorted({int(n) for n in re.findall(r"\d+", text)})


def parse_command(
    raw: str, templates: Sequence[ScheduleTemplate] = (), resources: Sequence[Resource] = ()
) -> Command | None:
    text = clean(raw)
    if not text:
        return None
    low = text.lower()

    m = _CONFIRM.match(text)
    if m:
        return Command("confirm", {"pin": m.group(1)})
    if _ABORT.match(text):
        return Command("abort")
    if _HELP.match(text):
        return Command("help")
    if _SUMMARY.match(text):
        return Command("summary")
    m = _MISSED.match(text)
    if m:
        return Command("attendance", {"missed": parse_numbers(m.group("nums"))})
    if _NONE_MISSED.match(text):
        return Command("attendance", {"missed": []})
    if _NUMBERS.match(text):
        return Command("attendance", {"missed": parse_numbers(text)})

    if low.startswith(("today", "tomorrow", "tmrw", "list", "appointments", "schedule")):
        m = _TODAY.match(low)
        if m:
            resource = None
            if m.group("who"):
                resource, _ = match_resource(m.group("who"), resources)
            day = 1 if (m.group("day") or "").startswith(("tomorrow", "tmrw")) else 0
            return Command("today", {"day_offset": day, "resource_id": resource.id if resource else None})

    for pattern in _LATE:
        m = pattern.search(low)
        if m and "late" in low:
            resource, _ = match_resource(text, resources)
            return Command(
                "late", {"minutes": int(m.group(1)), "resource_id": resource.id if resource else None}
            )

    m = _LEAVE.match(text) or _LEAVE2.match(text)
    if m:
        who = (m.groupdict().get("who") or "").strip()
        resource = None
        if who and who.lower() not in ("i", "me", "i am", "i'm", "im"):
            resource, _ = match_resource(who, resources)
        return Command(
            "leave", {"when": m.group("when").strip(), "resource_id": resource.id if resource else None}
        )

    m = _CANCEL.match(text)
    if m:
        target = m.group("target").strip()
        resource, rest = match_resource(target, resources, require_prefix=True)
        rest = re.sub(r"^(?:my|the|appointment|appt)\s+", "", rest.strip(), flags=re.I)
        rest = re.sub(r"\b(?:appointment|appt|visit|slot)\b", "", rest, flags=re.I).strip()
        return Command("cancel", {"target": rest, "resource_id": resource.id if resource else None})

    m = _FOLLOW.match(text)
    if m:
        return Command(
            "followup",
            {
                "who": m.group("who").strip(" ,"),
                "prep": m.group("prep").lower(),
                "when": m.group("when").strip(),
            },
        )

    m = _FIND.match(text)
    if m:
        return Command("find", {"query": m.group("q").strip()})

    # Enrolment: "Rahul, root canal" / "enrol Rahul 98xxxxxxxx root canal with Dr Mehta, 1 done"
    body = re.sub(r"^(?:enrol|enroll|add|start|new)\s+", "", text, flags=re.I)
    template, rest = match_template(body, templates)
    if template is not None:
        args: dict[str, Any] = {"template_id": template.id}
        phone, rest = extract_phone(rest)
        args["phone"] = phone
        born = _BORN.search(rest)
        if born:
            args["born"] = born.group("date").strip()
            rest = (rest[: born.start()] + rest[born.end() :]).strip()
        done = _DONE_N.search(rest)
        if done:
            args["sessions_done"] = int(done.group(1) or done.group(2))
            rest = (rest[: done.start()] + rest[done.end() :]).strip()
        resource, rest = match_resource(rest, resources, require_prefix=True)
        args["resource_id"] = resource.id if resource else None
        rest = re.sub(r"\b(?:with|for|plan|on|in|course|treatment)\b", " ", rest, flags=re.I)
        name = re.sub(r"[,;:\-]+", " ", rest)
        name = re.sub(r"\s{2,}", " ", name).strip()
        args["name"] = name
        return Command("enrol", args)
    return None


HELP_TEXT = """WAM commands:
• Today's list — today's appointments (tomorrow's list works too)
• Cancel my 5 pm — cancel a visit; the patient gets 3 new slots (needs YES + PIN)
• Running 20 min late — tells your next patients
• On leave Friday — blocks the day and moves everyone booked (needs YES + PIN)
• Rahul, root canal — enrol a patient in a plan (add the number for new patients, e.g. "Rahul 98xxxxxxxx, root canal"; add "1 done" if a sitting is already done)
• Follow-up for Rahul in 7 days — schedule the next visit
• Find Rahul — see a patient's plans and visits
• Summary — today's numbers
After the end-of-day list, reply with the numbers of anyone who didn't come (or "none")."""
