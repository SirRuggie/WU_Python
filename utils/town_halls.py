"""The server-owned Town Hall registry and its read-only bot snapshot.

The migration creates the document. Ordinary saves are revision-checked
replacements and never create a missing registry or modify legacy weight data.
"""

from copy import deepcopy
from datetime import datetime, timezone
import logging
import re

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils.mongo_routes import collection_from


BASE_CONFLICT_MESSAGE = "This base changed. Refresh and review your edit."
BASE_PATHS = ("war_image", "active_image", "merged.link", "merged.instructions", "merged.upgrade_notes", "non_merged.link", "non_merged.instructions", "non_merged.upgrade_notes")

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
    # Version1 remains readable while the separately authorized bases migration
    # upgrades the existing244 registry; new base content requires version2.
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


def parse_variant_value(value):
    """Accept old Discord values without guessing or accepting arbitrary paths."""
    match = re.fullmatch(r"th([1-9][0-9]?)(_new)?", value) if isinstance(value, str) else None
    if match is None:
        raise ValueError("Select an available base level.")
    return int(match[1]), "non_merged" if match[2] else "merged"


def base_variants(doc):
    """Linked variants only, newest FWA level first and Merged before Non-merged."""
    result = []
    for level in levels(doc):
        if level < doc["lowest_fwa_town_hall"]:
            continue
        bases = doc["levels"][str(level)].get("bases", {})
        for variant in ("merged", "non_merged"):
            values = bases.get(variant, {})
            if not values.get("link"):
                continue
            result.append({"level": level, "key": f"th{level}" + ("_new" if variant == "non_merged" else ""),
                           "variant": variant, "link": values["link"],
                           "instructions": values.get("instructions", ""),
                           "upgrade_notes": values.get("upgrade_notes", ""),
                           "war_image": bases.get("war_image", ""),
                           "active_image": bases.get("active_image", "")})
    return result


def menu_options(doc):
    """Transport-neutral Discord choices, within the native25-option limit."""
    variants = base_variants(doc)
    if len(variants) > 25:
        _LOG.warning("Town Hall base menu has more than25 variants; keeping the highest25.")
    result = []
    for item in variants[:25]:
        label = "Non-merged" if item["variant"] == "non_merged" else "Merged"
        option = {"label": f"TH{item['level']} {label}", "value": item["key"]}
        emoji = emoji_markup(doc, item["level"])
        if emoji:
            option["emoji"] = emoji
        result.append(option)
    return result


def set_base_field(doc, level, path, value):
    """Pure draft update; shared image slots cannot become per-variant images."""
    if path not in BASE_PATHS:
        raise ValueError("Select a valid base field.")
    result, key = _edit(doc, level)
    if level < result["lowest_fwa_town_hall"]:
        raise ValueError("Bases are for FWA Town Hall levels only.")
    result["schema_version"] = 2
    result.setdefault("nonbase_revision", result["revision"])
    target = result["levels"][key].setdefault("bases", {})
    parts = path.split(".")
    if len(parts) == 2:
        target = target.setdefault(parts[0], {})
    target[parts[-1]] = value
    validate(result)
    return result


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


async def save(mongo, guild_id, doc, user_id, expected_revision, *, base_level=None, base_values=None, base_originals=None):
    """Save admin fields without overwriting bases or excusing another admin edit.

    The first CAS uses the client's global revision. A known no-match permits
    one reload/retry only if every intervening revision was base-only. An
    exception/uncertain write is propagated immediately, never retried.
    """
    validate(doc)
    _integer(expected_revision, 0, 2**63 - 2, "Use a valid expected registry revision.")
    _integer(user_id, 1, 2**64 - 1, "Use a valid actor ID.")
    guild = _guild_key(guild_id)
    if "_id" in doc and doc["_id"] != guild:
        raise ValueError("Town Halls belong to a different server.")
    if doc["revision"] != expected_revision:
        raise TownHallsConflict(CONFLICT_MESSAGE)
    base_query, base_changes = ({}, {})
    if base_values is not None:
        base_query, base_changes = _base_write_parts(doc, base_level, base_values, base_originals)
    revision = expected_revision
    collection = _collection(mongo)
    for attempt in range(2):
        changes = {"lowest_fwa_town_hall": doc["lowest_fwa_town_hall"],
                   "nonbase_revision": revision + 1, "updated_by": user_id,
                   "updated_at": datetime.now(timezone.utc)}
        changes.update(base_changes)
        unset = {}
        for level, item in doc["levels"].items():
            changes[f"levels.{level}.emoji"] = item.get("emoji", "")
            if "weight" in item:
                changes[f"levels.{level}.weight"] = deepcopy(item["weight"])
            else:
                unset[f"levels.{level}.weight"] = ""
        update = {"$set": changes, "$inc": {"revision": 1},
                  "$max": {"schema_version": doc["schema_version"]}}
        if unset:
            update["$unset"] = unset
        saved = await collection.find_one_and_update(
            {"_id": guild, "revision": revision, **base_query}, update,
            upsert=False, return_document=ReturnDocument.AFTER)
        if saved is not None:
            return deepcopy(saved)
        current = await load(mongo, guild)
        if current is None:
            raise TownHallsMissing(MISSING_MESSAGE)
        if base_values is not None and any(base_field_snapshot(current, base_level, path) != base_originals[path] for path in base_values):
            raise TownHallsConflict(BASE_CONFLICT_MESSAGE)
        if (current["revision"] < expected_revision or
                current.get("nonbase_revision", current["revision"]) > expected_revision or attempt):
            raise TownHallsConflict(CONFLICT_MESSAGE)
        revision = current["revision"]
    raise TownHallsConflict(CONFLICT_MESSAGE)


