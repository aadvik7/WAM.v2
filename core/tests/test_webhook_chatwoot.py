import json

import httpx
import pytest
import respx
from sqlalchemy import select

from tests.conftest import Clinic
from wam.config import get_settings
from wam.db import session_scope
from wam.main import app
from wam.messaging import Outgoing, send_to_contact
from wam.models import Business, Contact, MessageLog

CW = "http://chatwoot.test"


@pytest.fixture
def chatwoot(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "chatwoot_base_url", CW)
    monkeypatch.setattr(settings, "chatwoot_api_token", "admin-token")
    monkeypatch.setattr(settings, "chatwoot_bot_token", "bot-token")
    with respx.mock(assert_all_called=False) as mock:
        yield mock


async def _link_inbox(clinic):
    async with session_scope() as s:
        b = await s.get(Business, clinic.business_id)
        b.chatwoot_account_id = 1
        b.chatwoot_inbox_id = 5


def payload(text: str, msg_id: int, phone: str = Clinic.RAHUL_PHONE, status: str = "pending"):
    return {
        "event": "message_created",
        "id": msg_id,
        "content": text,
        "message_type": "incoming",
        "private": False,
        "sender": {"id": 900, "name": "Rahul Sharma", "phone_number": phone, "type": "contact"},
        "conversation": {
            "id": 42,
            "status": status,
            "inbox_id": 5,
            "contact_inbox": {"source_id": phone.lstrip("+")},
        },
        "account": {"id": 1, "name": "Smile"},
        "inbox": {"id": 5, "name": "WhatsApp"},
    }


async def test_webhook_rejects_wrong_secret_and_unlinked_inboxes(clinic):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        r = await client.post("/webhooks/chatwoot/wrong", json=payload("hi", 1))
        assert r.status_code == 404
        # the clinic isn't linked to an inbox yet: nothing may be routed to it
        secret = get_settings().webhook_secret
        bare = payload("hi", 2)
        bare["account"] = {"id": None}
        bare["inbox"] = {"id": None}
        bare["conversation"]["inbox_id"] = None
        r = await client.post(f"/webhooks/chatwoot/{secret}", json=bare)
        assert r.json()["ignored"] is True
        r = await client.post(f"/webhooks/chatwoot/{secret}", json=payload("hi", 3))
        assert r.json()["reason"] == "unknown inbox"


async def test_webhook_replies_through_chatwoot_and_dedupes(clinic, chatwoot):
    await _link_inbox(clinic)
    sent = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/messages").mock(
        return_value=httpx.Response(200, json={"id": 555})
    )
    toggles = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/toggle_status").mock(
        return_value=httpx.Response(200, json={})
    )
    secret = get_settings().webhook_secret
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        r = await client.post(f"/webhooks/chatwoot/{secret}", json=payload("what are your timings?", 101))
        assert r.status_code == 200 and r.json()["queued"]
        r = await client.post(f"/webhooks/chatwoot/{secret}", json=payload("what are your timings?", 101))
        assert r.json().get("duplicate") is True
        # outgoing / private / other events are ignored
        ignored = payload("x", 102)
        ignored["message_type"] = "outgoing"
        assert (await client.post(f"/webhooks/chatwoot/{secret}", json=ignored)).json()["ignored"] is True
    bodies = [json.loads(c.request.content) for c in sent.calls]
    assert len(bodies) == 2  # consent notice + answer
    assert "Privacy policy" in bodies[0]["content"]
    assert "Our timings" in bodies[1]["content"] and "template_params" not in bodies[1]
    assert sent.calls[0].request.headers["api_access_token"] == "bot-token"
    assert not toggles.called
    async with session_scope() as s:
        rahul = await s.get(Contact, clinic.rahul_id)
        assert rahul.chatwoot_conversation_id == 42 and rahul.chatwoot_contact_id == 900
        out = (await s.execute(select(MessageLog).where(MessageLog.direction == "out"))).scalars().all()
        assert all(m.status == "ok" for m in out) and out[-1].chatwoot_message_id == 555


