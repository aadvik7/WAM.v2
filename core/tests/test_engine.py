import asyncio
import datetime as dt

import pytest
from sqlalchemy import select

from tests.conftest import MONDAY, freeze, ist
from wam import clock
from wam.db import get_sessionmaker, session_scope
from wam.engine import appointments as appt_engine
from wam.engine import schedules as sched_engine
from wam.engine.appointments import SlotUnavailable
from wam.engine.slots import find_free_slots, offer_slots
from wam.models import (
    Appointment,
    AppointmentStatus,
    Availability,
    Business,
    Contact,
    Resource,
    ScheduleStatus,
    ScheduleTemplate,
)


async def _load(s, clinic):
    business = await s.get(Business, clinic.business_id)
    doctor = await s.get(Resource, clinic.doctor_id)
    rahul = await s.get(Contact, clinic.rahul_id)
    anita = await s.get(Contact, clinic.anita_id)
    return business, doctor, rahul, anita


async def test_free_slots_respect_notice_hours_and_bookings(clinic):
    freeze(MONDAY, 10, 20)  # notice 60 min -> first slot 11:30
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        slots = await find_free_slots(s, business, doctor, MONDAY, MONDAY)
        starts = [clock.to_local(x.start, "Asia/Kolkata").strftime("%H:%M") for x in slots]
        assert starts == ["11:30", "12:00", "12:30", "17:00", "17:30", "18:00", "18:30", "19:00", "19:30"]
        await appt_engine.book(s, business, rahul, doctor.id, ist(MONDAY, 17))
    async with session_scope() as s:
        business, doctor, _, _ = await _load(s, clinic)
        slots = await find_free_slots(s, business, doctor, MONDAY, MONDAY)
        assert ist(MONDAY, 17) not in [x.start for x in slots]
        # Sunday is closed
        sunday = MONDAY + dt.timedelta(days=6)
        assert await find_free_slots(s, business, doctor, sunday, sunday) == []


async def test_booking_rejects_taken_off_grid_and_leave(clinic):
    async with session_scope() as s:
        business, doctor, rahul, anita = await _load(s, clinic)
        await appt_engine.book(s, business, rahul, doctor.id, ist(MONDAY, 17))
    async with session_scope() as s:
        business, doctor, rahul, anita = await _load(s, clinic)
        with pytest.raises(SlotUnavailable):
            await appt_engine.book(s, business, anita, doctor.id, ist(MONDAY, 17))
        with pytest.raises(SlotUnavailable):
            await appt_engine.book(s, business, anita, doctor.id, ist(MONDAY, 17, 10))  # off the slot grid
        with pytest.raises(SlotUnavailable):
            await appt_engine.book(s, business, anita, doctor.id, ist(MONDAY, 14))  # lunch gap
        tuesday = MONDAY + dt.timedelta(days=1)
        s.add(
            Availability(
                resource_id=doctor.id,
                kind="leave",
                start_at=ist(tuesday, 0),
                end_at=ist(tuesday + dt.timedelta(days=1), 0),
            )
        )
        await s.flush()
        with pytest.raises(SlotUnavailable):
            await appt_engine.book(s, business, anita, doctor.id, ist(tuesday, 10))
        # staff override can book off-grid, but never overlapping
        appt = await appt_engine.book(
            s, business, anita, doctor.id, ist(MONDAY, 14), enforce_availability=False, source="admin"
        )
        assert appt.status == AppointmentStatus.BOOKED
        with pytest.raises(SlotUnavailable):
            await appt_engine.book(
                s, business, rahul, doctor.id, ist(MONDAY, 17, 15), enforce_availability=False
            )


async def test_concurrent_bookings_only_one_wins(clinic):
    sm = get_sessionmaker()

    async def attempt(contact_id: int):
        async with sm() as s:
            business = await s.get(Business, clinic.business_id)
            contact = await s.get(Contact, contact_id)
            try:
                await appt_engine.book(s, business, contact, clinic.doctor_id, ist(MONDAY, 18))
                await s.commit()
                return True
            except SlotUnavailable:
                await s.rollback()
                return False

    results = await asyncio.gather(
        *[attempt(clinic.rahul_id if i % 2 else clinic.anita_id) for i in range(6)]
    )
    assert results.count(True) == 1
    async with session_scope() as s:
        n = (
            (await s.execute(select(Appointment).where(Appointment.start_at == ist(MONDAY, 18))))
            .scalars()
            .all()
        )
        assert len(n) == 1


