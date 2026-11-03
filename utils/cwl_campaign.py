"""Durable, editable CWL campaigns shared by the dashboard and scheduler.

The public functions in this module intentionally return plain dictionaries.
Discord interaction state may therefore keep only a draft id while commands,
tests, and the reminder task all use the same stored representation.
"""

from __future__ import annotations

import copy
import re
import uuid
from datetime import datetime, timezone
from urllib.parse import urlparse

import hikari
import pendulum
from utils.dashboard_urls import (
    SIGNUP_URL, ASSIGNMENTS_URL, DASHBOARD_ORIGIN, TASKS_URL, WARS_URL,
    LEGACY_DASHBOARD_ORIGIN,
)
from pymongo.errors import DuplicateKeyError
from hikari.impl import (
    ContainerComponentBuilder as Container,
    LinkButtonBuilder as LinkButton,
    InteractiveButtonBuilder as InteractiveButton,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID


SCHEMA_VERSION = 1
DEFAULT_COPY_VERSION = 127
DEFAULT_COPY_FIELD = "default_copy_version"
SHORT_SIGNUP_CHECK_LINE = "Tap **Check my signups** to see your accounts."
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_GUILD_ID = 0
LEGACY_WU_GUILD_ID = WARRIORS_UNITED_GUILD_ID
AUDIENCES = ("main", "lazy")
MESSAGE_ORDER = ("signup", "reminder:1", "reminder:2", "reminder:3", "reminder:4", "reminder:5", "roster")
HISTORY_LIMIT = 100
SIGNUP_HELP_LINE = "-# Having trouble with the dashboard? Ping staff—we can help."
SIGNUP_CHECK_ID = "cwl_member_check:open"
SIGNUP_CHECK_LINE = "Already signed up? Tap **Check my signups** anytime to see your accounts."
_CYCLE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SKIP_OCCURRENCE = object()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uses_new_default_copy(value: dict | None) -> bool:
    version = value.get(DEFAULT_COPY_FIELD) if isinstance(value, dict) else None
    return type(version) is int and version == DEFAULT_COPY_VERSION


def cycle_key(now=None, timezone_name: str = DEFAULT_TIMEZONE) -> str:
    value = pendulum.instance(now, tz=timezone_name) if now else pendulum.now(timezone_name)
    return value.format("YYYY-MM")


def defaults_id(guild_id: int) -> str:
    return f"cwl:defaults:{int(guild_id)}"


def cycle_id(guild_id: int, cycle: str) -> str:
    return f"cwl:cycle:{int(guild_id)}:{cycle}"


def draft_id(guild_id: int, token: str) -> str:
    return f"cwl:draft:{int(guild_id)}:{token}"


def _buttons(*items):
    return [dict(zip(("label", "url", "emoji"), item)) for item in items]


def _variant(*, title, body, media_url, channel_id, role_ids, buttons):
    return {
        "enabled": True,
        "title": title,
        "body": body,
        "media_url": media_url,
        "destination_channel_id": channel_id,
        "role_ids": role_ids,
        "buttons": buttons,
    }


LEGACY_SIGNUP_MAIN = (
        "Below are the two signup forms required to participate here in Warriors United CWL. "
        "LazyCWL is an option for all within the Family but if your in one of our FWA Clans "
        "it's \"Lazy Way or No Way\".\n\nThe forms take less then a couple minutes to complete "
        "and the sooner you sign up the better it is on us making Rosters.\n\n"
        "Direct all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"
    )
LEGACY_SIGNUP_LAZY = (
        "The below form is required to participate within the Warriors United Lazy CWL Operation.\n\n"
        "The form take less then a couple minutes to complete and the sooner you sign up the better "
        "it is on us making Rosters.\n\nRemember...if you are in one of our FWA Clans it's "
        "\"LAZY WAY OR NO WAY!!\" Outside involvement is not permitted.\n\n"
        "Direct all questions and concerns in <#872692009066958879> <:warriorcat:947992348971905035>"
    )


def signup_buttons() -> list[dict]:
    """Website signup plus a private, read-only saved-signup check."""
    return [{"label": "Sign up for CWL", "url": SIGNUP_URL},
            {"label": "Check my signups", "custom_id": SIGNUP_CHECK_ID}]


LEGACY_ROSTER_URLS = (
    "https://docs.google.com/spreadsheets/d/1GcNVWyx5HjoDm5AbQAOT0_pwyf95KRl_f4lQ0Up3ZBM/edit?usp=sharing",
    "https://docs.google.com/spreadsheets/d/1GxIuathFuro-xdYM9rVcF2Sob9lyFgDsT7TekkkuK-E/edit#gid=512888016",
)


def normalize_signup_entry(campaign: dict) -> dict:
    """Upgrade signup destinations without changing delivery state or custom copy."""
    result = copy.deepcopy(campaign)
    new_default_copy = _uses_new_default_copy(result)
    for message_id, message in result.get("messages", {}).items():
        for item in message.get("variants", {}).values():
            item["body"] = item.get("body", "").replace(LEGACY_DASHBOARD_ORIGIN, DASHBOARD_ORIGIN)
            for button in item.get("buttons", []):
                url = button.get("url", "")
                if url.startswith(LEGACY_DASHBOARD_ORIGIN + "/") or url == LEGACY_DASHBOARD_ORIGIN:
                    button["url"] = DASHBOARD_ORIGIN + url[len(LEGACY_DASHBOARD_ORIGIN):]
                if message_id == "roster" and url in LEGACY_ROSTER_URLS:
                    button["url"] = ASSIGNMENTS_URL
                    button["label"] = "My assignments"
                    item["body"] = item.get("body", "").replace(
                        "The Clan Links are on the Spreadsheet.",
                        "Open My assignments below to see your published clan and its join link.",
                    )
        if message_id != "signup" and not message_id.startswith("reminder:"):
            continue
        for pool, item in message.get("variants", {}).items():
            item["buttons"] = signup_buttons()
            legacy = LEGACY_SIGNUP_MAIN if pool == "main" else LEGACY_SIGNUP_LAZY
            replacement = _legacy_dashboard_signup_body(pool)
            if replacement and legacy in item.get("body", ""):
                item["body"] = item["body"].replace(legacy, replacement)
            if (
                SIGNUP_CHECK_LINE not in item.get("body", "")
                and not (new_default_copy and SHORT_SIGNUP_CHECK_LINE in item.get("body", ""))
            ):
                proposed = item.get("body", "").rstrip() + "\n\n" + SIGNUP_CHECK_LINE
                overhead = len(" ".join(f"<@&{role}>" for role in item.get("role_ids", []))) + len(item.get("title", "")) + 3 + len(SIGNUP_HELP_LINE)
                if "{signup_deadline}" in proposed:
                    overhead += 32
                if len(proposed) + overhead <= 4000:
                    item["body"] = proposed
    return result



def _legacy_dashboard_signup_body(pool: str) -> str:
    """Keep the established read-only legacy migration independent of new defaults."""
    signup_main = (
        "Sign up for CWL on our website.\n\n"
        "1. Select **Sign up for CWL** below.\n"
        "2. Sign in with Discord.\n"
        "3. Choose Main or Lazy CWL, then select your accounts.\n"
        "4. Check your choices and select **Sign up**.\n\n"
        "FWA clan members must choose Lazy CWL.\n"
        "Need help? Ask in <#801950200133976124>."
    )
    signup_lazy = (
        "Sign up for Lazy CWL on our website.\n\n"
        "1. Select **Sign up for CWL** below.\n"
        "2. Sign in with Discord.\n"
        "3. Choose **Lazy CWL**, then select your accounts.\n"
        "4. Check your choices and select **Sign up**.\n\n"
        "FWA clan members must choose Lazy CWL.\n"
        "Need help? Ask in <#872692009066958879>."
    )
    return signup_main if pool == "main" else signup_lazy

def default_campaign(*, new_copy: bool = True) -> dict:
    """Provision current copy, or the exact compatibility fallback for saved data."""
    role = 1080521665584308286
    main_channel = 1072714594625257502
    lazy_channel = 865726525990633472
    main_buttons = signup_buttons()
    lazy_buttons = signup_buttons()
    signup_main = (
        "Sign up for CWL on our dashboard.\n\n"
        "FWA clan members must choose Lazy CWL.\n\n"
        "1. Select **Sign up for CWL** below.\n"
        "2. Sign in with Discord.\n"
        "3. Choose Main or Lazy CWL, then select your accounts.\n"
        "4. Check your choices and select **Sign up**.\n\n"
        "Need help? Ask in <#801950200133976124>."
    )
    signup_lazy = (
        "Sign up for Lazy CWL on our dashboard.\n\n"
        "FWA clan members must choose Lazy CWL.\n\n"
        "1. Select **Sign up for CWL** below.\n"
        "2. Sign in with Discord.\n"
        "3. Choose **Lazy CWL**, then select your accounts.\n"
        "4. Check your choices and select **Sign up**.\n\n"
        "Need help? Ask in <#872692009066958879>."
    )
    if not new_copy:
        # Existing records retain their previous missing-field fallback copy.
        signup_main = _legacy_dashboard_signup_body("main")
        signup_lazy = _legacy_dashboard_signup_body("lazy")
    reminder_media = {
        1: "https://c.tenor.com/6b2bCHLqrUkAAAAd/tenor.gif",
        2: "https://media.tenor.com/0XVm8XNzxFUAAAAj/its-not-too-late-to-get-involved-engage.gif",
        3: "https://c.tenor.com/t-scOJYZGPEAAAAC/tenor.gif",
        4: "https://c.tenor.com/fc51xvY2Tq4AAAAd/tenor.gif",
        5: "https://c.tenor.com/egVC6wj7VV8AAAAC/tenor.gif",
    }
    messages = {
        "signup": {
            "enabled": True,
            "label": "Signups open",
            "schedule": {"mode": "monthly", "day": 20, "hour": 17, "minute": 0},
            "variants": {
                "main": _variant(title="<:CWL:1399013745598009375> CWL Time <:CWL:1399013745598009375>", body=signup_main, media_url="assets/Gold_Footer.png", channel_id=main_channel, role_ids=[role], buttons=main_buttons),
                "lazy": _variant(title="<:CWL:1399013745598009375> CWL Time <:CWL:1399013745598009375>", body=signup_lazy, media_url="assets/Gold_Footer.png", channel_id=lazy_channel, role_ids=[role], buttons=lazy_buttons),
            },
        },
        "roster": {
            "enabled": True,
            "label": "Rosters released",
            "schedule": {"mode": "manual"},
            "variants": {
                "main": _variant(
                    title="<:league_medal:949137422933962753> CWL Time <:league_medal:949137422933962753>",
                    body="Rosters are out! Tap **My clan assignments** to find your clan.\n\nFinish both attacks in your current war, then move to your clan. __The sooner the better.__\n\nQuestions? Ask in <#801950200133976124> <:warriorcat:947992348971905035>",
                    media_url="https://c.tenor.com/aXIInybKvOwAAAAd/tenor.gif", channel_id=main_channel, role_ids=[role],
                    buttons=_buttons(("My clan assignments", ASSIGNMENTS_URL, "📋"), ("My tasks", TASKS_URL, "✅"), ("Wars", WARS_URL, "⚔️")),
                ),
                "lazy": _variant(
                    title="<:league_medal:949137422933962753> Lazy CWL Time <:league_medal:949137422933962753>",
                    body="Lazy rosters are out! Tap **My clan assignments** to find your clan.\n\nFinish both attacks in your current war, then move to your clan. __The sooner the better.__\n\nNeed help? Ping <@&769130325460254740> in <#872692009066958879>.",
                    media_url="https://c.tenor.com/aXIInybKvOwAAAAd/tenor.gif", channel_id=lazy_channel, role_ids=[role],
                    buttons=_buttons(("My clan assignments", ASSIGNMENTS_URL, "😴"), ("My tasks", TASKS_URL, "✅"), ("Wars", WARS_URL, "⚔️"), ("LazyCWL Guide", "https://docs.google.com/document/d/137zYF4CHwW-hqwZXzDVmQWONkao1X-XckjGs5Myg-h0/edit", "📖")),
                ),
            },
        },
    }
    for number in range(1, 6):
        prefix = "**Already signed up? You're set!** Not yet? Sign up below.\nTap **Check my signups** to see your accounts.\n\n"
        if not new_copy:
            prefix = "**If you already signed up, we got ya down. No need to sign up again. But everyone else...**\n\n"
        messages[f"reminder:{number}"] = {
            "enabled": True,
            "label": f"Sign-up reminder {number}",
            "schedule": {"mode": "legacy_chain", "after": "signup" if number == 1 else f"reminder:{number - 1}", "offset_minutes": 24 * 60},
            "variants": {
                "main": _variant(title=f"<:CWL:1399013745598009375> Sign-up Reminder #{number} <:CWL:1399013745598009375>", body=prefix + signup_main + "\n\n# **Signups close {signup_deadline}**", media_url=reminder_media[number], channel_id=main_channel, role_ids=[role], buttons=main_buttons),
                "lazy": _variant(title=f"<:CWL:1399013745598009375> Sign-up Reminder #{number} <:CWL:1399013745598009375>", body=prefix + signup_lazy + "\n\n# **Signups close {signup_deadline}**", media_url=reminder_media[number], channel_id=lazy_channel, role_ids=[role], buttons=lazy_buttons),
            },
        }
    if not new_copy:
        messages["roster"]["variants"]['main']['body'] = 'Below are the CWL Rosters. Once your attacks are complete, make your way to your assigned Clan.\n\nOpen My assignments below to see your published clan and its join link. You can also find them in <#1114047624216068136>\n\nDirect all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>'
        messages["roster"]["variants"]['main']['buttons'] = [{'label': 'My assignments', 'url': ASSIGNMENTS_URL, 'emoji': '📋'}]
        messages["roster"]["variants"]['lazy']['body'] = "Below are the Lazy CWL Rosters. If you cannot view the Roster or do not understand it, please ping <@&769130325460254740> in <#872692009066958879> and we'll get it sorted.\n\nAs soon as both your attacks are complete in the current war make your way to your assigned Clan. __The sooner the better.__\n\nThere are several Bots in the server that can provide war information. To many to list here. Feel free to play around in <#1128848663872028743>. War and CWL are good keywords for looking."
        messages["roster"]["variants"]['lazy']['buttons'] = [{'label': 'My assignments', 'url': ASSIGNMENTS_URL, 'emoji': '😴'}, {'label': 'LazyCWL Guide', 'url': 'https://docs.google.com/document/d/137zYF4CHwW-hqwZXzDVmQWONkao1X-XckjGs5Myg-h0/edit', 'emoji': '📖'}]
    return {
        "schema_version": SCHEMA_VERSION,
        **({DEFAULT_COPY_FIELD: DEFAULT_COPY_VERSION} if new_copy else {}),
        "timezone": DEFAULT_TIMEZONE,
        "paused": False,
        "reminder_sequence": {"enabled": False},
        "signup_deadline": {"month_end_offset_days": 2, "hour": 17, "minute": 0},
        "messages": {key: messages[key] for key in MESSAGE_ORDER},
    }


def _deep_merge(base: dict, override: dict | None) -> dict:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if key == "schedule" and isinstance(value, dict) and "mode" in value:
            # A complete timing rule replaces the prior choice: never blend a
            # saved day-of-month rule with a new before-month-end rule.
            result[key] = copy.deepcopy(value)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def _legacy_override(schedule: dict | None) -> dict:
    if not schedule:
        return {}
    result = {}
    if all(schedule.get(key) is not None for key in ("day", "hour", "minute")):
        result = {"messages": {"signup": {"schedule": {
            "mode": "monthly", "day": int(schedule["day"]),
            "hour": int(schedule["hour"]), "minute": int(schedule["minute"]),
            "missing_day": "skip",
        }}}}
    followups = schedule.get("followups", [])
    messages = result.setdefault("messages", {})
    for item in followups:
        number = item.get("number")
        if isinstance(number, int) and 1 <= number <= 5:
            messages[f"reminder:{number}"] = {
                "enabled": bool(item.get("enabled", True)),
                "schedule": {
                    "mode": "legacy_chain",
                    "after": "signup" if number == 1 else f"reminder:{number - 1}",
                    "offset_minutes": max(0, int(item.get("delay_minutes", 0))),
                },
            }
    return result


def campaign_from_legacy(schedule: dict | None) -> dict:
    """Snapshot global legacy timing into guild-scoped monthly defaults."""
    return _deep_merge(default_campaign(new_copy=not bool(schedule)), _legacy_override(schedule))


def _month(cycle: str, timezone_name: str):
    if not _CYCLE_RE.match(cycle):
        raise ValueError("cycle must use YYYY-MM")
    year, month = map(int, cycle.split("-"))
    return pendulum.datetime(year, month, 1, tz=timezone_name)


def signup_deadline(campaign: dict, cycle: str):
    tz = campaign.get("timezone", DEFAULT_TIMEZONE)
    month = _month(cycle, tz)
    rule = campaign.get("signup_deadline", {})
    if isinstance(rule, dict):
        month = month.add(months=int(rule.get("month_offset", 0)))
    if isinstance(rule, str):
        return pendulum.parse(rule, tz=tz).in_timezone(tz)
    if rule.get("at"):
        return pendulum.parse(rule["at"], tz=tz).in_timezone(tz)
    if rule.get("day"):
        day = min(int(rule["day"]), month.end_of("month").day)
        return month.replace(day=day, hour=int(rule.get("hour", 17)), minute=int(rule.get("minute", 0)), second=0)
    return month.end_of("month").subtract(days=int(rule.get("month_end_offset_days", 2))).replace(
        hour=int(rule.get("hour", 17)), minute=int(rule.get("minute", 0)), second=0, microsecond=0
    )


def _resolve_one(schedule: dict, *, month, deadline, resolved):
    mode = schedule.get("mode", "manual")
    if mode == "manual":
        return None
    if mode == "monthly":
        month = month.add(months=int(schedule.get("month_offset", 0)))
        day, hour, minute = _monthly_parts(schedule)
        if "month_end_offset_days" in schedule:
            day = month.end_of("month").day - int(schedule["month_end_offset_days"])
        if day > month.end_of("month").day:
            if schedule.get("missing_day") == "skip":
                return _SKIP_OCCURRENCE
            day = month.end_of("month").day
        return month.replace(day=day, hour=hour, minute=minute, second=0)
    if mode == "specific":
        return pendulum.parse(schedule["at"], tz=month.timezone_name).in_timezone(month.timezone_name)
    if mode == "before_close":
        return deadline.subtract(minutes=_offset_minutes(schedule))
    if mode in {"after_open", "legacy_chain"}:
        source = "signup" if mode == "after_open" else schedule.get("after", "signup")
        if source not in resolved:
            return None
        if resolved[source] is _SKIP_OCCURRENCE:
            return _SKIP_OCCURRENCE
        return resolved[source].add(minutes=_offset_minutes(schedule))
    raise ValueError(f"Unsupported schedule mode: {mode}")


def _offset_minutes(schedule: dict) -> int:
    value = schedule.get("offset_minutes", schedule.get("delay_minutes", schedule.get("offset", 0)))
    if isinstance(value, (int, float)):
        return max(0, int(value))
    match = re.fullmatch(r"\s*(\d+)\s*(m|min|minute|minutes|h|hour|hours|d|day|days)?\s*", str(value), re.I)
    if not match:
        raise ValueError("Schedule offset must look like `30 minutes`, `12 hours`, or `2 days`")
    amount = int(match.group(1))
    unit = (match.group(2) or "minutes").lower()
    if unit.startswith("h"):
        amount *= 60
    elif unit.startswith("d"):
        amount *= 1440
    return amount


def _monthly_parts(schedule: dict) -> tuple[int, int, int]:
    if "month_end_offset_days" in schedule:
        if "day" in schedule or schedule.get("time"):
            raise ValueError("Choose either a day of month or days before month end, not both.")
        offset = schedule["month_end_offset_days"]
        if isinstance(offset, bool) or not str(offset).isdigit() or not 0 <= int(offset) <= 27:
            raise ValueError("Days before month end must be a whole number from 0 to 27.")
    if schedule.get("time"):
        match = re.fullmatch(r"\s*(\d{1,2})\s+(\d{1,2}):(\d{2})\s*", str(schedule["time"]))
        if not match:
            raise ValueError("Monthly schedule must look like `20 17:00`")
        day, hour, minute = map(int, match.groups())
    else:
        day = int(schedule.get("day", 1))
        hour = int(schedule.get("hour", 0))
        minute = int(schedule.get("minute", 0))
    if not 1 <= day <= 31 or not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Monthly schedule day or time is outside its valid range")
    return day, hour, minute


def _schedule_for(campaign: dict, message_id: str, message: dict) -> dict:
    transitional_schedules = campaign.get("schedules") or {}
    transitional = transitional_schedules.get(message_id)
    return transitional if isinstance(transitional, dict) and transitional else message.get("schedule", {})


def occurrence_id(cycle: str, message_id: str, variant: str) -> str:
    return f"{cycle}|{message_id}|{variant}"


def resolve_schedule(campaign: dict, cycle: str, now=None) -> list[dict]:
    """Resolve all schedule modes to concrete local and UTC timestamps."""
    validate_campaign(campaign)
    tz = campaign.get("timezone", DEFAULT_TIMEZONE)
    month = _month(cycle, tz)
    deadline = signup_deadline(campaign, cycle)
    sequence_times = {}
    if campaign.get("reminder_sequence", {}).get("enabled"):
        from utils import cwl_sequence
        opening = _resolve_one(_schedule_for(campaign, "signup", campaign["messages"]["signup"]), month=month, deadline=deadline, resolved={})
        if opening is None or opening is _SKIP_OCCURRENCE:
            raise ValueError("Choose a signup opening date before configuring reminders.")
        sequence_times = cwl_sequence.plan(campaign, opening, deadline)
    resolved = {}
    output = []
    pending = list(campaign.get("messages", {}))
    for _ in range(len(pending) + 1):
        progressed = False
        for message_id in list(pending):
            message = campaign["messages"][message_id]
            schedule = _schedule_for(campaign, message_id, message)
            if schedule.get("mode") == "legacy_chain" and not schedule.get("after"):
                try:
                    number = int(message_id.partition(":")[2])
                except ValueError:
                    number = 1
                schedule = {**schedule, "after": "signup" if number <= 1 else f"reminder:{number - 1}"}
            when = (_SKIP_OCCURRENCE if sequence_times[message_id] is None else sequence_times[message_id]) if message_id in sequence_times else _resolve_one(schedule, month=month, deadline=deadline, resolved=resolved)
            mode = schedule.get("mode", "manual")
            if when is None and mode != "manual":
                continue
            pending.remove(message_id)
            progressed = True
            if when is _SKIP_OCCURRENCE:
                resolved[message_id] = _SKIP_OCCURRENCE
                continue
            if when is not None:
                resolved[message_id] = when
            for variant in AUDIENCES:
                item = message.get("variants", {}).get(variant)
                if not message.get("enabled", True) or not item or not item.get("enabled", True):
                    continue
                run_at = when.isoformat() if when is not None else None
                output.append({
                    "id": occurrence_id(cycle, message_id, variant),
                    "cycle": cycle, "message_id": message_id, "variant": variant,
                    "mode": mode,
                    "message_key": message_id,
                    "run_at": run_at,
                    "at": run_at,
                    "run_at_utc": when.in_timezone("UTC").isoformat() if when is not None else None,
                })
        if not pending or not progressed:
            break
    if pending:
        raise ValueError("Campaign schedules contain an unresolved or cyclic dependency")
    output.sort(key=lambda item: (item["run_at"] is None, item["run_at"] or "", item["message_id"], item["variant"]))
    return output


def _safe_url(value: str, *, media=False):
    if media and value == "assets/Gold_Footer.png":
        return True
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def validate_campaign(campaign: dict) -> None:
    if not isinstance(campaign, dict) or not isinstance(campaign.get("messages"), dict):
        raise ValueError("Campaign messages are missing")
    if not 1 <= len(campaign["messages"]) <= 25:
        raise ValueError("A campaign must contain between 1 and 25 messages")
    from utils import cwl_sequence
    cwl_sequence.validate(campaign)
    try:
        pendulum.timezone(campaign.get("timezone", DEFAULT_TIMEZONE))
    except Exception as exc:
        raise ValueError("Campaign timezone is invalid") from exc
    timezone_name = campaign.get("timezone", DEFAULT_TIMEZONE)
    deadline_rule = campaign.get("signup_deadline", {})
    try:
        if isinstance(deadline_rule, str):
            pendulum.parse(deadline_rule, tz=timezone_name)
        elif isinstance(deadline_rule, dict):
            hour, minute = int(deadline_rule.get("hour", 17)), int(deadline_rule.get("minute", 0))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
            if "at" in deadline_rule:
                if not isinstance(deadline_rule["at"], str) or not deadline_rule["at"].strip():
                    raise ValueError
                pendulum.parse(deadline_rule["at"], tz=timezone_name)
            elif "day" in deadline_rule:
                if isinstance(deadline_rule["day"], bool) or not 1 <= int(deadline_rule["day"]) <= 31:
                    raise ValueError
            elif "month_end_offset_days" in deadline_rule:
                offset = deadline_rule["month_end_offset_days"]
                if isinstance(offset, bool) or not 0 <= int(offset) <= 27:
                    raise ValueError
            else:
                raise ValueError
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Signup deadline is invalid") from exc
    transitional_schedules = campaign.get("schedules")
    if transitional_schedules is not None and not isinstance(transitional_schedules, dict):
        raise ValueError("Legacy campaign schedules are invalid")
    for message_id, message in campaign["messages"].items():
        if not isinstance(message_id, str) or not re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", message_id):
            raise ValueError("A campaign message id is invalid")
        if not isinstance(message, dict) or not isinstance(message.get("variants"), dict):
            raise ValueError(f"{message_id} variants are missing")
        for variant, item in message["variants"].items():
            if variant not in AUDIENCES or not isinstance(item, dict):
                raise ValueError(f"{message_id} has an invalid audience")
            if not str(item.get("title", "")).strip() or not str(item.get("body", "")).strip():
                raise ValueError(f"{message_id}/{variant} text is incomplete")
            roles = item.get("role_ids", [])
            if not isinstance(roles, list) or len(roles) > 10 or any(
                not isinstance(role, int) or role <= 0 for role in roles
            ):
                raise ValueError(f"{message_id}/{variant} pings are invalid")
            mention_text = " ".join(f"<@&{role}>" for role in roles)
            rendered_length = len(mention_text) + len(item["title"]) + 3 + len(item["body"])
            if message_id == "signup" or message_id.startswith("reminder:"):
                rendered_length += len(SIGNUP_HELP_LINE)
            if "{signup_deadline}" in item["body"]:
                rendered_length += 32
            if rendered_length > 4000:
                raise ValueError(f"{message_id}/{variant} text exceeds Discord's 4,000-character limit")
            media = item.get("media_url")
            if media and (not isinstance(media, str) or not _safe_url(media, media=True)):
                raise ValueError(f"{message_id}/{variant} image URL is invalid")
            channel = item.get("destination_channel_id")
            if not isinstance(channel, int) or channel <= 0:
                raise ValueError(f"{message_id}/{variant} destination is invalid")
            buttons = item.get("buttons", [])
            if not isinstance(buttons, list) or len(buttons) > 5:
                raise ValueError(f"{message_id}/{variant} buttons are invalid")
            for button in buttons:
                if not isinstance(button, dict):
                    raise ValueError(f"{message_id}/{variant} button is invalid")
                if button == {"label": "Check my signups", "custom_id": SIGNUP_CHECK_ID} and (message_id == "signup" or message_id.startswith("reminder:")):
                    continue
                label, url = str(button.get("label", "")).strip(), str(button.get("url", ""))
                if not label or len(label) > 80 or len(url) > 512 or not _safe_url(url):
                    raise ValueError(f"{message_id}/{variant} button is invalid")
                emoji = button.get("emoji")
                if emoji:
                    try:
                        hikari.Emoji.parse(emoji)
                    except (TypeError, ValueError) as exc:
                        raise ValueError(f"{message_id}/{variant} button emoji is invalid") from exc
        schedule = _schedule_for(campaign, message_id, message)
        if not isinstance(schedule, dict):
            raise ValueError(f"{message_id} schedule is invalid")
        mode = schedule.get("mode", "manual")
        if mode not in {"monthly", "after_open", "before_close", "specific", "manual", "legacy_chain"}:
            raise ValueError(f"{message_id} schedule mode is invalid")
        if mode == "monthly":
            _monthly_parts(schedule)
        elif mode == "specific":
            try:
                pendulum.parse(schedule["at"], tz=campaign.get("timezone", DEFAULT_TIMEZONE))
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"{message_id} specific date is invalid") from exc
        elif mode in {"after_open", "before_close", "legacy_chain"}:
            _offset_minutes(schedule)


