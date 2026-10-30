"""Durable, per-clan health for the automatic strike war monitor."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

from pymongo.errors import DuplicateKeyError

from utils.strike_store import tag, utc, war_key

RECENT = timedelta(minutes=25)
ERROR_LIMIT = 5
WAR_STALE = timedelta(days=3)
FINAL_GRACE = timedelta(seconds=60)


def safe_error(error: Exception | str) -> str:
    """Do not persist upstream exception bodies, URLs, or credentials."""
    if isinstance(error, str):
        return error if error in {'War source unavailable', 'Clan roster unavailable',
                                  'Account links unavailable', 'War processing failed',
                                  'Incomplete war data', 'Unresolved accounts',
                                  'War log private', 'Clash API key/IP rejected'} else 'Tracking check failed'
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

    @staticmethod
    def snapshot_key(guild_id: int, war: dict) -> str:
        return f'{int(guild_id)}:{war_key(war)}'

    async def snapshot(self, guild_id: int, war: dict):
        return await self.mongo.strike_war_snapshots.find_one(
            {'_id': self.snapshot_key(guild_id, war)})

    async def ensure_indexes(self):
        await self.mongo.strike_war_snapshots.create_index(
            [('guild_id', 1), ('clan_tag', 1), ('end_time', -1)],
            name='strike_official_clan_wars')
        await self.mongo.strike_war_snapshots.create_index(
            [('status', 1), ('next_check_at', 1)], name='strike_official_due')

    async def observe(self, guild_id: int, war: dict, *, now=None):
        """Persist an official observation before any strike processing."""
        now = utc(now or datetime.now(timezone.utc))
        key = self.snapshot_key(guild_id, war)
        existing = await self.mongo.strike_war_snapshots.find_one({'_id': key})
        if existing and existing.get('status') in ('finalized', 'incomplete', 'abandoned'):
            return existing
        active = war['state'] in ('preparation', 'inWar')
        ended = utc(war['end_time'])
        attempts = (int(existing.get('final_check_attempts') or 0) + 1
                    if existing and now >= ended else 0)
        next_check = (ended + FINAL_GRACE if now < ended else
                      now + timedelta(seconds=min(900, 60 * 2 ** min(attempts, 4))))
        fields = {'guild_id': int(guild_id), 'clan_tag': war['clan_tag'],
                  'war_key': war_key(war), 'war': war, 'end_time': war['end_time'],
                  'updated_at': now, 'status': 'observing',
                  'next_check_at': next_check,
                  'final_check_attempts': attempts}
        if existing is None:
            try:
                await self.mongo.strike_war_snapshots.insert_one(
                    {'_id': key, 'first_seen_at': now, 'seen_active': active, **fields})
            except DuplicateKeyError:
                pass
        else:
            await self.mongo.strike_war_snapshots.update_one(
                {'_id': key, 'status': 'observing'},
                {'$set': {**fields, 'seen_active': bool(existing.get('seen_active')) or active}})
        return await self.mongo.strike_war_snapshots.find_one({'_id': key})

    async def finalized(self, guild_id: int, war: dict, *, now=None):
        now = utc(now or datetime.now(timezone.utc))
        await self.mongo.strike_war_snapshots.update_one(
            {'_id': self.snapshot_key(guild_id, war), 'status': 'observing'},
            {'$set': {'war': war, 'status': 'finalized', 'finalized_at': now,
                      'next_check_at': None, 'updated_at': now}})

    async def incomplete(self, guild_id: int, war: dict, reason: str, *, now=None):
        now = utc(now or datetime.now(timezone.utc))
        await self.mongo.strike_war_snapshots.update_one(
            {'_id': self.snapshot_key(guild_id, war), 'status': 'observing'},
            {'$set': {'war': war, 'status': 'incomplete', 'incomplete_at': now,
                      'incomplete_reason': reason, 'next_check_at': None,
                      'updated_at': now}})

    async def abandon_older(self, guild_id: int, clan_tag: str, current_keys=(), *, now=None):
        now = utc(now or datetime.now(timezone.utc))
        rows = await self.mongo.strike_war_snapshots.find(
            {'guild_id': int(guild_id), 'clan_tag': tag(clan_tag),
             'status': 'observing'}).to_list(length=None)
        count = 0
        for row in rows:
            if (row['_id'] not in current_keys and utc(row['end_time']) <= now
                    and (row['war'].get('state') != 'warEnded'
                         or not row['war'].get('complete'))):
                await self.incomplete(guild_id, row['war'],
                                      'War ended before final check: review in Find war', now=now)
                count += 1
        return count

    async def abandon_untracked(self, guild_id: int, tracked_tags: set[str], *, now=None):
        """Retire open snapshots for clans removed from the tracked roster."""
        now = utc(now or datetime.now(timezone.utc))
        rows = await self.mongo.strike_war_snapshots.find(
            {'guild_id': int(guild_id), 'status': 'observing'}).to_list(length=None)
        removed = set()
        for row in rows:
            if row['clan_tag'] in tracked_tags:
                continue
            result = await self.mongo.strike_war_snapshots.update_one(
                {'_id': row['_id'], 'status': 'observing'},
                {'$set': {'status': 'abandoned', 'abandoned_at': now,
                          'next_check_at': None, 'updated_at': now}})
            if result.matched_count:
                removed.add(row['clan_tag'])
        return removed

    async def defer_due(self, guild_id: int, clan_tag: str, *, now=None):
        """Back off source failures without losing the durable final deadline."""
        now = utc(now or datetime.now(timezone.utc))
        await self.mongo.strike_tracking.update_one(
            {'_id': self.key(guild_id, clan_tag)},
            {'$set': {'retry_not_before': now + timedelta(minutes=2)}})
        rows = await self.mongo.strike_war_snapshots.find(
            {'guild_id': int(guild_id), 'clan_tag': tag(clan_tag),
             'status': 'observing'}).to_list(length=None)
        for row in rows:
            due = row.get('next_check_at')
            if due is None or utc(due) > now:
                continue
            attempts = int(row.get('final_check_attempts') or 0) + 1
            await self.mongo.strike_war_snapshots.update_one(
                {'_id': row['_id'], 'status': 'observing'},
                {'$set': {'next_check_at': now + timedelta(
                    seconds=min(900, 60 * 2 ** min(attempts, 4))),
                          'final_check_attempts': attempts}})

    async def pending_finals(self, guild_id: int, clan_tag: str):
        rows = await self.mongo.strike_war_snapshots.find(
            {'guild_id': int(guild_id), 'clan_tag': tag(clan_tag),
             'status': 'observing'}).to_list(length=None)
        return [row for row in rows if row['war'].get('state') == 'warEnded'
                and row['war'].get('complete') and row.get('seen_active')]

    async def due_clans(self, guild_id: int, *, now=None):
        now = utc(now or datetime.now(timezone.utc))
        rows = await self.mongo.strike_war_snapshots.find(
            {'guild_id': int(guild_id), 'status': 'observing',
             'next_check_at': {'$lte': now}}, {'clan_tag': 1}).to_list(length=None)
        return {row['clan_tag'] for row in rows}

    async def incomplete_wars(self, guild_id: int, *, clan_tag=None):
        query = {'guild_id': int(guild_id), 'status': 'incomplete'}
        if clan_tag:
            query['clan_tag'] = tag(clan_tag)
        rows = await self.mongo.strike_war_snapshots.find(query).to_list(length=None)
        return [{'war_key': row['war_key'], 'clan_tag': row['clan_tag'],
                 'clan_name': row['war'].get('clan_name'),
                 'opponent_tag': row['war'].get('opponent_tag'),
                 'opponent_name': row['war'].get('opponent_name'),
                 'war_end': row['end_time'], 'war_type': row['war'].get('type'),
                 'missed_accounts': 0, 'strikes': 0, 'one_missed': 0,
                 'cwl_missed': 0, 'incomplete': True,
                 'review_message': row.get('incomplete_reason') or
                    'War ended before final check: review in Find war',
                 'source_label': 'Clash API'} for row in rows]

    async def begin(self, guild_id: int, clan_tag: str):
        now = datetime.now(timezone.utc)
        token = uuid.uuid4().hex
        await self.mongo.strike_tracking.update_one(
            {'_id': self.key(guild_id, clan_tag)},
            {'$set': {'guild_id': guild_id, 'clan_tag': tag(clan_tag),
                      'last_started_at': now, 'scan_token': token},
             '$setOnInsert': {'error_history': []}}, upsert=True)
        return token

    async def failed_begin(self, guild_id: int, clan_tag: str, attempted_at):
        """Record startup failure without replacing a newer overlapping scan."""
        key = self.key(guild_id, clan_tag)
        previous = await self.mongo.strike_tracking.find_one({'_id': key})
        if previous and previous.get('last_started_at') and utc(previous['last_started_at']) > utc(attempted_at):
            return
        changes = {'guild_id': int(guild_id), 'clan_tag': tag(clan_tag),
                   'last_checked_at': datetime.now(timezone.utc),
                   'last_scan_status': 'needs_review', 'error': 'War processing failed'}
        if previous is None:
            try:
                await self.mongo.strike_tracking.insert_one({'_id': key, **changes})
            except DuplicateKeyError:
                return
        else:
            await self.mongo.strike_tracking.update_one(
                {'_id': key, 'scan_token': previous.get('scan_token')}, {'$set': changes})

    async def finish(self, guild_id: int, clan_tag: str, *, started_at: str,
                     regular_wars=0, cwl_wars=0, deferred_accounts=0,
                     skipped_wars=0, error: str | None = None,
                     current_war_state='unknown', private=False):
        now = datetime.now(timezone.utc)
        partial = bool(error or deferred_accounts or skipped_wars or private or
                       current_war_state == 'unknown')
        status = 'needs_review' if partial else 'healthy'
        update = {'last_checked_at': now, 'last_scan_status': status,
                  'completed_scan_token': started_at,
                  'regular_wars': regular_wars, 'cwl_wars': cwl_wars,
                  'deferred_accounts': deferred_accounts, 'skipped_wars': skipped_wars,
                  'current_war_state': 'private' if private else current_war_state,
                  'error': safe_error(error) if error else ('Unresolved accounts' if deferred_accounts else
                           'Incomplete war data' if skipped_wars else
                           'War log private' if private else None)}
        if not partial:
            update['last_success_at'] = now
        key = self.key(guild_id, clan_tag)
        # The token keeps an older overlapping attempt from replacing a newer check.
        previous = await self.mongo.strike_tracking.find_one({'_id': key}, {'error_history': 1}) or {}
        if partial and update['error']:
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
        rows = await self.mongo.strike_tracking.find(
            {'guild_id': guild_id, 'retry_requested_at': {'$ne': None}},
            {'clan_tag': 1, 'retry_requested_at': 1, 'retry_not_before': 1}).to_list(length=None)
        now = datetime.now(timezone.utc)
        return [row for row in rows if not row.get('retry_not_before')
                or utc(row['retry_not_before']) <= now]

    async def consume_retry(self, guild_id: int, clan_tag: str, requested_at):
        await self.mongo.strike_tracking.update_one(
            {'_id': self.key(guild_id, clan_tag), 'retry_requested_at': requested_at},
            {'$set': {'retry_requested_at': None, 'retry_requested_by': None}})

    async def rows(self, guild_id: int, clans: list[dict]):
        now = datetime.now(timezone.utc)
        saved = await self.mongo.strike_tracking.find({'guild_id': guild_id}).to_list(length=None)
        indexed = {row.get('clan_tag'): row for row in saved}
        snapshots = getattr(self.mongo, 'strike_war_snapshots', None)
        ended = (await snapshots.find(
            {'guild_id': guild_id, 'status': {'$in': ['incomplete', 'finalized']}},
            {'clan_tag': 1, 'end_time': 1, 'status': 1}).to_list(length=None)) if snapshots is not None else []
        latest_ended = {}
        for row in ended:
            prior = latest_ended.get(row['clan_tag'])
            if prior is None or utc(row['end_time']) > utc(prior['end_time']):
                latest_ended[row['clan_tag']] = row
        result = []
        for clan in clans:
            clan_tag = tag(clan['tag'])
            item = indexed.get(clan_tag, {})
            success = item.get('last_success_at')
            checked = item.get('last_checked_at')
            started = item.get('last_started_at')
            unfinished = bool(item.get('scan_token') and
                              item.get('scan_token') != item.get('completed_scan_token'))
            state = item.get('current_war_state') or 'unknown'
            latest = await self.mongo.strike_records.find_one(
                {'guild_id': guild_id, 'clan_tag': clan_tag,
                 'source': {'$in': ['war', 'cwl']}},
                {'occurred_at': 1}, sort=[('occurred_at', -1)])
            recorded = latest.get('occurred_at') if latest else None
            latest_snapshot = latest_ended.get(clan_tag)
            latest_time = max((utc(value) for value in
                               (recorded, latest_snapshot.get('end_time') if latest_snapshot else None)
                               if value is not None), default=None)
            latest_incomplete = bool(latest_snapshot and latest_snapshot['status'] == 'incomplete'
                                     and (recorded is None or
                                          utc(latest_snapshot['end_time']) >= utc(recorded)))
            stale = bool(latest_time and now - latest_time > WAR_STALE)
            check_stale = not checked or now - utc(checked) > RECENT
            failure = item.get('error')
            hard_error = failure and failure not in ('War log private', 'Incomplete war data',
                                                      'Unresolved accounts')
            status = ('error' if hard_error else
                      'behind' if unfinished or check_stale else
                      'private' if state == 'private' else
                      'behind' if state == 'unknown' or
                        latest_incomplete or stale or item.get('skipped_wars') or
                        item.get('deferred_accounts') or
                        (state != 'notInWar' and not recorded) else 'healthy')
            result.append({'clan_tag': clan_tag, 'clan_name': clan.get('name') or clan_tag,
                           'status': status, 'last_started_at': started,
                           'current_war_state': state,
                           'last_checked_at': checked,
                           'last_success_at': success,
                           'latest_recorded_war_at': recorded,
                           'regular_wars': item.get('regular_wars', 0),
                           'cwl_wars': item.get('cwl_wars', 0),
                           'deferred_accounts': item.get('deferred_accounts', 0),
                           'skipped_wars': item.get('skipped_wars', 0),
                           'error': item.get('error'),
                           'error_history': list(item.get('error_history') or [])[-ERROR_LIMIT:],
                           'retry_pending': bool(item.get('retry_requested_at')),
                           'retry_requested_at': item.get('retry_requested_at')})
        return result
