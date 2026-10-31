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

    async def test_staff_assumption_requires_send_permission_and_never_queues_announcement(self):
        from utils.cwl_roster_image_store import RosterImageStore
        from utils.cwl_web_bridge import get_roster_send_status, mark_worker_alive
        from cwl_web.manage_bridge import GUILD_ID
        await self.bind()
        await self.publish()
        await mark_worker_alive(self.mongo, GUILD_ID)
        state = await self.state()
        channel = state['pools']['main']['channel_id']
        sent = await self.call('POST', self.base + '/main/send', self.owner, json={
            'version': 1, 'generation': state['generation'], 'channel_id': channel})
        self.assertEqual(sent.status, 202, await sent.text())
        await cwl_campaign.record_delivery(self.mongo, GUILD_ID, state['cycle'], {
            'occurrence_id': cwl_campaign.occurrence_id(state['cycle'], 'roster', 'main'),
            'status': 'sent', 'channel_id': int(channel), 'message_id': None})
        storage = RosterImageStore(self.app['store'])
        job = storage.pool_sequence(self.sid, 'main')
        before = await get_roster_send_status(self.mongo, GUILD_ID, state['cycle'], 'main')
        body = {'sequence_id': job['sequence_id'], 'version': 1,
                'channel_id': channel, 'confirm_no_pings': True}
        path = self.base + '/main/sequence/assume'
        import json
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO grants(user_id,granted_by,permissions) VALUES(?,?,?)',
                       ('200', 'owner', json.dumps(['cwl_roster'])))
        limited = self.auth('200')
        with patch('utils.cwl_web_bridge.queue_roster_send', AsyncMock(side_effect=AssertionError('Must never queue an announcement'))):
            denied = await self.call('POST', path, self.member, json=body)
            self.assertEqual(denied.status, 403)
            self.assertEqual((await self.call('POST', path, limited, json=body)).status, 403)
            # Exercise the explicit send gate independently of the generic route
            # permission map, which also rejects this user in the HTTP case above.
            with patch('cwl_web.cwl_permissions.mutation_permission', return_value='cwl_roster'):
                self.assertEqual((await self.call('POST', path, limited, json=body)).status, 403)
            allowed = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(allowed.status, 202, await allowed.text())
            duplicate = await self.call('POST', path, self.owner, json=body)
            self.assertEqual(duplicate.status, 409)
        self.assertEqual(await get_roster_send_status(self.mongo, GUILD_ID, state['cycle'], 'main'), before)
        self.assertEqual(storage.sequence(job['sequence_id'])['status'], 'ready')

    async def test_concurrent_resend_posts_one_announcement_then_images_then_closing(self):
        from types import SimpleNamespace
        from cwl_web.manage_bridge import GUILD_ID
        from cwl_web.roster_sequence_jobs import SequenceJobs
        from utils import cwl_web_bridge
        from utils.cwl_roster_image_store import RosterImageStore
        from utils.cwl_roster_messages import clan_image_message, closing_message
        await self.bind()
        await self.publish()
        await cwl_web_bridge.mark_worker_alive(self.mongo, GUILD_ID)
        state = await self.state()
        channel = state['pools']['main']['channel_id']
        occurrence = cwl_campaign.occurrence_id(state['cycle'], 'roster', 'main')
        receipt = {'occurrence_id': occurrence, 'status': 'sent', 'channel_id': channel,
                   'message_id': RECEIPT['message_id']}
        await cwl_campaign.record_delivery(self.mongo, GUILD_ID, state['cycle'], receipt)
        plan = {'clans': [{'tag': '#AAA', 'request_id': 'b'*24, 'frozen': {
            'name': 'Clan', 'league': 'Gold', 'season_label': 'October',
            'payload': clan_image_message('Clan', '#AAA')}}],
            'closing': {'request_id': 'c'*24, 'payload': closing_message()}}
        async def deleted(*args, **kwargs):
            await asyncio.sleep(0)
            if '/messages/' in args[2]:
                raise DiscordItemNotFound(10008)
            return CHANNEL
        body = {'version': 1, 'generation': state['generation'], 'channel_id': channel,
                'deleted_message_id': RECEIPT['message_id'], 'confirm_resend': True}
        with patch('cwl_web.announcement_recovery.discord', deleted), \
             patch('cwl_web.roster_sequence_review.frozen_plan', AsyncMock(return_value=plan)):
            responses = await asyncio.gather(*[
                self.call('POST', self.base+'/main/send', self.owner, json=body) for _ in range(2)])
        self.assertEqual(sorted(response.status for response in responses), [202, 409])
        events = []
        async def sender(*args, **kwargs):
            events.append('announcement')
            await cwl_campaign.record_delivery(self.mongo, GUILD_ID, state['cycle'], receipt | {'message_id': '123456789012345680'})
            return True
        await cwl_web_bridge.process_pending_roster_requests(self.mongo, sender, guild_id=GUILD_ID)
        async def image(job, item):
            self.assertEqual(item['frozen']['payload']['allowed_mentions'], {'parse': []})
            events.append('image'); return '123456789012345681'
        async def closing(job, item):
            self.assertEqual(item['payload']['allowed_mentions'], {'parse': []})
            events.append('closing'); return '123456789012345682'
        jobs = SequenceJobs(self.app); jobs.authorized = AsyncMock(return_value=True)
        sequence = RosterImageStore(self.app['store']).pool_sequence(self.sid, 'main')
        with patch('cwl_web.roster_sequence_jobs.SequenceTransport', return_value=SimpleNamespace(image=image, closing=closing)):
            await jobs.advance(sequence['sequence_id'])
            await jobs.advance(sequence['sequence_id'])
        self.assertEqual(events, ['announcement', 'image', 'closing'])

    async def refused_resend_preserves_occurrence(self, uncertain):
        from copy import deepcopy
        from utils import cwl_web_bridge
        from utils.cwl_roster_image_store import RosterImageStore
        from cwl_web.manage_bridge import GUILD_ID
        await self.bind()
        await self.publish()
        await cwl_web_bridge.mark_worker_alive(self.mongo, GUILD_ID)
        state = await self.state()
        channel = state['pools']['main']['channel_id']
        response = await self.call('POST', self.base+'/main/send', self.owner, json={
            'version': 1, 'generation': state['generation'], 'channel_id': channel})
        self.assertEqual(response.status, 202, await response.text())
        receipt = {'occurrence_id': cwl_campaign.occurrence_id(state['cycle'], 'roster', 'main'),
                   'status': 'sent', 'channel_id': channel, 'message_id': RECEIPT['message_id']}
        async def sender(*args, **kwargs):
            await cwl_campaign.record_delivery(self.mongo, GUILD_ID, state['cycle'], receipt)
            return True
        await cwl_web_bridge.process_pending_roster_requests(self.mongo, sender, guild_id=GUILD_ID)
        storage = RosterImageStore(self.app['store'])
        with self.app['store'].tx() as db:
            db.execute("UPDATE roster_image_sequences SET status=?,announcement_message_id=?",
                       ('stopped' if uncertain else 'ready', RECEIPT['message_id']))
            if uncertain:
                db.execute("INSERT INTO roster_image_posts(season_id,pool,clan_tag,channel_id,status,request_id,posted_by) VALUES(?,'main','#AAA',?,'uncertain','fixture','staff')", (self.sid,channel))
        before = deepcopy(await cwl_campaign.load_campaign(self.mongo, GUILD_ID, state['cycle']))
        sequence = storage.pool_sequence(self.sid,'main')
        posts = self.app['store'].rows('SELECT * FROM roster_image_posts')
        body = {'version': 1, 'generation': state['generation'], 'channel_id': channel,
                'deleted_message_id': RECEIPT['message_id'], 'confirm_resend': True}
        async def deleted(*args, **kwargs):
            if '/messages/' in args[2]: raise DiscordItemNotFound(10008)
            return CHANNEL
        with patch('cwl_web.announcement_recovery.discord', deleted):
            refused = await self.call('POST', self.base+'/main/send', self.owner, json=body)
            self.assertEqual(refused.status,409,await refused.text())
            self.assertEqual(await cwl_campaign.load_campaign(self.mongo,GUILD_ID,state['cycle']),before)
            self.assertEqual(storage.pool_sequence(self.sid,'main'),sequence)
            self.assertEqual(self.app['store'].rows('SELECT * FROM roster_image_posts'), posts)
            with self.app['store'].tx() as db:
                db.execute("UPDATE roster_image_sequences SET status='stopped'")
                db.execute("UPDATE roster_image_posts SET status='failed'")
            valid = await self.call('POST',self.base+'/main/send',self.owner,json=body)
            self.assertEqual(valid.status,202,await valid.text())

    async def test_ready_sequence_refuses_resend_without_reopening_native_receipt(self):
        await self.refused_resend_preserves_occurrence(False)

    async def test_uncertain_image_refuses_resend_without_reopening_native_receipt(self):
        await self.refused_resend_preserves_occurrence(True)
