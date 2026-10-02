"""Guild-owned war weight settings. Permanent fwa_data database collection; no TTL."""
from copy import deepcopy
from datetime import datetime, timezone
import re
from pymongo.errors import DuplicateKeyError
from utils.emoji import emojis

DEFAULT_RANGES = {
    9: {"min": 56000, "max": 70000, "display": "56k - 70k"},
    10: {"min": 71000, "max": 90000, "display": "71k - 90k"},
    11: {"min": 91000, "max": 110000, "display": "91k - 110k"},
    12: {"min": 111000, "max": 120000, "display": "111k - 120k"},
    13: {"min": 121000, "max": 130000, "display": "121k - 130k"},
    14: {"min": 131000, "max": 140000, "display": "131k - 140k"},
    15: {"min": 141000, "max": 150000, "display": "141k - 150k"},
    16: {"min": 151000, "max": 160000, "display": "151k - 160k"},
    17: {"min": 161000, "max": 170000, "display": "161k - 170k"},
    18: {"min": 171000, "max": 180000, "display": "171k - 180k"},
}


def collection(mongo):
    return mongo.fwa_data.database.get_collection("war_weight_settings")


def defaults():
    return {"schema_version": 1, "revision": 0, "minimum_th": 9,
            "ranges": {str(k): {**v, "emoji": ""} for k, v in DEFAULT_RANGES.items()}}


async def load(mongo, guild_id):
    return await collection(mongo).find_one({"_id": str(guild_id)}) or defaults()


def ranges(config):
    return {int(k): v for k, v in config["ranges"].items()}


def validate(config):
    entries = ranges(config)
    if not entries or len(entries) > 25:
        raise ValueError("Keep between 1 and 25 Town Hall entries.")
    if config["minimum_th"] not in entries:
        raise ValueError("The lowest displayed Town Hall must be a configured entry.")
    previous = 0
    for th, item in sorted(entries.items()):
        if not 1 <= th <= 99 or not 1 <= item["min"] < item["max"] <= 500000:
            raise ValueError("Use TH1–99 and total weights from 1–500,000, with minimum below maximum.")
        if item["min"] <= previous:
            raise ValueError("Weight ranges must increase with Town Hall level and must not overlap.")
        previous = item["max"]
        emoji = item.get("emoji", "")
        if emoji and not re.fullmatch(r"(?:<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>|[A-Za-z0-9_]{2,32})", emoji):
            raise ValueError("Use an emoji name such as TH_19, a Discord custom emoji, or leave it blank for automatic.")


def edit_entry(config, th, low, high, emoji=""):
    result = deepcopy(config)
    result["ranges"][str(th)] = {"min": low, "max": high,
        "display": f"{low / 1000:g}k - {high / 1000:g}k", "emoji": emoji.strip()}
    validate(result)
    return result


async def save(mongo, guild_id, config, user_id):
    validate(config)
    revision = config.get("revision", 0)
    doc = {**config, "_id": str(guild_id), "guild_id": int(guild_id),
           "revision": revision + 1, "updated_by": int(user_id),
           "updated_at": datetime.now(timezone.utc)}
    try:
        result = await collection(mongo).replace_one(
            {"_id": str(guild_id), "revision": revision}, doc, upsert=revision == 0)
    except DuplicateKeyError:
        raise ValueError("Someone changed these settings. Refresh and try again.") from None
    if not result.matched_count and result.upserted_id is None:
        raise ValueError("Someone changed these settings. Refresh and try again.")


def emoji_for(th, config, available=()):
    if th is None:
        return "❓"
    override = config["ranges"].get(str(th), {}).get("emoji", "")
    if override.startswith("<"):
        return override
    names = (override,) if override else (f"TH_{th}", f"TH{th}")
    for name in names:
        for emoji in available:
            if str(emoji.name).casefold() == name.casefold() and getattr(emoji, "is_available", True):
                return str(emoji)
    return "🏛️" if override else str(getattr(emojis, f"TH{th}", "🏛️"))
