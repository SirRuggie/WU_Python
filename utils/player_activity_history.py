"""Bounded clan history caches; only the activity storage owner persists them."""

import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from utils.constants import WARRIORS_UNITED_GUILD_ID
from utils.fwa_war_plan_store import WarPlanStore
from utils.player_activity_store import PlayerActivityStore
from utils.strike_store import StrikeService, tag, stamp, validate_war, war_key
from utils.strike_wars import fetch_history_report

log = logging.getLogger(__name__)
HISTORY_VERSION = 2
HISTORY_TIMEOUT_SECONDS = 600


def recent_wars(existing, incoming):
    indexed = {}
    for row in [*existing, *incoming]:
        used, available = row.get("attacks_used"), row.get("attacks_available")
        if (
            not isinstance(row.get("war_key"), str)
            or not 1 <= len(row["war_key"]) <= 256
            or type(used) is not int
            or type(available) is not int
            or available != 2
            or not 0 <= used <= available
        ):
            raise ValueError("Incomplete player war observation")
        prior = indexed.get(row["war_key"], {})
        indexed[row["war_key"]] = {
            "war_key": row["war_key"],
            "occurred_at": stamp(row["occurred_at"]),
            "attacks_used": used,
            "attacks_available": available,
            "neutral": bool(prior.get("neutral") or row.get("neutral")),
        }
    return sorted(
        indexed.values(), key=lambda r: (r["occurred_at"], r["war_key"]), reverse=True
    )[:14]


async def _backfill(mongo, fetch, now):
    store = PlayerActivityStore(mongo)
    players = await store.all_players()
    if not players:
        return {"players": 0, "wars": 0, "retryable": 0, "stuck_clans": []}
    from utils.player_activity_polling import active_clan

    clans = [
        row
        for row in await mongo.clans.find({}).to_list(length=None)
        if row.get("tag") and active_clan(row)
    ]
    if len(clans) > 100:
        raise RuntimeError("Activity history clan budget exceeded")
    tags = {tag(row["tag"]) for row in clans}
    await store.retire_history_clans(tags, now=now)
    states = {row["clan_tag"]: row for row in await store.history_clans()}
    semaphore = asyncio.Semaphore(3)
    plans = WarPlanStore(mongo)

    async def read(clan):
        key = tag(clan["tag"])
        previous = states.get(key, {})
        new_member = any(
            p.get("current_clan_tag") == key
            and p.get("tracking_started_at")
            and previous.get("captured_at")
            and stamp(p["tracking_started_at"]) > stamp(previous["captured_at"])
            for p in players
        )
        if (
            previous.get("version") == HISTORY_VERSION
            and previous.get("status") == "complete"
            and not previous.get("left_at")
            and not new_member
        ):
            return
        if previous.get("next_retry_at") and stamp(previous["next_retry_at"]) > now:
            return
        async with semaphore:
            # A durable pending marker is not an attempt charge. Cancellation or
            # restart leaves it immediately retryable, preserving previous data.
            await store.save_history_clan(
                key,
                {
                    **{
                        k: v
                        for k, v in previous.items()
                        if k in ("wars", "failed_attempts", "captured_at")
                    },
                    "status": "pending",
                    "version": HISTORY_VERSION,
                },
                now=now,
            )
            try:
                async with asyncio.timeout(120):
                    report = await fetch(key, days=60)
                    cached = {}
                    partial = bool(report.get("skipped"))
                    for war in report["wars"]:
                        try:
                            validate_war(war, now=now)
                        except (ValueError, TypeError, KeyError):
                            partial = True
                            continue
                        if (
                            not now - timedelta(days=60)
                            <= stamp(war["end_time"])
                            <= now
                        ):
                            continue
                        neutral = False
                        if clan.get("type") == "FWA":
                            outcome, _ = await plans.outcome(
                                WARRIORS_UNITED_GUILD_ID, war
                            )
                            if outcome is None:
                                partial = True
                                continue
                            neutral = outcome == "mismatch"
                        cached[war_key(war)] = {
                            "war_key": war_key(war),
                            "occurred_at": stamp(war["end_time"]),
                            "neutral": neutral,
                            "members": [
                                {"tag": tag(m["tag"]), "attacks_used": m["attacks"]}
                                for m in war["members"]
                            ],
                        }
                    wars = sorted(
                        cached.values(), key=lambda w: w["occurred_at"], reverse=True
                    )
                    partial = partial or len(wars) > 60
                    if partial:
                        raise PartialHistory(wars[:60])
                    await store.save_history_clan(
                        key,
                        {
                            "status": "complete",
                            "version": HISTORY_VERSION,
                            "failed_attempts": 0,
                            "next_retry_at": None,
                            "captured_at": now,
                            "wars": wars,
                        },
                        now=now,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                failures = int(previous.get("failed_attempts", 0)) + 1
                cached = (
                    exc.wars
                    if isinstance(exc, PartialHistory)
                    else previous.get("wars", [])
                )
                retry = (
                    timedelta(hours=6)
                    if failures >= 3
                    else timedelta(minutes=5 * failures)
                )
                await store.save_history_clan(
                    key,
                    {
                        "status": "stuck" if failures >= 3 else "retry",
                        "version": HISTORY_VERSION,
                        "failed_attempts": failures,
                        "next_retry_at": now + retry,
                        "wars": cached,
                        "captured_at": previous.get("captured_at"),
                    },
                    now=now,
                )
                log.warning(
                    "Player activity history incomplete: clan=%s failures=%d",
                    key,
                    failures,
                )

    await asyncio.gather(*(read(clan) for clan in clans))
    states = {
        row["clan_tag"]: row
        for row in await store.history_clans()
        if row["clan_tag"] in tags
    }
    complete = bool(clans) and all(
        states.get(c, {}).get("status") == "complete" for c in tags
    )
    observed = defaultdict(list)
    selected = {row["_id"] for row in players}
    exclusions = await StrikeService(mongo).history_exclusions(
        WARRIORS_UNITED_GUILD_ID, selected
    )
    for state in states.values():
        for war in state.get("wars", []):
            if stamp(war["occurred_at"]) < now - timedelta(days=60):
                continue
            for member in war["members"]:
                player = member["tag"]
                if player in selected:
                    observed[player].append(
                        {
                            "war_key": war["war_key"],
                            "occurred_at": war["occurred_at"],
                            "attacks_used": member["attacks_used"],
                            "attacks_available": 2,
                            "neutral": bool(
                                war.get("neutral")
                                or war["war_key"] in exclusions.get(player, set())
                            ),
                        }
                    )
    for player in selected:
        await store.save_recent_wars(
            player,
            observed[player],
            complete=complete,
            version=HISTORY_VERSION,
            now=now,
        )
    stuck = sorted(c for c, s in states.items() if s.get("failed_attempts", 0) >= 3)
    return {
        "players": len(players),
        "wars": sum(map(len, observed.values())),
        "retryable": sum(s.get("status") != "complete" for s in states.values()),
        "stuck_clans": stuck,
    }


class PartialHistory(ValueError):
    def __init__(self, wars):
        self.wars = wars


async def backfill_recent_wars(mongo, *, fetch=fetch_history_report, now=None):
    async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
        return await _backfill(mongo, fetch, now or datetime.now(timezone.utc))
