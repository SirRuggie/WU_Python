"""Background discovery for cross-clan /todo obligations.

The tracker keeps network discovery away from the interaction path:

* registered clan rosters identify current family members;
* a family-roster departure enrolls that player and all linked accounts for
  direct profile polling, regardless of destination clan;
* a /todo use adds a direct 48-hour watch as a second enrollment path;
* active regular-war and CWL rosters bootstrap obligations that were spun
  before the tracker started.

Mongo retention and query semantics live in utils.clan_history.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import coc
import hikari
import lightbulb

from utils import clan_history, todo_data
from utils.clash_links import resolve_family_linked_tags
from utils.mongo import MongoClient


loader = lightbulb.Loader()

SCAN_INTERVAL_SECONDS = 10 * 60
FETCH_CONCURRENCY = 8
LINK_EXPANSION_BATCH_SIZE = 100

tracker_task: asyncio.Task | None = None


def _badge(obj) -> str | None:
    return getattr(getattr(obj, "badge", None), "medium", None)


def _war_end(war, fallback: datetime) -> datetime:
    value = getattr(getattr(war, "end_time", None), "time", None)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    return fallback


def _utc_datetime(value) -> datetime | None:
    """Normalize PyMongo's default naive UTC datetimes for local comparisons."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _safe_fetch(sem: asyncio.Semaphore, label: str, key: str, fn):
    try:
        async with sem:
            return await fn()
    except Exception as exc:  # noqa: BLE001 - one object cannot stop the tracker
        print(f"[clan-history] {label} fetch failed for {key}: "
              f"{type(exc).__name__}: {exc}")
        return None


def _clan_presences(clan) -> list[clan_history.ClanPresence]:
    clan_tag = getattr(clan, "tag", "")
    clan_name = getattr(clan, "name", None)
    badge = _badge(clan)
    return [
        clan_history.ClanPresence(member.tag, clan_tag, clan_name, badge)
        for member in getattr(clan, "members", ())
    ]


def _player_presence(player) -> clan_history.ClanPresence | None:
    clan = getattr(player, "clan", None)
    if clan is None:
        return None
    return clan_history.ClanPresence(
        player.tag, clan.tag, getattr(clan, "name", None), _badge(clan)
    )


def _war_roster(war, clan_tag: str) -> list[clan_history.ClanPresence]:
    side = todo_data._side_for(war, clan_tag)
    if side is None:
        return []
    return [
        clan_history.ClanPresence(
            member.tag,
            clan_tag,
            getattr(side, "name", None),
            _badge(side),
        )
        for member in getattr(side, "members", ())
    ]


