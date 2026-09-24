"""Command line helpers.

python -m wam.cli migrate
python -m wam.cli create-admin --email you@example.com --password '...'  [--business-id 1]
python -m wam.cli seed-demo            # a demo clinic with a doctor, hours, FAQ, staff and patients
python -m wam.cli tick                 # run the scheduler once
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import sys
from pathlib import Path

from sqlalchemy import func, select

from wam.config import get_settings
from wam.db import dispose_engine, session_scope
from wam.models import (
    AdminUser,
    Availability,
    Business,
    Contact,
    Faq,
    Resource,
    Role,
    ScheduleTemplate,
    Staff,
)
from wam.packs import seed_business
from wam.security import hash_secret


def migrate() -> None:
    from alembic.config import Config

    from alembic import command

    # alembic.ini lives next to the `wam` package in the repo and in /app in the Docker image.
    candidates = [Path.cwd(), Path(__file__).resolve().parent.parent]
    root = next((c for c in candidates if (c / "alembic.ini").exists()), None)
    if root is None:
        sys.exit("alembic.ini not found; run from the core/ directory")
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    command.upgrade(cfg, "head")


async def create_admin(email: str, password: str, business_id: int | None, name: str | None) -> None:
    if len(password) < 8:
        sys.exit("Password must be at least 8 characters")
    async with session_scope() as session:
        existing = (
            await session.execute(select(AdminUser).where(func.lower(AdminUser.email) == email.lower()))
        ).scalar_one_or_none()
        if existing is not None:
            existing.password_hash = hash_secret(password)
            existing.business_id = business_id
            existing.is_active = True
            print(f"Updated admin {email}")
            return
        session.add(
            AdminUser(
                email=email.lower(), name=name, password_hash=hash_secret(password), business_id=business_id
            )
        )
        print(
            f"Created admin {email} ({'super admin' if business_id is None else f'business {business_id}'})"
        )


async def seed_demo() -> None:
    async with session_scope() as session:
        found = (
            await session.execute(select(Business).where(Business.name == "Smile Dental Clinic"))
        ).scalar_one_or_none()
        if found is not None:
            print(f"Demo clinic already exists (id {found.id})")
            return
        business = Business(
            name="Smile Dental Clinic",
            type="clinic",
            timezone="Asia/Kolkata",
            phone="+912212345678",
            address="Shop 4, Sunshine Plaza, Linking Road, Bandra West, Mumbai 400050",
            maps_url="https://maps.google.com/?q=Sunshine+Plaza+Bandra",
            emergency_number="+919820000000",
            hours={
                d: [["10:00", "13:00"], ["17:00", "20:00"]]
                for d in ("mon", "tue", "wed", "thu", "fri", "sat")
            },
            settings={"privacy_url": "https://example.com/privacy"},
        )
        session.add(business)
        await session.flush()
        await seed_business(session, business)
        roles = {
            r.name: r
            for r in (await session.execute(select(Role).where(Role.business_id == business.id))).scalars()
        }
        doctor_staff = Staff(
            business_id=business.id,
            name="Dr. Mehta",
            phone="+919800000001",
            role_id=roles["doctor"].id,
            pin_hash=hash_secret("1234"),
        )
        desk = Staff(
            business_id=business.id,
            name="Priya (front desk)",
            phone="+919800000002",
            role_id=roles["front_desk"].id,
            pin_hash=hash_secret("4321"),
            receives_eod_list=True,
        )
        session.add_all([doctor_staff, desk])
        await session.flush()
        doctor = Resource(
            business_id=business.id,
            name="Dr. Mehta",
            kind="doctor",
            specialty="Dental",
            slot_minutes=15,
            staff_id=doctor_staff.id,
        )
        session.add(doctor)
        await session.flush()
        for wd in range(0, 6):
            session.add(
                Availability(
                    resource_id=doctor.id,
                    kind="weekly",
                    weekday=wd,
                    start_time=dt.time(10),
                    end_time=dt.time(13),
                )
            )
            session.add(
                Availability(
                    resource_id=doctor.id,
                    kind="weekly",
                    weekday=wd,
                    start_time=dt.time(17),
                    end_time=dt.time(20),
                )
            )
        session.add_all(
            [
                Faq(
                    business_id=business.id,
                    question="What is the consultation fee?",
                    answer="The consultation fee is ₹500. Treatment costs depend on the procedure; the doctor will explain them at your visit.",
                    keywords=["fee", "fees", "cost", "price", "charges", "consultation"],
                ),
                Faq(
                    business_id=business.id,
                    question="How much does a root canal cost?",
                    answer="A root canal usually costs ₹4,000–₹8,000 per tooth depending on the tooth. The doctor will confirm after the check-up.",
                    keywords=["root canal cost", "rct cost", "root canal price"],
                ),
                Faq(
                    business_id=business.id,
                    question="Do you accept cards and UPI?",
                    answer="Yes, we accept cash, all cards and UPI.",
                    keywords=["upi", "card", "cards", "payment", "pay", "gpay", "paytm"],
                ),
                Faq(
                    business_id=business.id,
                    question="Is there parking?",
                    answer="Paid parking is available in the Sunshine Plaza basement.",
                    keywords=["parking", "park", "car"],
                ),
                Faq(
                    business_id=business.id,
                    question="When will my X-ray report be ready?",
                    answer="X-rays taken at the clinic are ready the same day; the doctor goes through them with you at the visit.",
                    keywords=["report", "reports", "x-ray", "xray"],
                ),
            ]
        )
        session.add_all(
            [
                Contact(business_id=business.id, name="Rahul Sharma", phone="+919811111111"),
                Contact(business_id=business.id, name="Anita Desai", phone="+919822222222"),
            ]
        )
        await session.flush()
        n_templates = (
            await session.execute(
                select(func.count(ScheduleTemplate.id)).where(ScheduleTemplate.business_id == business.id)
            )
        ).scalar_one()
        print(
            f"Demo clinic created (id {business.id}) with Dr. Mehta, {n_templates} plan templates, 5 FAQs.\n"
            "Staff: Dr. Mehta +919800000001 (PIN 1234), Priya front desk +919800000002 (PIN 4321).\n"
            "Patients: Rahul +919811111111, Anita +919822222222."
        )


async def run_tick() -> None:
    from wam.jobs.tasks import tick

    print(await tick())


def main() -> None:
    parser = argparse.ArgumentParser(prog="wam")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    p = sub.add_parser("create-admin")
    p.add_argument("--email", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--business-id", type=int, default=None)
    p.add_argument("--name", default=None)
    sub.add_parser("seed-demo")
    sub.add_parser("tick")
    sub.add_parser("bootstrap", help="migrate + create admin from BOOTSTRAP_ADMIN_EMAIL/PASSWORD if set")
    args = parser.parse_args()

    if args.cmd == "migrate":
        migrate()
        return

    async def run() -> None:
        try:
            if args.cmd == "create-admin":
                await create_admin(args.email, args.password, args.business_id, args.name)
            elif args.cmd == "seed-demo":
                await seed_demo()
            elif args.cmd == "tick":
                await run_tick()
            elif args.cmd == "bootstrap":
                settings = get_settings()
                if settings.bootstrap_admin_email and settings.bootstrap_admin_password:
                    async with session_scope() as session:
                        exists = (
                            await session.execute(
                                select(AdminUser).where(
                                    func.lower(AdminUser.email) == settings.bootstrap_admin_email.lower()
                                )
                            )
                        ).scalar_one_or_none()
                    if exists is None:
                        await create_admin(
                            settings.bootstrap_admin_email, settings.bootstrap_admin_password, None, "Admin"
                        )
        finally:
            await dispose_engine()

    if args.cmd == "bootstrap":
        migrate()
    asyncio.run(run())


if __name__ == "__main__":
    main()
