"""Clinic pack (version 1): brings patients back until their treatment is done."""

from __future__ import annotations

from wam.packs.base import Pack

# Starter plan templates (clinics edit these in WAM admin).
STARTER_TEMPLATES: list[dict] = [
    {
        "name": "Root canal",
        "specialty": "Dental",
        "session_count": 3,
        "gap_days": 7,
        "duration_minutes": 30,
        "session_labels": ["1st sitting", "2nd sitting", "3rd sitting"],
        "aliases": ["rct", "root canal treatment", "root canal"],
    },
    {
        "name": "Braces adjustment",
        "specialty": "Dental",
        "session_count": None,
        "gap_days": 30,
        "duration_minutes": 20,
        "aliases": ["braces", "ortho", "orthodontic", "aligner"],
    },
    {
        "name": "Cleaning recall",
        "specialty": "Dental",
        "session_count": None,
        "gap_days": 182,
        "duration_minutes": 30,
        "aliases": ["cleaning", "scaling", "recall", "checkup", "check-up"],
    },
    {
        "name": "Laser or peel course",
        "specialty": "Skin",
        "session_count": 6,
        "gap_days": 30,
        "duration_minutes": 30,
        "aliases": ["laser", "peel", "chemical peel", "laser course", "hair removal"],
    },
    {
        "name": "Physio course",
        "specialty": "Physiotherapy",
        "session_count": 10,
        "gap_days": 2,
        "duration_minutes": 45,
        "aliases": ["physio", "physiotherapy", "rehab"],
    },
    {
        # Offsets are days from the child's date of birth. Clinics must edit this to match
        # their own schedule; WAM only reminds, it never advises on vaccines.
        "name": "Vaccination schedule",
        "specialty": "Paediatrics",
        "session_count": None,
        "gap_days": 0,
        "offsets_days": [0, 42, 70, 98, 182, 273, 365, 456, 547, 730, 1461],
        "session_labels": [
            "birth doses",
            "6-week doses",
            "10-week doses",
            "14-week doses",
            "6-month doses",
            "9-month doses",
            "12-month doses",
            "15-month doses",
            "18-month doses",
            "2-year doses",
            "4–6-year doses",
        ],
        "duration_minutes": 15,
        "aliases": ["vaccination", "vaccine", "vaccines", "immunisation", "immunization", "shots"],
    },
    {
        "name": "Chronic review",
        "specialty": "Physician",
        "session_count": None,
        "gap_days": 91,
        "duration_minutes": 15,
        "aliases": ["review", "bp review", "diabetes review", "sugar review", "thyroid review", "chronic"],
    },
    {
        "name": "Follow-up",
        "specialty": "General",
        "session_count": 1,
        "gap_days": 0,
        "duration_minutes": None,
        "aliases": ["follow up", "followup", "follow-up", "review visit"],
    },
]

DEFAULT_ROLES: dict[str, list[str]] = {
    "owner": ["*"],
    "doctor": ["today", "cancel", "late", "leave", "enrol", "followup", "attendance", "summary", "help"],
    "front_desk": ["today", "cancel", "late", "enrol", "followup", "attendance", "summary", "help"],
}

AI_RULES = """\
Medical safety (strict):
- Never give medical advice, diagnoses, medicine names, doses, or opinions on symptoms or treatment.
- If asked a medical question, say the doctor will advise at the visit, and offer to book a visit or
  hand the chat to the clinic team (use handoff_to_staff).
- Never guess report results; for report questions use the FAQ, otherwise hand off to staff.
"""

CLINIC_PACK = Pack(
    type="clinic",
    label="Clinic",
    vocab={"customer": "patient", "customers": "patients", "resource": "doctor", "visit": "visit"},
    starter_templates=STARTER_TEMPLATES,
    default_roles=DEFAULT_ROLES,
    medical=True,
    ai_rules=AI_RULES,
)
