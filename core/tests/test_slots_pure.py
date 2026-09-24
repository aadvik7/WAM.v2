import datetime as dt

from wam.engine.slots import BreakBlock, Slot, WeeklyBlock, compute_free_slots, pick_spread

TZ = "Asia/Kolkata"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
MONDAY = dt.date(2026, 10, 5)


def ist(day: dt.date, h: int, m: int = 0) -> dt.datetime:
    return dt.datetime(day.year, day.month, day.day, h, m, tzinfo=IST).astimezone(dt.UTC)


def slots_for(**overrides):
    params = dict(
        resource_id=1,
        tz_name=TZ,
        date_from=MONDAY,
        date_to=MONDAY,
        slot_minutes=30,
        duration_minutes=None,
        weekly=[WeeklyBlock(0, dt.time(10), dt.time(12))],
        breaks=[],
        leave=[],
        busy=[],
        earliest=ist(MONDAY, 0),
    )
    params.update(overrides)
    return compute_free_slots(**params)


def test_basic_grid():
    slots = slots_for()
    assert [s.start for s in slots] == [
        ist(MONDAY, 10),
        ist(MONDAY, 10, 30),
        ist(MONDAY, 11),
        ist(MONDAY, 11, 30),
    ]
    assert all(s.end - s.start == dt.timedelta(minutes=30) for s in slots)


def test_busy_and_notice_and_break_removed():
    slots = slots_for(
        busy=[(ist(MONDAY, 10, 30), ist(MONDAY, 11))],
        earliest=ist(MONDAY, 10, 1),
        breaks=[BreakBlock(None, dt.time(11, 30), dt.time(12))],
    )
    assert [s.start for s in slots] == [ist(MONDAY, 11)]


def test_leave_blocks_day_and_other_weekday_closed():
    leave = [(ist(MONDAY, 0), ist(MONDAY + dt.timedelta(days=1), 0))]
    assert slots_for(leave=leave) == []
    tuesday = MONDAY + dt.timedelta(days=1)
    assert slots_for(date_from=tuesday, date_to=tuesday) == []


def test_longer_duration_must_fit():
    slots = slots_for(duration_minutes=60)
    assert [s.start for s in slots] == [ist(MONDAY, 10), ist(MONDAY, 10, 30), ist(MONDAY, 11)]
    # a busy 10:30–11:00 blocks every 60-min slot overlapping it
    slots = slots_for(duration_minutes=60, busy=[(ist(MONDAY, 10, 30), ist(MONDAY, 11))])
    assert [s.start for s in slots] == [ist(MONDAY, 11)]


def test_slot_key_round_trip():
    slot = Slot(7, ist(MONDAY, 10, 30), ist(MONDAY, 11))
    rid, start = Slot.parse_key(slot.key)
    assert rid == 7 and start == slot.start


def test_pick_spread_prefers_one_per_day():
    weekly = [WeeklyBlock(d, dt.time(10), dt.time(12)) for d in range(0, 3)]
    slots = slots_for(weekly=weekly, date_to=MONDAY + dt.timedelta(days=2))
    picked = pick_spread(slots, 3, TZ)
    assert [p.start for p in picked] == [
        ist(MONDAY, 10),
        ist(MONDAY + dt.timedelta(days=1), 10),
        ist(MONDAY + dt.timedelta(days=2), 10),
    ]


def test_pick_spread_same_day_spaced():
    weekly = [WeeklyBlock(0, dt.time(9), dt.time(18))]
    slots = slots_for(weekly=weekly)
    picked = pick_spread(slots, 3, TZ)
    assert [p.start for p in picked] == [ist(MONDAY, 9), ist(MONDAY, 11), ist(MONDAY, 13)]
