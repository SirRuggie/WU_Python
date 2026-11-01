import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from contextlib import asynccontextmanager
from cwl_web.roster_profile_zones import cached_profile_zones, lifecycle


def test_profile_cache_is_scoped_immediate_and_cancels(monkeypatch):
    from cwl_web import server_management
    from utils.member_profiles import MemberProfiles

    async def run():
        event = asyncio.Event()
        one = "123456789012345678"
        other = "234567890123456789"

        @asynccontextmanager
        async def mongo(request):
            yield object()

        monkeypatch.setattr(server_management, "mongo", mongo)

        async def read(*args):
            await event.wait()
            return {one: {"zone_id": "gmt+5:30"}, other: {"zone_id": "gmt-5"}}

        monkeypatch.setattr(MemberProfiles, "__init__", lambda self, db: None)
        provider = AsyncMock(side_effect=read)
        monkeypatch.setattr(MemberProfiles, "for_members", provider)
        request = S(app={})
        assert cached_profile_zones(request, {one}) == {}
        await asyncio.sleep(0)
        assert provider.await_count == 1
        event.set()
        await request.app["roster_profile_zones"]["task"]
        assert cached_profile_zones(request, {one}) == {
            one: {"label": "GMT+5:30", "offsetMinutes": 330}
        }
        assert other not in cached_profile_zones(request, {one})
        state = request.app["roster_profile_zones"]
        state["until"] = 0
        event.clear()
        life = lifecycle(request.app)
        await anext(life)
        cached_profile_zones(request, {one})
        task = state["task"]
        try:
            await anext(life)
        except StopAsyncIteration:
            pass
        assert task.cancelled()

    asyncio.run(run())
