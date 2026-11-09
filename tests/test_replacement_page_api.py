"""Paged replacement reads over isolated stored profiles, never live API data."""
import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cwl_web import strikes as api
from cwl_web.store import Store
from test_strike_ux_backend import setup, record


def test_default_page_is_bounded_and_uses_provider_weights_without_profile_weight(tmp_path):
    async def scenario():
        db, ledger = setup()
        await db.clans.insert_one({'_id': 'clan', 'tag': '#Q2Y', 'name': 'Family', 'type': 'FWA'})
        now = datetime.now(timezone.utc)
        for i in range(273):
            tag = f'#P{i}'
            await db.strike_profiles.insert_one({'_id': f'{api.GUILD_ID}:{tag}',
                'guild_id': api.GUILD_ID, 'player_tag': tag, 'player_name': f'Player {i:03}',
                'current_clan_tag': '#Q2Y', 'roster_seen_at': now,
                'town_hall': 16, 'revision': 2})
            for j in range(i % 5):
                await db.strike_records.insert_one(record(f'{i}-{j}', tag, guild_id=api.GUILD_ID,
                    expires_at=now + timedelta(days=30)))
        store = Store(str(tmp_path / 'fixture.sqlite'))
        provider = SimpleNamespace(weights=AsyncMock(return_value={f'#P{i}': {'weight': 100000+i} for i in range(273)}))
        request = SimpleNamespace(method='GET', query={}, app={'store': store, 'providers': provider,
                                                               'strike_service': ledger})
        @asynccontextmanager
        async def mongo(_):
            yield db
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo):
            first = json.loads((await api.replacements(request)).text)
            assert first['total'] == 108
            assert len(first['candidates']) == 25 and len(first['top']) == 10
            assert all(row['active_strikes'] >= 3 for row in first['candidates'])
            assert all(row['revision'] == 2 for row in first['candidates'])
            request.query = {'offset': '25'}
            second = json.loads((await api.replacements(request)).text)
            assert not {r['player_tag'] for r in first['candidates']} & {r['player_tag'] for r in second['candidates']}
            request.query = {'include_low': 'true'}
            low = json.loads((await api.replacements(request)).text)
            assert low['total'] == 218
            provider.weights.assert_awaited()
            assert first['candidates'][0]['weight'] is not None
            assert first['town_halls'] == [16]
            for player in ['#P2Y', '#P2YY']:
                await db.strike_profiles.insert_one({'_id':f'{api.GUILD_ID}:{player}', 'guild_id':api.GUILD_ID, 'player_tag':player, 'current_clan_tag':'#Q2Y', 'roster_seen_at':now})
                for j in range(3):
                    await db.strike_records.insert_one(record(f'{player}-{j}', player, guild_id=api.GUILD_ID, expires_at=now+timedelta(days=30)))
            request.query = {'exact_tag':'#P2Y','limit':'1'}
            exact = json.loads((await api.replacements(request)).text)
            assert [row['player_tag'] for row in exact['candidates']] == ['#P2Y']
    asyncio.run(scenario())


def test_route_passes_revision_to_add_update_and_clear():
    async def scenario():
        ledger = SimpleNamespace(
            set_replacement_preference=AsyncMock(return_value={'player_tag':'#P2Y', 'replacement_priority':'high', 'replacement_clan_tag':'#Q2Y', 'revision':9}),
            clear_replacement_preference=AsyncMock(return_value={'revision':9}))
        @asynccontextmanager
        async def mongo(_):
            yield object()
        from cwl_web import app
        for handler, method in [(api.add_replacement_list,'POST'), (api.update_replacement_list,'PUT'), (api.delete_replacement_list,'DELETE')]:
            request = SimpleNamespace(method=method, match_info={'player_tag':'#P2Y'})
            with patch.object(api.shared,'require_manage',AsyncMock()), patch.object(api.shared,'mongo',mongo), patch.object(api,'service',AsyncMock(return_value=ledger)), patch.object(api,'body',AsyncMock(return_value={'player_tag':'#P2Y','priority':'high','note':'keep','revision':8})), patch.object(api,'_verified_replacement_player',AsyncMock(return_value={'tag':'#P2Y','current_clan_tag':'#Q2Y'})), patch.object(app,'_session',return_value={'user_id':'123'}):
                response = await handler(request)
                assert response.status == 200
                call = ledger.clear_replacement_preference if method == 'DELETE' else ledger.set_replacement_preference
                assert call.await_args.kwargs['expected_revision'] == 8
    asyncio.run(scenario())


