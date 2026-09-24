"""Test fixtures. Tests run against a real Postgres (TEST_DATABASE_URL), migrated with Alembic."""

from __future__ import annotations

import datetime as dt
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+asyncpg://wam:wam@localhost:5432/wam_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["CHATWOOT_BASE_URL"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ENABLE_SIMULATOR"] = "true"
os.environ["PROCESS_INLINE"] = "true"
os.environ["ENVIRONMENT"] = "test"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-0123456789"
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

import pytest  # noqa: E402
from sqlalchemy import select, text  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from wam import clock  # noqa: E402
from wam.agent import agent as agent_module  # noqa: E402
from wam.db import Base, get_sessionmaker, set_engine  # noqa: E402
from wam.models import (  # noqa: E402
    Availability,
    Business,
    Contact,
    Faq,
    Resource,
    Role,
    Staff,
)
from wam.packs import seed_business  # noqa: E402
from wam.security import hash_secret  # noqa: E402

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
# Monday 5 Oct 2026, 09:00 IST
MONDAY = dt.date(2026, 10, 5)


def ist(day: dt.date, h: int, m: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST)


def _run_migrations(connection) -> None:  # type: ignore[no-untyped-def]
    from alembic.config import Config

    from alembic import command

    root = Path(__file__).resolve().parent.parent
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    cfg.attributes["connection"] = connection
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session", autouse=True)
async def database() -> AsyncIterator[None]:
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"], pool_size=10)
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations)
    set_engine(engine)
    yield
    await engine.dispose()


TABLES = [t.name for t in reversed(Base.metadata.sorted_tables)]


@pytest.fixture(autouse=True)
async def clean_db() -> AsyncIterator[None]:
    sm = get_sessionmaker()
    async with sm() as s:
        await s.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
        await s.commit()
    clock.freeze(ist(MONDAY, 9))
    agent_module.set_llm_client(None)
    yield
    clock.freeze(None)
    agent_module.set_llm_client(None)


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    sm = get_sessionmaker()
    async with sm() as s:
        yield s
        await s.rollback()


@dataclass
class Clinic:
    business_id: int
    doctor_id: int
    doctor_staff_id: int
    desk_staff_id: int
    rahul_id: int
    anita_id: int

    DOCTOR_PHONE = "+919800000001"
    DESK_PHONE = "+919800000002"
    RAHUL_PHONE = "+919811111111"
    ANITA_PHONE = "+919822222222"


async def make_clinic(s: AsyncSession) -> Clinic:
    business = Business(
        name="Smile Dental",
        type="clinic",
        timezone="Asia/Kolkata",
        address="Linking Road, Bandra",
        maps_url="https://maps.example/smile",
        emergency_number="+919820000000",
        hours={
            d: [["10:00", "13:00"], ["17:00", "20:00"]] for d in ("mon", "tue", "wed", "thu", "fri", "sat")
        },
        settings={"min_notice_minutes": 60},
    )
    s.add(business)
    await s.flush()
    await seed_business(s, business)
    roles = {
        r.name: r for r in (await s.execute(select(Role).where(Role.business_id == business.id))).scalars()
    }
    doc = Staff(
        business_id=business.id,
        name="Dr. Mehta",
        phone=Clinic.DOCTOR_PHONE,
        role_id=roles["doctor"].id,
        pin_hash=hash_secret("1234"),
    )
    desk = Staff(
        business_id=business.id,
        name="Priya",
        phone=Clinic.DESK_PHONE,
        role_id=roles["front_desk"].id,
        pin_hash=hash_secret("4321"),
        receives_eod_list=True,
    )
    s.add_all([doc, desk])
    await s.flush()
    doctor = Resource(
        business_id=business.id, name="Dr. Mehta", specialty="Dental", slot_minutes=30, staff_id=doc.id
    )
    s.add(doctor)
    await s.flush()
    for wd in range(6):
        s.add(
            Availability(
                resource_id=doctor.id, kind="weekly", weekday=wd, start_time=dt.time(10), end_time=dt.time(13)
            )
        )
        s.add(
            Availability(
                resource_id=doctor.id, kind="weekly", weekday=wd, start_time=dt.time(17), end_time=dt.time(20)
            )
        )
    rahul = Contact(business_id=business.id, name="Rahul Sharma", phone=Clinic.RAHUL_PHONE)
    anita = Contact(business_id=business.id, name="Anita Desai", phone=Clinic.ANITA_PHONE)
    s.add_all([rahul, anita])
    s.add(
        Faq(
            business_id=business.id,
            question="What is the consultation fee?",
            answer="Consultation is ₹500.",
            keywords=["fee", "fees", "cost", "charges"],
        )
    )
    await s.flush()
    await s.commit()
    return Clinic(business.id, doctor.id, doc.id, desk.id, rahul.id, anita.id)


@pytest.fixture
async def clinic() -> Clinic:
    sm = get_sessionmaker()
    async with sm() as s:
        return await make_clinic(s)


def freeze(day: dt.date, h: int, m: int = 0) -> None:
    clock.freeze(ist(day, h, m))
