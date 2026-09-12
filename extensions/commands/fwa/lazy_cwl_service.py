# extensions/commands/fwa/lazy_cwl_service.py
"""Scheduler lifecycle and orchestration for LazyCWL saved player lists.

Sits on top of utils/lazy_cwl_store.py, the only module allowed to touch
the LazyCWL saved-list collection (reports/design-01-main.md section 9). This
module owns the AsyncIOScheduler, the daily expiry job, the reminder jobs,
and the four operations a later dashboard brief calls: save_list,
remind_now, add_player_by_tag, set_reminders (plus away_players and
finish). No slash command, component action, or bot-event hook is wired up
here; a later brief calls start()/stop() from StartedEvent/StoppingEvent.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import coc
import hikari
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.base import JobLookupError
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
)

from utils import lazy_cwl_store as store
from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler
from utils.constants import GOLD_ACCENT, RED_ACCENT
from utils.clash_links import resolve_discord_ids

_log = logging.getLogger(__name__)

# Hard-coded ping channel, unchanged from the old feature; out of scope here.
PING_CHANNEL = 1424256751913668770

JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 300,
}
EXPIRY_JOB_ID = "lazycwl_expiry"
SEVEN_DAYS = timedelta(days=7)

# Module globals, set once by start().
scheduler: Optional[AsyncIOScheduler] = None
bot_instance: Optional[hikari.GatewayBot] = None
coc_client: Optional[coc.Client] = None
mongo_client: Optional[MongoClient] = None
startup_reconciler: Optional[StartupReconciler] = None


async def get_discord_ids(player_tags: list[str]) -> Optional[dict[str, Optional[str]]]:
    """
    Call ClashKing API to get Discord IDs for player tags.

    Args:
        player_tags: List of player tags WITH # prefix

    Returns:
        Dict mapping player tags (with #) to Discord IDs or None,
        or **None if the lookup itself failed**.

    A FAILED LOOKUP AND AN EMPTY RESULT ARE DIFFERENT THINGS AND CALLERS MUST
    TELL THEM APART. This previously returned {} for both, and the caller could
    not distinguish "ClashKing is down" from "nobody in this clan has linked".
    The snapshot was written either way, with discord_id None on every player,
    and every downstream auto-ping then silently pinged nobody. Nothing raised
    and nothing warned; the bad snapshot persisted until deleted by hand.

        None  -> the call failed. The answer is unknown. Do not persist.
        {}    -> the call succeeded and nobody is linked. A real answer.
    """
    if not player_tags:
        return {}

    return await resolve_discord_ids(player_tags)


def _reminder_job_id(list_id) -> str:
    return f"lazycwl_reminder_{list_id}"


def _remove_job(job_id: str) -> None:
    if scheduler is None:
        return
    try:
        scheduler.remove_job(job_id)
    except JobLookupError:
        pass
    except Exception:
        _log.warning("lazycwl_service._remove_job: unexpected error removing job_id=%s", job_id, exc_info=True)


def _reminder_expired(reminders: dict, now: datetime) -> bool:
    """True once seven days have passed since reminders were turned on.

    The one 7-day check shared by reminder_job and restore_reminder_jobs.
    """
    started_at = reminders.get("started_at")
    if not started_at:
        return False
    return now - store._utc(started_at) > SEVEN_DAYS


def calculate_next_run(doc: dict, now: Optional[datetime] = None) -> datetime:
    """Find the next future reminder run while preserving the persisted
    cadence, ported from the old auto-ping cadence math (lazy_cwl.py:64-88).

    Missed intervals are skipped rather than replayed after a reboot: the
    next run stays aligned to the last successful send (or the start time
    for a job that has never sent).
    """
    now = store._utc(now)
    reminders = doc.get("reminders", {})
    interval_minutes = max(1, int(reminders.get("every_minutes") or 60))
    interval = timedelta(minutes=interval_minutes)
    anchor = (
        (store._utc(reminders["last_sent_at"]) if reminders.get("last_sent_at") else None)
        or (store._utc(reminders["started_at"]) if reminders.get("started_at") else None)
        or now
    )

    next_run = anchor + interval
    if next_run <= now:
        missed_intervals = ((now - anchor) // interval) + 1
        next_run = anchor + (interval * missed_intervals)
    return next_run


async def start(bot: hikari.GatewayBot, coc_api: coc.Client, mongo: MongoClient) -> None:
    """Create the scheduler and reconciler once; safe to call repeatedly.

    A later brief calls this from a StartedEvent hook, which can fire
    more than once for the same process; only the first call builds the
    scheduler and reconciler, matching lazy_cwl.py's on_bot_started guard.
    """
    global scheduler, bot_instance, coc_client, mongo_client, startup_reconciler

    bot_instance = bot
    coc_client = coc_api
    mongo_client = mongo

    if scheduler is None:
        scheduler = AsyncIOScheduler(timezone="UTC", job_defaults=JOB_DEFAULTS)
    if startup_reconciler is None:
        startup_reconciler = StartupReconciler("lazy_cwl_service", reconcile)
    startup_reconciler.start()


async def stop() -> None:
    """Shut down the scheduler and reconciler cleanly; safe to call twice."""
    global scheduler, startup_reconciler

    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None

    current_scheduler = scheduler
    scheduler = None
    if current_scheduler is None:
        return
    try:
        current_scheduler.shutdown(wait=False)
    except Exception:
        _log.exception("lazycwl_service: scheduler shutdown failed")


async def reconcile() -> None:
    """Repair indexes, stop jobs for expired lists, restore reminder jobs,
    and (re)install the daily expiry cron. Called by StartupReconciler with
    retries, so it must be idempotent.

    ensure_indexes failures re-raise so the reconciler retries instead of
    letting restore run against unrepaired data (audit item 7).
    """
    if scheduler is None:
        raise RuntimeError("service not started")
    if not scheduler.running:
        scheduler.start()

    try:
        await store.ensure_indexes(mongo_client)
    except Exception:
        _log.exception("lazycwl_service: ensure_indexes failed")
        raise

    await expire_due_and_stop_jobs()
    await restore_reminder_jobs()

    scheduler.add_job(
        expire_due_and_stop_jobs,
        trigger=CronTrigger(hour=0, minute=10, timezone="UTC"),
        id=EXPIRY_JOB_ID,
        replace_existing=True,
        **JOB_DEFAULTS,
    )


_SAVE_LIST_DEFAULTS = {
    "ok": False, "clan_name": None, "clan_tag": None, "player_count": 0,
    "linked_count": 0, "already_saved": False, "existing_saved_at": None,
    "error": None,
}


async def save_list(clan_tag: str, saved_by: int) -> dict:
    """Save clan_tag's current roster as its active saved list."""
    try:
        clan = await coc_client.get_clan(clan_tag)
    except coc.NotFound:
        return {**_SAVE_LIST_DEFAULTS, "error": f"Clan {clan_tag} not found."}

    tags = [member.tag for member in clan.members]
    links = await get_discord_ids(tags)
    if links is None:
        return {
            **_SAVE_LIST_DEFAULTS,
            "clan_name": clan.name,
            "clan_tag": clan.tag,
            "error": "Could not reach the link service. Nothing was saved. Try again in a minute.",
        }

    players = []
    linked_count = 0
    for member in clan.members:
        discord_raw = links.get(member.tag)
        discord_id = int(discord_raw) if discord_raw else None
        if discord_id is not None:
            linked_count += 1
        players.append({
            "tag": member.tag,
            "name": member.name,
            "town_hall": member.town_hall,
            "discord_id": discord_id,
        })

    try:
        document = await store.save_list(
            mongo_client,
            clan_tag=clan.tag,
            clan_name=clan.name,
            players=players,
            saved_by=saved_by,
        )
    except store.AlreadySavedError as exc:
        existing = exc.existing_doc
        return {
            **_SAVE_LIST_DEFAULTS,
            "clan_name": clan.name,
            "clan_tag": clan.tag,
            "already_saved": True,
            "existing_saved_at": existing.get("saved_at") if existing else None,
            "error": "This clan already has a saved list.",
        }

    return {
        "ok": True,
        "clan_name": document["clan_name"],
        "clan_tag": document["clan_tag"],
        "player_count": len(document["players"]),
        "linked_count": linked_count,
        "already_saved": False,
        "existing_saved_at": None,
        "error": None,
    }


async def away_players(doc: dict) -> list[dict]:
    """Players on doc's saved list who are not in the clan right now."""
    clan = await coc_client.get_clan(doc["clan_tag"])
    current = {member.tag.upper() for member in clan.members}
    return [
        player for player in doc.get("players", [])
        if player.get("tag", "").upper() not in current
    ]


async def _send_reminder_message(doc: dict, away: list[dict]) -> None:
    clan_data = await mongo_client.clans.find_one({"tag": doc["clan_tag"]})
    role_id = clan_data.get("role_id") if clan_data else None

    lines = [
        Text(content=f"## 🚪 Time to go back to {doc['clan_name']}"),
        Separator(),
    ]
    for player in away:
        mention = f"<@{player['discord_id']}>" if player.get("discord_id") else "no Discord link"
        lines.append(Text(content=f"**{player['name']}** · {mention}"))
    lines.append(Separator())
    lines.append(Text(content=(
        "Go back to your home clan for the war. Train, join, attack, return. "
        "About 15 to 30 minutes."
    )))

    await bot_instance.rest.create_message(
        channel=PING_CHANNEL,
        components=[Container(accent_color=GOLD_ACCENT, components=lines)],
        user_mentions=True,
        role_mentions=[int(role_id)] if role_id else [],
    )


_REMIND_NOW_DEFAULTS = {
    "ok": False, "clan_name": None, "away_count": 0, "total_count": 0,
    "sent": False, "error": None,
}


async def remind_now(clan_tag: str) -> dict:
    """Send an away-players reminder for clan_tag's active saved list."""
    doc = await store.get_active(mongo_client, clan_tag)
    if doc is None:
        return {**_REMIND_NOW_DEFAULTS, "error": "No saved list for this clan."}

    away = await away_players(doc)
    total_count = len(doc.get("players", []))
    if not away:
        return {
            "ok": True,
            "clan_name": doc["clan_name"],
            "away_count": 0,
            "total_count": total_count,
            "sent": False,
            "error": None,
        }

    await _send_reminder_message(doc, away)
    await store.record_reminder_sent(mongo_client, doc["_id"])

    return {
        "ok": True,
        "clan_name": doc["clan_name"],
        "away_count": len(away),
        "total_count": total_count,
        "sent": True,
        "error": None,
    }


async def add_player_by_tag(clan_tag: str, tag: str) -> dict:
    """Add one player, found by tag, to clan_tag's active saved list."""
    tag = store._normalize_tag(tag)
    if not coc.utils.is_valid_tag(tag):
        return {
            "ok": False, "name": None, "town_hall": None, "discord_id": None,
            "away_now": None, "error": "That doesn't look like a player tag.",
            "reason": "invalid_tag",
        }

    try:
        player = await coc_client.get_player(tag)
    except coc.NotFound:
        return {
            "ok": False, "name": None, "town_hall": None, "discord_id": None,
            "away_now": None, "error": "Player not found.", "reason": "not_found",
        }

    links = await get_discord_ids([player.tag])
    reason = None
    discord_id = None
    if links is None:
        reason = "link_service_down"
    else:
        raw = links.get(player.tag)
        discord_id = int(raw) if raw else None

    try:
        doc = await store.add_player(
            mongo_client,
            clan_tag,
            {"tag": player.tag, "name": player.name, "town_hall": player.town_hall, "discord_id": discord_id},
            added_manually=True,
        )
    except store.NoActiveListError:
        return {
            "ok": False, "name": None, "town_hall": None, "discord_id": None,
            "away_now": None, "error": "No saved list for this clan.", "reason": "no_list",
        }
    except store.PlayerAlreadyListedError:
        return {
            "ok": False, "name": player.name, "town_hall": player.town_hall, "discord_id": None,
            "away_now": None, "error": f"{player.name} is already on the list.",
            "reason": "already_listed",
        }

    clan = await coc_client.get_clan(doc["clan_tag"])
    current = {member.tag.upper() for member in clan.members}
    away_now = player.tag.upper() not in current

    return {
        "ok": True,
        "name": player.name,
        "town_hall": player.town_hall,
        "discord_id": discord_id,
        "away_now": away_now,
        "error": None,
        "reason": reason,
    }


async def set_reminders(clan_tag: str, enabled: bool, every_minutes: Optional[int] = None) -> dict:
    """Turn a clan's reminders on or off and (un)schedule its job."""
    if enabled and every_minutes is None:
        return {"ok": False, "error": "Choose how often."}

    doc = await store.set_reminders(mongo_client, clan_tag, enabled=enabled, every_minutes=every_minutes)
    if doc is None:
        return {"ok": False, "error": "No saved list for this clan."}

    job_id = _reminder_job_id(doc["_id"])
    if not enabled:
        _remove_job(job_id)
        return {"ok": True, "error": None}

    try:
        scheduler.add_job(
            reminder_job,
            trigger=IntervalTrigger(minutes=every_minutes),
            args=[doc["_id"]],
            id=job_id,
            replace_existing=True,
            **JOB_DEFAULTS,
        )
    except Exception as exc:
        # Mirror lazy_cwl.py:91-99: never advertise reminders as on when the
        # scheduler could not actually create the job.
        await store.set_reminders(mongo_client, clan_tag, enabled=False, every_minutes=every_minutes)
        _log.error("lazycwl_service.set_reminders: add_job failed clan_tag=%s error=%s", clan_tag, exc)
        return {"ok": False, "error": "Could not schedule reminders. Try again."}

    return {"ok": True, "error": None}


async def reminder_job(list_id) -> None:
    """Scheduled callback for one saved list's reminders.

    Re-reads current state on every run so a stale in-memory doc never
    drives a send; stops itself once the list is no longer eligible.
    Never propagates: an uncaught exception here would surface inside
    APScheduler rather than the bot's normal error handling.
    """
    try:
        doc = await store.get_by_id(mongo_client, list_id)
        job_id = _reminder_job_id(list_id)

        if doc is None or doc.get("status") != "active" or not doc.get("reminders", {}).get("enabled"):
            _remove_job(job_id)
            return

        now = datetime.now(timezone.utc)
        if _reminder_expired(doc["reminders"], now):
            await store.set_reminders(
                mongo_client, doc["clan_tag"], enabled=False,
                every_minutes=doc["reminders"].get("every_minutes"),
            )
            _remove_job(job_id)
            await bot_instance.rest.create_message(
                channel=PING_CHANNEL,
                components=[Container(accent_color=RED_ACCENT, components=[
                    Text(content=f"Auto reminders for {doc['clan_name']} stopped after 7 days."),
                ])],
            )
            return

        await remind_now(doc["clan_tag"])
    except Exception:
        _log.exception("lazycwl_service.reminder_job: unhandled error list_id=%s", list_id)


async def restore_reminder_jobs() -> None:
    """Recreate scheduler jobs for every saved list with reminders enabled,
    skipping jobs that already exist and disabling anything past 7 days."""
    docs = await store.list_reminder_enabled(mongo_client)
    now = datetime.now(timezone.utc)

    for doc in docs:
        if _reminder_expired(doc["reminders"], now):
            await store.set_reminders(
                mongo_client, doc["clan_tag"], enabled=False,
                every_minutes=doc["reminders"].get("every_minutes"),
            )
            continue

        job_id = _reminder_job_id(doc["_id"])
        if scheduler.get_job(job_id) is not None:
            continue

        try:
            scheduler.add_job(
                reminder_job,
                trigger=IntervalTrigger(minutes=doc["reminders"]["every_minutes"]),
                args=[doc["_id"]],
                id=job_id,
                replace_existing=True,
                next_run_time=calculate_next_run(doc, now),
                **JOB_DEFAULTS,
            )
        except Exception:
            _log.exception("lazycwl_service.restore_reminder_jobs: add_job failed list_id=%s", doc["_id"])


async def expire_due_and_stop_jobs(now: Optional[datetime] = None) -> int:
    """Flip due active lists to expired and remove their reminder jobs.

    Wrapped so a store failure never raises into the scheduler: this also
    runs directly as the daily expiry cron's callback.
    """
    try:
        docs = await store.expire_due(mongo_client, now)
    except Exception:
        _log.exception("lazycwl_service.expire_due_and_stop_jobs: expire_due failed")
        return 0

    for doc in docs:
        _remove_job(_reminder_job_id(doc["_id"]))
    return len(docs)


async def finish(clan_tag: str) -> dict:
    """Mark a clan's saved list finished and stop its reminder job."""
    doc = await store.finish(mongo_client, clan_tag)
    if doc is None:
        return {"ok": False, "clan_name": None, "error": "No saved list for this clan."}
    _remove_job(_reminder_job_id(doc["_id"]))
    return {"ok": True, "clan_name": doc["clan_name"], "error": None}
