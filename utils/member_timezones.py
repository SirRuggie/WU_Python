"""Standard GMT labels, country choices and safe nickname/name selection rules."""

import re

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
    ("GB", "United Kingdom"),
    ("IN", "India"),
    ("CA", "Canada"),
    ("AU", "Australia"),
    ("PH", "Philippines"),
    ("DE", "Germany"),
    ("NL", "Netherlands"),
    ("FR", "France"),
    ("IT", "Italy"),
    ("ES", "Spain"),
    ("PT", "Portugal"),
    ("IE", "Ireland"),
    ("PL", "Poland"),
    ("RO", "Romania"),
    ("ZA", "South Africa"),
    ("PK", "Pakistan"),
    ("BD", "Bangladesh"),
    ("ID", "Indonesia"),
    ("MY", "Malaysia"),
    ("SG", "Singapore"),
    ("JP", "Japan"),
    ("KR", "South Korea"),
    ("NZ", "New Zealand"),
)
SINGLE_ZONE = dict(
    GB="gmt",
    IE="gmt",
    PT="gmt",
    IN="gmt+5:30",
    PH="gmt+8",
    DE="gmt+1",
    NL="gmt+1",
    FR="gmt+1",
    IT="gmt+1",
    ES="gmt+1",
    PL="gmt+1",
    RO="gmt+2",
    ZA="gmt+2",
    PK="gmt+5",
    BD="gmt+6",
    MY="gmt+8",
    SG="gmt+8",
    JP="gmt+9",
    KR="gmt+9",
    NZ="gmt+12",
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
    except (TimeoutError, OSError):
        return {
            "accounts": [],
            "suggested": None,
            "complete": False,
            "unavailable": True,
        }
