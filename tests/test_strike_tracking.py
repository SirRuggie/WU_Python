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
        await tracking.finish(1, '#P2Y', started_at=token, regular_wars=2,
                              current_war_state='notInWar')
        first = collection.rows[tracking.key(1, '#P2Y')]['last_success_at']
        token = await tracking.begin(1, '#P2Y')
        await tracking.finish(1, '#P2Y', started_at=token,
                              error='https://secret.invalid?token=private')
        row = collection.rows[tracking.key(1, '#P2Y')]
        assert row['last_success_at'] == first
        assert row['error'] == 'Tracking check failed'
        assert len(row['error_history']) == 1
        assert (await tracking.rows(1, [{'tag': '#P2Y', 'name': 'Clan'}]))[0]['status'] == 'error'
    asyncio.run(run())


def test_unfinished_or_stale_check_cannot_be_healthy():
    async def run():
        tracking, collection = service()
        first = await tracking.begin(1, '#P2Y')
        await tracking.finish(1, '#P2Y', started_at=first, current_war_state='notInWar')
        second = await tracking.begin(1, '#P2Y')
        rows = await tracking.rows(1, [{'tag': '#P2Y'}])
        assert rows[0]['status'] == 'behind'
        await tracking.finish(1, '#P2Y', started_at=first, error='Tracking check failed')
        assert collection.rows[tracking.key(1, '#P2Y')]['completed_scan_token'] == first
        await tracking.finish(1, '#P2Y', started_at=second, current_war_state='notInWar')
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
        assert row['status'] == 'behind'
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


def test_expired_incomplete_is_quarantined_without_a_past_ttl_and_resolution_is_audited():
    import asyncio
    from datetime import datetime, timedelta, timezone
    from tests.test_strike_streaks import setup, war, GUILD
    from utils.strike_store import war_key, StrikeConflict
    async def run():
        db, ledger=setup(); tracking=StrikeTracking(db)
        now=datetime.now(timezone.utc)
        old={**war(1),'end_time':now-timedelta(days=100),'state':'inWar'}
        await tracking.observe(GUILD,old,now=now-timedelta(days=101))
        await tracking.incomplete(GUILD,old,'Missing final data',now=now)
        row=await db.strike_war_snapshots.find_one({'war_key':war_key(old)})
        assert row['manual_review_required'] and 'purge_after' not in row
        with __import__('pytest').raises(StrikeConflict):
            await tracking.resolve_review(GUILD+1,row['war_key'],row['review_revision'],'Wrong guild',123,now=now)
        with __import__('pytest').raises(StrikeConflict):
            await tracking.resolve_review(GUILD,row['war_key'],row['review_revision']+1,'Stale revision',123,now=now)
        receipt=await tracking.resolve_review(GUILD,row['war_key'],row['review_revision'],'Reviewed old war',123,now=now)
        saved=await db.strike_war_snapshots.find_one({'war_key':row['war_key']})
        assert saved['status']=='resolved' and not saved['manual_review_required']
        assert saved['purge_after']==now+timedelta(days=30) and saved['review_resolution']==receipt
        assert receipt['reason']=='Reviewed old war' and receipt['actor_id']==123
        assert not await tracking.incomplete_wars(GUILD)
        from extensions.commands.strikes import _finish_official_war
        assert await _finish_official_war(tracking,ledger,GUILD,{**old,'state':'warEnded'}) == (0,0,0,0)
    asyncio.run(run())


def test_observe_and_quarantine_remove_stale_purge_dates():
    from tests.test_strike_streaks import setup, war, GUILD
    async def run():
        db, ledger=setup();tracking=StrikeTracking(db);sample=war(1)
        await tracking.observe(GUILD,sample)
        key=tracking.snapshot_key(GUILD,sample)
        await db.strike_war_snapshots.update_one({'_id':key},{'$set':{'purge_after':datetime.now(timezone.utc)}})
        await tracking.observe(GUILD,sample)
        assert 'purge_after' not in (await db.strike_war_snapshots.find_one({'_id':key}))
        await db.strike_war_snapshots.update_one({'_id':key},{'$set':{'purge_after':datetime.now(timezone.utc)}})
        await tracking.quarantine_old(GUILD,sample)
        assert 'purge_after' not in (await db.strike_war_snapshots.find_one({'_id':key}))
    asyncio.run(run())


def test_review_resolution_requires_an_actual_review_hold():
    from tests.test_strike_streaks import setup, war, GUILD
    from utils.strike_store import StrikeConflict
    async def run():
        db, _ = setup()
        tracking = StrikeTracking(db)
        sample = war(1)
        await tracking.observe(GUILD, sample)
        row = await db.strike_war_snapshots.find_one({'_id': tracking.snapshot_key(GUILD, sample)})
        row['review_revision'] = 1
        before = __import__('copy').deepcopy(row)
        with __import__('pytest').raises(StrikeConflict):
            await tracking.resolve_review(GUILD, row['war_key'], 1, 'No hold exists', 123)
        assert row == before
    asyncio.run(run())
