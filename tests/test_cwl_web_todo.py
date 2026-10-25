"""Personal Todo endpoint keeps account scope and incomplete reads visible."""

import asyncio
import hashlib
import secrets
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from aiohttp.test_utils import TestClient, TestServer

from cwl_web import create_app
from cwl_web.providers import ProviderUnavailable
from utils import todo_data


class Providers:
    def __init__(self):
        self.fail = False
        self.empty = False

    async def linked_tags(self, user_id):
        if self.fail:
            raise RuntimeError("link service unavailable")
        if self.empty:
            return {}
        return {"#P2Y": True} if user_id == "100" else {"#Q2Y": True}


class FakeClient:
    async def close(self):
        pass


class TodoWebTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.games_patch = patch("cwl_web.todo_games.build_games_view", new=AsyncMock(return_value={
            "ok": True, "note": "", "notes": [], "unavailable": "", "incomplete": "", "rows": []}))
        self.games_patch.start()
        self.providers = Providers()
        self.app = create_app(db_path=str(Path(self.tmp.name) / "web.sqlite"),
                              providers=self.providers, secure_cookies=False)
        self.client = TestClient(TestServer(self.app))
        await self.client.start_server()
        self.app["todo_client"] = FakeClient()

    async def asyncTearDown(self):
        await self.client.close()
        self.games_patch.stop()
        self.tmp.cleanup()

    def auth(self, user_id):
        raw = secrets.token_urlsafe(24)
        with self.app["store"].tx() as db:
            db.execute("INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) "
                       "VALUES (?,?,?,?,?,?)", (hashlib.sha256(raw.encode()).hexdigest(),
                       user_id, user_id, 0, "csrf", int(time.time()) + 900))
        return {"Cookie": "cwl_session=" + raw}

    async def test_auth_and_user_scope(self):
        unauth = await self.client.get("/api/cwl/todo")
        self.assertEqual(unauth.status, 401)
        seen = []

        async def accounts(client, tags, **kwargs):
            seen.append(tags)
            tag = tags[0]
            return [todo_data.Account(tag, tag, "#R2Y", "Family", 16)], []

        async def view(*args, **kwargs):
            return todo_data.ViewData()

        async def history(*args):
            return {}, ""

        with patch("cwl_web.todo.todo_data.fetch_accounts", side_effect=accounts), \
             patch("cwl_web.todo.todo_data.build_war_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_cwl_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_raid_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_blocked_view", side_effect=view), \
             patch("cwl_web.todo._history", side_effect=history):
            a = await self.client.get("/api/cwl/todo", headers=self.auth("100"))
            b = await self.client.get("/api/cwl/todo", headers=self.auth("200"))
        self.assertEqual(a.status, 200)
        self.assertEqual(b.status, 200)
        self.assertEqual([x["tag"] for x in (await a.json())["accounts"]], ["#P2Y"])
        self.assertEqual([x["tag"] for x in (await b.json())["accounts"]], ["#Q2Y"])
        self.assertEqual(seen, [["#P2Y"], ["#Q2Y"]])

    async def test_partial_and_failed_view_never_all_clear(self):
        async def accounts(*args, **kwargs):
            return [todo_data.Account("#P2Y", "Scout", "#R2Y", "Family", 16)], ["#Q2Y: timeout"]

        async def good(*args, **kwargs):
            row = todo_data.Row("Scout", "#P2Y", "Family", "#R2Y", 1, 2, None)
            return todo_data.ViewData(rows=[row])

        async def failed(*args, **kwargs):
            raise TimeoutError()

        async def history(*args):
            return {}, ""

        with patch("cwl_web.todo.todo_data.fetch_accounts", side_effect=accounts), \
             patch("cwl_web.todo.todo_data.build_war_view", side_effect=good), \
             patch("cwl_web.todo.todo_data.build_cwl_view", side_effect=failed), \
             patch("cwl_web.todo.todo_data.build_raid_view", side_effect=good), \
             patch("cwl_web.todo.todo_data.build_blocked_view", side_effect=good), \
             patch("cwl_web.todo._history", side_effect=history):
            response = await self.client.get("/api/cwl/todo", headers=self.auth("100"))
        body = await response.json()
        self.assertTrue(body["views"]["war"]["ok"])
        self.assertIn("could not be checked", body["views"]["war"]["incomplete"])
        self.assertEqual(body["views"]["war"]["rows"][0]["remaining"], 1)
        self.assertFalse(body["views"]["cwl"]["ok"])
        self.assertIn("could not be checked", body["views"]["cwl"]["note"])

    async def test_coalesces_same_user(self):
        calls = 0
        release = asyncio.Event()

        async def accounts(*args, **kwargs):
            nonlocal calls
            calls += 1
            await release.wait()
            return [todo_data.Account("#P2Y", "Scout", "#R2Y", "Family", 16)], []

        async def history(*args):
            return {}, ""

        async def view(*args, **kwargs):
            return todo_data.ViewData()

        with patch("cwl_web.todo.todo_data.fetch_accounts", side_effect=accounts), \
             patch("cwl_web.todo.todo_data.build_war_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_cwl_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_raid_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_blocked_view", side_effect=view), \
             patch("cwl_web.todo._history", side_effect=history):
            auth = self.auth("100")
            first = asyncio.create_task(self.client.get("/api/cwl/todo", headers=auth))
            second = asyncio.create_task(self.client.get("/api/cwl/todo", headers=auth))
            for _ in range(100):
                if calls:
                    break
                await asyncio.sleep(0.001)
            release.set()
            a, b = await asyncio.gather(first, second)
            self.assertEqual(await a.json(), await b.json())
            self.assertEqual(calls, 1)
            cached = await self.client.get("/api/cwl/todo", headers=auth)
            self.assertEqual(cached.status, 200)
            self.assertEqual(calls, 1)
            saved = self.app["todo_cache"]["100"][1]
            self.app["todo_cache"]["100"] = (time.monotonic() - 1, saved)
            refreshed = await self.client.get("/api/cwl/todo", headers=auth)
            self.assertEqual(refreshed.status, 200)
            self.assertEqual(calls, 2)

    async def test_total_failures_are_503_and_not_cached(self):
        auth = self.auth("100")
        self.providers.fail = True
        failed_links = await self.client.get("/api/cwl/todo", headers=auth)
        self.assertEqual(failed_links.status, 503)
        self.assertNotIn("100", self.app["todo_cache"])
        self.providers.fail = False
        self.app["todo_client"] = None
        with patch("cwl_web.todo.get_clash_client", side_effect=ProviderUnavailable("client down")):
            failed_client = await self.client.get("/api/cwl/todo", headers=auth)
        self.assertEqual(failed_client.status, 503)
        self.assertNotIn("100", self.app["todo_cache"])
        self.app["todo_client"] = FakeClient()
        async def no_accounts(*args, **kwargs):
            return [], ["#P2Y: timeout"]
        async def history(*args):
            return {}, ""
        with patch("cwl_web.todo.todo_data.fetch_accounts", side_effect=no_accounts), \
             patch("cwl_web.todo._history", side_effect=history):
            failed_players = await self.client.get("/api/cwl/todo", headers=auth)
        self.assertEqual(failed_players.status, 503)
        self.assertNotIn("100", self.app["todo_cache"])

    async def test_no_links_is_success_without_external_reads(self):
        self.providers.empty = True
        with patch("cwl_web.todo.get_clash_client") as clash, \
             patch("cwl_web.todo._history") as history:
            response = await self.client.get("/api/cwl/todo", headers=self.auth("100"))
        self.assertEqual(response.status, 200)
        body = await response.json()
        self.assertEqual(body["accounts"], [])
        self.assertEqual(body["views"]["war"]["rows"], [])
        self.assertTrue(body["views"]["war"]["ok"])
        clash.assert_not_called()
        history.assert_not_called()

    async def test_cancelled_refresh_cancels_games_task(self):
        from cwl_web.todo import _live_snapshot
        games_started = asyncio.Event()
        games_cancelled = asyncio.Event()
        war_started = asyncio.Event()

        async def accounts(*args, **kwargs):
            return [todo_data.Account("#P2Y", "Scout", "#R2Y", "Family", 16)], []

        async def history(*args):
            return {}, ""

        async def pending_war(*args, **kwargs):
            war_started.set()
            await asyncio.Event().wait()

        async def pending_games(*args):
            games_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                games_cancelled.set()

        async def view(*args, **kwargs):
            return todo_data.ViewData()

        with patch("cwl_web.todo.todo_data.fetch_accounts", side_effect=accounts), \
             patch("cwl_web.todo._history", side_effect=history), \
             patch("cwl_web.todo.todo_data.build_war_view", side_effect=pending_war), \
             patch("cwl_web.todo.todo_data.build_cwl_view", side_effect=view), \
             patch("cwl_web.todo.todo_data.build_raid_view", side_effect=view), \
             patch("cwl_web.todo_games.build_games_view", side_effect=pending_games):
            task = asyncio.create_task(_live_snapshot(self.app, ["#P2Y"]))
            await asyncio.wait_for(asyncio.gather(games_started.wait(), war_started.wait()), 1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(games_cancelled.is_set())

    async def test_background_returns_fast_views_before_slow_cwl_finishes(self):
        release = asyncio.Event()
        async def slow(*args, **kwargs):
            await release.wait()
            return todo_data.ViewData()
        with patch('cwl_web.todo.todo_data.fetch_accounts', new=AsyncMock(return_value=([todo_data.Account('#P2Y', 'Scout', '#R2Y', 'Home', 16)], []))), \
             patch('cwl_web.todo._history', new=AsyncMock(return_value=({}, ''))), \
             patch('cwl_web.todo.todo_data.build_war_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo.todo_data.build_raid_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo.todo_data.build_blocked_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo.todo_data.build_cwl_view', new=slow):
            headers = self.auth('100')
            response = await self.client.get('/api/cwl/todo?background=1', headers=headers)
            self.assertTrue((await response.json())['updating'])
            for _ in range(100):
                response = await self.client.get('/api/cwl/todo?background=1', headers=headers)
                body = await response.json()
                if body['snapshot'] and not body['snapshot']['views']['war'].get('loading'):
                    break
                await asyncio.sleep(.001)
            self.assertTrue(body['updating'])
            self.assertTrue(body['snapshot']['views']['war']['ok'])
            self.assertTrue(body['snapshot']['views']['cwl']['loading'])
            self.assertEqual(len(self.app['todo_inflight']), 1)
            release.set()
            await asyncio.gather(*list(self.app['todo_inflight'].values()))
            final = await (await self.client.get('/api/cwl/todo?background=1', headers=headers)).json()
            self.assertFalse(final['updating'])
            self.assertNotIn('loading', final['snapshot']['views']['cwl'])

    async def test_background_failure_stops_polling_without_restarting_job(self):
        self.providers.fail = True
        headers = self.auth('100')
        await self.client.get('/api/cwl/todo?background=1', headers=headers)
        await asyncio.gather(*list(self.app['todo_inflight'].values()), return_exceptions=True)
        body = await (await self.client.get('/api/cwl/todo?background=1', headers=headers)).json()
        self.assertFalse(body['updating'])
        self.assertTrue(body['error'])
        self.assertFalse(self.app['todo_inflight'])
        self.assertEqual((await self.client.get('/api/cwl/todo?background=1')).status, 401)

    async def test_slow_account_does_not_discard_completed_accounts(self):
        from cwl_web.todo import _task_accounts
        cancelled = asyncio.Event()
        async def fetch(client, tags, **kwargs):
            if tags == ['#SLOW']:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return [todo_data.Account(tags[0], 'Scout', '#R2Y', 'Home', 16)], []
        with patch('cwl_web.todo.todo_data.fetch_accounts', new=fetch), patch('cwl_web.todo.VIEW_TIMEOUT', .02):
            accounts, errors = await _task_accounts(None, ['#FAST', '#SLOW'], asyncio.Semaphore(8))
        self.assertEqual([a.tag for a in accounts], ['#FAST'])
        self.assertEqual(len(errors), 1)
        self.assertTrue(cancelled.is_set())

    async def test_slow_clan_keeps_successful_war_rows(self):
        from cwl_web.todo import _live_snapshot
        from types import SimpleNamespace
        account = todo_data.Account('#P2Y', 'Scout', '#R2Y', 'Home', 16)
        other = todo_data.Account('#Q2Y', 'Other', '#SLOW', 'Slow', 16)
        cancelled = asyncio.Event()
        async def war(client, tag, **kwargs):
            if tag == '#SLOW':
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return 'war', SimpleNamespace(state='inWar', end_time=None, start_time=None,
                attacks_per_member=2, clan=SimpleNamespace(tag='#R2Y', members=[SimpleNamespace(tag='#P2Y', attacks=[])]), opponent=None)
        bounded_reads = todo_data.bounded_clan_reads
        # Exercise the actual builder, grouping, semaphore and timeout.
        with patch('cwl_web.todo._task_accounts', new=AsyncMock(return_value=([account, other], []))), \
             patch('cwl_web.todo._history', new=AsyncMock(return_value=({}, ''))), \
             patch('utils.todo_data._get_war', side_effect=war), \
             patch('cwl_web.todo.todo_data.bounded_clan_reads', new=lambda seconds: bounded_reads(.02)), \
             patch('cwl_web.todo.todo_data.build_cwl_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo.todo_data.build_raid_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo.todo_data.build_blocked_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo._fwa_outcomes', new=AsyncMock(return_value=([None], ''))):
            result = await _live_snapshot(self.app, ['#P2Y', '#Q2Y'])
        self.assertEqual([r['tag'] for r in result['views']['war']['rows']], ['#P2Y'])
        self.assertTrue(result['views']['war']['incomplete'])
        self.assertTrue(cancelled.is_set())

    async def test_stalled_war_reads_do_not_starve_raids(self):
        from cwl_web.todo import _live_snapshot
        started, raid_finished, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
        held = 0
        async def war(client, accounts, sem, **kwargs):
            async def hold():
                nonlocal held
                async with sem:
                    held += 1
                    if held >= 2:
                        started.set()
                    await release.wait()
            await asyncio.gather(*(hold() for _ in range(8)))
            return todo_data.ViewData()
        async def raid(client, accounts, sem, **kwargs):
            await started.wait()
            async with sem:
                raid_finished.set()
            return todo_data.ViewData()
        with patch('cwl_web.todo._task_accounts', new=AsyncMock(return_value=([todo_data.Account('#P2Y','Scout','#R2Y','Home',16)], []))), \
             patch('cwl_web.todo._history', new=AsyncMock(return_value=({}, ''))), \
             patch('cwl_web.todo.todo_data.build_war_view', new=war), \
             patch('cwl_web.todo.todo_data.build_raid_view', new=raid), \
             patch('cwl_web.todo.todo_data.build_cwl_view', new=AsyncMock(return_value=todo_data.ViewData())), \
             patch('cwl_web.todo.todo_data.build_blocked_view', new=AsyncMock(return_value=todo_data.ViewData())):
            task = asyncio.create_task(_live_snapshot(self.app, ['#P2Y']))
            try:
                await asyncio.wait_for(raid_finished.wait(), 1)
                self.assertFalse(task.done())
            finally:
                release.set()
                await task

    async def test_later_linked_accounts_get_a_turn_after_slow_first_wave(self):
        from cwl_web.todo import _task_accounts
        from types import SimpleNamespace
        started = []
        class Client:
            async def get_player(self, tag):
                started.append(tag)
                if tag.startswith('#SLOW'):
                    await asyncio.Event().wait()
                return SimpleNamespace(tag=tag, name='Later account', clan=None, town_hall=18)
        tags = [f'#SLOW{i}' for i in range(24)] + ['#LATER']
        with todo_data.fresh_reads(), patch('cwl_web.todo.ACCOUNT_LOOKUP_TIMEOUT', .02):
            accounts, errors = await _task_accounts(Client(), tags, todo_data.new_semaphore())
        self.assertEqual(set(started), set(tags))
        self.assertEqual([account.tag for account in accounts], ['#LATER'])
        self.assertEqual(len(errors), 24)

    async def test_account_progress_is_visible_before_slow_accounts_finish(self):
        from cwl_web.todo import _task_accounts
        from types import SimpleNamespace
        release = asyncio.Event()
        progress = []
        class Client:
            async def get_player(self, tag):
                if tag == '#WAIT':
                    await release.wait()
                return SimpleNamespace(tag=tag, name='Account', clan=None, town_hall=18)
        with todo_data.fresh_reads():
            task = asyncio.create_task(_task_accounts(Client(), ['#READY','#WAIT'], todo_data.new_semaphore(), on_progress=lambda rows: progress.append([row.tag for row in rows])))
            try:
                for _ in range(100):
                    if progress:
                        break
                    await asyncio.sleep(.001)
                self.assertEqual(progress, [['#READY']])
                self.assertFalse(task.done())
            finally:
                release.set()
                await task
        self.assertEqual(progress[-1], ['#READY','#WAIT'])
