import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from utils.strike_tracking import StrikeTracking, safe_error


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return self.rows


class Collection:
    def __init__(self):
        self.rows = {}

    async def update_one(self, query, update, upsert=False):
        key = query['_id']
        row = self.rows.get(key)
        if row is None:
            if not upsert:
                return SimpleNamespace(matched_count=0)
            row = {'_id': key}
            row.update(update.get('$setOnInsert', {}))
            self.rows[key] = row
        for field, expected in query.items():
            if field != '_id' and row.get(field) != expected:
                return SimpleNamespace(matched_count=0)
        row.update(update.get('$set', {}))
        return SimpleNamespace(matched_count=1)

    async def find_one(self, query, projection=None, sort=None):
        if sort:
            return None
        row = self.rows.get(query['_id'])
        return dict(row) if row else None

    def find(self, query, projection=None):
        rows = []
        for row in self.rows.values():
            if row.get('guild_id') != query.get('guild_id'):
                continue
            if 'retry_requested_at' in query and row.get('retry_requested_at') is None:
                continue
            rows.append(dict(row))
        return Cursor(rows)


def service():
    collection = Collection()
    return StrikeTracking(SimpleNamespace(strike_tracking=collection,
                                          strike_records=Collection())), collection


def test_failure_preserves_success_and_never_persists_exception_body():
    async def run():
        tracking, collection = service()
        token = await tracking.begin(1, '#P2Y')
        await tracking.finish(1, '#P2Y', started_at=token, regular_wars=2)
        first = collection.rows[tracking.key(1, '#P2Y')]['last_success_at']
        token = await tracking.begin(1, '#P2Y')
        await tracking.finish(1, '#P2Y', started_at=token,
                              error='https://secret.invalid?token=private')
        row = collection.rows[tracking.key(1, '#P2Y')]
        assert row['last_success_at'] == first
        assert row['error'] == 'Tracking check failed'
        assert len(row['error_history']) == 1
        assert (await tracking.rows(1, [{'tag': '#P2Y', 'name': 'Clan'}]))[0]['status'] == 'needs_review'
    asyncio.run(run())


def test_unfinished_or_stale_check_cannot_be_healthy():
    async def run():
        tracking, collection = service()
        first = await tracking.begin(1, '#P2Y')
        await tracking.finish(1, '#P2Y', started_at=first)
        second = await tracking.begin(1, '#P2Y')
        rows = await tracking.rows(1, [{'tag': '#P2Y'}])
        assert rows[0]['status'] == 'delayed'
        await tracking.finish(1, '#P2Y', started_at=first, error='Tracking check failed')
        assert collection.rows[tracking.key(1, '#P2Y')]['completed_scan_token'] == first
        await tracking.finish(1, '#P2Y', started_at=second)
        assert (await tracking.rows(1, [{'tag': '#P2Y'}]))[0]['status'] == 'healthy'
    asyncio.run(run())


def test_retry_is_durable_deduplicated_and_consumes_only_same_request():
    async def run():
        tracking, collection = service()
        first = await tracking.queue_retry(1, '#P2Y', 101)
        second = await tracking.queue_retry(1, '#P2Y', 202)
        assert first['retry_requested_at'] == second['retry_requested_at']
        assert second['retry_requested_by'] == 101
        assert len(await tracking.pending(1)) == 1
        await tracking.consume_retry(1, '#P2Y', first['retry_requested_at'] - timedelta(seconds=1))
        assert len(await tracking.pending(1)) == 1
        await tracking.consume_retry(1, '#P2Y', first['retry_requested_at'])
        assert await tracking.pending(1) == []
    asyncio.run(run())


def test_history_capped_and_previously_recorded_war_read_from_ledger():
    async def run():
        tracking, collection = service()
        end = datetime.now(timezone.utc) - timedelta(days=4)
        tracking.mongo.strike_records.find_one = lambda *a, **kw: async_result({'occurred_at': end})
        for _ in range(7):
            token = await tracking.begin(1, '#P2Y')
            await tracking.finish(1, '#P2Y', started_at=token, skipped_wars=1)
        row = (await tracking.rows(1, [{'tag': '#P2Y'}]))[0]
        assert row['latest_recorded_war_at'] == end
        assert len(row['error_history']) == 5
        assert row['status'] == 'needs_review'
    asyncio.run(run())


async def async_result(value):
    return value


def test_safe_error_never_echoes_provider_secret():
    assert 'secret' not in safe_error(RuntimeError('secret=123'))


def test_tracking_retry_requires_write_scope_and_registered_clan(monkeypatch):
    from contextlib import asynccontextmanager
    import json
    from cwl_web import strikes as api

    tracking, collection = service()
    async def clan_find(query, projection=None):
        return {'tag': '#P2Y'} if query.get('tag') == '#P2Y' else None
    tracking.mongo.clans = SimpleNamespace(find_one=clan_find)
    requested = []
    async def require(request, scope, write=False):
        requested.append((scope, write))
    async def identity(request):
        return {'user_id': '101'}
    async def parse(request, fields):
        return {'clan_tag': '#P2Y'}
    @asynccontextmanager
    async def mongo(request):
        yield tracking.mongo
    monkeypatch.setattr(api.shared, 'require_manage', require)
    monkeypatch.setattr(api.shared, 'identity', identity)
    monkeypatch.setattr(api.shared, 'mongo', mongo)
    monkeypatch.setattr(api, 'body', parse)
    response = asyncio.run(api.tracking_retry(SimpleNamespace(method='POST')))
    assert response.status == 202
    assert json.loads(response.text)['retry_pending'] is True
    assert requested == [('strikes_add', True)]
    assert len(asyncio.run(tracking.pending(api.GUILD_ID))) == 1