async def render_message(config: dict, message_id: str, variant: str, preview: bool = True):
    """Build the exact Components V2 message used for preview and delivery."""
    campaign = normalize_signup_entry(config.get("campaign", config))
    validate_campaign(campaign)
    try:
        message = campaign["messages"][message_id]
        item = message["variants"][variant]
    except KeyError as exc:
        raise ValueError("Unknown CWL message or audience") from exc
    deadline = config.get("deadline")
    body = item["body"]
    if deadline:
        deadline_value = pendulum.parse(deadline) if isinstance(deadline, str) else deadline
        body = body.replace("{signup_deadline}", f"<t:{int(deadline_value.timestamp())}:F>")
    children = []
    if item.get("role_ids"):
        children.append(Text(content=" ".join(f"<@&{role}>" for role in item["role_ids"])))
        children.append(Separator(divider=True))
    children.extend([Text(content=f"## {item['title']}"), Separator(divider=True), Text(content=body)])
    if item.get("media_url"):
        children.append(Media(items=[MediaItem(media=item["media_url"])]))
    buttons = []
    for button in item.get("buttons", []):
        if button.get("custom_id") == SIGNUP_CHECK_ID:
            buttons.append(InteractiveButton(style=hikari.ButtonStyle.SECONDARY, custom_id=SIGNUP_CHECK_ID, label="Check my signups"))
            continue
        kwargs = {"url": button["url"], "label": button["label"]}
        if button.get("emoji"):
            kwargs["emoji"] = button["emoji"]
        buttons.append(LinkButton(**kwargs))
    if buttons:
        children.append(ActionRow(components=buttons))
    if message_id == "signup" or message_id.startswith("reminder:"):
        children.append(Separator(divider=True))
        children.append(Text(content=SIGNUP_HELP_LINE))
    return [Container(accent_color=int(message.get("accent_color", GOLDENROD_ACCENT)), components=children)]


