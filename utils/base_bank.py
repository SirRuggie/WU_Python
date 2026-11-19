"""Public read-only FWA base projection. Staff configuration is never returned."""

from urllib.parse import urlsplit, parse_qs
from utils import town_halls
from utils.constants import WARRIORS_UNITED_GUILD_ID



def https_url(value, *, clash=False):
    if (
        not isinstance(value, str)
        or len(value) > 4096
        or any(ord(c) <= 32 for c in value)
    ):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username
            or url.password
            or url.port
            or url.fragment
        ):
            return None
        if clash and (
            url.hostname != "link.clashofclans.com"
            or parse_qs(url.query).get("action") != ["OpenLayout"]
            or not parse_qs(url.query).get("id")
        ):
            return None
    except ValueError:
        return None
    return value


def public_bases(document):
    """Project only linked registry variants, never legacy/staff configuration."""
    if document is None:
        return [], {}
    rows, details = [], {}
    for variant in town_halls.base_variants(document):
        instructions = variant["instructions"]
        notes = variant["upgrade_notes"]
        rows.append({"key": variant["key"], "town_hall": variant["level"],
                     "variant": "non-merged" if variant["variant"] == "non_merged" else "merged",
                     "link": variant["link"], "war_base_image": variant["war_image"] or None,
                     "has_details": bool(instructions.strip() or notes.strip())})
        details[variant["key"]] = {"base_information": instructions, "base_upgrade_notes": notes}
    return rows, details


async def read_base_bank(mongo):
    registry = await town_halls.load(mongo, WARRIORS_UNITED_GUILD_ID)
    if registry is None:
        raise town_halls.TownHallsMissing(town_halls.MISSING_MESSAGE)
    return public_bases(registry)
