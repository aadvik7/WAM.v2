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
