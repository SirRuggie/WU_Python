"""The server-owned Town Hall registry and its read-only bot snapshot.

The migration creates the document. Ordinary saves are revision-checked
replacements and never create a missing registry or modify legacy weight data.
"""

from copy import deepcopy
from datetime import datetime, timezone
import logging
import re

from pymongo.errors import DuplicateKeyError

from utils.mongo_routes import collection_from


CONFLICT_MESSAGE = "Town Halls changed. Refresh and review your edit."
MISSING_MESSAGE = "Town Halls not migrated"
_EMOJI = re.compile(r"<a?:[A-Za-z0-9_]{2,32}:[0-9]{15,22}>")
_LEVEL = re.compile(r"[1-9][0-9]?")
_LOG = logging.getLogger(__name__)
_snapshot = None
_snapshot_guild = None


class TownHallsConflict(ValueError):
    """The supplied revision no longer owns the registry document."""


class TownHallsMissing(ValueError):
    """The separately authorized registry migration has not created a row."""


def _collection(mongo):
    return collection_from(mongo.fwa_data, "town_halls")


def _integer(value, low, high, message):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(message)
    return value


def _level_number(value):
    return _integer(value, 1, 99, "Use a Town Hall level from 1 to 99.")


def _guild_key(value):
    guild = str(value)
    if isinstance(value, bool) or re.fullmatch(r"[1-9][0-9]{0,19}", guild) is None or int(guild) > 2**64 - 1:
        raise ValueError("Use a valid server ID.")
    return guild


def validate(doc):
    """Validate all registry entries together without changing the input."""
    if not isinstance(doc, dict) or type(doc.get("schema_version")) is not int or doc["schema_version"] not in (1, 2):
        raise ValueError("Use Town Halls registry schema version 1 or 2.")
    if not set(doc) <= {"_id", "schema_version", "revision", "lowest_fwa_town_hall", "levels", "updated_by", "updated_at", "nonbase_revision"}:
        raise ValueError("Unknown Town Halls registry field.")
    _integer(doc.get("revision"), 0, 2**63 - 1, "Use a valid registry revision.")
    if "nonbase_revision" in doc:
        _integer(doc["nonbase_revision"], 0, doc["revision"], "Use a valid Town Hall edit revision.")
    entries = doc.get("levels")
    if not isinstance(entries, dict) or not 1 <= len(entries) <= 30:
        raise ValueError("Keep between 1 and 30 Town Hall levels.")
    lowest = _level_number(doc.get("lowest_fwa_town_hall"))
    previous_max = 0
    ordered = []
    for key, item in entries.items():
        if not isinstance(key, str) or _LEVEL.fullmatch(key) is None:
            raise ValueError("Use canonical Town Hall level keys from 1 to 99.")
        if not isinstance(item, dict) or not set(item) <= {"emoji", "weight", "bases"}:
            raise ValueError("Each Town Hall stores only an emoji, optional weight and bases.")
        if "bases" in item:
            if doc["schema_version"] != 2:
                raise ValueError("Base content requires Town Halls registry schema version 2.")
            _validate_bases(item["bases"])
        emoji = item.get("emoji", "")
        if not isinstance(emoji, str) or (emoji and _EMOJI.fullmatch(emoji) is None):
            raise ValueError("Select a Discord custom emoji or leave it blank.")
        weight = item.get("weight")
        if "weight" in item:
            if not isinstance(weight, dict) or set(weight) != {"min", "max"}:
                raise ValueError("A weight range needs only minimum and maximum weights.")
            low = _integer(weight["min"], 1, 500000, "Use whole weights from 1 to 500,000.")
            high = _integer(weight["max"], 1, 500000, "Use whole weights from 1 to 500,000.")
            if low >= high:
                raise ValueError("Minimum weight must be below maximum weight.")
            ordered.append((int(key), low, high))
    for _level, low, high in sorted(ordered):
        if low <= previous_max:
            raise ValueError("Weight ranges must increase with Town Hall level and must not overlap.")
        previous_max = high
    if str(lowest) not in entries or "weight" not in entries[str(lowest)]:
        raise ValueError("The lowest FWA Town Hall must be a listed level with a weight range.")


def _validate_bases(bases):
    # Reuse the established public URL rule without a module-import cycle.
    from utils.base_bank import https_url
    if not isinstance(bases, dict) or not set(bases) <= {"war_image", "active_image", "merged", "non_merged"}:
        raise ValueError("Use shared base images and Merged or Non-merged fields.")
    for slot in ("war_image", "active_image"):
        value = bases.get(slot, "")
        if not isinstance(value, str) or (value and https_url(value) is None):
            raise ValueError("Use a public HTTPS base image URL or leave it blank.")
    for variant in ("merged", "non_merged"):
        values = bases.get(variant, {})
        if not isinstance(values, dict) or not set(values) <= {"link", "instructions", "upgrade_notes"}:
            raise ValueError("A base variant stores only its link, instructions and upgrade notes.")
        for field, value in values.items():
            if not isinstance(value, str):
                raise ValueError("Base fields must be text.")
            if field == "link":
                if value and https_url(value, clash=True) is None:
                    raise ValueError("Use a Clash OpenLayout base link or leave it blank.")
            elif len(value) > 4000:
                raise ValueError("Keep base instructions and upgrade notes within 4,000 characters.")


async def load(mongo, guild_id):
    """Read a registry; missing means not migrated, never implicit defaults."""
    doc = await _collection(mongo).find_one({"_id": _guild_key(guild_id)})
    if doc is None:
        return None
    validate(doc)
    return deepcopy(doc)


async def migration_count(mongo):
    """Count registry documents for the separately authorized migration report."""
    return await _collection(mongo).count_documents({})


