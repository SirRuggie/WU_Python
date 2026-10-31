"""Hourly player polling, spread evenly; failed reads never become observations."""
import asyncio
import logging
import time

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
        return await self.request('get_clan', clan)

    async def get_player(self, player):
        return await self.request('get_player', player)

    async def get_raid_log(self, clan, **kwargs):
        return await self.request('get_raid_log', clan, **kwargs)


async def family_members(mongo, client):
    """Return only a complete roster sweep; any failure prevents departure writes."""
    clans = await mongo.clans.find({'tag': {'$type': 'string'}}, {'tag': 1}).to_list(length=None)
    members = {}
    for row in clans:
        clan = await client.get_clan(row['tag'])
        for player in clan.members:
            members[player.tag] = clan.tag
    return members


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
    try:
        while True:
            started = time.monotonic()
            try:
                if not indexes_ready:
                    await store.ensure_indexes()
                    indexes_ready = True
                members = await family_members(mongo, client)
                await store.reconcile_membership(members)
                await capture_raids(store, client, members.values())
                counts = await poll_hour(store, members, client.get_player,
                                         duration=max(1, 3600 - (time.monotonic() - started)))
                if (seed_task is None or (seed_task.done() and not seed_task.cancelled()
                                           and seed_task.exception() is None
                                           and seed_task.result().get('pending', 0))):
                    seed_task = asyncio.create_task(seed_from_clashking(store), name='player-activity-seed')
                elif seed_task.done() and not seed_task.cancelled() and seed_task.exception():
                    log.warning('Player activity seed state unavailable')
                log.info('Player activity hourly sweep: members=%d success=%d failure=%d',
                         len(members), counts['success'], counts['failure'])
            except asyncio.CancelledError:
                raise
            except Exception:
                log.warning('Player activity family sweep unavailable')
            await asyncio.sleep(max(1, 3600 - (time.monotonic() - started)))

    finally:
        if seed_task is not None:
            seed_task.cancel()
            await asyncio.gather(seed_task, return_exceptions=True)
