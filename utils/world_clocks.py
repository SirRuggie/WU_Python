"""Pure rules for World clocks: names, zones, update marks and channel order.

No database, HTTP or Discord code lives here. The bot task and the dashboard
API both build channel names with these functions, so the preview on the page
is the exact name the task writes.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

GUILD_ID = 644963518025826315
INTERVALS = (6, 10)
DEFAULT_INTERVAL = 6
TIME_FORMATS = ("12h", "24h")
MAX_CLOCKS = 25
NAME_LIMIT = 100  # Discord channel name limit.
CODE = re.compile(r"[A-Z]{2,6}\Z")
# Fixed English names: strftime("%a") would follow the server locale.
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
# Codes from tzdata that are wrong for our members.
ZONE_CODES = {"Asia/Manila": "PHT"}
# Flags that read better than the country flag tzdata would give.
ZONE_FLAGS = {"Europe/Paris": "🇪🇺", "Europe/Berlin": "🇪🇺", "Europe/Amsterdam": "🇪🇺"}

# Quick choices on the Add clock sheet, named by city (Impeccable S8).
CHIPS = (
    ("Los Angeles", "America/Los_Angeles"),
    ("Denver", "America/Denver"),
    ("Chicago", "America/Chicago"),
    ("New York", "America/New_York"),
    ("London", "Europe/London"),
    ("Paris", "Europe/Paris"),
    ("India", "Asia/Kolkata"),
    ("Manila", "Asia/Manila"),
    ("Sydney", "Australia/Sydney"),
    ("São Paulo", "America/Sao_Paulo"),
    ("Jakarta", "Asia/Jakarta"),
    ("Dubai", "Asia/Dubai"),
)


@lru_cache(maxsize=1)
def zones() -> frozenset[str]:
    """IANA zones a staff member may select (no legacy aliases like EST5EDT)."""
    return frozenset(
        name for name in available_timezones()
        if "/" in name and not name.startswith(("Etc/", "SystemV/", "posix/", "right/"))
    )


@lru_cache(maxsize=1)
def _zone_countries() -> dict[str, str]:
    for folder in ("/usr/share/zoneinfo", "/usr/lib/zoneinfo"):
        path = Path(folder) / "zone.tab"
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        countries = {}
        for line in lines:
            parts = line.split("\t")
            if len(parts) >= 3 and not line.startswith("#") and len(parts[0]) == 2:
                countries[parts[2]] = parts[0].upper()
        return countries
    return {}


def flag_for(zone: str) -> str:
    """Country flag for a zone, or an empty string when it is not known."""
    if zone in ZONE_FLAGS:
        return ZONE_FLAGS[zone]
    country = _zone_countries().get(zone, "")
    if not re.fullmatch(r"[A-Z]{2}", country):
        return ""
    return "".join(chr(0x1F1E6 + ord(letter) - ord("A")) for letter in country)


def zone_info(zone: str) -> ZoneInfo:
    if not isinstance(zone, str) or zone not in zones():
        raise ValueError("Select a time zone from the list.")
    try:
        return ZoneInfo(zone)
    except ZoneInfoNotFoundError:
        raise ValueError("Select a time zone from the list.") from None


def auto_code(zone: str, at: datetime) -> str | None:
    """The zone's own code at this moment, or None when tzdata has only a number."""
    if zone in ZONE_CODES:
        return ZONE_CODES[zone]
    code = at.astimezone(zone_info(zone)).tzname() or ""
    return code if CODE.fullmatch(code) else None