def _slot_scenario(tmp_path, query, *, extra=None, provider_weights=None, raw_profiles=(), saved=None,
                   links=None, member_ids=True):
    """Run the endpoint over an isolated fixture: two FWA clans, one family clan."""
    from multidict import MultiDict
    async def scenario():
        db, ledger = setup()
        for clan_tag, name, kind in (('#Q2Y', 'Alpha', 'FWA'), ('#J2Y', 'Bravo', 'FWA'), ('#L2L', 'Lazy', 'normal')):
            await db.clans.insert_one({'_id': clan_tag, 'tag': clan_tag, 'name': name, 'type': kind})
        now = datetime.now(timezone.utc)
        fixtures = [  # tag, clan, strikes, weight, marked, member, discord_name
            ('#P0', '#Q2Y', 3, 143000, False, '111111111111111111', 'slayer'),
            ('#P1', '#Q2Y', 3, 144000, False, None, None),
            ('#P2', '#J2Y', 4, 143000, False, '111111111111111111', 'slayer'),
            ('#P3', '#J2Y', 0, 145000, True, None, None),
            ('#P8', '#Q2Y', 2, 143000, False, None, None),
            ('#P9', '#L2L', 5, 143000, False, None, None),
            ('#PC', '#Q2Y', 1, 173000, False, '111111111111111111', 'slayer'),
        ] + (extra or [])
        for player, clan_tag, count, weight, marked, member, name in fixtures:
            if not member_ids:
                member = None
            profile = {'_id': f'{api.GUILD_ID}:{player}', 'guild_id': api.GUILD_ID, 'player_tag': player,
                       'player_name': player, 'current_clan_tag': clan_tag, 'roster_seen_at': now,
                       'town_hall': 15, 'revision': 1, 'member_id': member, 'discord_name': name}
            if marked:
                profile.update(replacement_listed=True, replacement_clan_tag=clan_tag,
                               replacement_priority='high')
            await db.strike_profiles.insert_one(profile)
            for j in range(count):
                await db.strike_records.insert_one(record(f'{player}-{j}', player, guild_id=api.GUILD_ID,
                                                          expires_at=now + timedelta(days=30)))
        for profile in raw_profiles:
            await db.strike_profiles.insert_one({
                '_id': f'{api.GUILD_ID}:{profile["player_tag"]}', 'guild_id': api.GUILD_ID,
                'player_name': profile['player_tag'], 'roster_seen_at': now, 'town_hall': 15,
                'revision': 1, **profile})
        store = Store(str(tmp_path / 'fixture.sqlite'))
        if saved:
            from utils.clan_weight_store import ClanWeightStore
            for player, saved_weight in saved.items():
                ClanWeightStore(store.path).save_discord(
                    player, {'weight': saved_weight, 'revision': 0, 'storages': 5},
                    {'name': player, 'town_hall': 15}, '1', 'Seed')
        weights = provider_weights or {p[0]: {'weight': p[3]} for p in fixtures}
        provider = SimpleNamespace(weights=AsyncMock(return_value=weights))
        request = SimpleNamespace(method='GET', query=MultiDict(query),
                                  app={'store': store, 'providers': provider, 'strike_service': ledger})
        @asynccontextmanager
        async def mongo(_):
            yield db
        from utils.recruit_links import LinksResult
        member_links = links or LinksResult(sources={tag_: ('ClashKing',) for tag_ in ('#P0', '#P2', '#PC')})
        with patch.object(api.shared, 'require_manage', AsyncMock()), patch.object(api.shared, 'mongo', mongo), \
                patch.object(api.recruit_links, 'resolve', AsyncMock(return_value=member_links)):
            try:
                return json.loads((await api.replacements(request)).text)
            except Exception as exc:
                return exc
    return asyncio.run(scenario())


