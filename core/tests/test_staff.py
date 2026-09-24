import datetime as dt

from sqlalchemy import select

from tests.conftest import MONDAY, Clinic, freeze, ist
from tests.helpers import last_log_id, outbox, send
from wam.db import session_scope
from wam.engine import appointments as appt_engine
from wam.models import (
    Appointment,
    AppointmentStatus,
    AuditLog,
    Availability,
    Business,
    Contact,
    Job,
    Schedule,
    Staff,
)


async def _book(clinic, contact_id, when):
    async with session_scope() as s:
        business = await s.get(Business, clinic.business_id)
        contact = await s.get(Contact, contact_id)
        appt = await appt_engine.book(s, business, contact, clinic.doctor_id, when, source="admin")
        return appt.id


async def test_help_and_todays_list(clinic):
    await _book(clinic, clinic.rahul_id, ist(MONDAY, 17))
    await _book(clinic, clinic.anita_id, ist(MONDAY, 18))
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "help")
    assert "Cancel my 5 pm" in replies[0]
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "Today's list")
    assert "1) 5:00 PM Rahul Sharma" in replies[0] and "2) 6:00 PM Anita Desai" in replies[0]
    assert "didn't come" in replies[0]


async def test_cancel_needs_yes_and_pin_then_patient_rebooks(clinic):
    appt_id = await _book(clinic, clinic.rahul_id, ist(MONDAY, 17))
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "Cancel my 5 pm")
    assert "Reply YES and your PIN" in replies[0] and "Rahul Sharma" in replies[0]
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "YES 9999")
    assert "Wrong PIN. 4 tries left" in replies[0]
    async with session_scope() as s:
        assert (await s.get(Appointment, appt_id)).status == AppointmentStatus.BOOKED
    mark = await last_log_id()
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "yes 1234")
    staff_reply = [m for m in await outbox(Clinic.DOCTOR_PHONE, mark)][-1].content
    assert "Cancelled Rahul Sharma's" in staff_reply
    patient_msgs = await outbox(Clinic.RAHUL_PHONE, mark)
    assert len(patient_msgs) == 1
    # Rahul hasn't messaged in 24h -> it goes out as the approved template
    assert patient_msgs[0].template_name == "wam_doctor_unavailable"
    async with session_scope() as s:
        assert (await s.get(Appointment, appt_id)).status == AppointmentStatus.CANCELLED
        audit = (
            await s.execute(select(AuditLog).where(AuditLog.action == "cancel_appointment"))
        ).scalar_one()
        assert audit.phone == Clinic.DOCTOR_PHONE
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "3")
    assert any(r.startswith("Booked:") for r in replies)
    async with session_scope() as s:
        new = (await s.execute(select(Appointment).where(Appointment.status == "booked"))).scalar_one()
        assert new.rebooked_from_id == appt_id


async def test_pin_lockout_after_five_wrong(clinic):
    await _book(clinic, clinic.rahul_id, ist(MONDAY, 17))
    await send(clinic.business_id, Clinic.DOCTOR_PHONE, "cancel 5pm")
    for _ in range(4):
        await send(clinic.business_id, Clinic.DOCTOR_PHONE, "YES 0000")
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "YES 0000")
    assert "locked" in replies[0]
    await send(clinic.business_id, Clinic.DOCTOR_PHONE, "cancel 5pm")
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "YES 1234")
    assert "Too many wrong PINs" in replies[0]


async def test_running_late_tells_next_patients(clinic):
    freeze(MONDAY, 16, 50)
    await _book(clinic, clinic.rahul_id, ist(MONDAY, 17, 30) if False else ist(MONDAY, 18))
    await _book(clinic, clinic.anita_id, ist(MONDAY + dt.timedelta(days=1), 10))  # tomorrow: not told
    mark = await last_log_id()
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "Running 20 min late")
    assert "Told 1" in replies[-1]
    rahul = await outbox(Clinic.RAHUL_PHONE, mark)
    assert rahul and rahul[0].template_name == "wam_running_late"
    assert "20 minutes late" in rahul[0].content


async def test_leave_blocks_day_and_moves_patients(clinic):
    friday = MONDAY + dt.timedelta(days=4)
    appt_id = await _book(clinic, clinic.rahul_id, ist(friday, 10))
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "On leave Friday")
    assert "Block Dr. Mehta on Fri 9 Oct and move 1 booked patients" in replies[0]
    mark = await last_log_id()
    replies = await send(clinic.business_id, Clinic.DOCTOR_PHONE, "YES 1234")
    assert "Blocked Dr. Mehta on Fri 9 Oct" in replies[-1]
    async with session_scope() as s:
        assert (await s.get(Appointment, appt_id)).status == AppointmentStatus.CANCELLED
        leave = (await s.execute(select(Availability).where(Availability.kind == "leave"))).scalar_one()
        assert leave.start_at == ist(friday, 0)
    offered = await outbox(Clinic.RAHUL_PHONE, mark)
    assert offered and "Fri 9 Oct" not in offered[0].content.split("New slots")[-1]


