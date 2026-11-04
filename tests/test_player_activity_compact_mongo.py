"""159 compact read equivalence on an explicitly owned, isolated Mongo only."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from pymongo import AsyncMongoClient

from utils.player_activity_overview import family_activity_rows
from utils.player_activity_store import PlayerActivityStore
from tests.fixtures.strike_activity_955_reference import overview_reference, activity_context_reference

pytestmark = pytest.mark.skipif(os.getenv('WU159_OWNED_SNAPSHOT') != '1', reason='fresh owned159 Mongo required')


def owned_uri():
    receipt_path = Path(os.environ['WU159_OWNED_SNAPSHOT_RECEIPT'])
    assert receipt_path.resolve().is_relative_to(Path(__file__).resolve().parents[1] / '.local/read159')
    receipt = json.loads(receipt_path.read_text())
    pid, data = receipt['pid'], receipt['dbpath']
    args = Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')
    assert Path(f'/proc/{pid}/exe').resolve() == Path('/home/ruggie/.local/opt/wu-backup-tools/mongod').resolve()
    assert args[args.index('--dbpath')+1] == data
    assert args[args.index('--port')+1] == '27171'
    assert receipt['listener_owned_before_client'] is True
    return 'mongodb://127.0.0.1:27171'


def test_compact_125_account_snapshot_is_equivalent_and_does_not_change_documents():
    async def run():
        client = AsyncMongoClient(owned_uri(), tz_aware=True, serverSelectionTimeoutMS=2000)
        db = client['wu159_compact_equivalence']
        now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
        try:
            original = []
            for index in range(125):
                original.append({'_id': f'p{index}', 'tag': f'#P{index}', 'name': f'Player {index}',
                    'current_clan_tag': '#CLAN', 'last_seen_at': now-timedelta(days=index%20),
                    'updated_at': now, 'last_seen_source': 'fixture', 'tracking_started_at': now-timedelta(days=90),
                    'baseline': {'townHallLevel': 16, 'unused': 'x'*5000}, 'active_days': ['not needed'],
                    'recent_wars': [{'war_key': f'war:{war}', 'occurred_at': now-timedelta(days=war),
                                     'attacks_used': (index+war)%3, 'attacks_available': 2,
                                     'neutral': war == 3, 'unusable': war == 5} for war in range(14)],
                    'raid_weekends': [{'weekend_id': (now-timedelta(days=2+7*week)).isoformat(),
                                      'attacked': (index+week)%2 == 0, 'unused': 'large unused raid metadata'} for week in range(8)]})
            original.append({'_id': 'history', 'kind': 'history_clan', 'clan_tag': '#CLAN', 'lineups': ['never transfer']})
            await db.player_activity.insert_many(deepcopy(original))
            store = PlayerActivityStore(SimpleNamespace(player_activity=db.player_activity))
            before = await db.player_activity.find({}).sort('_id', 1).to_list(length=None)
            old = await overview_reference(store)
            compact = await store.overview()
            clans = [{'tag': '#CLAN', 'name': 'Family'}]
            records = [{'player_tag': '#P0', 'source': 'war', 'kind': 'exempt', 'war_key': 'war:0'},
                       {'player_tag': '#P1', 'source': 'manual', 'kind': 'strike',
                        'occurred_at': now, 'expires_at': now+timedelta(days=60)}]
            assert len(old) == len(compact) == 125
            assert family_activity_rows(old, [], records, clans, now=now) == family_activity_rows(compact, [], records, clans, now=now)
            assert await db.player_activity.find({}).sort('_id', 1).to_list(length=None) == before
            assert all('active_days' not in row and 'unused' not in row['baseline'] for row in compact)
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())


@pytest.mark.parametrize('value', ['missing', None, 0])
@pytest.mark.parametrize('unusable', [False, True])
def test_optional_missed_attacks_missing_null_zero_match_the_original(value, unusable):
    async def run():
        client = AsyncMongoClient(owned_uri(), tz_aware=True, serverSelectionTimeoutMS=2000)
        db = client['wu159_compact_missing_null_zero']
        now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
        war = {'war_key': 'same-war', 'occurred_at': now, 'unusable': unusable,
               'attacks_used': 0, 'attacks_available': 2}
        if value != 'missing':
            war['missed_attacks'] = value
        original = {'_id': 'one', 'tag': '#PYY', 'current_clan_tag': '#CLAN',
                    'updated_at': now, 'recent_wars': [war], 'raid_weekends': []}
        try:
            await db.player_activity.insert_one(deepcopy(original))
            store = PlayerActivityStore(SimpleNamespace(player_activity=db.player_activity))
            old = await overview_reference(store)
            projected = await store.overview()
            assert projected[0]['recent_wars'] == old[0]['recent_wars']
            assert ('missed_attacks' in projected[0]['recent_wars'][0]) == (value != 'missing')
            def result(rows):
                try:
                    return ('ok', family_activity_rows(rows, [], [], [{'tag': '#CLAN'}], now=now))
                except (TypeError, ValueError, KeyError) as error:
                    return ('error', type(error))
            assert result(old) == result(projected)
            assert await db.player_activity.find_one({'_id': 'one'}) == original
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())


def test_ledger_projection_preserves_missing_null_zero_and_input_order():
    from utils.strike_activity_projection import FIELDS, observation_pipeline, decode_observations
    async def run():
        client = AsyncMongoClient(owned_uri(), tz_aware=True, serverSelectionTimeoutMS=2000)
        db = client['wu159_ledger_presence_equivalence']
        originals = []
        for index, value in enumerate(('missing', None, 0)):
            row = {'_id': str(index), 'source': 'war', 'kind': 'exempt'}
            if value != 'missing':
                row.update({field: value for field in ('player_tag', 'war_key',
                    'missed_attacks', 'revoked_at', 'import_id', 'exemption')})
            originals.append(row)
        try:
            await db.strike_records.insert_many(deepcopy(originals))
            raw = await db.strike_records.find({}).to_list(length=None)
            packed = await (await db.strike_records.aggregate(observation_pipeline({}))).to_list(length=1)
            expected = [{key: value for key, value in row.items() if key in FIELDS} for row in raw]
            assert decode_observations(packed[0]) == expected
            assert 'missed_attacks' not in expected[0]
            assert expected[1]['missed_attacks'] is None
            assert expected[2]['missed_attacks'] == 0
            assert await db.strike_records.find({}).to_list(length=None) == originals
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())


def test_authenticated_http_125_cold_fill_core_failure_and_explicit_diagnostics(tmp_path, monkeypatch):
    """Real HTTP/session/permission adapters over owned Mongo; fake Discord only."""
    import hashlib
    import secrets
    import time
    from unittest.mock import AsyncMock
    from aiohttp.test_utils import TestClient, TestServer
    from cwl_web import create_app
    from cwl_web.app import PERMANENT_OWNER_ID
    from cwl_web.server_management import GUILD_ID
    from cwl_web.providers import FixtureProviders
    from cwl_web.strikes import public
    from cwl_web.strike_activity_cache import snapshots
    from utils.strike_store import StrikeService
    from pymongo.errors import NetworkTimeout

    async def run():
        native = AsyncMongoClient(owned_uri(), tz_aware=True, serverSelectionTimeoutMS=2000)
        db = native['wu159_http_equivalence']
        now = datetime.now(timezone.utc).replace(microsecond=0)
        clan = '#2UVGQU9'
        alphabet = '0289PYLQGRJCUV'
        profiles, activity, records = [], [], []
        for index in range(125):
            player = '#P'+alphabet[index//len(alphabet)]+alphabet[index%len(alphabet)]
            profiles.append({'_id': player, 'guild_id': GUILD_ID, 'player_tag': player,
                             'player_name': f'Fixture {index}', 'current_clan_tag': clan, 'weight': 149000})
            activity.append({'_id': player, 'tag': player, 'name': f'Fixture {index}',
                'current_clan_tag': clan, 'updated_at': now, 'last_seen_at': now-timedelta(days=3),
                'baseline': {'townHallLevel': 16, 'unused': 'x'*5000},
                'recent_wars': [{'war_key': f'war:{number}', 'occurred_at': now-timedelta(days=number),
                                 'attacks_used': number % 3, 'attacks_available': 2} for number in range(14)],
                'raid_weekends': []})
            for number in range(3):
                records.append({'_id': f'{player}:{number}', 'guild_id': GUILD_ID,
                    'player_tag': player, 'kind': 'strike', 'source': 'manual',
                    'occurred_at': now-timedelta(days=number+1),
                    'expires_at': now+timedelta(days=30) if number < 2 else now-timedelta(days=1)})
        web_client = None
        try:
            await db.clans.insert_one({'tag': clan, 'name': 'Fixture family'})
            await db.strike_profiles.insert_many(profiles)
            await db.player_activity.insert_many(activity)
            await db.strike_records.insert_many(records)
            before = {name: await db[name].find({}).sort('_id', 1).to_list(length=None)
                      for name in await db.list_collection_names()}
            ledger = StrikeService(db)
            start = time.perf_counter()
            old_activity = await overview_reference(PlayerActivityStore(db))
            old_context = await activity_context_reference(ledger, GUILD_ID, [row['tag'] for row in activity])
            expected = public(family_activity_rows(old_activity, **old_context, now=now))
            old_seconds = time.perf_counter()-start
            release = asyncio.Event()
            original = ledger.activity_observations
            async def delayed_observations(guild_id):
                await release.wait()
                return await original(guild_id)
            ledger.activity_observations = delayed_observations
            providers = FixtureProviders(str(PERMANENT_OWNER_ID))
            providers.weights = AsyncMock(return_value={})
            app = create_app(db_path=str(tmp_path/'http.sqlite'), providers=providers,
                             dev_fixture=True, secure_cookies=False, live_access=True)
            app['server_management_mongo'] = db
            app['strike_service'] = ledger
            async def discord(method, path, **kwargs):
                assert method == 'GET'
                if path.endswith('/roles'):
                    return []
                if '/members/' in path:
                    return {'user': {'id': path.rsplit('/', 1)[-1]}, 'roles': []}
                return {'owner_id': str(PERMANENT_OWNER_ID)}
            app['server_management_discord'] = discord
            monkeypatch.setattr('cwl_web.strike_activity_identity.account_identities', AsyncMock(return_value=({}, False)))
            monkeypatch.setattr('cwl_web.strike_activity_identity.identity_updating', lambda request: False)
            web_client = TestClient(TestServer(app))
            await web_client.start_server()
            def headers(user_id):
                token, csrf = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
                with app['store'].tx() as sql:
                    sql.execute('INSERT INTO sessions(token_hash,user_id,username,guild_owner,csrf,expires_at) VALUES (?,?,?,?,?,?)',
                        (hashlib.sha256(token.encode()).hexdigest(), str(user_id), 'Fixture', 0, csrf, int(time.time())+900))
                return {'Cookie': 'cwl_session='+token, 'X-CSRF-Token': csrf}
            path = '/api/cwl/strikes/accounts?activity=true'
            assert (await web_client.get(path)).status == 401
            assert not snapshots(app).entries
            assert (await web_client.get(path, headers=headers('100'))).status == 403
            assert not snapshots(app).entries
            owner = headers(PERMANENT_OWNER_ID)
            start = time.perf_counter()
            response = await web_client.get(path, headers=owner)
            cold_seconds = time.perf_counter()-start
            assert response.status == 200
            cold = await response.json()
            assert len(cold['accounts']) == 125 and cold['activity_updating']
            assert all(row['active_strikes'] == 2 and row['total_strikes'] == 3
                       and row['activity_unavailable'] and row['quiet_days'] is None for row in cold['accounts'])
            release.set()
            await snapshots(app).entries[GUILD_ID].task
            start = time.perf_counter()
            response = await web_client.get(path, headers=owner)
            filled_seconds = time.perf_counter()-start
            assert response.status == 200
            filled = await response.json()
            assert filled['accounts'] == expected
            assert not filled['activity_updating'] and filled['activity_as_of'].startswith('Activity as of ')
            assert {row['player_tag'] for row in cold['accounts']} <= {row['player_tag'] for row in filled['accounts']}
            assert cold_seconds < 3 and filled_seconds < 3
            healthy = {name: await db[name].find({}).sort('_id', 1).to_list(length=None)
                       for name in await db.list_collection_names()}
            assert healthy == before
            ledger.activity_core = AsyncMock(side_effect=NetworkTimeout('isolated required core failure'))
            failure_started = time.time()
            response = await web_client.get(path, headers=owner)
            assert response.status == 503
            failure = await response.json()
            after = {name: await db[name].find({}).sort('_id', 1).to_list(length=None)
                     for name in await db.list_collection_names()}
            assert set(after) == set(before) | {'bot_config'}
            assert {name: after[name] for name in before} == before
            assert len(after['bot_config']) == 1
            document = after['bot_config'][0]
            assert set(document) == {'_id', 'items'} and document['_id'] == 'dashboard-issues-v1'
            assert len(document['items']) == 1
            issue = document['items'][0]
            assert set(issue) == {'id', 'at', 'member', 'kind', 'status', 'action', 'method', 'error_type'}
            assert issue['id'] == failure['issue_reference']
            assert issue['kind'] == 'service_unavailable' and issue['status'] == 503
            assert issue['action'] == '/api/cwl/strikes/accounts' and issue['method'] == 'GET'
            assert issue['error_type'] == 'NetworkTimeout' and issue['member'] == str(PERMANENT_OWNER_ID)
            assert failure_started <= issue['at'] <= time.time()
            receipt = Path(os.environ['WU159_OWNED_SNAPSHOT_RECEIPT'])
            receipt.with_name(receipt.stem+'-http-timing.json').write_text(json.dumps({
                'accounts': 125, 'old_serial_reference_read_and_assembly_seconds': old_seconds,
                'authenticated_cold_http_seconds': cold_seconds, 'authenticated_filled_http_seconds': filled_seconds,
                'discord_and_weights_fixture_only': True, 'owned_mongo_only': True, 'production_writes': 0})+'\n')
        finally:
            if web_client is not None:
                await web_client.close()
            await native.drop_database(db.name)
            await native.close()
    asyncio.run(run())


def test_summarized_ledger_matches_full_125_account_output_with_imports_and_exemptions():
    from utils.strike_store import StrikeService
    from bson import BSON
    async def run():
        client = AsyncMongoClient(owned_uri(), tz_aware=True, serverSelectionTimeoutMS=2000)
        db = client['wu159_ledger_summary_equivalence']
        now = datetime.now(timezone.utc).replace(microsecond=0)
        clan, guild = '#2UVGQU9', 123
        alphabet = '0289PYLQGRJCUV'
        activities, profiles, records = [], [], []
        try:
            await db.clans.insert_one({'tag': clan, 'name': 'Family'})
            for index in range(125):
                player = '#P'+alphabet[index//len(alphabet)]+alphabet[index%len(alphabet)]
                profiles.append({'_id': player, 'guild_id': guild, 'player_tag': player,
                    'player_name': f'Player {index}', 'current_clan_tag': clan,
                    'roster_seen_at': now, 'weight': 140000, 'replacement_listed': index%3 == 0,
                    'replacement_clan_tag': clan, 'replacement_priority': 'high', 'revision': index})
                activities.append({'tag': player, 'name': f'Player {index}', 'current_clan_tag': clan,
                    'updated_at': now, 'last_seen_at': now-timedelta(days=index%20),
                    'raid_weekends': [], 'recent_wars': [
                        {'war_key': 'neutral-war', 'occurred_at': now-timedelta(days=2), 'attacks_used': 0, 'attacks_available': 2},
                        {'war_key': 'monitored-war', 'occurred_at': now-timedelta(days=3), 'attacks_used': 0, 'attacks_available': 2}]})
                for number in range(12):
                    records.append({'_id': f'{player}:import:{number}', 'guild_id': guild,
                        'player_tag': player, 'kind': 'strike', 'source': 'war', 'import_id': 'fixture-import',
                        'occurred_at': now-timedelta(days=number+1), 'expires_at': now+timedelta(days=40),
                        'war_key': f'imported-war:{number}'})
                records.extend([
                    {'_id': player+':exempt', 'guild_id': guild, 'player_tag': player, 'source': 'war',
                     'kind': 'exempt', 'import_id': 'fixture-import', 'war_key': 'neutral-war', 'occurred_at': now-timedelta(days=2)},
                    {'_id': player+':manual', 'guild_id': guild, 'player_tag': player, 'source': 'manual',
                     'kind': 'strike', 'occurred_at': now-timedelta(days=1), 'expires_at': now+timedelta(days=30)},
                    {'_id': player+':revoked', 'guild_id': guild, 'player_tag': player, 'source': 'manual',
                     'kind': 'strike', 'occurred_at': now-timedelta(days=1), 'expires_at': now+timedelta(days=30), 'revoked_at': now},
                    {'_id': player+':expired', 'guild_id': guild, 'player_tag': player, 'source': 'manual',
                     'kind': 'strike', 'occurred_at': now-timedelta(days=40), 'expires_at': now-timedelta(days=1)},
                    {'_id': player+':monitored', 'guild_id': guild, 'player_tag': player, 'source': 'war',
                     'capture_source': 'clash_api', 'kind': 'completed', 'war_key': 'monitored-war',
                     'occurred_at': now-timedelta(days=3), 'missed_attacks': 0},
                ])
            await db.strike_profiles.insert_many(profiles)
            await db.strike_records.insert_many(records)
            before = await db.strike_records.find({}).sort('_id', 1).to_list(length=None)
            ledger = StrikeService(db)
            tags = [row['tag'] for row in activities]
            old = await activity_context_reference(ledger, guild, tags)
            core = await ledger.activity_core(guild)
            from utils.player_activity_overview import activity_view_context
            compact = activity_view_context(core, activities, await ledger.activity_observations(guild), now=now)
            old_rows = family_activity_rows(activities, **old, now=now)
            new_rows = family_activity_rows(activities, **compact, now=now)
            assert len(new_rows) == 125 and old_rows == new_rows
            core_rows = family_activity_rows(activities,
                **activity_view_context(core, activities, compact['records'], now=now), now=now)
            assert core_rows == old_rows
            cold_rows = family_activity_rows([], **activity_view_context(core, None, None, now=now), now=now)
            cold_by_tag = {row['player_tag']: row for row in cold_rows}
            filled_by_tag = {row['player_tag']: row for row in core_rows}
            assert set(cold_by_tag) <= set(filled_by_tag)
            assert all(cold_by_tag[player]['active_strikes'] == filled_by_tag[player]['active_strikes']
                       and cold_by_tag[player]['total_strikes'] == filled_by_tag[player]['total_strikes']
                       for player in cold_by_tag)
            fresh_observations = await ledger.activity_observations(guild)
            from utils.strike_activity_projection import FIELDS
            from utils.strike_activity_summary import record_query, observation_query
            native_observations = await db.strike_records.find(
                observation_query(record_query(guild, None, now)),
                {'_id': 0, **{key: 1 for key in FIELDS}}).to_list(length=None)
            assert fresh_observations == native_observations
            assert family_activity_rows(activities,
                **activity_view_context(core, activities, fresh_observations, now=now), now=now) == old_rows
            # Exercise the selected HTTP read path with a warm real dictionary
            # snapshot, fresh core counts and fresh manual dispositions.
            from types import SimpleNamespace
            from cwl_web.strike_activity_reads import read_activity
            from cwl_web.strike_activity_cache import snapshots
            await db.player_activity.insert_many(activities)
            request = SimpleNamespace(app={})
            cache = snapshots(request.app)
            try:
                from utils.player_activity_cache import ActivityPayload
                async def load():
                    return ActivityPayload(await PlayerActivityStore(db).overview(),
                                           await ledger.activity_observations(guild))
                await cache.get(guild, load, require_observations=True)
                await cache.entries[guild].task
                view = await read_activity(request, db, ledger, guild)
                assert not view.unavailable and view.warning.startswith('Activity as of ')
                assert family_activity_rows(view.activity, **view.context, now=now) == old_rows
            finally:
                await cache.close()
            assert all(row['active_strikes'] == 13 and row['total_strikes'] == 15 for row in new_rows)
            assert all(row['new_this_week'] and row['observed_attacks'] == 2 and row['missed_attacks'] == 0 for row in new_rows)
            assert len(compact['records']) < len(old['records']) / 4
            assert sum(len(BSON.encode(row)) for row in compact['records']) < sum(len(BSON.encode(row)) for row in old['records']) / 4
            assert await db.strike_records.find({}).sort('_id', 1).to_list(length=None) == before
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())


def test_scheduled_projection_reads_preserve_write_results_and_all_documents(monkeypatch):
    """Compare full-read vs projected-read inputs to the unchanged job writers."""
    from utils import player_activity_store as activity_owner
    from utils.player_activity_raids import capture_raids
    from utils.player_activity_seed import seed_players
    class FullReadStore(PlayerActivityStore):
        async def all_players(self, *, view=None):
            return await super().all_players()
        async def get(self, player_tag, *, view=None):
            return await super().get(player_tag)
    now = datetime(2026, 11, 2, 7, 30, tzinfo=timezone.utc)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now
    monkeypatch.setattr(activity_owner, 'datetime', Clock)
    async def run():
        client = AsyncMongoClient(owned_uri(), tz_aware=True, serverSelectionTimeoutMS=2000)
        db = client['wu159_scheduled_projection_equivalence']
        alphabet = '0289PYLQGRJCUV'
        players = ['#P'+alphabet[i//len(alphabet)]+alphabet[i%len(alphabet)] for i in range(125)]
        clan = '#2UVGQU9'
        documents = [{'_id': player, 'tag': player, 'name': 'Known player', 'revision': 1,
            'current_clan_tag': clan, 'left_at': None, 'family_since': now-timedelta(days=60),
            'last_roster_at': now-timedelta(hours=1), 'previous_roster_at': now-timedelta(minutes=90),
            'raid_membership_ends': [], 'raid_clan_history': [], 'raid_weekends': [],
            'raid_checked_weekends': [], 'raid_logs_reviewed': [],
            'recent_wars': [{'war_key': 'old', 'occurred_at': now-timedelta(days=2),
                             'attacks_used': 0, 'attacks_available': 2, 'neutral': True}],
            'baseline': {'attackWins': 5, 'troops': 'large unrelated payload'*1000},
            'unrelated_saved_text': 'Keep this exactly'} for player in players]
        async def no_sleep(seconds):
            return None
        async def seed(player):
            return now-timedelta(days=1)
        async def raid(clan_tag, limit):
            return [SimpleNamespace(end_time=now-timedelta(minutes=30),
                members=[SimpleNamespace(tag=player, attack_count=i%3) for i, player in enumerate(players)])]
        async def jobs(store):
            await store.reconcile_membership({player: clan for player in players}, now=now)
            raids = await capture_raids(store, SimpleNamespace(get_raid_log=raid), [clan], now=now)
            for player in players:
                await store.save_recent_wars(player, [{'war_key': 'new', 'occurred_at': now,
                    'attacks_used': 1, 'attacks_available': 2}], version=3, now=now)
            seeds = await seed_players(store, seed, sleep=no_sleep)
            return {'raids': raids, 'seeds': seeds}
        try:
            await db.full.insert_many(deepcopy(documents))
            await db.projected.insert_many(deepcopy(documents))
            before = await db.full.find({}).sort('_id', 1).to_list(length=None)
            old = await jobs(FullReadStore(SimpleNamespace(player_activity=db.full)))
            new = await jobs(PlayerActivityStore(SimpleNamespace(player_activity=db.projected)))
            assert old == new
            full_rows = await db.full.find({}).sort('_id', 1).to_list(length=None)
            projected_rows = await db.projected.find({}).sort('_id', 1).to_list(length=None)
            assert len(full_rows) == 125 and full_rows == projected_rows
            assert all(row['unrelated_saved_text'] == 'Keep this exactly' for row in projected_rows)
            assert [row['baseline'] for row in projected_rows] == [row['baseline'] for row in before]
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())
