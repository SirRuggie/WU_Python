"""Durable, staff-authored applicant flags.

Flags match a ticket when either its Discord ID or any normalized player tag
matches.  Only ``blacklisted`` blocks approval; the other kinds are cautions.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterable
from uuid import uuid4

from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import perms, schema, store
from utils.mongo import MongoClient


FLAG_BLACKLISTED = "blacklisted"
FLAG_DENIED_BEFORE = "denied_before"
FLAG_NOT_LOYAL = "not_loyal"
FLAG_KINDS = frozenset({FLAG_BLACKLISTED, FLAG_DENIED_BEFORE, FLAG_NOT_LOYAL})
IDENTITY_LOCK_LEASE = timedelta(minutes=3)
IDENTITY_LOCK_WAIT_SECONDS = 5.0
IDENTITY_LOCK_POLL_SECONDS = 0.05

_log = logging.getLogger(__name__)


class FlagStoreError(RuntimeError):
    pass


class FlagConflictError(FlagStoreError):
    pass


class IdentityLockBusy(FlagConflictError):
    pass


@dataclasses.dataclass(frozen=True, slots=True)
class FlagMutation:
    outcome: str
    doc: dict | None
    reason: str | None = None

    @property
    def won(self) -> bool:
        return self.outcome == store.WON


def normalize_kind(value: str) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if normalized not in FLAG_KINDS:
        raise ValueError(f"flag kind must be one of {sorted(FLAG_KINDS)}")
    return normalized


def _discord_ids(values: Iterable | int | str | None) -> list[int]:
    if values is None:
        return []
    if isinstance(values, (int, str)):
        values = [values]
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        normalized = schema.snowflake(value, field="discord_id")
        if normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _identity_query(discord_ids: list[int], player_tags: list[str]) -> list[dict]:
    clauses: list[dict] = []
    if discord_ids:
        mixed = [item for value in discord_ids for item in (value, str(value))]
        clauses.extend([
            {"discord_ids": {"$in": mixed}},
            {"discordIds": {"$in": mixed}},
        ])
    if player_tags:
        clauses.extend([
            {"player_tags": {"$in": player_tags}},
            {"playerTags": {"$in": player_tags}},
        ])
    return clauses


def _identity_lock_ids(
    discord_ids: Iterable | int | str | None,
    player_tags: Iterable[str] | str,
) -> list[str]:
    keys = [f"discord:{value}" for value in _discord_ids(discord_ids)]
    keys.extend(f"tag:{value}" for value in schema.player_tags(player_tags))
    return [f"ticket_identity_lock:{key}" for key in sorted(set(keys))]


async def _acquire_identity_lock(
    mongo: MongoClient,
    *,
    lock_id: str,
    owner: str,
) -> None:
    collection = mongo.ticket_flags
    now = datetime.now(timezone.utc)
    try:
        await collection.insert_one({
            "_id": lock_id,
            "kind": "identity_lock",
            "active": False,
            "created_at": now,
        })
    except DuplicateKeyError:
        pass

    deadline = time.monotonic() + IDENTITY_LOCK_WAIT_SECONDS
    while True:
        now = datetime.now(timezone.utc)
        current = await collection.find_one({"_id": lock_id}) or {}
        current_owner = str(current.get("lease_owner") or "")
        lease_until = current.get("lease_until")
        normalized_lease = (
            schema.normalize_datetime(lease_until, field="identity_lock.lease_until")
            if isinstance(lease_until, datetime)
            else None
        )
        available = (
            not current_owner
            or normalized_lease is None
            or normalized_lease <= now
        )
        if available:
            claim: dict = {"_id": lock_id}
            claim["lease_owner"] = (
                current.get("lease_owner")
                if "lease_owner" in current
                else {"$exists": False}
            )
            claim["lease_until"] = (
                lease_until if "lease_until" in current else {"$exists": False}
            )
            acquired = await collection.find_one_and_update(
                claim,
                {"$set": {
                    "lease_owner": owner,
                    "lease_until": now + IDENTITY_LOCK_LEASE,
                    "acquired_at": now,
                }},
                return_document=ReturnDocument.AFTER,
            )
            if acquired is not None:
                return
        if time.monotonic() >= deadline:
            raise IdentityLockBusy("applicant identity is being updated; try again")
        await asyncio.sleep(IDENTITY_LOCK_POLL_SECONDS)


@asynccontextmanager
async def identity_guard(
    mongo: MongoClient,
    *,
    discord_ids: Iterable | int | str | None = None,
    player_tags: Iterable[str] | str = (),
):
    """Serialize flag creation and approval for every matching identity."""

    lock_ids = _identity_lock_ids(discord_ids, player_tags)
    if not lock_ids:
        raise ValueError("at least one Discord ID or player tag is required")
    owner = uuid4().hex
    acquired: list[str] = []
    try:
        for lock_id in lock_ids:
            await _acquire_identity_lock(mongo, lock_id=lock_id, owner=owner)
            acquired.append(lock_id)
        yield
    finally:
        released_at = datetime.now(timezone.utc)
        for lock_id in reversed(acquired):
            try:
                await mongo.ticket_flags.update_one(
                    {"_id": lock_id, "lease_owner": owner},
                    {
                        "$unset": {"lease_owner": "", "lease_until": ""},
                        "$set": {"released_at": released_at},
                    },
                )
            except Exception:
                _log.exception("could not release applicant identity lock %s", lock_id)


async def ensure_indexes(mongo: MongoClient) -> list[str]:
    collection = mongo.ticket_flags
    specs = [
        await collection.create_index(
            [("kind", 1), ("active", 1), ("checked_at", -1)],
            name="flag_kind_active_checked",
        ),
        await collection.create_index(
            [("kind", 1), ("discord_ids", 1)],
            unique=True,
            partialFilterExpression={
                "active": True, "discord_ids.0": {"$exists": True}
            },
            name="active_flag_discord_unique",
        ),
        await collection.create_index(
            [("kind", 1), ("player_tags", 1)],
            unique=True,
            partialFilterExpression={
                "active": True, "player_tags.0": {"$exists": True}
            },
            name="active_flag_player_tag_unique",
        ),
    ]
    return [str(name) for name in specs]


async def list_for_identity(
    mongo: MongoClient,
    *,
    discord_ids: Iterable | int | str | None = None,
    player_tags: Iterable[str] | str = (),
    active_only: bool = True,
) -> list[dict]:
    ids = _discord_ids(discord_ids)
    tags = schema.player_tags(player_tags)
    clauses = _identity_query(ids, tags)
    if not clauses:
        return []
    filt: dict = {"$or": clauses}
    if active_only:
        filt["active"] = True
    cursor = mongo.ticket_flags.find(filt)
    return await cursor.sort([("checked_at", -1), ("_id", 1)]).to_list(length=None)


async def active_blacklist(
    mongo: MongoClient,
    *,
    user_id=None,
    player_tags: Iterable[str] | str = (),
) -> dict | None:
    ids = _discord_ids(user_id)
    tags = schema.player_tags(player_tags)
    clauses = _identity_query(ids, tags)
    if not clauses:
        return None
    return await mongo.ticket_flags.find_one({
        "kind": FLAG_BLACKLISTED,
        "active": True,
        "$or": clauses,
    })


async def count_active(mongo: MongoClient) -> dict[str, int]:
    """Return all chart flag kinds, including zero-count kinds."""
    cursor = await mongo.ticket_flags.aggregate([
        {"$match": {"active": True, "kind": {"$in": sorted(FLAG_KINDS)}}},
        {"$group": {"_id": "$kind", "count": {"$sum": 1}}},
    ])
    rows = await cursor.to_list(length=None)
    result = {kind: 0 for kind in sorted(FLAG_KINDS)}
    for row in rows:
        if row.get("_id") in result:
            result[row["_id"]] = int(row.get("count") or 0)
    return result


async def _set_flag_unlocked(
    mongo: MongoClient,
    *,
    kind: str,
    discord_ids: Iterable | int | str | None = None,
    player_tags: Iterable[str] | str = (),
    source: str,
    added_by,
    added_by_name: str,
    reason: str = "",
    checked_at: datetime | None = None,
) -> dict:
    """Create or extend one active flag, retry-safe under unique indexes."""
    flag_kind = normalize_kind(kind)
    ids = _discord_ids(discord_ids)
    tags = schema.player_tags(player_tags)
    if not ids and not tags:
        raise ValueError("at least one Discord ID or player tag is required")
    actor = schema.snowflake(added_by, field="added_by")
    actor_name = str(added_by_name or "").strip() or str(actor)
    source_name = str(source or "").strip()
    if not source_name:
        raise ValueError("flag source is required")
    checked = schema.normalize_datetime(checked_at, field="checked_at")
    now = datetime.now(timezone.utc)
    await ensure_indexes(mongo)

    clauses = _identity_query(ids, tags)
    existing = await mongo.ticket_flags.find({
        "kind": flag_kind,
        "active": True,
        "$or": clauses,
    }).limit(2).to_list(length=2)
    if len(existing) > 1:
        raise FlagConflictError("identities overlap multiple active flag records")
    audit = {
        "event": "flag_set",
        "at": now,
        "actor": actor,
        "actor_name": actor_name,
        "discord_ids": ids,
        "player_tags": tags,
        "source": source_name,
        "reason": str(reason or "").strip(),
    }
    if existing:
        current = existing[0]
        rev = max(0, int(current.get("rev") or 0))
        updated = await mongo.ticket_flags.find_one_and_update(
            {"_id": current["_id"], "active": True, "rev": store._rev_filter(rev)},
            {
                "$addToSet": {
                    "discord_ids": {"$each": ids},
                    "player_tags": {"$each": tags},
                },
                "$set": {
                    "source": source_name,
                    "reason": str(reason or "").strip(),
                    "checked_at": checked,
                    "updated_at": now,
                    "added_by": actor,
                    "added_by_name": actor_name,
                },
                "$inc": {"rev": 1},
                "$push": {"audit": audit},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise FlagConflictError("flag changed while it was being updated")
        return updated

    document = {
        "_id": f"flag_{uuid4().hex}",
        "kind": flag_kind,
        "discord_ids": ids,
        "player_tags": tags,
        "source": source_name,
        "added_by": actor,
        "added_by_name": actor_name,
        "checked_at": checked,
        "reason": str(reason or "").strip(),
        "active": True,
        "created_at": now,
        "updated_at": now,
        "rev": 0,
        "audit": [audit],
    }
    try:
        await mongo.ticket_flags.insert_one(document)
    except DuplicateKeyError:
        # Another worker created the same identity after our lookup. Merge into
        # that record through one bounded retry instead of creating a duplicate.
        raced = await mongo.ticket_flags.find({
            "kind": flag_kind, "active": True, "$or": clauses,
        }).limit(2).to_list(length=2)
        if len(raced) != 1:
            raise FlagConflictError("concurrent flag creation could not be reconciled")
        current = raced[0]
        rev = max(0, int(current.get("rev") or 0))
        updated = await mongo.ticket_flags.find_one_and_update(
            {"_id": current["_id"], "active": True, "rev": store._rev_filter(rev)},
            {
                "$addToSet": {
                    "discord_ids": {"$each": ids},
                    "player_tags": {"$each": tags},
                },
                "$set": {"updated_at": now},
                "$inc": {"rev": 1},
                "$push": {"audit": audit},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            raise FlagConflictError("concurrent flag creation changed twice")
        return updated
    return document


async def set_flag(
    mongo: MongoClient,
    *,
    kind: str,
    discord_ids: Iterable | int | str | None = None,
    player_tags: Iterable[str] | str = (),
    source: str,
    added_by,
    added_by_name: str,
    reason: str = "",
    checked_at: datetime | None = None,
) -> dict:
    """Create or extend one flag while excluding a concurrent approval."""

    ids = _discord_ids(discord_ids)
    tags = schema.player_tags(player_tags)
    async with identity_guard(mongo, discord_ids=ids, player_tags=tags):
        return await _set_flag_unlocked(
            mongo,
            kind=kind,
            discord_ids=ids,
            player_tags=tags,
            source=source,
            added_by=added_by,
            added_by_name=added_by_name,
            reason=reason,
            checked_at=checked_at,
        )


async def set_flag_authorized(
    mongo: MongoClient,
    *,
    member,
    actor_name: str,
    kind: str,
    discord_ids: Iterable | int | str | None = None,
    player_tags: Iterable[str] | str = (),
    source: str,
    reason: str = "",
    checked_at: datetime | None = None,
) -> FlagMutation:
    if not await perms.is_recruiter(member, mongo):
        return FlagMutation(store.UNAUTHORIZED, None, "recruiter permission required")
    document = await set_flag(
        mongo,
        kind=kind,
        discord_ids=discord_ids,
        player_tags=player_tags,
        source=source,
        added_by=member.id,
        added_by_name=actor_name,
        reason=reason,
        checked_at=checked_at,
    )
    return FlagMutation(store.WON, document)


async def deactivate_flag(
    mongo: MongoClient,
    flag_id,
    *,
    removed_by,
    removed_by_name: str,
    reason: str = "",
    expected_rev: int | None = None,
) -> FlagMutation:
    initial = await mongo.ticket_flags.find_one({"_id": flag_id})
    if initial is None:
        return FlagMutation(store.MISSING, None)
    ids = [
        *_discord_ids(initial.get("discord_ids")),
        *_discord_ids(initial.get("discordIds")),
    ]
    tags = [
        *schema.player_tags(initial.get("player_tags")),
        *schema.player_tags(initial.get("playerTags")),
    ]
    if not ids and not tags:
        return FlagMutation(store.LOST, initial, "flag has no applicant identity")
    guarded_lock_ids = set(_identity_lock_ids(ids, tags))

    async with identity_guard(mongo, discord_ids=ids, player_tags=tags):
        current = await mongo.ticket_flags.find_one({"_id": flag_id})
        if current is None:
            return FlagMutation(store.MISSING, None)
        current_ids = [
            *_discord_ids(current.get("discord_ids")),
            *_discord_ids(current.get("discordIds")),
        ]
        current_tags = [
            *schema.player_tags(current.get("player_tags")),
            *schema.player_tags(current.get("playerTags")),
        ]
        if set(_identity_lock_ids(current_ids, current_tags)) != guarded_lock_ids:
            return FlagMutation(store.LOST, current, "flag changed")
        if not current.get("active"):
            return FlagMutation(store.LOST, current, "flag is already inactive")
        rev = max(0, int(current.get("rev") or 0))
        if expected_rev is not None and rev != int(expected_rev):
            return FlagMutation(store.LOST, current, "flag changed")
        actor = schema.snowflake(removed_by, field="removed_by")
        actor_name = str(removed_by_name or "").strip() or str(actor)
        now = datetime.now(timezone.utc)
        updated = await mongo.ticket_flags.find_one_and_update(
            {"_id": flag_id, "active": True, "rev": store._rev_filter(rev)},
            {
                "$set": {
                    "active": False,
                    "removed_at": now,
                    "removed_by": actor,
                    "removed_by_name": actor_name,
                    "removal_reason": str(reason or "").strip(),
                    "updated_at": now,
                },
                "$inc": {"rev": 1},
                "$push": {"audit": {
                    "event": "flag_deactivated",
                    "at": now,
                    "actor": actor,
                    "actor_name": actor_name,
                    "reason": str(reason or "").strip(),
                    "rev_before": rev,
                    "rev_after": rev + 1,
                }},
            },
            return_document=ReturnDocument.AFTER,
        )
        if updated is None:
            latest = await mongo.ticket_flags.find_one({"_id": flag_id})
            return FlagMutation(store.LOST, latest, "flag changed")
        return FlagMutation(store.WON, updated)


async def deactivate_flag_authorized(
    mongo: MongoClient,
    flag_id,
    *,
    member,
    actor_name: str,
    reason: str = "",
    expected_rev: int | None = None,
) -> FlagMutation:
    if not await perms.is_recruiter(member, mongo):
        return FlagMutation(store.UNAUTHORIZED, None, "recruiter permission required")
    return await deactivate_flag(
        mongo,
        flag_id,
        removed_by=member.id,
        removed_by_name=actor_name,
        reason=reason,
        expected_rev=expected_rev,
    )
