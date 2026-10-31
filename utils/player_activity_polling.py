"""Hourly player polling, spread evenly; failed reads never become observations."""
import asyncio
import logging
import time

from utils.player_activity_store import PlayerActivityStore
from utils.player_activity_raids import capture_raids

log = logging.getLogger(__name__)


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


async def poll_hour(store, members, fetch_player, *, sleep=asyncio.sleep, clock=time.monotonic):
    start = clock()
    count = len(members)
    success = failure = 0
    previous_start = start - 1
    for index, (player_tag, clan_tag) in enumerate(sorted(members.items())):
        await sleep(max(0, max(start + index * 3600 / max(count, 1), previous_start + 1) - clock()))
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
    store = PlayerActivityStore(mongo)
    await store.ensure_indexes()
    while True:
        started = time.monotonic()
        try:
            members = await family_members(mongo, client)
            await store.reconcile_membership(members)
            await capture_raids(store, client, members.values())
            counts = await poll_hour(store, members, client.get_player)
            log.info('Player activity hourly sweep: members=%d success=%d failure=%d',
                     len(members), counts['success'], counts['failure'])
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning('Player activity family sweep unavailable')
        await asyncio.sleep(max(1, 3600 - (time.monotonic() - started)))
