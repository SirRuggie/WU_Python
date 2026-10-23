"""Replacement preferences are account and clan scoped, not strike mutations."""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from aiohttp import web

from cwl_web import strikes
from utils.strike_store import StrikeService


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length=None):
        return self.rows


class Profiles:
    def __init__(self, rows):
        self.rows = rows

    def find(self, query):
        cutoff = query.get('roster_seen_at', {}).get('$gt')
        clan = query['current_clan_tag']
        allowed = set(clan['$in']) if isinstance(clan, dict) else {clan}
        return Cursor([row.copy() for row in self.rows.values()
                       if (cutoff is None or row.get('roster_seen_at', cutoff - timedelta(seconds=1)) > cutoff)
                       and row.get('current_clan_tag') in allowed
                       and ('town_hall' not in query or row.get('town_hall') == query['town_hall'])])

    async def update_one(self, query, update, upsert=False):
        row = self.rows.setdefault(query['_id'], {'_id': query['_id']})
        row.update(update.get('$set', {}))
        for key in update.get('$unset', {}):
            row.pop(key, None)


class Clans:
    def __init__(self):
        self.rows = {'#2UVGQU9': 'FWA', '#8GG82': 'Competitive'}

    async def find_one(self, query, projection=None):
        kind = self.rows.get(query['tag'])
        return {'tag': query['tag'], 'type': kind} if kind else None

    def find(self, query, projection=None):
        return Cursor([{'tag': tag} for tag, kind in self.rows.items()
                       if not query or kind == query.get('type')])


class Records:
    def __init__(self, counts):
        self.counts = counts
        self.rows = [{'player_tag': tag} for tag, count in counts.items() for _ in range(count)]

    async def aggregate(self, pipeline):
        assert pipeline[0]['$match']['kind'] == 'strike'
        allowed = set(pipeline[0]['$match']['player_tag']['$in'])
        return Cursor([{'_id': tag, 'count': count} for tag, count in self.counts.items()
                       if tag in allowed])


class Mongo:
    def __init__(self, profiles, counts=None):
        self.strike_profiles = Profiles({f'123:{row["player_tag"]}': row for row in profiles})
        self.strike_records = Records(counts or {})
        self.clans = Clans()


def test_zero_strike_marked_account_ranks_before_struck_account():
    async def run():
        now = datetime.now(timezone.utc)
        mongo = Mongo([
            {'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9', 'roster_seen_at': now,
             'replacement_listed': True, 'replacement_clan_tag': '#2UVGQU9',
             'replacement_priority': 'replace_first', 'weight': 100000},
            {'player_tag': '#8GG82', 'current_clan_tag': '#2UVGQU9', 'roster_seen_at': now,
             'weight': 100000},
        ], {'#8GG82': 3})
        rows = await StrikeService(mongo).replacement(123)
        assert [row['player_tag'] for row in rows] == ['#PC9YGL0JL', '#8GG82']
        assert rows[0]['active_strikes'] == 0 and rows[0]['is_manual']
        assert rows[1]['active_strikes'] == 3 and not rows[1]['is_manual']
    asyncio.run(run())


def test_clan_transfer_does_not_carry_manual_priority_or_note():
    async def run():
        now = datetime.now(timezone.utc)
        mongo = Mongo([{'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#8GG82',
                        'roster_seen_at': now, 'replacement_listed': True,
                        'replacement_clan_tag': '#2UVGQU9',
                        'replacement_priority': 'replace_first', 'replacement_note': 'Filler'}],
                      {'#PC9YGL0JL': 1})
        rows = await StrikeService(mongo).replacement(123)
        assert len(rows) == 1
        assert rows[0]['replacement_priority'] == 'normal'
        assert rows[0]['replacement_note'] == ''
        assert not rows[0]['is_manual']
        assert rows[0]['active_strikes'] == 1
    asyncio.run(run())


def test_known_weights_rank_ahead_of_unknown_for_fwa_matching():
    async def run():
        now = datetime.now(timezone.utc)
        mongo = Mongo([
            {'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9', 'roster_seen_at': now,
             'replacement_listed': True, 'replacement_clan_tag': '#2UVGQU9',
             'replacement_priority': 'replace_first'},
            {'player_tag': '#8GG82', 'current_clan_tag': '#2UVGQU9', 'roster_seen_at': now,
             'weight': 100000},
        ])
        rows = await StrikeService(mongo).replacement(123, 100000)
        assert [row['player_tag'] for row in rows] == ['#8GG82', '#PC9YGL0JL']
        assert rows[-1]['weight'] is None and rows[-1]['weight_difference'] is None
    asyncio.run(run())


def test_add_and_remove_manual_preference_keeps_strikes():
    async def run():
        mongo = Mongo([], {'#PC9YGL0JL': 2})
        service = StrikeService(mongo)
        await service.set_replacement_preference(123, '#PC9YGL0JL', 'high', 'Needs space', 456,
                                                 clan_tag='#2UVGQU9', player_name='Player')
        row = mongo.strike_profiles.rows['123:#PC9YGL0JL']
        assert row['replacement_priority'] == 'high'
        assert row['replacement_note'] == 'Needs space'
        await service.clear_replacement_preference(123, '#PC9YGL0JL', 456)
        assert 'replacement_priority' not in row
        assert mongo.strike_records.counts['#PC9YGL0JL'] == 2
    asyncio.run(run())


def test_replacement_mutation_denied_before_player_or_database_lookup():
    async def deny(request, section, *, write=False):
        assert section == 'strikes' and write
        raise web.HTTPForbidden()
    async def run():
        with patch.object(strikes.shared, 'require_manage', deny):
            with pytest.raises(web.HTTPForbidden):
                await strikes.add_replacement_list(SimpleNamespace(method='POST'))
    asyncio.run(run())