async def test_emergency_webhook_sets_urgent_and_opens(clinic, chatwoot):
    await _link_inbox(clinic)
    chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/messages").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    toggle = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/toggle_status").mock(
        return_value=httpx.Response(200, json={})
    )
    prio = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/toggle_priority").mock(
        return_value=httpx.Response(200, json={})
    )
    labels = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/labels").mock(
        return_value=httpx.Response(200, json={})
    )
    # the desk alert goes to a new conversation for the staff member
    chatwoot.get(f"{CW}/api/v1/accounts/1/contacts/search").mock(
        return_value=httpx.Response(200, json={"payload": []})
    )
    chatwoot.post(f"{CW}/api/v1/accounts/1/contacts").mock(
        return_value=httpx.Response(
            200,
            json={
                "payload": {
                    "contact": {
                        "id": 77,
                        "contact_inboxes": [{"source_id": "919800000002", "inbox": {"id": 5}}],
                    }
                }
            },
        )
    )
    chatwoot.get(f"{CW}/api/v1/accounts/1/contacts/77/conversations").mock(
        return_value=httpx.Response(200, json={"payload": []})
    )
    chatwoot.post(f"{CW}/api/v1/accounts/1/conversations").mock(
        return_value=httpx.Response(200, json={"id": 88})
    )
    desk_msg = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/88/messages").mock(
        return_value=httpx.Response(200, json={"id": 2})
    )
    secret = get_settings().webhook_secret
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        await client.post(f"/webhooks/chatwoot/{secret}", json=payload("he is unconscious please help", 201))
    assert json.loads(toggle.calls[0].request.content) == {"status": "open"}
    assert json.loads(prio.calls[0].request.content) == {"priority": "urgent"}
    assert json.loads(labels.calls[0].request.content) == {"labels": ["emergency"]}
    body = json.loads(desk_msg.calls[0].request.content)
    # front desk hasn't messaged in 24h -> approved template
    assert body["template_params"]["name"] == "wam_staff_alert"
    assert body["template_params"]["processed_params"]["body"]["1"] == "Smile Dental"
    assert body["template_params"]["language"] == "en"


async def test_proactive_template_creates_conversation(clinic, chatwoot):
    await _link_inbox(clinic)
    chatwoot.get(f"{CW}/api/v1/accounts/1/contacts/search").mock(
        return_value=httpx.Response(
            200, json={"payload": [{"id": 900, "phone_number": Clinic.ANITA_PHONE, "contact_inboxes": []}]}
        )
    )
    ci = chatwoot.post(f"{CW}/api/v1/accounts/1/contacts/900/contact_inboxes").mock(
        return_value=httpx.Response(200, json={"source_id": "919822222222"})
    )
    chatwoot.get(f"{CW}/api/v1/accounts/1/contacts/900/conversations").mock(
        return_value=httpx.Response(200, json={"payload": [{"id": 12, "inbox_id": 5, "status": "resolved"}]})
    )
    msg = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/12/messages").mock(
        return_value=httpx.Response(200, json={"id": 3})
    )
    async with session_scope() as s:
        business = await s.get(Business, clinic.business_id)
        anita = await s.get(Contact, clinic.anita_id)
        row = await send_to_contact(
            s,
            business,
            anita,
            Outgoing(
                text="free text",
                template_key="booking_confirmation",
                template_values={"service": "Cleaning", "date": "Mon 12 Oct", "time": "10:00 AM"},
            ),
        )
        assert row.status == "ok" and row.template_name == "wam_booking_confirmation"
        assert anita.chatwoot_conversation_id == 12
    assert ci.called
    body = json.loads(msg.calls[0].request.content)
    assert body["content"] == "Booked: Cleaning, Mon 12 Oct at 10:00 AM. Reply here if you need to change it."
    assert body["template_params"]["processed_params"] == {
        "body": {"1": "Cleaning", "2": "Mon 12 Oct", "3": "10:00 AM"}
    }


