"""API dependencies: admin auth and business access."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from wam.db import get_session
from wam.models import AdminUser, Business
from wam.security import decode_admin_token

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def current_user(
    session: SessionDep, authorization: Annotated[str | None, Header()] = None
) -> AdminUser:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    claims = decode_admin_token(authorization.split(" ", 1)[1].strip())
    if claims is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired, please sign in again")
    user = await session.get(AdminUser, int(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account disabled")
    return user


UserDep = Annotated[AdminUser, Depends(current_user)]


def require_super(user: UserDep) -> AdminUser:
    if user.business_id is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only a super admin can do this")
    return user


async def business_access(business_id: int, user: UserDep, session: SessionDep) -> Business:
    if user.business_id is not None and user.business_id != business_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "No access to this business")
    business = await session.get(Business, business_id)
    if business is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Business not found")
    return business


BusinessDep = Annotated[Business, Depends(business_access)]


def not_found(what: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail)
