"""Replacement list regression checks independent of dashboard rendering."""

import asyncio
from datetime import datetime, timezone

from utils.strike_store import StrikeService


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return self.rows if length is None else self.rows[:length]


class Clans:
    def __init__(self):
        self.rows = [{'tag': '#2UVGQU9', 'type': 'FWA'}, {'tag': '#8GG82', 'type': 'Main'}]

    def find(self, query, projection=None):
        return Cursor([row for row in self.rows if not query or row['type'] == query['type']])

    async def find_one(self, query, projection=None):
        return next((row for row in self.rows if row['tag'] == query['tag']), None)


class Profiles:
    def __init__(self, rows):
        self.rows = rows
        self.updates = []

    def find(self, query):
        from test_strike_streaks import matches
        return Cursor([row for row in self.rows if matches({'guild_id': 123, **row}, query)])

    async def update_one(self, query, update, upsert=False):
        self.updates.append((query, update, upsert))


class Records:
    def __init__(self, counts):
        self.counts = counts
        self.pipeline = None

    async def aggregate(self, pipeline):
        self.pipeline = pipeline
        return Cursor([{'_id': tag, 'count': count} for tag, count in self.counts.items()])


class Mongo:
    def __init__(self, profiles, counts):
        self.clans = Clans()
        self.strike_profiles = Profiles(profiles)
        self.strike_records = Records(counts)


def profile(tag, clan='#2UVGQU9', **changes):
    return {'player_tag': tag, 'current_clan_tag': clan,
            'roster_seen_at': datetime.now(timezone.utc), **changes}


def test_unweighted_family_list_includes_unstruck_priority_marks_and_unknown_weights():
    async def run():
        mongo = Mongo([
            profile('#PC9YGL0JL', replacement_listed=True, replacement_clan_tag='#2UVGQU9',
                    replacement_priority='replace_first'),
            profile('#8GG82', weight=120000),
            profile('#YLC820G', clan='#8GG82', replacement_listed=True,
                    replacement_clan_tag='#8GG82', replacement_priority='high'),
            profile('#PYL0QG', weight=100000),
        ], {'#8GG82': 3})
        rows = await StrikeService(mongo).replacement(123)
        assert [row['player_tag'] for row in rows] == ['#PC9YGL0JL', '#YLC820G', '#8GG82']
        assert rows[0]['active_strikes'] == 0 and rows[0]['weight'] is None
        assert rows[1]['current_clan_tag'] == '#8GG82'
        assert rows[2]['active_strikes'] == 3
        assert mongo.strike_records.pipeline[0]['$match']['kind'] == 'strike'
        assert mongo.strike_records.pipeline[0]['$match']['revoked_at'] == {'$exists': False}
    asyncio.run(run())


def test_weighted_list_keeps_unknown_visible_but_after_known_matches():
    async def run():
        mongo = Mongo([
            profile('#PC9YGL0JL', replacement_listed=True, replacement_clan_tag='#2UVGQU9',
                    replacement_priority='replace_first'),
            profile('#8GG82', weight=120000),
            profile('#YLC820G', clan='#8GG82', replacement_listed=True,
                    replacement_clan_tag='#8GG82', replacement_priority='replace_first'),
        ], {'#8GG82': 2})
        rows = await StrikeService(mongo).replacement(123, 115000)
        assert [row['player_tag'] for row in rows] == ['#8GG82', '#PC9YGL0JL']
        assert rows[0]['weight_difference'] == 5000
        assert rows[1]['weight'] is None and rows[1]['weight_difference'] is None
        assert all(row['current_clan_tag'] == '#2UVGQU9' for row in rows)
    asyncio.run(run())


