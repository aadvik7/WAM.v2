"""Short-lived conversation state (offered slots, pending reminders, today's list sent to staff)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.models import ConversationState


async def get_state(
    session: AsyncSession, *, key: str, contact_id: int | None = None, staff_id: int | None = None
) -> ConversationState | None:
    stmt = select(ConversationState).where(
        ConversationState.key == key, ConversationState.expires_at > clock.now()
    )
    if contact_id is not None:
        stmt = stmt.where(ConversationState.contact_id == contact_id)
    elif staff_id is not None:
        stmt = stmt.where(ConversationState.staff_id == staff_id)
    else:
        raise ValueError("contact_id or staff_id required")
    stmt = stmt.order_by(ConversationState.id.desc()).limit(1)
    return (await session.execute(stmt)).scalar_one_or_none()


async def set_state(
    session: AsyncSession,
    *,
    business_id: int,
    key: str,
    data: dict[str, Any],
    ttl: dt.timedelta,
    contact_id: int | None = None,
    staff_id: int | None = None,
) -> ConversationState:
    await clear_state(session, key=key, contact_id=contact_id, staff_id=staff_id)
    row = ConversationState(
        business_id=business_id,
        contact_id=contact_id,
        staff_id=staff_id,
        key=key,
        data=data,
        expires_at=clock.now() + ttl,
    )
    session.add(row)
    await session.flush()
    return row


async def clear_state(
    session: AsyncSession, *, key: str, contact_id: int | None = None, staff_id: int | None = None
) -> None:
    stmt = delete(ConversationState).where(ConversationState.key == key)
    if contact_id is not None:
        stmt = stmt.where(ConversationState.contact_id == contact_id)
    elif staff_id is not None:
        stmt = stmt.where(ConversationState.staff_id == staff_id)
    else:
        raise ValueError("contact_id or staff_id required")
    await session.execute(stmt)


async def purge_expired(session: AsyncSession) -> int:
    result = await session.execute(
        delete(ConversationState).where(ConversationState.expires_at <= clock.now())
    )
    return result.rowcount or 0