async def validate_destinations(bot, campaign: dict, guild_id: int) -> None:
    """Verify every configured destination is a channel in this guild."""
    cache = getattr(bot, "cache", None)
    checked = {}
    for message in campaign.get("messages", {}).values():
        for item in message.get("variants", {}).values():
            channel_id = int(item["destination_channel_id"])
            if channel_id in checked:
                channel = checked[channel_id]
            else:
                channel = (
                    cache.get_guild_channel(channel_id)
                    if cache and hasattr(cache, "get_guild_channel") else None
                )
                if channel is None:
                    channel = await bot.rest.fetch_channel(channel_id)
                checked[channel_id] = channel
            channel_guild = getattr(channel, "guild_id", None)
            if channel_guild is None or int(channel_guild) != int(guild_id):
                raise ValueError("Every CWL destination must be a channel in this server")


async def _legacy(mongo):
    collection = getattr(mongo, "cwl_reminder", None)
    return await collection.find_one({"_id": "schedule"}) if collection is not None else None


def _saved_copy_baseline(campaign: dict | None) -> dict:
    return default_campaign(new_copy=_uses_new_default_copy(campaign))


async def load_defaults_campaign(mongo, guild_id: int) -> dict:
    """Defaults editor baseline, without importing a cycle's custom message copy.

    Only a genuinely new setup gets newly provisioned copy. Existing unmarked
    metadata, partial records, cycles and legacy settings retain their fallback.
    Reads do not backfill or rewrite any record.
    """
    saved = await mongo.bot_config.find_one({"_id": defaults_id(guild_id)})
    if saved and isinstance(saved.get("campaign"), dict):
        return _deep_merge(_saved_copy_baseline(saved["campaign"]), saved["campaign"])
    legacy = await _legacy(mongo) if int(guild_id) == LEGACY_WU_GUILD_ID else None
    if legacy:
        return campaign_from_legacy(legacy)
    existing_cycle = await mongo.bot_config.find_one({"kind": "cwl_campaign_cycle", "guild_id": int(guild_id)})
    return default_campaign(new_copy=not bool(saved or existing_cycle))


