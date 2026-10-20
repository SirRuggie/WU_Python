"""Durable, per-clan health for the automatic strike war monitor."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from utils.strike_store import tag, utc

RECENT = timedelta(minutes=25)
ERROR_LIMIT = 5


def safe_error(error: Exception | str) -> str:
    """Do not persist upstream exception bodies, URLs, or credentials."""
    if isinstance(error, str):
        return error if error in {'War source unavailable', 'Clan roster unavailable',
                                  'Account links unavailable', 'War processing failed',
                                  'Incomplete war data', 'Unresolved accounts'} else 'Tracking check failed'
    name = type(error).__name__
    if name in {'ClientError', 'ClientConnectorError', 'ClientResponseError', 'TimeoutError'}:
        return 'War source unavailable'
    if name in {'ProviderUnavailable'}:
        return 'Account links unavailable'
    return 'Tracking check failed'


class StrikeTracking:
    def __init__(self, mongo):
        self.mongo = mongo

    @staticmethod
    def key(guild_id: int, clan_tag: str) -> str:
        return f'{int(guild_id)}:{tag(clan_tag)}'

    async def begin(self, guild_id: int, clan_tag: str):
        now = datetime.now(timezone.utc)
        token = uuid.uuid4().hex
        await self.mongo.strike_tracking.update_one(
            {'_id': self.key(guild_id, clan_tag)},
            {'$set': {'guild_id': guild_id, 'clan_tag': tag(clan_tag),
                      'last_started_at': now, 'scan_token': token},
             '$setOnInsert': {'error_history': []}}, upsert=True)
        return token

    async def finish(self, guild_id: int, clan_tag: str, *, started_at: str,
                     regular_wars=0, cwl_wars=0, deferred_accounts=0,
                     skipped_wars=0, error: str | None = None):
        now = datetime.now(timezone.utc)
        partial = bool(error or deferred_accounts or skipped_wars)
        status = 'needs_review' if partial else 'healthy'
        update = {'last_checked_at': now, 'last_scan_status': status,
                  'completed_scan_token': started_at,
                  'regular_wars': regular_wars, 'cwl_wars': cwl_wars,
                  'deferred_accounts': deferred_accounts, 'skipped_wars': skipped_wars,
                  'error': safe_error(error) if error else ('Unresolved accounts' if deferred_accounts else
                           'Incomplete war data' if skipped_wars else None)}
        if not partial:
            update['last_success_at'] = now
        key = self.key(guild_id, clan_tag)
        # The token keeps an older overlapping attempt from replacing a newer check.
        previous = await self.mongo.strike_tracking.find_one({'_id': key}, {'error_history': 1}) or {}
        if partial:
            history = list(previous.get('error_history') or [])[-(ERROR_LIMIT - 1):]
            history.append({'at': now, 'error': update['error']})
            update['error_history'] = history
        await self.mongo.strike_tracking.update_one({'_id': key, 'scan_token': started_at}, {'$set': update})

    async def queue_retry(self, guild_id: int, clan_tag: str, actor_id: int):
        key = self.key(guild_id, clan_tag)
        await self.mongo.strike_tracking.update_one(
            {'_id': key}, {'$setOnInsert': {'guild_id': guild_id,
            'clan_tag': tag(clan_tag), 'error_history': []}}, upsert=True)
        now = datetime.now(timezone.utc)
        await self.mongo.strike_tracking.update_one(
            {'_id': key, 'retry_requested_at': None},
            {'$set': {'retry_requested_at': now, 'retry_requested_by': actor_id}})
        return await self.mongo.strike_tracking.find_one({'_id': key})

    async def pending(self, guild_id: int):
        return await self.mongo.strike_tracking.find(
            {'guild_id': guild_id, 'retry_requested_at': {'$ne': None}},
            {'clan_tag': 1, 'retry_requested_at': 1}).to_list(length=None)

    async def consume_retry(self, guild_id: int, clan_tag: str, requested_at):
        await self.mongo.strike_tracking.update_one(
            {'_id': self.key(guild_id, clan_tag), 'retry_requested_at': requested_at},
            {'$set': {'retry_requested_at': None, 'retry_requested_by': None}})

    async def rows(self, guild_id: int, clans: list[dict]):
        now = datetime.now(timezone.utc)
        saved = await self.mongo.strike_tracking.find({'guild_id': guild_id}).to_list(length=None)
        indexed = {row.get('clan_tag'): row for row in saved}
        result = []
        for clan in clans:
            clan_tag = tag(clan['tag'])
            item = indexed.get(clan_tag, {})
            success = item.get('last_success_at')
            checked = item.get('last_checked_at')
            started = item.get('last_started_at')
            unfinished = bool(item.get('scan_token') and
                              item.get('scan_token') != item.get('completed_scan_token'))
            failed = item.get('last_scan_status') in {'needs_review', 'failed'}
            status = ('needs_review' if failed else
                      'delayed' if unfinished or not success or now - utc(success) > RECENT else 'healthy')
            latest = await self.mongo.strike_records.find_one(
                {'guild_id': guild_id, 'clan_tag': clan_tag,
                 'source': {'$in': ['war', 'cwl']}},
                {'occurred_at': 1}, sort=[('occurred_at', -1)])
            result.append({'clan_tag': clan_tag, 'clan_name': clan.get('name') or clan_tag,
                           'status': status, 'last_started_at': started,
                           'last_checked_at': checked,
                           'last_success_at': success,
                           'latest_recorded_war_at': latest.get('occurred_at') if latest else None,
                           'regular_wars': item.get('regular_wars', 0),
                           'cwl_wars': item.get('cwl_wars', 0),
                           'deferred_accounts': item.get('deferred_accounts', 0),
                           'skipped_wars': item.get('skipped_wars', 0),
                           'error': item.get('error'),
                           'error_history': list(item.get('error_history') or [])[-ERROR_LIMIT:],
                           'retry_pending': bool(item.get('retry_requested_at')),
                           'retry_requested_at': item.get('retry_requested_at')})
        return result
