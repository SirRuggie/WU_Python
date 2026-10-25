import asyncio
import unittest
from utils import todo_data

class ReadBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_budget_retains_order_cancels_slow_and_restores_background_policy(self):
        cancelled = asyncio.Event()
        async def fetch(tag):
            if tag == 'slow':
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return 'war', tag
        with todo_data.bounded_clan_reads(.02):
            results = await todo_data.gather_clans(asyncio.Semaphore(3), ['one', 'slow', 'two'], fetch)
        assert results == [('war', 'one'), ('error', None), ('war', 'two')]
        assert cancelled.is_set()
        assert todo_data._clan_batch_budget.get() is None

    async def test_budget_includes_queued_reads_and_empty_batches(self):
        called = []
        async def fetch(tag):
            called.append(tag)
            await asyncio.Event().wait()
        with todo_data.bounded_clan_reads(.02):
            assert await todo_data.gather_clans(asyncio.Semaphore(1), ['first', 'queued'], fetch) == [('error', None), ('error', None)]
            assert await todo_data.gather_clans(asyncio.Semaphore(1), [], fetch) == []
        assert called == ['first']

    async def test_player_timeout_releases_slot_for_next_account(self):
        from types import SimpleNamespace
        class Client:
            async def get_player(self, tag):
                if tag == '#SLOW':
                    await asyncio.Event().wait()
                return SimpleNamespace(tag=tag, name='Fast', clan=None, town_hall=18)
        with todo_data.fresh_reads():
            accounts, errors = await todo_data.fetch_accounts(Client(), ['#SLOW', '#FAST'], concurrency=1, lookup_timeout=.02)
        assert [account.tag for account in accounts] == ['#FAST']
        assert len(errors) == 1

    async def test_mixed_cwl_and_raid_results_are_explicitly_partial(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch
        accounts = [todo_data.Account('#ONE', 'One', '#CLAN1', 'Clan1', 18),
                    todo_data.Account('#TWO', 'Two', '#CLAN2', 'Clan2', 18)]
        war = SimpleNamespace(state='inWar', start_time=None, end_time=None,
            clan=SimpleNamespace(tag='#CLAN1', members=[SimpleNamespace(tag='#ONE', attacks=[])]), opponent=None)
        raid = SimpleNamespace(end_time=None, get_member=lambda tag: None)
        with patch('utils.todo_data.gather_clans', new=AsyncMock(return_value=[('war',war),('error',None)])):
            cwl = await todo_data.build_cwl_view(None, accounts)
        with patch('utils.todo_data.gather_clans', new=AsyncMock(return_value=[('raid',raid),('error',None)])), patch('utils.todo_data.DIAG',False):
            raids = await todo_data.build_raid_view(None, accounts)
        for view in (cwl, raids):
            assert view.ok
            assert len(view.rows) == 1
            assert view.incomplete
