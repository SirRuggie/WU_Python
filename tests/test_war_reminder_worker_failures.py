"""Adversarial worker tests: concurrency, uncertain delivery, and live edits."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from extensions.tasks import war_reminders as worker
from utils import war_reminders as reminders


class Store:
    def __init__(self):
        self.config = {**reminders.settings(), '_id': '#P2Y', 'enabled': True,
                       'channel_id': '123456789012345678', 'version': 1}
        self.receipts = {}
        self.status = {}
        self.exists = True

    async def clan_exists(self, tag):
        return self.exists

    async def get_status(self, tag):
        return self.status.copy()

    async def get_settings(self, tag):
        return self.config.copy()

    async def record_status(self, tag, **values):
        self.status.update(values)

    async def delivered_or_claimed(self, key):
        return key in self.receipts

    async def claim_delivery(self, key, **values):
        # Models Mongo's unique _id insert: no await between check and insert.
        if key in self.receipts:
            return False
        self.receipts[key] = values
        return True

    async def finish_delivery(self, key, **values):
        self.receipts[key].update(values)


@pytest.fixture
def setup(monkeypatch):
    store = Store()
    now = datetime.now(timezone.utc)
    war = reminders.sample({'tag': '#P2Y', 'name': 'Warriors'}, '60')
    war.update(start=now-timedelta(hours=23), end=now+timedelta(hours=1))
    monkeypatch.setattr(worker, 'WarReminderStore', lambda db: store)
    monkeypatch.setattr(reminders, 'snapshot', lambda *_: war)
    links = NS(linked_owners=AsyncMock(return_value={'#SAMPLE1': '123456789012345670'}))
    bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=reminders.GUILD_ID, type=0)),
                     create_message=AsyncMock(return_value=NS(id=1))))
    args = (NS(), NS(get_current_war=AsyncMock()), bot, links, store.config.copy())
    return store, bot, links, args


def test_concurrent_workers_only_one_claim_sends(setup):
    store, bot, links, args = setup
    async def run():
        await asyncio.gather(worker.scan_clan(*args), worker.scan_clan(*args))
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    assert len(store.receipts) == 1
    links = bot.rest.create_message.await_args.kwargs["components"][0].components
    assert [(link.label, link.url) for link in links] == [("My tasks", "https://dash.warriorsunited.cc/tasks"), ("Wars", "https://dash.warriorsunited.cc/wars")]


def test_uncertain_send_is_never_replayed(setup):
    store, bot, links, args = setup
    bot.rest.create_message.side_effect = TimeoutError()
    async def run():
        await worker.scan_clan(*args)
        await worker.scan_clan(*args)
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    assert next(iter(store.receipts.values()))['status'] == 'uncertain'
    assert links.linked_owners.await_count == 1


@pytest.mark.parametrize('change', ['disable', 'edit', 'remove'])
def test_settings_changed_during_lookup_cancel_delivery(setup, change):
    store, bot, links, args = setup
    async def lookup(tags):
        if change == 'disable': store.config['enabled'] = False
        elif change == 'edit': store.config['version'] += 1
        else: store.exists = False
        return {}
    links.linked_owners.side_effect = lookup
    asyncio.run(worker.scan_clan(*args))
    bot.rest.create_message.assert_not_awaited()
    assert not store.receipts


def test_link_outage_retries_without_treating_members_as_unlinked(setup):
    store, bot, links, args = setup
    links.linked_owners.side_effect = [RuntimeError('unavailable'), {}]
    async def run():
        await worker.scan_clan(*args)
        assert not store.receipts
        await worker.scan_clan(*args)
    asyncio.run(run())
    assert bot.rest.create_message.await_count == 1
    assert next(iter(store.receipts.values()))['status'] == 'sent'


def test_foreign_channel_cannot_receive_scheduled_message(setup):
    store, bot, links, args = setup
    bot.rest.fetch_channel.return_value = NS(guild_id=123, type=0)
    asyncio.run(worker.scan_clan(*args))
    bot.rest.create_message.assert_not_awaited()
    assert not store.receipts


def test_cancellation_preserves_claim_and_propagates(setup):
    store, bot, links, args = setup
    bot.rest.create_message.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(worker.scan_clan(*args))
    assert next(iter(store.receipts.values()))['status'] == 'sending'


def test_partial_send_records_progress_and_no_repeat_pings(setup, monkeypatch):
    store, bot, links, args = setup
    monkeypatch.setattr(reminders, 'messages', lambda *a, **kw: [
        {'content': 'first', 'allowed_mentions': {'users': ['123456789012345670']}},
        {'content': 'second', 'allowed_mentions': {'users': []}},
    ])
    bot.rest.create_message.side_effect = [NS(id=1), TimeoutError()]
    asyncio.run(worker.scan_clan(*args))
    receipt = next(iter(store.receipts.values()))
    assert receipt['status'] == 'uncertain' and len(receipt['urls']) == 1
    assert bot.rest.create_message.await_args.kwargs['user_mentions'] == []


@pytest.mark.parametrize('scan_old_settings_first', [False, True])
def test_scan_confirms_only_scanned_settings_and_refreshes_first_new_success(monkeypatch, scan_old_settings_first):
    from bson import BSON
    from utils.war_reminder_health import health
    from utils.war_reminder_store import WarReminderStore
    first = datetime(2026, 11, 17, tzinfo=timezone.utc)
    config = {**reminders.settings(), '_id': '#P2Y', 'enabled': True,
              'channel_id': '123456789012345678', 'version': 2,
              'updated_at': first + timedelta(seconds=1)}
    persisted = BSON.encode({'_id': '#P2Y', 'checked_at': first, 'error': None,
                             'detail': 'Waiting for an active war', 'war_end': None,
                             'settings_updated_at': first, 'settings_version': 1}).decode()
    writes = []
    async def find(query, *projection):
        return persisted
    async def update(query, values, **kwargs):
        nonlocal persisted
        persisted = BSON.encode({'_id': query['_id'], **values['$set']}).decode()
        writes.append(persisted.copy())
        return NS(matched_count=1, upserted_id=None)
    store = WarReminderStore.__new__(WarReminderStore)
    store.status = NS(find_one=find, update_one=update)
    store.db = NS(clans=NS(find_one=AsyncMock(return_value={'_id': 'clan'})))
    monkeypatch.setattr(worker, 'WarReminderStore', lambda db: store)
    monkeypatch.setattr(reminders, 'snapshot', lambda *_: None)
    class Clock(datetime):
        current = first + timedelta(seconds=60)
        @classmethod
        def now(cls, tz=None):
            return cls.current
    monkeypatch.setattr(worker, 'datetime', Clock)
    client = NS(get_current_war=AsyncMock(return_value=None))
    bot = NS(rest=NS(create_message=AsyncMock()))
    async def check():
        if scan_old_settings_first:
            old_config = {**config, 'version': 1, 'updated_at': first}
            await worker.scan_clan(NS(), client, bot, NS(), old_config)
            assert len(writes) == 0
            assert health(config, persisted, None, Clock.current)[0] == 'pending'
        await worker.scan_clan(NS(), client, bot, NS(), config)
        assert len(writes) == 1
        assert health(config, persisted, None, Clock.current)[0] == 'tracking'
        Clock.current = first + timedelta(seconds=120)
        await worker.scan_clan(NS(), client, bot, NS(), config)
        assert len(writes) == 1
        assert health(config, persisted, None, Clock.current)[0] == 'tracking'
        assert persisted['settings_version'] == 2
        assert persisted['settings_updated_at'].replace(tzinfo=timezone.utc) == config['updated_at']
        bot.rest.create_message.assert_not_awaited()
    asyncio.run(check())


def _multipart_channels(monkeypatch, channels):
    monkeypatch.setattr(worker, '_channel_locks', {})
    monkeypatch.setattr(worker, 'WarReminderStore', lambda db: db)
    monkeypatch.setattr(reminders, 'snapshot', lambda war, tag: war)
    monkeypatch.setattr(reminders, 'messages', lambda war, *args, **kw: [
        dict(content=f"{war['name']}{part}", allowed_mentions={'users': []}, footer=part == 3)
        for part in (1, 2, 3)])
    now = datetime.now(timezone.utc)
    pairs = []
    for name, channel in zip(('A', 'B'), channels):
        store = Store()
        store.config.update(_id='#'+name, channel_id=channel)
        war = reminders.sample({'tag': '#'+name, 'name': name}, '60')
        war.update(start=now-timedelta(hours=23), end=now+timedelta(hours=1))
        pairs.append((store, NS(get_current_war=AsyncMock(return_value=war))))
    return pairs


def test_same_channel_concurrent_clan_scans_group_claim_and_all_parts_with_footer(monkeypatch):
    pairs = _multipart_channels(monkeypatch, ['123456789012345678'] * 2)
    calls = []
    async def create(channel, **payload):
        calls.append((payload['content'], payload))
        await asyncio.sleep(0)
        return NS(id=len(calls))
    bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=reminders.GUILD_ID, type=0)), create_message=create))
    links = NS(linked_owners=AsyncMock(return_value={}))
    async def run():
        await asyncio.gather(*(worker.scan_clan(store, client, bot, links, store.config.copy())
                               for store, client in pairs))
    asyncio.run(run())
    assert [content for content, _ in calls] in [list(('A1','A2','A3','B1','B2','B3')), list(('B1','B2','B3','A1','A2','A3'))]
    for content, payload in calls:
        assert ('attachment' in payload) is content.endswith('3')
        if content.endswith('3'):
            assert isinstance(payload['attachment'], worker.hikari.File)
            assert payload['attachment'].filename == 'Gold_Footer.png'
        assert payload['mentions_everyone'] is False and payload['role_mentions'] is False
    assert all(next(iter(store.receipts.values()))['status'] == 'sent' for store, _ in pairs)


@pytest.mark.parametrize('same_channel', [True, False])
def test_cancelled_send_releases_channel_and_different_channel_never_waits(monkeypatch, same_channel):
    pairs = _multipart_channels(monkeypatch, ['123456789012345678', '123456789012345678' if same_channel else '123456789012345679'])
    async def run():
        entered, blocked = asyncio.Event(), asyncio.Event()
        calls = []
        async def create(channel, **payload):
            calls.append(payload['content'])
            if payload['content'] == 'A1':
                entered.set()
                await blocked.wait()
            return NS(id=len(calls))
        bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=reminders.GUILD_ID, type=0)), create_message=create))
        links = NS(linked_owners=AsyncMock(return_value={}))
        tasks = [asyncio.create_task(worker.scan_clan(store, client, bot, links, store.config.copy()))
                 for store, client in pairs]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            if same_channel:
                assert calls == ['A1'] and not pairs[1][0].receipts
                tasks[0].cancel()
                with pytest.raises(asyncio.CancelledError): await tasks[0]
            await asyncio.wait_for(tasks[1], 1)
            assert calls[-3:] == ['B1', 'B2', 'B3']
            assert next(iter(pairs[0][0].receipts.values()))['status'] == 'sending'
            assert next(iter(pairs[1][0].receipts.values()))['status'] == 'sent'
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert not any(lock.locked() for lock in worker._channel_locks.values())
    asyncio.run(run())


@pytest.mark.parametrize('change', ['disable', 'version', 'expiry'])
def test_waiting_channel_rechecks_settings_and_due_before_claim(monkeypatch, change):
    pairs = _multipart_channels(monkeypatch, ['123456789012345678'] * 2)
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def create(channel, **payload):
            calls.append(payload['content'])
            if payload['content'] == 'A1':
                entered.set(); await release.wait()
            return NS(id=len(calls))
        bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=reminders.GUILD_ID, type=0)), create_message=create))
        links = NS(linked_owners=AsyncMock(return_value={}))
        tasks = [asyncio.create_task(worker.scan_clan(store, client, bot, links, store.config.copy()))
                 for store, client in pairs]
        try:
            await asyncio.wait_for(entered.wait(), 1)
            await asyncio.sleep(0)
            if change == 'disable': pairs[1][0].config['enabled'] = False
            elif change == 'version': pairs[1][0].config['version'] += 1
            else:
                original = reminders.due
                monkeypatch.setattr(reminders, 'due', lambda war, config, now: [] if war['name'] == 'B' else original(war, config, now))
            release.set()
            await asyncio.gather(*tasks)
            assert calls == ['A1', 'A2', 'A3']
            assert not pairs[1][0].receipts
        finally:
            for task in tasks:
                if not task.done(): task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
    asyncio.run(run())


def test_partial_exception_releases_channel_without_replaying_uncertain_set(monkeypatch):
    pairs = _multipart_channels(monkeypatch, ['123456789012345678'] * 2)
    calls = []
    async def create(channel, **payload):
        calls.append(payload['content'])
        await asyncio.sleep(0)
        if payload['content'] == 'A2': raise TimeoutError('mock accepted status unknown')
        return NS(id=len(calls))
    bot = NS(rest=NS(fetch_channel=AsyncMock(return_value=NS(guild_id=reminders.GUILD_ID, type=0)), create_message=create))
    links = NS(linked_owners=AsyncMock(return_value={}))
    async def run():
        await asyncio.gather(*(worker.scan_clan(store, client, bot, links, store.config.copy())
                               for store, client in pairs))
        await worker.scan_clan(pairs[0][0], pairs[0][1], bot, links, pairs[0][0].config.copy())
    asyncio.run(run())
    assert calls == ['A1', 'A2', 'B1', 'B2', 'B3']
    first = next(iter(pairs[0][0].receipts.values()))
    assert first['status'] == 'uncertain' and len(first['urls']) == 1
    assert next(iter(pairs[1][0].receipts.values()))['status'] == 'sent'
    assert not any(lock.locked() for lock in worker._channel_locks.values())