async def load_campaign(mongo, guild_id: int, cycle: str | None = None, now=None) -> dict:
    guild_id = int(guild_id)
    saved = await mongo.bot_config.find_one({"_id": defaults_id(guild_id)})
    base = _saved_copy_baseline(saved.get("campaign")) if saved else default_campaign()
    legacy = None
    if saved and isinstance(saved.get("campaign"), dict):
        base = _deep_merge(base, saved["campaign"])
    elif guild_id == LEGACY_WU_GUILD_ID and (legacy := await _legacy(mongo)):
        base = _deep_merge(default_campaign(new_copy=False), _legacy_override(legacy))
    selected_cycle = cycle or cycle_key(now, base.get("timezone", DEFAULT_TIMEZONE))
    row = await mongo.bot_config.find_one({"_id": cycle_id(guild_id, selected_cycle)})
    override = copy.deepcopy(row.get("campaign")) if row else None
    recurring_rows = await mongo.bot_config.find({
        "kind": "cwl_campaign_cycle", "guild_id": guild_id,
        "recurring_campaign": {"$exists": True},
    }).to_list(length=None)
    recurring_rows = [item for item in recurring_rows if item.get("cycle", "") <= selected_cycle]
    recurring = max(recurring_rows, key=lambda item: item.get("recurring_updated_at", ""), default=None)
    if recurring and recurring["_id"] != (row or {}).get("_id"):
        if recurring.get("recurring_updated_at", "") >= (row or {}).get("updated_at", ""):
            override = copy.deepcopy(recurring["recurring_campaign"])
    if isinstance(override, dict):
        # Older saved cycle snapshots predate the sequence feature. They keep
        # their individual schedules when future defaults adopt a sequence.
        override.setdefault("reminder_sequence", {"enabled": False})
    previous = []
    has_saved_cycles = False
    if row is None:
        previous = await mongo.bot_config.find({"kind": "cwl_campaign_cycle", "guild_id": guild_id}).to_list(length=None)
        has_saved_cycles = bool(previous)
        previous = [item for item in previous if item.get("cycle", "") < selected_cycle and isinstance(item.get("campaign"), dict)]
    if not saved and not legacy and (row or recurring_rows or has_saved_cycles):
        base = default_campaign(new_copy=False)
    # Full cycle snapshots are independent of future monthly defaults,
    # including newly provisioned sequence templates and sequence settings.
    campaign = _deep_merge(_saved_copy_baseline(override) if isinstance(override, dict) and "schema_version" in override else base, override)
    if isinstance(override, dict) and not _uses_new_default_copy(override):
        campaign.pop(DEFAULT_COPY_FIELD, None)
    if row is None:
        # Carry only destinations forward, not old messages, dates or delivery state.
        candidates = previous + ([saved] if saved and isinstance(saved.get("campaign"), dict) else [])
        for pool in ("main", "lazy"):
            for source in sorted(candidates, key=lambda item: str(item.get("updated_at", "")), reverse=True):
                channel = source["campaign"].get("messages", {}).get("roster", {}).get("variants", {}).get(pool, {}).get("destination_channel_id")
                if channel:
                    campaign["messages"]["roster"]["variants"][pool]["destination_channel_id"] = channel
                    break
    campaign = normalize_signup_entry(campaign)
    validate_campaign(campaign)
    deliveries = copy.deepcopy((row or {}).get("deliveries", []))
    sent_occurrences = list((row or {}).get("sent_occurrences", []))
    skipped = list((row or {}).get("skipped", []))
    result = {
        "guild_id": guild_id,
        "cycle": selected_cycle,
        "revision": int((row or {}).get("revision", 0)),
        "defaults_revision": int((saved or {}).get("revision", 0)),
        "activated": bool((row or {}).get("activated") or (saved or {}).get("activated") or recurring),
        "recurring_version": (recurring or {}).get("recurring_updated_at"),
        "campaign": campaign,
        "deliveries": deliveries,
        "sent_occurrences": sent_occurrences,
        "uncertain_occurrences": list((row or {}).get("uncertain_occurrences", [])),
        "skipped": skipped,
        "deadline": signup_deadline(campaign, selected_cycle).isoformat(),
    }
    result["schedule"] = resolve_schedule(campaign, selected_cycle, now=now)
    return result


async def new_draft(mongo, guild_id: int, user_id: int, cycle: str | None = None, scope: str = "cycle") -> dict:
    if scope not in {"cycle", "defaults"}:
        raise ValueError("scope must be cycle or defaults")
    loaded = await load_campaign(mongo, guild_id, cycle)
    campaign = loaded["campaign"]
    if scope == "defaults":
        campaign = await load_defaults_campaign(mongo, guild_id)
    now = _utcnow()
    token = uuid.uuid4().hex
    draft = {
        "_id": draft_id(guild_id, token), "token": token, "kind": "cwl_campaign_draft",
        "guild_id": int(guild_id), "user_id": int(user_id), "cycle": loaded["cycle"],
        "scope": scope,
        "base_revision": loaded["defaults_revision"] if scope == "defaults" else loaded["revision"],
        "cycle_base_revision": loaded["revision"],
        "defaults_base_revision": loaded["defaults_revision"],
        "recurring_base_version": loaded.get("recurring_version"),
        "campaign": copy.deepcopy(campaign), "created_at": now, "updated_at": now,
        "saved_campaign": copy.deepcopy(campaign),
    }
    await mongo.bot_config.update_one({"_id": draft["_id"]}, {"$set": draft}, upsert=True)
    return copy.deepcopy(draft)


async def load_draft(mongo, draft: str) -> dict | None:
    query = {"_id": draft} if str(draft).startswith("cwl:draft:") else {"kind": "cwl_campaign_draft", "token": str(draft)}
    row = await mongo.bot_config.find_one(query)
    return row if row and row.get("kind") == "cwl_campaign_draft" else None


async def find_draft(
    mongo, guild_id: int, user_id: int, cycle: str | None = None,
) -> dict | None:
    """Return the editor's most recently updated resumable draft."""
    query = {
        "kind": "cwl_campaign_draft", "guild_id": int(guild_id),
        "user_id": int(user_id),
    }
    if cycle is not None:
        query["cycle"] = cycle
    cursor = mongo.bot_config.find(query).sort("updated_at", -1).limit(1)
    rows = await cursor.to_list(length=1)
    return rows[0] if rows else None


def _drop_superseded_transitional_schedules(previous: dict, candidate: dict) -> dict:
    """Make an explicit canonical schedule edit win over old top-level data.

    Early dashboard drafts stored timing under ``campaign.schedules``.  That
    compatibility value must continue to win until an editor actually changes
    the corresponding message schedule; otherwise merely loading and saving an
    old campaign would replace its real timing with merged default fields.
    """
    result = copy.deepcopy(candidate)
    transitional = result.get("schedules")
    if not isinstance(transitional, dict):
        return result
    old_messages = previous.get("messages", {}) if isinstance(previous, dict) else {}
    for message_id, message in result.get("messages", {}).items():
        if not isinstance(message, dict) or "schedule" not in message:
            continue
        old_message = old_messages.get(message_id, {})
        old_schedule = old_message.get("schedule") if isinstance(old_message, dict) else None
        if message["schedule"] != old_schedule:
            transitional.pop(message_id, None)
    if not transitional:
        result.pop("schedules", None)
    return result


async def patch_draft(mongo, draft: str, patch: dict) -> dict:
    row = await load_draft(mongo, draft)
    if not row:
        raise ValueError("Draft expired or does not exist")
    allowed = {"campaign", "scope", "cycle", "base_revision", "cycle_base_revision", "recurring_base_version"}
    if set(patch) - allowed:
        raise ValueError("Draft patch contains unsupported fields")
    updated = copy.deepcopy(row)
    if "campaign" in patch:
        campaign = _drop_superseded_transitional_schedules(
            row.get("campaign", {}), patch["campaign"],
        )
        validate_campaign(campaign)
        updated["campaign"] = campaign
    if "scope" in patch:
        if patch["scope"] not in {"cycle", "defaults"}:
            raise ValueError("scope must be cycle or defaults")
        updated["scope"] = patch["scope"]
    if "cycle" in patch:
        _month(patch["cycle"], updated["campaign"].get("timezone", DEFAULT_TIMEZONE))
        updated["cycle"] = patch["cycle"]
    for key in ("base_revision", "cycle_base_revision"):
        if key in patch:
            value = int(patch[key])
            if value < 0:
                raise ValueError("Draft revision is invalid")
            updated[key] = value
    updated["updated_at"] = _utcnow()
    await mongo.bot_config.update_one({"_id": row["_id"]}, {"$set": {key: updated[key] for key in allowed if key in updated} | {"updated_at": updated["updated_at"]}})
    return updated


def _sent_ids(deliveries, sent_occurrences=()):
    return set(sent_occurrences) | {
        item.get("occurrence_id") for item in deliveries if item.get("status") == "sent"
    }


