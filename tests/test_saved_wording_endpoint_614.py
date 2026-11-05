"""Field-scoped saved wording updates over the existing Manage HTTP paths."""
import copy
import unittest
from unittest.mock import patch

from test_cwl_web_manage_bridge import ManageBridgeTests, GUILD_ID
from utils import cwl_campaign


class SavedWordingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = ManageBridgeTests.asyncSetUp
    asyncTearDown = ManageBridgeTests.asyncTearDown
    auth = ManageBridgeTests.auth
    call = ManageBridgeTests.call
    revision = ManageBridgeTests.revision
    bind = ManageBridgeTests.bind
    state = ManageBridgeTests.state

    async def test_lazy_guide_only_for_legacy_and_current_button_layouts(self):
        await self.bind()
        key = cwl_campaign.cycle_id(GUILD_ID, '2026-10')
        for new_copy in (False, True):
            with self.subTest(new_copy=new_copy):
                campaign = cwl_campaign.default_campaign(new_copy=new_copy)
                buttons = campaign['messages']['roster']['variants']['lazy']['buttons']
                self.assertEqual(len(buttons), 4 if new_copy else 2)
                self.assertEqual(buttons[-1]['label'], 'LazyCWL Guide')
                buttons[-1]['url'] = 'https://example.com/custom-guide'
                buttons[-1]['style'] = 5
                self.mongo.bot_config.documents[key] = {
                    '_id': key, 'kind': 'cwl_campaign_cycle', 'guild_id': GUILD_ID,
                    'cycle': '2026-10', 'revision': 1, 'activated': True, 'campaign': campaign,
                }
                state = await self.state()
                original = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, '2026-10')
                variant = original['campaign']['messages']['roster']['variants']['lazy']
                body = {'generation': state['generation'], 'channel_id': str(variant['destination_channel_id']),
                        'body': variant['body'], 'roster_url': variant['buttons'][0]['url'],
                        'roster_button_label': 'Lazy CWL guide'}
                before = copy.deepcopy(self.mongo.bot_config.documents)
                self.assertEqual((await self.call('PATCH', self.base + '/lazy', self.member, json=body)).status, 403)
                for value in ('', 'My clan assignments', 'LazyCWL Guide', None, True, {'label': 'x'}):
                    rejected = await self.call('PATCH', self.base + '/lazy', self.owner,
                                               json={**body, 'roster_button_label': value})
                    self.assertEqual(rejected.status, 400, await rejected.text())
                self.assertEqual((await self.call('PATCH', self.base + '/main', self.owner, json=body)).status, 400)
                for field, value in (('channel_id', '111111111111111111'), ('body', 'changed'),
                                     ('roster_url', 'https://example.com/other')):
                    rejected = await self.call('PATCH', self.base + '/lazy', self.owner, json={**body, field: value})
                    self.assertEqual(rejected.status, 400, await rejected.text())
                self.assertEqual((await self.call('PATCH', self.base + '/lazy', self.owner,
                                                  json={**body, 'button_style': 1})).status, 400)
                self.assertEqual(self.mongo.bot_config.documents, before)
                response = await self.call('PATCH', self.base + '/lazy', self.owner, json=body)
                self.assertEqual(response.status, 200, await response.text())
                after = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, '2026-10')
                expected = copy.deepcopy(original['campaign'])
                expected['messages']['roster']['variants']['lazy']['buttons'][-1]['label'] = 'Lazy CWL guide'
                self.assertEqual(after['campaign'], expected)
                committed = copy.deepcopy(self.mongo.bot_config.documents)
                stale = await self.call('PATCH', self.base + '/lazy', self.owner, json=body)
                self.assertEqual(stale.status, 409)
                self.assertEqual(self.mongo.bot_config.documents, committed)

    async def test_missing_or_ambiguous_lazy_guide_never_writes(self):
        await self.bind()
        key = cwl_campaign.cycle_id(GUILD_ID, '2026-10')
        for scenario in ('missing', 'duplicate'):
            with self.subTest(scenario=scenario):
                campaign = cwl_campaign.default_campaign(new_copy=False)
                buttons = campaign['messages']['roster']['variants']['lazy']['buttons']
                if scenario == 'missing':
                    buttons.pop()
                else:
                    buttons.append(copy.deepcopy(buttons[-1]))
                self.mongo.bot_config.documents[key] = {
                    '_id': key, 'kind': 'cwl_campaign_cycle', 'guild_id': GUILD_ID,
                    'cycle': '2026-10', 'revision': 1, 'activated': True, 'campaign': campaign,
                }
                state = await self.state()
                item = state['pools']['lazy']
                body = {'generation': state['generation'], 'channel_id': item['channel_id'],
                        'body': item['body'], 'roster_url': item['buttons'][0]['url'],
                        'roster_button_label': 'Lazy CWL guide'}
                before = copy.deepcopy(self.mongo.bot_config.documents)
                response = await self.call('PATCH', self.base + '/lazy', self.owner, json=body)
                self.assertEqual(response.status, 409, await response.text())
                self.assertEqual(self.mongo.bot_config.documents, before)

    async def test_reminder_marker_unversioned_to_128_only_and_no_duplicate_check_lines(self):
        with patch.object(cwl_campaign, 'cycle_key', return_value='2029-11'):
            cycle = '2029-11'
            campaign = cwl_campaign.default_campaign(new_copy=False)
            key = cwl_campaign.cycle_id(GUILD_ID, cycle)
            self.mongo.bot_config.documents[key] = {
                '_id': key, 'kind': 'cwl_campaign_cycle', 'guild_id': GUILD_ID,
                'cycle': cycle, 'revision': 1, 'activated': True, 'campaign': campaign,
            }
            endpoint = f'/seasons/{self.sid}/manage-reminders'
            async def read():
                response = await self.call('GET', endpoint, self.owner)
                self.assertEqual(response.status, 200, await response.text())
                return await response.json()
            state = await read()
            self.assertNotIn('default_copy_version', state['campaign'])
            variants = {pool: {'body': 'Fixture instructions\n\n' + cwl_campaign.CURRENT_SIGNUP_CHECK_LINE}
                        for pool in ('main', 'lazy')}
            missing = {pool: {'body': 'Other fixture instructions'} for pool in ('main', 'lazy')}
            body = {'generation': state['generation'], 'repeat_monthly': False,
                    'patch': {'default_copy_version': 128,
                              'messages': {'reminder:1': {'variants': variants},
                                           'reminder:2': {'variants': missing}}}}
            before = copy.deepcopy(self.mongo.bot_config.documents)
            self.assertEqual((await self.call('PATCH', endpoint, self.member, json=body)).status, 403)
            for wrong in (127, 129, None, True, '128'):
                invalid = copy.deepcopy(body)
                invalid['patch']['default_copy_version'] = wrong
                response = await self.call('PATCH', endpoint, self.owner, json=invalid)
                self.assertEqual(response.status, 400, await response.text())
            self.assertEqual(self.mongo.bot_config.documents, before)
            response = await self.call('PATCH', endpoint, self.owner, json=body)
            self.assertEqual(response.status, 200, await response.text())
            saved = await cwl_campaign.load_campaign(self.mongo, GUILD_ID, cycle)
            self.assertEqual(saved['campaign']['default_copy_version'], 128)
            for pool in ('main', 'lazy'):
                text = saved['campaign']['messages']['reminder:1']['variants'][pool]['body']
                self.assertEqual(text, variants[pool]['body'])
                self.assertNotIn(cwl_campaign.SIGNUP_CHECK_LINE, text)
                self.assertEqual(text.count('Check my signups'), 1)
                normalized = cwl_campaign.normalize_signup_entry(saved['campaign'])
                self.assertEqual(normalized['messages']['reminder:1']['variants'][pool]['body'], text)
                new_line = saved['campaign']['messages']['reminder:2']['variants'][pool]['body']
                self.assertEqual(new_line, missing[pool]['body'] + '\n\n' + cwl_campaign.CURRENT_SIGNUP_CHECK_LINE)
                self.assertNotIn(cwl_campaign.SIGNUP_CHECK_LINE, new_line)
                self.assertEqual(new_line.count('Check my signups'), 1)
            committed = copy.deepcopy(self.mongo.bot_config.documents)
            self.assertEqual((await self.call('PATCH', endpoint, self.owner, json=body)).status, 409)
            self.assertEqual(self.mongo.bot_config.documents, committed)
            current = await read()
            for value in (128, 127, 129):
                invalid = {'generation': current['generation'], 'repeat_monthly': False,
                           'patch': {'default_copy_version': value}}
                self.assertEqual((await self.call('PATCH', endpoint, self.owner, json=invalid)).status, 400)
                self.assertEqual(self.mongo.bot_config.documents, committed)
