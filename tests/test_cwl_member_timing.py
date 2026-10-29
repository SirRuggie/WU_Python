"""Optional campaign guidance never writes or prevents reading member seasons."""
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import test_cwl_web_foundation as foundation
from test_cwl_dashboard_integration import MemoryMongo
from cwl_web.manage_bridge import GUILD_ID
from utils import cwl_campaign
from cwl_web.member_timing import utc_timing


def test_utc_math_and_null_never_produce_naive_dates():
    assert utc_timing(None) == {'signup_deadline': None, 'placements_by': None}
    assert utc_timing('2026-10-30T17:00:00') == utc_timing(None)
    assert utc_timing('2026-10-30T21:00:00Z') == {
        'signup_deadline': '2026-10-30T21:00:00+00:00',
        'placements_by': '2026-10-31T21:00:00+00:00'}


def test_non_utc_and_dst_weekend_use_24_elapsed_hours():
    for at, expected in [('2026-10-30T17:00:00-04:00', '2026-10-31T21:00:00+00:00'),
                         ('2026-10-31T17:00:00-04:00', '2026-11-01T21:00:00+00:00'),
                         ('2026-03-07T17:00:00-05:00', '2026-03-08T22:00:00+00:00')]:
        campaign = cwl_campaign.default_campaign()
        campaign['timezone'] = 'America/New_York'
        campaign['signup_deadline'] = {'at': at}
        result = utc_timing(cwl_campaign.signup_deadline(campaign, at[:7]))
        assert result['placements_by'] == expected
        start, end = (datetime.fromisoformat(result[k]) for k in ('signup_deadline', 'placements_by'))
        assert start.utcoffset() == end.utcoffset() == timedelta(0)
        assert end - start == timedelta(hours=24)


class MemberTimingTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = foundation.WebFoundationTests.asyncSetUp
    asyncTearDown = foundation.WebFoundationTests.asyncTearDown
    auth = foundation.WebFoundationTests.auth
    call = foundation.WebFoundationTests.call
    season = foundation.WebFoundationTests.season

    async def test_linked_timezone_cache_expiry_and_no_writes(self):
        sid = await self.season()
        mongo = MemoryMongo()
        self.app['manage_bridge_mongo'] = mongo
        campaign = cwl_campaign.default_campaign()
        campaign['timezone'] = 'America/New_York'
        key = cwl_campaign.defaults_id(GUILD_ID)
        mongo.bot_config.documents[key] = {'_id': key, 'campaign': campaign}
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,?)', (sid, '2026-10'))
            before = list(db.iterdump())
        async def read():
            response = await self.call('GET', '/seasons', self.member)
            self.assertEqual(response.status, 200)
            return (await response.json())['seasons'][0]
        from cwl_web import member_timing
        with patch.object(member_timing, 'load_campaign', wraps=cwl_campaign.load_campaign) as load, patch.object(member_timing.time, 'monotonic', return_value=1000) as clock:
            first = await read()
            self.assertEqual(first['signup_deadline'], '2026-10-29T21:00:00+00:00')
            self.assertEqual(datetime.fromisoformat(first['placements_by']) - datetime.fromisoformat(first['signup_deadline']), timedelta(hours=24))
            self.assertEqual((await read())['signup_deadline'], first['signup_deadline'])
            self.assertEqual(load.call_count, 1)
            clock.return_value = 1301
            await read()
            self.assertEqual(load.call_count, 2)
        with self.app['store'].tx() as db:
            self.assertEqual(list(db.iterdump()), before)

    async def test_unlinked_and_unavailable_have_null_dates(self):
        sid = await self.season()
        async def read():
            response = await self.call('GET', '/seasons', self.member)
            self.assertEqual(response.status, 200)
            return (await response.json())['seasons'][0]
        result = await read()
        self.assertIsNone(result['signup_deadline'])
        self.assertIsNone(result['placements_by'])
        with self.app['store'].tx() as db:
            db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,?)', (sid, '2026-10'))
        self.app['member_timing_cache'].clear()
        self.app['manage_bridge_mongo'] = MemoryMongo()
        with patch('cwl_web.member_timing.load_campaign', new=AsyncMock(side_effect=OSError('fake unavailable'))):
            result = await read()
        self.assertIsNone(result['signup_deadline'])
        self.assertIsNone(result['placements_by'])
