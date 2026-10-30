"""Independent tracking-health regressions; no production database access."""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from utils.strike_tracking import StrikeTracking, safe_error


CLAN = '#2UVGQU9'
GUILD = 123


class MemoryCollection:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    @staticmethod
    def matches(row, query):
        for key, wanted in query.items():
            value = row.get(key)
            if isinstance(wanted, dict) and '$ne' in wanted:
                if value == wanted['$ne']:
                    return False
            elif isinstance(wanted, dict) and '$in' in wanted:
                if value not in wanted['$in']:
                    return False
            elif value != wanted:
                return False
        return True

    async def update_one(self, query, update, upsert=False):
        key = query['_id']
        row = self.rows.get(key)
        if row is None:
            if not upsert:
                return
            row = {'_id': key}
            self.rows[key] = row
            row.update(update.get('$setOnInsert', {}))
        if not self.matches(row, query):
            return
        row.update(update.get('$set', {}))

    async def find_one(self, query, projection=None, sort=None):
        rows = [row for row in self.rows.values() if self.matches(row, query)]
        if sort:
            rows.sort(key=lambda row: row.get(sort[0][0]), reverse=sort[0][1] < 0)
        return rows[0] if rows else None

    def find(self, query, projection=None):
        rows = [row for row in self.rows.values() if self.matches(row, query)]
        return SimpleNamespace(to_list=lambda length=None: async_value(rows))


async def async_value(value):
    return value


def test_failure_updates_checked_time_preserves_good_time_and_sanitizes_errors():
    async def run():
        mongo = SimpleNamespace(strike_tracking=MemoryCollection(), strike_records=MemoryCollection())
        tracking = StrikeTracking(mongo)
        first = await tracking.begin(GUILD, CLAN)
        await tracking.finish(GUILD, CLAN, started_at=first, regular_wars=1,
                              current_war_state='notInWar')
        saved = mongo.strike_tracking.rows[tracking.key(GUILD, CLAN)]
        good = saved['last_success_at']
        checked = saved['last_checked_at']
        second = await tracking.begin(GUILD, CLAN)
        await tracking.finish(GUILD, CLAN, started_at=second,
                              error='https://upstream.invalid/?token=SECRET')
        failed = mongo.strike_tracking.rows[tracking.key(GUILD, CLAN)]
        assert failed['last_success_at'] == good
        assert failed['last_checked_at'] >= checked
        assert failed['last_scan_status'] == 'needs_review'
        assert failed['error'] == 'Tracking check failed'
        assert 'SECRET' not in str(failed)
        rows = await tracking.rows(GUILD, [{'tag': CLAN, 'name': 'Our clan'}])
        assert rows[0]['status'] == 'error'
        assert rows[0]['last_success_at'] == good
        assert rows[0]['last_checked_at'] == failed['last_checked_at']
    asyncio.run(run())


def test_stale_scan_token_cannot_overwrite_newer_check():
    async def run():
        mongo = SimpleNamespace(strike_tracking=MemoryCollection(), strike_records=MemoryCollection())
        tracking = StrikeTracking(mongo)
        stale = await tracking.begin(GUILD, CLAN)
        current = await tracking.begin(GUILD, CLAN)
        await tracking.finish(GUILD, CLAN, started_at=stale, error='War source unavailable')
        row = mongo.strike_tracking.rows[tracking.key(GUILD, CLAN)]
        assert row.get('last_checked_at') is None
        await tracking.finish(GUILD, CLAN, started_at=current, regular_wars=2,
                              current_war_state='notInWar')
        assert row['last_scan_status'] == 'healthy'
        assert row['regular_wars'] == 2
    asyncio.run(run())


def test_retry_queue_is_idempotent_and_stale_consume_cannot_clear_new_request():
    async def run():
        mongo = SimpleNamespace(strike_tracking=MemoryCollection(), strike_records=MemoryCollection())
        tracking = StrikeTracking(mongo)
        first = await tracking.queue_retry(GUILD, CLAN, 456)
        queued = first['retry_requested_at']
        second = await tracking.queue_retry(GUILD, CLAN, 789)
        assert second['retry_requested_at'] == queued
        assert second['retry_requested_by'] == 456
        pending = await tracking.pending(GUILD)
        assert len(pending) == 1 and pending[0]['clan_tag'] == CLAN
        await tracking.consume_retry(GUILD, CLAN, queued - timedelta(seconds=1))
        assert (await tracking.pending(GUILD))
        await tracking.consume_retry(GUILD, CLAN, queued)
        assert not (await tracking.pending(GUILD))
    asyncio.run(run())


def test_latest_recorded_war_uses_record_time_not_latest_check():
    async def run():
        recorded = datetime.now(timezone.utc) - timedelta(days=2)
        mongo = SimpleNamespace(
            strike_tracking=MemoryCollection(),
            strike_records=MemoryCollection({'war': {'_id': 'war', 'guild_id': GUILD,
                'clan_tag': CLAN, 'source': 'cwl', 'occurred_at': recorded}}))
        tracking = StrikeTracking(mongo)
        token = await tracking.begin(GUILD, CLAN)
        await tracking.finish(GUILD, CLAN, started_at=token, current_war_state='notInWar')
        row = (await tracking.rows(GUILD, [{'tag': CLAN}]))[0]
        assert row['latest_recorded_war_at'] == recorded
        assert row['last_checked_at'] > recorded
    asyncio.run(run())


def test_error_labels_never_persist_raw_provider_message():
    assert safe_error('database password=SECRET') == 'Tracking check failed'
    assert safe_error(RuntimeError('https://upstream.invalid?token=SECRET')) == 'Tracking check failed'


def test_unfinished_new_scan_cannot_look_healthy_after_restart_or_cancel():
    async def run():
        mongo = SimpleNamespace(strike_tracking=MemoryCollection(), strike_records=MemoryCollection())
        tracking = StrikeTracking(mongo)
        first = await tracking.begin(GUILD, CLAN)
        await tracking.finish(GUILD, CLAN, started_at=first, current_war_state='notInWar')
        healthy = (await tracking.rows(GUILD, [{'tag': CLAN}]))[0]
        assert healthy['status'] == 'healthy'
        good = healthy['last_success_at']
        await tracking.begin(GUILD, CLAN)
        # Simulate process exit or task cancellation before finish().
        unfinished = (await tracking.rows(GUILD, [{'tag': CLAN}]))[0]
        assert unfinished['status'] == 'behind'
        assert unfinished['last_success_at'] == good
    asyncio.run(run())