def _slot_tags(group):
    return [row['player_tag'] for row in group['candidates']]


def test_endpoint_multi_weight_returns_one_group_per_weight_in_input_order(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '173000'), ('weight', '143k'), ('weight', '173k')])
    assert [g['weight'] for g in result['slots']] == [173000, 143000, 173000]
    assert [g['weight_label'] for g in result['slots']] == ['173k', '143k', '173k']
    # marked or 3+ strikes, FWA only: #PC (1 strike), #P8 (2 strikes) and non-FWA #P9 are not slots
    assert _slot_tags(result['slots'][1]) == ['#P2', '#P0', '#P1']   # 0 gap: more strikes first
    assert all('#P9' not in _slot_tags(g) and '#P8' not in _slot_tags(g) and '#PC' not in _slot_tags(g)
               for g in result['slots'])
    assert [row['weight_difference'] for row in result['slots'][1]['candidates']] == [0, 0, 1000]
    assert result['candidates'] == result['slots'][0]['candidates']   # back-compat: first group
    assert result['matching_weight'] == 173000


def test_endpoint_old_single_weight_still_works(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '143000')])
    assert len(result['slots']) == 1 and result['candidates'] == result['slots'][0]['candidates']
    assert _slot_tags(result['slots'][0])[0] == '#P2' and len(result['candidates']) <= 3


def test_endpoint_clan_filter_repeated_and_non_fwa_rejected(tmp_path):
    only = _slot_scenario(tmp_path, [('weight', '143000'), ('clan', '#J2Y')])
    assert set(_slot_tags(only['slots'][0])) == {'#P2', '#P3'}
    both = _slot_scenario(tmp_path, [('weight', '143000'), ('clan', '#J2Y'), ('clan', '#Q2Y')])
    assert set(_slot_tags(both['slots'][0])) == {'#P0', '#P1', '#P2'}
    for clan_tag in ('#L2L', '#2PP'):
        bad = _slot_scenario(tmp_path, [('weight', '143000'), ('clan', clan_tag)])
        assert getattr(bad, 'status', None) == 400 and bad.text == 'Select FWA clans only.'


def test_endpoint_rejects_more_than_five_and_invalid_weights_naming_the_value(tmp_path):
    many = _slot_scenario(tmp_path, [('weight', '143')] * 6)
    assert many.status == 400 and many.text == 'Enter up to 5 weights.'
    bad = _slot_scenario(tmp_path, [('weight', '143'), ('weight', 'abc')])
    assert bad.status == 400 and '"abc"' in bad.text


def test_endpoint_member_returns_all_their_fwa_accounts_with_discord_name(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '173000'), ('member', '111111111111111111')])
    group = result['slots'][0]
    assert set(_slot_tags(group)) == {'#P0', '#P2', '#PC'}     # includes the 1-strike account
    assert _slot_tags(group)[0] == '#PC'
    assert all(row['discord_name'] == 'slayer' and row['discord_id'] == '111111111111111111'
               for row in group['candidates'])
    plain = _slot_scenario(tmp_path, [('weight', '143000')])
    unknown = next(row for row in plain['slots'][0]['candidates'] if row['player_tag'] == '#P1')
    assert unknown['discord_name'] is None and unknown['discord_id'] is None


def test_endpoint_member_uses_links_when_cached_member_id_is_missing(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '173000'), ('member', '111111111111111111')],
                            member_ids=False)
    assert set(_slot_tags(result['slots'][0])) == {'#P0', '#P2', '#PC'}


def test_endpoint_member_ignores_stale_cached_member_id(tmp_path):
    from utils.recruit_links import LinksResult
    links = LinksResult(sources={'#P1': ('ClashKing',), '#P2': ('ClashKing',)})
    result = _slot_scenario(tmp_path, [('weight', '173000'), ('member', '111111111111111111')], links=links)
    # #P0 and #PC cache this member id but are not linked; #P1 caches none but is linked.
    assert set(_slot_tags(result['slots'][0])) == {'#P1', '#P2'}


