"""Week-4 'done when': a 3-sitting plan runs end to end, including a missed visit."""

import datetime as dt

from sqlalchemy import select

from tests.conftest import MONDAY, Clinic, freeze, ist
from tests.helpers import last_log_id, outbox, send, tick
from wam.db import session_scope
from wam.models import Appointment, AppointmentStatus, Contact, Schedule, ScheduleStatus


def day(n: int) -> dt.date:
    return MONDAY + dt.timedelta(days=n)


async def _only_active(contact_id: int) -> Appointment:
    async with session_scope() as s:
        return (
            await s.execute(
                select(Appointment).where(
                    Appointment.contact_id == contact_id, Appointment.status.in_(AppointmentStatus.ACTIVE)
                )
            )
        ).scalar_one()


async def test_three_sitting_root_canal_with_a_missed_visit(clinic):
    bid = clinic.business_id

    # 1. Enrol (Monday 09:00): sitting 1 due today -> Rahul gets 3 slots
    replies = await send(bid, Clinic.DESK_PHONE, "Rahul, root canal")
    assert "sent Rahul Sharma 3 free slots" in replies[-1]
    replies = await send(bid, Clinic.RAHUL_PHONE, "2")  # option 2 = Tuesday 10:00
    booked = [r for r in replies if r.startswith("Booked:")]
    assert booked and "Root canal (1st sitting)" in booked[0]
    a1 = await _only_active(clinic.rahul_id)

    # 2. Day-before reminder: the booking is on a later day; tick at 10:00 the day before
    visit_day = a1.start_at.astimezone(ist(MONDAY, 0).tzinfo).date()
    assert visit_day == MONDAY + dt.timedelta(days=1)
    if True:
        freeze(visit_day - dt.timedelta(days=1), 10, 5)
        # booked at 09:00 today: the confirmation is fresh, so no reminder yet
        assert (await tick(bid))["reminders"] == 0
        freeze(visit_day - dt.timedelta(days=1), 15, 5)
        mark = await last_log_id()
        result = await tick(bid)
        assert result["reminders"] == 1
        reminder = (await outbox(Clinic.RAHUL_PHONE, mark))[0]
        assert "Reply 1 to confirm or 2 to reschedule" in reminder.content
        assert (await tick(bid))["reminders"] == 0  # idempotent
        replies = await send(bid, Clinic.RAHUL_PHONE, "1")
        assert replies[0].startswith("Thanks, confirmed!")

    # 3. End-of-day check on the visit day at 20:00 -> front desk replies "none" -> done
    freeze(visit_day, 20, 1)
    mark = await last_log_id()
    assert (await tick(bid))["eod"] is True
    eod = await outbox(Clinic.DESK_PHONE, mark)
    # the desk hasn't messaged in 24h, so the check goes out as the staff template
    assert eod and eod[0].template_name == "wam_staff_alert" and "Reply LIST" in eod[0].content
    assert (await tick(bid))["eod"] is False  # once a day
    replies = await send(bid, Clinic.DESK_PHONE, "list")
    assert "1) 10:00 AM Rahul Sharma – Root canal (1st sitting) ✓" in replies[0]
    replies = await send(bid, Clinic.DESK_PHONE, "none")
    assert "Marked 1 as came" in replies[0]

    async with session_scope() as s:
        sched = (await s.execute(select(Schedule))).scalar_one()
        assert sched.sessions_done == 1
        due2 = sched.next_due_date
    assert due2 == visit_day + dt.timedelta(days=7)

    # 4. Nudge on the due date for sitting 2 (template, window closed)
    freeze(due2, 10, 1)
    mark = await last_log_id()
    assert (await tick(bid))["nudges"] == 1
    nudge = (await outbox(Clinic.RAHUL_PHONE, mark))[0]
    assert nudge.template_name == "wam_session_due" and "Root canal (2nd sitting)" in nudge.content
    assert (await tick(bid))["nudges"] == 0  # not twice
    replies = await send(bid, Clinic.RAHUL_PHONE, "2")
    assert any("Root canal (2nd sitting)" in r for r in replies)
    a2 = await _only_active(clinic.rahul_id)

    # 5. He misses sitting 2: marked missed at the end-of-day check
    visit2 = a2.start_at.astimezone(ist(MONDAY, 0).tzinfo).date()
    freeze(visit2, 20, 1)
    await tick(bid)
    replies = await send(bid, Clinic.DESK_PHONE, "1")
    assert "1 missed (Rahul Sharma)" in replies[0]

    # 6. Follow-up 24h after the visit, with slots; Rahul rebooks -> a recovered visit
    freeze(visit2 + dt.timedelta(days=1), 20, 30)  # outside send window -> postponed
    assert (await tick(bid))["jobs"] == 0
    freeze(visit2 + dt.timedelta(days=2), 9, 1)
    mark = await last_log_id()
    await tick(bid)
    follow = [m for m in await outbox(Clinic.RAHUL_PHONE, mark) if m.template_name == "wam_missed_followup"]
    assert len(follow) == 1 and "we missed you" in follow[0].content
    replies = await send(bid, Clinic.RAHUL_PHONE, "1")
    assert any(r.startswith("Booked:") and "2nd sitting" in r for r in replies)
    a2b = await _only_active(clinic.rahul_id)
    assert a2b.recovered is True and a2b.session_number == 2

    # 7. Came for the recovered visit and for sitting 3 -> plan completed
    v = a2b.start_at.astimezone(ist(MONDAY, 0).tzinfo).date()
    freeze(v, 20, 1)
    await tick(bid)
    await send(bid, Clinic.DESK_PHONE, "none")
    async with session_scope() as s:
        sched = (await s.execute(select(Schedule))).scalar_one()
        due3 = sched.next_due_date
        assert sched.sessions_done == 2
    freeze(due3, 10, 1)
    await tick(bid)
    await send(bid, Clinic.RAHUL_PHONE, "1")
    a3 = await _only_active(clinic.rahul_id)
    assert a3.service == "Root canal (3rd sitting)"
    v3 = a3.start_at.astimezone(ist(MONDAY, 0).tzinfo).date()
    freeze(v3, 20, 1)
    await tick(bid)
    await send(bid, Clinic.DESK_PHONE, "none")
    async with session_scope() as s:
        sched = (await s.execute(select(Schedule))).scalar_one()
        assert sched.status == ScheduleStatus.COMPLETED
        # no stray follow-up for the missed visit after he rebooked
    freeze(v3 + dt.timedelta(days=3), 10, 1)
    mark = await last_log_id()
    await tick(bid)
    assert [m for m in await outbox(Clinic.RAHUL_PHONE, mark)] == []
    # exactly one missed-visit follow-up: the second try was skipped because he had rebooked
    followups = [m for m in await outbox(Clinic.RAHUL_PHONE) if m.template_name == "wam_missed_followup"]
    assert len(followups) == 1


