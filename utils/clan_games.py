"""Read-only monthly Clan Games scores. No player history or database writes."""
import asyncio
import json
import re
from urllib.parse import quote

from utils.clashperk_links import BASE_URL, get_access_token

TAG_RE = re.compile(r'^#[0289PYLQGRJCUV]{3,15}$')
MAX_RESPONSE_BYTES = 512 * 1024


def valid_tag(value):
    return isinstance(value, str) and TAG_RE.fullmatch(value.upper()) is not None


async def _body(response):
    if response.content_type != 'application/json':
        raise ValueError('ClashPerk returned an invalid response')
    raw = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        raw.extend(chunk)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError('ClashPerk response too large')
    return json.loads(raw)


def scores(payload, season):
    """Validate the explicit event month; absent/conflicting players stay unknown."""
    if not isinstance(payload, dict) or payload.get('season') != season:
        raise ValueError('ClashPerk returned a different season')
    members = payload.get('members')
    if not isinstance(members, list) or len(members) > 1000:
        raise ValueError('ClashPerk returned invalid members')
    result = {}
    for member in members:
        if not isinstance(member, dict) or not valid_tag(member.get('tag')):
            continue
        tag, points = member['tag'].upper(), member.get('points')
        if type(points) is not int or not 0 <= points <= 1_000_000:
            points = None
        if tag in result and result[tag] != points:
            result[tag] = None
        else:
            result.setdefault(tag, points)
    return result


async def fetch_clan_scores(session, clan_tag, season, semaphore):
    if not valid_tag(clan_tag) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', season):
        raise ValueError('Invalid clan or event month')
    async with semaphore:
        # Includes waiting for shared authentication; never retry a game action.
        async with asyncio.timeout(8):
            token = await get_access_token(session)
            if not token:
                raise ValueError('ClashPerk access unavailable')
            for attempt in range(2):
                url = BASE_URL + '/clans/' + quote(clan_tag.upper(), safe='') + '/clan-games'
                async with session.get(url, params={'season': season},
                                       headers={'Authorization': 'Bearer ' + token},
                                       allow_redirects=False) as response:
                    if response.status == 401 and attempt == 0:
                        token = await get_access_token(session, rejected=token)
                        if not token:
                            raise ValueError('ClashPerk access unavailable')
                        continue
                    if response.status != 200:
                        raise ValueError('ClashPerk scores unavailable')
                    return scores(await _body(response), season)
    raise ValueError('ClashPerk scores unavailable')
