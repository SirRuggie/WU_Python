import asyncio
from unittest.mock import AsyncMock

import pytest

from cwl_web.app import _roster_rows
from cwl_web.store import Store
from cwl_web.providers import ProviderUnavailable
from cwl_web.clan_weights import capture_lineups
from utils.clan_weight_store import ClanWeightStore
from utils.clan_weights import source_weights, overlay_accounts


@pytest.fixture
def ledger(tmp_path):
    store = Store(tmp_path / 'weights.sqlite')
    weights = ClanWeightStore(store.path, transaction_factory=store.tx)
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES(1,'November')")
        db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,'#P2Y','1','lazy',0,'Player',17)")
        db.execute("INSERT INTO roster_entries(season_id,tag,source_weight,source_status) VALUES(1,'#P2Y',100000,'current')")
    return store, weights


def save(weights, weight, revision=0):
    return weights.save({'tag': '#R2Y', 'name': 'Family', 'members': [
        {'tag': '#P2Y', 'name': 'Player', 'town_hall': 17}]},
        [{'tag': '#P2Y', 'weight': weight, 'revision': revision, 'storages': 5}], '1', 'Staff')


def lineup(end='20261102T070000.000Z', state='preparation'):
    return {'order': {'#P2Y': 2, '#Q2Y': 1}, 'end_time': end, 'state': state, 'opponent': 'Opponent'}


def test_saved_weights_immediately_drive_roster_and_invalidate_previews(ledger):
    store, weights = ledger
    save(weights, 149000)
    with store.tx() as db:
        row = _roster_rows(db, 1)[0]
    assert row['effective_weight'] == 149000
    assert row['source_name'] == 'Clan weights'
    revision = store.one('SELECT revision FROM roster_meta')['revision']
    save(weights, 150000, 1)
    assert store.one('SELECT revision FROM roster_meta')['revision'] == revision + 1
    save(weights, 150000, 1)  # Lost-response replay does not bump a second time.
    assert store.one('SELECT revision FROM roster_meta')['revision'] == revision + 1
    with store.tx() as db:
        db.execute('UPDATE roster_entries SET manual_weight=160000')
        assert _roster_rows(db, 1)[0]['effective_weight'] == 150000
    assert len(weights.all()) == 1


def test_official_weight_needs_no_external_service_and_blank_does_not_revive_it(ledger):
    store, weights = ledger
    save(weights, 149000)
    provider = type('Provider', (), {})()
    provider.weights = AsyncMock(side_effect=ProviderUnavailable('offline'))
    result = asyncio.run(source_weights(store, provider, ['#P2Y']))
    assert result['#P2Y']['weight'] == 149000
    provider.weights.assert_not_awaited()
    save(weights, None, 1)
    assert asyncio.run(source_weights(store, provider, ['#P2Y'])) == {}
    with store.tx() as db:
        assert _roster_rows(db, 1)[0]['effective_weight'] is None
    provider.weights.assert_not_awaited()


def test_fallback_only_fetches_unsaved_accounts_and_cached_member_view_updates(ledger):
    store, weights = ledger
    save(weights, 149000)
    provider = type('Provider', (), {})()
    provider.weights = AsyncMock(return_value={'#Q2Y': {'weight': 140000, 'source_name': 'FWA Stats'}})
    result = asyncio.run(source_weights(store, provider, ['#P2Y', '#Q2Y']))
    provider.weights.assert_awaited_once_with(['#Q2Y'])
    assert result['#Q2Y']['weight'] == 140000
    cached = {'accounts': [{'tag': '#P2Y', 'war_weight': 100000}]}
    assert overlay_accounts(store, cached)['accounts'][0]['war_weight'] == 149000
    save(weights, None, 1)
    assert overlay_accounts(store, cached)['accounts'][0]['war_weight'] is None
    assert cached['accounts'][0]['war_weight'] == 100000


