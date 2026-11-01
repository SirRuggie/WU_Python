"""Standard GMT labels, country choices and safe nickname/name selection rules."""

import re
import logging

log = logging.getLogger(__name__)

# Standard offsets are deliberate; familiar aliases are menu text only.
import json
from pathlib import Path

_PICKER = json.loads(Path(__file__).with_name("member_timezone_data.json").read_text())
ZONE_CHOICES = tuple(tuple(row) for row in _PICKER["zones"])
COUNTRY_CHOICES = tuple(tuple(row) for row in _PICKER["countries"])
COUNTRY_ZONES = _PICKER["countryZones"]

SINGLE_ZONE = dict(
    GB="gmt",
    IE="gmt",
    IN="gmt+5:30",
    PH="gmt+8",
    DE="gmt+1",
    PL="gmt+1",
    BD="gmt+6",
    MY="gmt+8",
    KR="gmt+9",
    NO="gmt+1",
    AE="gmt+4",
    AL="gmt+1",
    AR="gmt-3",
    BE="gmt+1",
    BG="gmt+2",
    CO="gmt-5",
    HK="gmt+8",
    NZ="gmt+12",
)


def zones_for_country(country, *, show_all=False):
    keys = COUNTRY_ZONES.get(country) or (
        [SINGLE_ZONE[country]] if country in SINGLE_ZONE else None
    )
    by_id = {row[0]: row for row in ZONE_CHOICES}
    if show_all or not keys:
        return ZONE_CHOICES
    labels = _PICKER.get("countryLabels", {}).get(country, {})
    return tuple((key, by_id[key][1], labels.get(key, by_id[key][2])) for key in keys)


def flag(country):
    if not isinstance(country, str) or not re.fullmatch("[A-Za-z]{2}", country):
        raise ValueError("Use a two-letter country code, such as US.")
    return "".join(chr(ord(c) + 127397) for c in country.upper())


def zone(zone_id):
    for key, offset, description in ZONE_CHOICES:
        if zone_id == key:
            return {
                "zone_id": key,
                "gmt_label": key.upper(),
                "utc_offset_minutes": offset,
            }
    raise ValueError("Choose a time zone from the menu.")


def profile_fields(fields):
    values = zone(fields.get("zone_id"))
    country = fields.get("country")
    values.update(
        country=country.upper() if isinstance(country, str) else country,
        flag=flag(country),
    )
    tag = fields.get("name_source_tag")
    if tag is not None and (
        not isinstance(tag, str) or not re.fullmatch(r"#[0289PYLQGRJCUV]{3,9}", tag)
    ):
        raise ValueError("Invalid name source account.")
    return dict(values, name_source_tag=tag)


def nickname(name, zone_id, country):
    if not isinstance(name, str):
        raise ValueError("Type an in-game name.")
    name = name.strip()
    if not name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("Type a name without line breaks or control characters.")
    value = f"{name} | {zone(zone_id)['gmt_label']} {flag(country)}"
    if len(value) > 32:
        raise ValueError(
            f"Nickname is {len(value)} characters; shorten the name to fit 32."
        )
    return value


def highest_account(accounts, *, complete=True):
    """Only a uniquely highest official TH in a complete result can autofill."""
    usable = [
        row
        for row in accounts
        if isinstance(row, dict)
        and isinstance(row.get("name"), str)
        and row["name"].strip()
        and type(row.get("townHallLevel")) is int
        and row["townHallLevel"] > 0
    ]
    if not complete or len(usable) != len(accounts) or not usable:
        return None
    highest = max(row["townHallLevel"] for row in usable)
    top = [row for row in usable if row["townHallLevel"] == highest]
    return top[0] if len(top) == 1 else None


async def name_choices(coc_client, discord_id):
    """Existing combined links + official player service, bounded and outage-aware."""
    import asyncio
    from utils import recruit_links, todo_data

    try:
        async with asyncio.timeout(20):
            linked = await recruit_links.resolve(int(discord_id))
            tags = list(linked.sources)
            accounts, errors = await todo_data.fetch_accounts(
                coc_client, tags[:200], lookup_timeout=8
            )
        rows = [
            {"tag": a.tag, "name": a.name, "townHallLevel": a.town_hall}
            for a in accounts
        ]
        complete = not (
            linked.unavailable or linked.conflicts or errors or len(tags) > 200
        ) and len(rows) == len(tags)
        return {
            "accounts": rows,
            "suggested": highest_account(rows, complete=complete),
            "complete": complete,
            "unavailable": not complete,
        }
    except Exception as error:
        log.warning("Warrior name lookup unavailable (%s)", type(error).__name__)
        return {
            "accounts": [],
            "suggested": None,
            "complete": False,
            "unavailable": True,
        }
