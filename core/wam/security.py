"""Password / PIN hashing and admin tokens."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

import bcrypt
import jwt

from wam.config import get_settings

PIN_RE = re.compile(r"^\d{4,6}$")
MAX_PIN_ATTEMPTS = 5
PIN_LOCK_MINUTES = 15


def hash_secret(secret: str) -> str:
    return bcrypt.hashpw(secret.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_secret(secret: str, hashed: str | None) -> bool:
    if not hashed or not secret:
        return False
    try:
        return bcrypt.checkpw(secret.encode(), hashed.encode())
    except ValueError:
        return False


def valid_pin(pin: str) -> bool:
    return bool(PIN_RE.match(pin or ""))


def create_admin_token(user_id: int, business_id: int | None) -> str:
    settings = get_settings()
    now = dt.datetime.now(dt.UTC)  # real time: JWT expiry is checked against the wall clock
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "bid": business_id,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(hours=settings.admin_token_hours)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_admin_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
