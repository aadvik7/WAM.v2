"""Institute pack (version 2): batches, announcements, doubts, uploads, timetable, PTM, fees."""

from __future__ import annotations

import datetime as dt
import io
import json
from dataclasses import dataclass

import httpx
import pytest
import respx
from openpyxl import Workbook
from sqlalchemy import select

from tests.conftest import MONDAY, freeze, ist
from tests.helpers import last_log_id, outbox, send, tick
from wam.cli import create_admin
from wam.config import get_settings
from wam.db import get_sessionmaker, session_scope
from wam.main import app
from wam.models import (
    Appointment,
    Availability,
    Broadcast,
    BroadcastRecipient,
    Business,
    Contact,
    Doubt,
    Group,
    Resource,
    Role,
    Schedule,
    ScheduleTemplate,
    Staff,
    Subject,
)
from wam.packs import seed_business
from wam.packs.institute import batches as batch_mod
from wam.packs.institute import broadcasts
from wam.packs.institute.commands import parse
from wam.security import hash_secret

COORD = "+919700000001"
TEACHER = "+919700000002"
DESK = "+919700000003"
AARAV = "+919711111111"
AARAV_MOM = "+919722222222"
AARAV_DAD = "+919733333333"
DIYA_PARENT = "+919744444444"
KABIR = "+919755555555"
KABIR_PARENT = "+919766666666"


@dataclass
class Institute:
    business_id: int
    neet_id: int
    jee_id: int
    teacher_resource_id: int
    aarav_id: int
    diya_id: int


@pytest.fixture
async def inst() -> Institute:
    sm = get_sessionmaker()
    async with sm() as s:
        business = Business(
            name="Bright Future Academy", type="institute", timezone="Asia/Kolkata", settings={}
        )
        s.add(business)
        await s.flush()
        await seed_business(s, business)
        roles = {
            r.name: r
            for r in (await s.execute(select(Role).where(Role.business_id == business.id))).scalars()
        }
        coord = Staff(
            business_id=business.id,
            name="Meera",
            phone=COORD,
            role_id=roles["coordinator"].id,
            pin_hash=hash_secret("1111"),
            receives_eod_list=True,
        )
        teacher = Staff(
            business_id=business.id,
            name="Mr. Rao",
            phone=TEACHER,
            role_id=roles["teacher"].id,
            pin_hash=hash_secret("2222"),
        )
        desk = Staff(
            business_id=business.id,
            name="Office",
            phone=DESK,
            role_id=roles["front_desk"].id,
            pin_hash=hash_secret("3333"),
        )
        s.add_all([coord, teacher, desk])
        await s.flush()
        resource = Resource(
            business_id=business.id,
            name="Mr. Rao",
            kind="teacher",
            specialty="Institute",
            slot_minutes=30,
            staff_id=teacher.id,
        )
        s.add(resource)
        s.add_all(
            [
                Subject(business_id=business.id, name="Physics", aliases=["phy"], chatwoot_team_id=3),
                Subject(business_id=business.id, name="Chemistry", aliases=["chem"], chatwoot_team_id=4),
            ]
        )
        await s.flush()
        neet = await batch_mod.get_or_create_batch(s, business, "NEET-A2")
        jee = await batch_mod.get_or_create_batch(s, business, "JEE-B1")
        await batch_mod.set_batch_teachers(s, neet, [teacher.id])
        aarav, _, _ = await batch_mod.upsert_student(
            s,
            business,
            batch_mod.StudentInput(
                name="Aarav Shah",
                roll="12",
                phone=AARAV,
                parent_phones=(AARAV_MOM, AARAV_DAD),
                parent_names=("Sunita", "Raj"),
            ),
        )
        diya, _, _ = await batch_mod.upsert_student(
            s, business, batch_mod.StudentInput(name="Diya Nair", roll="15", parent_phones=(DIYA_PARENT,))
        )
        kabir, _, _ = await batch_mod.upsert_student(
            s,
            business,
            batch_mod.StudentInput(name="Kabir Das", roll="7", phone=KABIR, parent_phones=(KABIR_PARENT,)),
        )
        await batch_mod.add_to_batch(s, neet, aarav)
        await batch_mod.add_to_batch(s, neet, diya)
        await batch_mod.add_to_batch(s, jee, kabir)
        await s.commit()
        return Institute(business.id, neet.id, jee.id, resource.id, aarav.id, diya.id)