def _protect_sent(candidate: dict, current: dict, cycle: str, deliveries: list[dict], sent_occurrences=()):
    """Keep delivered audience content immutable without freezing event timing.

    A message schedule is shared by both audiences and is also the signup
    opening anchor for reminder sequences.  Delivery protects the rendered
    variant that was posted; it does not turn the event's configured start
    time into immutable content.
    """
    protected = []
    for oid in _sent_ids(deliveries, sent_occurrences):
        try:
            event_cycle, message_id, variant = oid.split("|", 2)
        except (AttributeError, ValueError):
            continue
        if event_cycle != cycle or message_id not in current.get("messages", {}):
            continue
        old_message = current["messages"][message_id]
        new_message = candidate.setdefault("messages", {}).setdefault(message_id, {})
        new_message.setdefault("variants", {})[variant] = copy.deepcopy(old_message.get("variants", {}).get(variant, {}))
        protected.append(oid)
    return protected


def _validate_future_signup(candidate: dict, live: dict, cycle: str) -> None:
    """Do not accept a newly selected signup time that cannot be scheduled."""
    planned = [item for item in resolve_schedule(candidate, cycle) if item["message_id"] == "signup" and item.get("run_at")]
    previous = [item for item in live.get("schedule", ()) if item["message_id"] == "signup" and item.get("run_at")]
    changed = {(item["id"], item["run_at"]) for item in planned} != {(item["id"], item["run_at"]) for item in previous}
    if not changed and live.get("activated"):
        return
    sent = _sent_ids(live.get("deliveries", ()), live.get("sent_occurrences", ()))
    now = pendulum.now("UTC")
    if any(item["id"] not in sent and pendulum.parse(item["run_at"]) <= now for item in planned):
        raise ValueError("The signup time has already passed. Choose a future date and time.")


def monthly_campaign(campaign: dict, cycle: str) -> dict:
    """Convert dated rules to their monthly equivalents for subsequent cycles."""
    result = copy.deepcopy(campaign)
    timezone = result.get("timezone", DEFAULT_TIMEZONE)
    origin = _month(cycle, timezone)
    def parts(at):
        offset = (at.year - origin.year) * 12 + at.month - origin.month
        return {"day": at.day, "hour": at.hour, "minute": at.minute, **({"month_offset": offset} if offset else {})}
    overrides = result.pop("schedules", {})
    for key, message in result.get("messages", {}).items():
        schedule = overrides.get(key, message.get("schedule", {}))
        message["schedule"] = copy.deepcopy(schedule)
        if schedule.get("mode") == "specific":
            at = pendulum.parse(schedule["at"], tz=timezone).in_timezone(timezone)
            message["schedule"] = {"mode": "monthly", **parts(at)}
    deadline = result.get("signup_deadline", {})
    if isinstance(deadline, str) or deadline.get("at"):
        at = pendulum.parse(deadline if isinstance(deadline, str) else deadline["at"], tz=timezone).in_timezone(timezone)
        result["signup_deadline"] = parts(at)
    return result


async def apply_draft(mongo, draft: str, user_id: int, expected_revision: int | None = None, *, keep_draft: bool = False, require_future_signup: bool = False, repeat_monthly: bool = False, candidate_campaign: dict | None = None, preserve_editor_campaign: bool = False, expected_generation: str | None = None) -> dict:
    row = await load_draft(mongo, draft)
    if not row:
        raise ValueError("Draft expired or does not exist")
    if int(row["user_id"]) != int(user_id):
        raise PermissionError("This draft belongs to another editor")
    guild_id, cycle, scope = int(row["guild_id"]), row["cycle"], row["scope"]
    validate_campaign(candidate_campaign if candidate_campaign is not None else row["campaign"])
    live = await load_campaign(mongo, guild_id, cycle)
    if expected_generation is not None:
        from utils.cwl_web_bridge import campaign_generation
        if campaign_generation(live) != expected_generation:
            raise RuntimeError("CWL settings changed. Reload the dashboard before saving.")
    if repeat_monthly and row.get("recurring_base_version") != live.get("recurring_version"):
        raise RuntimeError("CWL settings changed. Reload the dashboard before saving.")
    current_revision = live["defaults_revision"] if scope == "defaults" else live["revision"]
    scope_revision = row.get(f"{scope}_base_revision", row.get("base_revision", 0))
    # UI callers created before separate scope revisions pass the draft's
    # original base revision. When the scope changed, use the stored revision
    # for the selected scope rather than comparing unrelated counters.
    if expected_revision is None or int(expected_revision) == int(row.get("base_revision", 0)):
        wanted_revision = int(scope_revision)
    else:
        wanted_revision = int(expected_revision)
    if current_revision != wanted_revision:
        raise RuntimeError("CWL campaign changed while this draft was open")
    candidate = copy.deepcopy(candidate_campaign if candidate_campaign is not None else row["campaign"])
    recurring_candidate = monthly_campaign(candidate, cycle) if repeat_monthly else None
    if recurring_candidate:
        for offset in range(1, 13):
            resolve_schedule(recurring_candidate, _month(cycle, candidate.get("timezone", DEFAULT_TIMEZONE)).add(months=offset).format("YYYY-MM"))
    try:
        from extensions.tasks import cwl_reminder
        runtime_bot = getattr(cwl_reminder, "bot_instance", None)
    except ImportError:
        runtime_bot = None
    if runtime_bot is not None:
        await validate_destinations(runtime_bot, candidate, guild_id)
    protected = _protect_sent(
        candidate, live["campaign"], cycle, live["deliveries"],
        live.get("sent_occurrences", ()),
    ) if scope == "cycle" else []
    if require_future_signup and scope == "cycle":
        _validate_future_signup(candidate, live, cycle)
    active_cycle = cycle_key(timezone_name=candidate.get("timezone", DEFAULT_TIMEZONE))
    if scope == "defaults":
        # Defaults begin after the actual active cycle, regardless of which
        # month the editor happened to browse when opening the draft. Validate
        # the same next 12 cycles that can inherit this rule in production.
        month = _month(active_cycle, candidate.get("timezone", DEFAULT_TIMEZONE))
        for offset in range(1, 13):
            resolve_schedule(candidate, month.add(months=offset).format("YYYY-MM"))
    else:
        resolve_schedule(candidate, cycle)
    target_id = defaults_id(guild_id) if scope == "defaults" else cycle_id(guild_id, cycle)
    if scope == "defaults":
        # Monthly defaults begin with the next cycle. Materialize the current
        # effective campaign before changing its base so unsent current-month
        # occurrences do not move under an administrator's feet.
        active_loaded = await load_campaign(mongo, guild_id, active_cycle)
        active_id = cycle_id(guild_id, active_cycle)
        active_row = await mongo.bot_config.find_one({"_id": active_id})
        if not active_row:
            await mongo.bot_config.update_one(
                {"_id": active_id},
                {"$setOnInsert": {
                    "kind": "cwl_campaign_cycle", "guild_id": guild_id,
                    "cycle": active_cycle, "revision": 0, "activated": True,
                    "campaign": active_loaded["campaign"],
                    "instantiated_at": _utcnow(),
                }},
                upsert=True,
            )
        elif not isinstance(active_row.get("campaign"), dict):
            await mongo.bot_config.update_one(
                {"_id": active_id, "campaign": {"$exists": False}},
                {"$set": {
                    "campaign": active_loaded["campaign"], "activated": True,
                    "instantiated_at": _utcnow(),
                }, "$setOnInsert": {"revision": 0}},
            )
    new_revision = current_revision + 1
    now = _utcnow()
    revision_entry = {"revision": new_revision, "at": now, "by": int(user_id), "draft_id": row["_id"], "protected_sent": protected, "campaign": copy.deepcopy(candidate)}
    update = {"$set": {
        "kind": "cwl_campaign_defaults" if scope == "defaults" else "cwl_campaign_cycle",
        "guild_id": guild_id, "campaign": candidate, "revision": new_revision,
        "activated": True,
        "updated_at": now, "updated_by": int(user_id), "schema_version": SCHEMA_VERSION,
    }, "$push": {"revisions": {"$each": [revision_entry], "$slice": -20}}}
    if scope == "cycle":
        update["$set"]["cycle"] = cycle
        if recurring_candidate:
            # Current settings and the monthly rule commit in one Mongo write.
            update["$set"].update(recurring_campaign=recurring_candidate, recurring_updated_at=now)
    try:
        write = await mongo.bot_config.update_one(
            {"_id": target_id, "revision": current_revision}, update,
            upsert=current_revision == 0,
        )
    except DuplicateKeyError as exc:
        raise RuntimeError("CWL campaign changed while this draft was being applied") from exc
    matched = getattr(write, "matched_count", None)
    upserted = getattr(write, "upserted_id", None)
    modified = getattr(write, "modified_count", None)
    won = matched == 1 or upserted is not None or (matched is None and modified == 1)
    if not won:
        raise RuntimeError("CWL campaign changed while this draft was being applied")
    if not keep_draft:
        await mongo.bot_config.delete_one({"_id": row["_id"]})
    result = await load_campaign(mongo, guild_id, cycle)
    result["protected_sent"] = protected
    if keep_draft:
        # Keep existing dashboard buttons usable after a timing form saves.
        # Do not replace a newer edit submitted while this save was running.
        fields = {
            "campaign": copy.deepcopy(row["campaign"] if preserve_editor_campaign else candidate), "updated_at": _utcnow(),
            "saved_campaign": copy.deepcopy(candidate),
            "base_revision": new_revision,
            "cycle_base_revision": result["revision"],
            "defaults_base_revision": result["defaults_revision"],
            "recurring_base_version": result.get("recurring_version"),
        }
        refreshed = await mongo.bot_config.update_one(
            {"_id": row["_id"], "updated_at": row.get("updated_at")}, {"$set": fields},
        )
        result["draft_refresh_pending"] = getattr(refreshed, "matched_count", 0) != 1
        result["draft"] = await load_draft(mongo, row["_id"])
    try:
        from extensions.tasks import cwl_reminder
        if getattr(cwl_reminder, "mongo_client", None) is mongo:
            if scope == "defaults" or repeat_monthly:
                await cwl_reminder._sync_all_campaigns()
            else:
                await cwl_reminder.sync_campaign_schedule(guild_id, cycle)
    except Exception as exc:  # durable startup reconciliation will retry
        result["schedule_sync_pending"] = True
        result["schedule_sync_error"] = type(exc).__name__
    return result


