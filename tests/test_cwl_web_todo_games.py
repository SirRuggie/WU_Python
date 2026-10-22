"""Monthly Clan Games scores: read-only, scoped to linked accounts, no fake zeros."""
import asyncio
import json
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cwl_web import todo_games
from utils import clan_games

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def account(tag='#P2Y', clan='#Q2Y', th=16):
    return SimpleNamespace(tag=tag, name='<script>Account</script>', town_hall=th,
                           clan_tag=clan, clan_name='Clan', clan_badge=None)


class GamesTests(unittest.IsolatedAsyncioTestCase):
    async def test_one_fetch_per_clan_only_linked_players_no_goal(self):
        fetch = AsyncMock(return_value={'#P2Y': 2450, '#Q2Y': 700, '#PYY': 9000})
        with patch.object(todo_games, 'fetch_clan_scores', fetch):
            view = await todo_games.build_games_view([account(), account('#Q2Y'), account('#PYY', th=5)], now=NOW)
        self.assertEqual(fetch.await_count, 1)
        self.assertEqual(fetch.call_args.args[2], '2026-10')
        self.assertEqual([r['used'] for r in view['rows']], [2450, 700])
        self.assertTrue(all(r['total'] is None and r['remaining'] is None for r in view['rows']))
        self.assertNotIn('goal', str(view))
        self.assertEqual(view['source'], 'ClashPerk')

    async def test_missing_not_zero_and_explicit_zero_kept(self):
        with patch.object(todo_games, 'fetch_clan_scores', AsyncMock(return_value={'#P2Y': 0})):
            view = await todo_games.build_games_view([account(), account('#Q2Y'), account('#PYY', clan=None)], now=NOW)
        self.assertEqual([r['used'] for r in view['rows']], [0, None, None])
        self.assertEqual(view['rows'][0]['state'], 'reported')
        self.assertEqual(view['rows'][1]['state'], 'unknown')

    async def test_upcoming_does_not_fetch_and_month_rollover(self):
        fetch = AsyncMock()
        with patch.object(todo_games, 'fetch_clan_scores', fetch):
            view = await todo_games.build_games_view([account()], now=datetime(2027, 1, 1, tzinfo=timezone.utc))
        fetch.assert_not_awaited()
        self.assertEqual(view['season'], '2027-01')
        self.assertEqual(view['rows'][0]['state'], 'upcoming')
        self.assertIsNone(view['rows'][0]['used'])

    async def test_finished_event_keeps_same_month(self):
        with patch.object(todo_games, 'fetch_clan_scores', AsyncMock(return_value={'#P2Y': 9000})):
            view = await todo_games.build_games_view([account()], now=NOW.replace(day=30))
        self.assertEqual(view['season'], '2026-10')
        self.assertLess(view['event_end'], NOW.replace(day=30).timestamp())
        self.assertEqual(view['rows'][0]['used'], 9000)

    async def test_partial_outage_does_not_erase_other_clan(self):
        async def fetch(session, clan, *args):
            if clan == '#Q2Y': raise TimeoutError()
            return {'#Q2Y': 800}
        with patch.object(todo_games, 'fetch_clan_scores', fetch):
            view = await todo_games.build_games_view([account(), account('#Q2Y', clan='#PYY')], now=NOW)
        self.assertTrue(view['ok'])
        self.assertTrue(view['incomplete'])
        self.assertEqual([r['used'] for r in view['rows']], [None, 800])
        with patch.object(todo_games, 'fetch_clan_scores', AsyncMock(side_effect=TimeoutError)):
            view = await todo_games.build_games_view([account()], now=NOW)
        self.assertFalse(view['ok'])

    def test_wrong_season_malformed_and_conflicting_scores(self):
        with self.assertRaises(ValueError):
            clan_games.scores({'season':'2026-09','members':[]},'2026-10')
        members = [{'tag':'#P2Y','points':250}, {'tag':'#P2Y','points':300},
                   {'tag':'#Q2Y','points':True}, {'tag':'#PYY','points':-1},
                   {'tag':'#QYY','points':500}, {'tag':'#QYY','points':500}]
        data = clan_games.scores({'season':'2026-10','members':members}, '2026-10')
        self.assertEqual(data, {'#P2Y':None, '#Q2Y':None, '#PYY':None, '#QYY':500})
        with self.assertRaises(ValueError):
            clan_games.scores({'season':'2026-10','members':{}},'2026-10')

    async def test_cancellation_is_not_converted_to_empty_result(self):
        fetch = AsyncMock(side_effect=asyncio.CancelledError)
        # Caller cancellation must cancel gather, not produce a successful snapshot.
        async def wait(*args):
            await asyncio.sleep(60)
        with patch.object(todo_games, 'fetch_clan_scores', wait):
            task = asyncio.create_task(todo_games.build_games_view([account()], now=NOW))
            await asyncio.sleep(0)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError): await task


class Response:
    content_type = 'application/json'
    def __init__(self, status=200, chunks=None):
        self.status = status
        self.chunks = chunks or [b'{"season":"2026-10","members":[]}']
        self.content = self
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    async def iter_chunked(self, size):
        for chunk in self.chunks: yield chunk


class Session:
    def __init__(self, responses): self.responses, self.calls = list(responses), []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_401_refresh_once_correct_season_and_no_redirects(self):
        session = Session([Response(401), Response()])
        auth = AsyncMock(side_effect=['one','two'])
        with patch.object(clan_games, 'get_access_token', auth):
            self.assertEqual(await clan_games.fetch_clan_scores(session, '#Q2Y', '2026-10', asyncio.Semaphore(1)), {})
        self.assertEqual(len(session.calls),2)
        url, args = session.calls[-1]
        self.assertIn('%23Q2Y/clan-games',url)
        self.assertEqual(args['params'],{'season':'2026-10'})
        self.assertFalse(args['allow_redirects'])
        self.assertEqual(args['headers']['Authorization'],'Bearer two')

    async def test_rejected_credentials_and_rate_limit_are_not_retried(self):
        for status in (401,403,429,500,302):
            session = Session([Response(status),Response(status)])
            with patch.object(clan_games, 'get_access_token', AsyncMock(return_value='token')):
                with self.assertRaises(ValueError):
                    await clan_games.fetch_clan_scores(session,'#Q2Y','2026-10',asyncio.Semaphore(1))
            self.assertEqual(len(session.calls),2 if status==401 else 1)

    async def test_stream_read_and_size_bound(self):
        data=json.dumps({'season':'2026-10','members':[{'tag':'#P2Y','points':1234}]}).encode()
        with patch.object(clan_games, 'get_access_token', AsyncMock(return_value='token')):
            result=await clan_games.fetch_clan_scores(Session([Response(chunks=[data[:11],data[11:]])]),'#Q2Y','2026-10',asyncio.Semaphore(1))
            self.assertEqual(result,{'#P2Y':1234})
            with self.assertRaisesRegex(ValueError,'too large'):
                await clan_games.fetch_clan_scores(Session([Response(chunks=[b' '*(clan_games.MAX_RESPONSE_BYTES+1)])]),'#Q2Y','2026-10',asyncio.Semaphore(1))

    async def test_missing_key_and_invalid_tags_never_request_scores(self):
        session=Session([])
        with patch.object(clan_games,'get_access_token',AsyncMock(return_value=None)):
            for tag in ('#Q2Y','https://other.example'):
                with self.assertRaises(ValueError):
                    await clan_games.fetch_clan_scores(session,tag,'2026-10',asyncio.Semaphore(1))
        self.assertEqual(session.calls,[])
