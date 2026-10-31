"""Daily bounded clan history; unusable observations stop only local chains."""

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
HISTORY_VERSION = 3
HISTORY_TIMEOUT_SECONDS = 600


def recent_wars(existing, incoming):
    # A successful refresh replaces old gap markers. Neutral decisions survive
    # ledger retention, while all timestamps normalize BSON's naive UTC values.
    indexed = {}
    for row in [*(r for r in existing if not r.get("unusable")), *incoming]:
        key = row.get("war_key")
        if not isinstance(key, str) or not 1 <= len(key) <= 256:
            raise ValueError("Invalid war observation key")
        value = {"war_key": key, "occurred_at": stamp(row["occurred_at"])}
        if row.get("unusable"):
            value["unusable"] = True
        else:
            used, available = row.get("attacks_used"), row.get("attacks_available")
            if type(used) is not int or available != 2 or not 0 <= used <= 2:
                raise ValueError("Incomplete player war observation")
            value.update(
                attacks_used=used,
                attacks_available=2,
                neutral=bool(row.get("neutral") or indexed.get(key, {}).get("neutral")),
            )
        indexed[key] = value
    return sorted(indexed.values(), key=lambda r: (r["occurred_at"], r["war_key"]), reverse=True)[
        :14
    ]


def ignored(war):
    return war.get("war_type", war.get("type", "regular")) not in (None, "regular", "random")


def barrier_time(row, now):
    try:
        return stamp(row.get("end_time") or row.get("occurred_at"))
    except (ValueError, TypeError, AttributeError):
        return now


async def _backfill(mongo, fetch, now):
    from utils.player_activity_polling import active_clan

    store = PlayerActivityStore(mongo)
    players = await store.all_players()
    if not players:
        return {"players": 0, "wars": 0, "retryable": 0}
    clans = [
        r
        for r in await mongo.clans.find({}).to_list(length=None)
        if r.get("tag") and active_clan(r)
    ]
    if len(clans) > 100:
        raise RuntimeError("Activity history clan budget exceeded")
    tags = {tag(r["tag"]) for r in clans}
    await store.retire_history_clans(tags, now=now)
    states = {r["clan_tag"]: r for r in await store.history_clans()}
    semaphore, plans = asyncio.Semaphore(3), WarPlanStore(mongo)

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
            and not previous.get("left_at")
            and previous.get("next_read_at")
            and stamp(previous["next_read_at"]) > now
            and not new_member
        ):
            return
        async with semaphore:
            # No pending write: cancellation/restart never consumes an attempt.
            wars, unusable = previous.get("wars", []), []
            try:
                async with asyncio.timeout(120):
                    report = await fetch(key, days=60)
                    unusable = [
                        barrier_time(r, now)
                        for r in report.get("skipped", [])
                        if not r.get("ignored") and not ignored(r)
                    ]
                    cached = {}
                    for war in report["wars"]:
                        if ignored(war):
                            continue
                        try:
                            validate_war(war, now=now)
                        except (ValueError, TypeError, KeyError):
                            unusable.append(barrier_time(war, now))
                            continue
                        if not now - timedelta(days=60) <= stamp(war["end_time"]) <= now:
                            continue
                        outcome = None
                        if clan.get("type") == "FWA":
                            outcome, _ = await plans.outcome(WARRIORS_UNITED_GUILD_ID, war)
                        cached[war_key(war)] = {
                            "war_key": war_key(war),
                            "occurred_at": stamp(war["end_time"]),
                            "neutral": outcome == "mismatch",
                            "members": [
                                {"tag": tag(m["tag"]), "attacks_used": m["attacks"]}
                                for m in war["members"]
                            ],
                        }
                    wars = sorted(cached.values(), key=lambda w: w["occurred_at"], reverse=True)[
                        :60
                    ]
            except asyncio.CancelledError:
                raise
            except Exception:
                unusable = [now]
            failures = int(previous.get("failed_attempts", 0)) + 1 if unusable else 0
            delay = (
                timedelta(hours=6)
                if failures >= 3
                else timedelta(minutes=5 * failures) if failures else timedelta(days=1)
            )
            await store.save_history_clan(
                key,
                {
                    "version": HISTORY_VERSION,
                    "wars": wars,
                    "unusable": sorted(set(unusable), reverse=True)[:60],
                    "failed_attempts": failures,
                    "next_read_at": now + delay,
                    "captured_at": now,
                },
                now=now,
            )
            if failures:
                log.warning(
                    "Player activity history unavailable: clan=%s failures=%d", key, failures
                )

    await asyncio.gather(*(read(clan) for clan in clans))
    states = [r for r in await store.history_clans() if r["clan_tag"] in tags]
    observed = defaultdict(list)
    selected = {p["_id"] for p in players}
    exclusions = await StrikeService(mongo).history_exclusions(WARRIORS_UNITED_GUILD_ID, selected)
    for state in states:
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
        for p in players:
            if p.get("current_clan_tag") == state["clan_tag"]:
                observed[p["_id"]].extend(
                    {
                        "war_key": "unusable:" + state["clan_tag"] + ":" + stamp(t).isoformat(),
                        "occurred_at": stamp(t),
                        "unusable": True,
                    }
                    for t in state.get("unusable", [])
                    if stamp(t) >= now - timedelta(days=60)
                )
    for player in selected:
        await store.save_recent_wars(player, observed[player], version=HISTORY_VERSION, now=now)
    return {
        "players": len(players),
        "wars": sum(map(len, observed.values())),
        "retryable": sum(bool(s.get("failed_attempts")) for s in states),
    }


async def backfill_recent_wars(mongo, *, fetch=fetch_history_report, now=None):
    async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
        return await _backfill(mongo, fetch, now or datetime.now(timezone.utc))
