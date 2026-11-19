"""Maintenance recovery uses real reminder owner/claims with literal fixture rows."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import coc
import pytest
from pymongo.errors import DuplicateKeyError
from bson import BSON

def bson(value):
    return BSON.encode({"v": value}).decode()["v"]
from extensions.tasks import war_reminders as worker
from utils import coc_maintenance as detector, war_reminders as reminders
from utils.war_reminder_store import WarReminderStore, occurrence_key
from utils.war_reminder_health import health

NOW = datetime(2026, 1, 2, tzinfo=timezone.utc)


class Rows:
    def __init__(self):self.rows = {};self.before_update = None;self.roundtrip = False
    async def find_one(self, query, *projection):
        row=self.rows.get(query['_id']);return bson(row) if self.roundtrip else deepcopy(row)
    async def insert_one(self, row):
        if row['_id'] in self.rows:raise DuplicateKeyError('fixture duplicate')
        self.rows[row['_id']] = deepcopy(row)
    async def update_one(self, query, update, *, upsert=False):
        if self.roundtrip:query,update=bson(query),bson(update)
        if self.before_update is not None:
            callback,self.before_update=self.before_update,None
            callback(query,update)
        row = self.rows.get(query['_id'])
        matches = row is not None and all(
            ((key in row) == value['$exists'] if isinstance(value, dict) and '$exists' in value
             else row.get(key) == value) for key, value in query.items())
        if not matches and not (upsert and row is None):return NS(matched_count=0, upserted_id=None)
        inserted = row is None
        row = self.rows.setdefault(query['_id'], {'_id': query['_id']})
        row.update(deepcopy(update.get('$set', {})))
        return NS(matched_count=not inserted, upserted_id=query['_id'] if inserted else None)


@pytest.fixture
def fixture(monkeypatch):
    detector.reset();worker._warned_maintenance_start = None
    store = WarReminderStore.__new__(WarReminderStore)
    store.status = Rows();store.deliveries = Rows();store.settings = Rows()
    config = {**reminders.settings(), '_id': '#P2Y', 'enabled': True, 'channel_id': '123456789012345678',
              'version': 1, 'minutes': [480, 60], 'updated_at': NOW-timedelta(days=2)}
    store.settings.rows['#P2Y'] = deepcopy(config)
    store.db = NS(clans=NS(find_one=AsyncMock(return_value={'_id': 'clan'})))
    war = reminders.sample({'tag': '#P2Y', 'name': 'Warriors'}, '60')
    war.update(start=NOW-timedelta(hours=23), end=NOW+timedelta(minutes=40))
    store.status.rows['#P2Y'] = dict(_id='#P2Y', checked_at=NOW-timedelta(minutes=1),
                                    war_start=war['start'], maintenance_since=NOW-timedelta(hours=8),
                                    error='Maintenance', settings_updated_at=config['updated_at'], settings_version=1)
    monkeypatch.setattr(worker, 'WarReminderStore', lambda db: store)
    monkeypatch.setattr(reminders, 'snapshot', lambda value, tag: value)
    class Clock(datetime):
        value = NOW
        @classmethod
        def now(cls, tz=None):return cls.value
    monkeypatch.setattr(worker, 'datetime', Clock);monkeypatch.setattr(detector, '_now', lambda: Clock.value)
    bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=reminders.GUILD_ID, type=0)),
                     create_message=AsyncMock(return_value=NS(id=123))))
    links = NS(linked_owners=AsyncMock(return_value={'#SAMPLE1': '123456789012345670'}))
    client = NS(get_current_war=AsyncMock(return_value=war))
    args = (NS(), client, bot, links, config)
    yield NS(store=store, war=war, bot=bot, links=links, client=client, args=args, clock=Clock, config=config)
    detector.reset()


def test_latest_only_with_real_time_left_and_earlier_log_status_only(fixture, caplog):
    caplog.set_level("INFO", logger=worker.__name__)
    f = fixture
    asyncio.run(worker.scan_clan(*f.args))
    assert f.bot.rest.create_message.await_count == 1
    text = f.bot.rest.create_message.await_args.kwargs['content']
    assert '40 minutes left · delayed by Clash maintenance' in text
    receipts = f.store.deliveries.rows
    assert occurrence_key('#P2Y', f.war['start'], '480') not in receipts
    assert '1 earlier maintenance reminders skipped.' in f.store.status.rows['#P2Y']['detail']
    infos = [r for r in caplog.records if r.name == worker.__name__ and r.levelname == 'INFO']
    assert len(infos) == 1 and '480 (1)' in infos[0].getMessage()
    assert receipts[occurrence_key('#P2Y', f.war['start'], '60')]['status'] == 'sent'
    assert f.store.status.rows['#P2Y']['maintenance_since'] is None
    assert f.store.status.rows['#P2Y']['war_start'] == f.war['start']
    asyncio.run(worker.scan_clan(*f.args));assert f.bot.rest.create_message.await_count == 1


def test_two_workers_and_restart_do_not_duplicate_latest(fixture):
    f = fixture
    async def run():await asyncio.gather(worker.scan_clan(*f.args), worker.scan_clan(*f.args))
    asyncio.run(run());asyncio.run(worker.scan_clan(*f.args))
    assert f.bot.rest.create_message.await_count == 1
    assert len(f.store.deliveries.rows) == 1


@pytest.mark.parametrize('change', ['new', 'unknown', 'ended', 'no-pending'])
def test_wrong_unknown_finished_war_or_no_pending_never_sends(fixture, change):
    f = fixture
    if change == 'new':f.store.status.rows['#P2Y']['war_start'] -= timedelta(days=2)
    if change == 'unknown':f.store.status.rows['#P2Y'].pop('war_start')
    if change == 'ended':f.client.get_current_war.return_value = None
    if change == 'no-pending':
        for member in f.war['members']:member['used'] = f.war['limit']
    asyncio.run(worker.scan_clan(*f.args));f.bot.rest.create_message.assert_not_awaited()
    assert all(row['status'] == 'skipped' for row in f.store.deliveries.rows.values())
    if change in ('new', 'unknown', 'ended'):assert f.store.deliveries.rows == {}


@pytest.mark.parametrize('claimed_state', ['uncertain', 'sending', 'sent', 'skipped'])
def test_latest_already_claimed_never_falls_back_to_older(fixture, claimed_state):
    f = fixture;k=occurrence_key('#P2Y', f.war['start'], '60')
    f.store.deliveries.rows[k] = {'_id': k, 'status': claimed_state}
    asyncio.run(worker.scan_clan(*f.args));f.bot.rest.create_message.assert_not_awaited()
    assert f.store.deliveries.rows[k]['status'] == claimed_state
    assert occurrence_key('#P2Y', f.war['start'], '480') not in f.store.deliveries.rows


def test_timeout_latest_is_durably_uncertain_and_not_replayed(fixture):
    f=fixture;f.bot.rest.create_message.side_effect=TimeoutError('fixture delivery')
    asyncio.run(worker.scan_clan(*f.args));asyncio.run(worker.scan_clan(*f.args))
    assert f.bot.rest.create_message.await_count == 1
    assert f.store.deliveries.rows[occurrence_key('#P2Y', f.war['start'], '60')]['status'] == 'uncertain'


def test_maintenance_first_since_identity_and_warning_no_traceback(fixture, caplog):
    f=fixture;f.store.status.rows['#P2Y'].pop('maintenance_since');f.client.get_current_war.side_effect=coc.Maintenance(503, {'reason': 'inMaintenance'})
    async def run():
        await worker.scan_clan(*f.args);f.clock.value += timedelta(seconds=60);await worker.scan_clan(*f.args)
    asyncio.run(run());state=f.store.status.rows['#P2Y']
    assert state['maintenance_since'] == NOW and state['war_start'] == f.war['start']
    assert detector.in_maintenance()
    warnings=[r for r in caplog.records if r.name == worker.__name__]
    assert len(warnings)==1 and warnings[0].levelname=='WARNING' and warnings[0].exc_info is None
    assert state['detail']=='Clash maintenance. Reminders continue when it ends.'
    assert health(f.config,state,None,f.clock.value)[0]=='maintenance'
    assert health({**f.config,'enabled':False},state,None,f.clock.value)[0]=='off'
    assert health(f.config,state,{'status':'uncertain'},f.clock.value)[1]=='Check delivery'


def test_restart_mid_maintenance_persists_catchup_without_memory(fixture):
    f=fixture;detector.reset()
    asyncio.run(worker.scan_clan(*f.args));assert f.bot.rest.create_message.await_count==1


def test_interval_bounds_preserve_existing_occurrence_identity(fixture):
    f=fixture;since=NOW-timedelta(hours=8)
    assert [e for e,_ in reminders.catchup_events(f.war,f.config,NOW,since,f.war['start'])]==['480','60']
    assert reminders.catchup_events(f.war,f.config,NOW,since,f.war['start']+timedelta(seconds=1))==[]
    near={**f.war,'end':NOW+timedelta(minutes=59)}
    assert '60' not in dict(reminders.catchup_events(near,f.config,NOW,since,f.war['start']))
    assert '60' in reminders.due(near,f.config,NOW)


def test_changed_settings_identity_does_not_replay_old_maintenance(fixture):
    f=fixture;f.store.status.rows['#P2Y']['settings_version']=0
    asyncio.run(worker.scan_clan(*f.args));f.bot.rest.create_message.assert_not_awaited()
    assert f.store.deliveries.rows=={}


def test_existing_tracker_calls_feed_detector_without_more_provider_requests(monkeypatch):
    from extensions.tasks.clan_history_tracker import _safe_fetch
    detector.reset();success=AsyncMock(return_value=object());failure=AsyncMock(side_effect=coc.Maintenance(503, {'reason':'inMaintenance'}))
    async def run():
        await _safe_fetch(asyncio.Semaphore(1),'clan','#FIXTURE',success)
        assert detector.observation()['last_success_at'] is not None
        await _safe_fetch(asyncio.Semaphore(1),'clan','#FIXTURE',failure)
        assert detector.in_maintenance()
    asyncio.run(run());assert success.await_count==failure.await_count==1;detector.reset()


def test_warning_once_across_detector_clear_then_five_minute_flap(fixture, caplog):
    f=fixture
    error=coc.Maintenance(503, {'reason':'inMaintenance'})
    async def run():
        f.client.get_current_war.side_effect=error
        await worker.scan_clan(*f.args)
        first_window=detector.window_started_at()
        f.clock.value=NOW+timedelta(seconds=100)
        detector.note_success();assert not detector.in_maintenance()
        f.clock.value=NOW+timedelta(seconds=170)
        await worker.scan_clan(*f.args)
        assert detector.window_started_at()==first_window
        f.clock.value=NOW+timedelta(seconds=270);detector.note_success()
        f.clock.value=NOW+timedelta(seconds=571)
        await worker.scan_clan(*f.args)
        assert detector.window_started_at()!=first_window
    asyncio.run(run())
    warnings=[r for r in caplog.records if r.name==worker.__name__]
    assert len(warnings)==2 and all(r.levelname=='WARNING' and r.exc_info is None for r in warnings)


def test_exact_five_minute_boundary_is_retained_until_next_existing_scan(fixture):
    f=fixture;f.config['minutes']=[60];f.store.settings.rows['#P2Y']['minutes']=[60]
    f.war['end']=NOW+timedelta(minutes=55)
    asyncio.run(worker.scan_clan(*f.args));f.bot.rest.create_message.assert_not_awaited()
    assert f.store.status.rows['#P2Y']['maintenance_since'] is not None
    f.clock.value=NOW+timedelta(seconds=60)
    asyncio.run(worker.scan_clan(*f.args));assert f.bot.rest.create_message.await_count==1
    assert f.store.status.rows['#P2Y']['maintenance_since'] is None


def test_cached_success_inside_shared_grace_preserves_pause_and_claims_nothing(fixture):
    f=fixture;detector.note_maintenance();since=f.store.status.rows['#P2Y']['maintenance_since']
    async def run():
        await worker.scan_clan(*f.args)
        f.clock.value=NOW+timedelta(seconds=60);await worker.scan_clan(*f.args)
        assert detector.in_maintenance() and f.store.status.rows['#P2Y']['maintenance_since']==since
        assert f.store.deliveries.rows=={} and f.store.status.rows['#P2Y']['error']=='Maintenance'
        f.clock.value=NOW+timedelta(seconds=91);await worker.scan_clan(*f.args)
    asyncio.run(run())
    assert not detector.in_maintenance() and f.bot.rest.create_message.await_count==1
    assert f.client.get_current_war.await_count==3  # only the three existing scans
    assert f.store.status.rows['#P2Y']['maintenance_since'] is None


def test_clear_cas_cannot_clear_a_replacement_window_and_writes_no_liveness(fixture):
    f=fixture;row=f.store.status.rows['#P2Y'];row['error']=None
    original=row['maintenance_since'];checked=row['checked_at'];replacement=NOW+timedelta(seconds=1)
    def race(query, update):
        assert update=={'$set':{'maintenance_since':None}}
        row['maintenance_since']=replacement
    f.store.status.before_update=race
    assert asyncio.run(f.store.clear_maintenance(f.config,original,f.war['start'])) is False
    assert row['maintenance_since']==replacement and row['checked_at']==checked


def test_bson_naive_millisecond_war_identity_still_matches_current_snapshot(fixture):
    f=fixture;f.war['start']=f.war['start'].replace(microsecond=123456)
    f.store.status.rows['#P2Y']['war_start']=f.war['start']
    f.store.status.rows=bson(f.store.status.rows);f.store.status.roundtrip=True
    asyncio.run(worker.scan_clan(*f.args))
    assert f.bot.rest.create_message.await_count==1
    assert f.store.status.rows['#P2Y']['maintenance_since'] is None


@pytest.mark.parametrize('newest_state', [None, 'uncertain', 'sending', 'sent', 'skipped'])
def test_same_war_shifted_end_earlier_event_normal_due_once(fixture, newest_state):
    """Earlier catch-up events reserve no key needed after a same-war end shift."""
    f = fixture
    old_key = occurrence_key('#P2Y', f.war['start'], '480')
    newest_key = occurrence_key('#P2Y', f.war['start'], '60')
    if newest_state:
        f.store.deliveries.rows[newest_key] = {'_id': newest_key, 'status': newest_state}
    async def scan_twice():
        await asyncio.gather(worker.scan_clan(*f.args), worker.scan_clan(*f.args))
    asyncio.run(scan_twice())
    assert old_key not in f.store.deliveries.rows
    assert f.bot.rest.create_message.await_count == (0 if newest_state else 1)
    if newest_state:
        assert f.store.deliveries.rows[newest_key]['status'] == newest_state
    else:
        assert '40 minutes left · delayed by Clash maintenance' in f.bot.rest.create_message.await_args.kwargs['content']
    prior_sends = f.bot.rest.create_message.await_count
    # Same start/occurrence identity; only war end shifts so480is now normal-due.
    f.war['end'] = NOW + timedelta(minutes=479)
    assert reminders.due(f.war, f.config, NOW) == ['480']
    asyncio.run(scan_twice()); asyncio.run(worker.scan_clan(*f.args))
    assert f.bot.rest.create_message.await_count == prior_sends + 1
    assert f.store.deliveries.rows[old_key]['status'] == 'sent'
    assert 'delayed by Clash maintenance' not in f.bot.rest.create_message.await_args.kwargs['content']


@pytest.mark.parametrize('claimed_state', ['uncertain', 'sending', 'sent', 'skipped'])
def test_preclaimed_earlier_offset_is_not_reported_as_skipped(fixture, caplog, claimed_state):
    caplog.set_level('INFO', logger=worker.__name__)
    f = fixture
    key = occurrence_key('#P2Y', f.war['start'], '480')
    f.store.deliveries.rows[key] = {'_id': key, 'status': claimed_state}
    before = deepcopy(f.store.deliveries.rows[key])
    asyncio.run(worker.scan_clan(*f.args))
    assert f.bot.rest.create_message.await_count == 1
    assert f.store.deliveries.rows[key] == before
    assert '0 earlier maintenance reminders skipped.' in f.store.status.rows['#P2Y']['detail']
    infos = [r.getMessage() for r in caplog.records if r.name == worker.__name__ and r.levelname == 'INFO']
    assert len(infos) == 1 and 'none (0)' in infos[0] and '480' not in infos[0]


def test_concurrent_same_prestatus_has_one_delivery_and_one_catchup_info(fixture, caplog, monkeypatch):
    caplog.set_level('INFO', logger=worker.__name__)
    f = fixture
    original = f.store.get_status
    async def run():
        ready = asyncio.Event()
        reads = 0
        async def synchronized(tag):
            nonlocal reads
            before = await original(tag)
            reads += 1
            if reads <= 2:
                if reads == 2:
                    ready.set()
                await ready.wait()
            return before
        monkeypatch.setattr(f.store, 'get_status', synchronized)
        await asyncio.gather(worker.scan_clan(*f.args), worker.scan_clan(*f.args))
    asyncio.run(run())
    assert f.bot.rest.create_message.await_count == 1
    assert len(f.store.deliveries.rows) == 1
    assert occurrence_key('#P2Y', f.war['start'], '480') not in f.store.deliveries.rows
    infos = [r for r in caplog.records if r.name == worker.__name__ and r.levelname == 'INFO']
    assert len(infos) == 1 and '480 (1)' in infos[0].getMessage()
    assert '1 earlier maintenance reminders skipped.' in f.store.status.rows['#P2Y']['detail']
