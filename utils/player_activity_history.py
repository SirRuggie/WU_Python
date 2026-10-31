"""Bounded, evidence-only historical activity backfill; never writes the ledger."""
import asyncio
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from utils.constants import WARRIORS_UNITED_GUILD_ID
from utils.fwa_war_plan_store import WarPlanStore
from utils.player_activity_store import PlayerActivityStore
from utils.strike_store import tag, stamp, validate_war, war_key
from utils.strike_wars import fetch_history_report

log = logging.getLogger(__name__)
HISTORY_VERSION = 1
MAX_ATTEMPTS = 3
HISTORY_TIMEOUT_SECONDS = 600


def recent_wars(existing, incoming):
    """Validate and retain fourteen distinct known two-attack outcomes."""
    indexed = {}
    for row in [*existing, *incoming]:
        used, available = row.get('attacks_used'), row.get('attacks_available')
        if (not isinstance(row.get('war_key'), str) or not row['war_key']
                or type(used) is not int or type(available) is not int
                or available != 2 or not 0 <= used <= available):
            raise ValueError('Incomplete player war observation')
        indexed[row['war_key']] = {'war_key': row['war_key'], 'occurred_at': stamp(row['occurred_at']),
                                   'attacks_used': used, 'attacks_available': available}
    return sorted(indexed.values(), key=lambda row: (row['occurred_at'], row['war_key']), reverse=True)[:14]


async def _backfill_recent_wars(mongo, *, fetch, now):
    """At most three attempts/player, three clan reads concurrently, ten minutes/run.

    Full historical lineups are fetched through the existing import reader. Only
    existing player documents are updated; retries merge idempotently by war key.
    Partial clan failures leave the completion receipt unset, never guessed rows.
    """
    now = now or datetime.now(timezone.utc)
    store = PlayerActivityStore(mongo)
    players = [row for row in await store.all_players()
               if row.get('recent_wars_version') != HISTORY_VERSION
               and row.get('recent_wars_attempts', 0) < MAX_ATTEMPTS]
    if not players:
        return {'players': 0, 'wars': 0, 'retryable': 0}
    selected = {row['_id'] for row in players}
    for player in selected:
        await store.begin_history_attempt(player, HISTORY_VERSION)
    from utils.player_activity_polling import active_clan
    clans = [row for row in await mongo.clans.find({}).to_list(length=None)
             if row.get('tag') and active_clan(row)]
    if len(clans) > 100:
        raise RuntimeError('Activity history clan budget exceeded')
    semaphore = asyncio.Semaphore(3)
    plans = WarPlanStore(mongo)
    async def read(clan):
        async with semaphore:
            try:
                async with asyncio.timeout(120):
                    report = await fetch(tag(clan['tag']), days=60)
                    wars = []
                    for war in report['wars']:
                        validate_war(war, now=now)
                        if not now-timedelta(days=60) <= stamp(war['end_time']) <= now:
                            continue
                        if clan.get('type') == 'FWA':
                            outcome, _ = await plans.outcome(WARRIORS_UNITED_GUILD_ID, war)
                            if outcome not in ('win', 'lose', 'blacklisted'):
                                continue  # Missing/neutral plans cannot establish penalties.
                        wars.append(war)
                    return wars, False
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Player activity historical wars unavailable: %s', clan['tag'])
                return [], True
    reports = await asyncio.gather(*(read(clan) for clan in clans))
    observed = defaultdict(list)
    incomplete = not clans or any(failed for _, failed in reports)
    for wars, _ in reports:
        for war in wars:
            for member in war['members']:
                player = tag(member['tag'])
                if player in selected:
                    observed[player].append({'war_key': war_key(war), 'occurred_at': war['end_time'],
                                             'attacks_used': member['attacks'], 'attacks_available': 2})
    for player in selected:
        await store.save_recent_wars(player, observed[player], complete=not incomplete,
                                     version=HISTORY_VERSION, now=now)
    result = {'players': len(selected), 'wars': sum(len(rows) for rows in observed.values()),
              'retryable': len(selected) if incomplete else 0}
    log.info('Player activity historical backfill: players=%d wars=%d retryable=%d',
             result['players'], result['wars'], result['retryable'])
    return result


async def backfill_recent_wars(mongo, *, fetch=fetch_history_report, now=None):
    """Bound the entire job, including Mongo reads, attempt receipts and CAS writes."""
    async with asyncio.timeout(HISTORY_TIMEOUT_SECONDS):
        return await _backfill_recent_wars(mongo, fetch=fetch, now=now)