def test_priority_mark_does_not_follow_player_into_another_clan():
    async def run():
        mongo = Mongo([
            profile('#PC9YGL0JL', clan='#8GG82', replacement_listed=True,
                    replacement_clan_tag='#2UVGQU9', replacement_priority='replace_first',
                    filler=True, filler_clan_tag='#2UVGQU9'),
            profile('#8GG82', clan='#8GG82', replacement_listed=True,
                    replacement_clan_tag='#8GG82', replacement_priority='normal'),
        ], {'#PC9YGL0JL': 2})
        rows = await StrikeService(mongo).replacement(123)
        assert [row['player_tag'] for row in rows] == ['#PC9YGL0JL', '#8GG82']
        assert not rows[0]['is_manual'] and rows[0]['replacement_priority'] == 'normal'
        assert not rows[0]['filler']
    asyncio.run(run())


def test_clear_mark_changes_profile_only_without_touching_strike_ledger():
    async def run():
        mongo = Mongo([], {})
        service = StrikeService(mongo)
        await service.set_replacement_preference(123, '#PC9YGL0JL', 'replace_first', 'temporary', 456,
                                                 clan_tag='#2UVGQU9')
        await service.clear_replacement_preference(123, '#PC9YGL0JL', 456)
        assert len(mongo.strike_profiles.updates) == 2
        assert mongo.strike_records.pipeline is None
        assert mongo.strike_profiles.updates[1][1]['$set']['filler'] is False
    asyncio.run(run())


def test_replacement_read_and_preference_writes_have_distinct_scopes():
    from types import SimpleNamespace
    from unittest.mock import patch
    from aiohttp import web
    from cwl_web import strikes as api

    async def run():
        observed = []
        async def deny(request, section, *, write=False):
            observed.append((request.method, section, write))
            raise web.HTTPForbidden()
        with patch.object(api.shared, 'require_manage', deny):
            for handler, method in [(api.replacements, 'GET'),
                                    (api.add_replacement_list, 'POST'),
                                    (api.update_replacement_list, 'PUT'),
                                    (api.delete_replacement_list, 'DELETE')]:
                try:
                    await handler(SimpleNamespace(method=method))
                except web.HTTPForbidden:
                    pass
                else:
                    raise AssertionError('Handler did not deny before touching data')
        assert observed == [('GET', 'strikes_read', False), ('POST', 'strikes', True),
                            ('PUT', 'strikes', True), ('DELETE', 'strikes', True)]
    asyncio.run(run())


def test_current_clan_verification_fails_closed_on_provider_outage():
    from types import SimpleNamespace
    from aiohttp import web
    from cwl_web import strikes as api
    from cwl_web.providers import ProviderUnavailable

    class Providers:
        async def player(self, tag):
            raise ProviderUnavailable('offline')

    async def run():
        try:
            await api._verified_replacement_player(SimpleNamespace(app={'providers': Providers()}), '#PC9YGL0JL')
        except web.HTTPServiceUnavailable:
            pass
        else:
            raise AssertionError('Must not mark stale clan when player API is offline')
    asyncio.run(run())


def test_replacement_list_routes_registered_next_to_legacy_toggle():
    from cwl_web import strikes as api
    routes = {(route.method, route.path) for route in api.routes}
    assert ('GET', api.API + '/replacements') in routes
    assert ('POST', api.API + '/replacement-list') in routes
    assert ('PUT', api.API + '/replacement-list/{player_tag}') in routes
    assert ('DELETE', api.API + '/replacement-list/{player_tag}') in routes


def test_town_hall_four_is_exact_and_149_weight_matches_main_when_family_scope_all():
    from utils.replacement_filters import parse_weight
    async def run():
        mongo = Mongo([
            profile('#PC9YGL0JL', town_hall=4, weight=149000),
            profile('#8GG82', town_hall=14, weight=149000),
            profile('#YLC820G', clan='#8GG82', town_hall=4, weight=149500),
        ], {})
        rows = await StrikeService(mongo).replacement(
            123, parse_weight('149'), town_hall=4, family_scope='all', browse_all=True)
        assert [row['player_tag'] for row in rows] == ['#PC9YGL0JL', '#YLC820G']
        assert [row['weight_difference'] for row in rows] == [0, 500]
    asyncio.run(run())
