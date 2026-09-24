"""Scheduled work, run by the arq worker every minute (`tick`).

Each scanner is idempotent (driven by DB state), so a missed or repeated tick is harmless:
- day-before reminders           (appointments.reminder_sent_at)
- due nudges / recalls           (schedules.nudge_count, last_nudged_at)
- end-of-day attendance check    (jobs row with dedupe key eod:<business>:<date>)
- missed-visit follow-ups        (jobs rows missed_followup, created when staff mark someone missed)
- data retention                 (daily)
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.db import session_scope
from wam.engine.schedules import active_appointment_for_schedule
from wam.flows import (
    flag_to_staff,
    followup_missed,
    nudge_schedule,
    send_payment_reminder,
    send_reminder,
    staff_to_alert,
)
from wam.jobs.queue import schedule_job
from wam.messaging import Outgoing, send_to_staff
from wam.models import (
    Appointment,
    AppointmentStatus,
    Business,
    Job,
    JobStatus,
    MessageLog,
    PendingAction,
    Schedule,
    ScheduleStatus,
    ScheduleTemplate,
)
from wam.monitoring import alert
from wam.settings_defaults import get_setting, get_time_setting
from wam.state import purge_expired
from wam.windows import in_send_window, next_window_start

log = logging.getLogger(__name__)

MAX_JOB_ATTEMPTS = 3
# Automatic patient messages wait for the business's send window; staff-triggered sends go out at once.
WINDOWED_KINDS = {"missed_followup", "nudge_schedule"}


# --------------------------------------------------------------------------------------
# Scanners
# --------------------------------------------------------------------------------------


async def send_due_reminders(session: AsyncSession, business: Business) -> int:
    local = clock.local_now(business.timezone)
    if not in_send_window(business, local) or local.time() < get_time_setting(
        business.settings, "reminder_time"
    ):
        return 0
    tomorrow = local.date() + dt.timedelta(days=1)
    start, end = clock.day_bounds(tomorrow, business.timezone)
    appts = (
        (
            await session.execute(
                select(Appointment)
                .where(
                    Appointment.business_id == business.id,
                    Appointment.status.in_(AppointmentStatus.ACTIVE),
                    Appointment.reminder_sent_at.is_(None),
                    # just booked (the confirmation covers it); reminded later in the day instead
                    Appointment.created_at < clock.now() - dt.timedelta(hours=6),
                    Appointment.start_at >= start,
                    Appointment.start_at < end,
                )
                .order_by(Appointment.start_at)
                .limit(200)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    sent = 0
    for appt in appts:
        try:
            async with session.begin_nested():
                if await send_reminder(session, business, appt):
                    sent += 1
        except Exception:
            log.exception("reminder failed for appointment %s", appt.id)
    return sent


async def send_due_nudges(session: AsyncSession, business: Business) -> int:
    local = clock.local_now(business.timezone)
    if not in_send_window(business, local) or local.time() < get_time_setting(
        business.settings, "reminder_time"
    ):
        return 0
    today = local.date()
    renudge = dt.timedelta(days=int(get_setting(business.settings, "renudge_after_days")))
    max_nudges = int(get_setting(business.settings, "max_nudges"))
    now = clock.now()
    schedules = (
        (
            await session.execute(
                select(Schedule)
                .where(
                    Schedule.business_id == business.id,
                    Schedule.status == ScheduleStatus.ACTIVE,
                    Schedule.next_due_date.is_not(None),
                    Schedule.next_due_date <= today,
                    or_(Schedule.last_nudged_at.is_(None), Schedule.last_nudged_at < now - renudge),
                )
                .order_by(Schedule.next_due_date, Schedule.id)
                .limit(200)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    sent = 0
    for schedule in schedules:
        try:
            async with session.begin_nested():
                if schedule.template.kind == "payment":
                    continue  # fee plans follow send_payment_reminders
                if await active_appointment_for_schedule(session, schedule.id) is not None:
                    continue
                if schedule.nudge_count >= max_nudges:
                    if not schedule.needs_staff:
                        await flag_to_staff(
                            session,
                            business,
                            schedule.contact,
                            f"{schedule.template.name} is overdue and {schedule.nudge_count} reminders got no booking.",
                            schedule,
                        )
                    continue
                if await nudge_schedule(session, business, schedule):
                    sent += 1
        except Exception:
            log.exception("nudge failed for schedule %s", schedule.id)
    return sent


async def send_payment_reminders(session: AsyncSession, business: Business) -> int:
    """Fee installments: a reminder `days_before` the due date, one on the due date, then overdue reminders
    every few days; after `max_nudges` overdue reminders the family is flagged to staff."""
    local = clock.local_now(business.timezone)
    if not in_send_window(business, local) or local.time() < get_time_setting(
        business.settings, "reminder_time"
    ):
        return 0
    today = local.date()
    horizon = today + dt.timedelta(days=30)
    renudge = dt.timedelta(days=int(get_setting(business.settings, "renudge_after_days")))
    max_nudges = int(get_setting(business.settings, "max_nudges"))
    rows = (
        (
            await session.execute(
                select(Schedule)
                .join(ScheduleTemplate, ScheduleTemplate.id == Schedule.template_id)
                .where(
                    Schedule.business_id == business.id,
                    Schedule.status == ScheduleStatus.ACTIVE,
                    ScheduleTemplate.kind == "payment",
                    Schedule.next_due_date.is_not(None),
                    Schedule.next_due_date <= horizon,
                )
                .order_by(Schedule.next_due_date)
                .limit(500)
            )
        )
        .scalars()
        .unique()
        .all()
    )
    sent = 0
    for schedule in rows:
        due = schedule.next_due_date
        assert due is not None
        days_before = int((schedule.template.reminder_rules or {}).get("days_before", 3))
        if today < due - dt.timedelta(days=days_before):
            continue
        last = (
            clock.to_local(schedule.last_nudged_at, business.timezone).date()
            if schedule.last_nudged_at
            else None
        )
        overdue_sent = max(schedule.nudge_count - 2, 0)  # before-due + due-day reminders come first
        send = False
        if last is None:
            send = True
        elif today >= due and last < due:
            send = True  # due-day reminder
        elif today > due and clock.now() - (schedule.last_nudged_at or clock.now()) >= renudge:
            if overdue_sent < max_nudges:
                send = True
            elif not schedule.needs_staff:
                await flag_to_staff(
                    session,
                    business,
                    schedule.contact,
                    f"{schedule.template.name}: installment due {clock.fmt_date(due)} is still unpaid after reminders.",
                    schedule,
                )
        if not send:
            continue
        try:
            async with session.begin_nested():
                if await send_payment_reminder(session, business, schedule):
                    sent += 1
        except Exception:
            log.exception("payment reminder failed for schedule %s", schedule.id)
    return sent


async def send_eod_check(session: AsyncSession, business: Business) -> bool:
    """At closing time, send the front desk today's list for attendance marking (once a day)."""
    from wam.staff.commands import Ctx, build_day_list

    local = clock.local_now(business.timezone)
    if local.time() < get_time_setting(business.settings, "eod_time"):
        return False
    today = local.date()
    key = f"eod:{business.id}:{today.isoformat()}"
    exists = (await session.execute(select(Job.id).where(Job.dedupe_key == key))).scalar_one_or_none()
    if exists is not None:
        return False
    session.add(
        Job(
            business_id=business.id,
            kind="eod_check",
            run_at=clock.now(),
            payload={},
            status=JobStatus.DONE,
            dedupe_key=key,
            finished_at=clock.now(),
        )
    )
    await session.flush()
    recipients = await staff_to_alert(session, business)
    for member in recipients:
        ctx = Ctx(session, business, member)
        await ctx.load()
        text_out, appts = await build_day_list(ctx, today, None, save_attendance=True)
        pending = [a for a in appts if a.status in AppointmentStatus.ACTIVE]
        if not pending:
            continue
        summary = (
            f"{len(pending)} of today's visits need attendance marking. Reply LIST to mark who didn't come"
        )
        await send_to_staff(
            session,
            business,
            member,
            Outgoing(text=text_out, template_key="staff_alert", template_values={"summary": summary}),
        )
    return True


