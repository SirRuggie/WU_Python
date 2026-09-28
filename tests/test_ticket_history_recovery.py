import asyncio
from unittest.mock import AsyncMock

from extensions.commands import tickets


def test_history_failure_retries_without_blocking_intake(monkeypatch):
    async def scenario():
        monkeypatch.setattr(tickets, '_thread_intake_ready', True)
        monkeypatch.setattr(tickets, '_history_recovery', None)
        scan = AsyncMock(side_effect=[{'checked': 1208, 'failed': 1}, {'checked': 1208, 'failed': 0}])
        monkeypatch.setattr(tickets.console, 'reconcile_prior_denial_flags', scan)
        reconciler = tickets.start_ticket_history_recovery(object(), object())
        reconciler.retry_delays = (0,)
        first = reconciler.task
        assert tickets.start_ticket_history_recovery(object(), object()).task is first
        await first
        assert scan.await_count == 2
        assert reconciler.health.state == 'healthy'
        assert tickets.thread_intake_ready()
        await reconciler.stop()
    asyncio.run(scenario())


def test_history_waits_for_essential_recovery_and_stops_cleanly(monkeypatch):
    async def scenario():
        monkeypatch.setattr(tickets, '_thread_intake_ready', False)
        monkeypatch.setattr(tickets, '_history_recovery', None)
        scan = AsyncMock()
        monkeypatch.setattr(tickets.console, 'reconcile_prior_denial_flags', scan)
        reconciler = tickets.start_ticket_history_recovery(object(), object())
        await asyncio.sleep(0)
        scan.assert_not_awaited()
        await reconciler.stop()
        assert reconciler.task is None
        assert not tickets.thread_intake_ready()
    asyncio.run(scenario())
