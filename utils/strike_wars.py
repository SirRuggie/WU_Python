"""Read saved ClashKing wars and accept only complete ended regular-war rosters.

The public previous-war endpoint is a best-effort source. Its available depth is
measured for each clan; the importer never claims a full 60 days without rows.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import aiohttp

from utils.strike_store import tag, stamp, validate_war

BASE = 'https://api.clashk.ing'
TIMEOUT = aiohttp.ClientTimeout(total=25)


def _date(value):
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000 if value > 10**11 else value, timezone.utc)
    if isinstance(value, str) and len(value) == 20 and value[8] == 'T' and value.endswith('Z'):
        return datetime.strptime(value, '%Y%m%dT%H%M%S.000Z').replace(tzinfo=timezone.utc)
    return stamp(value)


def _objects(payload) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ('wars', 'items', 'data', 'results'):
            if key in payload:
                return _objects(payload[key])
        if 'clan' in payload and 'opponent' in payload:
            return [payload]
    return []


def normalize(raw: dict, clan_tag: str, *, now=None) -> dict:
    """Normalize one saved war; reject missing state, roster, or attack limit."""
    wanted = tag(clan_tag)
    sides = [raw.get('clan'), raw.get('opponent')]
    our = next((side for side in sides if isinstance(side, dict) and tag(side.get('tag', '')) == wanted), None)
    other = next((side for side in sides if isinstance(side, dict) and side is not our), None)
    if our is None or other is None:
        raise ValueError('Selected clan is missing from war.')
    state = raw.get('state')
    kind = raw.get('type', raw.get('warType'))
    if kind not in (None, 'regular', 'random'):
        raise ValueError('Not a regular war.')
    if state not in ('warEnded', 'ended'):
        raise ValueError('War is not ended.')
    team_size = raw.get('teamSize')
    roster = our.get('members')
    opposing_roster = other.get('members')
    if (not isinstance(team_size, int) or not isinstance(roster, list)
            or not isinstance(opposing_roster, list) or len(roster) != team_size
            or len(opposing_roster) != team_size):
        raise ValueError('Full war roster is unavailable.')
    members = []
    for member in roster:
        if not isinstance(member, dict) or 'tag' not in member:
            raise ValueError('War member is incomplete.')
        attacks = member.get('attacks', [])
        # CoC omits `attacks` for members with zero hits. A present invalid
        # value is different and cannot be silently counted as zero.
        if not isinstance(attacks, list):
            raise ValueError('War attack list is incomplete.')
        members.append({'tag': tag(member['tag']), 'name': member.get('name'),
                        'attacks': len(attacks)})
    if isinstance(our.get('attacks'), int) and our['attacks'] != sum(row['attacks'] for row in members):
        raise ValueError('War attack totals do not match roster.')
    war = {'clan_tag': wanted, 'clan_name': our.get('name'),
           'opponent_tag': tag(other['tag']), 'opponent_name': other.get('name'),
           'end_time': _date(raw['endTime']), 'type': 'regular',
           'state': 'warEnded', 'attacks_per_member': raw.get('attacksPerMember'),
           'complete': True, 'members': members}
    validate_war(war, now=now)
    return war


def normalize_cwl(raw: dict, clan_tag: str, *, now=None) -> dict:
    """Accept a tagged, complete, ended one-attack league war for history only."""
    wanted = tag(clan_tag)
    war_tag = tag(raw.get('tag'))
    if raw.get('attacksPerMember') not in (None, 1):
        raise ValueError('Tagged war has an incompatible attack limit.')
    kind = raw.get('type', raw.get('warType'))
    if kind not in (None, 'cwl', 'league'):
        raise ValueError('Tagged war is not CWL.')
    if raw.get('state') not in ('warEnded', 'ended'):
        raise ValueError('CWL war is not ended.')
    sides = [raw.get('clan'), raw.get('opponent')]
    our = next((side for side in sides if isinstance(side, dict)
                and tag(side.get('tag', '')) == wanted), None)
    other = next((side for side in sides if isinstance(side, dict) and side is not our), None)
    team_size = raw.get('teamSize')
    if (our is None or other is None or not isinstance(team_size, int)
            or isinstance(team_size, bool) or not 1 <= team_size <= 50
            or not isinstance(our.get('members'), list)
            or not isinstance(other.get('members'), list)
            or len(our['members']) != team_size or len(other['members']) != team_size):
        raise ValueError('Full CWL war roster is unavailable.')
    for side in (our, other):
        total = 0
        seen = set()
        for member in side['members']:
            if not isinstance(member, dict):
                raise ValueError('CWL war member is incomplete.')
            player = tag(member.get('tag'))
            if player in seen:
                raise ValueError('CWL war roster has duplicate accounts.')
            seen.add(player)
            attacks = member.get('attacks', [])
            if not isinstance(attacks, list) or len(attacks) > 1:
                raise ValueError('CWL attack list is incomplete or exceeds one attack.')
            total += len(attacks)
        if isinstance(side.get('attacks'), int) and side['attacks'] != total:
            raise ValueError('CWL attack totals do not match roster.')
    war = {'clan_tag': wanted, 'clan_name': our.get('name'),
           'opponent_tag': tag(other['tag']), 'opponent_name': other.get('name'),
           'war_tag': war_tag, 'end_time': _date(raw['endTime']),
           'type': 'cwl', 'state': 'warEnded', 'attacks_per_member': 1,
           'complete': True,
           'members': [{'tag': tag(member['tag']), 'name': member.get('name'),
                        'attacks': len(member.get('attacks', []))}
                       for member in our['members']]}
    from utils.strike_store import validate_cwl_war
    validate_cwl_war(war, now=now)
    return war


async def fetch_saved_wars(clan_tag: str, *, days=60, session=None) -> dict:
    """Return every available validated war plus coverage and skipped reasons."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=TIMEOUT)
    try:
        url = f'{BASE}/war/{quote(tag(clan_tag), safe="")}/previous'
        async with session.get(url, allow_redirects=False) as response:
            if response.status != 200:
                raise RuntimeError(f'ClashKing war history returned {response.status}.')
            payload = await response.json()
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=days)
        wars, skipped = [], []
        oldest = None
        for raw in _objects(payload):
            try:
                war = normalize(raw, clan_tag, now=now)
                oldest = min(oldest, war['end_time']) if oldest else war['end_time']
                if war['end_time'] >= cutoff:
                    wars.append(war)
            except (ValueError, KeyError, TypeError) as error:
                skipped.append(str(error))
        unique = {f"{item['clan_tag']}:{item['opponent_tag']}:{item['end_time'].isoformat()}": item for item in wars}
        return {'clan_tag': tag(clan_tag), 'wars': list(unique.values()),
                'oldest_available': oldest, 'requested_since': cutoff,
                'skipped': skipped, 'complete_90_days': bool(oldest and oldest <= cutoff)}
    finally:
        if own_session:
            await session.close()


