"""Dashboard account refresh is authenticated, isolated, and coalesced."""

import asyncio
import hashlib
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.providers import LiveProviders, ProviderUnavailable


class AccountProviders:
    def __init__(self):
        self.calls = []
        self.release = None
        self.fail = False

    async def linked_tags(self, user_id):
        self.calls.append(str(user_id))
        if self.release is not None:
            await self.release.wait()
        if self.fail:
            raise ProviderUnavailable("Linked-account service unavailable")
        return {"#P2Y": True} if str(user_id) == "100" else {"#Q2Y": False}

    async def player(self, value):
        return {"tag": value, "name": value, "town_hall": 16,
                "current_clan_tag": "#R2Y", "current_clan_name": "Family",
                "current_clan_badge_url": None}

    async def weights(self, tags):
        return {"#P2Y": {"weight": 135000}}

    async def family_clans(self):
        return {"clans": [{"tag": "#R2Y", "name": "Family", "type": "Tactical"}]}


class DashboardAccountTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.providers = AccountProviders()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "cwl.sqlite"),
                              providers=self.providers, secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.a = self.auth("100")
        self.b = self.auth("200")

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def auth(self, user_id):
        raw, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) "
                       "VALUES (?,?,?,?,?,?)",
                       (hashlib.sha256(raw.encode()).hexdigest(), user_id, user_id,
                        0, csrf, int(time.time()) + 900))
        return {"Cookie": "cwl_session=" + raw}

    async def get(self, headers=None):
        return await self.client.get("/api/cwl/dashboard/accounts", headers=headers)

    async def progressive(self, headers=None, refresh=False):
        return await self.client.get('/api/cwl/linked-accounts?background=1' + ('&refresh=1' if refresh else ''), headers=headers)

    async def finish_progressive(self, user='100'):
        job = self.app['account_display_jobs'].get(user)
        if job:
            await job

    async def test_progressive_shows_fast_account_before_slow_and_shares_reads(self):
        release = asyncio.Event()
        self.providers.linked_tags = AsyncMock(return_value={'#P2Y': True, '#SLOW': True})
        original = self.providers.player
        async def player(tag):
            if tag == '#SLOW':
                await release.wait()
            return await original(tag)
        self.providers.player = AsyncMock(side_effect=player)
        response = await asyncio.wait_for(self.progressive(self.a), .5)
        self.assertTrue((await response.json())['updating'])
        for _ in range(100):
            if '#P2Y' in self.app['account_display_states']['100']['accounts']:
                break
            await asyncio.sleep(.001)
        data = await (await self.progressive(self.a)).json()
        self.assertTrue(data['updating'])
        self.assertEqual([row['tag'] for row in data['accounts']], ['#P2Y'])
        dashboard = await self.client.get('/api/cwl/dashboard/accounts?background=1', headers=self.a)
        self.assertEqual((await dashboard.json())['accounts'], data['accounts'])
        await self.progressive(self.a, refresh=True)
        self.providers.linked_tags.assert_awaited_once()
        release.set()
        await self.finish_progressive()
        final = await (await self.progressive(self.a)).json()
        self.assertFalse(final['updating'])
        self.assertEqual(final['status'], 'ok')
        self.assertEqual(len(final['accounts']), 2)
        self.assertEqual(self.providers.player.await_count, 2)

    async def test_large_slow_member_does_not_block_another_member(self):
        release = asyncio.Event()
        async def links(uid):
            return {f'#SLOW{i}': True for i in range(30)} if uid == '100' else {'#Q2Y': True}
        original = self.providers.player
        async def player(tag):
            if tag.startswith('#SLOW'): await release.wait()
            return await original(tag)
        self.providers.linked_tags = links
        self.providers.player = player
        await self.progressive(self.a)
        await asyncio.sleep(.01)
        await self.progressive(self.b)
        await asyncio.wait_for(self.finish_progressive('200'), 1)
        other = await (await self.progressive(self.b)).json()
        self.assertEqual(other['status'], 'ok')
        self.assertEqual([row['tag'] for row in other['accounts']], ['#Q2Y'])
        self.assertIn('100', self.app['account_display_jobs'])
        release.set()
        await self.finish_progressive()

    async def test_progressive_one_failure_keeps_healthy_account_and_reports_partial(self):
        self.providers.linked_tags = AsyncMock(return_value={'#P2Y': True, '#FAIL': True})
        original = self.providers.player
        async def player(tag):
            if tag == '#FAIL': raise ProviderUnavailable('offline')
            return await original(tag)
        self.providers.player = player
        await self.progressive(self.a)
        await self.finish_progressive()
        data = await (await self.progressive(self.a)).json()
        self.assertFalse(data['updating'])
        self.assertEqual(data['status'], 'partial')
        self.assertTrue(data['error'])
        self.assertEqual([row['tag'] for row in data['accounts']], ['#P2Y'])

    async def test_progressive_auth_isolation_and_explicit_refresh_removes_unlinked(self):
        self.assertEqual((await self.progressive()).status, 401)
        self.assertFalse(self.app['account_display_states'])
        await self.progressive(self.a)
        await self.finish_progressive()
        await self.progressive(self.b)
        await self.finish_progressive('200')
        self.assertEqual([a['tag'] for a in (await (await self.progressive(self.b)).json())['accounts']], ['#Q2Y'])
        self.providers.linked_tags = AsyncMock(return_value={})
        fresh = await (await self.progressive(self.a, refresh=True)).json()
        self.assertEqual(fresh['accounts'], [])
        await self.finish_progressive()
        final = await (await self.progressive(self.a)).json()
        self.assertEqual(final['accounts'], [])
        self.assertEqual(final['status'], 'ok')
        self.assertEqual(final['total'], 0)

    async def test_progressive_failed_link_lookup_never_means_empty_success(self):
        self.providers.fail = True
        await self.progressive(self.a)
        await self.finish_progressive()
        data = await (await self.progressive(self.a)).json()
        self.assertEqual(data['status'], 'partial')
        self.assertIsNone(data['total'])
        self.assertTrue(data['error'])
        self.providers.fail = False
        await self.progressive(self.a, refresh=True)
        await self.finish_progressive()
        self.assertEqual((await (await self.progressive(self.a)).json())['status'], 'ok')

    async def test_progressive_shutdown_cancels_provider_children(self):
        release = asyncio.Event()
        self.providers.player = AsyncMock(side_effect=lambda tag: None)
        started = asyncio.Event()
        stopped = asyncio.Event()
        async def player(tag):
            started.set()
            try: await release.wait()
            finally: stopped.set()
        self.providers.player = player
        await self.progressive(self.a)
        await asyncio.wait_for(started.wait(), 1)
        job = self.app['account_display_jobs']['100']
        await self.client.close()
        self.assertTrue(job.cancelled())
        self.assertTrue(stopped.is_set())
        self.assertFalse(self.app['account_display_states'])

    async def test_progressive_rejects_wrong_player_identity(self):
        self.providers.player = AsyncMock(return_value={'tag': '#OTHER'})
        await self.progressive(self.a)
        await self.finish_progressive()
        data = await (await self.progressive(self.a)).json()
        self.assertEqual(data['accounts'], [])
        self.assertEqual(data['status'], 'partial')

    async def test_weight_and_missing_weight(self):
        first = await self.get(self.a)
        self.assertEqual((await first.json())["accounts"][0]["war_weight"], 135000)
        missing = await self.get(self.b)
        self.assertIsNone((await missing.json())["accounts"][0]["war_weight"])

    async def test_weight_outage_does_not_hide_accounts(self):
        self.providers.weights = AsyncMock(side_effect=ProviderUnavailable("offline"))
        response = await self.get(self.a)
        self.assertEqual(response.status, 200)
        account = (await response.json())["accounts"][0]
        self.assertEqual(account["tag"], "#P2Y")
        self.assertIsNone(account["war_weight"])

    async def test_auth_and_per_user_cache(self):
        unauth = await self.get()
        self.assertEqual(unauth.status, 401)
        self.assertEqual(self.providers.calls, [])
        first = await self.get(self.a)
        self.assertEqual(first.status, 200)
        body = await first.json()
        self.assertEqual([row["tag"] for row in body["accounts"]], ["#P2Y"])
        self.assertTrue(body["accounts"][0]["verified"])
        self.assertEqual(body["accounts"][0]["family_clan_status"], "approved")
        self.assertEqual(body["status"], "ok")
        self.assertIn("ClashKing or ClashPerk", body["link_instruction"])
        self.assertIsNotNone(body["checked_at"])
        second = await self.get(self.a)
        self.assertEqual(await second.json(), body)
        self.assertEqual(self.providers.calls, ["100"])
        other = await self.get(self.b)
        self.assertEqual([row["tag"] for row in (await other.json())["accounts"]], ["#Q2Y"])
        self.assertEqual(self.providers.calls, ["100", "200"])
        self.app["dashboard_accounts_cache"]["100"] = (time.monotonic() - 1, body)
        refreshed = await self.get(self.a)
        self.assertEqual(refreshed.status, 200)
        self.assertEqual(self.providers.calls, ["100", "200", "100"])

    async def test_prunes_expired_inactive_users_and_bounds_cache(self):
        first = await self.get(self.a)
        self.assertEqual(first.status, 200)
        body = await first.json()
        cache = self.app["dashboard_accounts_cache"]
        cache["100"] = (time.monotonic() - 1, body)
        other = await self.get(self.b)
        self.assertEqual(other.status, 200)
        self.assertNotIn("100", cache)
        for index in range(1100):
            cache[f"inactive-{index}"] = (time.monotonic() + 60, body)
        refreshed = await self.get(self.a)
        self.assertEqual(refreshed.status, 200)
        self.assertLessEqual(len(cache), 1024)
        self.assertIn("100", cache)
        self.assertNotIn("inactive-0", cache)

    async def test_shutdown_cancels_and_drains_abandoned_refresh(self):
        self.providers.release = asyncio.Event()
        request = asyncio.create_task(self.get(self.a))
        for _ in range(100):
            if self.providers.calls:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(self.providers.calls, ["100"])
        refresh = self.app["dashboard_accounts_inflight"]["100"]
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)
        await self.client.close()
        self.assertTrue(refresh.cancelled())
        self.assertEqual(self.app["dashboard_accounts_inflight"], {})
        self.assertEqual(self.app["dashboard_accounts_cache"], {})

    async def test_coalesces_concurrent_requests(self):
        self.providers.release = asyncio.Event()
        requests = [asyncio.create_task(self.get(self.a)) for _ in range(3)]
        for _ in range(100):
            if self.providers.calls:
                break
            await asyncio.sleep(0.001)
        self.assertEqual(self.providers.calls, ["100"])
        self.providers.release.set()
        responses = await asyncio.gather(*requests)
        self.assertTrue(all(response.status == 200 for response in responses))
        bodies = await asyncio.gather(*(response.json() for response in responses))
        self.assertEqual(bodies[0], bodies[1])
        self.assertEqual(bodies[1], bodies[2])
        self.assertEqual(self.providers.calls, ["100"])

    async def test_failure_is_not_cached_and_can_retry(self):
        self.providers.fail = True
        failed = await self.get(self.a)
        self.assertEqual(failed.status, 503)
        self.assertNotIn("100", self.app["dashboard_accounts_cache"])
        self.providers.fail = False
        retried = await self.get(self.a)
        self.assertEqual(retried.status, 200)
        self.assertEqual(self.providers.calls, ["100", "100"])

    async def test_badge_url_uses_only_official_https_asset_host(self):
        provider = LiveProviders(coc_token="unused", mongo_uri="", routes={})
        body = {"tag": "#P2Y", "name": "Alpha", "townHallLevel": 16,
                "clan": {"tag": "#R2Y", "name": "Family", "badgeUrls": {
                    "medium": "https://evil.example/badges/200/badge.png",
                    "small": "https://api-assets.clashofclans.com/badges/70/badge.png"}}}
        provider._coc = AsyncMock(return_value=body)
        player = await provider.player("#P2Y")
        self.assertEqual(player["current_clan_badge_url"],
                         "https://api-assets.clashofclans.com/badges/70/badge.png")
        body["clan"]["badgeUrls"]["small"] = "http://api-assets.clashofclans.com/badges/70/badge.png"
        self.assertIsNone((await provider.player("#P2Y"))["current_clan_badge_url"])