def base_field_snapshot(doc, level, path):
    """Preserve missing versus explicitly empty fields for a client's base CAS."""
    if path not in BASE_PATHS:
        raise ValueError("Select a valid base field.")
    validate(doc)
    item = doc["levels"].get(str(_level_number(level)))
    if item is None:
        raise ValueError("This Town Hall is not in the list.")
    target = item.get("bases", {})
    parts = path.split(".")
    if len(parts) == 2:
        target = target.get(parts[0], {})
    return {"exists": True, "value": target[parts[-1]]} if parts[-1] in target else {"exists": False}


def _base_write_parts(current, level, values, originals):
    _level_number(level)
    if not isinstance(values, dict) or not values or not set(values) <= set(BASE_PATHS) or not isinstance(originals, dict) or set(originals) != set(values):
        raise ValueError("Review the changed base fields before saving.")
    if current["schema_version"] != 2 or "nonbase_revision" not in current:
        raise TownHallsMissing("Town Hall bases not migrated")
    proposed = current
    query = {"schema_version": 2,
             "nonbase_revision": {"$exists": True},
             "lowest_fwa_town_hall": {"$lte": level}, f"levels.{level}": {"$exists": True}}
    changes = {}
    for path, value in values.items():
        original = originals[path]
        if not isinstance(original, dict) or type(original.get("exists")) is not bool or set(original) != ({"exists", "value"} if original["exists"] else {"exists"}):
            raise ValueError("Review the original base values before saving.")
        if original["exists"] and not isinstance(original["value"], str):
            raise ValueError("Review the original base values before saving.")
        proposed = set_base_field(proposed, level, path, value)
        field = f"levels.{level}.bases.{path}"
        query[field] = original["value"] if original["exists"] else {"$exists": False}
        changes[field] = value
    return query, changes


async def save_base_fields(mongo, guild_id, level, values, originals, user_id):
    """Atomically CAS exactly the edited base fields, independent of admin edits."""
    _integer(user_id, 1, 2**64 - 1, "Use a valid actor ID.")
    current = await load(mongo, guild_id)
    if current is None:
        raise TownHallsMissing(MISSING_MESSAGE)
    query, changes = _base_write_parts(current, level, values, originals)
    query["_id"] = _guild_key(guild_id)
    changes.update(updated_by=user_id, updated_at=datetime.now(timezone.utc))
    saved = await _collection(mongo).find_one_and_update(
        query, {"$set": changes, "$inc": {"revision": 1}},
        upsert=False, return_document=ReturnDocument.AFTER)
    if saved is None:
        raise TownHallsConflict(BASE_CONFLICT_MESSAGE)
    return deepcopy(saved)


async def apply_bases_migration(mongo, guild_id, current, proposed):
    """One reviewed migration CAS; legacy data and all non-base values stay put."""
    guild = _guild_key(guild_id)
    validate(current)
    validate(proposed)
    if current.get("_id") != guild or proposed.get("_id") != guild:
        raise ValueError("Town Halls belong to a different server.")
    if any("bases" in item for item in current["levels"].values()):
        return False
    query = {"_id": guild, "revision": current["revision"]}
    for level in current["levels"]:
        query[f"levels.{level}.bases"] = {"$exists": False}
    changes = {"schema_version": 2, "nonbase_revision": current.get("nonbase_revision", current["revision"]),
               "updated_at": datetime.now(timezone.utc)}
    for level, item in proposed["levels"].items():
        if "bases" not in item:
            continue
        if level in current["levels"]:
            changes[f"levels.{level}.bases"] = deepcopy(item["bases"])
        else:
            if set(item) != {"emoji", "bases"} or item["emoji"] != "":
                raise ValueError("A migrated missing level has only bases and a blank emoji.")
            changes[f"levels.{level}"] = deepcopy(item)
    if not any(path.startswith("levels.") for path in changes):
        return False
    saved = await _collection(mongo).find_one_and_update(
        query, {"$set": changes, "$inc": {"revision": 1}},
        upsert=False, return_document=ReturnDocument.AFTER)
    return saved is not None


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
