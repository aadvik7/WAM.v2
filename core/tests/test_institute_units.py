import datetime as dt
from decimal import Decimal

import pytest

from wam.packs.institute.sheets import SheetError, is_absent, parse_clock, parse_sheet_date, read_sheet
from wam.packs.institute.timetable import is_timetable_question, requested_day
from wam.people import fmt_inr

MON = dt.date(2026, 10, 5)


def test_read_sheet_finds_header_and_aliases():
    csv = "Bright Future Academy — attendance\n\nRoll No.;Name of Student;P/A\n12;Aarav;A\n15;Diya;P\n\n"
    rows, cols = read_sheet("att.csv", csv.encode())
    assert cols == ["name", "roll", "status"]
    assert rows == [
        {"roll": "12", "name": "Aarav", "status": "A"},
        {"roll": "15", "name": "Diya", "status": "P"},
    ]


def test_read_sheet_errors():
    with pytest.raises(SheetError, match="header row"):
        read_sheet("x.csv", b"a,b\n1,2\n")
    with pytest.raises(SheetError, match="empty"):
        read_sheet("x.csv", b"")
    with pytest.raises(SheetError, match=r"\.xls"):
        read_sheet("old.xls", b"\xd0\xcf\x11\xe0")


def test_cell_parsers():
    assert is_absent("A") is True and is_absent("present") is False and is_absent("?") is None
    assert parse_clock("8:00 AM") == dt.time(8) and parse_clock("2.30 pm") == dt.time(14, 30)
    assert parse_clock("14:05") == dt.time(14, 5) and parse_clock("25:00") is None
    assert parse_sheet_date("13/10/2026") == dt.date(2026, 10, 13)
    assert parse_sheet_date("2026-10-13") == dt.date(2026, 10, 13)


def test_fmt_inr_indian_grouping():
    assert fmt_inr(12000) == "₹12,000"
    assert fmt_inr(Decimal("120000")) == "₹1,20,000"
    assert fmt_inr(Decimal("12345678.50")) == "₹1,23,45,678.50"
    assert fmt_inr(999) == "₹999"


def test_timetable_questions():
    assert is_timetable_question("What's my timetable tomorrow?")
    assert is_timetable_question("kal ki class kab hai")
    assert not is_timetable_question("what are the fees")
    assert requested_day("timetable tomorrow", MON) == MON + dt.timedelta(days=1)
    assert requested_day("classes on friday?", MON) == MON + dt.timedelta(days=4)
    assert requested_day("timetable 13/10", MON) == dt.date(2026, 10, 13)
    assert requested_day("timetable", MON) == MON