async def run_retention(session: AsyncSession, business: Business) -> int:
    """Daily at ~03:00 local: delete message logs past the retention period."""
    local = clock.local_now(business.timezone)
    if local.hour != 3:
        return 0
    key = f"retention:{business.id}:{local.date().isoformat()}"
    if (await session.execute(select(Job.id).where(Job.dedupe_key == key))).scalar_one_or_none():
        return 0
    session.add(
        Job(
            business_id=business.id,
            kind="retention",
            run_at=clock.now(),
            payload={},
            status=JobStatus.DONE,
            dedupe_key=key,
            finished_at=clock.now(),
        )
    )
    days = int(get_setting(business.settings, "retention_days"))
    cutoff = clock.now() - dt.timedelta(days=days)
    result = await session.execute(
        delete(MessageLog).where(MessageLog.business_id == business.id, MessageLog.created_at < cutoff)
    )
    await session.execute(
        delete(Job).where(
            Job.business_id == business.id,
            Job.status.in_([JobStatus.DONE, JobStatus.CANCELLED, JobStatus.FAILED]),
            Job.created_at < clock.now() - dt.timedelta(days=30),
            Job.dedupe_key != key,
        )
    )
    return result.rowcount or 0


# --------------------------------------------------------------------------------------
# Durable jobs table
# --------------------------------------------------------------------------------------


