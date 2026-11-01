"""Standard GMT labels, country choices and safe nickname/name selection rules."""

import re
import logging

log = logging.getLogger(__name__)

# Standard offsets are deliberate; labels can differ from summer civil time.
ZONE_CHOICES = (
    ("gmt-8", -480, "US Pacific"),
    ("gmt-7", -420, "US Mountain"),
    ("gmt-6", -360, "US Central"),
    ("gmt-5", -300, "US Eastern"),
    ("gmt-4", -240, "Atlantic"),
    ("gmt-3", -180, "Brazil / Argentina"),
    ("gmt", 0, "UK / Ireland / Portugal"),
    ("gmt+1", 60, "Germany / France / Spain / Italy"),
    ("gmt+2", 120, "Eastern Europe / South Africa"),
    ("gmt+3", 180, "Turkey / Saudi / Moscow"),
    ("gmt+4", 240, "UAE"),
    ("gmt+5", 300, "Pakistan"),
    ("gmt+5:30", 330, "India"),
    ("gmt+6", 360, "Bangladesh"),
    ("gmt+7", 420, "Thailand / Vietnam / Indonesia"),
    ("gmt+8", 480, "Philippines / Malaysia / Singapore"),
    ("gmt+9", 540, "Japan / Korea"),
    ("gmt+10", 600, "Australia East"),
    ("gmt+12", 720, "New Zealand"),
)
COUNTRY_CHOICES = (
    ("US", "United States"),
    ("IN", "India"),
    ("CA", "Canada"),
    ("GB", "United Kingdom"),
    ("AU", "Australia"),
    ("BD", "Bangladesh"),
    ("DE", "Germany"),
    ("PH", "Philippines"),
    ("ID", "Indonesia"),
    ("MY", "Malaysia"),
    ("NZ", "New Zealand"),
    ("ES", "Spain"),
    ("NO", "Norway"),
    ("PL", "Poland"),
    ("AE", "United Arab Emirates"),
    ("AL", "Albania"),
    ("AR", "Argentina"),
    ("BE", "Belgium"),
    ("BG", "Bulgaria"),
    ("BR", "Brazil"),
    ("CO", "Colombia"),
    ("HK", "Hong Kong"),
    ("IE", "Ireland"),
    ("KR", "South Korea"),
)

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
)


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
    from utils.member_timezone_import import canonical_zone

    if isinstance(zone_id, str):
        match = re.fullmatch(r"gmt([+-])([0-9]{1,2})(?::([0-5][0-9]))?", zone_id)
        if match:
            offset = (int(match[2]) * 60 + int(match[3] or 0)) * (
                -1 if match[1] == "-" else 1
            )
            checked = canonical_zone(offset)
            if checked["zone_id"] == zone_id:
                return checked
    raise ValueError("Choose a valid GMT time zone.")


def profile_fields(fields, *, source=None):
    values = zone(fields.get("zone_id"))
    country = fields.get("country")
    values.update(
        country=country.upper() if isinstance(country, str) else country,
        flag=None if country is None and source == "nickname_import" else flag(country),
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
            f"Nickname is {len(value)} characters; shorten the name to fit32."
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