async def _cycle_update(mongo, guild_id: int, cycle: str, update: dict):
    update.setdefault("$setOnInsert", {}).update({
        "kind": "cwl_campaign_cycle", "guild_id": int(guild_id),
        "cycle": cycle, "revision": 0,
    })
    await mongo.bot_config.update_one({"_id": cycle_id(guild_id, cycle)}, update, upsert=True)
    return await load_campaign(mongo, guild_id, cycle)


async def set_paused(mongo, guild_id: int, paused: bool, cycle: str | None = None, user_id: int | None = None, *, expected_generation: str | None = None):
    loaded = await load_campaign(mongo, guild_id, cycle)
    if expected_generation is not None:
        from utils.cwl_web_bridge import campaign_generation
        if campaign_generation(loaded) != expected_generation:
            raise RuntimeError("CWL settings changed. Reload the dashboard before saving.")
    campaign = copy.deepcopy(loaded["campaign"])
    campaign["paused"] = bool(paused)
    now = _utcnow()
    old_revision = int(loaded["revision"])
    new_revision = old_revision + 1
    update = {"$set": {"kind": "cwl_campaign_cycle", "guild_id": int(guild_id), "cycle": loaded["cycle"], "campaign": campaign, "activated": True, "revision": new_revision, "updated_at": now}, "$push": {
        "actions": {"$each": [{"action": "paused" if paused else "resumed", "at": now, "by": user_id}], "$slice": -HISTORY_LIMIT},
        "revisions": {"$each": [{"revision": new_revision, "at": now, "by": user_id, "action": "paused" if paused else "resumed", "campaign": copy.deepcopy(campaign)}], "$slice": -20},
    }}
    if loaded.get("recurring_version"):
        source = await mongo.bot_config.find_one({"guild_id": int(guild_id), "recurring_updated_at": loaded["recurring_version"]})
        recurring = copy.deepcopy(source["recurring_campaign"])
        recurring["paused"] = bool(paused)
        update["$set"].update(recurring_campaign=recurring, recurring_updated_at=now)
    try:
        write = await mongo.bot_config.update_one(
            {"_id": cycle_id(guild_id, loaded["cycle"]), "revision": old_revision},
            update, upsert=old_revision == 0,
        )
    except DuplicateKeyError as exc:
        raise RuntimeError("CWL campaign changed while pause state was updating") from exc
    if not (
        getattr(write, "matched_count", 0)
        or getattr(write, "upserted_id", None) is not None
        or (getattr(write, "matched_count", None) is None and getattr(write, "modified_count", 0))
    ):
        raise RuntimeError("CWL campaign changed while pause state was updating")
    result = await load_campaign(mongo, guild_id, loaded["cycle"])
    try:
        from extensions.tasks import cwl_reminder
        if getattr(cwl_reminder, "mongo_client", None) is mongo:
            if loaded.get("recurring_version"):
                await cwl_reminder._sync_all_campaigns()
            else:
                await cwl_reminder.sync_campaign_schedule(guild_id, loaded["cycle"])
    except Exception as exc:
        result["schedule_sync_pending"] = True
        result["schedule_sync_error"] = type(exc).__name__
    return result


async def skip_occurrence(mongo, guild_id: int, occurrence: str, cycle: str | None = None, user_id: int | None = None):
    loaded = await load_campaign(mongo, guild_id, cycle)
    valid = {item["id"] for item in loaded["schedule"]}
    if occurrence not in valid:
        raise ValueError("Unknown occurrence")
    now = _utcnow()
    result = await _cycle_update(mongo, guild_id, loaded["cycle"], {"$set": {"activated": True}, "$addToSet": {"skipped": occurrence}, "$push": {"actions": {"$each": [{"action": "skipped", "occurrence_id": occurrence, "at": now, "by": user_id}], "$slice": -HISTORY_LIMIT}}})
    try:
        from extensions.tasks import cwl_reminder
        if getattr(cwl_reminder, "mongo_client", None) is mongo:
            await cwl_reminder.sync_campaign_schedule(guild_id, loaded["cycle"])
    except Exception as exc:
        result["schedule_sync_pending"] = True
        result["schedule_sync_error"] = type(exc).__name__
    return result


async def retry_occurrence(mongo, guild_id: int, occurrence: str, cycle: str | None = None, user_id: int | None = None):
    loaded = await load_campaign(mongo, guild_id, cycle)
    failed = any(item.get("occurrence_id") == occurrence and item.get("status") == "failed" for item in loaded["deliveries"])
    if not failed:
        raise ValueError("Only a failed occurrence can be retried")
    now = _utcnow()
    result = await _cycle_update(mongo, guild_id, loaded["cycle"], {"$pull": {"skipped": occurrence}, "$push": {"actions": {"$each": [{"action": "retry_requested", "occurrence_id": occurrence, "at": now, "by": user_id}], "$slice": -HISTORY_LIMIT}}})
    try:
        from extensions.tasks import cwl_reminder
        if getattr(cwl_reminder, "mongo_client", None) is mongo:
            await cwl_reminder.queue_campaign_retry(guild_id, loaded["cycle"], occurrence)
    except (ImportError, AttributeError):
        pass
    return result


async def queue_manual_occurrence(
    mongo,
    guild_id: int,
    message_key: str,
    audience: str,
    cycle: str | None = None,
    user_id: int | None = None,
) -> dict:
    """Queue a manual message through the same durable delivery pipeline."""
    loaded = await load_campaign(mongo, guild_id, cycle)
    message = loaded["campaign"].get("messages", {}).get(message_key)
    if not message or audience not in AUDIENCES:
        raise ValueError("Unknown CWL message or audience")
    if audience not in message.get("variants", {}):
        raise ValueError("That message has no configured audience version")
    if loaded["campaign"].get("paused"):
        raise ValueError("Resume the campaign before sending a manual message")
    from extensions.tasks import cwl_reminder
    if getattr(cwl_reminder, "mongo_client", None) is not mongo:
        raise RuntimeError("CWL scheduler is not ready")
    job_id = await cwl_reminder.queue_manual_campaign_occurrence(
        int(guild_id), loaded["cycle"], message_key, [audience]
    )
    now = _utcnow()
    await mongo.bot_config.update_one(
        {"_id": cycle_id(guild_id, loaded["cycle"])},
        {"$setOnInsert": {
            "kind": "cwl_campaign_cycle", "guild_id": int(guild_id),
            "cycle": loaded["cycle"], "revision": 0,
        }, "$push": {"actions": {"$each": [{
            "action": "manual_queued", "message_key": message_key,
            "variant": audience, "job_id": job_id, "at": now,
            "by": user_id,
        }], "$slice": -HISTORY_LIMIT}}},
        upsert=True,
    )
    return {"queued": True, "job_id": job_id, "cycle": loaded["cycle"]}


async def restore_revision(
    mongo,
    guild_id: int,
    revision: int,
    user_id: int,
    cycle: str | None = None,
    scope: str = "cycle",
) -> dict:
    """Create a reviewable draft from a previous full campaign snapshot."""
    if scope not in {"cycle", "defaults"}:
        raise ValueError("scope must be cycle or defaults")
    loaded = await load_campaign(mongo, guild_id, cycle)
    target_id = defaults_id(guild_id) if scope == "defaults" else cycle_id(guild_id, loaded["cycle"])
    row = await mongo.bot_config.find_one({"_id": target_id}) or {}
    snapshot = next(
        (entry.get("campaign") for entry in row.get("revisions", [])
         if int(entry.get("revision", -1)) == int(revision)),
        None,
    )
    if not isinstance(snapshot, dict):
        raise ValueError("That revision is no longer available")
    draft = await new_draft(
        mongo, guild_id, user_id, cycle=loaded["cycle"], scope=scope
    )
    return await patch_draft(mongo, draft["_id"], {"campaign": snapshot})


async def record_delivery(mongo, guild_id: int, cycle: str, entry: dict):
    item = copy.deepcopy(entry)
    item.setdefault("at", _utcnow())
    update = {"$setOnInsert": {"kind": "cwl_campaign_cycle", "guild_id": int(guild_id), "cycle": cycle, "revision": 0}, "$push": {"deliveries": {"$each": [item], "$slice": -HISTORY_LIMIT}}}
    if item.get("status") == "sent" and item.get("occurrence_id"):
        update["$addToSet"] = {"sent_occurrences": item["occurrence_id"]}
    await mongo.bot_config.update_one({"_id": cycle_id(guild_id, cycle)}, update, upsert=True)


def _catchup_scope(guild_id, cycle, occurrence):
    parts = str(occurrence).split("|")
    if (
        not isinstance(guild_id, int) or isinstance(guild_id, bool) or guild_id <= 0
        or not isinstance(cycle, str) or not _CYCLE_RE.fullmatch(cycle)
        or len(parts) != 3 or parts[0] != cycle or parts[2] not in AUDIENCES
        or parts[1] == "roster" or not re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", parts[1])
    ):
        raise ValueError("Invalid catch-up scope")
    return parts[1], parts[2]


def _catchup_row_scope(row):
    variants = row.get("variants")
    if not isinstance(variants, list) or len(variants) != 1:
        raise ValueError("Invalid catch-up audience")
    gid, cycle, message_id = row.get("guild_id"), row.get("cycle"), row.get("message_id")
    _catchup_scope(gid, cycle, occurrence_id(cycle, message_id, variants[0]))
    if (
        row.get("kind") != "campaign"
        or row.get("job_kind", "scheduled") not in {"scheduled", "catchup"}
        or row.get("status", "scheduled") != "scheduled"
        or not isinstance(message_id, str)
        or not isinstance(row.get("failure_count", 0), int)
        or isinstance(row.get("failure_count", 0), bool)
        or row.get("failure_count", 0) != 0
        or row.get("_id") != f"cwl_campaign:{gid}:{cycle}:{message_id}:{variants[0]}"
    ):
        raise ValueError("Invalid persisted catch-up job")
    if row.get("job_kind") == "catchup" and (
        not isinstance(row.get("catchup"), dict)
        or row["catchup"].get("protocol") != 1
        or isinstance(row["catchup"].get("protocol"), bool)
        or not isinstance(row["catchup"].get("original_due_at"), str)
    ):
        raise ValueError("Invalid catch-up protocol")


STAFF_SEND_BUSY_REASON = "Not sent: another send was running. Send again."


