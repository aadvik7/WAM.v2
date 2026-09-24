"""Admin sign-in."""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status
from sqlalchemy import func, select

from wam import clock
from wam.api.deps import SessionDep, UserDep
from wam.api.schemas import LoginIn, admin_user_out
from wam.audit import audit
from wam.jobs.queue import get_pool
from wam.models import AdminUser
from wam.security import create_admin_token, verify_secret

router = APIRouter(prefix="/api/auth", tags=["auth"])
log = logging.getLogger(__name__)

MAX_FAILURES = 10
WINDOW_SECONDS = 15 * 60
_memory_failures: dict[str, list[float]] = {}


async def _failures(key: str) -> int:
    try:
        value = await (await get_pool()).get(f"wam:login_fail:{key}")
        return int(value or 0)
    except Exception:  # Redis unavailable: per-process fallback
        now = time.monotonic()
        recent = [t for t in _memory_failures.get(key, []) if now - t < WINDOW_SECONDS]
        _memory_failures[key] = recent
        return len(recent)


async def _record_failure(key: str) -> None:
    try:
        pool = await get_pool()
        redis_key = f"wam:login_fail:{key}"
        await pool.incr(redis_key)
        await pool.expire(redis_key, WINDOW_SECONDS)
    except Exception:
        _memory_failures.setdefault(key, []).append(time.monotonic())


@router.post("/login")
async def login(body: LoginIn, request: Request, session: SessionDep) -> dict[str, Any]:
    ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "unknown"
    )
    keys = [f"email:{body.email.lower()}", f"ip:{ip}"]
    for key in keys:
        if await _failures(key) >= MAX_FAILURES:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS, "Too many attempts. Try again in 15 minutes."
            )
    user = (
        await session.execute(select(AdminUser).where(func.lower(AdminUser.email) == body.email.lower()))
    ).scalar_one_or_none()
    if user is None or not user.is_active or not verify_secret(body.password, user.password_hash):
        for key in keys:
            await _record_failure(key)
        log.warning("failed admin login for %s from %s", body.email, ip)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    user.last_login_at = clock.now()
    await audit(session, business_id=user.business_id, action="admin_login", admin_user_id=user.id)
    return {"token": create_admin_token(user.id, user.business_id), "user": admin_user_out(user)}


@router.get("/me")
async def me(user: UserDep) -> dict[str, Any]:
    return admin_user_out(user)
