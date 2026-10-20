"""Background replacement refreshes end with the bot lifecycle."""

import asyncio

from extensions.commands import strikes


def test_stopping_cancels_monitor_weight_warm_and_refresh_tasks(monkeypatch):
    async def run():
        entered = asyncio.Event()
        async def pending():
            entered.set()
            await asyncio.Event().wait()
        monitor = asyncio.create_task(pending())
        warm = asyncio.create_task(pending())
        refresh = asyncio.create_task(pending())
        monkeypatch.setattr(strikes, '_task', monitor)
        monkeypatch.setattr(strikes, '_weight_warm_task', warm)
        monkeypatch.setattr(strikes, '_weight_refresh_task', refresh)
        await entered.wait()
        await strikes.stopped(None)
        assert all(task.done() and task.cancelled() for task in (monitor, warm, refresh))
        assert strikes._task is None
        assert strikes._weight_warm_task is None
        assert strikes._weight_refresh_task is None
    asyncio.run(run())
