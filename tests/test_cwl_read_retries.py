import asyncio
import unittest
from unittest.mock import AsyncMock, patch
from cwl_web.providers import LiveProviders, ProviderUnavailable
from test_cwl_web_league_provider import Response, Session

class ReadRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_status_recovers_one_lookup(self):
        calls=[]
        with patch('cwl_web.providers.aiohttp.ClientSession', return_value=Session([Response({},503),Response({'tag':'#P2Y'})],calls)), patch('cwl_web.providers.asyncio.sleep',new_callable=AsyncMock) as sleep:
            result=await LiveProviders(coc_token='test',routes={})._coc('players','#P2Y')
        self.assertEqual(result['tag'],'#P2Y'); self.assertEqual(len(calls),2); sleep.assert_awaited_once()

    async def test_timeout_recovery_and_exhaustion(self):
        class TimeoutResponse(Response):
            async def __aenter__(self): raise TimeoutError()
        calls=[]
        with patch('cwl_web.providers.aiohttp.ClientSession', return_value=Session([TimeoutResponse({}) for _ in range(3)],calls)), patch('cwl_web.providers.asyncio.sleep',new_callable=AsyncMock):
            with self.assertRaises(ProviderUnavailable) as result:
                await LiveProviders(coc_token='test',routes={})._coc('players','#P2Y')
        self.assertTrue(result.exception.read_retries_exhausted); self.assertEqual(len(calls),3)

    async def test_permanent_status_and_cancellation_do_not_retry(self):
        for status in [400,403,404,429]:
            calls=[]
            with patch('cwl_web.providers.aiohttp.ClientSession',return_value=Session([Response({},status)],calls)), patch('cwl_web.providers.asyncio.sleep',new_callable=AsyncMock) as sleep:
                with self.assertRaises(ProviderUnavailable):
                    await LiveProviders(coc_token='test',routes={})._league_get('/test')
            self.assertEqual(len(calls),1);sleep.assert_not_awaited()
        class CancelResponse(Response):
            async def __aenter__(self):raise asyncio.CancelledError()
        with patch('cwl_web.providers.aiohttp.ClientSession',return_value=Session([CancelResponse({})],[])),patch('cwl_web.providers.asyncio.sleep',new_callable=AsyncMock) as sleep:
            with self.assertRaises(asyncio.CancelledError):await LiveProviders(coc_token='test',routes={})._league_get('/test')
            sleep.assert_not_awaited()

    async def test_successful_accounts_are_not_repeated(self):
        calls=[]
        queues={'#P2Y':[Response({'tag':'#P2Y'})], '#Q2Y':[Response({},503),Response({'tag':'#Q2Y'})]}
        class PerAccountSession(Session):
            def get(self,url,**kwargs):
                from urllib.parse import unquote
                key=unquote(url.rsplit('/',1)[1]);calls.append(key);return queues[key].pop(0)
        with patch('cwl_web.providers.aiohttp.ClientSession',side_effect=lambda **kw: PerAccountSession([],[])),patch('cwl_web.providers.asyncio.sleep',new_callable=AsyncMock):
            provider=LiveProviders(coc_token='test',routes={})
            result=await asyncio.gather(provider._coc('players','#P2Y'),provider._coc('players','#Q2Y'))
        self.assertEqual(len(result),2);self.assertEqual(calls.count('#P2Y'),1);self.assertEqual(calls.count('#Q2Y'),2)

    async def test_exhausted_marker_reaches_browser(self):
        from types import SimpleNamespace
        from cwl_web.app import errors
        from cwl_web.issues import diagnostics
        for attribute in ['read_retries_exhausted','read_retry_blocked']:
            error=ProviderUnavailable('Unavailable');setattr(error,attribute,True)
            async def handler(request):raise error
            request=SimpleNamespace(path='/api/cwl/linked-accounts',method='GET')
            async def adapted(request):return await errors(request,handler)
            with patch('cwl_web.issues.record',new_callable=AsyncMock,return_value='test-reference'):
                response=await diagnostics(request,adapted)
            self.assertEqual(response.status,503)
            self.assertEqual(response.headers['X-Read-Retries-Exhausted'],'1')
            self.assertIn('test-reference',response.text)
