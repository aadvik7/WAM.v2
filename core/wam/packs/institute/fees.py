"""Fee installments: reminders before each due date (see flows.send_payment_reminder) and recording payments."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.engine import schedules as sched_engine
from wam.models import Business, Contact, Schedule, ScheduleStatus, ScheduleTemplate
from wam.people import children_of, fmt_inr


async def fee_plans(session: AsyncSession, contact: Contact, *, only_active: bool = True) -> list[Schedule]:
    """Payment plans of this contact and of their children."""
    ids = [contact.id] + [c.id for c in await children_of(session, contact)]
    stmt = (
        select(Schedule)
        .join(ScheduleTemplate, ScheduleTemplate.id == Schedule.template_id)
        .where(Schedule.contact_id.in_(ids), ScheduleTemplate.kind == "payment")
        .order_by(Schedule.next_due_date.nulls_last(), Schedule.id)
    )
    if only_active:
        stmt = stmt.where(Schedule.status == ScheduleStatus.ACTIVE)
    return list((await session.execute(stmt)).scalars().unique().all())


def amount_of(schedule: Schedule) -> str | None:
    amount = schedule.amount if schedule.amount is not None else schedule.template.amount
    return fmt_inr(amount) if amount is not None else None


def plan_line(schedule: Schedule, business: Business, with_name: bool) -> str:
    total = f" of {schedule.sessions_total}" if schedule.sessions_total else ""
    who = f"{schedule.contact.name}: " if with_name and schedule.contact.name else ""
    if schedule.status == ScheduleStatus.COMPLETED or schedule.next_due_date is None:
        return f"{who}{schedule.template.name} fully paid."
    amount = amount_of(schedule)
    today = clock.local_today(business.timezone)
    due = clock.fmt_date(schedule.next_due_date)
    state = "was due" if schedule.next_due_date < today else "is due"
    money = f" of {amount}" if amount else ""
    return (
        f"{who}installment {schedule.sessions_done + 1}{total}{money} {state} on {due} "
        f"({schedule.sessions_done} paid so far)."
    )


async def status_text(session: AsyncSession, business: Business, contact: Contact) -> str:
    plans = await fee_plans(session, contact)
    if not plans:
        return "I don't see any fee installments due. For fee questions, the office will help."
    many = len({p.contact_id for p in plans}) > 1 or plans[0].contact_id != contact.id
    return "\n".join(plan_line(p, business, many) for p in plans)


async def record_payment(session: AsyncSession, business: Business, schedule: Schedule) -> str:
    await sched_engine.record_payment(session, schedule)
    await session.flush()
    name = schedule.contact.name or "the student"
    if schedule.status == ScheduleStatus.COMPLETED:
        return f"Recorded. {name}'s {schedule.template.name} is now fully paid."
    due = clock.fmt_date(schedule.next_due_date) if schedule.next_due_date else "-"
    return (
        f"Recorded installment {schedule.sessions_done} for {name}. "
        f"Next installment is due on {due}; I'll remind the family before then."
    )