async def test_legacy_template_format_option(clinic, chatwoot, monkeypatch):
    monkeypatch.setattr(get_settings(), "chatwoot_template_format", "legacy")
    await _link_inbox(clinic)
    msg = chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/messages").mock(
        return_value=httpx.Response(200, json={"id": 3})
    )
    async with session_scope() as s:
        business = await s.get(Business, clinic.business_id)
        business.settings = {**business.settings, "template_language": "en_US"}
        rahul = await s.get(Contact, clinic.rahul_id)
        rahul.chatwoot_conversation_id = 42
        await send_to_contact(
            s,
            business,
            rahul,
            Outgoing(
                text="x",
                template_key="recall",
                template_values={"name": "R", "service": "Cleaning", "slots": "1) a"},
            ),
        )
    params = json.loads(msg.calls[0].request.content)["template_params"]
    assert params["processed_params"] == {"1": "R", "2": "Cleaning", "3": "1) a"}
    assert params["language"] == "en_US"


async def test_send_failure_is_logged(clinic, chatwoot):
    await _link_inbox(clinic)
    chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/messages").mock(
        return_value=httpx.Response(500, text="boom")
    )
    async with session_scope() as s:
        business = await s.get(Business, clinic.business_id)
        rahul = await s.get(Contact, clinic.rahul_id)
        rahul.chatwoot_conversation_id = 42
        row = await send_to_contact(
            s,
            business,
            rahul,
            Outgoing(
                text="hi", template_key="recall", template_values={"name": "R", "service": "x", "slots": "y"}
            ),
        )
        assert row.status == "failed" and "500" in row.error


async def test_signed_webhooks_are_verified(clinic, chatwoot):
    import hashlib
    import hmac
    import time

    await _link_inbox(clinic)
    async with session_scope() as s:
        b = await s.get(Business, clinic.business_id)
        b.chatwoot_webhook_secret = "bot-secret"
    chatwoot.post(f"{CW}/api/v1/accounts/1/conversations/42/messages").mock(
        return_value=httpx.Response(200, json={"id": 1})
    )
    secret = get_settings().webhook_secret
    body = json.dumps(payload("timings?", 301)).encode()
    ts = str(int(time.time()))
    good = "sha256=" + hmac.new(b"bot-secret", f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        headers = {"content-type": "application/json"}
        r = await client.post(f"/webhooks/chatwoot/{secret}", content=body, headers=headers)
        assert r.status_code == 401
        bad = {**headers, "x-chatwoot-timestamp": ts, "x-chatwoot-signature": "sha256=00"}
        assert (
            await client.post(f"/webhooks/chatwoot/{secret}", content=body, headers=bad)
        ).status_code == 401
        ok = {**headers, "x-chatwoot-timestamp": ts, "x-chatwoot-signature": good}
        r = await client.post(f"/webhooks/chatwoot/{secret}", content=body, headers=ok)
        assert r.status_code == 200 and r.json()["queued"]


async def test_resolving_chat_in_inbox_ends_handoff(clinic):
    await _link_inbox(clinic)
    async with session_scope() as s:
        rahul = await s.get(Contact, clinic.rahul_id)
        rahul.needs_staff = True
    secret = get_settings().webhook_secret
    event = {
        "event": "conversation_resolved",
        "id": 42,
        "inbox_id": 5,
        "status": "resolved",
        "account": {"id": 1},
        "meta": {"sender": {"id": 900, "phone_number": Clinic.RAHUL_PHONE}, "assignee": None},
    }
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as client:
        r = await client.post(f"/webhooks/chatwoot/{secret}", json={**event, "status": "open"})
        assert r.json()["ignored"] is True
        r = await client.post(f"/webhooks/chatwoot/{secret}", json=event)
        assert r.json()["handoff_cleared"] is True
    async with session_scope() as s:
        assert (await s.get(Contact, clinic.rahul_id)).needs_staff is False