def offset_label(offset: timedelta) -> str:
    minutes = int(offset.total_seconds() // 60)
    if minutes == 0:
        return "GMT"
    sign = "+" if minutes > 0 else "-"
    hours, rest = divmod(abs(minutes), 60)
    return f"GMT{sign}{hours}" + (f":{rest:02d}" if rest else "")


def format_time(local: datetime, time_format: str = "12h") -> str:
    if time_format == "24h":
        return f"{local.hour:02d}:{local.minute:02d}"
    hour = local.hour % 12 or 12
    return f"{hour}:{local.minute:02d}{'am' if local.hour < 12 else 'pm'}"


def zone_label(clock: dict, at: datetime) -> str:
    """The name without the time, for example "🇺🇸 EST (GMT-5)" or "🇬🇧 GMT"."""
    local = at.astimezone(zone_info(clock["zone"]))
    code = clock.get("code") or auto_code(clock["zone"], at)
    if not code:
        raise ValueError("Type a code for this time zone.")
    offset = offset_label(local.utcoffset() or timedelta())
    # Only a zero offset drops the offset part; a typed "GMT" on London in summer keeps "GMT+1".
    parts = [clock.get("flag") or "", code if code == "GMT" and offset == "GMT" else f"{code} ({offset})"]
    return " ".join(part for part in parts if part)


def format_day(local: datetime) -> str:
    """Local short weekday and day of the month, for example "Wed 11"."""
    return f"{WEEKDAYS[local.weekday()]} {local.day}"


def clock_name(clock: dict, at: datetime, time_format: str = "12h") -> str:
    """For example "🇺🇸 EST (GMT-5) · 12:12pm · Wed 11"; the day is the zone's own day."""
    local = at.astimezone(zone_info(clock["zone"]))
    name = f"{zone_label(clock, at)} · {format_time(local, time_format)} · {format_day(local)}"
    return name[:NAME_LIMIT]


def other_half(zone: str, at: datetime) -> datetime | None:
    """A moment in the other half of the year when the zone changes offset."""
    info = zone_info(zone)
    now_offset = at.astimezone(info).utcoffset()
    for months in (6, 5, 7, 4, 8):
        probe = at + timedelta(days=30.44 * months)
        if probe.astimezone(info).utcoffset() != now_offset:
            return probe
    return None


# Search-only codes for common zones where tzdata has only a number. They help
# search find the zone; channel names still need a typed code there.
SEARCH_CODES = {"America/Sao_Paulo": ("BRT",), "Asia/Dubai": ("GST",), "Asia/Singapore": ("SGT",)}


def zone_codes(zone: str, at: datetime) -> list[str]:
    """Letter codes the zone uses now and in the other half of the year, for search.

    For example America/Chicago gives ["CST", "CDT"] in November. Numeric-only
    zones give [].
    """
    codes = [auto_code(zone, at)]
    later = other_half(zone, at)
    if later is not None:
        codes.append(auto_code(zone, later))
    codes.extend(SEARCH_CODES.get(zone, ()))
    return list(dict.fromkeys(code for code in codes if code))


def mark(now: datetime, interval: int = DEFAULT_INTERVAL) -> datetime:
    """The latest update mark at or before now (:00, :06, :12 … for 6)."""
    now = now.astimezone(timezone.utc)
    minute = now.minute - now.minute % interval
    return now.replace(minute=minute, second=0, microsecond=0)


def next_mark(now: datetime, interval: int = DEFAULT_INTERVAL) -> datetime:
    return mark(now, interval) + timedelta(minutes=interval)


def offset_minutes(zone: str, at: datetime) -> int:
    return int((at.astimezone(zone_info(zone)).utcoffset() or timedelta()).total_seconds() // 60)


def sort_clocks(clocks: list[dict], at: datetime) -> list[dict]:
    """GMT offset, lowest first; ties keep a stable order by code and id."""
    return sorted(clocks, key=lambda clock: (
        offset_minutes(clock["zone"], at), clock.get("code") or "", str(clock.get("_id") or clock.get("id") or "")))


def positions_for(clocks: list[dict], channels: dict[str, dict], at: datetime) -> dict[str, int]:
    """New positions for clock channels that are out of order.

    Only clock channels move, and only into the positions clock channels in the
    same category already hold. Other channels never move. Returns {} when the
    order is already right or when the positions cannot be swapped safely.
    """
    changes: dict[str, int] = {}
    groups: dict[str, list[dict]] = {}
    clock_channels = {str(clock.get("channel_id") or "") for clock in clocks}
    for clock in clocks:
        channel = channels.get(str(clock.get("channel_id") or ""))
        if channel:
            groups.setdefault(str(channel.get("parent_id") or ""), []).append(clock)
    for group in groups.values():
        if len(group) < 2:
            continue
        current = sorted(group, key=lambda clock: (channels[str(clock["channel_id"])]["position"], str(clock["channel_id"])))
        wanted = sort_clocks(group, at)
        if [c["channel_id"] for c in current] == [c["channel_id"] for c in wanted]:
            continue
        slots = [channels[str(clock["channel_id"])]["position"] for clock in current]
        if len(set(slots)) != len(slots):
            continue  # Duplicate positions: a swap would not change the order.
        parent = str(channels[str(group[0]["channel_id"])].get("parent_id") or "")
        shared = [channel_id for channel_id, channel in channels.items()
                  if channel_id not in clock_channels and channel.get("position") in slots
                  and str(channel.get("parent_id") or "") == parent]
        if shared:
            continue  # Another channel shares a slot; moving clocks could move it too.
        for clock, position in zip(wanted, slots):
            if channels[str(clock["channel_id"])]["position"] != position:
                changes[str(clock["channel_id"])] = position
    return changes


def _hidden(ch: str) -> bool:
    """Invisible or direction characters that can scramble a channel name.

    Allowed: the zero-width joiner (U+200D), which emoji sequences need, and
    the tag characters (U+E0020 to U+E007F) that build the England, Scotland
    and Wales flags.
    """
    if ch == "\u200d" or 0xE0020 <= ord(ch) <= 0xE007F:
        return False
    return unicodedata.category(ch) in ("Cc", "Cf", "Zl", "Zp")


def validate_clock(body: object, at: datetime) -> dict:
    """Normalize a clock edit from the dashboard. Raises ValueError with page text."""
    if not isinstance(body, dict):
        raise ValueError("Check the clock settings.")
    zone = body.get("zone")
    zone_info(zone)
    flag = body.get("flag")
    flag = "" if flag is None else str(flag).strip()
    if (len(flag) > 16 or any(ch in flag for ch in "@#<>`\n\r\t") or any(ch.isalnum() for ch in flag)
            or any(_hidden(ch) for ch in flag)):
        raise ValueError("Select a flag emoji, or leave the flag empty.")
    code = body.get("code")
    code = None if code in (None, "") else str(code).strip().upper()
    if code is not None and not CODE.fullmatch(code):
        raise ValueError("Use 2 to 6 letters for the code.")
    if code is None and auto_code(zone, at) is None:
        raise ValueError("Type a code for this time zone.")
    if code is not None and code == auto_code(zone, at):
        code = None  # Keep the automatic code so summer time still switches it.
    return {"zone": zone, "flag": flag, "code": code}


def preview(clock: dict, at: datetime, time_format: str = "12h") -> dict:
    """Names for the page: now and the other half of the year."""
    later = other_half(clock["zone"], at)
    needs_code = not clock.get("code") and auto_code(clock["zone"], at) is None
    result = {
        "code_auto": auto_code(clock["zone"], at),
        "flag_auto": flag_for(clock["zone"]),
        "needs_code": needs_code,
        "name_now": None if needs_code else clock_name(clock, at, time_format),
        "name_other": None,
        "offset_minutes": offset_minutes(clock["zone"], at),
    }
    if later is not None and not (not clock.get("code") and auto_code(clock["zone"], later) is None):
        result["name_other"] = zone_label(clock, later)
    return result
