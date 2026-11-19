"""Real worker/store with BSON rows and conditional-write race behavior."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from bson import BSON
from bson.int64 import Int64
from pymongo.errors import DuplicateKeyError

from extensions.tasks import war_reminders as worker
from utils import war_reminders as reminders
from utils.war_reminder_health import health
from utils.war_reminder_store import WarReminderStore

FIRST = datetime(2026, 11, 17, tzinfo=timezone.utc)


def bson(value):
    return BSON.encode({'value': value}).decode()['value']


class ConditionalStatus:
    def __init__(self, row):
        self.row = bson(row)
        self.writes = []
        self.before_update = None
        self.duplicate_inserts = 0

    async def find_one(self, query, *projection):
        return deepcopy(self.row)

    async def update_one(self, query, update, *, upsert=False):
        if self.before_update:
            callback, self.before_update = self.before_update, None
            await callback()
        def matches():
            for key, expected in query.items():
                if isinstance(expected, dict) and '$exists' in expected:
                    if (self.row is not None and key in self.row) != expected['$exists']:
                        return False
                elif self.row is None or self.row.get(key) != bson(expected):
                    return False
            return True
        if self.row is not None and not matches():
            if upsert:
                self.duplicate_inserts += 1
                raise DuplicateKeyError('competing clan insert')
            return NS(matched_count=0, upserted_id=None)
        inserted = self.row is None
        self.row = bson({**(self.row or {'_id': query['_id']}), **update['$set']})
        self.writes.append(deepcopy(self.row))
        return NS(matched_count=not inserted, upserted_id=query['_id'] if inserted else None)


def harness(monkeypatch, *, legacy=False, empty=False, same_millisecond=False, long_versions=False):
    old = {**reminders.settings(), '_id': '#P2Y', 'enabled': True,
           'channel_id': '123456789012345678', 'war_started': False, 'version': 1, 'updated_at': FIRST}
    new = {**old, 'version': 2,
           'updated_at': FIRST if same_millisecond else FIRST + timedelta(seconds=1)}
    if long_versions:
        old['version'], new['version'] = bson(Int64(1)), bson(Int64(2))
    row = {'_id': '#P2Y', 'checked_at': FIRST, 'error': None,
           'detail': 'Waiting for an active war', 'war_end': None}
    if not legacy:
        row.update(settings_updated_at=FIRST, settings_version=1)
    collection = ConditionalStatus(None if empty else row)
    store = WarReminderStore.__new__(WarReminderStore)
    store.status = collection
    store.db = NS(clans=NS(find_one=AsyncMock(return_value={'_id': 'clan'})))
    monkeypatch.setattr(worker, 'WarReminderStore', lambda db: store)
    monkeypatch.setattr(reminders, 'snapshot', lambda raw, *_: raw)
    class Clock(datetime):
        current = FIRST
        @classmethod
        def now(cls, tz=None):
            return cls.current
    monkeypatch.setattr(worker, 'datetime', Clock)
    bot = NS(rest=NS(create_message=AsyncMock()))
    async def scan(config, seconds, *, error=False, active=False):
        Clock.current = FIRST + timedelta(seconds=seconds)
        war = reminders.sample({'tag': '#P2Y', 'name': 'Clan'}, '60') if active else None
        if war:
            war.update(start=FIRST, end=FIRST + timedelta(hours=24))
        client = NS(get_current_war=AsyncMock(return_value=war,
                                             side_effect=(error if isinstance(error, Exception) else RuntimeError('offline')) if error else None))
        await worker.scan_clan(NS(), client, bot, NS(), config)
        bot.rest.create_message.assert_not_awaited()
    return NS(old=old, new=new, status=collection, store=store, scan=scan)


@pytest.mark.parametrize('active', [False, True])
def test_old_scan_writing_at120_cannot_certify_new_settings_and_new180_writes(monkeypatch, active):
    case = harness(monkeypatch)
    async def check():
        await case.scan(case.old, 120, active=active)
        assert len(case.status.writes) == 1
        assert case.status.row['settings_version'] == 1
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=120))[0] == 'pending'
        await case.scan(case.new, 180, active=active)
        assert len(case.status.writes) == 2
        assert case.status.row['settings_version'] == 2
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=180))[0] == 'tracking'
        await case.scan(case.new, 240, active=active)
        assert len(case.status.writes) == 2
    asyncio.run(check())


@pytest.mark.parametrize('error', [False, True])
@pytest.mark.parametrize('same_millisecond', [False, True])
@pytest.mark.parametrize('long_versions', [False, True])
def test_late_older_true_change_or_error_cannot_overwrite_newer_settings(monkeypatch, error, same_millisecond, long_versions):
    case = harness(monkeypatch, same_millisecond=same_millisecond, long_versions=long_versions)
    async def check():
        await case.scan(case.new, 60)
        saved = deepcopy(case.status.row)
        await case.scan(case.old, 120, error=error, active=not error)
        assert case.status.row == saved
        assert len(case.status.writes) == 1
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=120))[0] == 'tracking'
    asyncio.run(check())


@pytest.mark.parametrize('error', [False, True])
@pytest.mark.parametrize('empty', [False, True])
def test_newer_result_winning_during_old_conditional_write_cannot_be_overwritten(monkeypatch, error, empty):
    case = harness(monkeypatch, empty=empty)
    async def newer():
        await case.scan(case.new, 180)
    case.status.before_update = newer
    async def check():
        await case.scan(case.old, 120, error=error, active=not error)
        assert len(case.status.writes) == 1
        assert case.status.row['settings_version'] == 2
        assert case.status.row['checked_at'] == bson(FIRST + timedelta(seconds=180))
        assert case.status.row['error'] is None
        assert case.status.duplicate_inserts == int(empty)
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=180))[0] == 'tracking'
    asyncio.run(check())


@pytest.mark.parametrize('seconds,initial_health', [(120, 'pending'), (182, 'attention')])
def test_legacy_recent_row_requires_one_honest_settings_refresh(monkeypatch, seconds, initial_health):
    case = harness(monkeypatch, legacy=True)
    case.status.row['checked_at'] = bson(FIRST + timedelta(seconds=seconds))
    async def check():
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=seconds))[0] == initial_health
        await case.scan(case.new, seconds)
        assert len(case.status.writes) == 1
        assert case.status.row['settings_version'] == 2
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=seconds))[0] == 'tracking'
        await case.scan(case.new, seconds + 60)
        assert len(case.status.writes) == 1
    asyncio.run(check())


def test_unbound_status_cannot_overwrite_bound_result_and_current_errors_still_write(monkeypatch):
    case = harness(monkeypatch)
    async def check():
        await case.scan(case.new, 60)
        assert not await case.store.record_status('#P2Y', checked_at=FIRST + timedelta(seconds=120),
                                                   error='UnknownSettings', detail='Unbound')
        assert len(case.status.writes) == 1
        await case.scan(case.new, 120, error=True)
        assert len(case.status.writes) == 2
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=120))[0] == 'attention'
        await case.scan(case.new, 180)
        assert len(case.status.writes) == 3
        assert health(case.new, case.status.row, None, FIRST + timedelta(seconds=180))[0] == 'tracking'
    asyncio.run(check())


@pytest.mark.parametrize('older_error', [False, True])
def test_same_identity_late_result_cannot_regress_newer_check(monkeypatch, older_error):
    case = harness(monkeypatch)
    async def check():
        await case.scan(case.old, 120, error=False if older_error else TimeoutError())
        saved = deepcopy(case.status.row)
        await case.scan(case.old, 119, error=TimeoutError() if older_error else False)
        assert case.status.row == saved
        assert len(case.status.writes) == 1
        assert health(case.old, case.status.row, None, FIRST + timedelta(seconds=121))[0] == (
            'tracking' if older_error else 'attention')
    asyncio.run(check())


@pytest.mark.parametrize('older_error', [False, True])
def test_same_identity_paused_worker_read_cannot_overwrite_newer_receipt(monkeypatch, older_error):
    case = harness(monkeypatch)
    # Make the old119s success due for its120s refresh, rather than a no-op.
    case.status.row['checked_at'] = bson(FIRST - timedelta(seconds=1))
    async def check():
        read_started, release = asyncio.Event(), asyncio.Event()
        original_find = case.status.find_one
        older_task = None
        paused = False
        async def delayed_find(query, *projection):
            nonlocal paused
            observed = await original_find(query, *projection)
            if asyncio.current_task() is older_task and not paused:
                paused = True
                read_started.set()
                await release.wait()
            return observed
        case.status.find_one = delayed_find
        older_task = asyncio.create_task(case.scan(
            case.old, 119, error=TimeoutError() if older_error else False))
        try:
            await asyncio.wait_for(read_started.wait(), timeout=5)
            await case.scan(case.old, 120, error=False if older_error else TimeoutError())
            saved = deepcopy(case.status.row)
        finally:
            release.set()
            await asyncio.wait_for(older_task, timeout=5)
        assert case.status.row == saved
        assert len(case.status.writes) == 1
        assert case.status.row['checked_at'] == bson(FIRST + timedelta(seconds=120))
        assert case.status.row['error'] == (None if older_error else 'TimeoutError')
        assert health(case.old, case.status.row, None, FIRST + timedelta(seconds=121))[0] == (
            'tracking' if older_error else 'attention')
    asyncio.run(check())


@pytest.mark.parametrize('older_error', [False, True])
@pytest.mark.parametrize('empty', [False, True])
def test_same_identity_conditional_update_or_insert_rechecks_newer_clock(monkeypatch, older_error, empty):
    case = harness(monkeypatch, empty=empty)
    if not empty:
        case.status.row['checked_at'] = bson(FIRST - timedelta(seconds=1))
    async def newer():
        await case.scan(case.old, 120, error=False if older_error else TimeoutError())
    case.status.before_update = newer
    async def check():
        await case.scan(case.old, 119, error=TimeoutError() if older_error else False)
        assert len(case.status.writes) == 1
        assert case.status.row['checked_at'] == bson(FIRST + timedelta(seconds=120))
        assert case.status.row['error'] == (None if older_error else 'TimeoutError')
        assert case.status.duplicate_inserts == int(empty)
        assert health(case.old, case.status.row, None, FIRST + timedelta(seconds=121))[0] == (
            'tracking' if older_error else 'attention')
    asyncio.run(check())
