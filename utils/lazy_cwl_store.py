"""Durable storage operations for LazyCWL saved player lists.

One active list per clan is enforced by a partial unique index on
``clan_tag``. Mongo's TTL index deletes rows itself once ``purge_at``
passes (90 days after ``expires_at``); the daily expiry job only flips
``status`` to ``"expired"`` and removes the scheduler job, it never
deletes. This is the only module allowed to touch the
``lazy_cwl_lists`` collection; see reports/design-01-main.md section 9.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from utils.mongo import MongoClient
from utils.lazy_cwl_schema import SCHEMA_VERSION

_log = logging.getLogger(__name__)


PURGE_RETENTION = timedelta(days=90)

ONE_ACTIVE_PER_CLAN_INDEX = "lazycwl_one_active_per_clan"
TTL_PURGE_INDEX = "lazycwl_ttl_purge_at"
STATUS_EXPIRES_INDEX = "lazycwl_status_expires"
LEGACY_SNAPSHOT_INDEX = "lazycwl_legacy_snapshot"


class AlreadySavedError(Exception):
    """Raised by save_list when the clan already has an active list.

    existing_doc may be None: the DuplicateKeyError race can be raised
    without a usable re-read if the conflicting list finishes between the
    insert attempt and the recovery lookup.
    """

    def __init__(self, existing_doc: dict | None = None):
        self.existing_doc = existing_doc
        clan_tag = existing_doc.get("clan_tag") if existing_doc else None
        super().__init__(f"clan {clan_tag} already has an active list")


class PlayerAlreadyListedError(Exception):
    """Raised by add_player when the tag is already on the active list."""


class NoActiveListError(Exception):
    """Raised by add_player when the clan has no active list."""


class StaleListError(Exception):
    """Raised when a component refers to a list which is no longer active.

    Dashboard confirmations carry the list id that was displayed to the
    administrator.  Matching it in the write query prevents a delayed click
    from changing a newly-created list for the same clan.
    """


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _coll(mongo: MongoClient):
    return mongo.lazy_cwl_lists


def _normalize_tag(tag: str) -> str:
    """Strip, upper-case, and prepend '#' if the caller omitted it, so
    "P1" and "#P1" are always the same stored/looked-up tag."""
    tag = str(tag).strip().upper()
    if not tag.startswith("#"):
        tag = "#" + tag
    return tag


def _normalize_player(player: dict, *, now: datetime, added_manually_default: bool) -> dict:
    """Shape one player entry the way it is stored: tag '#'-prefixed and
    upper, name and town_hall as given, discord_id defaulted,
    added_manually and added_at defaulted when the caller did not supply
    them (a caller-supplied added_at is still routed through _utc)."""
    return {
        "tag": _normalize_tag(player["tag"]),
        "name": player["name"],
        "town_hall": int(player["town_hall"]),
        "discord_id": player.get("discord_id"),
        "added_manually": bool(player.get("added_manually", added_manually_default)),
        "added_at": _utc(player["added_at"]) if player.get("added_at") else now,
    }


def expires_at_for(saved_at: datetime) -> datetime:
    """00:00 UTC on the 16th of saved_at's month, or the next month's 16th
    if saved_at falls on or after the 16th."""
    saved_at = _utc(saved_at)
    year = saved_at.year
    month = saved_at.month
    if saved_at.day >= 16:
        month += 1
        if month > 12:
            month = 1
            year += 1
    return datetime(year, month, 16, tzinfo=timezone.utc)


async def ensure_indexes(mongo: MongoClient) -> None:
    """Install indexes for the one-active-list guard, TTL purge, and the
    expiry job's scan."""
    collection = _coll(mongo)
    await collection.create_index(
        "clan_tag",
        unique=True,
        partialFilterExpression={"status": "active"},
        name=ONE_ACTIVE_PER_CLAN_INDEX,
    )
    await collection.create_index(
        "purge_at",
        expireAfterSeconds=0,
        name=TTL_PURGE_INDEX,
    )
    await collection.create_index(
        [("status", 1), ("expires_at", 1)],
        name=STATUS_EXPIRES_INDEX,
    )
    await collection.create_index(
        "legacy_snapshot_id",
        unique=True,
        sparse=True,
        name=LEGACY_SNAPSHOT_INDEX,
    )


def _active_query(clan_tag: str, expected_list_id=None) -> dict:
    query = {"clan_tag": _normalize_tag(clan_tag), "status": "active"}
    if expected_list_id is not None:
        query["_id"] = expected_list_id
    return query


