import asyncio
from unittest.mock import AsyncMock

import pytest

from tests.test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign as campaign
from utils.cwl_web_bridge import native_receipt


def test_deleted_receipt_preserves_history_and_other_pool_and_replay():
    async def scenario():
        mongo = MemoryMongo()
        for pool, message in [('main', 123), ('lazy', 456)]:
            await campaign.record_delivery(mongo, 22, '2026-11', {
                'occurrence_id': campaign.occurrence_id('2026-11', 'roster', pool),
                'status': 'sent', 'channel_id': 789, 'message_id': message,
            })
        args = dict(channel_id=789, message_id=123, actor_id=42)
        archived = await campaign.reopen_deleted_roster_delivery(mongo, 22, '2026-11', 'main', **args)
        assert archived['status'] == 'deleted_confirmed'
        assert archived['message_id'] == 123
        assert archived['deleted_by'] == 42
        assert await campaign.reopen_deleted_roster_delivery(mongo, 22, '2026-11', 'main', **args) == archived
        state = await campaign.load_campaign(mongo, 22, '2026-11')
        assert native_receipt(state, 'main') is None
        assert native_receipt(state, 'lazy')['message_id'] == 456
        await campaign.record_delivery(mongo, 22, '2026-11', {
            'occurrence_id': campaign.occurrence_id('2026-11', 'roster', 'main'),
            'status': 'sent', 'channel_id': 789, 'message_id': 999,
        })
        with pytest.raises(ValueError, match='changed'):
            await campaign.reopen_deleted_roster_delivery(mongo, 22, '2026-11', 'main', **args)
        assert native_receipt(await campaign.load_campaign(mongo, 22, '2026-11'), 'main')['message_id'] == 999
    asyncio.run(scenario())


def test_stale_destination_and_concurrent_receipt_change_keep_sent_block():
    async def scenario():
        mongo = MemoryMongo()
        await campaign.record_delivery(mongo, 22, '2026-11', {
            'occurrence_id': campaign.occurrence_id('2026-11', 'roster', 'main'),
            'status': 'sent', 'channel_id': 789, 'message_id': 123,
        })
        with pytest.raises(ValueError, match='changed'):
            await campaign.reopen_deleted_roster_delivery(mongo, 22, '2026-11', 'main', channel_id=888, message_id=123, actor_id=42)
        mongo.bot_config.update_one = AsyncMock(return_value=type('Result', (), {'matched_count': 0})())
        with pytest.raises(ValueError, match='changed'):
            await campaign.reopen_deleted_roster_delivery(mongo, 22, '2026-11', 'main', channel_id=789, message_id=123, actor_id=42)
        assert native_receipt(await campaign.load_campaign(mongo, 22, '2026-11'), 'main')['message_id'] == 123
    asyncio.run(scenario())


def test_confirmed_deleted_message_changes_nonce_but_retry_is_stable():
    import hashlib
    occurrence = campaign.occurrence_id('2026-11', 'roster', 'main')
    original = campaign.roster_delivery_nonce(22, occurrence, [])
    assert original == hashlib.blake2s(f'22|{occurrence}'.encode(), digest_size=10).hexdigest()
    unrelated = [{'occurrence_id': 'other', 'status': 'deleted_confirmed', 'message_id': 789}]
    assert campaign.roster_delivery_nonce(22, occurrence, unrelated) == original
    deleted = [{'occurrence_id': occurrence, 'status': 'deleted_confirmed', 'message_id': 123}]
    replacement = campaign.roster_delivery_nonce(22, occurrence, deleted)
    assert replacement != original
    assert campaign.roster_delivery_nonce(22, occurrence, deleted) == replacement
    assert campaign.roster_delivery_nonce(22, occurrence, deleted + [dict(deleted[0], message_id=456)]) != replacement


def test_reopened_request_can_queue_once_and_old_receipt_survives():
    from utils import cwl_web_bridge as bridge
    from test_cwl_web_bridge import settings, GUILD, CYCLE
    async def scenario():
        mongo = MemoryMongo()
        loaded = await campaign.load_campaign(mongo, GUILD, CYCLE)
        args = settings(loaded)
        queued = await bridge.queue_roster_send(mongo, **args)
        receipt = {'occurrence_id': campaign.occurrence_id(CYCLE, 'roster', 'main'),
                   'status': 'sent', 'channel_id': queued['channel_id'], 'message_id': 123}
        await campaign.record_delivery(mongo, GUILD, CYCLE, receipt)
        await mongo.bot_config.update_one({'_id': queued['_id']}, {'$set': {'status': 'sent', 'receipt': receipt}})
        await bridge.reopen_deleted_request(mongo, guild_id=GUILD, cycle=CYCLE, pool='main', receipt=receipt, actor_id=42)
        row = await bridge.queue_roster_send(mongo, **args, retry_failed=True)
        assert row['status'] == 'pending'
        assert row['previous_receipts'][-1]['message_id'] == 123
        with pytest.raises(bridge.BridgeConflict):
            await bridge.reopen_deleted_request(mongo, guild_id=GUILD, cycle=CYCLE, pool='main', receipt=receipt, actor_id=42)
        with pytest.raises(bridge.BridgeConflict):
            await bridge.queue_roster_send(mongo, **args, retry_failed=True)
    asyncio.run(scenario())