def test_mark_stays_visible_when_roster_scan_is_stale():
    async def run():
        mongo = Mongo([{'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9',
                        'roster_seen_at': datetime.now(timezone.utc) - timedelta(hours=2),
                        'replacement_listed': True, 'replacement_clan_tag': '#2UVGQU9',
                        'replacement_priority': 'high'}])
        rows = await StrikeService(mongo).replacement(123)
        assert len(rows) == 1
        assert rows[0]['is_manual']
        assert not rows[0]['clan_is_current']
        assert await StrikeService(mongo).replacement(123, 100000) == []
    asyncio.run(run())


def test_replacement_list_crud_routes_are_registered():
    registered = {(route.method, route.path) for route in strikes.routes}
    root = strikes.API + '/replacement-list'
    assert ('POST', root) in registered
    assert ('PUT', root + '/{player_tag}') in registered
    assert ('DELETE', root + '/{player_tag}') in registered


def test_browse_all_and_family_scope_include_unmarked_main_accounts():
    async def run():
        now = datetime.now(timezone.utc)
        mongo = Mongo([
            {'player_tag': '#PC9YGL0JL', 'current_clan_tag': '#2UVGQU9',
             'roster_seen_at': now, 'town_hall': 16, 'weight': 149000},
            {'player_tag': '#8GG82', 'current_clan_tag': '#8GG82',
             'roster_seen_at': now, 'town_hall': 17, 'weight': 150000},
        ])
        service = StrikeService(mongo)
        assert await service.replacement(123) == []
        browsed = await service.replacement(123, browse_all=True)
        assert {row['player_tag'] for row in browsed} == {'#PC9YGL0JL', '#8GG82'}
        fwa = await service.replacement(123, 149000)
        assert [row['player_tag'] for row in fwa] == ['#PC9YGL0JL']
        family = await service.replacement(123, 149000, family_scope='all')
        assert {row['player_tag'] for row in family} == {'#PC9YGL0JL', '#8GG82'}
        th17 = await service.replacement(123, browse_all=True, town_hall=17)
        assert [row['player_tag'] for row in th17] == ['#8GG82']
    asyncio.run(run())


def test_sync_roster_saves_town_hall_without_guessing_missing_values():
    async def run():
        class Profiles:
            def __init__(self):
                self.writes = []
            async def update_many(self, query, update):
                pass
            async def update_one(self, query, update, upsert=False):
                self.writes.append(update['$set'])
        profiles = Profiles()
        db = SimpleNamespace(strike_profiles=profiles)
        await StrikeService(db).sync_roster(123, '#2UVGQU9', [
            {'tag': '#PC9YGL0JL', 'name': 'Player', 'town_hall': 16},
            {'tag': '#8GG82', 'name': 'Other'}])
        assert profiles.writes[0]['town_hall'] == 16
        assert 'town_hall' not in profiles.writes[1]
    asyncio.run(run())


@pytest.mark.parametrize('official', ['absent', 152000, None])
def test_dashboard_replacement_query_normalizes_weight_and_passes_filters(tmp_path, official):
    import json
    from contextlib import asynccontextmanager

    class Cursor:
        async def to_list(self, length=None):
            return [{'player_tag': '#PC9YGL0JL'}]

    class Db:
        class Profiles:
            def find(self, query):
                assert '#8GG82' in query['current_clan_tag']['$in']
                return Cursor()
        strike_profiles = Profiles()

    class Provider:
        async def weights(self, tags):
            assert tags == ['#PC9YGL0JL']
            return {'#PC9YGL0JL': {'weight': 149000}}

    class Ledger:
        async def replacement(self, guild_id, weight, **options):
            assert options['weights']['#PC9YGL0JL'] == (151000 if official == 'absent' else official)
            assert weight == 149000
            assert options['family_scope'] == 'all'
            assert options['browse_all'] is True
            assert options['town_hall'] == 16
            return []

    async def permit(request, section, *, write=False):
        assert section == 'strikes_read' and not write

    @asynccontextmanager
    async def mongo(request):
        yield Db()

    async def create_service(request, db):
        return Ledger()

    async def clans(db):
        return [{'tag': '#2UVGQU9', 'name': 'FWA', 'is_fwa': True},
                {'tag': '#8GG82', 'name': 'Main', 'is_fwa': False}]

    from cwl_web.store import Store
    store = Store(str(tmp_path / 'weights.sqlite'))
    with store.tx() as db:
        db.execute("INSERT INTO player_weights(tag,weight,updated_at) VALUES('#PC9YGL0JL',151000,'2026-10-23')")
        if official != 'absent':
            db.execute("INSERT INTO clan_player_weights(tag,weight,revision,player_name,town_hall,last_clan_tag,last_clan_name,updated_at,actor_id) VALUES('#PC9YGL0JL',?,1,'Sample',16,'#2UVGQU9','Sample','2026-10-23','1')", (official,))

    async def run():
        request = SimpleNamespace(method='GET', query={'weight': '149k' , 'scope': 'all',
                                  'browse_all': 'true', 'town_hall': '16'},
                                  app={'providers': Provider(), 'store': store})
        with patch.object(strikes.shared, 'require_manage', permit), \
             patch.object(strikes.shared, 'mongo', mongo), \
             patch.object(strikes, 'service', create_service), \
             patch.object(strikes, 'clan_rows', clans), \
             patch('cwl_web.app._store', return_value=store):
            return await strikes.replacements(request)
    data = json.loads(asyncio.run(run()).text)
    assert data['matching_weight'] == 149000
    assert data['matching_weight_label'] == '149k'
    assert data['scope'] == 'all' and data['town_hall'] == 16
