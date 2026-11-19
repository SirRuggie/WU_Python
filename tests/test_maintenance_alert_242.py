"""Literal Mongo/Discord fixtures only; no API, database or message delivery."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from pymongo.errors import DuplicateKeyError
from bson import BSON

def bson(value):
    return BSON.encode({"v": value}).decode()["v"]
from utils import coc_maintenance as detector
from utils import maintenance_alert_store as storage
from extensions.tasks.maintenance_alert import AlertWorker, alert_text, payload

START = datetime(2026, 1, 1, tzinfo=timezone.utc)


class Rows:
    def __init__(self):
        self.rows = {}
        self.roundtrip = False

    @property
    def row(self):
        return self.rows.get('clash')

    @row.setter
    def row(self, value):
        if value is None:self.rows.pop('clash', None)
        else:self.rows['clash'] = value

    async def find_one(self, query):
        row = self.rows.get(query['_id'])
        return bson(row) if self.roundtrip else deepcopy(row)

    def find(self, query):
        selected = [deepcopy(row) for row in self.rows.values()
                    if all(row.get(key) == value for key, value in query.items())]
        async def to_list(length=None):return selected
        return NS(to_list=to_list)

    async def insert_one(self, row):
        if row['_id'] in self.rows:
            raise DuplicateKeyError('fixture unique key')
        self.rows[row['_id']] = bson(row) if self.roundtrip else deepcopy(row)

    async def update_one(self, query, update):
        if self.roundtrip:query,update=bson(query),bson(update)
        row = self.rows.get(query['_id'])
        if row is None or any(row.get(k) != v for k, v in query.items()):
            return NS(matched_count=0)
        row.update(deepcopy(update.get('$set', {})))
        for key, amount in update.get('$inc', {}).items():
            row[key] = row.get(key, 0) + amount
        return NS(matched_count=1)


@pytest.fixture
def setup(monkeypatch):
    detector.reset()
    rows = Rows()
    calls = []
    def collection(db, name, **kwargs):
        calls.append((name, kwargs['write_concern'].document))
        return rows
    monkeypatch.setattr(storage, 'collection_from', collection)
    store = storage.MaintenanceAlertStore(NS(bot_config=object()))
    bot = NS(rest=NS(create_message=AsyncMock(return_value=NS(id=123)),
                     edit_message=AsyncMock()))
    clock = [START]
    monkeypatch.setattr(detector, '_now', lambda: clock[0])
    worker = AlertWorker(store, bot, started_at=START)
    yield rows, store, bot, clock, worker, calls
    detector.reset()


def test_majority_intent_precedes_post_and_concurrent_ticks_post_once(setup):
    rows, store, bot, clock, worker, calls = setup
    async def send(*args, **kwargs):
        assert rows.row['state'] == 'uncertain' and rows.row['message_id'] is None
        await asyncio.sleep(0)
        return NS(id=123)
    bot.rest.create_message.side_effect = send
    detector.note_maintenance()
    async def run():
        await asyncio.gather(worker.tick(START), AlertWorker(store, bot, started_at=START).tick(START))
        await worker.tick(START)
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    assert rows.row['message_id'] == '123' and rows.row['state'] == 'open'
    assert calls == [('maintenance_alert', {'w': 'majority'})]
    kwargs = bot.rest.create_message.await_args.kwargs
    assert kwargs['mentions_everyone'] is kwargs['user_mentions'] is kwargs['role_mentions'] is False
    assert int(kwargs['components'][0].accent_color) == 0xE00010


def test_five_minute_clear_flap_preserves_first_start_and_same_message(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance();await worker.tick(START)
        clock[0] = START + timedelta(seconds=100);detector.note_success();await worker.tick(clock[0])
        clock[0] = START + timedelta(seconds=170);detector.note_maintenance();await worker.tick(clock[0])
        assert rows.row['started_at'] == START and rows.row['clear_since'] is None
        assert bot.rest.edit_message.await_count == 0
        clock[0] = START + timedelta(seconds=270);detector.note_success();await worker.tick(clock[0])
        await worker.tick(START + timedelta(seconds=569));assert bot.rest.edit_message.await_count == 0
        await worker.tick(START + timedelta(seconds=570));await worker.tick(START + timedelta(seconds=600))
    asyncio.run(run())
    assert bot.rest.create_message.await_count == bot.rest.edit_message.await_count == 1
    assert rows.row['state'] == 'closed'
    kwargs = bot.rest.edit_message.await_args.kwargs
    assert int(kwargs['components'][0].accent_color) == 0x00D659
    assert 'Lasted 4 min' in kwargs['components'][0].components[0].content


def test_restart_during_maintenance_edits_known_message_never_posts(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance();await worker.tick(START)
        clock[0] = START + timedelta(seconds=20)
        restarted = AlertWorker(store, bot, started_at=clock[0])
        await restarted.tick(clock[0]);await restarted.tick(clock[0])
    asyncio.run(run())
    assert bot.rest.create_message.await_count == bot.rest.edit_message.await_count == 1
    assert bot.rest.edit_message.await_args.args == (947166650321494067, 123)


def test_restart_default_healthy_requires_new_success_and_full_clear_window(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance();await worker.tick(START)
        detector.reset();clock[0] = START + timedelta(hours=1)
        restarted = AlertWorker(store, bot, started_at=clock[0])
        await restarted.tick(clock[0]);assert rows.row['clear_since'] is None
        detector.note_success();await restarted.tick(clock[0])
        await restarted.tick(clock[0] + timedelta(seconds=299));assert bot.rest.edit_message.await_count == 0
        await restarted.tick(clock[0] + timedelta(seconds=300))
    asyncio.run(run())
    assert rows.row['state'] == 'closed' and bot.rest.edit_message.await_count == 1


def test_timeout_post_is_never_reposted_after_restart(setup, caplog):
    rows, store, bot, clock, worker, _ = setup
    bot.rest.create_message.side_effect = TimeoutError('PRIVATE fixture error must not be logged')
    async def run():
        detector.note_maintenance();assert await worker.tick(START) is False
        await worker.tick(START);await AlertWorker(store, bot, started_at=START).tick(START)
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1 and bot.rest.edit_message.await_count == 0
    assert rows.row['state'] == 'uncertain'
    assert len(caplog.records) == 1 and caplog.records[0].levelname == 'WARNING'
    assert caplog.records[0].exc_info is None and 'PRIVATE' not in caplog.text


def test_cancelled_ambiguous_post_stays_uncertain(setup):
    rows, store, bot, clock, worker, _ = setup
    bot.rest.create_message.side_effect = asyncio.CancelledError
    async def run():
        detector.note_maintenance()
        with pytest.raises(asyncio.CancelledError):await worker.tick(START)
        await AlertWorker(store, bot, started_at=START).tick(START)
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1 and rows.row['state'] == 'uncertain'


def test_known_id_failed_edit_retries_without_post_or_traceback(setup, caplog):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance();await worker.tick(START)
        clock[0] = START + timedelta(seconds=100);detector.note_success();await worker.tick(clock[0])
        bot.rest.edit_message.side_effect = TimeoutError('secret fixture')
        await worker.tick(START + timedelta(seconds=400));await worker.tick(START + timedelta(seconds=430))
        bot.rest.edit_message.side_effect = None
        await worker.tick(START + timedelta(seconds=460))
    asyncio.run(run())
    assert rows.row['state'] == 'closed' and bot.rest.create_message.await_count == 1
    assert bot.rest.edit_message.await_count == 3
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None


def test_two_workers_close_only_one_claim(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance();await worker.tick(START)
        clock[0] = START + timedelta(seconds=100);detector.note_success();await worker.tick(clock[0])
        other = AlertWorker(store, bot, started_at=START)
        await asyncio.gather(worker.tick(START + timedelta(seconds=400)), other.tick(START + timedelta(seconds=400)))
    asyncio.run(run())
    assert bot.rest.edit_message.await_count == 1


def test_alert_copy_has_no_raw_ids_or_mention_syntax():
    text = alert_text(START)
    assert 'Started <t:' in text and 'the bot' not in text.lower()
    assert '<@' not in text and '947166650321494067' not in text
    p = payload(START)
    assert p['user_mentions'] is False


def test_stale_observer_cannot_cancel_clear_or_reopen_closed_window(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance();await worker.tick(START)
        clock[0] = START + timedelta(seconds=100);detector.note_success();await worker.tick(clock[0])
        same, post = await store.observe(START, START, 947166650321494067)
        assert not post and same['clear_since'] == clock[0]
        await worker.tick(START + timedelta(seconds=400))
        same, post = await store.observe(START, START, 947166650321494067)
        assert not post and same['state'] == 'closed'
    asyncio.run(run())
    assert bot.rest.create_message.await_count == bot.rest.edit_message.await_count == 1


def test_alert_collection_is_a_routed_child_of_bot_config():
    from utils.mongo_routes import load_routes, collection_from
    routes=load_routes({'bot_config':{'database':'fixture_config','collection':'bot_config'}})
    assert routes['maintenance_alert'].database=='fixture_config'
    assert routes['maintenance_alert'].collection=='maintenance_alert'
    calls=[]
    database=NS(get_collection=lambda name,**options:(calls.append((name,options)), 'fixture')[1])
    assert collection_from(NS(database=database),'maintenance_alert',write_concern='fixture-majority')=='fixture'
    assert calls==[('maintenance_alert',{'write_concern':'fixture-majority'})]


def test_real_hikari_payload_serializes_components_v2_without_attachments():
    for end,color in ((None,0xE00010),(START+timedelta(minutes=46),0x00D659)):
        value=payload(START,end);component,attachments=value['components'][0].build()
        assert component['type']==17 and component['accent_color']==color
        assert not attachments and int(value['flags'])==32768
        assert value['mentions_everyone'] is value['user_mentions'] is value['role_mentions'] is False


def test_bson_millisecond_roundtrip_does_not_renew_stale_observation_or_restart_clear(setup):
    rows, store, bot, clock, _, _=setup;rows.roundtrip=True
    clock[0]=START.replace(microsecond=123456)
    first=AlertWorker(store,bot,started_at=clock[0])
    async def run():
        detector.note_maintenance();await first.tick(clock[0]);revision=rows.row['revision']
        await first.tick(clock[0]+timedelta(seconds=30))
        assert rows.row['revision']==revision  # same actual503 is not a fresh observation
        detector.reset();clock[0]+=timedelta(seconds=100)
        restarted=AlertWorker(store,bot,started_at=clock[0]);detector.note_success()
        await restarted.tick(clock[0]);await restarted.tick(clock[0]+timedelta(seconds=300))
    asyncio.run(run())
    assert rows.row['state']=='closed' and bot.rest.create_message.await_count==bot.rest.edit_message.await_count==1


def test_flap_entirely_between_ticks_restarts_full_continuous_clear_hold(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        clock[0] = START + timedelta(seconds=100)
        detector.note_success(); await worker.tick(clock[0])
        clock[0] = START + timedelta(seconds=170); detector.note_maintenance()
        clock[0] = START + timedelta(seconds=270); detector.note_success()
        # No alert tick occurred at either transition of the second flap.
        await worker.tick(START + timedelta(seconds=400))
        assert bot.rest.edit_message.await_count == 0
        assert rows.row['clear_since'] == START + timedelta(seconds=270)
        await worker.tick(START + timedelta(seconds=569))
        assert bot.rest.edit_message.await_count == 0
        await worker.tick(START + timedelta(seconds=570))
    asyncio.run(run())
    assert bot.rest.create_message.await_count == bot.rest.edit_message.await_count == 1
    assert 'Lasted 4 min' in bot.rest.edit_message.await_args.kwargs['components'][0].components[0].content


def test_resolution_payload_uses_actual_clear_observation_not_later_tick(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        clock[0] = START + timedelta(seconds=119); detector.note_success()
        await worker.tick(START + timedelta(seconds=145))
        clock[0] = START + timedelta(seconds=200); detector.note_success()
        await worker.tick(START + timedelta(seconds=418))
        assert bot.rest.edit_message.await_count == 0
        await worker.tick(START + timedelta(seconds=419))
    asyncio.run(run())
    text = bot.rest.edit_message.await_args.kwargs['components'][0].components[0].content
    assert text == f'## ✅ Clash maintenance ended\nLasted 1 min · ended <t:{int(START.timestamp()) + 119}:t>'


@pytest.mark.parametrize('healthy', [False, True])
@pytest.mark.parametrize('channel', ['123456789012345678', None, 'malformed'])
def test_restart_rejects_persisted_foreign_or_malformed_destination(setup, healthy, channel, caplog):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        rows.row['channel_id'] = channel
        before = deepcopy(rows.row)
        clock[0] = START + timedelta(seconds=100)
        if healthy:
            detector.note_success()
        restarted = AlertWorker(store, bot, started_at=clock[0])
        assert await restarted.tick(clock[0]) is False
        assert await restarted.tick(clock[0] + timedelta(seconds=600)) is False
        assert rows.row == before
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    bot.rest.edit_message.assert_not_awaited()
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None


def test_stale_green_completes_after_new_red_and_next_tick_repairs_same_message(setup):
    rows, store, bot, clock, worker, _ = setup
    completed = []
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        clock[0] = START + timedelta(seconds=100)
        detector.note_success(); await worker.tick(clock[0])
        other = AlertWorker(store, bot, started_at=START)
        green_started, release_green = asyncio.Event(), asyncio.Event()
        async def edit(*args, **kwargs):
            color = int(kwargs['components'][0].accent_color)
            if color == 0x00D659 and not green_started.is_set():
                green_started.set(); await release_green.wait()
            completed.append(color)
        bot.rest.edit_message.side_effect = edit
        old = asyncio.create_task(worker.tick(START + timedelta(seconds=400)))
        await green_started.wait()
        clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
        await other.tick(clock[0])
        assert completed == [0xE00010] and not rows.row['needs_red_edit']
        release_green.set(); await old
        assert completed == [0xE00010, 0x00D659]
        assert rows.row['state'] == 'open' and rows.row['needs_red_edit']
        assert detector.in_maintenance()
        await other.tick(START + timedelta(seconds=431))
    asyncio.run(run())
    assert completed == [0xE00010, 0x00D659, 0xE00010]
    assert not rows.row['needs_red_edit']
    assert bot.rest.create_message.await_count == 1
    assert all(call.args == (947166650321494067, 123) for call in bot.rest.edit_message.await_args_list)


def test_stale_red_after_closed_green_restart_repairs_original_observed_clear(setup):
    rows, store, bot, clock, worker, _ = setup
    completed = []
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        other = AlertWorker(store, bot, started_at=START)
        red_started, release_red = asyncio.Event(), asyncio.Event()
        async def edit(*args, **kwargs):
            color = int(kwargs['components'][0].accent_color)
            if color == 0xE00010 and not red_started.is_set():
                red_started.set(); await release_red.wait()
            completed.append(color)
        bot.rest.edit_message.side_effect = edit
        old = asyncio.create_task(other.tick(START))
        await red_started.wait()
        # The old red REST request remains pending beyond its lease. Another
        # worker can recover, observe a full clear and complete the green edit.
        clock[0] = START + timedelta(seconds=100); detector.note_success()
        await worker.tick(clock[0]); await worker.tick(START + timedelta(seconds=101))
        await worker.tick(START + timedelta(seconds=400))
        assert rows.row['state'] == 'closed' and not rows.row['needs_red_edit']
        release_red.set(); await old
        assert completed[-2:] == [0x00D659, 0xE00010]
        assert rows.row['state'] == 'closed' and rows.row['needs_red_edit']
        detector.reset()  # Neither recovery evidence nor payload time survives in memory.
        restarted = AlertWorker(store, bot, started_at=START + timedelta(hours=1))
        await restarted.tick(START + timedelta(hours=1))
    asyncio.run(run())
    assert completed[-1] == 0x00D659 and not rows.row['needs_red_edit']
    text = bot.rest.edit_message.await_args.kwargs['components'][0].components[0].content
    assert text == f'## ✅ Clash maintenance ended\nLasted 1 min · ended <t:{int(START.timestamp()) + 100}:t>'
    assert rows.row['clear_since'] == START + timedelta(seconds=100)
    assert bot.rest.create_message.await_count == 1


@pytest.mark.parametrize('ack_first', [False, True])
def test_render_ack_cannot_erase_a_later_invalidation_in_either_order(setup, ack_first):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        intent = await store.claim_edit(await store.get(), START)
        assert intent['needs_red_edit']
        if ack_first:
            assert await store.finish_edit(intent)
            assert not rows.row['needs_red_edit']
            assert await store.invalidate_edit(intent)
        else:
            assert await store.invalidate_edit(intent)
            assert not await store.finish_edit(intent)
        assert rows.row['needs_red_edit']
        await worker.tick(START + timedelta(seconds=91))
        assert not rows.row['needs_red_edit']
    asyncio.run(run())


@pytest.mark.parametrize('replacement', ['window', 'message', 'destination'])
def test_stale_edit_completion_never_dirties_replacement_or_foreign_owner(setup, replacement):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        intent = await store.claim_edit(await store.get(), START)
        values = dict(needs_red_edit=False)
        if replacement == 'window':values['started_at'] = START + timedelta(seconds=1)
        if replacement == 'message':values['message_id'] = '456'
        if replacement == 'destination':values['channel_id'] = '123456789012345678'
        assert await store.change(intent, **values)
        before = deepcopy(rows.row)
        assert not await store.finish_edit(intent, ended=START + timedelta(seconds=100),
                                           final_render=alert_text(START, START + timedelta(seconds=100)))
        assert rows.row == before
    asyncio.run(run())
    bot.rest.edit_message.assert_not_awaited()


@pytest.mark.parametrize('green', [False, True])
@pytest.mark.parametrize('accepted', [False, True])
def test_cancelled_edit_keeps_dirty_intent_and_restart_reconciles_without_post(setup, green, accepted):
    rows, store, bot, clock, worker, _ = setup
    accepted_payloads = []
    async def cancelled(*args, **kwargs):
        assert rows.row['needs_red_edit']  # Durable BEFORE the external attempt.
        if accepted:accepted_payloads.append(kwargs)
        raise asyncio.CancelledError
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        if green:
            clock[0] = START + timedelta(seconds=100)
            detector.note_success(); await worker.tick(clock[0])
        bot.rest.edit_message.side_effect = cancelled
        actor = worker if green else AlertWorker(store, bot, started_at=START)
        with pytest.raises(asyncio.CancelledError):
            await actor.tick(START + timedelta(seconds=400) if green else START)
        assert rows.row['needs_red_edit'] and rows.row['state'] == 'open'
        bot.rest.edit_message.side_effect = None
        restarted = AlertWorker(store, bot, started_at=START)
        await restarted.tick(START + timedelta(seconds=430) if green else START)
    asyncio.run(run())
    assert len(accepted_payloads) == int(accepted)
    assert not rows.row['needs_red_edit']
    assert rows.row['state'] == ('closed' if green else 'open')
    assert bot.rest.create_message.await_count == 1


def test_process_death_after_durable_red_intent_reconciles_after_lease(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        abandoned = await store.claim_edit(await store.get(), START)
        assert abandoned and rows.row['needs_red_edit']
        restarted = AlertWorker(store, bot, started_at=START)
        await restarted.tick(START + timedelta(seconds=89))
        bot.rest.edit_message.assert_not_awaited()
        await restarted.tick(START + timedelta(seconds=90))
    asyncio.run(run())
    assert bot.rest.edit_message.await_count == 1 and not rows.row['needs_red_edit']
    assert bot.rest.create_message.await_count == 1


@pytest.mark.parametrize('green', [False, True])
def test_cancelled_edit_preserves_shutdown_when_storage_cleanup_is_unavailable(setup, monkeypatch, caplog, green):
    rows, store, bot, clock, worker, _ = setup
    original_finish = store.finish_edit
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        if green:
            clock[0] = START + timedelta(seconds=100)
            detector.note_success(); await worker.tick(clock[0])
        actor = worker if green else AlertWorker(store, bot, started_at=START)
        bot.rest.edit_message.side_effect = asyncio.CancelledError
        monkeypatch.setattr(store, 'finish_edit', AsyncMock(side_effect=OSError('PRIVATE fixture unavailable')))
        with pytest.raises(asyncio.CancelledError):
            await actor.tick(START + timedelta(seconds=400) if green else START)
        assert len(actor.pending_invalidations) == 1 and rows.row['needs_red_edit']
        monkeypatch.setattr(store, 'finish_edit', original_finish)
        bot.rest.edit_message.side_effect = None
        await actor.tick(START + timedelta(seconds=500) if green else START + timedelta(seconds=100))
        assert not actor.pending_invalidations and not rows.row['needs_red_edit']
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None
    assert 'PRIVATE' not in caplog.text


def test_stale_red_storage_failure_retains_invalidation_until_next_tick_recovers(setup, monkeypatch, caplog):
    rows, store, bot, clock, worker, _ = setup
    original_finish = store.finish_edit
    original_invalidate = store.invalidate_edit
    completed = []
    async def run():
        detector.note_maintenance(); await worker.tick(START)
        other = AlertWorker(store, bot, started_at=START)
        red_started, release_red = asyncio.Event(), asyncio.Event()
        async def edit(*args, **kwargs):
            color = int(kwargs['components'][0].accent_color)
            if color == 0xE00010 and not red_started.is_set():
                red_started.set(); await release_red.wait()
            completed.append(color)
        bot.rest.edit_message.side_effect = edit
        old = asyncio.create_task(other.tick(START))
        await red_started.wait()
        old_claim = rows.row['edit_claim']
        clock[0] = START + timedelta(seconds=100); detector.note_success()
        await worker.tick(clock[0]); await worker.tick(START + timedelta(seconds=101))
        await worker.tick(START + timedelta(seconds=400))
        assert rows.row['state'] == 'closed' and not rows.row['needs_red_edit']
        async def unavailable(intent, **kwargs):
            if intent['edit_claim'] == old_claim:
                raise OSError('PRIVATE fixture unavailable')
            return await original_finish(intent, **kwargs)
        monkeypatch.setattr(store, 'finish_edit', unavailable)
        release_red.set(); assert await old is False
        assert completed[-1] == 0xE00010
        assert len(other.pending_invalidations) == 1
        assert rows.row['state'] == 'closed' and not rows.row['needs_red_edit']
        # An outage on the retry must retain ownership and issue no REST edit.
        monkeypatch.setattr(store, 'invalidate_edit', AsyncMock(side_effect=OSError('PRIVATE fixture unavailable')))
        before = bot.rest.edit_message.await_count
        assert await other.tick(START + timedelta(seconds=430)) is False
        assert len(other.pending_invalidations) == 1 and bot.rest.edit_message.await_count == before
        monkeypatch.setattr(store, 'invalidate_edit', original_invalidate)
        monkeypatch.setattr(store, 'finish_edit', original_finish)
        await other.tick(START + timedelta(seconds=460))
        assert not other.pending_invalidations and not rows.row['needs_red_edit']
    asyncio.run(run())
    assert completed[-1] == 0x00D659
    assert bot.rest.create_message.await_count == 1
    assert all(r.exc_info is None for r in caplog.records) and 'PRIVATE' not in caplog.text


async def rollover_fixture(setup, *, old_red_count=1):
    """Actual owner/workers; delayed old edits finish only when explicitly released."""
    rows, store, bot, clock, worker, _ = setup
    colors, posts, edits = {}, [], []
    ids = iter((123, 456))
    async def create(*args, **kwargs):
        message = next(ids); colors[message] = int(kwargs['components'][0].accent_color)
        posts.append(message); return NS(id=message)
    bot.rest.create_message.side_effect = create
    detector.note_maintenance(); await worker.tick(START)
    entered = [asyncio.Event() for _ in range(old_red_count)]
    releases = [asyncio.Event() for _ in range(old_red_count)]
    held = []
    async def edit(channel, message, **kwargs):
        color = int(kwargs['components'][0].accent_color)
        if message == 123 and color == 0xE00010 and len(held) < old_red_count:
            index = len(held); held.append(index); entered[index].set()
            await releases[index].wait()
        colors[message] = color; edits.append((message, color))
    bot.rest.edit_message.side_effect = edit
    tasks, actors, intents = [], [], []
    for index in range(old_red_count):
        actor = AlertWorker(store, bot, started_at=START); actors.append(actor)
        tasks.append(asyncio.create_task(actor.tick(START + timedelta(seconds=91 * index))))
        await entered[index].wait(); intents.append(deepcopy(rows.row))
    clock[0] = START + timedelta(seconds=100); detector.note_success()
    for second in (100, 200, 201, 400):await worker.tick(START + timedelta(seconds=second))
    assert rows.row['state'] == 'closed' and colors[123] == 0x00D659
    closed = deepcopy(rows.row)
    clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
    await worker.tick(clock[0])
    assert rows.row['message_id'] == '456' and posts == [123, 456]
    return NS(rows=rows, store=store, bot=bot, clock=clock, worker=worker, colors=colors,
              posts=posts, edits=edits, tasks=tasks, actors=actors, intents=intents,
              releases=releases, closed=closed, key=store.window_id(closed))


def test_1164_exact_old_red_after_green_and_new_window_reconciles_123_only(setup):
    async def run():
        f = await rollover_fixture(setup)
        receipt = deepcopy(f.rows.rows[f.key])
        assert receipt['state'] == 'reconciled'
        f.releases[0].set(); await f.tasks[0]
        assert f.colors == {123: 0xE00010, 456: 0xE00010}
        assert f.rows.rows[f.key]['state'] == 'dirty'
        await f.worker.tick(START + timedelta(seconds=431))
        assert f.colors == {123: 0x00D659, 456: 0xE00010}
        assert f.rows.rows[f.key]['state'] == 'reconciled'
        assert {key: f.rows.rows[f.key][key] for key in storage.MaintenanceAlertStore.CLOSED_FIELDS} == {
            key: receipt[key] for key in storage.MaintenanceAlertStore.CLOSED_FIELDS}
        revision, edits = f.rows.rows[f.key]['revision'], list(f.edits)
        await f.worker.tick(START + timedelta(seconds=461)); await f.worker.tick(START + timedelta(seconds=491))
        assert f.edits == edits and f.rows.rows[f.key]['revision'] == revision
        assert f.posts == [123, 456] and len(f.rows.rows) == 2
    asyncio.run(run())


def test_reconciled_receipt_is_reactivated_by_each_later_known_red_completion(setup):
    async def run():
        f = await rollover_fixture(setup, old_red_count=2)
        for index, second in ((0, 431), (1, 461)):
            f.releases[index].set(); await f.tasks[index]
            assert f.colors[123] == 0xE00010 and f.rows.rows[f.key]['state'] == 'dirty'
            await f.worker.tick(START + timedelta(seconds=second))
            assert f.colors == {123: 0x00D659, 456: 0xE00010}
            assert f.rows.rows[f.key]['state'] == 'reconciled'
        assert f.posts == [123, 456]
    asyncio.run(run())


def test_concurrent_receipt_acknowledgements_cannot_erase_later_red_invalidation(setup):
    async def run():
        f = await rollover_fixture(setup)
        f.releases[0].set(); await f.tasks[0]
        first = await f.store.claim_edit(deepcopy(f.rows.rows[f.key]), START)
        second = await f.store.claim_edit(deepcopy(f.rows.rows[f.key]), START)
        assert await f.store.invalidate_closed(deepcopy(f.rows.rows[f.key]))
        assert not await f.store.finish_edit(first, ended=first['ended_at'], final_render=first['final_render'])
        assert not await f.store.finish_edit(second, ended=second['ended_at'], final_render=second['final_render'])
        assert f.rows.rows[f.key]['state'] == 'dirty'
        await asyncio.gather(f.worker.tick(START + timedelta(seconds=431)),
                             AlertWorker(f.store, f.bot, started_at=START).tick(START + timedelta(seconds=431)))
        assert f.colors == {123: 0x00D659, 456: 0xE00010}
        assert f.rows.rows[f.key]['state'] == 'reconciled' and f.posts == [123, 456]
    asyncio.run(run())


@pytest.mark.parametrize('foreign', ['destination', 'message', 'window'])
def test_closed_receipt_callback_and_tick_reject_foreign_ownership(setup, foreign):
    async def run():
        f = await rollover_fixture(setup)
        receipt = f.rows.rows[f.key]
        if foreign == 'destination':receipt['channel_id'] = '123456789012345678'
        if foreign == 'message':receipt['message_id'] = '999'
        if foreign == 'window':receipt['started_at'] += timedelta(seconds=1)
        before = deepcopy(receipt)
        f.releases[0].set(); await f.tasks[0]
        assert receipt == before  # Never dirty a replacement/foreign receipt.
        if foreign == 'destination':
            receipt['state'] = 'dirty'
            before = deepcopy(receipt)
            await f.worker.tick(START + timedelta(seconds=431))
            assert receipt == before
        assert not any(message == 999 for message, _ in f.edits)
        assert f.posts == [123, 456] and f.rows.row['message_id'] == '456'
    asyncio.run(run())


@pytest.mark.parametrize('accepted_insert', [False, True])
def test_closed_receipt_write_failure_blocks_replacement_then_retry_posts_once(setup, monkeypatch, accepted_insert):
    rows, store, bot, clock, worker, _ = setup
    original = rows.insert_one
    async def run():
        bot.rest.create_message.side_effect = [NS(id=123), NS(id=456)]
        detector.note_maintenance(); await worker.tick(START)
        clock[0] = START + timedelta(seconds=100); detector.note_success()
        await worker.tick(clock[0]); await worker.tick(START + timedelta(seconds=400))
        old = deepcopy(rows.row); key = store.window_id(old)
        async def unavailable(row):
            if row['_id'] == key:
                if accepted_insert:await original(row)
                raise OSError('literal fixture unavailable')
            return await original(row)
        monkeypatch.setattr(rows, 'insert_one', unavailable)
        clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
        assert await worker.tick(clock[0]) is False
        assert rows.row == old and bot.rest.create_message.await_count == 1
        monkeypatch.setattr(rows, 'insert_one', original)
        await asyncio.gather(worker.tick(clock[0]), AlertWorker(store, bot, started_at=START).tick(clock[0]))
        assert rows.row['message_id'] == '456' and bot.rest.create_message.await_count == 2
        assert rows.rows[key]['message_id'] == '123' and len(rows.rows) == 2
    asyncio.run(run())


def test_late_red_at_replacement_cas_transfers_dirty_event_before_new_window(setup, monkeypatch):
    rows, store, bot, clock, worker, _ = setup
    original = rows.update_one
    async def run():
        bot.rest.create_message.side_effect = [NS(id=123), NS(id=456)]
        detector.note_maintenance(); await worker.tick(START)
        old_intent = deepcopy(rows.row)
        clock[0] = START + timedelta(seconds=100); detector.note_success()
        await worker.tick(clock[0]); await worker.tick(START + timedelta(seconds=400))
        key = store.window_id(rows.row); raced = False
        async def replacement(query, update):
            nonlocal raced
            if update.get('$set', {}).get('state') == 'uncertain' and not raced:
                raced = True
                assert await store.invalidate_edit(old_intent)
            return await original(query, update)
        monkeypatch.setattr(rows, 'update_one', replacement)
        clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
        await worker.tick(clock[0])
        assert raced and rows.rows[key]['state'] == 'dirty'
        assert rows.row['message_id'] == '456' and bot.rest.create_message.await_count == 2
        await worker.tick(START + timedelta(seconds=431))
        assert rows.rows[key]['state'] == 'reconciled'
    asyncio.run(run())


@pytest.mark.parametrize('cleanup_unavailable', [False, True])
def test_cancelled_historical_green_repair_stays_edit_only_and_recovers(setup, monkeypatch, cleanup_unavailable):
    async def run():
        f = await rollover_fixture(setup)
        f.releases[0].set(); await f.tasks[0]
        original_finish = f.store.finish_edit
        f.bot.rest.edit_message.side_effect = asyncio.CancelledError
        if cleanup_unavailable:
            monkeypatch.setattr(f.store, 'finish_edit', AsyncMock(side_effect=OSError('fixture unavailable')))
        with pytest.raises(asyncio.CancelledError):await f.worker.tick(START + timedelta(seconds=431))
        assert f.rows.rows[f.key]['state'] == 'dirty' and f.rows.row['message_id'] == '456'
        monkeypatch.setattr(f.store, 'finish_edit', original_finish)
        async def edit(channel, message, **kwargs):f.colors[message] = int(kwargs['components'][0].accent_color)
        f.bot.rest.edit_message.side_effect = edit
        await f.worker.tick(START + timedelta(seconds=461))
        assert not f.worker.pending_invalidations
        assert f.colors == {123: 0x00D659, 456: 0xE00010}
        assert f.rows.rows[f.key]['state'] == 'reconciled' and f.posts == [123, 456]
    asyncio.run(run())


def test_historical_red_callback_db_failure_retries_own_receipt_after_rollover(setup, monkeypatch):
    async def run():
        f = await rollover_fixture(setup)
        original = f.store.finish_edit
        old_claim = f.intents[0]['edit_claim']
        async def unavailable(intent, **kwargs):
            if intent['edit_claim'] == old_claim:raise OSError('fixture unavailable')
            return await original(intent, **kwargs)
        monkeypatch.setattr(f.store, 'finish_edit', unavailable)
        f.releases[0].set(); assert await f.tasks[0] is False
        assert len(f.actors[0].pending_invalidations) == 1
        assert f.rows.rows[f.key]['state'] == 'reconciled' and f.colors[123] == 0xE00010
        monkeypatch.setattr(f.store, 'finish_edit', original)
        await f.actors[0].tick(START + timedelta(seconds=431))
        assert not f.actors[0].pending_invalidations
        assert f.colors == {123: 0x00D659, 456: 0xE00010} and f.posts == [123, 456]
    asyncio.run(run())


def test_unknown_id_uncertain_post_is_preserved_without_retry_when_new_window_starts(setup):
    rows, store, bot, clock, worker, _ = setup
    async def run():
        bot.rest.create_message.side_effect = [TimeoutError('fixture ambiguous post'), NS(id=456)]
        detector.note_maintenance(); assert await worker.tick(START) is False
        assert rows.row['state'] == 'uncertain' and rows.row['message_id'] is None
        clock[0] = START + timedelta(seconds=100); detector.note_success()
        await worker.tick(clock[0]); await worker.tick(START + timedelta(seconds=400))
        key = store.window_id(rows.row)
        clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
        await worker.tick(clock[0]); await worker.tick(START + timedelta(seconds=431))
        assert rows.rows[key]['state'] == 'unconfirmed' and rows.rows[key]['message_id'] is None
        assert rows.row['message_id'] == '456' and bot.rest.create_message.await_count == 2
        bot.rest.edit_message.assert_not_awaited()
    asyncio.run(run())


def test_matching_late_green_callback_does_not_reactivate_reconciled_receipt(setup):
    async def run():
        f = await rollover_fixture(setup)
        f.releases[0].set(); await f.tasks[0]
        await f.worker.tick(START + timedelta(seconds=431))
        before = deepcopy(f.rows.rows[f.key])
        assert not await f.store.finish_edit(f.closed, ended=before['ended_at'], final_render=before['final_render'])
        assert f.rows.rows[f.key] == before
    asyncio.run(run())


def test_tampered_closed_render_is_discoverable_and_never_sent(setup, caplog):
    async def run():
        f = await rollover_fixture(setup)
        f.releases[0].set(); await f.tasks[0]
        f.rows.rows[f.key]['final_render'] = 'unsafe <@123456789012345678> external text'
        before = list(f.edits)
        assert await f.worker.tick(START + timedelta(seconds=431)) is False
        assert f.edits == before and f.rows.rows[f.key]['state'] == 'dirty'
        assert f.posts == [123, 456]
    asyncio.run(run())
    assert len(caplog.records) == 1 and caplog.records[0].exc_info is None


async def pending_post_fixture(setup):
    rows, store, bot, clock, actor, _ = setup
    entered, release = asyncio.Event(), asyncio.Event()
    colors, posts, intents = {}, [], []
    original_observe = store.observe
    async def observe(*args):
        row, post = await original_observe(*args)
        if post:intents.append(deepcopy(row))
        return row, post
    store.observe = observe
    async def create(channel, **kwargs):
        if not entered.is_set():
            entered.set(); await release.wait(); message = 123
        else:message = 456
        colors[message] = int(kwargs['components'][0].accent_color); posts.append(message)
        assert kwargs['mentions_everyone'] is kwargs['user_mentions'] is kwargs['role_mentions'] is False
        return NS(id=message)
    async def edit(channel, message, **kwargs):colors[message] = int(kwargs['components'][0].accent_color)
    bot.rest.create_message.side_effect = create; bot.rest.edit_message.side_effect = edit
    detector.note_maintenance(); task = asyncio.create_task(actor.tick(START))
    await entered.wait()
    other = AlertWorker(store, bot, started_at=START)
    clock[0] = START + timedelta(seconds=100); detector.note_success(); await other.tick(clock[0])
    return NS(rows=rows, store=store, bot=bot, clock=clock, actor=actor, other=other,
              release=release, task=task, colors=colors, posts=posts, intent=intents[0])


async def close_pending_post(f):
    await f.other.tick(START + timedelta(seconds=400))
    assert f.rows.row['state'] == 'closed' and f.rows.row['message_id'] is None


async def replace_pending_post(f):
    await close_pending_post(f)
    f.key = f.store.window_id(f.rows.row)
    f.clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
    await f.other.tick(f.clock[0])
    assert f.rows.row['message_id'] == '456' and f.rows.rows[f.key]['state'] == 'unconfirmed'


@pytest.mark.parametrize('stage', ['before-close', 'closing', 'closed', 'archived'])
def test_1166_known_post_return_attaches_only_own_window_at_each_transition(setup, monkeypatch, stage):
    async def run():
        f = await pending_post_fixture(setup)
        if stage == 'closing':
            entered, release_close = asyncio.Event(), asyncio.Event()
            original = f.store.finish_edit
            async def finish(intent, **kwargs):
                if intent['state'] == 'closing' and intent['message_id'] is None:
                    entered.set(); await release_close.wait()
                return await original(intent, **kwargs)
            monkeypatch.setattr(f.store, 'finish_edit', finish)
            closing = asyncio.create_task(f.other.tick(START + timedelta(seconds=400)))
            await entered.wait()
            f.release.set(); await f.task
            assert f.rows.row['message_id'] == '123' and f.rows.row['state'] == 'open'
            release_close.set(); await closing
            await f.other.tick(START + timedelta(seconds=430))
            f.clock[0] = START + timedelta(seconds=431); detector.note_maintenance()
            await f.other.tick(f.clock[0])
        else:
            if stage == 'closed':await close_pending_post(f)
            if stage == 'archived':await replace_pending_post(f)
            f.release.set(); await f.task
            if stage == 'before-close':await f.other.tick(START + timedelta(seconds=400))
            if stage != 'archived':
                f.clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
                await f.other.tick(f.clock[0])
        await f.other.tick(START + timedelta(seconds=500))
        assert f.colors == {123: 0x00D659, 456: 0xE00010}
        assert sorted(f.posts) == [123, 456] and f.bot.rest.create_message.await_count == 2
        assert not f.actor.pending_posts
        assert f.rows.rows[f.store.window_id(f.intent)]['message_id'] == '123'
    asyncio.run(run())


def test_delayed_winning_insert_returns_exact_intent_and_cannot_post_new_window_twice(setup, monkeypatch):
    rows, store, bot, clock, actor, _ = setup
    original_insert, original_observe = rows.insert_one, store.observe
    snapshots = []
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        async def insert(row):
            await original_insert(row)
            if row['_id'] == 'clash' and not entered.is_set():
                entered.set(); await release.wait()
        async def observe(*args):
            row, post = await original_observe(*args)
            if post:snapshots.append(deepcopy(row))
            return row, post
        monkeypatch.setattr(rows, 'insert_one', insert); monkeypatch.setattr(store, 'observe', observe)
        bot.rest.create_message.return_value = NS(id=456)
        detector.note_maintenance(); old = asyncio.create_task(actor.tick(START))
        await entered.wait()
        other = AlertWorker(store, bot, started_at=START)
        clock[0] = START + timedelta(seconds=100); detector.note_success(); await other.tick(clock[0])
        await other.tick(START + timedelta(seconds=400))
        clock[0] = START + timedelta(seconds=401); detector.note_maintenance(); await other.tick(clock[0])
        assert bot.rest.create_message.await_count == 1 and rows.row['message_id'] == '456'
        release.set(); await old
        assert snapshots[-1]['started_at'] == START and snapshots[-1]['message_id'] is None
        assert snapshots[-1]['state'] == 'uncertain' and snapshots[-1]['revision'] == 1
        assert bot.rest.create_message.await_count == 1
        assert rows.row['message_id'] == '456'
        kwargs = bot.rest.create_message.await_args.kwargs
        assert f'<t:{int(clock[0].timestamp())}:R>' in kwargs['components'][0].components[0].content
    asyncio.run(run())


def test_known_return_during_archive_insert_fills_receipt_before_replacement(setup, monkeypatch):
    async def run():
        f = await pending_post_fixture(setup); await close_pending_post(f)
        key = f.store.window_id(f.rows.row); original_insert = f.rows.insert_one
        archived, release_archive = asyncio.Event(), asyncio.Event()
        async def insert(row):
            await original_insert(row)
            if row['_id'] == key:
                archived.set(); await release_archive.wait()
        monkeypatch.setattr(f.rows, 'insert_one', insert)
        f.clock[0] = START + timedelta(seconds=401); detector.note_maintenance()
        replacement = asyncio.create_task(f.other.tick(f.clock[0]))
        await archived.wait()
        f.release.set(); await f.task
        assert f.rows.row['message_id'] == '123' and f.rows.rows[key]['message_id'] is None
        release_archive.set(); await replacement
        assert f.rows.row['message_id'] == '456' and f.rows.rows[key]['message_id'] == '123'
        await f.other.tick(START + timedelta(seconds=431))
        assert f.colors == {123: 0x00D659, 456: 0xE00010} and sorted(f.posts) == [123, 456]
    asyncio.run(run())


@pytest.mark.parametrize('cancel', [False, True])
@pytest.mark.parametrize('write_accepted', [False, True])
def test_known_post_attachment_storage_error_or_cancel_retries_only_storage(setup, monkeypatch, cancel, write_accepted):
    async def run():
        f = await pending_post_fixture(setup); await replace_pending_post(f)
        original = f.store.posted
        async def unavailable(intent, message):
            if intent['started_at'] == START:
                if write_accepted:assert await original(intent, message)
                if cancel:raise asyncio.CancelledError
                raise OSError('PRIVATE attachment fixture')
            return await original(intent, message)
        monkeypatch.setattr(f.store, 'posted', unavailable)
        f.release.set()
        if cancel:
            with pytest.raises(asyncio.CancelledError):await f.task
        else:assert await f.task is False
        assert len(f.actor.pending_posts) == 1 and f.bot.rest.create_message.await_count == 2
        monkeypatch.setattr(f.store, 'posted', original)
        if write_accepted:
            await f.other.tick(START + timedelta(seconds=431))
            before = deepcopy(f.rows.rows[f.key])
        await f.actor.tick(START + timedelta(seconds=461))
        assert not f.actor.pending_posts
        assert f.colors == {123: 0x00D659, 456: 0xE00010} and sorted(f.posts) == [123, 456]
        if write_accepted:assert f.rows.rows[f.key] == before  # No redirty on storage-only retry.
        assert f.bot.rest.create_message.await_count == 2
    asyncio.run(run())


def test_fill_once_duplicate_conflicting_and_foreign_post_callbacks_fail_closed(setup):
    async def run():
        f = await pending_post_fixture(setup); await replace_pending_post(f)
        f.release.set(); await f.task
        before = deepcopy(f.rows.rows[f.key])
        results = await asyncio.gather(f.store.posted(f.intent, 123), f.store.posted(f.intent, 123))
        assert results == [True, True] and f.rows.rows[f.key] == before
        assert not await f.store.posted(f.intent, 999)
        for change in ({'channel_id': '123456789012345678'},
                       {'started_at': START + timedelta(seconds=1)},
                       {'revision': True}, {'state': 'open'}, {'_id': f.key}):
            assert not await f.store.posted({**f.intent, **change}, 123)
        assert f.rows.rows[f.key] == before and f.rows.row['message_id'] == '456'
        await f.other.tick(START + timedelta(seconds=431))
        assert f.colors == {123: 0x00D659, 456: 0xE00010} and f.bot.rest.create_message.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('foreign', ['destination', 'window', 'known-id'])
def test_known_return_never_attaches_to_foreign_closed_receipt(setup, foreign):
    async def run():
        f = await pending_post_fixture(setup); await replace_pending_post(f)
        receipt = f.rows.rows[f.key]
        if foreign == 'destination':receipt['channel_id'] = '123456789012345678'
        if foreign == 'window':receipt['started_at'] += timedelta(seconds=1)
        if foreign == 'known-id':receipt['message_id'] = '999'
        before = deepcopy(receipt)
        f.release.set(); assert await f.task is False
        assert receipt == before and f.rows.row['message_id'] == '456'
        assert not f.actor.pending_posts and f.bot.rest.create_message.await_count == 2
    asyncio.run(run())


def test_restart_reconciles_durable_known_late_post_without_post_retry(setup):
    async def run():
        f = await pending_post_fixture(setup); await replace_pending_post(f)
        f.release.set(); await f.task
        assert f.rows.rows[f.key]['message_id'] == '123' and f.rows.rows[f.key]['state'] == 'dirty'
        detector.reset()
        restarted = AlertWorker(f.store, f.bot, started_at=START + timedelta(seconds=900))
        await restarted.tick(START + timedelta(seconds=900))
        assert f.colors == {123: 0x00D659, 456: 0xE00010}
        assert f.rows.rows[f.key]['state'] == 'reconciled'
        assert sorted(f.posts) == [123, 456] and f.bot.rest.create_message.await_count == 2
    asyncio.run(run())