async def test_enrol_and_nudge_then_followup(clinic):
    mark = await last_log_id()
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Rahul, root canal")
    assert "Enrolled Rahul Sharma in Root canal (3 visits)" in replies[-1]
    assert "sent Rahul Sharma 3 free slots" in replies[-1]
    nudges = await outbox(Clinic.RAHUL_PHONE, mark)
    assert nudges[0].template_name == "wam_session_due"
    # new patient with number
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Karan 98444 55555, laser")
    assert "Enrolled Karan in Laser or peel course (6 visits)" in replies[-1]
    # already on the plan
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Rahul, root canal")
    assert "already on 'Root canal'" in replies[-1]
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Follow-up for Anita in 7 days")
    assert "I'll message Anita Desai on Mon 12 Oct" in replies[-1]
    async with session_scope() as s:
        sched = (await s.execute(select(Schedule).where(Schedule.contact_id == clinic.anita_id))).scalar_one()
        assert sched.next_due_date == MONDAY + dt.timedelta(days=7)
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Rahul, root canal, 1 done")
    assert "already" in replies[-1]
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Nobody, root canal")
    assert "don't have a patient called Nobody" in replies[-1]


async def test_vaccination_enrol_for_child_via_parent_phone(clinic):
    replies = await send(
        clinic.business_id, Clinic.DESK_PHONE, "Aarav 98555 66666, vaccination, born 24/08/2026"
    )
    assert "Enrolled Aarav in Vaccination schedule" in replies[-1]
    async with session_scope() as s:
        kid = (await s.execute(select(Contact).where(Contact.name == "Aarav"))).scalar_one()
        assert kid.phone is None and kid.guardian is not None and kid.guardian.phone == "+919855566666"
        sched = (await s.execute(select(Schedule).where(Schedule.contact_id == kid.id))).scalar_one()
        # born 24 Aug: birth dose long past -> skipped; 6-week dose due 5 Oct (today)
        assert sched.sessions_done == 1 and sched.next_due_date == MONDAY


async def test_attendance_reply_marks_done_and_missed_and_schedules_followup(clinic):
    a1 = await _book(clinic, clinic.rahul_id, ist(MONDAY, 10))
    a2 = await _book(clinic, clinic.anita_id, ist(MONDAY, 11))
    a3 = await _book(clinic, clinic.anita_id, ist(MONDAY, 19))
    freeze(MONDAY, 13, 30)
    await send(clinic.business_id, Clinic.DESK_PHONE, "today's list")
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "2")
    assert "Marked 1 as came, 1 missed (Anita Desai)" in replies[0]
    async with session_scope() as s:
        assert (await s.get(Appointment, a1)).status == "done"
        assert (await s.get(Appointment, a2)).status == "missed"
        assert (await s.get(Appointment, a3)).status == "booked"  # not reached yet
        job = (await s.execute(select(Job).where(Job.kind == "missed_followup"))).scalar_one()
        assert job.payload["appointment_id"] == a2
        assert job.run_at == ist(MONDAY + dt.timedelta(days=1), 11)
    # correction: actually nobody missed
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "none")
    async with session_scope() as s:
        assert (await s.get(Appointment, a2)).status == "done"
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "9")
    assert "only has numbers 1 to 3" in replies[0]


async def test_role_permissions(clinic):
    async with session_scope() as s:
        desk = await s.get(Staff, clinic.desk_staff_id)
        desk.role_id = None
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "on leave friday")
    assert "your role can't do that" in replies[0]
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "gibberish words here")
    assert "Reply HELP" in replies[0]


async def test_enrol_outside_send_window_defers_nudge_to_morning(clinic):
    from tests.helpers import tick

    freeze(MONDAY, 22, 30)
    mark = await last_log_id()
    replies = await send(clinic.business_id, Clinic.DESK_PHONE, "Anita, cleaning")
    assert "I'll send Anita Desai free slots at 10:00 AM tomorrow" in replies[-1]
    assert await outbox(Clinic.ANITA_PHONE, mark) == []
    freeze(MONDAY + dt.timedelta(days=1), 10, 1)
    assert (await tick(clinic.business_id))["nudges"] == 1
    assert (await outbox(Clinic.ANITA_PHONE, mark))[0].template_name == "wam_recall"
