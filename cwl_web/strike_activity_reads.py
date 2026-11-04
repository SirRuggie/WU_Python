"""Parallel HTTP read adaptation: fresh ledger core and optional activity."""

import asyncio
from dataclasses import dataclass

from pymongo.errors import PyMongoError

from utils.player_activity_overview import activity_view_context
from utils.player_activity_store import PlayerActivityStore
from utils.player_activity_cache import ActivityPayload
from .strike_activity_cache import snapshots


@dataclass
class ActivityRead:
    activity: list
    context: dict
    warning: str | None
    history_warning: str | None
    checked_at: object
    updating: bool
    unavailable: bool


async def optional(read, *, timeout=1.5):
    try:
        return await asyncio.wait_for(read, timeout=timeout)
    except (PyMongoError, TimeoutError):
        return None


async def read_activity(request, db, ledger, guild_id):
    """The caller has authorized this request before any cache access.

    Background loaders capture the startup-owned pool, never a request/session.
    Observations are on-demand background data, at most30 seconds old (564).
    """
    owner = PlayerActivityStore(db)
    cache = snapshots(request.app)
    async def load():
        work = [asyncio.create_task(owner.overview()),
                asyncio.create_task(ledger.activity_observations(guild_id))]
        try:
            rows, observations = await asyncio.gather(*work)
            return ActivityPayload(rows, observations)
        finally:
            for task in work:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*work, return_exceptions=True)
    await cache.get(guild_id, load, require_observations=True)
    tasks = [asyncio.create_task(ledger.activity_core(guild_id)),
             asyncio.create_task(optional(owner.history_report()))]
    try:
        core, failed_clans = await asyncio.gather(*tasks)
    finally:
        # Also drain siblings on core failure or a disconnected HTTP request.
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    snapshot = await cache.get(guild_id, load, require_observations=True)
    activity = snapshot.rows
    records = snapshot.observations
    unavailable = activity is None or records is None
    warning = 'Activity unavailable. Strike rows remain available.' if unavailable else None
    if not unavailable:
        warning = 'Activity as of ' + snapshot.observations_checked_at.strftime('%H:%M') + ' UTC'
    # Incomplete observations cannot establish quiet/no-attack health or risk.
    # Assemble core-only rows so even the derived status is based on known data.
    context = activity_view_context(core, None if unavailable else activity,
                                    None if unavailable else records)
    names = {row['tag']: str(row.get('name') or row['tag'])[:100] for row in context['clans']}
    failures = sorted(set(failed_clans or []) & names.keys())
    history_warning = ('Some war reads unavailable for clans: ' + ', '.join(names[tag] for tag in failures)) if failures else None
    if core['clan_warning']:
        history_warning = 'Clan names are unavailable. Showing clan tags.'
    elif failed_clans is None:
        history_warning = 'Could not check recent war reads.'
    return ActivityRead([] if unavailable else activity, context, warning, history_warning,
                        snapshot.observations_checked_at,
                        snapshot.refreshing, unavailable)