async def fetch_family_wars(mongo, *, days=60, limit=8) -> dict:
    clans = await mongo.clans.find({'tag': {'$type': 'string'}}, {'tag': 1, 'name': 1}).to_list(length=None)
    semaphore = asyncio.Semaphore(limit)
    async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
        async def one(clan):
            async with semaphore:
                try:
                    return await fetch_saved_wars(clan['tag'], days=days, session=session)
                except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError, ValueError) as error:
                    return {'clan_tag': clan.get('tag'), 'wars': [], 'error': str(error),
                            'complete_90_days': False}
        coverage = await asyncio.gather(*(one(clan) for clan in clans))
    return {'wars': [war for item in coverage for war in item['wars']], 'coverage': coverage}


async def fetch_history_report(clan_tag: str, days: int = 60, *, session=None) -> dict:
    """Read date-filtered stored wars, reporting gaps and skipped data."""
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession(timeout=TIMEOUT)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)
    found, cwl_found, skipped = {}, {}, []
    oldest_raw = None
    source_count = 0
    try:
        before = now
        endpoint = 'v2'
        for _page in range(30):
            if endpoint == 'v2':
                url = f'{BASE}/v2/clan/{quote(tag(clan_tag), safe="")}/wars'
                params = {'time[after]': cutoff.isoformat(),
                          'time[before]': before.isoformat(), 'limit': 100}
            else:
                url = f'{BASE}/war/{quote(tag(clan_tag), safe="")}/previous'
                params = {'timestamp_start': str(int(cutoff.timestamp())),
                          'timestamp_end': str(int(before.timestamp())), 'limit': 100}
            async with session.get(url, params=params, allow_redirects=False) as response:
                if response.status != 200:
                    if endpoint == 'v2':
                        endpoint = 'legacy'
                        continue
                    raise RuntimeError(f'ClashKing stored wars returned {response.status}.')
                payload = await response.json()
            raw_wars = _objects(payload)
            source_count += len(raw_wars)
            if not raw_wars:
                break
            page_oldest = None
            for raw in raw_wars:
                try:
                    raw_end = _date(raw['endTime'])
                    page_oldest = min(page_oldest, raw_end) if page_oldest else raw_end
                    oldest_raw = min(oldest_raw, raw_end) if oldest_raw else raw_end
                    if raw_end < cutoff:
                        continue
                    if raw.get('tag'):
                        war = normalize_cwl(raw, clan_tag, now=now)
                        cwl_found[f"{war['clan_tag']}:{war['war_tag']}:{war['end_time'].isoformat()}"] = war
                    else:
                        war = normalize(raw, clan_tag, now=now)
                        found[f"{war['clan_tag']}:{war['opponent_tag']}:{war['end_time'].isoformat()}"] = war
                except (ValueError, KeyError, TypeError) as error:
                    skipped.append({'end_time': str(raw.get('endTime', 'unknown')),
                                    'reason': str(error)})
                    continue
            if len(raw_wars) < 100 or page_oldest is None or page_oldest >= before:
                break
            before = page_oldest - timedelta(seconds=1 if endpoint == 'legacy' else 0,
                                              microseconds=0 if endpoint == 'legacy' else 1)
            if before < cutoff:
                break
        return {'clan_tag': tag(clan_tag),
                'wars': sorted(found.values(), key=lambda row: row['end_time'], reverse=True),
                'cwl_wars': sorted(cwl_found.values(), key=lambda row: row['end_time'], reverse=True),
                'skipped': skipped, 'oldest_available': oldest_raw,
                'requested_since': cutoff,
                'complete_90_days': bool(oldest_raw and oldest_raw <= cutoff),
                'source_count': source_count, 'source': endpoint}
    finally:
        if own_session:
            await session.close()


async def fetch_history(clan_tag: str, days: int = 60, *, session=None) -> list[dict]:
    return (await fetch_history_report(clan_tag, days, session=session))['wars']