async def execute_job(session: AsyncSession, job: Job) -> None:
    business = await session.get(Business, job.business_id)
    if business is None or not business.is_active:
        job.status = JobStatus.CANCELLED
        return
    if job.kind == "missed_followup":
        appt = await session.get(Appointment, int(job.payload["appointment_id"]))
        if appt is None:
            job.status = JobStatus.CANCELLED
            return
        result = await followup_missed(session, business, appt)
        if result == "sent":
            gap = dt.timedelta(hours=int(get_setting(business.settings, "second_followup_after_hours")))
            attempt = appt.followup_count + 1
            await schedule_job(
                session,
                business.id,
                "missed_followup",
                clock.now() + gap,
                {"appointment_id": appt.id},
                dedupe_key=f"missed_followup:{appt.id}:{attempt}",
            )
        return
    if job.kind == "nudge_schedule":
        schedule = await session.get(Schedule, int(job.payload["schedule_id"]))
        if schedule is not None:
            await nudge_schedule(session, business, schedule)
        return
    if job.kind in ("broadcast_send", "broadcast_status"):
        from wam.models import Broadcast
        from wam.packs.institute import broadcasts

        broadcast = await session.get(Broadcast, int(job.payload["broadcast_id"]))
        if broadcast is None or broadcast.business_id != business.id:
            job.status = JobStatus.CANCELLED
            return
        if job.kind == "broadcast_status":
            await broadcasts.refresh_status(session, business, broadcast)
            return
        if await broadcasts.send_batch(session, business, broadcast):
            await _continue_job(session, job, "broadcast_send", "broadcast_id", broadcast.id)
        return
    if job.kind == "import_send":
        from wam.models import Import
        from wam.packs.institute import imports

        imp = await session.get(Import, int(job.payload["import_id"]))
        if imp is None or imp.business_id != business.id:
            job.status = JobStatus.CANCELLED
            return
        if await imports.send_batch(session, business, imp):
            await _continue_job(session, job, "import_send", "import_id", imp.id)
        return
    raise ValueError(f"unknown job kind {job.kind}")


async def _continue_job(session: AsyncSession, job: Job, kind: str, key: str, obj_id: int) -> None:
    """Queue the next batch of a long send right away (each batch is its own short job)."""
    part = int(job.payload.get("part", 0)) + 1
    await schedule_job(
        session,
        job.business_id,
        kind,
        clock.now(),
        {key: obj_id, "part": part},
        dedupe_key=f"{kind}:{obj_id}:{part}",
    )


