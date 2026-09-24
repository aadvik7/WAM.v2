import datetime as dt
from types import SimpleNamespace

from wam.phone import extract_phone, normalize_phone
from wam.staff.dates import parse_date, parse_date_range, parse_offset_days, parse_time
from wam.staff.parser import parse_command

MON = dt.date(2026, 10, 5)
TEMPLATES = [
    SimpleNamespace(id=1, name="Root canal", aliases=["rct", "root canal treatment"]),
    SimpleNamespace(id=2, name="Cleaning recall", aliases=["cleaning"]),
]
RESOURCES = [SimpleNamespace(id=10, name="Dr. Mehta"), SimpleNamespace(id=11, name="Dr. Anil Rao")]


def cmd(text):
    return parse_command(text, TEMPLATES, RESOURCES)


def test_phone_normalisation():
    assert normalize_phone("98765 43210") == "+919876543210"
    assert normalize_phone("+91 98765-43210") == "+919876543210"
    assert normalize_phone("09876543210") == "+919876543210"
    assert normalize_phone("919876543210") == "+919876543210"
    assert normalize_phone("+14155550123") == "+14155550123"
    assert normalize_phone("12345") is None
    assert extract_phone("Rahul 98765 43210 root canal") == ("+919876543210", "Rahul root canal")


def test_times_and_dates():
    assert parse_time("5 pm") == dt.time(17)
    assert parse_time("5:30pm") == dt.time(17, 30)
    assert parse_time("17:30") == dt.time(17, 30)
    assert parse_time("11 am") == dt.time(11)
    assert parse_time("5") == dt.time(17)
    assert parse_time("Rahul") is None
    assert parse_date("friday", MON) == dt.date(2026, 10, 9)
    assert parse_date("monday", MON) == MON
    assert parse_date("next monday", MON) == dt.date(2026, 10, 12)
    assert parse_date("tomorrow", MON) == dt.date(2026, 10, 6)
    assert parse_date("12 oct", MON) == dt.date(2026, 10, 12)
    assert parse_date("Oct 12", MON) == dt.date(2026, 10, 12)
    assert parse_date("12/10", MON) == dt.date(2026, 10, 12)
    assert parse_date("3 jan", MON) == dt.date(2027, 1, 3)
    assert parse_date_range("12 oct to 14 oct", MON) == (dt.date(2026, 10, 12), dt.date(2026, 10, 14))
    assert parse_date_range("friday - monday", MON) == (dt.date(2026, 10, 9), dt.date(2026, 10, 12))
    assert parse_date_range("next 3 days", MON) == (MON, dt.date(2026, 10, 7))
    assert parse_offset_days("7 days") == 7
    assert parse_offset_days("2 weeks") == 14
    assert parse_offset_days("3 months") == 90


def test_spec_commands():
    assert cmd("Today's list").key == "today"
    assert cmd("tomorrow's list").args["day_offset"] == 1
    assert cmd("today's list for dr rao").args["resource_id"] == 11
    c = cmd("Cancel my 5 pm")
    assert c.key == "cancel" and c.args == {"target": "5 pm", "resource_id": None}
    assert cmd("cancel dr mehta 5pm").args == {"target": "5pm", "resource_id": 10}
    assert cmd("Running 20 min late").args == {"minutes": 20, "resource_id": None}
    assert cmd("Dr Rao running late by 15 minutes").args == {"minutes": 15, "resource_id": 11}
    c = cmd("On leave Friday")
    assert c.key == "leave" and c.args["when"] == "Friday"
    assert cmd("Dr Mehta is on leave 12 oct to 14 oct").args == {
        "when": "12 oct to 14 oct",
        "resource_id": 10,
    }
    c = cmd("Rahul, root canal")
    assert (
        c.key == "enrol"
        and c.args["name"] == "Rahul"
        and c.args["template_id"] == 1
        and c.args["phone"] is None
    )
    c = cmd("enrol Rahul Mehta 98765 43210 rct with dr mehta, 1 done")
    assert c.args["name"] == "Rahul Mehta" and c.args["phone"] == "+919876543210"
    assert c.args["resource_id"] == 10 and c.args["sessions_done"] == 1
    c = cmd("Follow-up for Rahul in 7 days")
    assert c.key == "followup" and c.args == {"who": "Rahul", "prep": "in", "when": "7 days"}
    assert cmd("YES 1234").args == {"pin": "1234"}
    assert cmd("yes").args == {"pin": None}
    assert cmd("no").key == "abort"
    assert cmd("2 5").args == {"missed": [2, 5]}
    assert cmd("3, 4 and 7").args == {"missed": [3, 4, 7]}
    assert cmd("none").args == {"missed": []}
    assert cmd("missed 3").args == {"missed": [3]}
    assert cmd("find Rahul").args == {"query": "Rahul"}
    assert cmd("summary").key == "summary"
    assert cmd("what's the weather") is None
