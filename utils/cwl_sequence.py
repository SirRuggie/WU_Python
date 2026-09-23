"""Pure planning helpers for bounded CWL reminder sequences."""

from __future__ import annotations

import copy
import re
from datetime import datetime

import pendulum


MAX_REMINDERS = 10
MAX_CAMPAIGN_MESSAGES = 12
MODES = {"evenly", "interval"}
REMINDER_IDS = tuple(f"reminder:{number}" for number in range(1, MAX_REMINDERS + 1))
_NUMBERED_REMINDER = re.compile(r"^reminder:([1-9]|10)$")


def _integer(name: str, value, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be a whole number from {minimum} to {maximum}.")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be from {minimum} to {maximum}.")
    return value


def _settings(campaign: dict) -> dict | None:
    value = campaign.get("reminder_sequence")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Reminder sequence settings are invalid. Reopen the dashboard and save them again.")
    return value


def validate(campaign: dict) -> None:
    """Validate sequence settings without requiring the sequence to be enabled."""
    if not isinstance(campaign, dict) or not isinstance(campaign.get("messages"), dict):
        raise ValueError("Campaign messages are missing.")
    settings = _settings(campaign)
    if settings is None:
        return
    enabled = settings.get("enabled")
    if not isinstance(enabled, bool):
        raise ValueError("Reminder sequence enabled must be true or false.")
    if not enabled:
        return
    mode = settings.get("mode")
    if mode not in MODES:
        raise ValueError("Reminder sequence mode must be `evenly` or `interval`.")
    _integer("Reminder count", settings.get("count"), 1, MAX_REMINDERS)
    _integer("Interval hours", settings.get("interval_hours"), 1, 744)
    _integer("Final reminder hours", settings.get("final_hours"), 1, 744)
    minimum_gap = _integer("Minimum gap hours", settings.get("min_gap_hours"), 1, 24)
    if mode == "interval" and settings["interval_hours"] < minimum_gap:
        raise ValueError(
            "Interval hours must be at least the minimum gap so reminders cannot bunch together."
        )
    numbered = {key for key in campaign["messages"] if _NUMBERED_REMINDER.fullmatch(str(key))}
    if not numbered:
        raise ValueError("An enabled reminder sequence needs at least one numbered reminder slot.")
    if mode == "evenly":
        _require_slots(campaign, settings["count"])
    if len(campaign["messages"]) > MAX_CAMPAIGN_MESSAGES:
        raise ValueError("A reminder sequence supports at most 12 campaign messages in total.")


def _new_title(number: int) -> str:
    return f"CWL Sign-up Reminder #{number}"


def _provision(campaign: dict) -> None:
    messages = campaign["messages"]
    if len(messages) > MAX_CAMPAIGN_MESSAGES:
        raise ValueError("A reminder sequence supports at most 12 campaign messages in total.")

    existing = []
    for key, message in messages.items():
        match = _NUMBERED_REMINDER.fullmatch(str(key))
        if match and isinstance(message, dict):
            existing.append((int(match.group(1)), message))
    if existing:
        source = max(existing, key=lambda item: item[0])[1]
    else:
        source = messages.get("signup")
    if not isinstance(source, dict):
        raise ValueError(
            "Add a signup or reminder message before enabling a reminder sequence."
        )

    for number, message_id in enumerate(REMINDER_IDS, start=1):
        if message_id in messages:
            continue
        if len(messages) >= MAX_CAMPAIGN_MESSAGES:
            break
        item = copy.deepcopy(source)
        item["label"] = f"Sign-up reminder {number}"
        item["schedule"] = {"mode": "manual"}
        variants = item.get("variants")
        if not isinstance(variants, dict):
            raise ValueError("The reminder template has no Main/Lazy message versions to copy.")
        for variant in variants.values():
            if isinstance(variant, dict):
                variant["title"] = _new_title(number)
        messages[message_id] = item


def _slot_capacity(campaign: dict) -> int:
    """Number of consecutive usable reminder ids beginning with reminder:1."""
    messages = campaign.get("messages", {})
    capacity = 0
    for message_id in REMINDER_IDS:
        if message_id not in messages:
            break
        capacity += 1
    return capacity


def _require_slots(campaign: dict, required: int) -> None:
    capacity = _slot_capacity(campaign)
    if required > capacity:
        raise ValueError(
            f"Custom messages leave {capacity} reminder slots, but this plan needs {required}; "
            "reduce count or increase interval hours."
        )