async def create_for_migration(mongo, guild_id, doc):
    """Insert once for the migration tool; never replace an existing registry.

    This is deliberately separate from normal Save. Only the migration tool
    calls it, after its explicit dry-run/apply decision and release authorization.
    """
    guild = _guild_key(guild_id)
    validate(doc)
    if doc.get("_id") != guild:
        raise ValueError("Town Halls belong to a different server.")
    collection = _collection(mongo)
    if await collection.find_one({"_id": guild}, {"_id": 1}) is not None:
        return False
    try:
        await collection.insert_one(deepcopy(doc))
    except DuplicateKeyError:
        # A competing migration may have inserted the same primary key. Verify
        # that row exists; a different uniqueness failure is not called success.
        if await collection.find_one({"_id": guild}, {"_id": 1}) is None:
            raise
        return False
    return True


async def save(mongo, guild_id, doc, user_id, expected_revision):
    """Replace the one guild document only when its revision still matches.

    The caller owns authorization. Distinct typed failures let its HTTP adapter
    map conflicts to 409 and missing migration to readiness/unavailable errors.
    A failed/uncertain write is never retried here.
    """
    validate(doc)
    _integer(expected_revision, 0, 2**63 - 2, "Use a valid expected registry revision.")
    _integer(user_id, 1, 2**64 - 1, "Use a valid actor ID.")
    guild = _guild_key(guild_id)
    if "_id" in doc and doc["_id"] != guild:
        raise ValueError("Town Halls belong to a different server.")
    if doc["revision"] != expected_revision:
        raise TownHallsConflict(CONFLICT_MESSAGE)
    replacement = deepcopy(doc)
    replacement.update(
        _id=guild,
        revision=expected_revision + 1,
        updated_by=user_id,
        updated_at=datetime.now(timezone.utc),
    )
    if replacement['schema_version'] == 2:
        replacement['nonbase_revision'] = expected_revision + 1
    result = await _collection(mongo).replace_one(
        {"_id": guild, "revision": expected_revision}, replacement, upsert=False
    )
    if result.matched_count != 1:
        if await _collection(mongo).find_one({"_id": guild}, {"_id": 1}) is None:
            raise TownHallsMissing(MISSING_MESSAGE)
        raise TownHallsConflict(CONFLICT_MESSAGE)
    return deepcopy(replacement)


def levels(doc):
    """Return configured level numbers newest first."""
    validate(doc)
    return sorted((int(key) for key in doc["levels"]), reverse=True)


def fwa_levels(doc):
    """Return only weighted levels at or above the configured FWA minimum."""
    return [
        level for level in levels(doc)
        if level >= doc["lowest_fwa_town_hall"] and "weight" in doc["levels"][str(level)]
    ]


def weight_ranges(doc):
    """Adapt registry weights to the existing calculator's read-only shape."""
    result = {}
    for level in fwa_levels(doc):
        weight = deepcopy(doc["levels"][str(level)]["weight"])
        weight["display"] = f"{weight['min'] / 1000:g}k - {weight['max'] / 1000:g}k"
        result[level] = weight
    return result


def emoji_markup(doc, level):
    """Return the saved markup or the empty fallback; never guess an emoji."""
    if doc is None or type(level) is not int or not 1 <= level <= 99:
        return ""
    return doc.get("levels", {}).get(str(level), {}).get("emoji", "")


def _edit(doc, level):
    validate(doc)
    key = str(_level_number(level))
    if key not in doc["levels"]:
        raise ValueError("This Town Hall is not in the list.")
    return deepcopy(doc), key


def add_level(doc, level, emoji=""):
    validate(doc)
    key = str(_level_number(level))
    if key in doc["levels"]:
        raise ValueError("This Town Hall is already in the list. Open it to edit.")
    result = deepcopy(doc)
    result["levels"][key] = {"emoji": emoji}
    validate(result)
    return result


def set_emoji(doc, level, emoji):
    result, key = _edit(doc, level)
    result["levels"][key]["emoji"] = emoji
    validate(result)
    return result


def set_weight(doc, level, minimum, maximum):
    """Set a weight pair, or remove an optional range when both are None."""
    result, key = _edit(doc, level)
    if minimum is None and maximum is None:
        result["levels"][key].pop("weight", None)
    else:
        result["levels"][key]["weight"] = {"min": minimum, "max": maximum}
    validate(result)
    return result


def set_lowest_fwa(doc, level):
    result = deepcopy(doc)
    result["lowest_fwa_town_hall"] = _level_number(level)
    validate(result)
    return result


def snapshot(guild_id=None):
    """Return an independent copy of the single bot-owned last-good snapshot."""
    if guild_id is not None and str(guild_id) != _snapshot_guild:
        return None
    return deepcopy(_snapshot)


def town_hall_emoji(level):
    """Synchronous bot lookup; callers render plain TH text on an empty result."""
    return emoji_markup(_snapshot, level)


async def refresh_snapshot(mongo, guild_id, *, log_failure=True, expected_revision=None):
    """Refresh without writing; errors preserve the last good snapshot.

    Startup and the five-minute worker schedule call this same owner. Startup
    can suppress the WARNING and report its required migration ERROR itself.
    """
    global _snapshot, _snapshot_guild
    try:
        doc = await load(mongo, guild_id)
        if doc is None:
            raise TownHallsMissing(MISSING_MESSAGE)
    except Exception:
        if log_failure:
            _LOG.warning("Town Halls could not refresh; keeping the last saved snapshot.")
        return False
    if expected_revision is not None and doc["revision"] != expected_revision:
        return False
    guild = str(guild_id)
    if _snapshot_guild == guild and _snapshot is not None and doc["revision"] < _snapshot["revision"]:
        return False
    _snapshot = deepcopy(doc)
    _snapshot_guild = guild
    return True
