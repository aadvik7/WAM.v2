"""Slot engine.

free slots = availability − existing appointments − leave (and breaks),
respecting slot length and a minimum notice period.

`compute_free_slots` is a pure function (easy to test); `find_free_slots` loads data from the DB.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from wam import clock
from wam.models import Appointment, AppointmentStatus, Availability, Business, Resource
from wam.settings_defaults import get_setting

Interval = tuple[dt.datetime, dt.datetime]


@dataclass(frozen=True)
class Slot:
    resource_id: int
    start: dt.datetime  # UTC
    end: dt.datetime  # UTC

    @property
    def key(self) -> str:
        """Stable token for a slot: '<resource_id>@<UTC ISO start>'."""
        return f"{self.resource_id}@{self.start.astimezone(dt.UTC).strftime('%Y-%m-%dT%H:%M')}"

    @staticmethod
    def parse_key(key: str) -> tuple[int, dt.datetime]:
        rid, _, iso = key.partition("@")
        start = dt.datetime.strptime(iso, "%Y-%m-%dT%H:%M").replace(tzinfo=dt.UTC)
        return int(rid), start


@dataclass(frozen=True)
class WeeklyBlock:
    weekday: int  # 0=Mon
    start: dt.time
    end: dt.time


@dataclass(frozen=True)
class BreakBlock:
    weekday: int | None  # None => every day
    start: dt.time
    end: dt.time


def _subtract(intervals: list[Interval], cut: Interval) -> list[Interval]:
    out: list[Interval] = []
    cs, ce = cut
    for s, e in intervals:
        if ce <= s or cs >= e:
            out.append((s, e))
            continue
        if cs > s:
            out.append((s, cs))
        if ce < e:
            out.append((ce, e))
    return out


def _overlaps(a: Interval, b: Interval) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _merge(intervals: list[Interval]) -> list[Interval]:
    out: list[Interval] = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return out


def working_intervals(
    day: dt.date,
    tz_name: str,
    weekly: Sequence[WeeklyBlock],
    breaks: Sequence[BreakBlock],
    leave: Sequence[Interval],
    extra: Sequence[Interval] = (),
) -> list[Interval]:
    """Open intervals (UTC) for one local day: weekly hours minus breaks, plus one-off extra hours,
    minus leave (leave always wins)."""
    zone = ZoneInfo(tz_name)
    wd = day.weekday()
    intervals: list[Interval] = []
    for block in weekly:
        if block.weekday != wd:
            continue
        start = dt.datetime.combine(day, block.start, tzinfo=zone).astimezone(dt.UTC)
        end = dt.datetime.combine(day, block.end, tzinfo=zone).astimezone(dt.UTC)
        if end > start:
            intervals.append((start, end))
    intervals.sort()
    for br in breaks:
        if br.weekday is not None and br.weekday != wd:
            continue
        bs = dt.datetime.combine(day, br.start, tzinfo=zone).astimezone(dt.UTC)
        be = dt.datetime.combine(day, br.end, tzinfo=zone).astimezone(dt.UTC)
        intervals = _subtract(intervals, (bs, be))
    if extra:
        day_start = dt.datetime.combine(day, dt.time(0), tzinfo=zone).astimezone(dt.UTC)
        day_end = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0), tzinfo=zone).astimezone(dt.UTC)
        for es, ee in extra:
            s, e = max(es, day_start), min(ee, day_end)
            if e > s:
                intervals.append((s, e))
        intervals = _merge(intervals)
    for lv in leave:
        intervals = _subtract(intervals, lv)
    return intervals


def compute_free_slots(
    *,
    resource_id: int,
    tz_name: str,
    date_from: dt.date,
    date_to: dt.date,
    slot_minutes: int,
    duration_minutes: int | None,
    weekly: Sequence[WeeklyBlock],
    breaks: Sequence[BreakBlock],
    leave: Sequence[Interval],
    busy: Sequence[Interval],
    earliest: dt.datetime,
    limit: int | None = None,
    extra: Sequence[Interval] = (),
    step_minutes: int | None = None,
) -> list[Slot]:
    """All free slots for one resource between two local dates (inclusive).

    Slots start on the slot grid (block start + n × slot_minutes) and last `duration_minutes`
    (defaults to slot_minutes). A slot must fit inside one open interval, must not overlap a busy
    interval and must start at or after `earliest`.
    """
    step = dt.timedelta(minutes=step_minutes or slot_minutes)
    length = dt.timedelta(minutes=duration_minutes or slot_minutes)
    busy_sorted = sorted(busy)
    slots: list[Slot] = []
    day = date_from
    while day <= date_to:
        for open_start, open_end in working_intervals(day, tz_name, weekly, breaks, leave, extra):
            # Grid anchored at the start of the weekly block (not at a break end) keeps times tidy.
            cursor = open_start
            while cursor + length <= open_end:
                candidate = (cursor, cursor + length)
                if cursor >= earliest and not any(_overlaps(candidate, b) for b in busy_sorted):
                    slots.append(Slot(resource_id, cursor, cursor + length))
                    if limit is not None and len(slots) >= limit:
                        return slots
                cursor += step
        day += dt.timedelta(days=1)
    return slots


def pick_spread(slots: Sequence[Slot], count: int, tz_name: str) -> list[Slot]:
    """Pick `count` slots to offer: the earliest slot on each of the first days, then fill.

    Offering 10:00, 10:15 and 10:30 on the same day is a weak choice; one per day across the first
    available days gives the patient real options. If there are fewer days than `count`, fill with
    later slots at least 2 hours apart from ones already chosen on that day.
    """
    if count <= 0 or not slots:
        return []
    zone = ZoneInfo(tz_name)
    chosen: list[Slot] = []
    seen_days: set[dt.date] = set()
    for slot in slots:
        d = slot.start.astimezone(zone).date()
        if d not in seen_days:
            seen_days.add(d)
            chosen.append(slot)
            if len(chosen) == count:
                return sorted(chosen, key=lambda s: s.start)
    for slot in slots:
        if slot in chosen:
            continue
        if all(abs((slot.start - c.start).total_seconds()) >= 7200 for c in chosen):
            chosen.append(slot)
            if len(chosen) == count:
                break
    if len(chosen) < count:
        for slot in slots:
            if slot not in chosen:
                chosen.append(slot)
                if len(chosen) == count:
                    break
    return sorted(chosen, key=lambda s: s.start)


# --------------------------------------------------------------------------------------
# DB-backed helpers
# --------------------------------------------------------------------------------------


async def load_availability(
    session: AsyncSession, resource_id: int, window: Interval
) -> tuple[list[WeeklyBlock], list[BreakBlock], list[Interval], list[Interval]]:
    rows = (
        (await session.execute(select(Availability).where(Availability.resource_id == resource_id)))
        .scalars()
        .all()
    )
    weekly: list[WeeklyBlock] = []
    breaks: list[BreakBlock] = []
    leave: list[Interval] = []
    extra: list[Interval] = []
    for row in rows:
        if row.kind == "weekly" and row.weekday is not None and row.start_time and row.end_time:
            weekly.append(WeeklyBlock(row.weekday, row.start_time, row.end_time))
        elif row.kind == "break" and row.start_time and row.end_time:
            breaks.append(BreakBlock(row.weekday, row.start_time, row.end_time))
        elif row.kind in ("leave", "extra") and row.start_at and row.end_at:
            if _overlaps((row.start_at, row.end_at), window):
                (leave if row.kind == "leave" else extra).append((row.start_at, row.end_at))
    return weekly, breaks, leave, extra


async def load_busy(
    session: AsyncSession,
    resource_id: int,
    window: Interval,
    exclude_appointment_id: int | None = None,
) -> list[Interval]:
    stmt = select(Appointment.start_at, Appointment.end_at).where(
        Appointment.resource_id == resource_id,
        Appointment.status.in_(AppointmentStatus.ACTIVE),
        Appointment.start_at < window[1],
        Appointment.end_at > window[0],
    )
    if exclude_appointment_id is not None:
        stmt = stmt.where(Appointment.id != exclude_appointment_id)
    return [(s, e) for s, e in (await session.execute(stmt)).all()]


def earliest_bookable(business: Business, now: dt.datetime | None = None) -> dt.datetime:
    now = now or clock.now()
    notice = int(get_setting(business.settings, "min_notice_minutes"))
    return now + dt.timedelta(minutes=notice)


async def find_free_slots(
    session: AsyncSession,
    business: Business,
    resource: Resource,
    date_from: dt.date,
    date_to: dt.date,
    duration_minutes: int | None = None,
    limit: int | None = None,
    exclude_appointment_id: int | None = None,
    step_minutes: int | None = None,
) -> list[Slot]:
    horizon = int(get_setting(business.settings, "booking_horizon_days"))
    today = clock.local_today(business.timezone)
    date_from = max(date_from, today)
    date_to = min(date_to, today + dt.timedelta(days=horizon))
    if date_to < date_from:
        return []
    window = (
        clock.day_bounds(date_from, business.timezone)[0],
        clock.day_bounds(date_to, business.timezone)[1],
    )
    weekly, breaks, leave, extra = await load_availability(session, resource.id, window)
    busy = await load_busy(session, resource.id, window, exclude_appointment_id)
    return compute_free_slots(
        resource_id=resource.id,
        tz_name=business.timezone,
        date_from=date_from,
        date_to=date_to,
        slot_minutes=resource.slot_minutes,
        duration_minutes=duration_minutes,
        weekly=weekly,
        breaks=breaks,
        leave=leave,
        busy=busy,
        earliest=earliest_bookable(business),
        limit=limit,
        extra=extra,
        step_minutes=step_minutes,
    )


async def active_resources(session: AsyncSession, business_id: int) -> list[Resource]:
    return list(
        (
            await session.execute(
                select(Resource)
                .where(Resource.business_id == business_id, Resource.is_active.is_(True))
                .order_by(Resource.id)
            )
        )
        .scalars()
        .all()
    )


async def offer_slots(
    session: AsyncSession,
    business: Business,
    resources: Iterable[Resource],
    date_from: dt.date,
    count: int | None = None,
    duration_minutes: int | None = None,
    days: int = 14,
    exclude_appointment_id: int | None = None,
) -> list[Slot]:
    """Pick up to `count` well-spread free slots across the given resources, from `date_from`."""
    count = count or int(get_setting(business.settings, "offer_slot_count"))
    date_to = date_from + dt.timedelta(days=days)
    all_slots: list[Slot] = []
    for resource in resources:
        all_slots.extend(
            await find_free_slots(
                session,
                business,
                resource,
                date_from,
                date_to,
                duration_minutes=duration_minutes,
                limit=200,
                exclude_appointment_id=exclude_appointment_id,
            )
        )
    all_slots.sort(key=lambda s: (s.start, s.resource_id))
    return pick_spread(all_slots, count, business.timezone)
