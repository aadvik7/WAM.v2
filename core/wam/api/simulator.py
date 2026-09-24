"""Simulator: talk to WAM as a patient or staff member without WhatsApp (enable with ENABLE_SIMULATOR)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from wam.api.deps import BusinessDep, SessionDep
from wam.api.schemas import SimMessageIn, message_out
from wam.config import get_settings
from wam.db import session_scope
from wam.jobs.tasks import business_tick, run_due_jobs
from wam.models import MessageLog
from wam.phone import normalize_phone
from wam.router.inbound import Inbound, process_inbound_safely, record_inbound

router = APIRouter(prefix="/api/businesses/{business_id}/simulator", tags=["simulator"])


def _enabled() -> None:
    if not get_settings().enable_simulator:
        raise HTTPException(404, "Simulator is disabled (set ENABLE_SIMULATOR=true)")


@router.post("/message")
async def simulate_message(body: SimMessageIn, business: BusinessDep) -> dict[str, Any]:
    _enabled()
    phone = normalize_phone(body.phone)
    if phone is None:
        raise HTTPException(400, "Invalid phone number")
    async with session_scope() as session:
        log_id = await record_inbound(
            session, Inbound(business_id=business.id, phone=phone, text=body.text, name=body.name)
        )
    assert log_id is not None
    handled = await process_inbound_safely(log_id, {"name": body.name})
    async with session_scope() as session:
        replies = (
            (
                await session.execute(
                    select(MessageLog)
                    .where(
                        MessageLog.business_id == business.id,
                        MessageLog.direction == "out",
                        MessageLog.id > log_id,
                    )
                    .order_by(MessageLog.id)
                )
            )
            .scalars()
            .all()
        )
        return {
            "handled_by": handled,
            "replies": [message_out(m, business.timezone) for m in replies],
        }


@router.get("/conversation")
async def conversation(phone: str, business: BusinessDep, session: SessionDep) -> list[dict[str, Any]]:
    _enabled()
    e164 = normalize_phone(phone)
    rows = (
        (
            await session.execute(
                select(MessageLog)
                .where(MessageLog.business_id == business.id, MessageLog.phone == e164)
                .order_by(MessageLog.id.desc())
                .limit(100)
            )
        )
        .scalars()
        .all()
    )
    return [message_out(m, business.timezone) for m in reversed(rows)]


@router.post("/tick")
async def simulate_tick(business: BusinessDep) -> dict[str, Any]:
    """Run the scheduler now for this business (reminders, nudges, end-of-day check, due jobs)."""
    _enabled()
    result = await business_tick(business.id)
    result["jobs_run"] = await run_due_jobs()
    return result