async def save_list(
    mongo: MongoClient,
    *,
    clan_tag: str,
    clan_name: str,
    players: list[dict],
    saved_by: int,
    now: datetime | None = None,
) -> dict:
    """Insert a new active saved list for a clan.

    Raises AlreadySavedError if the clan already has an active list,
    either because get_active finds one first or the unique index
    rejects the insert.
    """
    now = _utc(now)
    clan_tag = _normalize_tag(clan_tag)

    existing = await get_active(mongo, clan_tag)
    if existing is not None:
        raise AlreadySavedError(existing)

    expires_at = expires_at_for(now)
    document = {
        "schema_version": SCHEMA_VERSION,
        "clan_tag": clan_tag,
        "clan_name": clan_name,
        "status": "active",
        "saved_at": now,
        "saved_by": int(saved_by),
        "expires_at": expires_at,
        "purge_at": expires_at + PURGE_RETENTION,
        "players": [
            _normalize_player(player, now=now, added_manually_default=False)
            for player in players
        ],
        "reminders": {
            "enabled": False,
            "every_minutes": None,
            "started_at": None,
            "last_sent_at": None,
            "sent_count": 0,
        },
    }

    try:
        result = await _coll(mongo).insert_one(document)
    except DuplicateKeyError:
        existing = await get_active(mongo, clan_tag)
        raise AlreadySavedError(existing) from None

    document["_id"] = result.inserted_id
    return document


async def get_active(mongo: MongoClient, clan_tag: str) -> dict | None:
    """Return the active list for one clan, if any."""
    clan_tag = _normalize_tag(clan_tag)
    return await _coll(mongo).find_one({"clan_tag": clan_tag, "status": "active"})


async def list_active(mongo: MongoClient) -> list[dict]:
    """Return every active list, sorted by clan name."""
    cursor = _coll(mongo).find({"status": "active"}).sort("clan_name", 1)
    return await cursor.to_list(length=None)


async def get_by_id(mongo: MongoClient, list_id) -> dict | None:
    """Return one saved list by _id, regardless of status. Used by the
    reminder job to re-read current state on every scheduled run."""
    return await _coll(mongo).find_one({"_id": list_id})