async def test_unanswered_nudges_flag_patient_to_staff(clinic):
    bid = clinic.business_id
    await send(bid, Clinic.DESK_PHONE, "Anita, cleaning")
    for i in range(1, 4):  # first nudge at enrolment, re-nudges after 3+ days, flag after the 3rd
        freeze(MONDAY + dt.timedelta(days=4 * i), 10, 1)
        await tick(bid)
    async with session_scope() as s:
        sched = (await s.execute(select(Schedule))).scalar_one()
        assert sched.nudge_count == 3 and sched.needs_staff is True
        anita = await s.get(Contact, clinic.anita_id)
        assert anita.needs_staff is True
    desk = await outbox(Clinic.DESK_PHONE)
    assert any("Please call Anita Desai" in (m.content or "") for m in desk)


async def test_second_followup_then_flag(clinic):
    bid = clinic.business_id
    await send(bid, Clinic.DESK_PHONE, "Rahul, physio")
    await send(bid, Clinic.RAHUL_PHONE, "1")
    appt = await _only_active(clinic.rahul_id)
    vday = appt.start_at.astimezone(ist(MONDAY, 0).tzinfo).date()
    freeze(vday, 20, 1)
    await tick(bid)
    await send(bid, Clinic.DESK_PHONE, "1")
    for hours in (26, 26 + 48, 26 + 96):
        clock_time = appt.start_at + dt.timedelta(hours=hours)
        freeze(clock_time.astimezone(ist(MONDAY, 0).tzinfo).date(), 10, 1)
        await tick(bid)
    async with session_scope() as s:
        a = await s.get(Appointment, appt.id)
        assert a.followup_count == 3
        rahul = await s.get(Contact, clinic.rahul_id)
        assert rahul.needs_staff is True
    msgs = await outbox(Clinic.RAHUL_PHONE)
    assert len([m for m in msgs if m.template_name == "wam_missed_followup"]) == 2
