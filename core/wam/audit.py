"""Audit log: who did what, when, from which phone."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from wam.models import AuditLog, Staff


async def audit(
    session: AsyncSession,
    *,
    business_id: int | None,
    action: str,
    details: dict[str, Any] | None = None,
    staff: Staff | None = None,
    admin_user_id: int | None = None,
    phone: str | None = None,
) -> None:
    session.add(
        AuditLog(
            business_id=business_id,
            staff_id=staff.id if staff else None,
            admin_user_id=admin_user_id,
            phone=phone or (staff.phone if staff else None),
            action=action,
            details=details or {},
        )
    )
    await session.flush()
