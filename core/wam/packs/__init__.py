"""Pack registry and business seeding."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam.models import Business, Role, ScheduleTemplate
from wam.packs.base import Pack
from wam.packs.clinic.pack import CLINIC_PACK
from wam.packs.institute.pack import INSTITUTE_PACK

# The business pack (v3) reuses the shared engine with its own wording; its dedicated features come later.
BUSINESS_PACK = Pack(
    type="business",
    label="Business",
    vocab={
        "customer": "customer",
        "customers": "customers",
        "resource": "staff member",
        "visit": "appointment",
    },
    default_roles={
        "owner": ["*"],
        "staff": ["today", "cancel", "late", "leave", "enrol", "followup", "attendance", "summary", "help"],
    },
    starter_templates=[
        {
            "name": "Haircut every 4 weeks",
            "specialty": "Salon",
            "session_count": None,
            "gap_days": 28,
            "duration_minutes": 45,
            "aliases": ["haircut", "hair cut", "trim"],
        },
        {
            "name": "Membership renewal",
            "specialty": "Gym",
            "session_count": None,
            "gap_days": 30,
            "duration_minutes": 15,
            "aliases": ["renewal", "membership", "gym"],
        },
        {
            "name": "Follow-up",
            "specialty": "General",
            "session_count": 1,
            "gap_days": 0,
            "duration_minutes": None,
            "aliases": ["follow up", "followup", "follow-up"],
        },
    ],
)

PACKS: dict[str, Pack] = {p.type: p for p in (CLINIC_PACK, INSTITUTE_PACK, BUSINESS_PACK)}


def get_pack(business_type: str) -> Pack:
    return PACKS.get(business_type, CLINIC_PACK)


async def seed_business(session: AsyncSession, business: Business) -> None:
    """Create the pack's default roles and starter plan templates (idempotent)."""
    pack = get_pack(business.type)
    existing_roles = {
        r.name for r in (await session.execute(select(Role).where(Role.business_id == business.id))).scalars()
    }
    for name, commands in pack.default_roles.items():
        if name not in existing_roles:
            session.add(Role(business_id=business.id, name=name, allowed_commands=list(commands)))
    existing_templates = {
        t.name
        for t in (
            await session.execute(select(ScheduleTemplate).where(ScheduleTemplate.business_id == business.id))
        ).scalars()
    }
    for tpl in pack.starter_templates:
        if tpl["name"] in existing_templates:
            continue
        session.add(
            ScheduleTemplate(
                business_id=business.id,
                name=tpl["name"],
                specialty=tpl.get("specialty"),
                session_count=tpl.get("session_count"),
                gap_days=tpl.get("gap_days", 0),
                kind=tpl.get("kind", "visit"),
                offsets_days=tpl.get("offsets_days"),
                session_labels=tpl.get("session_labels"),
                duration_minutes=tpl.get("duration_minutes"),
                aliases=tpl.get("aliases", []),
                reminder_rules=tpl.get("reminder_rules", {}),
            )
        )
    await session.flush()