async def add_player(
    mongo: MongoClient,
    clan_tag: str,
    player: dict,
    *,
    added_manually: bool = True,
    expected_list_id=None,
    now: datetime | None = None,
) -> dict:
    """Append one player to a clan's active list.

    added_manually is the default recorded on the entry when player does
    not already carry its own "added_manually" value.

    Raises NoActiveListError if the clan has no active list, or
    PlayerAlreadyListedError if the tag is already present.
    """
    now = _utc(now)
    clan_tag = _normalize_tag(clan_tag)
    tag = _normalize_tag(player["tag"])

    active = await _coll(mongo).find_one(_active_query(clan_tag, expected_list_id))
    if active is None:
        if expected_list_id is not None:
            raise StaleListError()
        raise NoActiveListError(clan_tag)
    if any(_normalize_tag(existing.get("tag", "")) == tag for existing in active.get("players", [])):
        raise PlayerAlreadyListedError(tag)

    entry = _normalize_player(player, now=now, added_manually_default=added_manually)
    query = _active_query(clan_tag, expected_list_id)
    # The read above gives a useful error in the normal case, but it cannot
    # make the check atomic. Keep the tag absence in the write filter so two
    # simultaneous modal submissions cannot append the same player twice.
    query["players.tag"] = {"$ne": tag}

    updated = await _coll(mongo).find_one_and_update(
        query,
        {"$push": {"players": entry}},
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        current = await _coll(mongo).find_one(_active_query(clan_tag, expected_list_id))
        if current is not None and any(
            _normalize_tag(existing.get("tag", "")) == tag
            for existing in current.get("players", [])
        ):
            raise PlayerAlreadyListedError(tag)
        if expected_list_id is not None:
            raise StaleListError()
        raise NoActiveListError(clan_tag)
    return updated


async def remove_players(mongo: MongoClient, clan_tag: str, tags: list[str], *, expected_list_id=None) -> int:
    """Remove players by tag from a clan's active list. Returns the number
    of tags that were present and removed, derived from the single
    find_one_and_update's BEFORE image (no second read, so nothing else can
    land between two reads and make the count stale). Stored tags are
    always '#'-prefixed and upper (see _normalize_tag), so the input tags
    are normalized here the same way for a case- and prefix-insensitive
    match, and the count tests membership against that same `wanted` set
    the $pull used instead of re-deriving its own predicate."""
    clan_tag = _normalize_tag(clan_tag)
    wanted = {_normalize_tag(tag) for tag in tags}
    if not wanted:
        return 0

    before = await _coll(mongo).find_one_and_update(
        _active_query(clan_tag, expected_list_id),
        {"$pull": {"players": {"tag": {"$in": list(wanted)}}}},
        return_document=ReturnDocument.BEFORE,
    )
    if before is None:
        if expected_list_id is not None:
            raise StaleListError()
        return 0

    return sum(1 for player in before.get("players", []) if player.get("tag") in wanted)


async def set_reminders(
    mongo: MongoClient,
    clan_tag: str,
    *,
    enabled: bool,
    every_minutes: int | None,
    expected_list_id=None,
    now: datetime | None = None,
) -> dict | None:
    """Turn a clan's reminders on or off. Enabling resets started_at,
    last_sent_at, and sent_count; disabling keeps sent_count for history.
    Returns None if the clan has no active list."""
    now = _utc(now)
    clan_tag = _normalize_tag(clan_tag)

    update: dict[str, Any] = {
        "reminders.enabled": enabled,
        "reminders.every_minutes": every_minutes,
    }
    if enabled:
        update["reminders.started_at"] = now
        update["reminders.last_sent_at"] = None
        update["reminders.sent_count"] = 0

    return await _coll(mongo).find_one_and_update(
        _active_query(clan_tag, expected_list_id),
        {"$set": update},
        return_document=ReturnDocument.AFTER,
    )


async def record_reminder_sent(mongo: MongoClient, list_id, now: datetime | None = None) -> None:
    """Record that a reminder was just sent for one saved list."""
    now = _utc(now)
    await _coll(mongo).find_one_and_update(
        {"_id": list_id},
        {
            "$set": {"reminders.last_sent_at": now},
            "$inc": {"reminders.sent_count": 1},
        },
        return_document=ReturnDocument.AFTER,
    )


async def finish(mongo: MongoClient, clan_tag: str, now: datetime | None = None, *, expected_list_id=None) -> dict | None:
    """Mark a clan's active list finished and turn off its reminders."""
    now = _utc(now)
    clan_tag = _normalize_tag(clan_tag)
    return await _coll(mongo).find_one_and_update(
        _active_query(clan_tag, expected_list_id),
        {"$set": {
            "status": "finished",
            "finished_at": now,
            "reminders.enabled": False,
        }},
        return_document=ReturnDocument.AFTER,
    )


async def expire_due(mongo: MongoClient, now: datetime | None = None) -> list[dict]:
    """Flip every active list past its expires_at to "expired" and turn off
    its reminders. Returns the flipped docs so the caller can remove their
    scheduler jobs."""
    now = _utc(now)
    cursor = _coll(mongo).find({"status": "active", "expires_at": {"$lte": now}})
    due = await cursor.to_list(length=None)

    flipped = []
    for document in due:
        updated = await _coll(mongo).find_one_and_update(
            {"_id": document["_id"], "status": "active"},
            {"$set": {"status": "expired", "reminders.enabled": False}},
            return_document=ReturnDocument.AFTER,
        )
        if updated is not None:
            flipped.append(updated)
    return flipped


async def list_reminder_enabled(mongo: MongoClient) -> list[dict]:
    """Return every active list with reminders currently enabled, for
    restoring scheduler jobs at startup."""
    cursor = _coll(mongo).find({"status": "active", "reminders.enabled": True})
    return await cursor.to_list(length=None)


async def repair_imported_expiry(mongo: MongoClient, now: datetime | None = None) -> int:
    """Correct the original migration's renewed expiry using capture time.

    Only imported rows with an incorrect expiry are changed. Conditional
    updates protect a concurrent close/edit, and repeated startup is a no-op.
    Past-due imports become inactive in the same write as the date correction.
    """
    now = _utc(now)
    repaired = 0
    documents = await _coll(mongo).find({"legacy_snapshot_id": {"$exists": True}}).to_list(length=None)
    for document in documents:
        if not document.get("legacy_snapshot_id") or not isinstance(document.get("saved_at"), datetime):
            continue
        expiry = expires_at_for(_utc(document["saved_at"]))
        if document.get("expires_at") and _utc(document["expires_at"]) == expiry:
            continue
        changes = {"expires_at": expiry, "purge_at": expiry + PURGE_RETENTION}
        if document.get("status") == "active" and expiry <= now:
            changes.update({"status": "expired", "reminders.enabled": False})
        result = await _coll(mongo).update_one(
            {"_id": document["_id"], "saved_at": document["saved_at"],
             "expires_at": document.get("expires_at"), "status": document["status"]},
            {"$set": changes},
        )
        repaired += result.modified_count
    return repaired


async def migrate_legacy_active_snapshots(mongo: MongoClient, now: datetime | None = None) -> int:
    """Move active rows from the retired ``lazy_cwl_snapshots`` collection.

    The migration is deliberately additive and idempotent.  A destination
    remembers its source id, so a later startup never recreates a finished
    list.  Only after a destination exists do we retire the legacy row, which
    keeps its auto-ping schedule alive if an insert temporarily fails.

    Expiry is calculated from the original capture time. Importing an old
    snapshot must never renew its lifetime or restart its reminders.
    """
    now = _utc(now)
    await repair_imported_expiry(mongo, now)
    legacy = getattr(mongo, "lazy_cwl_snapshots", None)
    if legacy is None:
        return 0

    snapshots = await legacy.find({"active": True}).to_list(length=None)
    # The retired implementation repaired duplicate active snapshots by
    # retaining the newest one.  Do the same before importing: otherwise the
    # partial unique destination index makes the winner depend on cursor
    # order.  The older rows are explicitly retired rather than discarded.
    by_clan: dict[str, list[dict]] = {}
    for snapshot in snapshots:
        clan_tag = snapshot.get("clan_tag")
        if isinstance(clan_tag, str) and clan_tag.strip():
            by_clan.setdefault(_normalize_tag(clan_tag), []).append(snapshot)

    winners = []
    for clan_snapshots in by_clan.values():
        clan_snapshots.sort(
            key=lambda item: (
                _utc(item["snapshot_date"]) if item.get("snapshot_date") else datetime.min.replace(tzinfo=timezone.utc),
                str(item.get("_id", "")),
            ),
            reverse=True,
        )
        winners.append(clan_snapshots[0])
        for duplicate in clan_snapshots[1:]:
            await legacy.update_one(
                {"_id": duplicate["_id"], "active": True},
                {"$set": {"active": False, "auto_ping_enabled": False, "lazycwl_migration_note": "superseded"}},
            )

    migrated = 0
    for snapshot in winners:
        legacy_id = snapshot.get("_id")
        clan_tag = snapshot.get("clan_tag")
        if legacy_id is None or not isinstance(clan_tag, str) or not clan_tag.strip():
            continue

        existing = await _coll(mongo).find_one({"legacy_snapshot_id": legacy_id})
        if existing is None:
            saved_at = _utc(snapshot.get("snapshot_date") or now)
            expiry = expires_at_for(saved_at)
            players = []
            for player in snapshot.get("players", []):
                tag = player.get("tag")
                if not tag:
                    continue
                raw_discord_id = player.get("discord_id")
                try:
                    discord_id = int(raw_discord_id) if raw_discord_id else None
                except (TypeError, ValueError):
                    discord_id = None
                players.append(_normalize_player({
                    "tag": tag,
                    "name": player.get("name") or "Unknown",
                    "town_hall": player.get("town_hall", player.get("th_level", 0)),
                    "discord_id": discord_id,
                    "added_manually": False,
                    "added_at": saved_at,
                }, now=saved_at, added_manually_default=False))

            enabled = bool(snapshot.get("auto_ping_enabled")) and expiry > now
            started_at = _utc(snapshot.get("auto_ping_started_at") or saved_at) if enabled else None
            document = {
                "schema_version": SCHEMA_VERSION,
                "clan_tag": _normalize_tag(clan_tag),
                "clan_name": snapshot.get("clan_name") or _normalize_tag(clan_tag),
                "status": "active" if expiry > now else "expired",
                "saved_at": saved_at,
                "saved_by": int(snapshot.get("saved_by", snapshot.get("created_by", 0)) or 0),
                "expires_at": expiry,
                "purge_at": expiry + PURGE_RETENTION,
                "players": players,
                "legacy_snapshot_id": legacy_id,
                "reminders": {
                    "enabled": enabled,
                    "every_minutes": max(1, int(snapshot.get("auto_ping_interval_minutes") or 60)) if enabled else None,
                    "started_at": started_at,
                    "last_sent_at": _utc(snapshot.get("last_auto_ping_at")) if snapshot.get("last_auto_ping_at") else None,
                    "sent_count": int(snapshot.get("auto_ping_count") or 0),
                },
            }
            try:
                result = await _coll(mongo).insert_one(document)
                document["_id"] = result.inserted_id
                existing = document
                migrated += 1
            except DuplicateKeyError:
                # A concurrent migration may already have inserted this
                # source. In that case it is safe to retire the legacy row.
                existing = await _coll(mongo).find_one({"legacy_snapshot_id": legacy_id})
                if existing is None:
                    # An unrelated dashboard list won the active-list race.
                    # Keep the source untouched: silently retiring it would
                    # lose the old roster. An operator can reconcile the two.
                    _log.warning("lazycwl migration skipped legacy snapshot %s: active destination exists for %s", legacy_id, clan_tag)
                    continue

        if existing is not None:
            await legacy.update_one(
                {"_id": legacy_id, "active": True},
                {"$set": {"active": False, "auto_ping_enabled": False, "lazycwl_migrated_to": existing.get("_id")}},
            )
    return migrated
