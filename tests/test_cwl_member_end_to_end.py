"""Simulated Discord controls -> real loopback bridge -> dashboard-owned SQLite."""
import unittest
from unittest.mock import patch

from extensions.commands import cwl_member as ui
from utils.cwl_member_client import request
from test_cwl_discord_member import Context
import test_cwl_discord_member_service as bridge_tests
import test_cwl_web_foundation as foundation_tests


class MemberEndToEndTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = bridge_tests.DiscordMemberBridgeTests.asyncSetUp
    asyncTearDown = bridge_tests.DiscordMemberBridgeTests.asyncTearDown
    auth = foundation_tests.WebFoundationTests.auth

    async def click(self, token, session, action, values=()):
        ctx = Context(user_id=100, values=values)
        await ui._handle(ctx, f'{token}:{session.version}', action)
        return ctx

    async def test_discord_save_dashboard_read_edit_conflict_and_withdraw(self):
        with patch.dict('os.environ', {'CWL_DISCORD_BRIDGE_URL': str(self.client.make_url('')).rstrip('/')}):
            session = ui.MemberSession(100, ui.WARRIORS_UNITED_GUILD_ID, ui.time.monotonic())
            session.view = await request('view', user_id=100, guild_id=session.guild_id)
            token = 'e2e'
            ui._sessions[token] = session
            await self.click(token, session, 'signup')
            await self.click(token, session, 'pool_lazy')
            await self.click(token, session, 'select', ('#P2Y', '#Q2Y'))
            await self.click(token, session, 'review')
            self.assertEqual(self.app['store'].rows('SELECT * FROM signups'), [])
            ctx = await self.click(token, session, 'confirm')
            self.assertIn('Signup saved', str(ctx.interaction.edits))
            member_auth = self.auth('100')
            response = await self.client.get(f'/api/cwl/seasons/{self.sid}/signups', headers=member_auth)
            self.assertEqual(response.status, 200)
            self.assertEqual({x['tag'] for x in (await response.json())['signups']}, {'#P2Y', '#Q2Y'})
            # Keep a review in Discord, then change this signup through real dashboard HTTP.
            await self.click(token, session, 'my_signups')
            await self.click(token, session, 'signup_pick', ('#Q2Y',))
            await self.click(token, session, 'withdraw')
            response = await self.client.post(f'/api/cwl/seasons/{self.sid}/signups', headers=member_auth,
                json={'pool': 'main', 'accounts': [{'tag': '#Q2Y', 'prefer_crystal_1_or_lower': True,
                                                   'move_from_pool': 'lazy'}]})
            self.assertEqual(response.status, 200)
            ctx = await self.click(token, session, 'withdraw_confirm')
            self.assertIn('Signups changed', str(ctx.interaction.edits))
            self.assertEqual(self.app['store'].one('SELECT pool FROM signups WHERE tag=?', ('#Q2Y',))['pool'], 'main')
            await self.click(token, session, 'my_signups')
            await self.click(token, session, 'signup_pick', ('#Q2Y',))
            await self.click(token, session, 'withdraw')
            await self.click(token, session, 'withdraw_confirm')
            response = await self.client.get(f'/api/cwl/seasons/{self.sid}/signups', headers=member_auth)
            self.assertEqual([x['tag'] for x in (await response.json())['signups']], ['#P2Y'])
            self.assertGreater(self.member_check.await_count, 5)
            ui._sessions.pop(token, None)

    async def test_provider_unverified_link_is_visible_and_saves_through_discord(self):
        self.providers.links["100"]["#Q2Y"] = False
        with patch.dict('os.environ', {'CWL_DISCORD_BRIDGE_URL': str(self.client.make_url('')).rstrip('/')}):
            session = ui.MemberSession(100, ui.WARRIORS_UNITED_GUILD_ID, ui.time.monotonic())
            session.view = await request('view', user_id=100, guild_id=session.guild_id, include_accounts=False)
            token = 'e2e-linked-parity'
            ui._sessions[token] = session
            try:
                await self.click(token, session, 'signup')
                await self.click(token, session, 'pool_lazy')
                menu = ui._components(token, session)[0].components[0]
                self.assertEqual({option.value for option in menu.options}, {'#P2Y', '#Q2Y'})
                await self.click(token, session, 'select', ('#P2Y', '#Q2Y'))
                await self.click(token, session, 'review')
                await self.click(token, session, 'confirm')
                response = await self.client.get(f'/api/cwl/seasons/{self.sid}/signups', headers=self.auth('100'))
                self.assertEqual(response.status, 200)
                self.assertEqual({row['tag'] for row in (await response.json())['signups']}, {'#P2Y', '#Q2Y'})
            finally:
                ui._sessions.pop(token, None)

    async def test_entry_owner_rejection_leaves_original_panel_untouched(self):
        ctx = Context(user_id=200)
        await ui.start(ctx, f"100:{ui.WARRIORS_UNITED_GUILD_ID}")
        self.assertEqual(ctx.interaction.edits, [])
        self.assertIn("belongs to another member", str(ctx.followups))
        self.member_check.assert_not_awaited()
        self.assertEqual(self.app['store'].rows('SELECT * FROM signups'), [])

    async def test_empty_link_recovery_refreshes_without_saving(self):
        with patch.dict('os.environ', {'CWL_DISCORD_BRIDGE_URL': str(self.client.make_url('')).rstrip('/')}):
            self.providers.links['100'] = {}
            session = ui.MemberSession(100, ui.WARRIORS_UNITED_GUILD_ID, ui.time.monotonic())
            session.view = await request('view', user_id=100, guild_id=session.guild_id)
            token = 'e2e-empty'
            ui._sessions[token] = session
            await self.click(token, session, 'signup')
            ctx = await self.click(token, session, 'pool_lazy')
            self.assertIn('Refresh accounts', str(ctx.interaction.edits))
            self.providers.links['100'] = {'#P2Y': True}
            await self.click(token, session, 'refresh')
            await self.click(token, session, 'pool_lazy')
            self.assertEqual(session.screen, 'select_accounts')
            self.assertEqual(session.view['accounts'][0]['tag'], '#P2Y')
            self.assertEqual(self.app['store'].rows('SELECT * FROM signups'), [])
            ui._sessions.pop(token, None)