def test_lineup_survives_restart_and_older_response_cannot_replace_it(ledger):
    store, weights = ledger
    weights.remember_lineup('#R2Y', lineup())
    weights.remember_lineup('#R2Y', lineup(state='warEnded'))
    weights.remember_lineup('#R2Y', lineup(state='inWar'))
    weights.remember_lineup('#R2Y', lineup(end='20261002T070000.000Z'))
    restarted = ClanWeightStore(store.path)
    saved = restarted.saved_lineup('#R2Y')
    assert saved['state'] == 'warEnded'
    assert saved['cached'] is True
    assert saved['order'] == {'#P2Y': 2, '#Q2Y': 1}
    assert restarted.saved_lineup('#OTHER') is None
    with pytest.raises(ValueError):
        weights.remember_lineup('#R2Y', {**lineup(), 'order': {'#P2Y': 2}})
    assert weights.saved_lineup('#R2Y') == saved


def test_background_capture_fwa_only_and_failures_retain_history(ledger):
    _, weights = ledger
    provider = type('Provider', (), {})()
    provider.family_clans = AsyncMock(return_value={'clans': [
        {'tag': '#R2Y', 'type': 'FWA'}, {'tag': '#J2Y', 'type': 'Tactical'}]})
    provider.weight_war_lineup = AsyncMock(return_value=lineup())
    app = {'providers': provider, 'clan_weight_trial': weights}
    asyncio.run(capture_lineups(app))
    provider.weight_war_lineup.assert_awaited_once_with('#R2Y')
    provider.weight_war_lineup.side_effect = ProviderUnavailable('private or no current war')
    asyncio.run(capture_lineups(app))
    assert weights.saved_lineup('#R2Y')['order'] == lineup()['order']


def test_manual_cannot_override_saved_or_explicitly_blank_clan_weight(ledger):
    store, weights = ledger
    with store.tx() as db:
        db.execute("INSERT INTO player_weights VALUES('#P2Y',170000,170000,'now')")
        db.execute('UPDATE roster_entries SET manual_weight=170000')
    save(weights, 149000)
    cached = {'accounts': [{'tag': '#P2Y', 'war_weight': 100000}]}
    assert overlay_accounts(store, cached)['accounts'][0]['war_weight'] == 149000
    save(weights, None, 1)
    assert overlay_accounts(store, cached)['accounts'][0]['war_weight'] is None
    with store.tx() as db:
        assert _roster_rows(db, 1)[0]['effective_weight'] is None


def test_legacy_ledger_migrates_in_place_without_losing_data(ledger):
    store, weights = ledger
    save(weights, 149000)
    with store.tx() as db:
        original = [tuple(r) for r in db.execute('SELECT * FROM clan_player_weights')]
        history = [tuple(r) for r in db.execute('SELECT * FROM clan_player_weight_history')]
        db.execute('ALTER TABLE clan_player_weights RENAME TO clan_weight_trial')
        db.execute('ALTER TABLE clan_player_weight_history RENAME TO clan_weight_trial_history')
    restarted = Store(store.path)
    with restarted.tx() as db:
        assert [tuple(r) for r in db.execute('SELECT * FROM clan_player_weights')] == original
        assert [tuple(r) for r in db.execute('SELECT * FROM clan_player_weight_history')] == history
        assert not db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('clan_weight_trial','clan_weight_trial_history')").fetchall()
        assert _roster_rows(db, 1)[0]['effective_weight'] == 149000
    Store(store.path)  # Repeated startup is safe.