def _staff_request_scope(row):
    variants = row.get("variants")
    request_id = row.get("staff_request_id")
    if (
        not isinstance(variants, list) or len(variants) != 1
        or not isinstance(request_id, str)
        or not re.fullmatch(r"[a-f0-9]{32}", request_id)
        or row.get("kind") != "campaign"
        or row.get("job_kind") not in {"manual", "retry"}
        or row.get("status") not in {"scheduled", "ledger_pending"}
        or not isinstance(row.get("message_id"), str)
        or not isinstance(row.get("generation"), str)
        or not isinstance(row.get("run_time"), str)
        or row.get("failure_count", 0) != 0
    ):
        raise ValueError("Invalid queued staff request")
    gid, cycle, message_key = row.get("guild_id"), row.get("cycle"), row.get("message_id")
    _catchup_scope(gid, cycle, occurrence_id(cycle, message_key, variants[0]))
    if row.get("_id") != f"cwl_campaign:{gid}:{cycle}:{message_key}:{variants[0]}":
        raise ValueError("Queued staff request ownership changed")
    return occurrence_id(cycle, message_key, variants[0])


async def load_queued_staff_job(mongo, guild_id, cycle, message_key, variant, generation, request_id):
    _catchup_scope(guild_id, cycle, occurrence_id(cycle, message_key, variant))
    row = await mongo.cwl_pending_reminders.find_one({
        "_id": f"cwl_campaign:{guild_id}:{cycle}:{message_key}:{variant}",
        "kind": "campaign", "job_kind": {"$in": ["manual", "retry"]},
        "generation": generation, "variants": [variant],
        "staff_request_id": request_id,
        "status": {"$in": ["scheduled", "ledger_pending"]},
    })
    if row is not None:
        _staff_request_scope(row)
    return row


def is_staff_not_sent_receipt(row):
    receipt = row.get("receipt")
    variants = row.get("variants")
    return (
        row.get("status") == "ledger_pending"
        and isinstance(receipt, dict)
        and receipt.get("staff_request_id") == row.get("staff_request_id")
        and receipt.get("status") == "failed"
        and receipt.get("delivery_attempted") is False
        and receipt.get("reason") == STAFF_SEND_BUSY_REASON
        and isinstance(variants, list) and len(variants) == 1
        and receipt.get("message_key") == row.get("message_id")
        and receipt.get("variant") == variants[0]
        and receipt.get("occurrence_id") == occurrence_id(
            row.get("cycle"), row.get("message_id"), variants[0]
        )
    )


async def record_staff_not_sent(mongo, row):
    """Finish one known-no-POST staff outcome; never release another send."""
    oid = _staff_request_scope(row)
    gid, cycle, request_id = row["guild_id"], row["cycle"], row["staff_request_id"]
    identity = {
        "_id": row["_id"], "kind": "campaign", "job_kind": row["job_kind"],
        "generation": row["generation"], "staff_request_id": request_id,
        "run_time": row["run_time"], "variants": row["variants"],
    }
    if row["status"] == "scheduled":
        receipt = {
            "occurrence_id": oid, "message_key": row["message_id"],
            "variant": row["variants"][0], "status": "failed",
            "reason": STAFF_SEND_BUSY_REASON, "at": _utcnow(),
            "staff_request_id": request_id, "delivery_attempted": False,
        }
        result = await mongo.cwl_pending_reminders.update_one(
            {**identity, "status": "scheduled"},
            {"$set": {"status": "ledger_pending", "receipt": receipt}},
        )
        if not getattr(result, "matched_count", 0):
            return False
    else:
        if not is_staff_not_sent_receipt(row):
            raise ValueError("Queued staff outcome needs review")
        receipt = copy.deepcopy(row["receipt"])
    recorded = False
    try:
        result = await mongo.bot_config.update_one(
            {"_id": cycle_id(gid, cycle), "staff_not_sent_requests": {"$ne": request_id},
             "sent_occurrences": {"$ne": oid}},
            {
                "$setOnInsert": {"kind": "cwl_campaign_cycle", "guild_id": int(gid), "cycle": cycle, "revision": 0},
                "$push": {
                    "deliveries": {"$each": [receipt], "$slice": -HISTORY_LIMIT},
                    "staff_not_sent_requests": {"$each": [request_id], "$slice": -HISTORY_LIMIT},
                },
            },
            upsert=True,
        )
        recorded = bool(getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None))
    except DuplicateKeyError:
        pass
    if not recorded:
        current = await mongo.bot_config.find_one(
            {"_id": cycle_id(gid, cycle)}, {"staff_not_sent_requests": 1, "sent_occurrences": 1}
        ) or {}
        if request_id not in current.get("staff_not_sent_requests", ()) and oid not in current.get("sent_occurrences", ()):
            raise RuntimeError("Staff not-sent outcome was not recorded")
    await mongo.cwl_pending_reminders.delete_one({
        **identity, "status": "ledger_pending", "receipt.staff_request_id": request_id,
    })
    return True


async def catchup_state(mongo, guild_id: int, cycle: str) -> dict:
    """Indexed, bounded state needed for a startup catch-up decision."""
    row = await mongo.bot_config.find_one(
        {"_id": cycle_id(guild_id, cycle)},
        {"catchup_reported_occurrences": 1, "delivery_claims": 1, "uncertain_occurrences": 1, "sent_occurrences": 1},
    ) or {}
    return {
        "reported": list(row.get("catchup_reported_occurrences", ())),
        "claims": copy.deepcopy(row.get("delivery_claims", {})),
        "uncertain": list(row.get("uncertain_occurrences", ())),
        "sent": list(row.get("sent_occurrences", ())),
    }


async def record_legacy_catchup_skip(mongo, row: dict, original_due_at: str) -> bool:
    """Report one combined legacy job without consuming either pool occurrence."""
    if (
        not isinstance(original_due_at, str)
        or not re.search(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$", original_due_at)
        or pendulum.parse(original_due_at) != pendulum.parse(row.get("run_time"))
    ):
        raise ValueError("Legacy reminder time changed")
    variants = row.get("variants")
    if (
        not isinstance(variants, list)
        or len(variants) != 2
        or any(not isinstance(value, str) for value in variants)
        or set(variants) != set(AUDIENCES)
    ):
        raise ValueError("Invalid combined reminder audiences")
    gid, cycle, message_key = row.get("guild_id"), row.get("cycle"), row.get("message_id")
    base_id = f"cwl_campaign:{gid}:{cycle}:{message_key}"
    _catchup_row_scope({
        **row, "_id": f"{base_id}:{variants[0]}", "variants": [variants[0]],
    })
    if (
        row.get("_id") not in {base_id, *(f"{base_id}:{value}" for value in variants)}
        or row.get("kind") != "campaign"
        or row.get("job_kind", "scheduled") != "scheduled"
        or row.get("status", "scheduled") != "scheduled"
    ):
        raise ValueError("Invalid combined legacy reminder")
    query = {
        "_id": cycle_id(gid, cycle),
        "catchup_legacy_reported_jobs": {"$ne": row["_id"]},
    }
    entry = {
        "message_key": message_key,
        "status": "skipped",
        "reason": "Skipped: older reminder listed Main and Lazy together; review settings",
        "at": _utcnow(),
        "original_due_at": original_due_at,
        "revision": row.get("generation"),
    }
    recorded = False
    try:
        result = await mongo.bot_config.update_one(
            query,
            {
                "$setOnInsert": {
                    "kind": "cwl_campaign_cycle", "guild_id": int(gid),
                    "cycle": cycle, "revision": 0,
                },
                "$addToSet": {"catchup_legacy_reported_jobs": row["_id"]},
                "$push": {"deliveries": {"$each": [entry], "$slice": -HISTORY_LIMIT}},
            },
            upsert=True,
        )
        recorded = bool(getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None))
    except DuplicateKeyError:
        pass
    if not recorded:
        current = await mongo.bot_config.find_one(
            {"_id": cycle_id(gid, cycle)}, {"catchup_legacy_reported_jobs": 1}
        ) or {}
        if row["_id"] not in current.get("catchup_legacy_reported_jobs", ()):
            raise RuntimeError("Legacy reminder decision was not recorded")
    await mongo.cwl_pending_reminders.delete_one({
        "_id": row["_id"], "kind": "campaign", "variants": variants,
        "run_time": row.get("run_time"),
        "job_kind": row.get("job_kind", {"$exists": False}),
        "status": row.get("status", {"$exists": False}),
        "generation": row.get("generation", {"$exists": False}),
    })
    return recorded


async def prepare_catchup_job(mongo, row: dict, due, now) -> bool:
    """CAS one existing scheduled row; never derive or insert a missing job."""
    _catchup_row_scope(row)
    query = {
        "_id": row["_id"],
        "kind": "campaign",
        "generation": row.get("generation"),
        "run_time": row.get("run_time"),
        "job_kind": row.get("job_kind", {"$exists": False}),
        "status": row.get("status", {"$exists": False}),
    }
    result = await mongo.cwl_pending_reminders.update_one(
        query,
        {"$set": {
            "job_kind": "catchup",
            "status": "scheduled",
            "run_time": now.isoformat(),
            "catchup": {"protocol": 1, "original_due_at": due.isoformat()},
            "updated_at": _utcnow(),
        }},
    )
    return bool(getattr(result, "matched_count", 0))


async def delete_catchup_job(mongo, row: dict) -> None:
    """Delete only the observed job or confirmed receipt, never a replacement."""
    recovering = row.get("status") == "ledger_pending"
    if recovering:
        receipt = row.get("receipt")
        if (
            not isinstance(receipt, dict)
            or receipt.get("status") != "sent"
            or receipt.get("late") is not True
        ):
            raise ValueError("Invalid late receipt recovery")
        _catchup_row_scope({**row, "status": "scheduled"})
    else:
        _catchup_row_scope(row)
    query = {
        "_id": row["_id"], "kind": "campaign",
        "generation": row.get("generation"),
        "job_kind": row.get("job_kind", {"$exists": False}),
        "status": row.get("status", {"$exists": False}),
    }
    if recovering:
        query["receipt.message_id"] = row["receipt"].get("message_id")
    if row.get("job_kind") == "catchup":
        query["catchup.original_due_at"] = row["catchup"]["original_due_at"]
    else:
        query["run_time"] = row.get("run_time")
    await mongo.cwl_pending_reminders.delete_one(query)


