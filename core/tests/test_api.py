import datetime as dt

import httpx
import pytest

from tests.conftest import MONDAY, freeze
from wam.cli import create_admin
from wam.main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://core") as c:
        yield c


async def login(client, email, password):
    r = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_full_admin_setup_and_daily_use(client):
    await create_admin("root@wam.test", "supersecret1", None, "Root")
    r = await client.post("/api/auth/login", json={"email": "root@wam.test", "password": "wrong"})
    assert r.status_code == 401
    assert (await client.get("/api/businesses")).status_code == 401
    h = await login(client, "root@wam.test", "supersecret1")

    # Business + pack seeding
    r = await client.post(
        "/api/businesses",
        headers=h,
        json={
            "name": "Glow Skin Clinic",
            "type": "clinic",
            "timezone": "Asia/Kolkata",
            "hours": {"mon": [["10:00", "18:00"]], "tue": [["10:00", "18:00"]]},
            "address": "MG Road",
            "emergency_number": "+919999999999",
        },
    )
    assert r.status_code == 201, r.text
    bid = r.json()["id"]
    B = f"/api/businesses/{bid}"
    templates = (await client.get(f"{B}/templates", headers=h)).json()
    assert {t["name"] for t in templates} >= {"Root canal", "Laser or peel course", "Vaccination schedule"}
    roles = {r["name"]: r["id"] for r in (await client.get(f"{B}/roles", headers=h)).json()}
    assert set(roles) == {"owner", "doctor", "front_desk"}

    r = await client.patch(B, headers=h, json={"settings": {"min_notice_minutes": 30}})
    assert r.json()["settings"]["min_notice_minutes"] == 30
    r = await client.patch(B, headers=h, json={"settings": {"nonsense": 1}})
    assert r.status_code == 400

    # Staff with PIN, doctor resource, availability
    r = await client.post(
        f"{B}/staff",
        headers=h,
        json={"name": "Dr. Rao", "phone": "98700 00001", "role_id": roles["doctor"], "pin": "2468"},
    )
    assert r.status_code == 201 and r.json()["phone"] == "+919870000001" and r.json()["pin_set"]
    staff_id = r.json()["id"]
    assert (
        await client.post(f"{B}/staff", headers=h, json={"name": "dup", "phone": "+919870000001"})
    ).status_code == 400
    r = await client.post(
        f"{B}/resources",
        headers=h,
        json={"name": "Dr. Rao", "specialty": "Skin", "slot_minutes": 30, "staff_id": staff_id},
    )
    rid = r.json()["id"]
    r = await client.put(
        f"{B}/resources/{rid}/availability",
        headers=h,
        json={
            "weekly": [{"weekday": d, "start": "10:00", "end": "18:00"} for d in range(0, 5)],
            "breaks": [{"weekday": None, "start": "13:00", "end": "14:00"}],
        },
    )
    assert r.status_code == 200 and len(r.json()["weekly"]) == 5
    slots = (
        await client.get(f"{B}/resources/{rid}/slots", headers=h, params={"date_from": MONDAY.isoformat()})
    ).json()
    labels = [s["start_at"][11:16] for s in slots]
    assert labels[0] == "10:00" and "13:00" not in labels and "13:30" not in labels and "14:00" in labels

    # FAQ
    r = await client.post(
        f"{B}/faqs", headers=h, json={"question": "Fees?", "answer": "₹800", "keywords": ["Fee", " price "]}
    )
    assert r.json()["keywords"] == ["fee", "price"]

    # Patient, enrol (nudge sent), appointment, mark, cancel
    r = await client.post(f"{B}/contacts", headers=h, json={"name": "Meera", "phone": "9811100000"})
    cid = r.json()["id"]
    laser = next(t for t in templates if t["name"] == "Laser or peel course")
    r = await client.post(
        f"{B}/contacts/{cid}/schedules", headers=h, json={"template_id": laser["id"], "resource_id": rid}
    )
    assert r.status_code == 201 and r.json()["nudged"] is True and r.json()["sessions_total"] == 6
    sid = r.json()["id"]
    r = await client.post(
        f"{B}/appointments",
        headers=h,
        json={
            "contact_id": cid,
            "resource_id": rid,
            "start_at": f"{MONDAY.isoformat()}T15:00:00",
            "schedule_id": sid,
        },
    )
    assert r.status_code == 201, r.text
    appt = r.json()
    assert appt["start_at"].startswith(f"{MONDAY.isoformat()}T15:00:00+05:30")
    assert appt["service"] == "Laser or peel course (visit 1 of 6)"
    r = await client.post(f"{B}/appointments/{appt['id']}/mark", headers=h, json={"status": "done"})
    assert r.status_code == 400  # not yet happened
    freeze(MONDAY, 16)
    r = await client.post(f"{B}/appointments/{appt['id']}/mark", headers=h, json={"status": "done"})
    assert r.json()["status"] == "done"
    detail = (await client.get(f"{B}/contacts/{cid}", headers=h)).json()
    assert detail["schedules"][0]["sessions_done"] == 1
    assert detail["schedules"][0]["next_due_date"] == (MONDAY + dt.timedelta(days=30)).isoformat()
    assert any(m["template_name"] == "wam_session_due" for m in detail["messages"])

    today = (await client.get(f"{B}/today", headers=h)).json()
    assert today["counts"] == {"done": 1}

    rep = (await client.get(f"{B}/reports", headers=h)).json()
    assert rep["attendance"]["done"] == 1 and rep["plans"]["started"] == 1
    assert rep["bookings_by_source"] == {"admin": 1}
    assert len(rep["daily"]) == 30

    # Simulator
    sim = await client.post(
        f"{B}/simulator/message", headers=h, json={"phone": "9811100000", "text": "fees?"}
    )
    assert sim.status_code == 200
    assert any("₹800" in (m["content"] or "") for m in sim.json()["replies"])
    sim = await client.post(
        f"{B}/simulator/message", headers=h, json={"phone": "98700 00001", "text": "today's list"}
    )
    assert "Meera" in sim.json()["replies"][0]["content"]
    tick = await client.post(f"{B}/simulator/tick", headers=h)
    assert tick.status_code == 200

    # A clinic-level admin only sees their own clinic
    r = await client.post(
        "/api/admin-users",
        headers=h,
        json={"email": "owner@glow.test", "password": "glowglow1", "business_id": bid},
    )
    assert r.status_code == 201
    h2 = await login(client, "owner@glow.test", "glowglow1")
    assert [b["id"] for b in (await client.get("/api/businesses", headers=h2)).json()] == [bid]
    r = await client.post("/api/businesses", headers=h2, json={"name": "x"})
    assert r.status_code == 403
    r2 = await client.post("/api/businesses", headers=h, json={"name": "Other"})
    other = r2.json()["id"]
    assert (await client.get(f"/api/businesses/{other}", headers=h2)).status_code == 403

    # Erasure
    assert (await client.delete(f"{B}/contacts/{cid}", headers=h)).status_code == 204
    assert (await client.get(f"{B}/contacts/{cid}", headers=h)).status_code == 404
    audit = (await client.get(f"{B}/audit", headers=h)).json()
    assert audit[0]["action"] == "contact_erased"


