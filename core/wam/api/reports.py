"""Reports: visits recovered, plan completion rate, no-shows, messages answered without staff."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, select

from wam import clock
from wam.api.deps import BusinessDep, SessionDep
from wam.api.schemas import message_out
from wam.models import Appointment, AppointmentStatus, AuditLog, MessageLog, Schedule, ScheduleStatus

router = APIRouter(prefix="/api/businesses/{business_id}", tags=["reports"])


def _pct(num: int, den: int) -> float | None:
    return round(100.0 * num / den, 1) if den else None


@router.get("/reports")
async def reports(
    business: BusinessDep,
    session: SessionDep,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> dict[str, Any]:
    tz = business.timezone
    today = clock.local_today(tz)
    date_to = date_to or today
    date_from = date_from or (date_to - dt.timedelta(days=29))
    start, _ = clock.day_bounds(date_from, tz)
    _, end = clock.day_bounds(date_to, tz)
    bid = business.id

    # Visits recovered: overdue/missed patients who rebooked through WAM (not later cancelled)
    rec = (
        await session.execute(
            select(
                func.count(Appointment.id),
                func.count(Appointment.id).filter(Appointment.status == AppointmentStatus.DONE),
            ).where(
                Appointment.business_id == bid,
                Appointment.recovered.is_(True),
                Appointment.status != AppointmentStatus.CANCELLED,
                Appointment.created_at >= start,
                Appointment.created_at < end,
            )
        )
    ).one()

    # No-shows among visits that happened in the period
    att = (
        await session.execute(
            select(
                func.count(Appointment.id).filter(Appointment.status == AppointmentStatus.DONE),
                func.count(Appointment.id).filter(Appointment.status == AppointmentStatus.MISSED),
                func.count(Appointment.id).filter(Appointment.status.in_(AppointmentStatus.ACTIVE)),
            ).where(
                Appointment.business_id == bid,
                Appointment.start_at >= start,
                Appointment.start_at < min(end, clock.now()),
            )
        )
    ).one()
    done, missed, unmarked = att

    # Plan completion (fixed-length plans started in the period)
    plans = (
        await session.execute(
            select(
                func.count(Schedule.id),
                func.count(Schedule.id).filter(Schedule.status == ScheduleStatus.COMPLETED),
                func.count(Schedule.id).filter(Schedule.status == ScheduleStatus.CANCELLED),
                func.count(Schedule.id).filter(Schedule.status == ScheduleStatus.ACTIVE),
            ).where(
                Schedule.business_id == bid,
                Schedule.sessions_total.is_not(None),
                Schedule.created_at >= start,
                Schedule.created_at < end,
            )
        )
    ).one()
    plans_total, plans_completed, plans_cancelled, plans_active = plans
    overdue_now = (
        await session.execute(
            select(func.count(Schedule.id)).where(
                Schedule.business_id == bid,
                Schedule.status == ScheduleStatus.ACTIVE,
                Schedule.next_due_date < today,
            )
        )
    ).scalar_one()

    # Messages answered without staff
    msgs = (
        await session.execute(
            select(
                func.count(MessageLog.id),
                func.count(MessageLog.id).filter(MessageLog.handled_by.in_(("ai", "rule"))),
                func.count(MessageLog.id).filter(MessageLog.handled_by == "ai"),
            ).where(
                MessageLog.business_id == bid,
                MessageLog.direction == "in",
                MessageLog.audience == "patient",
                MessageLog.handled_by.is_not(None),
                MessageLog.created_at >= start,
                MessageLog.created_at < end,
            )
        )
    ).one()
    msgs_total, msgs_auto, msgs_ai = msgs
    sent = (
        await session.execute(
            select(
                func.count(MessageLog.id).filter(MessageLog.status.in_(("ok", "dry_run"))),
                func.count(MessageLog.id).filter(MessageLog.template_name.is_not(None)),
                func.count(MessageLog.id).filter(MessageLog.status == "failed"),
            ).where(
                MessageLog.business_id == bid,
                MessageLog.direction == "out",
                MessageLog.created_at >= start,
                MessageLog.created_at < end,
            )
        )
    ).one()

    by_source = dict(
        (
            await session.execute(
                select(Appointment.source, func.count(Appointment.id))
                .where(
                    Appointment.business_id == bid,
                    Appointment.created_at >= start,
                    Appointment.created_at < end,
                    Appointment.cancelled_reason.is_distinct_from("rescheduled"),
                )
                .group_by(Appointment.source)
            )
        ).all()
    )

    # Daily series (local days)
    local_day = func.date(func.timezone(tz, Appointment.start_at))
    series_rows = (
        await session.execute(
            select(
                local_day,
                func.count(Appointment.id).filter(Appointment.status == AppointmentStatus.DONE),
                func.count(Appointment.id).filter(Appointment.status == AppointmentStatus.MISSED),
                func.count(Appointment.id).filter(
                    and_(Appointment.recovered.is_(True), Appointment.status != AppointmentStatus.CANCELLED)
                ),
            )
            .where(Appointment.business_id == bid, Appointment.start_at >= start, Appointment.start_at < end)
            .group_by(local_day)
            .order_by(local_day)
        )
    ).all()
    series = {r[0].isoformat(): {"done": r[1], "missed": r[2], "recovered": r[3]} for r in series_rows}
    days = []
    d = date_from
    while d <= date_to:
        days.append(
            {"date": d.isoformat(), **series.get(d.isoformat(), {"done": 0, "missed": 0, "recovered": 0})}
        )
        d += dt.timedelta(days=1)

    return {
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "visits_recovered": {"booked": rec[0], "came": rec[1]},
        "attendance": {
            "done": done,
            "missed": missed,
            "unmarked": unmarked,
            "no_show_rate": _pct(missed, done + missed),
        },
        "plans": {
            "started": plans_total,
            "completed": plans_completed,
            "cancelled": plans_cancelled,
            "active": plans_active,
            "completion_rate": _pct(plans_completed, plans_total),
            "overdue_now": overdue_now,
        },
        "messages": {
            "patient_messages": msgs_total,
            "answered_without_staff": msgs_auto,
            "answered_by_ai": msgs_ai,
            "rate_without_staff": _pct(msgs_auto, msgs_total),
            "sent": sent[0],
            "templates_sent": sent[1],
            "failed": sent[2],
        },
        "bookings_by_source": by_source,
        "daily": days,
    }


@router.get("/messages")
async def list_messages(
    business: BusinessDep,
    session: SessionDep,
    contact_id: int | None = None,
    phone: str | None = None,
    audience: str | None = None,
    status: str | None = None,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    stmt = select(MessageLog).where(MessageLog.business_id == business.id)
    if contact_id is not None:
        stmt = stmt.where(MessageLog.contact_id == contact_id)
    if phone:
        stmt = stmt.where(MessageLog.phone == phone)
    if audience:
        stmt = stmt.where(MessageLog.audience == audience)
    if status:
        stmt = stmt.where(MessageLog.status == status)
    if before_id:
        stmt = stmt.where(MessageLog.id < before_id)
    rows = (await session.execute(stmt.order_by(MessageLog.id.desc()).limit(limit))).scalars().all()
    return [message_out(m, business.timezone) for m in rows]


@router.get("/audit")
async def list_audit(
    business: BusinessDep,
    session: SessionDep,
    before_id: int | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[dict[str, Any]]:
    stmt = select(AuditLog).where(AuditLog.business_id == business.id)
    if before_id:
        stmt = stmt.where(AuditLog.id < before_id)
    rows = (await session.execute(stmt.order_by(AuditLog.id.desc()).limit(limit))).scalars().all()
    tz = business.timezone
    return [
        {
            "id": r.id,
            "action": r.action,
            "staff_id": r.staff_id,
            "admin_user_id": r.admin_user_id,
            "phone": r.phone,
            "details": r.details,
            "created_at": clock.to_local(r.created_at, tz).isoformat(),
        }
        for r in rows
    ]
