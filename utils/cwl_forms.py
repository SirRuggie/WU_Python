"""Human-readable timing forms for the CWL editor; no scheduling syntax needed."""
from __future__ import annotations

import re
from datetime import date

import hikari


def _field(key, label, value="", *, required=True):
    return hikari.impl.ModalActionRowBuilder().add_text_input(
        key, label, value=str(value), required=required, max_length=80,
    )


def _time(value):
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*(am|pm)?\s*", str(value), re.I)
    if not match:
        raise ValueError("Enter a time such as 5:00 PM or 17:00.")
    hour, minute = int(match[1]), int(match[2])
    if minute > 59 or (match[3] and not 1 <= hour <= 12) or (not match[3] and hour > 23):
        raise ValueError("Enter a valid time such as 5:00 PM or 17:00.")
    if match[3]:
        hour = hour % 12 + (12 if match[3].lower() == "pm" else 0)
    return hour, minute


def _integer(value, label, minimum, maximum):
    if not str(value).strip().isdigit() or not minimum <= int(value) <= maximum:
        raise ValueError(f"{label} must be a whole number from {minimum} to {maximum}.")
    return int(value)


def _date(value):
    try:
        result = date.fromisoformat(str(value).strip())
    except ValueError as exc:
        raise ValueError("Enter the date as YYYY-MM-DD, for example 2026-10-29.") from exc
    return result.isoformat()


def _clock(rule):
    return f"{int(rule.get('hour', 17)):02d}:{int(rule.get('minute', 0)):02d}"


def schedule_form(schedule):
    mode = schedule.get("mode", "manual")
    if mode == "monthly":
        return "Monthly delivery", [
            _field("day", "Day of month (1–31)", schedule.get("day", 20)),
            _field("time", "Time (5:00 PM or 17:00)", _clock(schedule)),
        ]
    if mode == "specific":
        at = str(schedule.get("at", ""))
        return "One-time delivery", [
            _field("date", "Date (YYYY-MM-DD)", at[:10]),
            _field("time", "Time in campaign timezone", at[11:16] if len(at) > 15 else "17:00"),
        ]
    if mode in {"before_close", "after_open", "legacy_chain"}:
        minutes = int(schedule.get("offset_minutes", 1440))
        unit, factor = ("days", 1440) if minutes and minutes % 1440 == 0 else (("hours", 60) if minutes and minutes % 60 == 0 else ("minutes", 1))
        title = {"before_close": "Before signup deadline", "after_open": "After signups open", "legacy_chain": "After previous reminder"}[mode]
        return title, [_field("amount", "How long?", minutes // factor), _field("unit", "Unit: minutes, hours, or days", unit)]
    raise ValueError("Manual messages do not need a delivery time.")


def parse_schedule_fields(mode, values, *, previous=None):
    rule = {"mode": mode}
    if mode == "monthly":
        hour, minute = _time(values.get("time", ""))
        rule.update(day=_integer(values.get("day", ""), "Day", 1, 31), hour=hour, minute=minute)
    elif mode == "specific":
        hour, minute = _time(values.get("time", ""))
        rule["at"] = f"{_date(values.get('date', ''))}T{hour:02d}:{minute:02d}:00"
    elif mode in {"before_close", "after_open", "legacy_chain"}:
        unit = str(values.get("unit", "")).strip().lower().rstrip("s")
        factor = {"minute": 1, "hour": 60, "day": 1440}.get(unit)
        if factor is None:
            raise ValueError("Choose minutes, hours, or days.")
        rule["offset_minutes"] = _integer(values.get("amount", ""), "Delay", 0, 525600 // factor) * factor
        if mode == "legacy_chain":
            rule["after"] = (previous or {}).get("after", "signup")
    elif mode != "manual":
        raise ValueError("Choose a supported delivery timing option.")
    return rule


def deadline_mode(rule):
    return "specific" if rule.get("at") else ("day" if rule.get("day") else "month_end")


def deadline_form(rule, timezone_name, *, mode=None):
    mode = mode or deadline_mode(rule)
    if mode == "specific":
        at = str(rule.get("at", ""))
        field = _field("date", "Signup closing date (YYYY-MM-DD)", at[:10])
        clock = at[11:16] if len(at) > 15 else "17:00"
    elif mode == "day":
        field = _field("day", "Signup closing day of month (1–31)", rule.get("day", 29))
        clock = _clock(rule)
    elif mode == "month_end":
        field = _field("offset_days", "Days before the last day of the month", rule.get("month_end_offset_days", 2))
        clock = _clock(rule)
    else:
        raise ValueError("Choose a supported deadline option.")
    return [field, _field("time", "Closing time (5:00 PM or 17:00)", clock),
            _field("timezone", "Timezone", timezone_name)]


def parse_deadline_fields(mode, values):
    hour, minute = _time(values.get("time", ""))
    if mode == "specific":
        rule = {"at": f"{_date(values.get('date', ''))}T{hour:02d}:{minute:02d}:00"}
    elif mode == "day":
        rule = {"day": _integer(values.get("day", ""), "Day", 1, 31), "hour": hour, "minute": minute}
    elif mode == "month_end":
        rule = {"month_end_offset_days": _integer(values.get("offset_days", ""), "Days before month end", 0, 27), "hour": hour, "minute": minute}
    else:
        raise ValueError("Choose a supported deadline option.")
    timezone_name = str(values.get("timezone", "")).strip()
    if not timezone_name:
        raise ValueError("A timezone is required.")
    return rule, timezone_name
