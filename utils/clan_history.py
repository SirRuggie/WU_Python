"""Bounded player-to-clan discovery data for /todo.

The official Clash API exposes only a player's current clan.  This module
builds the missing recent-clan lookup from observations made by the bot and
from active war rosters.  Every document has a BSON-date TTL anchor so the
collections cannot grow without bound.

Mongo failures are deliberately non-fatal.  Current-clan /todo behavior still
works without this data; only cross-clan discovery degrades.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

from pymongo import UpdateOne


HISTORY_WINDOW = timedelta(hours=48)
RETENTION = timedelta(days=30)
# /todo only needs the preceding 48 hours. Refreshing this on every use keeps
# active users covered without polling every account ever seen for a month.
WATCH_RETENTION = HISTORY_WINDOW

_indexes_ready = False
_indexes_failed = False
_index_retry_at = 0.0


@dataclass(frozen=True, slots=True)
class ClanPresence:
    player_tag: str
    clan_tag: str
    clan_name: str | None = None
    clan_badge: str | None = None


@dataclass(frozen=True, slots=True)
class ClanCandidate:
    clan_tag: str
    clan_name: str | None = None
    clan_badge: str | None = None
    check_war: bool = True
    check_cwl: bool = True


def _now(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _tag(value: str | None) -> str:
    return (value or "").strip().upper()


def _candidate_id(player_tag: str, clan_tag: str) -> str:
    return f"{_tag(player_tag)}:{_tag(clan_tag)}"


def _at_or_after(value, cutoff: datetime) -> bool:
    if not isinstance(value, datetime):
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value >= cutoff


async def ensure_indexes(mongo) -> bool:
    """Create lookup and TTL indexes once per process."""
    global _indexes_ready, _indexes_failed, _index_retry_at
    if _indexes_ready:
        return True
    if mongo is None:
        return False
    if _indexes_failed and time.monotonic() < _index_retry_at:
        return False

    try:
        await mongo.player_clan_candidates.create_index(
            "purge_at", expireAfterSeconds=0, name="ttl_purge_at"
        )
        await mongo.player_clan_candidates.create_index(
            "player_tag", name="player_tag"
        )
        await mongo.player_clan_watches.create_index(
            "expires_at", expireAfterSeconds=0, name="ttl_expires_at"
        )
        _indexes_ready = True
        _indexes_failed = False
        print("[clan-history] indexes ready")
        return True
    except Exception as exc:  # noqa: BLE001 - history must not take /todo down
        _indexes_failed = True
        _index_retry_at = time.monotonic() + 60 * 60
        print(
            "[clan-history] WARNING: index setup failed "
            f"({type(exc).__name__}: {exc}); tracking will continue and index setup will retry"
        )
        return False


async def watch_players(
    mongo,
    player_tags: Iterable[str],
    *,
    observed_at: datetime | None = None,
) -> bool:
    """Keep recently used /todo accounts under lightweight profile polling."""
    if mongo is None:
        return False
    tags = list(dict.fromkeys(_tag(tag) for tag in player_tags if _tag(tag)))
    if not tags:
        return True

    await ensure_indexes(mongo)
    now = _now(observed_at)
    operations = [
        UpdateOne(
            {"_id": tag},
            {
                "$set": {"updated_at": now, "expires_at": now + WATCH_RETENTION},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        for tag in tags
    ]
    try:
        await mongo.player_clan_watches.bulk_write(operations, ordered=False)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clan-history] watch write failed: {type(exc).__name__}: {exc}")
        return False


async def record_presence(
    mongo,
    presences: Iterable[ClanPresence],
    *,
    observed_at: datetime | None = None,
) -> bool:
    """Record actual player-clan observations, coalesced by player and clan."""
    if mongo is None:
        return False
    unique: dict[tuple[str, str], ClanPresence] = {}
    for presence in presences:
        player_tag = _tag(presence.player_tag)
        clan_tag = _tag(presence.clan_tag)
        if player_tag and clan_tag:
            unique[(player_tag, clan_tag)] = presence
    if not unique:
        return True

    await ensure_indexes(mongo)
    now = _now(observed_at)
    operations = []
    for (player_tag, clan_tag), presence in unique.items():
        operations.append(UpdateOne(
            {"_id": _candidate_id(player_tag, clan_tag)},
            {
                "$set": {
                    "player_tag": player_tag,
                    "clan_tag": clan_tag,
                    "clan_name": presence.clan_name,
                    "clan_badge": presence.clan_badge,
                    "last_seen_at": now,
                    "updated_at": now,
                    "purge_at": now + RETENTION,
                },
                "$setOnInsert": {"first_seen_at": now},
            },
            upsert=True,
        ))
    try:
        await mongo.player_clan_candidates.bulk_write(operations, ordered=False)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clan-history] presence write failed: {type(exc).__name__}: {exc}")
        return False


async def record_active_war_roster(
    mongo,
    presences: Iterable[ClanPresence],
    *,
    kind: str,
    active_until: datetime,
    observed_at: datetime | None = None,
) -> bool:
    """Record exact active-war roster membership for immediate bootstrap.

    This is deliberately separate from ``last_seen_at``: being on a CWL roster
    proves an attack obligation, but not that the player was physically in that
    clan during the last 48 hours.
    """
    if kind not in {"war", "cwl"}:
        raise ValueError("kind must be 'war' or 'cwl'")
    if mongo is None:
        return False

    unique: dict[tuple[str, str], ClanPresence] = {}
    for presence in presences:
        player_tag = _tag(presence.player_tag)
        clan_tag = _tag(presence.clan_tag)
        if player_tag and clan_tag:
            unique[(player_tag, clan_tag)] = presence
    if not unique:
        return True

    await ensure_indexes(mongo)
    now = _now(observed_at)
    until = _now(active_until)
    field = f"{kind}_until"
    operations = []
    for (player_tag, clan_tag), presence in unique.items():
        operations.append(UpdateOne(
            {"_id": _candidate_id(player_tag, clan_tag)},
            {
                "$set": {
                    "player_tag": player_tag,
                    "clan_tag": clan_tag,
                    "clan_name": presence.clan_name,
                    "clan_badge": presence.clan_badge,
                    "updated_at": now,
                },
                "$max": {field: until, "purge_at": now + RETENTION},
            },
            upsert=True,
        ))
    try:
        await mongo.player_clan_candidates.bulk_write(operations, ordered=False)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"[clan-history] war-roster write failed: {type(exc).__name__}: {exc}")
        return False


async def load_candidates(
    mongo,
    player_tags: Iterable[str],
    *,
    observed_at: datetime | None = None,
) -> dict[str, list[ClanCandidate]]:
    """Bulk-load recent-clan and active-war candidates for linked players."""
    if mongo is None:
        return {}
    tags = list(dict.fromkeys(_tag(tag) for tag in player_tags if _tag(tag)))
    if not tags:
        return {}

    await ensure_indexes(mongo)
    now = _now(observed_at)
    cutoff = now - HISTORY_WINDOW
    query = {
        "player_tag": {"$in": tags},
        "$or": [
            {"last_seen_at": {"$gte": cutoff}},
            {"war_until": {"$gte": now}},
            {"cwl_until": {"$gte": now}},
        ],
    }
    try:
        documents = await mongo.player_clan_candidates.find(query).to_list(length=None)
    except Exception as exc:  # noqa: BLE001
        print(f"[clan-history] candidate read failed: {type(exc).__name__}: {exc}")
        return {}

    result: dict[str, list[ClanCandidate]] = {}
    seen: set[tuple[str, str]] = set()
    for document in documents:
        player_tag = _tag(document.get("player_tag"))
        clan_tag = _tag(document.get("clan_tag"))
        key = (player_tag, clan_tag)
        if not player_tag or not clan_tag or key in seen:
            continue
        seen.add(key)
        recent = _at_or_after(document.get("last_seen_at"), cutoff)
        result.setdefault(player_tag, []).append(ClanCandidate(
            clan_tag=clan_tag,
            clan_name=document.get("clan_name"),
            clan_badge=document.get("clan_badge"),
            check_war=recent or _at_or_after(document.get("war_until"), now),
            check_cwl=recent or _at_or_after(document.get("cwl_until"), now),
        ))
    for player_candidates in result.values():
        player_candidates.sort(key=lambda candidate: candidate.clan_tag)
    return result


def presences_from_accounts(accounts: Iterable[object]) -> list[ClanPresence]:
    """Convert todo Account-like objects without importing todo_data."""
    result = []
    for account in accounts:
        clan_tag = getattr(account, "clan_tag", None)
        if not clan_tag:
            continue
        result.append(ClanPresence(
            player_tag=getattr(account, "tag", ""),
            clan_tag=clan_tag,
            clan_name=getattr(account, "clan_name", None),
            clan_badge=getattr(account, "clan_badge", None),
        ))
    return result