def test_endpoint_member_links_unavailable_or_conflicting_return_503(tmp_path):
    from utils.recruit_links import LinksResult
    for links in (LinksResult(unavailable=('ClashPerk',)), LinksResult(conflicts=('#P0',))):
        result = _slot_scenario(tmp_path, [('weight', '173000'), ('member', '111111111111111111')], links=links)
        assert result.status == 503


def test_endpoint_member_without_links_returns_empty_groups(tmp_path):
    from utils.recruit_links import LinksResult
    result = _slot_scenario(tmp_path, [('weight', '173000'), ('member', '111111111111111111')],
                            links=LinksResult())
    assert result['slots'][0]['candidates'] == []


def test_endpoint_bad_member_is_rejected_and_browse_mode_is_unchanged(tmp_path):
    assert _slot_scenario(tmp_path, [('weight', '143000'), ('member', 'abc')]).status == 400
    browse = _slot_scenario(tmp_path, [])
    assert browse['slots'] == [] and browse['matching_weight'] is None
    assert {row['player_tag'] for row in browse['candidates']} == {'#P0', '#P2', '#P3', '#P9', '#P1'}
    assert all('discord_name' in row for row in browse['candidates'])


def _departed(tag_, *, hours=2, weight=None):
    now = datetime.now(timezone.utc)
    profile = {'player_tag': tag_, 'current_clan_tag': None, 'departed_clan_tag': '#Q2Y',
               'departed_last_seen_at': now - timedelta(hours=hours),
               'replacement_listed': True, 'replacement_clan_tag': '#Q2Y',
               'replacement_priority': 'high'}
    if weight is not None:
        profile['weight'] = weight
    return profile


def _departed_row(result, tag_):
    return next((row for row in result['slots'][0]['candidates'] if row['player_tag'] == tag_), None)


def test_departed_grace_slot_uses_official_saved_weight_over_cached_profile(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '143000'), ('clan', '#Q2Y')],
                            raw_profiles=[_departed('#PD', weight=120000)], saved={'#PD': 143000})
    row = _departed_row(result, '#PD')
    assert row is not None and row['departed'] is True
    assert (row['weight'], row['weight_difference']) == (143000, 0)


def test_departed_grace_slot_without_cached_weight_still_appears_from_saved_weight(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '143000'), ('clan', '#Q2Y')],
                            raw_profiles=[_departed('#PD')], saved={'#PD': 143000})
    row = _departed_row(result, '#PD')
    assert row is not None and (row['weight'], row['weight_difference']) == (143000, 0)


def test_departed_outside_grace_is_not_a_slot(tmp_path):
    result = _slot_scenario(tmp_path, [('weight', '143000'), ('clan', '#Q2Y')],
                            raw_profiles=[_departed('#PD', hours=60, weight=143000)], saved={'#PD': 143000})
    assert _departed_row(result, '#PD') is None


def test_weight_mode_town_hall_filters_slots_and_candidates(tmp_path):
    th16 = {'player_tag': '#PT', 'town_hall': 16, 'current_clan_tag': '#Q2Y', 'replacement_listed': True,
            'replacement_clan_tag': '#Q2Y', 'replacement_priority': 'high'}
    weights = {'#PT': {'weight': 143000}, '#P0': {'weight': 143000}, '#P1': {'weight': 144000},
               '#P2': {'weight': 143000}, '#P3': {'weight': 145000}}
    plain = _slot_scenario(tmp_path, [('weight', '143000')], raw_profiles=[th16], provider_weights=weights)
    assert {row['town_hall'] for row in plain['candidates']} == {15, 16}
    result = _slot_scenario(tmp_path, [('weight', '143000'), ('town_hall', '16')],
                            raw_profiles=[th16], provider_weights=weights)
    assert _slot_tags(result['slots'][0]) == ['#PT']
    assert [row['player_tag'] for row in result['candidates']] == ['#PT']