def _xlsx(rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as c:
        await create_admin("owner@academy.test", "academy-pass-1", None, None)
        r = await c.post(
            "/api/auth/login", json={"email": "owner@academy.test", "password": "academy-pass-1"}
        )
        c.headers["Authorization"] = f"Bearer {r.json()['token']}"
        yield c


# --------------------------------------------------------------------------------------


def test_parser():
    assert parse("Send to NEET-A2: Tomorrow's class starts at 8 AM").args == {
        "target": "NEET-A2",
        "message": "Tomorrow's class starts at 8 AM",
    }
    assert parse("send to neet a2 parents: fees due\nthanks").args["message"] == "fees due\nthanks"
    assert parse("Absent NEET-A2 Physics: 12, 15").args == {"target": "NEET-A2 Physics", "list": "12, 15"}
    assert parse("Aarav paid").args == {"who": "Aarav"}
    assert parse("paid 12").args == {"who": "12"}
    assert parse("fees received from Diya Nair").args == {"who": "Diya Nair"}
    assert parse("announcement status").key == "announce_status"
    assert parse("my batches").key == "my_batches"
    assert parse("today's list") is None


async def test_student_links_and_batches(inst):
    async with session_scope() as s:
        aarav = await s.get(Contact, inst.aarav_id)
        summary = await batch_mod.student_summary(s, aarav)
        assert summary["roll"] == "12" and [p["phone"] for p in summary["parents"]] == [AARAV_MOM, AARAV_DAD]
        business = await s.get(Business, inst.business_id)
        # a third parent number is refused; re-upserting is idempotent
        _, created, notes = await batch_mod.upsert_student(
            s, business, batch_mod.StudentInput(roll="12", parent_phones=("+919799999999",))
        )
        assert created is False and "already has 2 parent numbers" in notes[0]
        # a student using a parent's phone is reached through the parent
        riya, _, _ = await batch_mod.upsert_student(
            s,
            business,
            batch_mod.StudentInput(name="Riya", roll="30", phone=DIYA_PARENT, parent_phones=(DIYA_PARENT,)),
        )
        assert riya.phone is None


async def test_announcement_with_yes_pin_to_each_person(inst):
    bid = inst.business_id
    replies = await send(
        bid, COORD, "Send to NEET-A2: Tomorrow's class starts at 8 AM, 10 min late start is fine."
    )
    assert "4 people (1 students, 3 parents)" in replies[0]
    assert (
        "\"Update for NEET-A2: Tomorrow's class starts at 8 AM, 10 min late start is fine. Reply here"
        in replies[0]
    )
    assert "1 students have no number" not in replies[0]
    mark = await last_log_id()
    replies = await send(bid, COORD, "YES 1111")
    assert "Sending to 4 people" in replies[-1]
    await tick(bid)
    for phone in (AARAV, AARAV_MOM, AARAV_DAD, DIYA_PARENT):
        msgs = await outbox(phone, mark)
        assert len(msgs) == 1 and msgs[0].template_name == "wam_announcement", phone
    assert await outbox(KABIR, mark) == []
    async with session_scope() as s:
        b = (await s.execute(select(Broadcast))).scalar_one()
        assert b.status == "sent" and b.sent_count == 4 and b.recipients_count == 4
    done = [m for m in await outbox(COORD, mark) if "sent to 4 of 4" in (m.content or "")]
    assert done
    replies = await send(bid, COORD, "announcement status")
    assert "4 of 4 sent" in replies[0]


async def test_announcement_permissions(inst):
    bid = inst.business_id
    replies = await send(bid, TEACHER, "Send to JEE-B1: hello")
    assert "only message your own batches (NEET-A2)" in replies[0]
    replies = await send(bid, TEACHER, "Send to NEET-A2 parents: PTM next week")
    assert "3 people (3 parents)" in replies[0]
    replies = await send(bid, DESK, "Send to NEET-A2: hi")
    assert "your role can't do that" in replies[0]
    replies = await send(bid, COORD, "Send to MBA-X: hi")
    assert "don't know the batch" in replies[0]
    replies = await send(bid, TEACHER, "my batches")
    assert "NEET-A2" in replies[0]


async def test_read_counts_from_chatwoot(inst, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "chatwoot_base_url", "http://cw.test")
    monkeypatch.setattr(settings, "chatwoot_api_token", "tok")
    async with session_scope() as s:
        business = await s.get(Business, inst.business_id)
        business.chatwoot_account_id, business.chatwoot_inbox_id = 1, 5
        group = await s.get(Group, inst.neet_id)
        b = await broadcasts.create_broadcast(s, business, group, "Holiday tomorrow", "everyone")
        b.status = "sent"
        rows = (await s.execute(select(BroadcastRecipient))).scalars().all()
        for i, r in enumerate(rows):
            r.status, r.chatwoot_conversation_id, r.chatwoot_message_id = "sent", 100 + i, 500 + i
        bid = b.id
    statuses = ["read", "delivered", "failed", "sent"]
    with respx.mock() as mock:
        for i, st in enumerate(statuses):
            mock.get(f"http://cw.test/api/v1/accounts/1/conversations/{100 + i}/messages").mock(
                return_value=httpx.Response(
                    200, json={"meta": {}, "payload": [{"id": 500 + i, "status": st}]}
                )
            )
        async with session_scope() as s:
            business = await s.get(Business, inst.business_id)
            b = await s.get(Broadcast, bid)
            changed = await broadcasts.refresh_status(s, business, b)
            assert changed == 3
            assert (b.sent_count, b.delivered_count, b.read_count, b.failed_count) == (3, 2, 1, 1)


async def test_doubt_goes_to_subject_team(inst, monkeypatch):
    bid = inst.business_id
    settings = get_settings()
    monkeypatch.setattr(settings, "chatwoot_base_url", "http://cw.test")
    monkeypatch.setattr(settings, "chatwoot_api_token", "tok")
    async with session_scope() as s:
        business = await s.get(Business, bid)
        business.chatwoot_account_id, business.chatwoot_inbox_id = 1, 5
        aarav = await s.get(Contact, inst.aarav_id)
        aarav.chatwoot_conversation_id = 77
        aarav.consent_notice_sent_at = aarav.consent_at = ist(MONDAY, 8)
    with respx.mock(assert_all_called=False) as mock:
        msgs = mock.post("http://cw.test/api/v1/accounts/1/conversations/77/messages").mock(
            return_value=httpx.Response(200, json={"id": 1})
        )
        assign = mock.post("http://cw.test/api/v1/accounts/1/conversations/77/assignments").mock(
            return_value=httpx.Response(200, json={})
        )
        mock.post("http://cw.test/api/v1/accounts/1/conversations/77/toggle_status").mock(
            return_value=httpx.Response(200, json={})
        )
        labels = mock.post("http://cw.test/api/v1/accounts/1/conversations/77/labels").mock(
            return_value=httpx.Response(200, json={})
        )
        replies = await send(bid, AARAV, "Doubt: phy - why does current flow from + to -?")
        assert "Physics doubt is with the Physics teachers" in replies[0]
        assert json.loads(assign.calls[0].request.content) == {"team_id": 3}
        assert json.loads(labels.calls[0].request.content) == {"labels": ["doubt", "physics"]}
        notes = [
            json.loads(c.request.content) for c in msgs.calls if json.loads(c.request.content).get("private")
        ]
        assert "Physics doubt from Aarav Shah (NEET-A2)" in notes[0]["content"]
    async with session_scope() as s:
        doubt = (await s.execute(select(Doubt))).scalar_one()
        assert doubt.status == "open" and doubt.subject.name == "Physics" and doubt.group_id == inst.neet_id
        assert (await s.get(Contact, inst.aarav_id)).needs_staff is True


async def test_doubt_asks_for_subject_then_resolves(inst):
    bid = inst.business_id
    await send(bid, KABIR, "hello")
    replies = await send(bid, KABIR, "doubt: what is the answer to question 4?")
    assert "Which subject" in replies[0] and "Chemistry, Physics" in replies[0]
    replies = await send(bid, KABIR, "chem")
    assert "Chemistry doubt" in replies[0]
    async with session_scope() as s:
        doubt = (await s.execute(select(Doubt))).scalar_one()
        assert doubt.question == "what is the answer to question 4?" and doubt.subject.name == "Chemistry"
        kabir = (await s.execute(select(Contact).where(Contact.phone == KABIR))).scalar_one()
        business = await s.get(Business, bid)
        from wam.packs.institute.hooks import on_conversation_resolved

        await on_conversation_resolved(s, business, kabir)
        assert doubt.status == "closed"


async def test_absent_command_alerts_parents(inst):
    bid = inst.business_id
    replies = await send(bid, TEACHER, "Absent NEET-A2 Physics: 12, 15, 99")
    assert "Aarav Shah (12), Diya Nair (15)" in replies[0] and "Not found: 99" in replies[0]
    mark = await last_log_id()
    replies = await send(bid, TEACHER, "YES 2222")
    assert "parents of 2 students" in replies[-1]
    await tick(bid)
    for phone in (AARAV_MOM, AARAV_DAD, DIYA_PARENT):
        msgs = await outbox(phone, mark)
        assert msgs[0].template_name == "wam_absence_alert"
        assert "was marked absent in Physics today" in msgs[0].content
    assert await outbox(AARAV, mark) == []  # the student themself isn't messaged, the parents are
    replies = await send(bid, TEACHER, "Absent JEE-B1 Maths: 7")
    assert "only message your own batches" in replies[0]


async def test_uploads_students_attendance_results_timetable(inst, client):
    B = f"/api/businesses/{inst.business_id}/institute"
    # students (CSV)
    csv = (
        "Roll No,Student Name,Mobile,Father Mobile,Mother Mobile,Batch\n"
        "21,Ishaan Gupta,9811100021,9811100022,,NEET-A2\n"
        "22,Tara Singh,,9811100032,9811100033,Foundation-9\n"
        ",,,,,\n"
        "23,No Number,,,,NEET-A2\n"
    )
    r = await client.post(
        f"{B}/uploads", data={"kind": "students"}, files={"file": ("students.csv", csv.encode())}
    )
    assert r.status_code == 201, r.text
    up = r.json()
    assert up["summary"]["new"] == 2 and up["summary"]["errors"] == 1
    assert up["summary"]["batches"] == ["Foundation-9", "NEET-A2"]
    r = await client.post(f"{B}/uploads/{up['id']}/apply")
    assert r.json()["result"]["created"] == 2
    batches = {b["name"]: b for b in (await client.get(f"{B}/batches")).json()}
    assert batches["NEET-A2"]["students"] == 3 and batches["Foundation-9"]["students"] == 1
    detail = (await client.get(f"{B}/batches/{batches['Foundation-9']['id']}")).json()
    assert [p["phone"] for p in detail["students"][0]["parents"]] == ["+919811100032", "+919811100033"]

    # attendance (Excel, P/A column)
    data = _xlsx(
        [
            ["Roll No.", "Name", "Status"],
            [12, "Aarav Shah", "A"],
            [15, "Diya Nair", "P"],
            [21, "Ishaan", "Absent"],
            [99, "?", "A"],
        ]
    )
    r = await client.post(
        f"{B}/uploads",
        data={"kind": "attendance", "label": "Chemistry", "group_id": str(inst.neet_id)},
        files={"file": ("att.xlsx", data)},
    )
    assert r.status_code == 201, r.text
    summary = r.json()["summary"]
    assert (summary["absent"], summary["present"], summary["unmatched"], summary["messages"]) == (2, 1, 1, 3)
    mark = await last_log_id()
    await client.post(f"{B}/uploads/{r.json()['id']}/apply")
    await tick(inst.business_id)
    alerts = [m for m in await outbox(since_id=mark) if m.template_name == "wam_absence_alert"]
    assert sorted(m.phone for m in alerts) == sorted([AARAV_MOM, AARAV_DAD, "+919811100022"])
    assert "in Chemistry today" in alerts[0].content

    # results (Excel with max marks)
    data = _xlsx([["Roll", "Marks", "Out of"], [12, 82, 100], [15, 91, 100]])
    r = await client.post(
        f"{B}/uploads",
        data={"kind": "results", "label": "Physics unit test 3"},
        files={"file": ("res.xlsx", data)},
    )
    assert r.json()["summary"]["scores"] == 2
    mark = await last_log_id()
    await client.post(f"{B}/uploads/{r.json()['id']}/apply")
    await tick(inst.business_id)
    diya = await outbox(DIYA_PARENT, mark)
    assert (
        diya[0].template_name == "wam_test_result"
        and "Diya scored 91/100 in Physics unit test 3" in diya[0].content
    )

    # timetable (weekly + a dated override)
    tuesday = MONDAY + dt.timedelta(days=1)
    data = _xlsx(
        [
            ["Batch", "Day", "Date", "Start", "End", "Subject", "Teacher", "Room"],
            ["NEET-A2", "Tue", None, "8:00 AM", "9:30 AM", "Physics", "Mr. Rao", "2"],
            ["NEET-A2", "Tuesday", None, "10:00", "11:30", "Chemistry", "Ms. Iyer", "2"],
            [
                "NEET-A2",
                None,
                (MONDAY + dt.timedelta(days=8)).isoformat(),
                "9:00",
                "12:00",
                "Mock test",
                None,
                "Hall",
            ],
            ["MBA-X", "Mon", None, "9:00", "10:00", "Economics", None, None],
        ]
    )
    r = await client.post(f"{B}/uploads", data={"kind": "timetable"}, files={"file": ("tt.xlsx", data)})
    assert r.json()["summary"]["entries"] == 3 and r.json()["summary"]["errors"] == 1
    await client.post(f"{B}/uploads/{r.json()['id']}/apply")
    replies = await send(inst.business_id, AARAV, "what's my timetable tomorrow?")
    text = replies[-1]
    assert f"NEET-A2 — {tuesday.strftime('%a')} {tuesday.day} Oct:" in text
    assert "8:00 AM–9:30 AM Physics (Mr. Rao, 2)" in text and "Chemistry" in text
    # the parent asking gets the child's timetable; the dated entry replaces next Tuesday's plan
    replies = await send(
        inst.business_id, DIYA_PARENT, f"timetable {(MONDAY + dt.timedelta(days=8)).strftime('%d/%m')}"
    )
    assert "9:00 AM–12:00 PM Mock test (Hall)" in replies[-1] and "Physics" not in replies[-1]
    assert (await client.get(f"{B}/timetable", params={"group_id": inst.neet_id})).json()[0]["subject"]


async def test_ptm_booking_by_parents(inst, client):
    B = f"/api/businesses/{inst.business_id}/institute"
    saturday = MONDAY + dt.timedelta(days=5)
    r = await client.post(
        f"{B}/ptm",
        json={
            "group_id": inst.neet_id,
            "date": saturday.isoformat(),
            "start": "10:00",
            "end": "11:00",
            "resource_ids": [inst.teacher_resource_id],
            "slot_minutes": 10,
        },
    )
    assert r.status_code == 201, r.text
    invite = r.json()["invite"]
    assert invite["audience"] == "parents" and invite["recipients"] == 3
    assert "Reply PTM to book a 10-minute slot" in invite["preview"]
    mark = await last_log_id()
    await client.post(f"{B}/broadcasts/{invite['id']}/send")
    await tick(inst.business_id)
    assert (await outbox(AARAV_MOM, mark))[0].template_name == "wam_announcement"
    replies = await send(inst.business_id, AARAV_MOM, "PTM")
    assert "1) 10:00 AM with Mr. Rao" in replies[-1] and "2) 10:10 AM with Mr. Rao" in replies[-1]
    replies = await send(inst.business_id, AARAV_MOM, "2")
    assert replies[-1].startswith("Booked: Parent-teacher meeting with Mr. Rao, Sat 10 Oct at 10:10 AM")
    replies = await send(inst.business_id, DIYA_PARENT, "ptm")
    assert "10:10" not in replies[-1] and "1) 10:00 AM" in replies[-1]
    replies = await send(inst.business_id, AARAV_MOM, "ptm")
    assert "already booked" in replies[-1]
    events = (await client.get(f"{B}/ptm")).json()
    assert events[0]["booked"] == 1 and events[0]["free"] == 5
    async with session_scope() as s:
        appt = (await s.execute(select(Appointment))).scalar_one()
        assert appt.end_at - appt.start_at == dt.timedelta(minutes=10)
        assert (await s.execute(select(Availability).where(Availability.kind == "extra"))).scalar_one()
    assert (await client.delete(f"{B}/ptm/{events[0]['id']}")).status_code == 204


async def test_fee_installments(inst, client):
    bid = inst.business_id
    async with session_scope() as s:
        fee = (
            await s.execute(select(ScheduleTemplate).where(ScheduleTemplate.name == "Fee installments"))
        ).scalar_one()
        assert fee.kind == "payment"
        fee_id = fee.id
    due = MONDAY + dt.timedelta(days=5)
    r = await client.post(
        f"/api/businesses/{bid}/contacts/{inst.aarav_id}/schedules",
        json={"template_id": fee_id, "anchor_date": due.isoformat(), "amount": "12000"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["next_due_date"] == due.isoformat() and r.json()["kind"] == "payment"
    assert r.json()["amount"] == 12000.0 and r.json()["nudged"] is False
    freeze(MONDAY, 10, 1)
    assert (await tick(bid))["payment_reminders"] == 0  # due in 5 days; reminders start 3 days before
    freeze(MONDAY + dt.timedelta(days=2), 10, 1)
    mark = await last_log_id()
    assert (await tick(bid))["payment_reminders"] == 1
    mom = await outbox(AARAV_MOM, mark)
    assert (
        mom[0].template_name == "wam_fee_reminder"
        and "Installment of ₹12,000 is due on Sat 10 Oct" in mom[0].content
    )
    assert len(await outbox(AARAV_DAD, mark)) == 1 and await outbox(AARAV, mark) == []
    assert (await tick(bid))["payment_reminders"] == 0
    freeze(due, 10, 1)
    assert (await tick(bid))["payment_reminders"] == 1  # due-day reminder
    today = (await client.get(f"/api/businesses/{bid}/today")).json()
    assert [f["template"] for f in today["fees_due"]] == ["Fee installments"] and today["due_unbooked"] == []
    replies = await send(bid, AARAV_MOM, "when are the fees due?")
    assert "installment 1 of 4 of ₹12,000 is due on Sat 10 Oct" in replies[-1]
    replies = await send(bid, AARAV_MOM, "we have already paid the fees")
    assert "Our office will check" in replies[-1]
    assert any("says fees are paid" in (m.content or "") for m in await outbox(COORD))
    replies = await send(bid, DESK, "Aarav paid")
    assert "Recorded installment 1 for Aarav Shah. Next installment is due on Mon 9 Nov" in replies[0]
    async with session_scope() as s:
        sched = (await s.execute(select(Schedule))).scalar_one()
        assert sched.sessions_done == 1 and sched.next_due_date == due + dt.timedelta(days=30)
    r = await client.post(f"/api/businesses/{bid}/schedules/{sched.id}/payment")
    assert r.json()["sessions_done"] == 2
    # fee plans are never offered as bookable visits
    replies = await send(bid, TEACHER, "Aarav paid")
    assert "your role can't do that" in replies[0]


async def test_fee_enrol_by_whatsapp(inst):
    replies = await send(inst.business_id, DESK, "Diya, fees")
    assert "Diya Nair" in replies[0] and "Fee installments" in replies[0], replies
    async with session_scope() as s:
        sched = (await s.execute(select(Schedule))).scalar_one()
        assert sched.contact_id == inst.diya_id and sched.template.kind == "payment"


async def test_fee_plan_first_due_and_moved_installment(inst, client):
    bid = inst.business_id
    async with session_scope() as s:
        fee_id = (
            await s.execute(select(ScheduleTemplate.id).where(ScheduleTemplate.name == "Fee installments"))
        ).scalar_one()
    first = MONDAY + dt.timedelta(days=10)
    r = await client.post(
        f"/api/businesses/{bid}/contacts/{inst.diya_id}/schedules",
        json={"template_id": fee_id, "sessions_done": 1, "first_due": first.isoformat()},
    )
    assert r.status_code == 201, r.text
    sched = r.json()
    assert sched["next_due_date"] == first.isoformat() and sched["sessions_done"] == 1
    r = await client.post(f"/api/businesses/{bid}/schedules/{sched['id']}/payment")
    assert r.json()["next_due_date"] == (first + dt.timedelta(days=30)).isoformat()
    # moving one installment moves the ones after it
    moved = first + dt.timedelta(days=35)
    r = await client.patch(
        f"/api/businesses/{bid}/schedules/{sched['id']}", json={"next_due_date": moved.isoformat()}
    )
    assert r.json()["next_due_date"] == moved.isoformat()
    r = await client.post(f"/api/businesses/{bid}/schedules/{sched['id']}/payment")
    assert r.json()["next_due_date"] == (moved + dt.timedelta(days=30)).isoformat()
    # the student page shows parents and batches
    detail = (await client.get(f"/api/businesses/{bid}/contacts/{inst.diya_id}")).json()
    assert [p["phone"] for p in detail["parents"]] == [DIYA_PARENT]
    assert [g["name"] for g in detail["batches"]] == ["NEET-A2"]


async def test_greeting_menu_and_no_timetable(inst):
    replies = await send(inst.business_id, KABIR, "hi")
    assert "Timetable" in replies[-1] and "Doubt:" in replies[-1] and "PTM" in replies[-1]
    replies = await send(inst.business_id, KABIR, "timetable today")
    assert "JEE-B1 — Mon 5 Oct: no classes on the timetable." in replies[-1]
    replies = await send(inst.business_id, "+919700099999", "timetable")
    assert "couldn't find your batch" in replies[-1]


async def test_ai_tools_for_institute(inst):
    from types import SimpleNamespace

    from wam.agent import agent as agent_module

    def resp(content, stop):
        return SimpleNamespace(content=content, stop_reason=stop)

    calls = []

    class LLM:
        def __init__(self, steps):
            self.steps = steps
            self.messages = self

        async def create(self, **kwargs):
            calls.append(kwargs)
            return self.steps.pop(0)(kwargs)

    def last_result(k):
        return json.loads(k["messages"][-1]["content"][0]["content"])

    await send(inst.business_id, KABIR, "hi")
    agent_module.set_llm_client(
        LLM(
            [
                lambda k: resp(
                    [
                        SimpleNamespace(
                            type="tool_use",
                            id="t1",
                            name="raise_doubt",
                            input={"question": "How do I balance redox equations?", "subject": "chemistry"},
                        )
                    ],
                    "tool_use",
                ),
                lambda k: resp(
                    [SimpleNamespace(type="text", text=last_result(k)["tell_student"])], "end_turn"
                ),
            ]
        )
    )
    replies = await send(inst.business_id, KABIR, "can someone explain how to balance redox equations")
    assert "Chemistry doubt is with the Chemistry teachers" in replies[-1]
    assert {t["name"] for t in calls[0]["tools"]} >= {
        "raise_doubt",
        "get_timetable",
        "get_fee_status",
        "find_slots",
    }
    assert "Institute rules" in calls[0]["system"]
    async with session_scope() as s:
        assert (await s.execute(select(Doubt))).scalar_one().subject.name == "Chemistry"


async def test_announcement_api_flow(inst, client):
    B = f"/api/businesses/{inst.business_id}/institute"
    r = await client.post(
        f"{B}/broadcasts",
        json={"group_id": inst.jee_id, "message": "Exam on Monday.", "audience": "everyone"},
    )
    assert r.status_code == 201
    b = r.json()
    assert (
        b["status"] == "draft"
        and b["recipients"] == 2
        and b["preview"].startswith("Update for JEE-B1: Exam on Monday.")
    )
    detail = (await client.get(f"{B}/broadcasts/{b['id']}")).json()
    assert {r["phone"]: r["name"] for r in detail["recipients"]} == {
        KABIR: "Kabir Das",
        KABIR_PARENT: "Parent of Kabir Das",
    }
    assert (await client.post(f"{B}/broadcasts/{b['id']}/cancel")).json()["status"] == "cancelled"
    r = await client.post(f"{B}/broadcasts/{b['id']}/send")
    assert r.status_code == 400
    r = await client.post(f"{B}/broadcasts", json={"group_id": inst.jee_id, "message": "x" * 800})
    assert r.status_code == 422
    subjects = (await client.get(f"{B}/subjects")).json()
    assert [s["name"] for s in subjects] == ["Chemistry", "Physics"]
    r = await client.put(f"{B}/batches/{inst.jee_id}/teachers", json={"staff_ids": [999]})
    assert r.status_code == 400
