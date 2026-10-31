import asyncio

from extensions.tasks import player_activity


def test_duplicate_start_and_stop_cancel_one_worker(monkeypatch):
    async def scenario():
        started = asyncio.Event()
        stopped = asyncio.Event()
        calls = []
        async def run(mongo, client):
            calls.append((mongo, client))
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        monkeypatch.setattr(player_activity, 'run', run)
        monkeypatch.setattr(player_activity, '_task', None)
        await player_activity.started(None, mongo='mongo', coc_client='official')
        await started.wait()
        await player_activity.started(None, mongo='mongo', coc_client='official')
        assert calls == [('mongo', 'official')]
        await player_activity.stopped(None)
        assert stopped.is_set()
        assert player_activity._task is None
    asyncio.run(scenario())