def configure(
    campaign: dict,
    mode: str,
    count: int = 4,
    interval_hours: int = 48,
    final_hours: int = 3,
    min_gap_hours: int = 3,
) -> dict:
    """Return an independent campaign with an explicitly enabled sequence."""
    if not isinstance(campaign, dict) or not isinstance(campaign.get("messages"), dict):
        raise ValueError("Campaign messages are missing.")
    if mode not in MODES:
        raise ValueError("Reminder sequence mode must be `evenly` or `interval`.")
    settings = {
        "enabled": True,
        "mode": mode,
        "count": _integer("Reminder count", count, 1, MAX_REMINDERS),
        "interval_hours": _integer("Interval hours", interval_hours, 1, 744),
        "final_hours": _integer("Final reminder hours", final_hours, 1, 744),
        "min_gap_hours": _integer("Minimum gap hours", min_gap_hours, 1, 24),
    }
    result = copy.deepcopy(campaign)
    result["reminder_sequence"] = settings
    _provision(result)
    validate(result)
    return result


def _instant(value, label: str) -> pendulum.DateTime:
    if isinstance(value, pendulum.DateTime):
        result = value
    elif isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(f"{label} must include a timezone.")
        result = pendulum.instance(value)
    else:
        raise ValueError(f"{label} must be a timezone-aware date and time.")
    if result.tzinfo is None:
        raise ValueError(f"{label} must include a timezone.")
    return result


def _at_elapsed_hours(opening: pendulum.DateTime, hours: float) -> pendulum.DateTime:
    """Add elapsed hours across DST, then return in the opening timezone."""
    utc = opening.in_timezone("UTC").add(seconds=hours * 3600)
    return utc.in_timezone(opening.timezone_name)


def _elapsed_hours(start: pendulum.DateTime, end: pendulum.DateTime) -> float:
    return (
        end.in_timezone("UTC").timestamp() - start.in_timezone("UTC").timestamp()
    ) / 3600


def _check_gaps(
    opening: pendulum.DateTime,
    deadline: pendulum.DateTime,
    times: list[pendulum.DateTime],
    minimum_gap: int,
) -> None:
    previous = opening
    for index, value in enumerate(times, start=1):
        if not opening < value < deadline:
            raise ValueError(
                f"Reminder #{index} must run after signups open and before they close."
            )
        gap = _elapsed_hours(previous, value)
        if gap + 1e-9 < minimum_gap:
            raise ValueError(
                f"The signup window is too short: reminder #{index} would be only {gap:.1f} hours after the previous event. Reduce the reminder count or minimum gap."
            )
        previous = value


def plan(campaign: dict, opening, deadline) -> dict[str, pendulum.DateTime | None]:
    """Resolve an enabled sequence using elapsed time, including across DST."""
    output = {message_id: None for message_id in REMINDER_IDS}
    validate(campaign)
    settings = _settings(campaign)
    if settings is None or settings.get("enabled") is not True:
        return output

    start = _instant(opening, "Signup opening")
    close = _instant(deadline, "Signup deadline").in_timezone(start.timezone_name)
    window_hours = _elapsed_hours(start, close)
    if window_hours <= 0:
        raise ValueError("Signup deadline must be after signups open.")

    final_hours = settings["final_hours"]
    final = _at_elapsed_hours(close, -final_hours)
    if final <= start:
        raise ValueError(
            "The signup window is too short for the final reminder. Open signups earlier or reduce final reminder hours."
        )

    if settings["mode"] == "evenly":
        count = settings["count"]
        usable_hours = _elapsed_hours(start, final)
        times = [
            _at_elapsed_hours(start, usable_hours * index / count)
            for index in range(1, count + 1)
        ]
    else:
        interval = settings["interval_hours"]
        times = []
        index = 1
        while True:
            candidate = _at_elapsed_hours(start, interval * index)
            if candidate >= final:
                break
            times.append(candidate)
            index += 1
        if times and _elapsed_hours(times[-1], final) < settings["min_gap_hours"]:
            times.pop()
        times.append(final)
        if len(times) > MAX_REMINDERS:
            raise ValueError(
                "This interval creates more than 10 reminders. Increase interval hours."
            )

    _check_gaps(start, close, times, settings["min_gap_hours"])
    _require_slots(campaign, len(times))
    for index, value in enumerate(times, start=1):
        output[f"reminder:{index}"] = value
    return output
