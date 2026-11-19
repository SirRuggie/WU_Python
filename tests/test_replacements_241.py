"""Accepted 241 recruit/Left contracts over isolated SQLite and Mongo fixtures."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from multidict import MultiDict

from cwl_web import strikes as api
from cwl_web.providers import ProviderUnavailable
from cwl_web.store import Store
from extensions.commands import strikes as discord
from utils.clan_weights import replacement_saved_weights, replacement_weights, recruit_weight_groups
from utils.player_activity_overview import family_activity_rows
from utils.recruit_links import LinksResult
from utils.replacement_view import find_slots
from test_strike_ux_backend import setup, record, Cursor
from test_strike_replacement_panel import text_of

MEMBER = '111111111111111111'
NOW = datetime.now(timezone.utc)


def test_saved_groups_newest_five_disputed_unknown_and_duplicate_identity():
    saved = {f'#P{i}': {'name': 'Same', 'saved_weight': 179000,
                        'saved_at': f'2026-11-{10+i:02}T00:00:00Z'} for i in range(6)}
    result = recruit_weight_groups(set(saved) | {'#NONE'}, saved, disputed={'#P5'})
    assert [row['account_tag'] for row in result['groups']] == ['#P5', '#P4', '#P3', '#P2', '#P1']
    assert len({row['account_tag'] for row in result['groups']}) == 5
    assert result['member_notice'] == 'Showing 5 of 6 accounts'
    assert next(row for row in result['member_accounts'] if row['tag'] == '#NONE')['saved_weight'] is None
    assert next(row for row in result['member_accounts'] if row['tag'] == '#P5')['link_disputed']
    typed = recruit_weight_groups(set(saved), saved, weights=[150000, 179000])
    assert [row['weight'] for row in typed['groups']] == [150000, 179000]
    assert [row['source'] for row in typed['groups']] == ['typed', 'typed']
    assert typed['groups'][1]['label'] == 'Same · 179k'


def test_saved_manual_feed_profile_fallback_and_explicit_clear(tmp_path):
    store = Store(str(tmp_path / 'fixture.sqlite'))
    with store.tx() as db:
        db.execute("INSERT INTO player_weights VALUES('#P2Y',150000,150000,'2026-11-18T00:00:00Z')")
        db.execute("INSERT INTO player_weights VALUES('#Q2Y',160000,160000,'2026-11-18T00:00:00Z')")
        for player, weight in (('#P2Y', 179000), ('#R2Y', None)):
            db.execute('INSERT INTO clan_player_weights(tag,weight,revision,player_name,last_clan_tag,last_clan_name,updated_at,actor_id) VALUES(?,?,1,?,?,?,?,?)',
                       (player, weight, 'SHOGUN', '', '', '2026-11-17T00:00:00Z', '1'))
    saved = replacement_saved_weights(store, ['#P2Y', '#Q2Y', '#R2Y', '#U2Y', '#V2Y'])
    profiles = [{'player_tag': tag, 'weight': 120000} for tag in ('#P2Y', '#Q2Y', '#R2Y', '#U2Y', '#V2Y')]
    feed = {row['player_tag']: {'weight': 170000} for row in profiles[:4]}
    assert replacement_weights(profiles, saved, feed) == {
        '#P2Y': 179000, '#Q2Y': 160000, '#R2Y': None, '#U2Y': 170000, '#V2Y': 120000}
    assert '#V2Y' not in saved


async def fixture(tmp_path):
    db, ledger = setup()
    await db.clans.insert_one({'_id': 'fwa', 'tag': '#Q2Y', 'name': 'Family', 'type': 'FWA'})
    for i, (player, weight, age) in enumerate((('#P2Y', 179000, 1), ('#R2Y', 160000, 1),
                                              ('#U2Y', 179000, 49), ('#V2Y', None, 1))):
        await db.strike_profiles.insert_one({'_id': player, 'guild_id': api.GUILD_ID,
            'player_tag': player, 'player_name': player, 'weight': weight,
            'current_clan_tag': '#Q2Y', 'roster_seen_at': NOW - timedelta(hours=age), 'town_hall': 16})
        for j in range(3):
            await db.strike_records.insert_one(record(f'{i}-{j}', player, guild_id=api.GUILD_ID,
                                                      expires_at=NOW + timedelta(days=10)))
    # Make the collection projection-faithful and record physical reads.
    for collection in (db.clans, db.strike_profiles):
        original = collection.find
        def projected(query, projection=None, *, original=original):
            rows = original(query).rows
            if projection and any(value for key, value in projection.items() if key != '_id'):
                rows = [{key: value for key, value in row.items() if projection.get(key)} for row in rows]
            return Cursor(rows)
        collection.find = projected
    store = Store(str(tmp_path / 'fixture.sqlite'))
    with store.tx() as sql:
        sql.execute('INSERT INTO clan_player_weights(tag,weight,revision,player_name,last_clan_tag,last_clan_name,updated_at,actor_id) VALUES(?,?,1,?,?,?,?,?)',
                    ('#QVVJG0VR', 179000, 'SHOGUN', '', '', '2026-11-17T00:00:00Z', '1'))
    return db, ledger, store


def request_for(store, ledger, query, feed):
    return SimpleNamespace(method='GET', query=MultiDict(query), app={
        'store': store, 'providers': SimpleNamespace(weights=feed), 'strike_service': ledger})


def test_recruit_without_family_account_same_slots_both_transports_and_readonly(tmp_path, monkeypatch):
    async def run():
        db, ledger, store = await fixture(tmp_path)
        before = deepcopy((db.strike_records.rows, db.strike_profiles.rows))
        with store.read() as sql:
            sql_before = list(map(tuple, sql.execute('SELECT * FROM clan_player_weights')))
        links = LinksResult(sources={'#QVVJG0VR': ('ClashKing',)}, conflicts=('#QVVJG0VR',))
        @asynccontextmanager
        async def mongo(_):
            yield db
        feed = AsyncMock(return_value={})
        loop_thread = threading.get_ident()
        def off_loop_saved(source, tags):
            assert threading.get_ident() != loop_thread
            return replacement_saved_weights(source, tags)
        with patch('utils.clan_weights.replacement_saved_weights', side_effect=off_loop_saved), \
             patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=links)) as resolve, \
             patch.object(discord, 'cached_weights', return_value={}), \
             patch.object(discord, 'update_state', AsyncMock()), \
             patch.object(db.strike_profiles, 'find', wraps=db.strike_profiles.find) as profiles, \
             patch.object(db.clans, 'find', wraps=db.clans.find) as clans:
            data = json.loads((await api.replacements(request_for(store, ledger, [('member', MEMBER)], feed))).text)
            assert profiles.call_count == clans.call_count == 1
            assert data['slots'][0]['label'] == 'SHOGUN · 179k'
            assert data['slots'][0]['account_tag'] == '#QVVJG0VR'
            assert data['slots'][0]['total'] == 3 and data['unknown_weight'] == 1
            assert data['member_accounts'][0]['link_disputed']
            expected = [row['player_tag'] for row in data['slots'][0]['candidates']]
            assert expected == ['#P2Y', '#R2Y', '#U2Y']  # stale exact match ranks after fresh larger gap
            assert data['slots'][0]['candidates'][-1]['last_seen_label'] == 'Last seen 2 d ago'
            monkeypatch.setenv('CWL_WEB_DB_PATH', store.path)
            state = {'_id': 'fixture-panel', 'guild_id': api.GUILD_ID, 'member_id': int(MEMBER)}
            profiles.reset_mock(); clans.reset_mock(); resolve.reset_mock()
            panel = await discord.replacement_panel(ledger, state)
            text = text_of(panel[0].build()[0])
            assert profiles.call_count == clans.call_count == 1
            assert '### SHOGUN · 179k · Linked to two Discord users' in text
            assert [text.index('`' + tag + '`') for tag in expected] == sorted(text.index('`' + tag + '`') for tag in expected)
            assert 'slot_expanded=a%23QVVJG0VR%3A13' in panel[0].build()[0]['components'][-1]['components'][-1]['url']
            state['page'] = 1
            await discord.replacement_panel(ledger, state)
            assert resolve.await_count == 1  # link resolution reused through paging
        assert (db.strike_records.rows, db.strike_profiles.rows) == before
        with store.read() as sql:
            assert list(map(tuple, sql.execute('SELECT * FROM clan_player_weights'))) == sql_before
        counts = {'strike_records': len(db.strike_records.rows),
                  'profiles': len(db.strike_profiles.rows),
                  'marks': sum(bool(row.get('replacement_listed')) for row in db.strike_profiles.rows.values()),
                  'saved_weights': len(sql_before)}
        print('241_FIXTURE_EVIDENCE=' + json.dumps({'before': counts, 'after': counts,
            'slot_tags': expected, 'discord_panel_text': text, 'endpoint': data}, sort_keys=True))
    asyncio.run(run())


def test_typed_wins_no_links_and_feed_failure_does_not_503(tmp_path):
    async def run():
        db, ledger, store = await fixture(tmp_path)
        @asynccontextmanager
        async def mongo(_):
            yield db
        feed = AsyncMock(side_effect=ProviderUnavailable('fixture outage'))
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=LinksResult())):
            empty = json.loads((await api.replacements(request_for(store, ledger, [('member', MEMBER)], feed))).text)
            assert empty['slots'] == [] and empty['member_notice'] == 'No linked accounts'
            typed = json.loads((await api.replacements(request_for(store, ledger,
                [('member', MEMBER), ('weight', '160k'), ('per_weight', '100')], feed))).text)
            assert typed['weights_stale'] is True
            assert typed['slots'][0]['weight'] == 160000 and typed['slots'][0]['source'] == 'typed'
            assert typed['slots'][0]['candidates'][0]['player_tag'] == '#R2Y'
            assert len(typed['slots'][0]['candidates']) == typed['slots'][0]['total'] == 3
            assert typed['unknown_weight'] == 1
    asyncio.run(run())


def test_left_47h_grace_49h_history_rejoin_and_no_mutation():
    from utils.strike_store import StrikeService
    clans = [{'tag': '#Q2Y', 'name': 'Old'}, {'tag': '#J2Y', 'name': 'New'}]
    profiles = [{'player_tag': f'#P{age}', 'departed_clan_tag': '#Q2Y',
                 'departed_last_seen_at': NOW - timedelta(hours=age), 'weight': 179000,
                 'replacement_listed': True, 'replacement_clan_tag': '#Q2Y'} for age in (47, 49)]
    before = deepcopy(profiles)
    replacements = StrikeService._replacement_rows(profiles, {}, now=NOW, browse_all=True)
    assert [row['player_tag'] for row in replacements] == ['#P47']
    assert replacements[0]['left_label'] == 'Left clan · 1 d ago'
    rows = family_activity_rows([], profiles, [], clans, now=NOW, left_history=None)
    assert rows[0]['current_clan_tag'] == '#Q2Y' and not rows[0]['left_history']
    assert rows[1]['current_clan_tag'] is None and rows[1]['left_history']
    joined = {**profiles[1], 'current_clan_tag': '#J2Y', 'roster_seen_at': NOW}
    rows = family_activity_rows([{'tag': '#P49', 'left_at': profiles[1]['departed_last_seen_at']}],
                                [joined], [], clans, now=NOW)
    assert not rows[0]['left_history'] and not rows[0]['left_clan']
    assert rows[0]['current_clan_tag'] == '#J2Y'
    replacement = StrikeService._replacement_rows([joined], {'#P49': 3}, now=NOW)
    assert replacement[0]['last_seen_clan_tag'] == '#J2Y' and not replacement[0]['departed']
    assert not replacement[0]['is_manual']  # old-clan mark is retained, never transferred
    assert profiles == before


def test_show_more_totals_unknown_and_stale_partition():
    rows = [{'player_tag': f'#{i}', 'last_seen_clan_tag': '#Q2Y', 'active_strikes': 3,
             'replacement_priority': 'normal', 'weight': 179000 + i * 1000,
             'stale': i == 0} for i in range(15)]
    rows.append({**rows[0], 'player_tag': '#UNKNOWN', 'weight': None})
    short = find_slots(rows, [179000], fwa_tags={'#Q2Y'})[0]
    more = find_slots(rows, [179000], fwa_tags={'#Q2Y'}, per_weight=13)[0]
    assert short['total'] == more['total'] == 15
    assert short['unknown_weight'] == more['unknown_weight'] == 1
    assert more['slots'][:3] == short['slots'] and len(more['slots']) == 13
    assert all(row['player_tag'] != '#0' for row in more['slots'])
    for bad in (0, 101, True):
        with pytest.raises(ValueError):
            find_slots(rows, [179000], fwa_tags={'#Q2Y'}, per_weight=bad)


def test_endpoint_uses_five_newest_saved_accounts_and_reports_unknown_once(tmp_path):
    async def run():
        db, ledger, store = await fixture(tmp_path)
        saved_tags = ['#PYY', '#QYY', '#RYY', '#UYY', '#VYY', '#GYY']
        with store.tx() as sql:
            for index, player in enumerate(saved_tags):
                sql.execute('INSERT INTO clan_player_weights(tag,weight,revision,player_name,last_clan_tag,last_clan_name,updated_at,actor_id) VALUES(?,?,1,?,?,?,?,?)',
                            (player, 179000, 'Same', '', '', f'2026-11-{10+index:02}T00:00:00Z', '1'))
        links = LinksResult(sources={tag: ('ClashKing',) for tag in saved_tags + ['#NONE']})
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=links)):
            data = json.loads((await api.replacements(request_for(
                store, ledger, [('member', MEMBER)], AsyncMock(return_value={})))).text)
        assert [row['account_tag'] for row in data['slots']] == list(reversed(saved_tags[1:]))
        assert data['member_notice'] == 'Showing 5 of 6 accounts'
        assert len(data['member_accounts']) == 7
        assert sum(row['saved_weight'] is None for row in data['member_accounts']) == 1
    asyncio.run(run())


def test_activity_http_default_and_left_filter_keep_counts_and_ignore_clan_ownership(tmp_path):
    async def run():
        db, ledger, store = await fixture(tmp_path)
        profiles = [{'player_tag': f'#P{age}', 'departed_clan_tag': '#Q2Y',
                     'departed_last_seen_at': NOW - timedelta(hours=age)} for age in (47, 49, 100)]
        context = {'profiles': profiles, 'records': [], 'clans': [{'tag': '#Q2Y', 'name': 'Family'}],
                   'record_totals': {row['player_tag']: {'active_strikes': 3, 'total_strikes': 4}
                                     for row in profiles}}
        read = SimpleNamespace(activity=[], context=context, warning=None, history_warning=None,
                               unavailable=False, updating=False, checked_at=None)
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'mongo', mongo), \
             patch('cwl_web.strike_activity_reads.read_activity', AsyncMock(return_value=read)), \
             patch('cwl_web.strike_activity_identity.account_identities', AsyncMock(return_value=({}, False))):
            normal = json.loads((await api.activity_accounts(request_for(
                store, ledger, [], AsyncMock(return_value={})))).text)
            history = json.loads((await api.activity_accounts(request_for(
                store, ledger, [('left', 'true')], AsyncMock(return_value={})))).text)
        assert [row['player_tag'] for row in normal['accounts']] == ['#P47']
        assert [row['player_tag'] for row in history['accounts']] == ['#P49', '#P100']
        assert all(row['current_clan_tag'] is None and row['last_clan_tag'] == '#Q2Y'
                   and row['active_strikes'] == 3 for row in history['accounts'])
        assert normal['total'] == 1 and history['total'] == 2
    asyncio.run(run())


def test_optional_snapshot_context_never_widens_when_clan_directory_failed():
    from utils.player_activity_overview import activity_view_context
    with pytest.raises(RuntimeError, match='Family clans could not be checked'):
        activity_view_context({'clan_warning': True}, None, None)


def test_same_instant_roster_transfer_overrides_retained_departure_without_read_writes():
    async def run():
        db, ledger = setup()
        clans = [{'tag': '#Q2Y', 'name': 'Old'}, {'tag': '#J2Y', 'name': 'New'}]
        member = {'tag': '#P2Y', 'name': 'Transferred recruit', 'town_hall': 16}
        await ledger.sync_roster(api.GUILD_ID, '#Q2Y', [member], observed_at=NOW)
        await ledger.sync_roster(api.GUILD_ID, '#J2Y', [member], observed_at=NOW)
        profiles = list(db.strike_profiles.rows.values())
        profile = profiles[0]
        assert profile['roster_seen_at'] == profile['departed_last_seen_at'] == NOW
        assert profile['current_clan_tag'] == '#J2Y'
        before = deepcopy(profiles)
        activity = [{'tag': '#P2Y', 'current_clan_tag': None, 'left_at': NOW}]
        rows = family_activity_rows(activity, profiles, [], clans, now=NOW)
        assert len(rows) == 1 and rows[0]['current_clan_tag'] == '#J2Y'
        assert not rows[0]['left_clan'] and not rows[0]['left_history']
        assert family_activity_rows(activity, profiles, [], clans, now=NOW, left_history=True) == []
        assert profiles == before
        # Missing, older and unknown-family observations still cannot override a departure.
        for changes in ({'roster_seen_at': None},
                        {'roster_seen_at': NOW - timedelta(seconds=1)},
                        {'current_clan_tag': '#V2Y'}):
            conservative = family_activity_rows(activity, [{**profile, **changes}], [], clans, now=NOW)
            assert conservative[0]['left_clan'] and conservative[0]['current_clan_tag'] == '#Q2Y'
    asyncio.run(run())


def test_typed_recruit_missing_weights_use_projected_names_and_unknown_tag_once(tmp_path, monkeypatch):
    async def run():
        db, ledger, store = await fixture(tmp_path)
        db.strike_profiles.rows['#P2Y']['player_name'] = 'Known recruit'
        links = LinksResult(sources={'#P2Y': ('ClashKing',), '#QYY': ('ClashKing',)})
        before = deepcopy((db.strike_profiles.rows, db.strike_records.rows))
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=links)), \
             patch.object(discord, 'cached_weights', return_value={}), \
             patch.object(discord, 'update_state', AsyncMock()), \
             patch.object(db.strike_profiles, 'find', wraps=db.strike_profiles.find) as profiles, \
             patch.object(db.clans, 'find', wraps=db.clans.find) as clans:
            data = json.loads((await api.replacements(request_for(store, ledger,
                [('member', MEMBER), ('weight', '179k')], AsyncMock(return_value={})))).text)
            assert profiles.call_count == clans.call_count == 1
            assert {row['tag']: row['name'] for row in data['member_accounts']} == {
                '#P2Y': 'Known recruit', '#QYY': '#QYY'}
            assert all(row['saved_weight'] is None for row in data['member_accounts'])
            monkeypatch.setenv('CWL_WEB_DB_PATH', store.path)
            profiles.reset_mock(); clans.reset_mock()
            panel = await discord.replacement_panel(ledger, {'_id': 'typed-recruit-panel',
                'guild_id': api.GUILD_ID, 'member_id': int(MEMBER), 'weights': [179000]})
            text = text_of(panel[0].build()[0])
            assert profiles.call_count == clans.call_count == 1
            assert 'No saved weight:\nKnown recruit #P2Y\n#QYY' in text
            assert '#QYY #QYY' not in text
            assert '### 179k' in text
        assert (db.strike_profiles.rows, db.strike_records.rows) == before
    asyncio.run(run())


@pytest.mark.parametrize('count', [2, 40])
def test_missing_weight_lines_fit_whole_or_use_exact_count_link(tmp_path, monkeypatch, count):
    async def run():
        db, ledger, store = await fixture(tmp_path)
        alphabet = '0289PYLQGRJCUV'
        accounts = {f'#P{alphabet[index // len(alphabet)]}{alphabet[index % len(alphabet)]}Y':
                    f'Recruit {index} ' + 'Z' * 100 + ' end' for index in range(count)}
        with store.tx() as sql:
            for player, name in accounts.items():
                sql.execute('INSERT INTO clan_player_weights(tag,weight,revision,player_name,last_clan_tag,last_clan_name,updated_at,actor_id) VALUES(?,NULL,1,?,?,?,?,?)',
                            (player, name, '', '', '2026-11-17T00:00:00Z', '1'))
        links = LinksResult(sources={player: ('ClashKing',) for player in accounts})
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
             patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=links)), \
             patch.object(discord, 'cached_weights', return_value={}), \
             patch.object(discord, 'update_state', AsyncMock()):
            data = json.loads((await api.replacements(request_for(store, ledger,
                [('member', MEMBER), ('weight', '179k')], AsyncMock(return_value={})))).text)
            assert {row['tag']: row['name'] for row in data['member_accounts']} == accounts
            assert len(data['member_accounts']) == count
            monkeypatch.setenv('CWL_WEB_DB_PATH', store.path)
            panel = await discord.replacement_panel(ledger, {'_id': 'bounded-missing-panel',
                'guild_id': api.GUILD_ID, 'member_id': int(MEMBER), 'weights': [179000]})
            payload = panel[0].build()[0]
            text = text_of(payload)
            assert discord.text_units(text) <= discord.PANEL_TEXT_LIMIT
            assert len([row for row in data['slots'][0]['candidates']]) == 3
            assert all('`' + row['player_tag'] + '`' in text for row in data['slots'][0]['candidates'])
            if count == 2:
                assert text.count('No saved weight:') == 1
                assert 'No saved weight:\n' + '\n'.join(
                    f'{accounts[player]} {player}' for player in sorted(accounts)) in text
                assert 'View all on the dashboard' not in text
            else:
                url = payload['components'][-1]['components'][-1]['url']
                expected = f'No saved weight: {count} accounts. [View all on the dashboard]({url}).'
                assert [line for line in text.splitlines() if line.startswith('No saved weight:')] == [expected]
                assert all(name not in text and player not in text for player, name in accounts.items())
    asyncio.run(run())
