"""Read-only Clan Games activity for the web Todo page.

ClashKing records positive player stat changes, not an authoritative live Clan
Games score. A missing event is therefore unknown, never zero. The displayed
target is the Warriors United family goal, not an in-game enforcement rule.
"""

import asyncio
import json
import re
from datetime import datetime, timezone
from urllib.parse import quote

import aiohttp


GAMES_GOAL = 1000
HISTORY_LIMIT = 500  # Current ClashKing public history query clamps to 500.
FETCH_CONCURRENCY = 5
MAX_RESPONSE_BYTES = 512 * 1024
HISTORY_URL = "https://api.clashk.ing/v2/player/{tag}/history/stats"
TAG_RE = re.compile(r"^#[0289PYLQGRJCUV]{3,15}$")
SOURCE_NOTE = "Observed Clan Games activity from ClashKing; 1,000 points is the Warriors United family goal."


def _month_window(now):
    now = now.astimezone(timezone.utc)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end


def _timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _safe_integer(value):
    return type(value) is int and 0 <= value <= 1_000_000_000


def _base_row(account):
    return {
        "tag": account.tag,
        "name": account.name,
        "town_hall": account.town_hall,
        "clan_tag": account.clan_tag,
        "clan_name": account.clan_name,
        "badge_url": account.clan_badge,
        "used": None,
        "total": None,
        "remaining": None,
        "state": "unknown",
        "detail": "No recorded Clan Games activity this month; check in game.",
        "starts_at": None,
        "ends_at": None,
    }


async def _fetch_history(session, tag, start, now, semaphore):
    if not isinstance(tag, str) or not TAG_RE.fullmatch(tag.upper()):
        raise ValueError("Invalid player tag")
    params = {
        "type": "clan_games",
        "limit": str(HISTORY_LIMIT),
        "time[after]": start.isoformat().replace("+00:00", "Z"),
        "time[before]": now.isoformat().replace("+00:00", "Z"),
    }
    async with semaphore:
        async with session.get(HISTORY_URL.format(tag=quote(tag.upper(), safe="")), params=params,
                               headers={"Accept": "application/json"}) as response:
            if response.status != 200 or response.content_type != "application/json":
                raise ValueError("ClashKing history unavailable")
            raw = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                raw.extend(chunk)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ValueError("ClashKing history response too large")
            body = json.loads(raw)
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        raise ValueError("Invalid ClashKing history response")
    return body["items"]


def _observations(items, start, now):
    """Return a conservative count plus whether any relevant record was bad."""
    observations = {}
    invalid = False
    for item in items:
        if not isinstance(item, dict) or item.get("statType") != "clan_games":
            invalid = True
            continue
        when = _timestamp(item.get("eventTime"))
        previous, current, delta = (item.get(key) for key in ("previousValue", "currentValue", "delta"))
        if (when is None or not start <= when <= now or not all(_safe_integer(v) for v in (previous, current, delta))
                or delta <= 0 or current - previous != delta):
            invalid = True
            continue
        clan_tag = item.get("clanTag")
        if clan_tag is not None and (not isinstance(clan_tag, str) or not TAG_RE.fullmatch(clan_tag.upper())):
            invalid = True
            continue
        key = (when, clan_tag.upper() if clan_tag else None)
        value = (previous, current, delta)
        if key in observations and observations[key] != value:
            # Conflicting observations of one event cannot safely be summed.
            observations[key] = None
            invalid = True
        else:
            observations.setdefault(key, value)
    valid = [(when, value[2]) for (when, _), value in observations.items() if value is not None]
    total = sum(delta for _, delta in valid)
    latest = max((when for when, _ in valid), default=None)
    return total, invalid, latest


async def build_games_view(accounts):
    """Build the serializable Todo section from resolved ``todo_data.Account``s."""
    accounts = list(accounts or ())
    rows = [_base_row(account) for account in accounts if account.town_hall >= 6]
    if not rows:
        return {"ok": True, "note": SOURCE_NOTE, "notes": [], "unavailable": "",
                "incomplete": "", "rows": rows}

    now = datetime.now(timezone.utc)
    start, _ = _month_window(now)
    semaphore = asyncio.Semaphore(FETCH_CONCURRENCY)
    failures = 0
    partials = 0
    unknowns = 0
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        results = await asyncio.gather(*(
            _fetch_history(session, row["tag"], start, now, semaphore) for row in rows
        ), return_exceptions=True)

    for row, result in zip(rows, results):
        if isinstance(result, Exception):
            failures += 1
            row["detail"] = "Clan Games activity unavailable from ClashKing; check in game."
            continue
        count, invalid, latest = _observations(result, start, now)
        truncated = len(result) >= HISTORY_LIMIT
        if invalid or truncated:
            partials += 1
        if count == 0:
            unknowns += 1
            if invalid or truncated:
                row["detail"] = "Clan Games history is incomplete; check in game."
            continue
        row["used"] = count
        row["total"] = GAMES_GOAL
        row["remaining"] = None if (invalid or truncated) else max(0, GAMES_GOAL - count)
        row["state"] = "partial" if (invalid or truncated) else ("goal_reached" if count >= GAMES_GOAL else "observed")
        date = latest.strftime("%b %-d") if latest else "this month"
        row["detail"] = (f"At least {count:,} points observed; history may be incomplete."
                         if invalid or truncated else f"{count:,} points observed this month; last activity {date} UTC.")

    notes = []
    if failures:
        notes.append(f"ClashKing activity could not be loaded for {failures} account(s).")
    if partials:
        notes.append(f"History was incomplete for {partials} account(s); shown points are a minimum.")
    if unknowns:
        notes.append(f"No usable activity was recorded for {unknowns} account(s); check their in-game scores.")
    return {"ok": failures < len(rows), "note": "; ".join([SOURCE_NOTE, *notes]), "notes": notes,
            "unavailable": "Clan Games activity unavailable from ClashKing" if failures == len(rows) else "",
            "incomplete": "; ".join(notes), "rows": rows}
