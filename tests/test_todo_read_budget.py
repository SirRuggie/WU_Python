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
