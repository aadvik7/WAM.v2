"""Durable scheduled jobs (the `jobs` table) and the arq queue for inbound message processing."""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from wam.config import get_settings
from wam.models import Job, JobStatus

log = logging.getLogger(__name__)

_pool: ArqRedis | None = None


def redis_settings() -> RedisSettings:
    return RedisSettings.from_dsn(get_settings().redis_url)


async def get_pool() -> ArqRedis:
    global _pool
    if _pool is None:
        _pool = await create_pool(redis_settings())
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.aclose()
    _pool = None


async def enqueue(function: str, *args: Any, job_id: str | None = None) -> bool:
    pool = await get_pool()
    job = await pool.enqueue_job(function, *args, _job_id=job_id)
    return job is not None


async def kick_jobs() -> None:
    """Ask the worker to run due jobs now rather than at the next minute tick (e.g. an announcement a
    coordinator just sent). Best effort: if Redis is down, the minute tick still runs them."""
    if get_settings().process_inline:
        return
    try:
        pool = await get_pool()
        await pool.enqueue_job("run_jobs", _defer_by=dt.timedelta(seconds=1))
    except Exception as exc:
        log.warning("could not wake the worker (%s); jobs run at the next tick", exc)


async def schedule_job(
    session: AsyncSession,
    business_id: int,
    kind: str,
    run_at: dt.datetime,
    payload: dict[str, Any],
    *,
    dedupe_key: str | None = None,
) -> None:
    """Insert a scheduled job; a duplicate dedupe_key is ignored (idempotent)."""
    stmt = (
        insert(Job)
        .values(
            business_id=business_id,
            kind=kind,
            run_at=run_at,
            payload=payload,
            status=JobStatus.SCHEDULED,
            dedupe_key=dedupe_key,
        )
        .on_conflict_do_nothing(index_elements=["dedupe_key"])
    )
    await session.execute(stmt)
