"""One bounded automatic /todo panel per user and DM channel.

The deterministic ``dm:{user_id}:{channel_id}`` key makes replacement atomic at
the ownership layer. ``message_id`` identifies the Discord panel and
``generation`` prevents delayed scheduler work from changing a replacement.

TTL
---
New ``/todo`` and **Check now** set an exact 30-day deadline. Navigation and
background checks never extend it. Mongo's TTL index removes abandoned owners.

EVERYTHING HERE IS NON-FATAL
----------------------------
A Mongo failure must never take the dashboard down. The dashboard remains
manually usable without this collection; only automatic checks depend on it.
Every entry point swallows and logs.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

AUTO_REFRESH_ENABLED = True

TTL_SECONDS = 30 * 24 * 60 * 60
REFRESH_INTERVAL_SECONDS = 10 * 60
REFRESH_POLL_SECONDS = 60
REFRESH_BATCH_SIZE = 100
REFRESH_CONCURRENCY = 4

# Retry at most hourly rather than on every interaction. A transient startup
# outage must not disable TTL cleanup until restart, but repeated failures also
# must not flood the log.
_index_ready = False
_index_failed = False
_index_retry_at = 0.0
INDEX_RETRY_SECONDS = 60 * 60


def _coll(mongo):
    return mongo.todo_sessions


def session_id(user_id: int, channel_id: int) -> str:
    """Stable owner key shared by commands, components, and the scheduler."""
    return f"dm:{int(user_id)}:{int(channel_id)}"


async def ensure_indexes(mongo) -> None:
    """Create the TTL index, retrying hourly after failure; never fatal.

    Lazy rather than called from main.py's startup: this module is only reached
    by /todo, so the index is only needed when /todo is first used, and keeping
    it self-contained means the feature can be removed by deleting two files.

    Without the index nothing breaks - rows are still written and read
    correctly, they just never self-prune.
    """
    global _index_ready, _index_failed, _index_retry_at
    if _index_ready:
        return
    if _index_failed and time.monotonic() < _index_retry_at:
        return
    try:
        await _coll(mongo).create_index(
            "expires_at", expireAfterSeconds=0, name="ttl_expires_at"
        )
        await _coll(mongo).create_index(
            [("active", 1), ("next_refresh_at", 1)],
            name="due_active_next_refresh",
        )
        _index_ready = True
        _index_failed = False
        _index_retry_at = 0.0
        print("[todo-sessions] TTL index ready on todo_sessions.expires_at")
    except Exception as exc:  # noqa: BLE001
        _index_failed = True
        _index_retry_at = time.monotonic() + INDEX_RETRY_SECONDS
        print(
            f"[todo-sessions] WARNING: could not create TTL index "
            f"({type(exc).__name__}: {exc}). Rows are still written; "
            f"todo_sessions will not self-prune until index setup retries."
        )


async def read_owner(
    mongo,
    *,
    user_id: int,
    channel_id: int,
    include_expired: bool = True,
) -> tuple[bool, dict | None]:
    """Return ``(read_succeeded, owner)``; failure is distinct from no owner."""
    if mongo is None:
        return False, None
    query: dict = {"_id": session_id(user_id, channel_id)}
    if not include_expired:
        query |= {
            "active": True,
            "refresh_until": {"$gt": datetime.now(timezone.utc)},
        }
    try:
        return True, await _coll(mongo).find_one(query)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-sessions] owner read failed for {query['_id']}: "
              f"{type(exc).__name__}: {exc}")
        return False, None


async def active_panels(
    mongo,
    *,
    user_id: int,
    channel_id: int,
    observed_at: datetime | None = None,
) -> tuple[bool, list[dict]]:
    """Read promised panels, including short-lived legacy message-keyed rows."""
    if mongo is None:
        return False, []
    now = _utc(observed_at)
    try:
        cursor = _coll(mongo).find({
            "user_id": int(user_id),
            "channel_id": int(channel_id),
            "is_dm": True,
            "active": True,
            "refresh_until": {"$gt": now},
        })
        return True, await cursor.to_list(length=None)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-sessions] active-panel read failed for "
              f"user={user_id} channel={channel_id}: {type(exc).__name__}: {exc}")
        return False, []


def panel_message_id(document: dict) -> int:
    """Message id from current owner rows or pre-owner legacy rows."""
    value = document.get("message_id", document.get("_id", 0))
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


async def claim(
    mongo,
    *,
    user_id: int,
    channel_id: int,
    message_id: int,
    view: str,
    expected_owner: dict | None,
    page: int = 0,
    kind: str = "dashboard",
    trigger: str = "command",
) -> tuple[str, datetime] | None:
    """CAS ownership to ``message_id`` and start an exact 30-day window."""
    if mongo is None or not message_id:
        return None

    await ensure_indexes(mongo)

    now = time.time()
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
    until = new_refresh_until(observed_at=now_dt)
    owner_id = session_id(user_id, channel_id)
    generation = uuid.uuid4().hex
    fields = {
        "user_id": int(user_id),
        "channel_id": int(channel_id),
        "message_id": int(message_id),
        "generation": generation,
        "guild_id": None,
        "is_dm": True,
        "active": True,
        "view": view,
        "page": int(page),
        "kind": kind,
        "last_trigger": trigger,
        "updated_at": now,
        "last_checked_at": now_dt,
        "next_refresh_at": now_dt + timedelta(seconds=REFRESH_INTERVAL_SECONDS),
        "refresh_until": until,
        "expires_at": until,
    }
    try:
        # Absence cannot be expressed safely as an upsert: a competing insert
        # between read_owner() and update_one(upsert=True) would be matched and
        # overwritten. Insert-only makes DuplicateKeyError the lost-race CAS.
        if expected_owner is None:
            await _coll(mongo).insert_one({
                "_id": owner_id,
                **fields,
                "created_at": now,
                "interactions": 1,
            })
            return generation, until

        query: dict = {"_id": owner_id}
        if expected_owner.get("generation") is None:
            query["generation"] = {"$exists": False}
        else:
            query["generation"] = expected_owner.get("generation")
        if expected_owner.get("message_id") is not None:
            query["message_id"] = expected_owner.get("message_id")
        result = await _coll(mongo).update_one(
            query,
            {
                "$set": fields,
                "$inc": {"interactions": 1},
            },
            upsert=False,
        )
    except DuplicateKeyError:
        print(f"[todo-sessions] claim lost insert race for user={user_id} "
              f"channel={channel_id} message={message_id}")
        return None
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-sessions] claim failed for message {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return None
    matched = int(getattr(result, "matched_count", 0) or 0)
    if not matched:
        print(f"[todo-sessions] claim lost race for user={user_id} "
              f"channel={channel_id} message={message_id}")
        return None
    return generation, until


async def remove_legacy_rows(mongo, documents: list[dict]) -> bool:
    """Remove superseded message-keyed rows after their panels are manual."""
    legacy_ids = [
        doc.get("_id")
        for doc in documents
        if isinstance(doc.get("_id"), int)
    ]
    if not legacy_ids:
        return True
    try:
        await _coll(mongo).delete_many({"_id": {"$in": legacy_ids}})
        return True
    except Exception as exc:  # noqa: BLE001 - TTL still bounds these rows
        print(f"[todo-sessions] legacy cleanup failed ids={legacy_ids[:5]}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def due(mongo, *, observed_at: datetime | None = None,
              limit: int = REFRESH_BATCH_SIZE) -> list[dict]:
    """Return active DM panels whose next automatic check is due."""
    if mongo is None:
        return []
    now = _utc(observed_at)
    try:
        cursor = _coll(mongo).find({
            "is_dm": True,
            "active": True,
            "next_refresh_at": {"$lte": now},
            "refresh_until": {"$gt": now},
        }).sort("next_refresh_at", 1).limit(int(limit))
        return await cursor.to_list(length=int(limit))
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session read failed: {type(exc).__name__}: {exc}")
        return []


def _identity(owner_id: str, message_id: int, generation: str | None) -> dict:
    if generation is None:
        return {"_id": int(message_id), "active": True}
    return {
        "_id": owner_id,
        "message_id": int(message_id),
        "generation": generation,
        "active": True,
    }


async def get(
    mongo, owner_id: str, message_id: int, generation: str | None
) -> tuple[bool, dict | None]:
    """Return ``(read_succeeded, exact active row)`` before an edit.

    ``generation=None`` is bounded compatibility for the numeric message-keyed
    rows written by 7ca8a33. Their original 72-hour maximum still applies.
    """
    if mongo is None:
        return False, None
    query = _identity(owner_id, message_id, generation)
    query["refresh_until"] = {"$gt": datetime.now(timezone.utc)}
    try:
        return True, await _coll(mongo).find_one(query)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session read failed for {owner_id}/{message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False, None


async def update_navigation(
    mongo,
    *,
    owner_id: str,
    message_id: int,
    generation: str,
    view: str,
    page: int,
    kind: str,
    trigger: str,
    checked_at: datetime | None = None,
) -> bool:
    """Save navigation, and advance freshness only after an actual load.

    A snapshot-only tab or page change passes no ``checked_at``.  It did not
    check Clash, so it must not change the displayed freshness or postpone the
    next automatic refresh.
    """
    observed = datetime.now(timezone.utc)
    checked = _utc(checked_at) if checked_at is not None else None
    fields = {
        "view": view,
        "page": int(page),
        "kind": kind,
        "last_trigger": trigger,
        "updated_at": observed.timestamp(),
    }
    if checked is not None:
        fields |= {
            "last_checked_at": checked,
            "next_refresh_at": checked + timedelta(
                seconds=REFRESH_INTERVAL_SECONDS
            ),
        }
    try:
        result = await _coll(mongo).update_one(
            {
                "_id": owner_id,
                "message_id": int(message_id),
                "generation": generation,
                "active": True,
                "refresh_until": {"$gt": observed},
            },
            {"$set": fields, "$inc": {"interactions": 1}},
        )
        return int(getattr(result, "matched_count", 0) or 0) == 1
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-sessions] navigation update failed for {owner_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def mark_refreshed(mongo, owner_id: str, message_id: int,
                         generation: str | None, *,
                         checked_at: datetime | None = None,
                         kind: str = "dashboard") -> bool:
    """Schedule the next check without extending the panel's lifetime."""
    if mongo is None:
        return False
    checked = _utc(checked_at)
    try:
        result = await _coll(mongo).update_one(
            _identity(owner_id, message_id, generation),
            {"$set": {
                "kind": kind,
                "last_checked_at": checked,
                "next_refresh_at": checked + timedelta(seconds=REFRESH_INTERVAL_SECONDS),
                "updated_at": checked.timestamp(),
                "last_trigger": "automatic",
            }},
        )
        return int(getattr(result, "matched_count", 0) or 0) == 1
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session update failed for {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def postpone(mongo, owner_id: str, message_id: int,
                   generation: str | None, *,
                   observed_at: datetime | None = None,
                   seconds: int = REFRESH_INTERVAL_SECONDS) -> bool:
    """Back off a failed panel without extending its retention."""
    if mongo is None:
        return False
    retry_at = _utc(observed_at) + timedelta(seconds=max(60, int(seconds)))
    try:
        result = await _coll(mongo).update_one(
            _identity(owner_id, message_id, generation),
            {"$set": {"next_refresh_at": retry_at}},
        )
        return int(getattr(result, "matched_count", 0) or 0) == 1
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] could not postpone {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def remove(mongo, owner_id: str, message_id: int,
                 generation: str | None) -> bool:
    """Remove only the generation Discord says is inaccessible."""
    if mongo is None:
        return False
    try:
        query = _identity(owner_id, message_id, generation)
        query.pop("active", None)
        result = await _coll(mongo).delete_one(query)
        return int(getattr(result, "deleted_count", 0) or 0) == 1
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session removal failed for {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def discard(mongo, document_id) -> bool:
    """Delete a malformed due row by its exact primary key."""
    if mongo is None or document_id is None:
        return False
    try:
        result = await _coll(mongo).delete_one({"_id": document_id})
        return int(getattr(result, "deleted_count", 0) or 0) == 1
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] malformed session cleanup failed for "
              f"{document_id!r}: {type(exc).__name__}: {exc}")
        return False


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def new_refresh_until(*, observed_at: datetime | None = None) -> datetime:
    """Exact deadline created only by new /todo and Check now."""
    return _utc(observed_at) + timedelta(seconds=TTL_SECONDS)
