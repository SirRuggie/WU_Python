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

    async def clan(self, tag):
        return {'tag': tag} if self.exists else None

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