def test_saved_player_change_invalidates_season_and_preserves_provenance(ledger):
    store, weights = ledger
    save(weights, 149000)
    before = store.rows('SELECT revision FROM roster_meta WHERE season_id=1')[0]['revision']
    changed = weights.save_existing('#P2Y', {'weight': 150000, 'revision': 1}, '2', 'Editor')
    assert changed['last_clan_tag'] == '#R2Y'
    assert changed['player_name'] == 'Player'
    assert store.rows('SELECT revision FROM roster_meta WHERE season_id=1')[0]['revision'] == before + 1
    history = store.rows('SELECT * FROM clan_player_weight_history ORDER BY id DESC')[0]
    assert history['actor_id'] == '2' and history['actor_name'] == 'Editor'
    assert history['clan_tag'] == '#R2Y'
    weights.save_existing('#P2Y', {'weight': 150000, 'revision': 1}, '2')
    assert store.rows('SELECT revision FROM roster_meta WHERE season_id=1')[0]['revision'] == before + 1
    with store.tx() as db:
        db.execute("CREATE TRIGGER fail_revision BEFORE UPDATE ON roster_meta BEGIN SELECT RAISE(ABORT, 'fixture'); END")
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        weights.save_existing('#P2Y', {'weight': 151000, 'revision': 2}, '2')
    assert weights.all()[0]['weight'] == 150000
    assert len(store.rows('SELECT * FROM clan_player_weight_history')) == 2


def test_saved_player_never_creates_unknown_row(ledger):
    _, weights = ledger
    from utils.clan_weight_store import WeightConflict
    with pytest.raises(WeightConflict):
        weights.save_existing('#Q2Y', {'weight': 150000, 'revision': 0}, '1')
    assert weights.all() == []


def test_optional_lineup_names_and_saved_source_link_metadata(ledger):
    store, weights = ledger
    item = {**lineup(), 'names': {'#P2Y': 'Named player'}}
    weights.remember_lineup('#R2Y', item)
    assert weights.saved_lineup('#R2Y')['names'] == item['names']
    save(weights, 149000)
    with store.tx() as db:
        rows = _roster_rows(db, 1)
    assert rows[0]['clan_weight_clan_tag'] == '#R2Y'
    assert rows[0]['clan_weight_clan_name'] == 'Family'
    assert rows[0]['clan_weight_saved_at']


def test_concurrent_saved_player_edits_have_one_winner(ledger):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from utils.clan_weight_store import WeightConflict
    _, weights = ledger
    save(weights, 149000)
    barrier = Barrier(2)
    def update(value):
        barrier.wait()
        try:
            weights.save_existing('#P2Y', {'weight': value, 'revision': 1}, '1')
            return 'saved'
        except WeightConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(update, [150000, 151000]))
    assert sorted(results) == ['conflict', 'saved']
    assert weights.all()[0]['revision'] == 2


def test_saved_search_is_unicode_case_insensitive_and_literal(ledger):
    _, weights = ledger
    save(weights, 149000)
    with weights.connect() as db:
        db.execute("UPDATE clan_player_weights SET player_name='Änne Straße%_'")
    for query in ('Änne', 'änne', 'STRASSE', 'straße', '%_'):
        assert weights.search(query)['total'] == 1
    assert weights.search('strasse_')['total'] == 0


def test_weight_login_target_keeps_only_validated_player_and_clan():
    from cwl_web.app import login_destination
    from urllib.parse import parse_qs, urlsplit
    target = login_destination({'view': 'weight-trial', 'player': '#P2Y', 'clan': '#R2Y'})
    assert parse_qs(urlsplit(target).query) == {'player': ['#P2Y'], 'clan': ['#R2Y']}
    assert login_destination({'view': 'weight-trial', 'player': '//evil.example', 'clan': 'bad\n'}) == '/clan-weights'


def test_saved_weight_login_cookie_retains_validated_target():
    from types import SimpleNamespace
    from cwl_web.app import saved_login_destination, RETURN_COOKIE
    assert saved_login_destination(SimpleNamespace(cookies={RETURN_COOKIE: '/clan-weights?player=%23P2Y&clan=%23R2Y'})) == '/clan-weights?player=%23P2Y&clan=%23R2Y'
    assert saved_login_destination(SimpleNamespace(cookies={RETURN_COOKIE: '/clan-weights?player=https://evil.example&clan=%23R2Y'})) == '/clan-weights?clan=%23R2Y'
