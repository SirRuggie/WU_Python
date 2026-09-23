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
from pymongo.errors import DuplicateKeyError
from hikari.impl import (
    ContainerComponentBuilder as Container,
    LinkButtonBuilder as LinkButton,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID


SCHEMA_VERSION = 1
DEFAULT_TIMEZONE = "America/New_York"
DEFAULT_GUILD_ID = 0
LEGACY_WU_GUILD_ID = WARRIORS_UNITED_GUILD_ID
AUDIENCES = ("main", "lazy")
MESSAGE_ORDER = ("signup", "reminder:1", "reminder:2", "reminder:3", "reminder:4", "reminder:5", "roster")
HISTORY_LIMIT = 100
_CYCLE_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
_SKIP_OCCURRENCE = object()


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def default_campaign() -> dict:
    """Return the native copy formerly hard-coded in both CWL extensions."""
    role = 1080521665584308286
    main_channel = 1072714594625257502
    lazy_channel = 865726525990633472
    main_form = "https://forms.gle/ntB6qFvstu4gKUXc6"
    lazy_form = "https://forms.gle/qeow1ygVaJQeRC26A"
    main_buttons = _buttons(("Main Clan", main_form, "📋"), ("Lazy CWL", lazy_form, "😴"))
    lazy_buttons = _buttons(("Lazy CWL", lazy_form, "😴"))
    signup_main = (
        "Below are the two signup forms required to participate here in Warriors United CWL. "
        "LazyCWL is an option for all within the Family but if your in one of our FWA Clans "
        "it's \"Lazy Way or No Way\".\n\nThe forms take less then a couple minutes to complete "
        "and the sooner you sign up the better it is on us making Rosters.\n\n"
        "Direct all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"
    )
    signup_lazy = (
        "The below form is required to participate within the Warriors United Lazy CWL Operation.\n\n"
        "The form take less then a couple minutes to complete and the sooner you sign up the better "
        "it is on us making Rosters.\n\nRemember...if you are in one of our FWA Clans it's "
        "\"LAZY WAY OR NO WAY!!\" Outside involvement is not permitted.\n\n"
        "Direct all questions and concerns in <#872692009066958879> <:warriorcat:947992348971905035>"
    )
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
                    body="Below are the CWL Rosters. Once your attacks are complete, make your way to your assigned Clan.\n\nThe Clan Links are on the Spreadsheet. You can also find them in <#1114047624216068136>\n\nDirect all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>",
                    media_url="https://c.tenor.com/aXIInybKvOwAAAAd/tenor.gif", channel_id=main_channel, role_ids=[role],
                    buttons=_buttons(("CWL Rosters", "https://docs.google.com/spreadsheets/d/1GcNVWyx5HjoDm5AbQAOT0_pwyf95KRl_f4lQ0Up3ZBM/edit?usp=sharing", "📋")),
                ),
                "lazy": _variant(
                    title="<:league_medal:949137422933962753> Lazy CWL Time <:league_medal:949137422933962753>",
                    body="Below are the Lazy CWL Rosters. If you cannot view the Roster or do not understand it, please ping <@&769130325460254740> in <#872692009066958879> and we'll get it sorted.\n\nAs soon as both your attacks are complete in the current war make your way to your assigned Clan. __The sooner the better.__\n\nThere are several Bots in the server that can provide war information. To many to list here. Feel free to play around in <#1128848663872028743>. War and CWL are good keywords for looking.",
                    media_url="https://c.tenor.com/aXIInybKvOwAAAAd/tenor.gif", channel_id=lazy_channel, role_ids=[role],
                    buttons=_buttons(("Lazy CWL Rosters", "https://docs.google.com/spreadsheets/d/1GxIuathFuro-xdYM9rVcF2Sob9lyFgDsT7TekkkuK-E/edit#gid=512888016", "😴"), ("LazyCWL Guide", "https://docs.google.com/document/d/137zYF4CHwW-hqwZXzDVmQWONkao1X-XckjGs5Myg-h0/edit", "📖")),
                ),
            },
        },
    }
    for number in range(1, 6):
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
    return {
        "schema_version": SCHEMA_VERSION,
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
    return _deep_merge(default_campaign(), _legacy_override(schedule))


def _month(cycle: str, timezone_name: str):
    if not _CYCLE_RE.match(cycle):
        raise ValueError("cycle must use YYYY-MM")
    year, month = map(int, cycle.split("-"))
    return pendulum.datetime(year, month, 1, tz=timezone_name)


def signup_deadline(campaign: dict, cycle: str):
    tz = campaign.get("timezone", DEFAULT_TIMEZONE)
    month = _month(cycle, tz)
    rule = campaign.get("signup_deadline", {})
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
    transitional = campaign.get("schedules", {}).get(message_id)
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
    deadline_rule = campaign.get("signup_deadline", {})
    try:
        if isinstance(deadline_rule, str):
            pendulum.parse(deadline_rule, tz=campaign.get("timezone", DEFAULT_TIMEZONE))
        elif isinstance(deadline_rule, dict):
            hour, minute = int(deadline_rule.get("hour", 17)), int(deadline_rule.get("minute", 0))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError
            if "day" in deadline_rule and not 1 <= int(deadline_rule["day"]) <= 31:
                raise ValueError
            if int(deadline_rule.get("month_end_offset_days", 0)) < 0:
                raise ValueError
        else:
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Signup deadline is invalid") from exc
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
    campaign = config.get("campaign", config)
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
        kwargs = {"url": button["url"], "label": button["label"]}
        if button.get("emoji"):
            kwargs["emoji"] = button["emoji"]
        buttons.append(LinkButton(**kwargs))
    if buttons:
        children.append(ActionRow(components=buttons))
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


async def load_campaign(mongo, guild_id: int, cycle: str | None = None, now=None) -> dict:
    guild_id = int(guild_id)
    base = default_campaign()
    saved = await mongo.bot_config.find_one({"_id": defaults_id(guild_id)})
    if saved and isinstance(saved.get("campaign"), dict):
        base = _deep_merge(base, saved["campaign"])
    elif guild_id == LEGACY_WU_GUILD_ID and (legacy := await _legacy(mongo)):
        base = _deep_merge(base, _legacy_override(legacy))
    selected_cycle = cycle or cycle_key(now, base.get("timezone", DEFAULT_TIMEZONE))
    row = await mongo.bot_config.find_one({"_id": cycle_id(guild_id, selected_cycle)})
    override = copy.deepcopy(row.get("campaign")) if row else None
    if isinstance(override, dict):
        # Older saved cycle snapshots predate the sequence feature. They keep
        # their individual schedules when future defaults adopt a sequence.
        override.setdefault("reminder_sequence", {"enabled": False})
    # Full cycle snapshots are independent of future monthly defaults,
    # including newly provisioned sequence templates and sequence settings.
    campaign = _deep_merge(default_campaign() if isinstance(override, dict) and "schema_version" in override else base, override)
    validate_campaign(campaign)
    deliveries = copy.deepcopy((row or {}).get("deliveries", []))
    sent_occurrences = list((row or {}).get("sent_occurrences", []))
    skipped = list((row or {}).get("skipped", []))
    result = {
        "guild_id": guild_id,
        "cycle": selected_cycle,
        "revision": int((row or {}).get("revision", 0)),
        "defaults_revision": int((saved or {}).get("revision", 0)),
        "campaign": campaign,
        "deliveries": deliveries,
        "sent_occurrences": sent_occurrences,
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
        saved = await mongo.bot_config.find_one({"_id": defaults_id(guild_id)})
        if saved and isinstance(saved.get("campaign"), dict):
            campaign = _deep_merge(default_campaign(), saved["campaign"])
        elif int(guild_id) == LEGACY_WU_GUILD_ID:
            campaign = campaign_from_legacy(await _legacy(mongo))
        else:
            campaign = default_campaign()
    now = _utcnow()
    token = uuid.uuid4().hex
    draft = {
        "_id": draft_id(guild_id, token), "token": token, "kind": "cwl_campaign_draft",
        "guild_id": int(guild_id), "user_id": int(user_id), "cycle": loaded["cycle"],
        "scope": scope,
        "base_revision": loaded["defaults_revision"] if scope == "defaults" else loaded["revision"],
        "cycle_base_revision": loaded["revision"],
        "defaults_base_revision": loaded["defaults_revision"],
        "campaign": copy.deepcopy(campaign), "created_at": now, "updated_at": now,
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


async def patch_draft(mongo, draft: str, patch: dict) -> dict:
    row = await load_draft(mongo, draft)
    if not row:
        raise ValueError("Draft expired or does not exist")
    allowed = {"campaign", "scope", "cycle", "base_revision", "cycle_base_revision"}
    if set(patch) - allowed:
        raise ValueError("Draft patch contains unsupported fields")
    updated = copy.deepcopy(row)
    if "campaign" in patch:
        validate_campaign(patch["campaign"])
        updated["campaign"] = copy.deepcopy(patch["campaign"])
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
        new_message["schedule"] = copy.deepcopy(old_message.get("schedule", {"mode": "manual"}))
        new_message.setdefault("variants", {})[variant] = copy.deepcopy(old_message.get("variants", {}).get(variant, {}))
        protected.append(oid)
    return protected


async def apply_draft(mongo, draft: str, user_id: int, expected_revision: int | None = None) -> dict:
    row = await load_draft(mongo, draft)
    if not row:
        raise ValueError("Draft expired or does not exist")
    if int(row["user_id"]) != int(user_id):
        raise PermissionError("This draft belongs to another editor")
    guild_id, cycle, scope = int(row["guild_id"]), row["cycle"], row["scope"]
    validate_campaign(row["campaign"])
    live = await load_campaign(mongo, guild_id, cycle)
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
    candidate = copy.deepcopy(row["campaign"])
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
    resolve_schedule(candidate, cycle)
    if scope == "defaults" and candidate.get("reminder_sequence", {}).get("enabled"):
        # Reject a rule that fits this month but would overfill a longer month
        # or bunch reminders in February when monthly defaults roll forward.
        month = _month(cycle, candidate.get("timezone", DEFAULT_TIMEZONE))
        for offset in range(1, 13):
            resolve_schedule(candidate, month.add(months=offset).format("YYYY-MM"))
    target_id = defaults_id(guild_id) if scope == "defaults" else cycle_id(guild_id, cycle)
    active_cycle = cycle_key(timezone_name=candidate.get("timezone", DEFAULT_TIMEZONE))
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
    await mongo.bot_config.delete_one({"_id": row["_id"]})
    result = await load_campaign(mongo, guild_id, cycle)
    result["protected_sent"] = protected
    try:
        from extensions.tasks import cwl_reminder
        if getattr(cwl_reminder, "mongo_client", None) is mongo:
            if scope == "defaults":
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


async def set_paused(mongo, guild_id: int, paused: bool, cycle: str | None = None, user_id: int | None = None):
    loaded = await load_campaign(mongo, guild_id, cycle)
    campaign = copy.deepcopy(loaded["campaign"])
    campaign["paused"] = bool(paused)
    now = _utcnow()
    old_revision = int(loaded["revision"])
    new_revision = old_revision + 1
    update = {"$set": {"kind": "cwl_campaign_cycle", "guild_id": int(guild_id), "cycle": loaded["cycle"], "campaign": campaign, "activated": True, "revision": new_revision, "updated_at": now}, "$push": {
        "actions": {"$each": [{"action": "paused" if paused else "resumed", "at": now, "by": user_id}], "$slice": -HISTORY_LIMIT},
        "revisions": {"$each": [{"revision": new_revision, "at": now, "by": user_id, "action": "paused" if paused else "resumed", "campaign": copy.deepcopy(campaign)}], "$slice": -20},
    }}
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


async def history(mongo, guild_id: int, cycle: str | None = None, limit: int = 25) -> list[dict]:
    loaded = await load_campaign(mongo, guild_id, cycle)
    row = await mongo.bot_config.find_one({"_id": cycle_id(guild_id, loaded["cycle"])}) or {}
    events = list(row.get("revisions", [])) + list(row.get("actions", [])) + list(row.get("deliveries", []))
    events.sort(key=lambda item: item.get("at", ""), reverse=True)
    return copy.deepcopy(events[:max(1, min(int(limit), HISTORY_LIMIT))])