async def test_meta_templates_and_health(client):
    await create_admin("a@wam.test", "password123", None, None)
    h = await login(client, "a@wam.test", "password123")
    tpls = (await client.get("/api/whatsapp-templates", headers=h)).json()
    names = {t["name"] for t in tpls}
    assert {
        "wam_session_due",
        "wam_day_before_reminder",
        "wam_missed_followup",
        "wam_recall",
        "wam_doctor_unavailable",
        "wam_booking_confirmation",
    } <= names
    for t in tpls:
        body = t["body"]
        assert not body.startswith("{{") and not body.rstrip(".").endswith("}}"), t["name"]
    r = await client.get("/health")
    assert r.json()["checks"]["database"] == "ok"
    assert (await client.get("/health/live")).json() == {"status": "ok"}


async def test_login_is_rate_limited(client):
    from wam.jobs.queue import get_pool

    pool = await get_pool()
    for key in await pool.keys("wam:login_fail:*"):
        await pool.delete(key)
    await create_admin("rl@wam.test", "password123", None, None)
    for _ in range(10):
        r = await client.post("/api/auth/login", json={"email": "rl@wam.test", "password": "nope"})
        assert r.status_code == 401
    r = await client.post("/api/auth/login", json={"email": "rl@wam.test", "password": "password123"})
    assert r.status_code == 429
    for key in await pool.keys("wam:login_fail:*"):
        await pool.delete(key)
