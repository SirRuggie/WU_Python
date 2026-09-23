import pytest

from utils.cwl_forms import deadline_form, parse_deadline_fields, parse_schedule_fields, schedule_form


@pytest.mark.parametrize("clock,hour", [("5:00 PM", 17), ("17:00", 17), ("12:00 AM", 0), ("12:00 pm", 12)])
def test_monthly_form_accepts_familiar_clock_formats(clock, hour):
    assert parse_schedule_fields("monthly", {"day": "20", "time": clock}) == {
        "mode": "monthly", "day": 20, "hour": hour, "minute": 0,
    }


def test_relative_form_round_trip_preserves_chain_anchor():
    schedule = {"mode": "legacy_chain", "offset_minutes": 2880, "after": "reminder:3"}
    _, components = schedule_form(schedule)
    values = {row.components[0].custom_id: row.components[0].value for row in components}
    assert values == {"amount": "2", "unit": "days"}
    assert parse_schedule_fields("legacy_chain", values, previous=schedule) == schedule


def test_deadline_month_end_form_round_trip():
    original = {"month_end_offset_days": 2, "hour": 17, "minute": 0}
    fields = deadline_form(original, "America/New_York")
    values = {row.components[0].custom_id: row.components[0].value for row in fields}
    assert parse_deadline_fields("month_end", values) == (original, "America/New_York")


def test_specific_date_combines_separate_user_fields():
    result = parse_schedule_fields("specific", {"date": "2028-02-29", "time": "5:30 PM"})
    assert result == {"mode": "specific", "at": "2028-02-29T17:30:00"}


@pytest.mark.parametrize("mode,values", [
    ("monthly", {"day": "32", "time": "17:00"}),
    ("monthly", {"day": "20", "time": "24:00"}),
    ("monthly", {"day": "20", "time": "0:00 PM"}),
    ("monthly", {"day": "20", "time": "5:60 PM"}),
    ("specific", {"date": "2026-02-29", "time": "17:00"}),
    ("before_close", {"amount": "-1", "unit": "hours"}),
    ("after_open", {"amount": "1", "unit": "months"}),
])
def test_invalid_timing_stays_a_user_facing_validation_error(mode, values):
    with pytest.raises(ValueError):
        parse_schedule_fields(mode, values)