async def record_catchup_decision(
    mongo, guild_id: int, cycle: str, entry: dict
) -> bool:
    """One durable catch-up report; do not consume a future ordinary send."""
    oid = entry["occurrence_id"]
    message_key, variant = _catchup_scope(guild_id, cycle, oid)
    if entry.get("message_key") != message_key or entry.get("variant") != variant:
        raise ValueError("Catch-up receipt scope changed")
    status = entry["status"]
    if status not in {"skipped", "uncertain", "failed"}:
        raise ValueError("Invalid catch-up decision")
    query = {
        "_id": cycle_id(guild_id, cycle),
        "catchup_reported_occurrences": {"$ne": oid},
        "sent_occurrences": {"$ne": oid},
    }
    if status != "uncertain":
        query["uncertain_occurrences"] = {"$ne": oid}
    item = copy.deepcopy(entry)
    item.setdefault("at", _utcnow())
    add = {"catchup_reported_occurrences": oid}
    if status == "uncertain":
        add["uncertain_occurrences"] = oid
    try:
        result = await mongo.bot_config.update_one(
            query,
            {
                "$setOnInsert": {
                    "kind": "cwl_campaign_cycle", "guild_id": int(guild_id),
                    "cycle": cycle, "revision": 0,
                },
                "$addToSet": add,
                "$push": {"deliveries": {"$each": [item], "$slice": -HISTORY_LIMIT}},
            },
            upsert=True,
        )
    except DuplicateKeyError:
        return False
    return bool(getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None))


async def begin_catchup_attempt(
    mongo, *, guild_id: int, cycle: str, occurrence: str, generation: str,
    job_id: str, original_due_at: str,
) -> bool:
    """Reserve uncertainty durably before entering Discord's POST boundary."""
    message_key, variant = _catchup_scope(guild_id, cycle, occurrence)
    if job_id != f"cwl_campaign:{guild_id}:{cycle}:{message_key}:{variant}":
        raise ValueError("Catch-up job scope changed")
    pending = await mongo.cwl_pending_reminders.find_one({
        "_id": job_id, "kind": "campaign", "job_kind": "catchup",
        "generation": generation, "catchup.original_due_at": original_due_at,
        "catchup.protocol": 1, "status": "scheduled",
    }, {"_id": 1})
    if pending is None:
        return False
    key = occurrence.replace(".", "_")
    result = await mongo.bot_config.update_one(
        {
            "_id": cycle_id(guild_id, cycle),
            f"delivery_claims.{key}.generation": generation,
            "sent_occurrences": {"$ne": occurrence},
            "uncertain_occurrences": {"$ne": occurrence},
            "skipped": {"$ne": occurrence},
            "catchup_reported_occurrences": {"$ne": occurrence},
        },
        {"$addToSet": {"uncertain_occurrences": occurrence}},
    )
    return bool(getattr(result, "matched_count", 0))


async def finish_catchup_attempt(mongo, guild_id: int, cycle: str, occurrence: str):
    """Only a confirmed receipt (or known no-POST path) may clear this marker."""
    _catchup_scope(guild_id, cycle, occurrence)
    await mongo.bot_config.update_one(
        {"_id": cycle_id(guild_id, cycle)},
        {"$pull": {"uncertain_occurrences": occurrence}},
    )


async def release_catchup_preflight_claim(mongo, guild_id, cycle, occurrence, claim):
    """New-protocol absence of an attempt marker proves POST was not entered."""
    _catchup_scope(guild_id, cycle, occurrence)
    key = occurrence.replace(".", "_")
    result = await mongo.bot_config.update_one(
        {
            "_id": cycle_id(guild_id, cycle),
            f"delivery_claims.{key}.at": claim.get("at"),
            f"delivery_claims.{key}.generation": claim.get("generation"),
            "uncertain_occurrences": {"$ne": occurrence},
            "sent_occurrences": {"$ne": occurrence},
        },
        {"$unset": {f"delivery_claims.{key}": ""}},
    )
    return bool(getattr(result, "matched_count", 0))


async def persist_catchup_receipt(mongo, row: dict, receipt: dict, error_type: str):
    """A confirmed post owns its occurrence until its receipt is durable."""
    _catchup_row_scope(row)
    if receipt.get("occurrence_id") != occurrence_id(row["cycle"], row["message_id"], row["variants"][0]) or receipt.get("status") != "sent":
        raise ValueError("Invalid confirmed catch-up receipt")
    result = await mongo.cwl_pending_reminders.update_one(
        {
            "_id": row["_id"],
            "kind": "campaign",
            "job_kind": "catchup",
            "status": "scheduled",
            "generation": row["generation"],
            "catchup.protocol": 1,
            "catchup.original_due_at": row["catchup"]["original_due_at"],
        },
        {"$set": {
            "kind": "campaign", "job_kind": "catchup", "status": "ledger_pending",
            "guild_id": row["guild_id"], "cycle": row["cycle"],
            "message_id": row["message_id"], "variants": list(row["variants"]),
            "generation": row["generation"], "catchup": copy.deepcopy(row["catchup"]),
            "receipt": copy.deepcopy(receipt), "last_error_type": error_type,
            "updated_at": _utcnow(),
        }},
    )
    if not getattr(result, "matched_count", 0):
        raise RuntimeError("Catch-up receipt owner changed")


async def record_catchup_delivery(mongo, guild_id, cycle, receipt):
    """Idempotently persist one confirmed late receipt, including lost ACKs."""
    oid = receipt["occurrence_id"]
    message_key, variant = _catchup_scope(guild_id, cycle, oid)
    if (
        receipt.get("status") != "sent" or receipt.get("late") is not True
        or receipt.get("message_key") != message_key or receipt.get("variant") != variant
        or not isinstance(receipt.get("at"), str)
    ):
        raise ValueError("Invalid confirmed late receipt")
    try:
        result = await mongo.bot_config.update_one(
            {"_id": cycle_id(guild_id, cycle), "sent_occurrences": {"$ne": oid}},
            {
                "$setOnInsert": {"kind": "cwl_campaign_cycle", "guild_id": guild_id, "cycle": cycle, "revision": 0},
                "$addToSet": {"sent_occurrences": oid},
                "$push": {"deliveries": {"$each": [copy.deepcopy(receipt)], "$slice": -HISTORY_LIMIT}},
            },
            upsert=True,
        )
        if getattr(result, "matched_count", 0) or getattr(result, "upserted_id", None):
            return True
    except DuplicateKeyError:
        pass
    current = await mongo.bot_config.find_one(
        {"_id": cycle_id(guild_id, cycle)}, {"deliveries": 1}
    ) or {}
    if any(
        item.get("occurrence_id") == oid and item.get("status") == "sent"
        and item.get("message_id") == receipt.get("message_id")
        for item in current.get("deliveries", ())
    ):
        return False
    raise ValueError("Confirmed reminder receipt needs review")


async def load_catchup_job(mongo, guild_id, cycle, message_key, variant, generation, due_at):
    _catchup_scope(guild_id, cycle, occurrence_id(cycle, message_key, variant))
    return await mongo.cwl_pending_reminders.find_one({
        "_id": f"cwl_campaign:{guild_id}:{cycle}:{message_key}:{variant}",
        "kind": "campaign", "job_kind": "catchup", "generation": generation,
        "catchup.original_due_at": due_at, "catchup.protocol": 1,
        "status": "scheduled",
    })


def roster_delivery_nonce(guild_id: int, occurrence: str, deliveries: list[dict]) -> str:
    """Keep retries stable, but give an explicitly reopened receipt a fresh nonce."""
    import hashlib
    deleted = [item for item in deliveries if item.get("occurrence_id") == occurrence
               and item.get("status") == "deleted_confirmed"]
    identity = f"{guild_id}|{occurrence}"
    if deleted:
        identity += f"|deleted:{deleted[-1]['message_id']}"
    return hashlib.blake2s(identity.encode("utf-8"), digest_size=10).hexdigest()


async def reopen_deleted_roster_delivery(
    mongo, guild_id: int, cycle: str, pool: str, *,
    channel_id: int, message_id: int, actor_id: int,
) -> dict:
    """Archive an explicitly reviewed, confirmed-deleted roster occurrence.

    The caller must verify Discord 404/10008 and receive explicit resend
    confirmation first. This function never sends or schedules a notification.
    Compare the complete receipt lists so a concurrent delivery cannot be erased.
    """
    if pool not in AUDIENCES or min(channel_id, message_id, actor_id) < 1:
        raise ValueError("A roster pool, destination, message and actor are required")
    key = cycle_id(guild_id, cycle)
    row = await mongo.bot_config.find_one({"_id": key}) or {}
    occurrence = occurrence_id(cycle, "roster", pool)
    deliveries = copy.deepcopy(row.get("deliveries", []))
    sent = [item for item in deliveries
            if item.get("occurrence_id") == occurrence and item.get("status") == "sent"]
    def matches(item):
        return (str(item.get("channel_id")), str(item.get("message_id"))) == (str(channel_id), str(message_id))
    if not sent:
        previous = [item for item in deliveries if item.get("occurrence_id") == occurrence
                    and item.get("status") == "deleted_confirmed" and matches(item)]
        if previous and occurrence not in row.get("sent_occurrences", []):
            return previous[-1]
        raise ValueError("No matching sent announcement receipt; refresh before resending")
    if not matches(sent[-1]):
        raise ValueError("The announcement receipt changed; refresh before resending")
    # Multiple live receipts are ambiguous: never discard another confirmed send.
    if any(not matches(item) for item in sent):
        raise ValueError("Multiple announcement receipts require reconciliation")
    archived = None
    for item in deliveries:
        if item.get("occurrence_id") == occurrence and item.get("status") == "sent":
            item.update(status="deleted_confirmed", deleted_at=_utcnow(), deleted_by=int(actor_id))
            archived = item
    query = {"_id": key, "deliveries": row.get("deliveries", [])}
    query["sent_occurrences"] = row["sent_occurrences"] if "sent_occurrences" in row else {"$exists": False}
    result = await mongo.bot_config.update_one(query, {"$set": {
        "deliveries": deliveries,
        "sent_occurrences": [value for value in row.get("sent_occurrences", []) if value != occurrence],
    }})
    if not result.matched_count:
        raise ValueError("Announcement receipts changed; refresh before resending")
    return archived


async def history(mongo, guild_id: int, cycle: str | None = None, limit: int = 25) -> list[dict]:
    loaded = await load_campaign(mongo, guild_id, cycle)
    row = await mongo.bot_config.find_one({"_id": cycle_id(guild_id, loaded["cycle"])}) or {}
    events = list(row.get("revisions", [])) + list(row.get("actions", [])) + list(row.get("deliveries", []))
    events.sort(key=lambda item: item.get("at", ""), reverse=True)
    return copy.deepcopy(events[:max(1, min(int(limit), HISTORY_LIMIT))])
