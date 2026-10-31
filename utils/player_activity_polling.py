"""Hourly player polling, spread evenly; failed reads never become observations."""
import asyncio
import logging
import time
from dataclasses import dataclass
import coc

from utils.player_activity_store import PlayerActivityStore
from utils.player_activity_raids import capture_raids
from utils.player_activity_seed import seed_from_clashking

log = logging.getLogger(__name__)


class PacedOfficialClient:
    """One logical official API call per second across this feature's reads."""
    def __init__(self, client, *, sleep=asyncio.sleep, clock=time.monotonic):
        self.client = client
        self.sleep = sleep
        self.clock = clock
        self.next_at = 0.0
        self.lock = asyncio.Lock()

    async def request(self, method, *args, **kwargs):
        async with self.lock:
            await self.sleep(max(0, self.next_at - self.clock()))
            self.next_at = self.clock() + 1
            return await getattr(self.client, method)(*args, **kwargs)

    async def get_clan(self, clan):
        return await self.request('get_clan', clan, cls=CompleteActivityClan)

    async def get_player(self, player):
        return await self.request('get_player', player)

    async def get_raid_log(self, clan, **kwargs):
        return await self.request('get_raid_log', clan, **kwargs)


class CompleteActivityClan(coc.Clan):
    def __init__(self, *, data, client, **kwargs):
        if not isinstance(data.get('memberList'), list):
            raise ValueError('Clan response has no complete member list')
        super().__init__(data=data, client=client, **kwargs)


@dataclass
class RosterSweep:
    members: dict
    clan_tags: list
    complete: bool


def active_clan(row):
    return not (row.get('archived') or row.get('removed') or row.get('deleted')
                or row.get('removed_at') or row.get('deleted_at') or row.get('active') is False
                or row.get('status') in ('archived', 'removed', 'deleted'))


async def family_members(mongo, client):
    """A failed clan does not stop healthy polls or authorize departures."""
    from utils.strike_store import tag
    rows = await mongo.clans.find({'tag': {'$type': 'string'}}).to_list(length=None)
    clans = [row for row in rows if active_clan(row)]
    members = {}
    clan_tags = []
    complete = bool(clans)
    for row in clans:
        try:
            clan_tag = tag(row['tag'])
        except ValueError:
            complete = False
            log.warning('Player activity configured clan tag is invalid')
            continue
        clan_tags.append(clan_tag)
        try:
            clan = await client.get_clan(clan_tag)
            roster = clan.members
            count = getattr(clan, 'member_count', None)
            if type(count) is not int or count != len(roster) or tag(clan.tag) != clan_tag:
                raise ValueError('Incomplete clan roster')
            for player in roster:
                members[tag(player.tag)] = clan_tag
        except asyncio.CancelledError:
            raise
        except Exception:
            complete = False
            log.warning('Player activity clan roster unavailable: %s', clan_tag)
            try:
                for player, last_clan in (await PlayerActivityStore(mongo).known_members(clan_tag)).items():
                    members.setdefault(player, last_clan)
            except Exception:
                log.warning('Player activity saved roster unavailable: %s', clan_tag)
    if not members:
        complete = False
        log.warning('Player activity family roster is empty; departures suppressed')
    return RosterSweep(members, clan_tags, complete)


def player_payload(player):
    if isinstance(player, dict):
        return player
    fields = {'tag': 'tag', 'name': 'name', 'attackWins': 'attack_wins',
              'donations': 'donations', 'warPreference': 'war_opted_in',
              'builderBaseTrophies': 'builder_base_trophies', 'trophies': 'trophies',
              'expLevel': 'exp_level', 'townHallLevel': 'town_hall'}
    result = {key: getattr(player, attr) for key, attr in fields.items()
              if getattr(player, attr, None) is not None}
    for key, attr in (('heroes', 'heroes'), ('heroEquipment', 'equipment'),
                      ('troops', 'troops'), ('spells', 'spells')):
        result[key] = [{'name': unit.name, 'level': unit.level,
                        'village': getattr(unit, 'village', 'home')}
                       for unit in getattr(player, attr, [])]
    result['achievements'] = [{'name': item.name, 'value': item.value}
                              for item in getattr(player, 'achievements', [])]
    return result


async def poll_hour(store, members, fetch_player, *, sleep=asyncio.sleep, clock=time.monotonic, duration=3600):
    start = clock()
    count = len(members)
    success = failure = 0
    previous_start = start - 1
    for index, (player_tag, clan_tag) in enumerate(sorted(members.items())):
        await sleep(max(0, max(start + index * duration / max(count, 1), previous_start + 1) - clock()))
        previous_start = clock()
        try:
            player = await fetch_player(player_tag)
            payload = player_payload(player)
            if payload.get('tag') != player_tag:
                raise ValueError('Player response identity mismatch')
            await store.record(payload, clan_tag)
            success += 1
        except asyncio.CancelledError:
            raise
        except Exception:
            failure += 1
            # Never log raw upstream URLs, exceptions or credential material.
            log.warning('Player activity read failed')
    return {'success': success, 'failure': failure}


async def run(mongo, client):
    client = PacedOfficialClient(client)
    store = PlayerActivityStore(mongo)
    indexes_ready = False
    seed_task = None
    history_task = None
    try:
        while True:
            started = time.monotonic()
            try:
                if not indexes_ready:
                    await store.ensure_indexes()
                    indexes_ready = True
                sweep = await family_members(mongo, client)
                members = sweep.members
                if sweep.complete:
                    await store.reconcile_membership(members)
                counts = await poll_hour(store, members, client.get_player,
                                         duration=max(1, 3600 - (time.monotonic() - started)))
                await capture_raids(store, client, sweep.clan_tags)
                if (seed_task is None or (seed_task.done() and not seed_task.cancelled()
                                           and seed_task.exception() is None
                                           and (seed_task.result().get('pending', 0) or seed_task.result().get('retryable', 0)))):
                    seed_task = asyncio.create_task(seed_from_clashking(store), name='player-activity-seed')
                elif seed_task.done() and not seed_task.cancelled() and seed_task.exception():
                    log.warning('Player activity seed state unavailable')
                if history_task is None or (history_task.done() and not history_task.cancelled()
                                             and history_task.exception() is None and history_task.result().get('retryable')):
                    from utils.player_activity_history import backfill_recent_wars
                    history_task = asyncio.create_task(backfill_recent_wars(mongo), name='player-activity-history')
                elif history_task.done() and not history_task.cancelled() and history_task.exception():
                    log.warning('Player activity history state unavailable')
                log.info('Player activity hourly sweep: members=%d success=%d failure=%d',
                         len(members), counts['success'], counts['failure'])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Player activity family sweep unavailable')
            await asyncio.sleep(max(1, 3600 - (time.monotonic() - started)))

    finally:
        if history_task is not None:
            history_task.cancel()
            await asyncio.gather(history_task, return_exceptions=True)
        if seed_task is not None:
            seed_task.cancel()
            await asyncio.gather(seed_task, return_exceptions=True)