async def test_three_sitting_plan_progresses_and_completes(clinic):
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        tpl = (
            await s.execute(select(ScheduleTemplate).where(ScheduleTemplate.name == "Root canal"))
        ).scalar_one()
        sched = await sched_engine.enrol(s, business, rahul, tpl, resource_id=doctor.id)
        assert sched.next_due_date == MONDAY and sched.sessions_total == 3
        a1 = await appt_engine.book(s, business, rahul, doctor.id, ist(MONDAY, 17), schedule_id=sched.id)
        assert a1.session_number == 1 and a1.service == "Root canal (1st sitting)"
        assert a1.end_at - a1.start_at == dt.timedelta(minutes=30)
        sched_id = sched.id
    freeze(MONDAY, 18)
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        a1 = (await s.execute(select(Appointment))).scalars().first()
        await appt_engine.mark(s, business, a1, AppointmentStatus.DONE)
        sched = await s.get(sched_engine.Schedule, sched_id)
        assert sched.sessions_done == 1
        assert sched.next_due_date == MONDAY + dt.timedelta(days=7)
    # rescheduling the plan's booking moves it rather than creating a second
    freeze(MONDAY + dt.timedelta(days=7), 9)
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        d = MONDAY + dt.timedelta(days=7)
        a2 = await appt_engine.book(s, business, rahul, doctor.id, ist(d, 11), schedule_id=sched_id)
        a2b = await appt_engine.book(s, business, rahul, doctor.id, ist(d, 12), schedule_id=sched_id)
        await s.refresh(a2)
        assert a2.status == AppointmentStatus.CANCELLED and a2.cancelled_reason == "rescheduled"
        assert a2b.session_number == 2
    freeze(MONDAY + dt.timedelta(days=7), 13)
    async with session_scope() as s:
        business, *_ = await _load(s, clinic)
        a2b = (await s.execute(select(Appointment).where(Appointment.status == "booked"))).scalar_one()
        await appt_engine.mark(s, business, a2b, AppointmentStatus.MISSED)
        sched = await s.get(sched_engine.Schedule, sched_id)
        assert sched.missed_count == 1 and sched.sessions_done == 1
    freeze(MONDAY + dt.timedelta(days=8), 9)
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        missed = (await s.execute(select(Appointment).where(Appointment.status == "missed"))).scalar_one()
        d = MONDAY + dt.timedelta(days=8)
        a3 = await appt_engine.book(
            s, business, rahul, doctor.id, ist(d, 11), schedule_id=sched_id, rebooked_from=missed
        )
        assert a3.recovered is True
    freeze(MONDAY + dt.timedelta(days=8), 12)
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        a3 = (await s.execute(select(Appointment).where(Appointment.status == "booked"))).scalar_one()
        await appt_engine.mark(s, business, a3, AppointmentStatus.DONE)
        d = MONDAY + dt.timedelta(days=15)
        sched = await s.get(sched_engine.Schedule, sched_id)
        assert sched.next_due_date == MONDAY + dt.timedelta(days=15)
    freeze(MONDAY + dt.timedelta(days=15), 9)
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        d = MONDAY + dt.timedelta(days=15)
        a4 = await appt_engine.book(s, business, rahul, doctor.id, ist(d, 11), schedule_id=sched_id)
        assert a4.service == "Root canal (3rd sitting)"
    freeze(MONDAY + dt.timedelta(days=15), 12)
    async with session_scope() as s:
        business, *_ = await _load(s, clinic)
        a4 = (await s.execute(select(Appointment).where(Appointment.status == "booked"))).scalar_one()
        await appt_engine.mark(s, business, a4, AppointmentStatus.DONE)
        sched = await s.get(sched_engine.Schedule, sched_id)
        assert sched.status == ScheduleStatus.COMPLETED and sched.next_due_date is None
        # correcting the last visit to missed re-opens the plan
        await appt_engine.mark(s, business, a4, AppointmentStatus.MISSED)
        await s.refresh(sched)
        assert sched.status == ScheduleStatus.ACTIVE and sched.sessions_done == 2


async def test_vaccination_offsets_from_birth(clinic):
    async with session_scope() as s:
        business, doctor, rahul, _ = await _load(s, clinic)
        tpl = (
            await s.execute(select(ScheduleTemplate).where(ScheduleTemplate.name == "Vaccination schedule"))
        ).scalar_one()
        born = MONDAY - dt.timedelta(days=40)
        sched = await sched_engine.enrol(s, business, rahul, tpl, anchor_date=born, sessions_done=1)
        assert sched.next_due_date == born + dt.timedelta(days=42)
        assert sched.sessions_total == len(tpl.offsets_days)


async def test_offer_slots_spread_across_days(clinic):
    async with session_scope() as s:
        business, doctor, *_ = await _load(s, clinic)
        slots = await offer_slots(s, business, [doctor], MONDAY)
        days = {clock.to_local(x.start, "Asia/Kolkata").date() for x in slots}
        assert len(slots) == 3 and len(days) == 3
