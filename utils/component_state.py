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


def _apply_projection(document: dict, projection: dict | None) -> dict:
    if not projection:
        return document
    result = dict(document)
    if projection.get("_id") == 0:
        result.pop("_id", None)
    return result


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
    document = await mongo.component_state.find_one({"_id": state_id})
    if document is not None:
        expires_at = document.get("expires_at")
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=timezone.utc)
            if expires_at <= utcnow():
                await mongo.component_state.delete_one({"_id": state_id})
                return None
        return _apply_projection(document, projection)

    legacy = await mongo.button_store.find_one({
        "_id": state_id,
        "type": {"$ne": "ticket"},
        "challenge_type": {"$ne": "goblin_ping"},
    })
    if legacy is None or _legacy_is_protected(legacy):
        return None

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
