"""Bounded in-process observations for the clan weight editor.

Roster summaries only peek: opening the directory never starts game reads.
Background capture and explicit member refresh share/coalesce public provider
calls. A failed refresh retains the last valid observation and its timestamp.
"""
import asyncio
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import time
import weakref


class WeightObservations:
    def __init__(self, provider, *, ttl=600, retry_ttl=60, limit=512):
        self.provider = provider
        self.ttl = ttl
        self.retry_ttl = retry_ttl
        self.limit = limit
        self._rows = OrderedDict()
        self._locks = weakref.WeakValueDictionary()
        self._semaphore = asyncio.Semaphore(3)

    def _lock(self, key):
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    def _peek(self, key):
        row = self._rows.get(key)
        if row is None:
            return {'value': None, 'checked_at': None, 'status': 'loading'}
        return {'value': deepcopy(row.get('value')), 'checked_at': row.get('checked_at'),
                'status': ('unavailable' if row.get('value') is None else
                           'stale' if row.get('failed') or row['expires'] <= time.monotonic() else 'current')}

    def roster(self, clan_tag):
        return self._peek(('roster', clan_tag))

    async def _refresh(self, kind, value, *, force=False):
        key = (kind, value)
        requested = time.monotonic()
        async with self._lock(key):
            previous = self._rows.get(key, {})
            if previous.get('attempted', -1) >= requested or (
                    not force and previous.get('expires', 0) > time.monotonic()):
                return self._peek(key)
            try:
                async with self._semaphore:
                    call = self.provider.clan_roster if kind == 'roster' else self.provider.player
                    result = await asyncio.wait_for(call(value), timeout=8)
                if not isinstance(result, dict) or result.get('tag') != value:
                    raise ValueError('Mismatched observation')
                if kind == 'roster':
                    members = result.get('members')
                    if (not isinstance(members, list) or len(members) > 50
                            or any(not isinstance(m, dict) or not isinstance(m.get('tag'), str) for m in members)
                            or len({m['tag'] for m in members}) != len(members)):
                        raise ValueError('Incomplete roster observation')
                elif 'current_clan_tag' not in result:
                    raise ValueError('Unknown player location')
                row = {'value': deepcopy(result), 'checked_at': datetime.now(timezone.utc).isoformat(),
                       'failed': False, 'expires': time.monotonic() + self.ttl}
            except asyncio.CancelledError:
                raise
            except Exception:
                row = {**previous, 'failed': True, 'expires': time.monotonic() + self.retry_ttl}
            row['attempted'] = time.monotonic()
            self._rows[key] = row
            self._rows.move_to_end(key)
            while len(self._rows) > self.limit:
                self._rows.popitem(last=False)
            return self._peek(key)

    async def refresh_roster(self, clan_tag, *, force=False):
        return await self._refresh('roster', clan_tag, force=force)

    async def player(self, player_tag):
        return await self._refresh('player', player_tag)
