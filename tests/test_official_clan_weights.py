import asyncio
from unittest.mock import AsyncMock

import pytest

from cwl_web.app import _roster_rows
from cwl_web.store import Store
from cwl_web.providers import ProviderUnavailable
from cwl_web.clan_weights import capture_lineups
from utils.clan_weight_trial_store import ClanWeightTrialStore
from utils.clan_weights import source_weights, overlay_accounts


@pytest.fixture
def ledger(tmp_path):
    store = Store(tmp_path / 'weights.sqlite')
    weights = ClanWeightTrialStore(store.path, transaction_factory=store.tx)
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
        assert _roster_rows(db, 1)[0]['effective_weight'] == 160000
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
    restarted = ClanWeightTrialStore(store.path)
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
