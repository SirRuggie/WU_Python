"""Short-lived state used by the custom Components V2 dispatcher.

Ticket history used to share ``button_store`` with these documents. New state
lives in its own TTL-backed collection; guarded fallback keeps already-rendered
legacy panels usable during migration without ever moving ticket records.
"""

from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta, timezone

from utils.mongo import MongoClient

_log = logging.getLogger(__name__)

STATE_TTL = timedelta(hours=24)
LEGACY_GRACE = timedelta(days=7)
TTL_INDEX_NAME = "component_state_expiry"
MIGRATION_ID = "component_state_legacy_migration_v1"

_STATE_TYPES = {
    "deny_action",
    "ticket_override",
}
_STATELESS_LEGACY_TYPES = {
    "fwa_links",
    "recruit_aboutus",
    "recruit_familyparticulars",
    "recruit_strikesystem",
}
_GENERIC_STATE_KEYS = {
    "_id",
    "user_id",
    "guild_id",
    "channel_id",
    "remove_roles_page",
}
_LEGACY_PROJECTION_DISCRIMINATORS = {
    "_id",
    "type",
    "challenge_type",
    "command",
    "origin",
    "base_only",
    "recruiter_id",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _filter_for_id(state_id) -> dict:
    return {"_id": state_id}


def _legacy_is_protected(document: dict) -> bool:
    document_id = str(document.get("_id", ""))
    return (
        document.get("type") == "ticket"
        or document.get("challenge_type") == "goblin_ping"
        or document_id.startswith("ticket_")
    )


def legacy_state_kind(document: dict) -> str | None:
    """Classify only audited legacy shapes; unknown rows are preserved."""
    if _legacy_is_protected(document):
        return None

    document_id = str(document.get("_id", ""))
    if document_id.startswith("war_message_"):
        return "dead"
    if document.get("type") in _STATELESS_LEGACY_TYPES:
        return "stateless"
    if document.get("type") in _STATE_TYPES:
        return "state"
    if "command" in document or document.get("origin") == "role_command":
        return "state"
    if "base_only" in document or "recruiter_id" in document:
        return "state"

    keys = set(document)
    if document.get("user_id") is not None and keys <= _GENERIC_STATE_KEYS:
        return "state"

    return None


def _with_expiry(document: dict, *, now: datetime, ttl: timedelta) -> dict:
    stamped = copy.deepcopy(document)
    stamped.setdefault("created_at", now)
    stamped["expires_at"] = now + ttl
    stamped["component_state"] = True
    return stamped


async def insert_state(
    mongo: MongoClient,
    document: dict,
    *,
    ttl: timedelta = STATE_TTL,
):
    """Insert one fixed-lifetime component session without mutating the caller."""
    return await mongo.component_state.insert_one(
        _with_expiry(document, now=utcnow(), ttl=ttl)
    )


async def update_state(
    mongo: MongoClient,
    state_id_or_filter,
    update: dict,
    *,
    upsert: bool = False,
    ttl: timedelta = STATE_TTL,
):
    """Update state without sliding its expiry; stamp metadata only on upsert."""
    filt = (
        state_id_or_filter
        if isinstance(state_id_or_filter, dict)
        else _filter_for_id(state_id_or_filter)
    )
    update_doc = copy.deepcopy(update)
    if upsert:
        now = utcnow()
        update_doc.setdefault("$setOnInsert", {}).update({
            "created_at": now,
            "expires_at": now + ttl,
            "component_state": True,
        })

    result = await mongo.component_state.update_one(filt, update_doc, upsert=upsert)
    if result.matched_count or result.upserted_id is not None or upsert:
        return result

    # An already-rendered pre-migration panel may still live in button_store.
    state_id = filt.get("_id")
    if state_id is not None and await get_state(mongo, state_id) is not None:
        return await mongo.component_state.update_one(filt, update_doc, upsert=False)
    return result


def _projection_mode(projection: dict | None) -> str | None:
    """Return Mongo's inclusion/exclusion mode for simple field projections."""
    if not projection:
        return None
    included = {
        field for field, value in projection.items()
        if field != "_id" and bool(value)
    }
    excluded = {
        field for field, value in projection.items()
        if field != "_id" and not bool(value)
    }
    if included and excluded:
        raise ValueError("cannot mix inclusion and exclusion in a component-state projection")
    if included:
        return "include"
    if excluded:
        return "exclude"
    return "include" if bool(projection.get("_id")) else "exclude"


def _read_projection(
    projection: dict | None,
    *,
    internal_fields: set[str],
) -> dict | None:
    """Add required internal reads without widening the caller-visible result."""
    mode = _projection_mode(projection)
    if mode is None:
        return None
    read = copy.deepcopy(projection)
    if mode == "include":
        for field in internal_fields:
            read[field] = 1
    else:
        for field in internal_fields:
            read.pop(field, None)
    return read


def _apply_projection(document: dict, projection: dict | None) -> dict:
    """Apply Mongo-compatible top-level inclusion or exclusion semantics."""
    mode = _projection_mode(projection)
    if mode is None:
        return document
    if mode == "include":
        result = {
            field: value
            for field, value in document.items()
            if field in projection and bool(projection[field])
        }
        if projection.get("_id", 1) and "_id" in document:
            result["_id"] = document["_id"]
        return result
    return {
        field: value
        for field, value in document.items()
        if bool(projection.get(field, 1))
    }


def _projected_legacy_state_is_recognized(document: dict) -> bool:
    """Classify a partial legacy row only from positive, explicit markers."""
    if _legacy_is_protected(document):
        return False
    if document.get("type") in _STATE_TYPES:
        return True
    if "command" in document or document.get("origin") == "role_command":
        return True
    return "base_only" in document or "recruiter_id" in document


async def _copy_legacy_state(
    mongo: MongoClient,
    document: dict,
    *,
    now: datetime,
) -> bool:
    stamped = _with_expiry(document, now=now, ttl=LEGACY_GRACE)
    # The upsert predicate already supplies the id. Keeping Mongo's immutable
    # ``_id`` field out of the update document avoids driver/server differences
    # around assigning it through $setOnInsert.
    stamped.pop("_id", None)
    stamped["legacy_migrated_at"] = now
    try:
        await mongo.component_state.update_one(
            {"_id": document["_id"]},
            {"$setOnInsert": stamped},
            upsert=True,
        )
    except Exception:
        _log.exception("failed to copy legacy component state %r", document.get("_id"))
        return False

    # Re-assert every protected discriminator in the delete so a row that turns
    # into a ticket/challenge during the copy cannot be removed by this worker.
    await mongo.button_store.delete_one({
        "_id": document["_id"],
        "type": {"$ne": "ticket"},
        "challenge_type": {"$ne": "goblin_ping"},
    })
    return True


async def get_state(
    mongo: MongoClient,
    state_id,
    projection: dict | None = None,
) -> dict | None:
    """Read current state, migrating a positively classified legacy row on use."""
    projection_mode = _projection_mode(projection)
    component_projection = _read_projection(
        projection, internal_fields={"expires_at"}
    )
    component_filter = {"_id": state_id}
    document = (
        await mongo.component_state.find_one(component_filter, component_projection)
        if component_projection is not None
        else await mongo.component_state.find_one(component_filter)
    )
    if document is not None:
        expires_at = document.get("expires_at")
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= utcnow():
                await mongo.component_state.delete_one({"_id": state_id})
                return None
        return _apply_projection(document, projection)

    legacy_filter = {
        "_id": state_id,
        "type": {"$ne": "ticket"},
        "challenge_type": {"$ne": "goblin_ping"},
    }
    legacy_projection = _read_projection(
        projection,
        internal_fields=_LEGACY_PROJECTION_DISCRIMINATORS,
    )
    legacy = (
        await mongo.button_store.find_one(legacy_filter, legacy_projection)
        if legacy_projection is not None
        else await mongo.button_store.find_one(legacy_filter)
    )
    if legacy is None or _legacy_is_protected(legacy):
        return None

    if projection_mode == "include":
        if not _projected_legacy_state_is_recognized(legacy):
            return None
        return _apply_projection(legacy, projection)

    if legacy_state_kind(legacy) == "state":
        await _copy_legacy_state(mongo, legacy, now=utcnow())
    return _apply_projection(legacy, projection)


async def delete_state(mongo: MongoClient, state_id):
    """Delete new state and any exact non-ticket legacy copy."""
    result = await mongo.component_state.delete_one({"_id": state_id})
    await mongo.button_store.delete_one({
        "_id": state_id,
        "type": {"$ne": "ticket"},
        "challenge_type": {"$ne": "goblin_ping"},
    })
    return result


async def migrate_legacy_state(mongo: MongoClient, *, now: datetime | None = None) -> dict:
    """Copy audited legacy sessions with grace, delete dead/stateless rows, preserve unknowns."""
    now = now or utcnow()
    counts = {"migrated": 0, "removed": 0, "protected_or_unknown": 0, "failed": 0}

    async for document in mongo.button_store.find({}):
        kind = legacy_state_kind(document)
        if kind is None:
            counts["protected_or_unknown"] += 1
            continue
        if kind == "state":
            if await _copy_legacy_state(mongo, document, now=now):
                counts["migrated"] += 1
            else:
                counts["failed"] += 1
            continue

        result = await mongo.button_store.delete_one({
            "_id": document["_id"],
            "type": {"$ne": "ticket"},
            "challenge_type": {"$ne": "goblin_ping"},
        })
        counts["removed"] += result.deleted_count

    return counts


async def prepare_storage(mongo: MongoClient) -> dict | None:
    """Install TTL first; only then move/delete positively classified legacy rows."""
    try:
        await mongo.component_state.create_index(
            "expires_at",
            expireAfterSeconds=0,
            name=TTL_INDEX_NAME,
        )
    except Exception:
        _log.exception("component-state TTL index unavailable; legacy cleanup skipped")
        return None

    marker = await mongo.bot_config.find_one({"_id": MIGRATION_ID})
    if marker and marker.get("complete"):
        return {"already_complete": 1}

    counts = await migrate_legacy_state(mongo)
    if counts["failed"] == 0:
        await mongo.bot_config.update_one(
            {"_id": MIGRATION_ID},
            {"$set": {"complete": True, "completed_at": utcnow(), **counts}},
            upsert=True,
        )
    _log.info("component-state legacy cleanup: %s", counts)
    return counts
