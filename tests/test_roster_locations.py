import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from cwl_web.roster_locations import enrich
from cwl_web.providers import ProviderUnavailable

class LocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_clan_is_cached_and_independent_of_signup_clan(self):
        provider=SimpleNamespace(player=AsyncMock(return_value={'current_clan_tag':'#NEW','current_clan_name':'New clan'}))
        request=SimpleNamespace(app={'providers':provider})
        accounts=[{'tag':'#P2Y','signup_clan_name':'Old clan'}]
        await enrich(request,accounts)
        await enrich(request,accounts)
        self.assertEqual(accounts[0]['current_clan_name'],'New clan')
        self.assertEqual(accounts[0]['signup_clan_name'],'Old clan')
        provider.player.assert_awaited_once()

    async def test_no_clan_is_different_from_unavailable(self):
        provider=SimpleNamespace(player=AsyncMock(side_effect=[{'current_clan_tag':None},ProviderUnavailable('offline')]))
        accounts=[{'tag':'#P2Y'},{'tag':'#Q2Y'}]
        await enrich(SimpleNamespace(app={'providers':provider}),accounts)
        self.assertEqual(accounts[0]['current_clan_status'],'current')
        self.assertIsNone(accounts[0]['current_clan_tag'])
        self.assertEqual(accounts[1]['current_clan_status'],'unavailable')

    async def test_background_returns_immediately_and_deduplicates(self):
        import asyncio
        from cwl_web.roster_locations import background_enrich
        release=asyncio.Event()
        async def player(tag):
            await release.wait()
            return {'current_clan_tag':'#NEW','current_clan_name':'New clan'}
        provider=SimpleNamespace(player=AsyncMock(side_effect=player))
        request=SimpleNamespace(app={'providers':provider})
        accounts=[{'tag':'#P2Y'}]
        self.assertTrue(await background_enrich(request,accounts,force=True))
        await background_enrich(request,accounts,force=True)
        self.assertEqual(len(request.app['roster_location_jobs']),1)
        self.assertEqual(accounts[0]['current_clan_status'],'unavailable')
        jobs=list(request.app['roster_location_jobs'].values())
        release.set();await asyncio.gather(*jobs)
        self.assertFalse(await background_enrich(request,accounts))
        self.assertEqual(accounts[0]['current_clan_name'],'New clan')
        self.assertEqual(accounts[0]['current_clan_status'],'current')
        provider.player.assert_awaited_once()

    async def test_failed_background_refresh_never_marks_old_location_current(self):
        import asyncio,time
        from unittest.mock import patch
        from cwl_web.roster_locations import background_enrich
        provider=SimpleNamespace(player=AsyncMock(side_effect=ProviderUnavailable('offline')))
        request=SimpleNamespace(app={'providers':provider,'roster_location_cache':{'#P2Y':(time.monotonic(),{'current_clan_name':'Old clan','current_clan_tag':'#OLD','current_clan_status':'current'})}})
        accounts=[{'tag':'#P2Y'}]
        with patch('cwl_web.roster_locations.asyncio.sleep',new=AsyncMock()):
            await background_enrich(request,accounts,force=True)
            self.assertEqual(accounts[0]['current_clan_status'],'stale')
            await asyncio.gather(*list(request.app['roster_location_jobs'].values()))
        self.assertEqual(provider.player.await_count,1)
        self.assertFalse(await background_enrich(request,accounts))
        self.assertEqual(accounts[0]['current_clan_status'],'stale')
        self.assertEqual(accounts[0]['current_clan_name'],'Old clan')
