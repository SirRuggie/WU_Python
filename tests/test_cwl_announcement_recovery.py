import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from cwl_web.announcement_recovery import deleted_in_discord, receipt_target
from cwl_web.server_management import DiscordItemNotFound

RECEIPT = {'channel_id': '123456789012345678', 'message_id': '987654321098765432'}
CHANNEL = {'guild_id': '644963518025826315', 'type': 0}

def test_only_known_deleted_message_allows_explicit_resend_review():
    async def scenario():
        fake = AsyncMock(side_effect=[CHANNEL, DiscordItemNotFound(10008)])
        with patch('cwl_web.announcement_recovery.discord', fake):
            assert await deleted_in_discord(None, RECEIPT) is True
        assert all(call.args[1] == 'GET' for call in fake.call_args_list)
        assert fake.call_args_list[-1].kwargs['roster_delivery'] is True
    asyncio.run(scenario())

@pytest.mark.parametrize('failure', [DiscordItemNotFound(10003), web.HTTPNotFound(), web.HTTPForbidden(), TimeoutError()])
def test_unknown_or_unavailable_is_not_deleted(failure):
    async def scenario():
        with patch('cwl_web.announcement_recovery.discord', AsyncMock(side_effect=[CHANNEL, failure])):
            with pytest.raises(type(failure)):
                await deleted_in_discord(None, RECEIPT)
    asyncio.run(scenario())

def test_existing_message_and_wrong_guild_never_allow_resend():
    async def scenario():
        with patch('cwl_web.announcement_recovery.discord', AsyncMock(side_effect=[CHANNEL, {'id': RECEIPT['message_id']}])):
            assert await deleted_in_discord(None, RECEIPT) is False
        fake = AsyncMock(return_value=dict(CHANNEL, guild_id='999'))
        with patch('cwl_web.announcement_recovery.discord', fake):
            with pytest.raises(web.HTTPForbidden):
                await deleted_in_discord(None, RECEIPT)
        assert fake.await_count == 1
    asyncio.run(scenario())

@pytest.mark.parametrize('receipt', [None, {}, {'channel_id': 'bad', 'message_id': '123'}])
def test_unverifiable_receipt_cannot_be_assumed_deleted(receipt):
    with pytest.raises(web.HTTPConflict):
        receipt_target(receipt)

from test_cwl_web_manage_bridge import ManageBridgeTests
from utils import cwl_campaign


class RecoveryHTTPTests(ManageBridgeTests):
    async def test_deletion_review_is_read_only_and_requires_send_permission(self):
        await self.bind()
        from cwl_web.manage_bridge import GUILD_ID
        cycle = (await self.state())['cycle']
        mongo = self.app['manage_bridge_mongo']
        await cwl_campaign.record_delivery(mongo, GUILD_ID, cycle, {
            'occurrence_id': cwl_campaign.occurrence_id(cycle, 'roster', 'main'),
            'status': 'sent', **RECEIPT,
        })
        before = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
        fake = AsyncMock(side_effect=[CHANNEL, DiscordItemNotFound(10008)])
        path = self.base + '/main/check-message'
        with patch('cwl_web.announcement_recovery.discord', fake):
            denied = await self.call('GET', path, self.member)
            self.assertEqual(denied.status, 403)
            self.assertEqual(fake.await_count, 0)
            result = await self.call('GET', path, self.owner)
            self.assertEqual(result.status, 200, await result.text())
            self.assertEqual(await result.json(), {'deleted': True, **RECEIPT})
        after = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
        self.assertEqual(after['deliveries'], before['deliveries'])
        self.assertEqual(after['sent_occurrences'], before['sent_occurrences'])

    async def test_explicit_resend_rechecks_deleted_message_and_queues_once(self):
        from utils import cwl_web_bridge
        from cwl_web.manage_bridge import GUILD_ID
        await self.bind()
        await self.publish()
        await cwl_web_bridge.mark_worker_alive(self.mongo, GUILD_ID)
        state = await self.state()
        receipt = {'occurrence_id': cwl_campaign.occurrence_id(state['cycle'], 'roster', 'main'),
                   'status': 'sent', **RECEIPT}
        await cwl_campaign.record_delivery(self.mongo, GUILD_ID, state['cycle'], receipt)
        body = {'version': 1, 'generation': state['generation'],
                'channel_id': state['pools']['main']['channel_id'],
                'deleted_message_id': RECEIPT['message_id'], 'confirm_resend': True}
        path = self.base + '/main/send'
        fake = AsyncMock(side_effect=[CHANNEL, {'id': RECEIPT['message_id']}, CHANNEL, DiscordItemNotFound(10008)])
        with patch('cwl_web.announcement_recovery.discord', fake):
            exists = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(exists.status, 409)
            sent = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(sent.status, 202, await sent.text())
            duplicate = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(duplicate.status, 409)
        self.assertEqual(fake.await_count, 4)
        self.assertTrue(all(call.args[1] == 'GET' for call in fake.call_args_list))
        current = await self.state()
        self.assertEqual(current['pools']['main']['delivery']['status'], 'pending')
        self.assertFalse(current['pools']['main']['sequence']['announcement_confirmed'])
        history = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, state['cycle'])
        self.assertEqual(history['deliveries'][-1]['status'], 'deleted_confirmed')

    async def test_closing_update_only_queues_replacement_for_confirmed_deletion(self):
        from utils.cwl_roster_image_store import RosterImageStore
        from utils.cwl_roster_messages import closing_message
        await self.bind()
        await self.publish()
        images = RosterImageStore(self.app['store'])
        images.prepare_sequence(sequence_id='a'*24, sid=self.sid, pool='main', cycle='2026-10',
            version=1, generation='g', channel=RECEIPT['channel_id'], actor='staff',
            plan={'clans': [], 'closing': {'request_id': 'b'*24, 'payload': closing_message()}})
        with self.app['store'].tx() as db:
            db.execute("UPDATE roster_image_sequences SET status='ready',announcement_message_id='987654321098765400'")
        images.claim_sequence_closing('a'*24)
        images.finish_sequence_closing('a'*24, status='posted', message=RECEIPT['message_id'])
        body = {'sequence_id': 'a'*24, 'message_id': RECEIPT['message_id']}
        path = self.base + '/main/sequence/closing/update'
        fake = AsyncMock(side_effect=[CHANNEL, {'id': RECEIPT['message_id']}, CHANNEL, DiscordItemNotFound(10008)])
        with patch('cwl_web.announcement_recovery.discord', fake):
            self.assertEqual((await self.call('POST', path, self.member, json=body)).status, 403)
            response = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(response.status, 200, await response.text())
            self.assertEqual(images.sequence('a'*24)['status'], 'complete')
            response = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(response.status, 202, await response.text())
            self.assertEqual((await self.call('POST', path, self.owner, json=body)).status, 409)
        self.assertEqual(images.sequence('a'*24)['status'], 'ready')
        self.assertIsNone(images.closing_receipt('a'*24))
        self.assertTrue(all(call.args[1] == 'GET' for call in fake.call_args_list))
