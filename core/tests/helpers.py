from __future__ import annotations

from sqlalchemy import select

from wam.db import session_scope
from wam.jobs.tasks import business_tick, run_due_jobs
from wam.models import MessageLog
from wam.router.inbound import Inbound, process_inbound_safely, record_inbound


async def send(business_id: int, phone: str, text: str, name: str | None = None, **meta) -> list[str]:
    """Simulate an inbound WhatsApp message; return the texts WAM sent back (to anyone)."""
    async with session_scope() as s:
        log_id = await record_inbound(s, Inbound(business_id=business_id, phone=phone, text=text, name=name))
    assert log_id is not None
    handled = await process_inbound_safely(log_id, {"name": name, **meta})
    assert handled != "failed", "processing failed"
    async with session_scope() as s:
        rows = (
            (
                await s.execute(
                    select(MessageLog)
                    .where(MessageLog.direction == "out", MessageLog.id > log_id)
                    .order_by(MessageLog.id)
                )
            )
            .scalars()
            .all()
        )
        return [r.content or "" for r in rows]


async def outbox(phone: str | None = None, since_id: int = 0) -> list[MessageLog]:
    async with session_scope() as s:
        stmt = select(MessageLog).where(MessageLog.direction == "out", MessageLog.id > since_id)
        if phone:
            stmt = stmt.where(MessageLog.phone == phone)
        return list((await s.execute(stmt.order_by(MessageLog.id))).scalars().all())


async def last_log_id() -> int:
    async with session_scope() as s:
        row = (
            await s.execute(select(MessageLog.id).order_by(MessageLog.id.desc()).limit(1))
        ).scalar_one_or_none()
        return row or 0


async def tick(business_id: int) -> dict:
    result = await business_tick(business_id)
    result["jobs"] = await run_due_jobs()
    return result
