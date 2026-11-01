import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cwl_web.roster_owner_names import cached_owner_nicknames, lifecycle


def test_immediate_cache_cooldown_scope_and_shutdown(monkeypatch, caplog):
    from cwl_web import manage_roles

    async def run():
        event = asyncio.Event()

        async def blocked(request):
            await event.wait()
            return [
                {"user": {"id": "1"}, "nick": "Owner | IST 🇮🇳"},
                {"user": {"id": "2"}, "nick": "Other"},
            ]

        provider = AsyncMock(side_effect=blocked)
        monkeypatch.setattr(manage_roles, "searchable_members", provider)
        request = SimpleNamespace(app={})
        assert cached_owner_nicknames(request, {"1"}) == {}
        assert cached_owner_nicknames(request, {"1"}) == {}
        await asyncio.sleep(0)
        assert provider.await_count == 1
        event.set()
        await request.app["roster_owner_nicknames"]["task"]
        assert cached_owner_nicknames(request, {"1"}) == {"1": "Owner | IST 🇮🇳"}
        assert cached_owner_nicknames(request, set()) == {}
        state = request.app["roster_owner_nicknames"]
        state["until"] = 0
        provider.side_effect = RuntimeError("offline")
        assert cached_owner_nicknames(request, {"1"}) == {"1": "Owner | IST 🇮🇳"}
        await state["task"]
        assert "Roster owner nickname refresh failed (RuntimeError)" in caplog.text
        cached_owner_nicknames(request, {"1"})
        assert provider.await_count == 2
        event.clear()
        provider.side_effect = blocked
        state["until"] = 0
        life = lifecycle(request.app)
        await anext(life)
        cached_owner_nicknames(request, {"1"})
        task = state["task"]
        try:
            await anext(life)
        except StopAsyncIteration:
            pass
        assert task.cancelled()

    asyncio.run(run())
