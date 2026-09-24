from sqlalchemy import select

from tests.conftest import MONDAY, Clinic, freeze
from tests.helpers import outbox, send
from wam.db import session_scope
from wam.models import Appointment, AppointmentStatus, Contact


async def test_new_patient_gets_consent_then_books_by_number(clinic):
    replies = await send(clinic.business_id, "+919833333333", "Hi, I want an appointment", name="Karan")
    assert "Privacy policy" in replies[0] and "STOP" in replies[0]
    assert "1) " in replies[1] and "Reply 1, 2 or 3" in replies[1]
    replies = await send(clinic.business_id, "+919833333333", "2")
    assert replies[0].startswith("Booked:")
    async with session_scope() as s:
        karan = (await s.execute(select(Contact).where(Contact.phone == "+919833333333"))).scalar_one()
        assert karan.name == "Karan" and karan.consent_at is not None
        appt = (await s.execute(select(Appointment).where(Appointment.contact_id == karan.id))).scalar_one()
        assert appt.status == AppointmentStatus.BOOKED and appt.source == "whatsapp"


async def test_emergency_hands_off_immediately(clinic):
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "my father has severe chest pain")
    assert "112" in replies[0] and "+919820000000" in replies[0]
    # front desk alerted
    desk_msgs = await outbox(Clinic.DESK_PHONE)
    assert any("EMERGENCY" in (m.content or "") for m in desk_msgs)
    async with session_scope() as s:
        rahul = await s.get(Contact, clinic.rahul_id)
        assert rahul.needs_staff is True


async def test_bot_stays_quiet_when_staff_handle_chat(clinic):
    replies = await send(
        clinic.business_id,
        Clinic.RAHUL_PHONE,
        "what are your timings",
        conversation_status="open",
        conversation_assigned=True,
    )
    assert replies == []
    # open but nobody assigned and no handoff: WAM still answers
    replies = await send(
        clinic.business_id, Clinic.RAHUL_PHONE, "what are your timings", conversation_status="open"
    )
    assert any("Our timings" in r for r in replies)


async def test_stop_and_start(clinic):
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "hello")
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "STOP")
    assert "won't get reminders" in replies[0]
    async with session_scope() as s:
        assert (await s.get(Contact, clinic.rahul_id)).opted_out is True
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "start")
    assert "Reminders are on again" in replies[0]


async def test_faq_and_timings_without_ai(clinic):
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "hello")
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "what are your timings?")
    assert "Mon–Sat: 10 AM–1 PM, 5 PM–8 PM" in replies[0] and "Sun: Closed" in replies[0]
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "how much is the consultation fee")
    assert replies == ["Consultation is ₹500."]
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "where are you located")
    assert "Linking Road" in replies[0]


async def test_unknown_question_goes_to_staff(clinic):
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "hello")
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "is my crown covered by insurance xyz?")
    assert "team member will reply" in replies[0]


async def test_voice_note_is_handed_off(clinic):
    from wam.db import session_scope as sc
    from wam.router.inbound import Inbound, process_inbound_safely, record_inbound

    async with sc() as s:
        log_id = await record_inbound(
            s,
            Inbound(business_id=clinic.business_id, phone=Clinic.RAHUL_PHONE, text="", has_attachments=True),
        )
    assert await process_inbound_safely(log_id, {"has_attachments": True}) == "staff"


async def test_duplicate_webhook_delivery_is_ignored(clinic):
    from wam.router.inbound import Inbound, record_inbound

    async with session_scope() as s:
        first = await record_inbound(
            s,
            Inbound(
                business_id=clinic.business_id, phone=Clinic.RAHUL_PHONE, text="hi", chatwoot_message_id=77
            ),
        )
        second = await record_inbound(
            s,
            Inbound(
                business_id=clinic.business_id, phone=Clinic.RAHUL_PHONE, text="hi", chatwoot_message_id=77
            ),
        )
    assert first is not None and second is None


async def test_stale_offer_rebooks_with_fresh_slots(clinic):
    await send(clinic.business_id, Clinic.RAHUL_PHONE, "book appointment")
    # Anita takes Rahul's first offered slot through the admin before he replies
    await send(clinic.business_id, Clinic.ANITA_PHONE, "book appointment")
    replies = await send(clinic.business_id, Clinic.ANITA_PHONE, "1")
    assert replies[0].startswith("Booked:")
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "1")
    assert "just taken" in replies[0] and "1) " in replies[0]
    replies = await send(clinic.business_id, Clinic.RAHUL_PHONE, "1")
    assert replies[0].startswith("Booked:")
    freeze(MONDAY, 9)