async def run_due_jobs(limit: int = 50) -> int:
    """Claim and run due jobs (FOR UPDATE SKIP LOCKED so several workers can run safely)."""
    async with session_scope() as session:
        rows = (
            (
                await session.execute(
                    select(Job)
                    .where(Job.status == JobStatus.SCHEDULED, Job.run_at <= clock.now())
                    .order_by(Job.run_at)
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            .scalars()
            .all()
        )
        ids = [r.id for r in rows]
        for r in rows:
            r.status = JobStatus.RUNNING
            r.attempts += 1
            r.run_at = clock.now()  # claim time; lets recover_stuck_jobs spot crashed workers
    done = 0
    for job_id in ids:
        try:
            async with session_scope() as session:
                job = await session.get(Job, job_id)
                if job is None:
                    continue
                business = await session.get(Business, job.business_id)
                if business is not None and job.kind in WINDOWED_KINDS and not in_send_window(business):
                    job.status = JobStatus.SCHEDULED
                    job.attempts -= 1
                    job.run_at = next_window_start(business)
                    continue
                await execute_job(session, job)
                if job.status == JobStatus.RUNNING:
                    job.status = JobStatus.DONE
                job.finished_at = clock.now()
                done += 1
        except Exception as exc:
            log.exception("job %s failed", job_id)
            async with session_scope() as session:
                job = await session.get(Job, job_id)
                if job is not None:
                    job.last_error = f"{type(exc).__name__}: {exc}"[:1000]
                    if job.attempts >= MAX_JOB_ATTEMPTS:
                        job.status = JobStatus.FAILED
                        await alert(
                            f"Job {job.kind} #{job.id} failed {job.attempts} times: {type(exc).__name__}"
                        )
                    else:
                        job.status = JobStatus.SCHEDULED
                        job.run_at = clock.now() + dt.timedelta(minutes=10 * job.attempts)
    return done


async def recover_stuck_jobs() -> None:
    """Jobs left 'running' by a crashed worker go back to the queue after 15 minutes."""
    async with session_scope() as session:
        await session.execute(
            update(Job)
            .where(Job.status == JobStatus.RUNNING, Job.run_at < clock.now() - dt.timedelta(minutes=15))
            .values(status=JobStatus.SCHEDULED)
        )


# --------------------------------------------------------------------------------------
# Tick
# --------------------------------------------------------------------------------------


async def business_tick(business_id: int) -> dict[str, Any]:
    async with session_scope() as session:
        # One tick per business at a time, even with several workers.
        got = (
            await session.execute(text("SELECT pg_try_advisory_xact_lock(7001, :b)"), {"b": business_id})
        ).scalar_one()
        if not got:
            return {"skipped": True}
        business = await session.get(Business, business_id)
        if business is None or not business.is_active:
            return {"skipped": True}
        result = {
            "reminders": await send_due_reminders(session, business),
            "nudges": await send_due_nudges(session, business),
            "payment_reminders": await send_payment_reminders(session, business),
            "eod": await send_eod_check(session, business),
            "retention_deleted": await run_retention(session, business),
        }
        return result


async def tick(ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    results: dict[str, Any] = {}
    async with session_scope() as session:
        ids = list((await session.execute(select(Business.id).where(Business.is_active.is_(True)))).scalars())
        await purge_expired(session)
        await session.execute(
            update(PendingAction)
            .where(PendingAction.status == "pending", PendingAction.expires_at < clock.now())
            .values(status="expired")
        )
    for bid in ids:
        try:
            results[bid] = await business_tick(bid)
        except Exception as exc:
            log.exception("tick failed for business %s", bid)
            await alert(f"Scheduler tick failed for business {bid}: {type(exc).__name__}")
    await recover_stuck_jobs()
    results["jobs"] = await run_due_jobs()
    if results["jobs"] and ctx is not None and ctx.get("redis") is not None:
        await ctx["redis"].enqueue_job("run_jobs")  # long sends continue in batches right away
    if ctx is not None and ctx.get("redis") is not None:
        await ctx["redis"].set("wam:worker:heartbeat", str(int(clock.now().timestamp())), ex=600)
    return results
