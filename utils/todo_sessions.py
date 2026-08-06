"""Bounded session storage for automatically refreshed DM /todo panels.

The row is written on every successful DM panel registration and interaction.
The background scheduler reads active rows and edits those messages in place.

WHY _id IS THE MESSAGE ID
-------------------------
One panel, one row, upserted. Every panel that visibly promises auto-checks stays
scheduled through its own short deadline. Silently retiring older rows would
leave those messages making a false promise, while overlapping registrations
could retire each other. The bounded TTL prevents long-term accumulation.

TTL
---
`expires_at` is pushed forward on every interaction, so an actively-used panel
stays alive and an abandoned one falls out on its own. Nothing has to clean up
after a restart, and a panel the user scrolled past a week ago is not still
being tracked.

The command supplies a refresh deadline based on the panel's event deadlines,
bounded to 72 hours. A user interaction may reactivate an old panel. Background
refreshes never extend retention by themselves.

EVERYTHING HERE IS NON-FATAL
----------------------------
A Mongo failure must never take the dashboard down. The dashboard remains
manually usable without this collection; only automatic checks depend on it.
Every entry point swallows and logs.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

AUTO_REFRESH_ENABLED = True

TTL_SECONDS = 24 * 60 * 60
MAX_REFRESH_SECONDS = 72 * 60 * 60
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


async def record(
    mongo,
    *,
    user_id: int,
    channel_id: int,
    message_id: int,
    view: str,
    page: int = 0,
    guild_id: int | None = None,
    kind: str = "dashboard",
    trigger: str = "command",
    refresh_until: datetime | None = None,
) -> bool:
    """Upsert one panel's row. Returns True if the write went through.

    `kind` distinguishes a real dashboard from a notice panel ("no linked
    accounts", "couldn't reach the link service"). Both are panels and both are
    recorded, because a refresher may well want to retry a notice - a link
    service that was down at 09:00 is probably up at 09:05 - but that is a
    decision for whoever builds it, and it cannot be made if the rows were
    never distinguished.

    `trigger` is what caused this write: "command" for /todo itself, otherwise
    the action that fired. Useful for seeing which panels are actually used.
    """
    if mongo is None or not message_id:
        return False

    await ensure_indexes(mongo)

    now = time.time()
    now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
    is_dm = guild_id is None
    until = bounded_refresh_until(refresh_until, observed_at=now_dt)
    try:
        await _coll(mongo).update_one(
            {"_id": int(message_id)},
            {
                "$set": {
                    "user_id": int(user_id),
                    "channel_id": int(channel_id),
                    "guild_id": int(guild_id) if guild_id else None,
                    # A DM panel is the one worth auto-refreshing; an in-channel
                    # one is a convenience read someone else may be looking at.
                    "is_dm": is_dm,
                    "active": is_dm,
                    "view": view,
                    "page": int(page),
                    "kind": kind,
                    "last_trigger": trigger,
                    "updated_at": now,
                    "last_checked_at": now_dt,
                    "next_refresh_at": (
                        now_dt + timedelta(seconds=REFRESH_INTERVAL_SECONDS)
                        if is_dm else None
                    ),
                    "refresh_until": until if is_dm else None,
                    # Pushed forward on every interaction: an active panel stays,
                    # an abandoned one ages out without anyone cleaning up.
                    "expires_at": until if is_dm else _expiry(now),
                },
                "$setOnInsert": {"created_at": now},
                "$inc": {"interactions": 1},
            },
            upsert=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-sessions] write failed for message {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False

    # Keep every promised DM panel scheduled until its own short, bounded
    # deadline. Removing an older row here leaves that visible message claiming
    # it will refresh when it no longer can; overlapping registrations could
    # also delete each other. The TTL index limits storage to at most 72 hours.
    return True


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


async def get(mongo, message_id: int) -> dict | None:
    """Read one active session immediately before editing its message."""
    if mongo is None:
        return None
    try:
        return await _coll(mongo).find_one({
            "_id": int(message_id),
            "active": True,
            "refresh_until": {"$gt": datetime.now(timezone.utc)},
        })
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session read failed for {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return None


async def mark_refreshed(mongo, message_id: int, *,
                         checked_at: datetime | None = None,
                         kind: str = "dashboard") -> bool:
    """Schedule the next check without extending the panel's lifetime."""
    if mongo is None:
        return False
    checked = _utc(checked_at)
    try:
        await _coll(mongo).update_one(
            {"_id": int(message_id), "active": True},
            {"$set": {
                "kind": kind,
                "last_checked_at": checked,
                "next_refresh_at": checked + timedelta(seconds=REFRESH_INTERVAL_SECONDS),
                "updated_at": checked.timestamp(),
                "last_trigger": "automatic",
            }},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session update failed for {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def postpone(mongo, message_id: int, *, observed_at: datetime | None = None,
                   seconds: int = REFRESH_INTERVAL_SECONDS) -> bool:
    """Back off a failed panel without extending its retention."""
    if mongo is None:
        return False
    retry_at = _utc(observed_at) + timedelta(seconds=max(60, int(seconds)))
    try:
        await _coll(mongo).update_one(
            {"_id": int(message_id), "active": True},
            {"$set": {"next_refresh_at": retry_at}},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] could not postpone {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


async def remove(mongo, message_id: int) -> bool:
    """Stop tracking a message Discord says no longer exists or is inaccessible."""
    if mongo is None:
        return False
    try:
        await _coll(mongo).delete_one({"_id": int(message_id)})
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-refresh] session removal failed for {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def bounded_refresh_until(requested: datetime | None,
                          *, observed_at: datetime | None = None) -> datetime:
    """Clamp an automatic-refresh window to 24–72 hours from observation."""
    now = _utc(observed_at)
    default = now + timedelta(seconds=TTL_SECONDS)
    maximum = now + timedelta(seconds=MAX_REFRESH_SECONDS)
    if requested is None:
        return default
    return min(max(_utc(requested), default), maximum)


def _expiry(now: float):
    """TTL anchor as a real datetime.

    MONGO TTL INDEXES ONLY UNDERSTAND BSON DATES. A float or an int in this
    field indexes fine, matches queries fine, and is silently never expired -
    the collection grows forever and nothing reports an error. Every other
    timestamp in this document is a float epoch, which is why this one being a
    datetime looks inconsistent; it is not, it is the one field that has to be.
    """
    return datetime.fromtimestamp(now + TTL_SECONDS, tz=timezone.utc)
