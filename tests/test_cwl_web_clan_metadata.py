import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cwl_web.clan_metadata import enrich
from cwl_web.providers import LiveProviders, ProviderUnavailable

class ClanMetadataTests(unittest.IsolatedAsyncioTestCase):
    async def test_ranked_and_unranked(self):
        provider = LiveProviders(coc_token="fixture", mongo_uri="", routes={})
        for league, expected in [({"name":"Crystal League I"}, "Crystal League I"), ({"name":"Unranked"}, "Unranked"), (None, "Unranked")]:
            provider._coc = AsyncMock(return_value={"tag":"#C2Y", "name":"Clan", "warLeague":league})
            self.assertEqual((await provider.clan("#C2Y"))["cwl_league"], expected)

    async def test_cache_and_failure_preserve_last_known(self):
        provider = SimpleNamespace(clan=AsyncMock(return_value={"cwl_league":"Gold League II"}))
        request = SimpleNamespace(app={"providers":provider})
        self.assertEqual((await enrich(request,[{"tag":"#C2Y"}]))[0]["cwl_league"], "Gold League II")
        await enrich(request,[{"tag":"#C2Y"}])
        self.assertEqual(provider.clan.await_count,1)
        request.app["clan_league_cache"]["#C2Y"]["expires"] = 0
        provider.clan.side_effect = ProviderUnavailable("offline")
        result = await enrich(request,[{"tag":"#C2Y"},{"tag":"#R2Y"}])
        self.assertEqual(result[0]["cwl_league"],"Gold League II")
        self.assertTrue(result[0]["cwl_league_stale"])
        self.assertIsNone(result[1]["cwl_league"])

    async def test_slow_lookup_does_not_block_cached_other_clan(self):
        import asyncio, time
        from cwl_web.clan_metadata import background_enrich, lifecycle
        release = asyncio.Event()
        async def slow(tag):
            await release.wait()
            return {"cwl_league": "Gold League I"}
        request = SimpleNamespace(app={"providers": SimpleNamespace(clan=AsyncMock(side_effect=slow))})
        life = lifecycle(request.app)
        await anext(life)
        request.app["clan_league_cache"] = {"#FAST": {"expires": time.monotonic()+300,
            "data": {"cwl_league": "Crystal League I", "cwl_league_stale": False}}}
        self.assertTrue(await background_enrich(request, [{"tag": "#SLOW"}]))
        fast = await asyncio.wait_for(enrich(request, [{"tag": "#FAST"}]), .2)
        self.assertEqual(fast[0]["cwl_league"], "Crystal League I")
        await background_enrich(request, [{"tag": "#SLOW"}])
        self.assertEqual(len(request.app["clan_league_jobs"]), 1)
        tasks = list(request.app["clan_league_jobs"].values())
        with self.assertRaises(StopAsyncIteration):
            await anext(life)
        self.assertTrue(all(task.cancelled() for task in tasks))
