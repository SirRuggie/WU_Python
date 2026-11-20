"""Authenticated public game search; private family rows never enter public cache.

One process-local owner manages public-result TTL/coalescing and per-session
request quotas. No store writes, account grants or provider mutations.
"""
import asyncio
from collections import OrderedDict, deque
from copy import deepcopy
import time
from urllib.parse import urlsplit
from aiohttp import web
from .providers import ProviderUnavailable, tag

UNAVAILABLE = 'Clash data is unavailable. Try again.'
RATE_ERROR = 'Too many searches. Wait a minute.'


def normalized(value):
    return ' '.join(value.split()).casefold()


def search_tag(value):
    try:
        result = tag(value)
        return result if 3 <= len(result) - 1 <= 12 else None
    except ValueError:
        return None


def badge(value):
    if not isinstance(value, str) or len(value)>2048:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme == 'https' and parsed.hostname == 'api-assets.clashofclans.com'
                and not parsed.port and not parsed.username and not parsed.password
                and parsed.path.startswith('/badges/') and not parsed.query and not parsed.fragment):
            return value
    except ValueError:
        pass
    return None


def public_row(kind, raw):
    if not isinstance(raw, dict) or not isinstance(raw.get('name'), str) or not 1 <= len(raw['name'].strip()) <= 100:
        raise ProviderUnavailable('Invalid public search result')
    row = {'kind': kind, 'tag': tag(raw.get('tag')), 'name': raw['name'], 'source': 'clash'}
    if kind == 'player':
        th = raw.get('town_hall')
        if th is not None:
            if type(th) is not int or not 1 <= th <= 99:
                raise ProviderUnavailable('Invalid public Town Hall')
            row['town_hall'] = th
        if isinstance(raw.get('current_clan_name'), str):
            row['clan_name'] = raw['current_clan_name']
        if raw.get('current_clan_tag'):
            row['clan_tag'] = tag(raw['current_clan_tag'])
        if type(raw.get('trophies')) is int and raw['trophies'] >= 0:
            row['trophies'] = raw['trophies']
    else:
        for name, low, high in (('level', 1, 100), ('members', 0, 50)):
            if name in raw:
                if type(raw[name]) is not int or not low <= raw[name] <= high:
                    raise ProviderUnavailable('Invalid public clan details')
                row[name] = raw[name]
        row['badge_url'] = badge(raw.get('badge_url'))
        league = raw.get('war_league', raw.get('cwl_league'))
        if isinstance(league, str):
            row['war_league'] = league
        if type(raw.get('public_war_log')) is bool:
            row['public_war_log'] = raw['public_war_log']
    return row


class SearchState:
    """Only sanitized PUBLIC rows are shared across sessions; quotas are private."""
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.cache = OrderedDict()
        self.inflight = {}
        self.buckets = OrderedDict()

    def claim(self, session_key):
        now = self.clock()
        while self.buckets and next(iter(self.buckets.values()))[-1] <= now - 3600:
            self.buckets.popitem(last=False)
        bucket = self.buckets.get(session_key)
        if bucket is None:
            if len(self.buckets) >= 10000:
                raise web.HTTPTooManyRequests(text=RATE_ERROR)
            bucket = deque()
            self.buckets[session_key] = bucket
        while bucket and bucket[0] <= now - 3600:
            bucket.popleft()
        if sum(stamp > now - 60 for stamp in bucket) >= 20 or len(bucket) >= 200:
            raise web.HTTPTooManyRequests(text=RATE_ERROR)
        bucket.append(now)
        self.buckets.move_to_end(session_key)

    async def public(self, key, load):
        now = self.clock()
        for old, (expires, _) in list(self.cache.items()):
            if expires <= now:
                self.cache.pop(old, None)
        cached = self.cache.get(key)
        if cached is not None:
            self.cache.move_to_end(key)
            return deepcopy(cached[1])
        task = self.inflight.get(key)
        if task is None:
            if len(self.inflight) >= 500:
                raise ProviderUnavailable('Public search busy')
            async def fill():
                value = await load()
                # Upstream failures are not cached as if they were empty results.
                if not value.get('errors'):
                    self.cache[key] = (self.clock() + 60, deepcopy(value))
                    while len(self.cache) > 500:
                        self.cache.popitem(last=False)
                return value
            task = asyncio.create_task(fill())
            self.inflight[key] = task
            def done(finished):
                if self.inflight.get(key) is finished:
                    self.inflight.pop(key, None)
                if not finished.cancelled():
                    finished.exception()
            task.add_done_callback(done)
        return deepcopy(await asyncio.shield(task))


async def lifecycle(app):
    app['game_search'] = SearchState()
    yield
    tasks = list(app['game_search'].inflight.values())
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


def authenticated(request):
    from .app import _require
    session = _require(request)
    state = request.app['game_search']
    state.claim(session['token_hash'])
    return session, state


async def upstream(provider, query, value):
    if value:
        calls = [('player', provider.player(value)), ('clan', provider.clan(value))]
        outputs = await asyncio.gather(*(call for _, call in calls), return_exceptions=True)
        results, errors = [], []
        for (kind, _), raw in zip(calls, outputs):
            if isinstance(raw, Exception):
                if getattr(raw, 'status_code', None) != 404:
                    errors.append(UNAVAILABLE)
                continue
            try:
                row = public_row(kind, raw)
                if row['tag'] != value:
                    raise ProviderUnavailable('Mismatched public result')
                results.append(row)
            except (ProviderUnavailable, ValueError, TypeError, TimeoutError):
                errors.append(UNAVAILABLE)
        return {'results': results, **({'errors': [UNAVAILABLE]} if errors else {})}
    if len(query) < 3:
        return {'results': []}
    try:
        raw = await provider.search_clans(query, limit=10)
        if not isinstance(raw, list) or len(raw) > 10:
            raise ProviderUnavailable('Invalid public clan search')
        return {'results': [public_row('clan', row) for row in raw]}
    except (ProviderUnavailable, ValueError, TypeError, TimeoutError):
        return {'results': [], 'errors': [UNAVAILABLE]}


async def search(request):
    _, state = authenticated(request)
    query = request.query.get('q', '').strip()
    if not query:
        raise web.HTTPBadRequest(text='Type at least 1 character.')
    if len(query) > 40:
        raise web.HTTPBadRequest(text='Search text is too long.')
    value = search_tag(query)
    try:
        public = await state.public(('search', value or normalized(query)),
                                    lambda: upstream(request.app['providers'], normalized(query), value))
    except ProviderUnavailable:
        public = {'results': [], 'errors': [UNAVAILABLE]}
    return web.json_response(public)


async def details(request):
    _, state = authenticated(request)
    kind = request.query.get('kind')
    if kind not in ('player', 'clan'):
        raise web.HTTPBadRequest(text='Select a player or clan.')
    try:
        value = tag(request.query.get('tag'))
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid player or clan tag.') from None
    async def load():
        raw = await getattr(request.app['providers'], kind)(value)
        row = public_row(kind, raw)
        if row['tag'] != value:
            raise ProviderUnavailable('Mismatched public details')
        return {'result': row}
    try:
        result = await state.public(('details', kind, value), load)
    except (ProviderUnavailable, ValueError, TypeError, TimeoutError) as exc:
        if getattr(exc, 'status_code', None) == 404:
            raise web.HTTPNotFound(text='Player or clan not found.') from None
        raise web.HTTPServiceUnavailable(text=UNAVAILABLE) from None
    return web.json_response(result['result'])


routes = [web.get('/api/cwl/search', search), web.get('/api/cwl/search/details', details)]
