"""arq worker: processes inbound messages and runs the scheduler tick every minute.

Run with:  arq wam.jobs.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from arq import cron

from wam.config import get_settings
from wam.db import dispose_engine
from wam.jobs.queue import redis_settings
from wam.jobs.tasks import run_due_jobs, tick
from wam.logging_setup import setup_logging
from wam.router.inbound import process_inbound_safely

log = logging.getLogger(__name__)
RUN_JOBS_SECONDS = 90


async def handle_inbound(ctx: dict[str, Any], log_id: int, meta: dict[str, Any] | None = None) -> str:
    return await process_inbound_safely(log_id, meta)


async def run_jobs(ctx: dict[str, Any]) -> int:
    """Run due jobs now, and keep going while a long send continues batch after batch."""
    total = 0
    idle = 0
    deadline = time.monotonic() + RUN_JOBS_SECONDS
    while time.monotonic() < deadline:
        done = await run_due_jobs()
        total += done
        if done:
            idle = 0
            continue
        idle += 1
        if idle > 5:  # the job that woke us may still be committing; give it a few seconds
            return total
        await asyncio.sleep(1)
    await ctx["redis"].enqueue_job("run_jobs")  # still busy: hand over to a fresh run
    return total


async def startup(ctx: dict[str, Any]) -> None:
    setup_logging(get_settings().log_level)
    log.info("WAM worker started")


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()


class WorkerSettings:
    functions = [handle_inbound, run_jobs]
    cron_jobs = [cron(tick, second=0, run_at_startup=True, unique=True, timeout=300)]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = redis_settings()
    max_jobs = 20
    job_timeout = 120
    keep_result = 3600
