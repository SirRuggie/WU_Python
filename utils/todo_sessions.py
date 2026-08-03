"""Auto-refresh phase 1: remember which /todo panels exist.

PHASE 1 WRITES ROWS AND NOTHING ELSE. No poller, no scheduler, no message
edits. The point is to get real documents into Mongo and look at them before
anything is built on top of their shape - a poller written against a guessed
schema is a poller that has to be rewritten.

The row is written on every panel send and every interaction, so a document
here means "this message existed and was a /todo panel at this time". What a
later phase does with that is a later phase's problem.

WHY _id IS THE MESSAGE ID
-------------------------
One panel, one row, upserted. A user who opens /todo four times has four
panels and four rows; a user who clicks Refresh forty times on one panel has
one row with interactions=40. That is the shape a refresher wants: it iterates
messages, not events. It also means dedupe rides on the primary key, so no
unique index is needed and a double-write cannot produce two rows.

TTL
---
`expires_at` is pushed forward on every interaction, so an actively-used panel
stays alive and an abandoned one falls out on its own. Nothing has to clean up
after a restart, and a panel the user scrolled past a week ago is not still
being tracked.

24 hours is a starting value, not a considered one - it is roughly "still on
screen tomorrow morning". If phase 2 builds a refresher, the right anchor is
probably the soonest deadline in the panel's data rather than a flat window,
since a panel whose war ended has nothing left to refresh.

EVERYTHING HERE IS NON-FATAL
----------------------------
A Mongo failure must never take the dashboard down. The dashboard works
perfectly without this collection; it is bookkeeping for a feature that does
not exist yet. Every entry point swallows and logs.
"""

from __future__ import annotations

import time

# Rows are written unconditionally - collecting them IS phase 1, so a flag that
# switched the writes off would defeat the exercise.
#
# This flag governs the POLLER, which does not exist. It lives here so phase 2
# has an obvious place to gate itself, and so nobody reads the presence of rows
# as evidence that auto-refresh is switched on. It is not.
AUTO_REFRESH_ENABLED = False

TTL_SECONDS = 24 * 60 * 60

# One log line per process, not one per failure. A remote Mongo that is down is
# down for every interaction, and the dashboard is already usable without this.
_index_ready = False
_index_failed = False


def _coll(mongo):
    return mongo.todo_sessions


async def ensure_indexes(mongo) -> None:
    """Create the TTL index. Once per process, never fatal.

    Lazy rather than called from main.py's startup: this module is only reached
    by /todo, so the index is only needed when /todo is first used, and keeping
    it self-contained means the feature can be removed by deleting two files.

    Without the index nothing breaks - rows are still written and read
    correctly, they just never self-prune.
    """
    global _index_ready, _index_failed
    if _index_ready or _index_failed:
        return
    try:
        await _coll(mongo).create_index(
            "expires_at", expireAfterSeconds=0, name="ttl_expires_at"
        )
        _index_ready = True
        print("[todo-sessions] TTL index ready on todo_sessions.expires_at")
    except Exception as exc:  # noqa: BLE001
        _index_failed = True
        print(
            f"[todo-sessions] WARNING: could not create TTL index "
            f"({type(exc).__name__}: {exc}). Rows are still written; "
            f"todo_sessions will NOT self-prune."
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
                    "is_dm": guild_id is None,
                    "view": view,
                    "page": int(page),
                    "kind": kind,
                    "last_trigger": trigger,
                    "updated_at": now,
                    # Pushed forward on every interaction: an active panel stays,
                    # an abandoned one ages out without anyone cleaning up.
                    "expires_at": _expiry(now),
                },
                "$setOnInsert": {"created_at": now},
                "$inc": {"interactions": 1},
            },
            upsert=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[todo-sessions] write failed for message {message_id}: "
              f"{type(exc).__name__}: {exc}")
        return False


def _expiry(now: float):
    """TTL anchor as a real datetime.

    MONGO TTL INDEXES ONLY UNDERSTAND BSON DATES. A float or an int in this
    field indexes fine, matches queries fine, and is silently never expired -
    the collection grows forever and nothing reports an error. Every other
    timestamp in this document is a float epoch, which is why this one being a
    datetime looks inconsistent; it is not, it is the one field that has to be.
    """
    from datetime import datetime, timezone
    return datetime.fromtimestamp(now + TTL_SECONDS, tz=timezone.utc)