async def run_scan(mongo: MongoClient, coc_client: coc.Client) -> dict[str, int]:
    """Run one complete scan and return counts for logs/tests."""
    now = datetime.now(timezone.utc)
    await clan_history.ensure_indexes(mongo)

    clan_docs = await mongo.clans.find(
        {"tag": {"$type": "string"}}, {"tag": 1, "type": 1}
    ).to_list(length=None)
    clan_tags = list(dict.fromkeys(
        str(doc.get("tag", "")).strip().upper()
        for doc in clan_docs
        if str(doc.get("tag", "")).strip()
    ))
    cwl_tags = list(dict.fromkeys(
        str(doc.get("tag", "")).strip().upper()
        for doc in clan_docs
        if str(doc.get("tag", "")).strip()
        and str(doc.get("type", "")).strip().upper() == "CWL"
    ))

    watch_docs = await mongo.player_clan_watches.find(
        {"expires_at": {"$gt": now}},
        {"_id": 1, "link_expand_pending": 1, "link_retry_at": 1,
         "link_retry_count": 1},
    ).to_list(length=None)
    watched_tags = list(dict.fromkeys(
        str(doc.get("_id", "")).strip().upper()
        for doc in watch_docs
        if str(doc.get("_id", "")).strip()
    ))

    sem = asyncio.Semaphore(FETCH_CONCURRENCY)
    clan_tasks = [
        _safe_fetch(sem, "clan", tag, lambda tag=tag: coc_client.get_clan(tag))
        for tag in clan_tags
    ]
    clans = await asyncio.gather(*clan_tasks)

    presences: list[clan_history.ClanPresence] = []
    family_roster_tags: list[str] = []
    current_rosters: dict[str, set[str]] = {}
    clan_metadata: dict[str, tuple[str | None, str | None]] = {}
    for clan in clans:
        if clan is None:
            continue
        clan_presences = _clan_presences(clan)
        family_roster_tags.extend(presence.player_tag for presence in clan_presences)
        current_rosters[clan.tag.upper()] = {
            presence.player_tag.upper() for presence in clan_presences
        }
        clan_metadata[clan.tag.upper()] = (getattr(clan, "name", None), _badge(clan))

    previous_rosters = await clan_history.load_roster_snapshots(
        mongo, current_rosters
    )
    changed_roster_tags: set[tuple[str, str]] = set()
    for clan_tag, members in current_rosters.items():
        previous = previous_rosters.get(clan_tag)
        changed = members if previous is None else members.symmetric_difference(previous)
        changed_roster_tags.update((player_tag, clan_tag) for player_tag in changed)
    for player_tag, clan_tag in changed_roster_tags:
        clan_name, clan_badge = clan_metadata.get(clan_tag, (None, None))
        presences.append(clan_history.ClanPresence(
            player_tag, clan_tag, clan_name, clan_badge
        ))

    departed_tags = set().union(*(
        previous_rosters.get(clan_tag, set()) - members
        for clan_tag, members in current_rosters.items()
    )) if current_rosters else set()
    movement_watches = set(departed_tags)
    pending_by_tag = {
        str(doc.get("_id", "")).strip().upper(): doc
        for doc in watch_docs
        if doc.get("link_expand_pending") and str(doc.get("_id", "")).strip()
    }
    newly_pending = departed_tags - set(pending_by_tag)
    queue_ok = await clan_history.queue_link_expansions(
        mongo, newly_pending, observed_at=now
    )
    for tag in newly_pending if queue_ok else ():
        pending_by_tag[tag] = {
            "_id": tag,
            "link_expand_pending": True,
            "link_retry_at": now,
            "link_retry_count": 0,
        }

    # Do not advance roster snapshots past a departure we failed to queue;
    # leaving the prior snapshot intact makes the next scan detect it again.
    snapshot_write = (
        asyncio.create_task(clan_history.save_roster_snapshots(
            mongo, current_rosters, observed_at=now
        ))
        if queue_ok else None
    )

    due_expansions = sorted(
        (
            doc for doc in pending_by_tag.values()
            if _utc_datetime(doc.get("link_retry_at")) is None
            or _utc_datetime(doc.get("link_retry_at")) <= now
        ),
        key=lambda doc: _utc_datetime(doc.get("link_retry_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
    )[:LINK_EXPANSION_BATCH_SIZE]
    if due_expansions:
        source_tags = [str(doc["_id"]).strip().upper() for doc in due_expansions]
        retry_counts = {
            str(doc["_id"]).strip().upper(): int(doc.get("link_retry_count", 0) or 0)
            for doc in due_expansions
        }
        linked_tags = await resolve_family_linked_tags(source_tags)
        # Retrying link expansion must not reset the departed source account's
        # 48-hour watch. Only newly discovered linked accounts get a fresh
        # watch; the source keeps the expiry set when its departure was queued.
        discovered_tags = (
            set(linked_tags or ()) - set(source_tags)
            if linked_tags is not None else set()
        )
        linked_watch_ok = (
            linked_tags is not None
            and await clan_history.watch_players(
                mongo, discovered_tags, observed_at=now
            )
        )
        if linked_watch_ok:
            movement_watches.update(linked_tags or ())
            completed = await clan_history.complete_link_expansions(
                mongo, source_tags, observed_at=now
            )
            if not completed:
                await clan_history.postpone_link_expansions(
                    mongo, retry_counts, observed_at=now
                )
        else:
            await clan_history.postpone_link_expansions(
                mongo, retry_counts, observed_at=now
            )
            print("[clan-history] mover link expansion deferred for retry")

    if departed_tags:
        print(
            f"[clan-history] family departures detected "
            f"players={len(departed_tags)} watches={len(movement_watches)}"
        )
    watched_tags = list(dict.fromkeys(watched_tags + sorted(movement_watches)))

    player_tasks = [
        _safe_fetch(sem, "player", tag, lambda tag=tag: coc_client.get_player(tag))
        for tag in watched_tags
    ]
    war_tasks = [
        _safe_fetch(sem, "war", tag, lambda tag=tag: todo_data._get_war(coc_client, tag))
        for tag in clan_tags
    ]
    cwl_tasks = [
        _safe_fetch(sem, "CWL", tag, lambda tag=tag: todo_data._get_cwl_round(coc_client, tag))
        for tag in cwl_tags
    ]

    all_results = await asyncio.gather(*(player_tasks + war_tasks + cwl_tasks))
    offset = 0
    players = all_results[offset:offset + len(player_tasks)]
    offset += len(player_tasks)
    wars = all_results[offset:offset + len(war_tasks)]
    offset += len(war_tasks)
    cwls = all_results[offset:offset + len(cwl_tasks)]

    for player in players:
        if player is not None:
            presence = _player_presence(player)
            if presence is not None:
                presences.append(presence)
    await clan_history.record_presence(mongo, presences, observed_at=now)

    war_roster: list[clan_history.ClanPresence] = []
    for clan_tag, result in zip(clan_tags, wars):
        if not result:
            continue
        kind, war = result
        if kind != "war" or war is None or todo_data._state(war) not in {"inWar", "preparation"}:
            continue
        clan_roster = _war_roster(war, clan_tag)
        war_roster.extend(clan_roster)
        if clan_roster:
            # Each clan's roster expires with its own war. Using one maximum end
            # across every clan kept earlier wars falsely active.
            await clan_history.record_active_war_roster(
                mongo,
                clan_roster,
                kind="war",
                active_until=_war_end(war, now + timedelta(days=2)),
                observed_at=now,
            )

    cwl_roster: list[clan_history.ClanPresence] = []
    for clan_tag, result in zip(cwl_tags, cwls):
        if not result:
            continue
        kind, war = result
        if kind != "war" or war is None or todo_data._state(war) not in {"inWar", "preparation"}:
            continue
        clan_roster = _war_roster(war, clan_tag)
        cwl_roster.extend(clan_roster)
        if clan_roster:
            await clan_history.record_active_war_roster(
                mongo,
                clan_roster,
                kind="cwl",
                active_until=_war_end(war, now + timedelta(days=2)),
                observed_at=now,
            )
    if snapshot_write is not None:
        await snapshot_write

    return {
        "clans": len(clan_tags),
        "cwl_clans": len(cwl_tags),
        "family_players": len(set(family_roster_tags)),
        "roster_changes": len(changed_roster_tags),
        "departed_players": len(departed_tags),
        "movement_players": len(movement_watches),
        "watched_players": len(watched_tags),
        "presences": len(presences),
        "war_roster": len(war_roster),
        "cwl_roster": len(cwl_roster),
    }


async def tracker_loop(mongo: MongoClient, coc_client: coc.Client) -> None:
    while True:
        try:
            counts = await run_scan(mongo, coc_client)
            print("[clan-history] scan complete " + " ".join(
                f"{key}={value}" for key, value in counts.items()
            ))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - retry on the next interval
            print(f"[clan-history] scan failed: {type(exc).__name__}: {exc}")
        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
    coc_client: coc.Client = lightbulb.di.INJECTED,
) -> None:
    del event
    global tracker_task
    tracker_task = asyncio.create_task(
        tracker_loop(mongo, coc_client), name="clan-history-tracker"
    )
    print("[clan-history] tracker started")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    del event
    global tracker_task
    if tracker_task and not tracker_task.done():
        tracker_task.cancel()
        try:
            await tracker_task
        except asyncio.CancelledError:
            pass
    print("[clan-history] tracker stopped")
