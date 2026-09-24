"""WhatsApp message templates (must be approved by Meta before use).

Outside the 24-hour window WAM can only send these. Inside the window it sends the richer
free-text version instead. Meta rules followed here: no variable at the very start or end of the
body, no adjacent variables, and parameter values are single-line.

The same list is exported for submission (see docs/whatsapp-templates.md and
`GET /api/templates`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class WaTemplate:
    key: str
    name: str  # Meta template name
    pack: str
    category: str
    params: tuple[str, ...]
    body: str  # uses {{1}}..{{n}} like Meta
    example: tuple[str, ...] = field(default_factory=tuple)
    language: str = "en"

    def render(self, values: dict[str, str]) -> str:
        out = self.body
        for idx, pname in enumerate(self.params, start=1):
            out = out.replace("{{" + str(idx) + "}}", clean_param(values.get(pname, "")))
        return out

    def positional(self, values: dict[str, str]) -> dict[str, str]:
        return {str(i): clean_param(values.get(p, "")) for i, p in enumerate(self.params, start=1)}


_WS = re.compile(r"\s{2,}")


def clean_param(value: object) -> str:
    """Template parameters can't contain newlines, tabs or 4+ consecutive spaces."""
    text = str(value if value is not None else "").replace("\n", "; ").replace("\t", " ")
    text = _WS.sub(" ", text).strip()
    return text or "-"


TEMPLATES: dict[str, WaTemplate] = {
    t.key: t
    for t in [
        WaTemplate(
            key="session_due",
            name="wam_session_due",
            pack="clinic",
            category="UTILITY",
            params=("name", "session", "resource", "slots"),
            body=(
                "Hi {{1}}, your {{2}} with {{3}} is due. Free slots: {{4}}. "
                "Reply 1, 2 or 3 to book, or tell us a time that suits you."
            ),
            example=(
                "Rahul",
                "Root canal (2nd sitting)",
                "Dr. Mehta",
                "1) Mon 12 Oct, 10:00 AM 2) Tue 13 Oct, 5:30 PM",
            ),
        ),
        WaTemplate(
            key="day_before_reminder",
            name="wam_day_before_reminder",
            pack="all",
            category="UTILITY",
            params=("service", "resource", "time"),
            body="Reminder: {{1}} with {{2}} tomorrow at {{3}}. Reply 1 to confirm or 2 to reschedule.",
            example=("Root canal (visit 2 of 3)", "Dr. Mehta", "5:30 PM"),
        ),
        WaTemplate(
            key="missed_followup",
            name="wam_missed_followup",
            pack="clinic",
            category="UTILITY",
            params=("name", "slots"),
            body="Hi {{1}}, we missed you at your last visit. Next free slots: {{2}}. Reply 1, 2 or 3 to book.",
            example=("Rahul", "1) Mon 12 Oct, 10:00 AM 2) Tue 13 Oct, 5:30 PM"),
        ),
        WaTemplate(
            key="recall",
            name="wam_recall",
            pack="clinic,business",
            category="UTILITY",
            params=("name", "service", "slots"),
            body="Hi {{1}}, it's time for your {{2}}. Free slots: {{3}}. Reply 1, 2 or 3 and I'll book it.",
            example=("Rahul", "Cleaning recall", "1) Mon 12 Oct, 10:00 AM"),
        ),
        WaTemplate(
            key="doctor_unavailable",
            name="wam_doctor_unavailable",
            pack="clinic",
            category="UTILITY",
            params=("resource", "time", "slots"),
            body="Sorry, {{1}} can't make your {{2}} visit. New slots: {{3}}. Reply 1, 2 or 3 to rebook.",
            example=("Dr. Mehta", "Fri 16 Oct, 5:00 PM", "1) Mon 19 Oct, 10:00 AM"),
        ),
        WaTemplate(
            key="booking_confirmation",
            name="wam_booking_confirmation",
            pack="all",
            category="UTILITY",
            params=("service", "date", "time"),
            body="Booked: {{1}}, {{2}} at {{3}}. Reply here if you need to change it.",
            example=("Root canal (visit 2 of 3)", "Mon 12 Oct", "10:00 AM"),
        ),
        WaTemplate(
            key="running_late",
            name="wam_running_late",
            pack="all",
            category="UTILITY",
            params=("resource", "minutes", "time"),
            body=(
                "Update: {{1}} is running about {{2}} minutes late today, so your {{3}} visit may start a "
                "little later. Thank you for your patience."
            ),
            example=("Dr. Mehta", "20", "5:30 PM"),
        ),
        WaTemplate(
            key="staff_alert",
            name="wam_staff_alert",
            pack="all",
            category="UTILITY",
            params=("business", "summary"),
            body="WAM update for {{1}}: {{2}}. Reply here to see the details.",
            example=("Smile Dental", "Today's list is ready for attendance marking"),
        ),
        WaTemplate(
            key="announcement",
            name="wam_announcement",
            pack="institute",
            category="UTILITY",
            params=("batch", "message"),
            body="Update for {{1}}: {{2}}. Reply here if you have questions.",
            example=("NEET-A2", "Tomorrow's class starts at 8 AM"),
        ),
        WaTemplate(
            key="absence_alert",
            name="wam_absence_alert",
            pack="institute",
            category="UTILITY",
            params=("student", "class"),
            body="Attendance alert: {{1}} was marked absent in {{2}} today. Reply here if this is a mistake.",
            example=("Aarav", "Physics"),
        ),
        WaTemplate(
            key="test_result",
            name="wam_test_result",
            pack="institute",
            category="UTILITY",
            params=("student", "score", "test"),
            body="Test result: {{1}} scored {{2}} in {{3}}. Reply here to talk to the teacher.",
            example=("Aarav", "82/100", "Physics unit test 3"),
        ),
        WaTemplate(
            key="fee_reminder",
            name="wam_fee_reminder",
            pack="institute",
            category="UTILITY",
            params=("amount", "date"),
            body="Installment of {{1}} is due on {{2}}. Reply here if you have already paid.",
            example=("Rs 12,000", "15 Oct"),
        ),
    ]
}


def get_template(key: str) -> WaTemplate:
    return TEMPLATES[key]


def slots_param(labels: list[str]) -> str:
    return " ".join(f"{i}) {label}" for i, label in enumerate(labels, start=1))
