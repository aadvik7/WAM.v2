"""Institute pack definition: roles, starter plans, AI rules, wording."""

from __future__ import annotations

from wam.packs.base import Pack

STARTER_TEMPLATES: list[dict] = [
    {
        "name": "Parent-teacher meeting",
        "specialty": "Institute",
        "session_count": 1,
        "gap_days": 0,
        "duration_minutes": 10,
        "aliases": ["ptm", "parent teacher meeting", "parent-teacher meeting"],
    },
    {
        "name": "Fee installments",
        "specialty": "Institute",
        "kind": "payment",
        "session_count": 4,
        "gap_days": 30,
        "duration_minutes": None,
        "reminder_rules": {"days_before": 3},
        "aliases": ["fees", "fee", "installment", "installments", "fee plan"],
    },
]

DEFAULT_ROLES: dict[str, list[str]] = {
    "owner": ["*"],
    # Coordinators can message any batch.
    "coordinator": [
        "today",
        "summary",
        "find",
        "help",
        "announce",
        "announce_all",
        "absent",
        "paid",
        "enrol",
        "followup",
        "cancel",
        "late",
        "leave",
        "attendance",
    ],
    # Teachers: their own batches and their doubt queue only.
    "teacher": ["today", "late", "help", "summary", "find", "announce", "absent"],
    "front_desk": ["today", "enrol", "followup", "summary", "find", "help", "paid", "attendance"],
}

AI_RULES = """\
Institute rules:
- Students may ask subject questions (doubts). Never solve or explain them yourself: call raise_doubt so the
  subject teacher answers in this chat.
- Timetable questions ("what's my timetable tomorrow?"): call get_timetable and repeat what it returns.
- Fees: call get_fee_status for due dates and amounts. Never promise waivers, discounts or extensions; if they
  say they have already paid or dispute a fee, hand off to staff.
- Parent-teacher meetings: parents can reply PTM to see free 10-minute slots.
"""

INSTITUTE_PACK = Pack(
    type="institute",
    label="Institute",
    vocab={"customer": "student", "customers": "students", "resource": "teacher", "visit": "session"},
    starter_templates=STARTER_TEMPLATES,
    default_roles=DEFAULT_ROLES,
    medical=False,
    ai_rules=AI_RULES,
    hooks="wam.packs.institute.hooks",
)
