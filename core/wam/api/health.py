"""Health checks for monitoring (webhook, job queue, WhatsApp sending)."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from fastapi import APIRouter, Response
from sqlalchemy import func, select, text

from wam import clock
from wam.db import session_scope
from wam.jobs.queue import get_pool
from wam.models import Job, JobStatus, MessageLog

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health")
async def health(response: Response) -> dict[str, Any]:
    checks: dict[str, Any] = {}
    ok = True
    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
            hour_ago = clock.now() - dt.timedelta(hours=1)
            failed_sends = (
                await session.execute(
                    select(func.count(MessageLog.id)).where(
                        MessageLog.direction == "out",
                        MessageLog.status == "failed",
                        MessageLog.created_at >= hour_ago,
                    )
                )
            ).scalar_one()
            failed_inbound = (
                await session.execute(
                    select(func.count(MessageLog.id)).where(
                        MessageLog.direction == "in",
                        MessageLog.status == "failed",
                        MessageLog.created_at >= hour_ago,
                    )
                )
            ).scalar_one()
            stuck_inbound = (
                await session.execute(
                    select(func.count(MessageLog.id)).where(
                        MessageLog.direction == "in",
                        MessageLog.status == "received",
                        MessageLog.created_at < clock.now() - dt.timedelta(minutes=5),
                        MessageLog.created_at >= clock.now() - dt.timedelta(days=1),
                    )
                )
            ).scalar_one()
            failed_jobs = (
                await session.execute(
                    select(func.count(Job.id)).where(
                        Job.status == JobStatus.FAILED, Job.created_at >= clock.now() - dt.timedelta(days=1)
                    )
                )
            ).scalar_one()
        checks["database"] = "ok"
        checks["failed_sends_last_hour"] = failed_sends
        checks["failed_inbound_last_hour"] = failed_inbound
        checks["unprocessed_inbound"] = stuck_inbound
        checks["failed_jobs_last_day"] = failed_jobs
        if failed_sends >= 5 or stuck_inbound > 0 or failed_inbound > 0:
            ok = False
    except Exception as exc:
        checks["database"] = f"error: {type(exc).__name__}"
        ok = False
    try:
        pool = await get_pool()
        await pool.ping()
        checks["redis"] = "ok"
        beat = await pool.get("wam:worker:heartbeat")
        age = int(time.time()) - int(beat) if beat else None
        checks["worker_heartbeat_age_seconds"] = age
        if age is None or age > 180:
            checks["worker"] = "not running"
            ok = False
        else:
            checks["worker"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
        ok = False
    if not ok:
        response.status_code = 503
    return {"status": "ok" if ok else "degraded", "checks": checks}
