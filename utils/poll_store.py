"""Durable storage operations for Discord polls.

Active polls intentionally have no TTL field.  Once a poll ends, ``end_poll``
adds ``purge_at`` and Mongo removes the completed record after the fixed
retention window. Every user-facing read is scoped by guild; the only global
reads are the scheduler's startup and due-poll scans.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ReturnDocument

from utils.mongo import MongoClient


ENDED_RETENTION = timedelta(days=30)
ACTIVE_LIST_LIMIT = 25
DUE_LIST_LIMIT = 100

GUILD_ACTIVE_END_INDEX = "polls_guild_active_ends_at"
DUE_END_INDEX = "polls_active_ends_at"
PURGE_INDEX = "polls_ttl_purge_at"
SYNC_PENDING_INDEX = "polls_message_sync_pending"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _utc(value: datetime | None = None) -> datetime:
    value = value or utcnow()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coll(mongo: MongoClient):
    return mongo.discord_polls


def _limit(value: int, default: int) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return default


async def ensure_indexes(mongo: MongoClient) -> None:
    """Install indexes for guild views, the deadline worker, and retention."""
    collection = _coll(mongo)
    await collection.create_index(
        [("guild_id", 1), ("active", 1), ("ends_at", 1)],
        name=GUILD_ACTIVE_END_INDEX,
    )
    await collection.create_index(
        [("active", 1), ("ends_at", 1)],
        name=DUE_END_INDEX,
    )
    await collection.create_index(
        "purge_at",
        expireAfterSeconds=0,
        name=PURGE_INDEX,
    )
    await collection.create_index(
        [("message_sync_pending", 1), ("updated_at", 1)],
        name=SYNC_PENDING_INDEX,
    )


async def create_poll(
    mongo: MongoClient,
    document: Mapping[str, Any],
    *,
    observed_at: datetime | None = None,
) -> dict:
    """Insert a new active poll while enforcing its durable-state invariants.

    Feature-specific fields such as title, choices, creator, and message IDs
    stay owned by the command layer.  This seam owns lifecycle fields only.
    """
    poll = copy.deepcopy(dict(document))
    if poll.get("_id") is None:
        raise ValueError("poll document requires _id")
    if poll.get("guild_id") is None:
        raise ValueError("poll document requires guild_id")
    if not isinstance(poll.get("ends_at"), datetime):
        raise TypeError("poll document requires datetime ends_at")

    now = _utc(observed_at)
    ends_at = _utc(poll["ends_at"])
    if ends_at <= now:
        raise ValueError("active poll ends_at must be in the future")

    poll["guild_id"] = int(poll["guild_id"])
    poll["ends_at"] = ends_at
    poll["active"] = True
    poll["created_at"] = _utc(poll.get("created_at") or now)
    poll["updated_at"] = now
    poll.setdefault("votes", {})
    poll["message_sync_pending"] = False

    # A TTL value on an active poll would make restart recovery unreliable.
    poll.pop("ended_at", None)
    poll.pop("ended_reason", None)
    poll.pop("purge_at", None)

    await _coll(mongo).insert_one(poll)
    return poll


async def get_poll(
    mongo: MongoClient,
    *,
    guild_id: int,
    poll_id: str,
) -> dict | None:
    """Return one poll only when it belongs to the requesting guild."""
    return await _coll(mongo).find_one({
        "_id": poll_id,
        "guild_id": int(guild_id),
    })


async def list_recent_polls(
    mongo: MongoClient,
    *,
    guild_id: int,
    limit: int = ACTIVE_LIST_LIMIT,
) -> list[dict]:
    """Return recent active and ended polls for one guild."""
    length = _limit(limit, ACTIVE_LIST_LIMIT)
    cursor = (
        _coll(mongo)
        .find({"guild_id": int(guild_id)})
        .sort("created_at", -1)
        .limit(length)
    )
    return await cursor.to_list(length=length)


async def list_active_polls(
    mongo: MongoClient,
    *,
    guild_id: int,
    observed_at: datetime | None = None,
    limit: int = ACTIVE_LIST_LIMIT,
) -> list[dict]:
    """Return unexpired active polls for one guild, soonest ending first."""
    now = _utc(observed_at)
    length = _limit(limit, ACTIVE_LIST_LIMIT)
    cursor = (
        _coll(mongo)
        .find({
            "guild_id": int(guild_id),
            "active": True,
            "ends_at": {"$gt": now},
        })
        .sort("ends_at", 1)
        .limit(length)
    )
    return await cursor.to_list(length=length)


async def list_open_polls(
    mongo: MongoClient,
    *,
    observed_at: datetime | None = None,
    limit: int | None = None,
) -> list[dict]:
    """Return every unexpired active poll for startup rescheduling."""
    now = _utc(observed_at)
    cursor = (
        _coll(mongo)
        .find({"active": True, "ends_at": {"$gt": now}})
        .sort("ends_at", 1)
    )
    if limit is None:
        return await cursor.to_list(length=None)
    length = _limit(limit, DUE_LIST_LIMIT)
    return await cursor.limit(length).to_list(length=length)


async def list_due_polls(
    mongo: MongoClient,
    *,
    observed_at: datetime | None = None,
    limit: int = DUE_LIST_LIMIT,
) -> list[dict]:
    """Return active polls whose persisted deadline has passed."""
    now = _utc(observed_at)
    length = _limit(limit, DUE_LIST_LIMIT)
    cursor = (
        _coll(mongo)
        .find({"active": True, "ends_at": {"$lte": now}})
        .sort("ends_at", 1)
        .limit(length)
    )
    return await cursor.to_list(length=length)


async def list_pending_message_sync(
    mongo: MongoClient,
    *,
    limit: int | None = None,
) -> list[dict]:
    """Return poll messages whose durable state still needs to be rendered."""
    cursor = (
        _coll(mongo)
        .find({"message_sync_pending": True})
        .sort("updated_at", 1)
    )
    if limit is None:
        return await cursor.to_list(length=None)
    length = _limit(limit, DUE_LIST_LIMIT)
    return await cursor.limit(length).to_list(length=length)


async def record_vote(
    mongo: MongoClient,
    *,
    guild_id: int,
    poll_id: str,
    user_id: int,
    choice: int | str,
    observed_at: datetime | None = None,
) -> dict | None:
    """Atomically record or replace one user's vote on a live poll.

    Reasserting the guild, active flag, and deadline in the write filter closes
    the race between a button click and the deadline worker ending the poll.
    """
    now = _utc(observed_at)
    return await _coll(mongo).find_one_and_update(
        {
            "_id": poll_id,
            "guild_id": int(guild_id),
            "active": True,
            "ends_at": {"$gt": now},
        },
        {"$set": {
            f"votes.{int(user_id)}": choice,
            # The vote and its need for a public re-render are one durable
            # transition. A process death after this write is recovered at startup.
            "message_sync_pending": True,
            "message_sync_error": None,
            "updated_at": now,
        }},
        return_document=ReturnDocument.AFTER,
    )


async def end_poll(
    mongo: MongoClient,
    *,
    guild_id: int,
    poll_id: str,
    reason: str,
    observed_at: datetime | None = None,
) -> dict | None:
    """Atomically end an active poll and begin its 30-day retention window."""
    ended_at = _utc(observed_at)
    ended_reason = str(reason).strip()
    if not ended_reason:
        raise ValueError("poll end reason must not be empty")

    return await _coll(mongo).find_one_and_update(
        {
            "_id": poll_id,
            "guild_id": int(guild_id),
            "active": True,
        },
        {"$set": {
            "active": False,
            "ended_at": ended_at,
            "ended_reason": ended_reason,
            "purge_at": ended_at + ENDED_RETENTION,
            "message_sync_pending": True,
            "message_sync_error": None,
            "updated_at": ended_at,
        }},
        return_document=ReturnDocument.AFTER,
    )


async def mark_message_sync_pending(
    mongo: MongoClient,
    *,
    guild_id: int,
    poll_id: str,
    error: str,
    observed_at: datetime | None = None,
) -> dict | None:
    """Persist a transient public-message render failure for later recovery."""
    now = _utc(observed_at)
    return await _coll(mongo).find_one_and_update(
        {"_id": poll_id, "guild_id": int(guild_id)},
        {"$set": {
            "message_sync_pending": True,
            "message_sync_error": str(error)[:120],
            "updated_at": now,
        }},
        return_document=ReturnDocument.AFTER,
    )


async def mark_message_synced(
    mongo: MongoClient,
    *,
    guild_id: int,
    poll_id: str,
    observed_at: datetime | None = None,
) -> dict | None:
    """Clear durable render recovery after Discord matches the saved poll."""
    now = _utc(observed_at)
    return await _coll(mongo).find_one_and_update(
        {"_id": poll_id, "guild_id": int(guild_id)},
        {"$set": {
            "message_sync_pending": False,
            "message_sync_error": None,
            "message_synced_at": now,
            "updated_at": now,
        }},
        return_document=ReturnDocument.AFTER,
    )


async def mark_message_unavailable(
    mongo: MongoClient,
    *,
    guild_id: int,
    poll_id: str,
    error: str,
    observed_at: datetime | None = None,
) -> dict | None:
    """Stop retrying a message Discord says is deleted or inaccessible."""
    now = _utc(observed_at)
    return await _coll(mongo).find_one_and_update(
        {"_id": poll_id, "guild_id": int(guild_id)},
        {"$set": {
            "message_sync_pending": False,
            "message_sync_error": str(error)[:120],
            "message_sync_terminal": True,
            "updated_at": now,
        }},
        return_document=ReturnDocument.AFTER,
    )
