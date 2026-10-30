"""Linked weights retain both ledgers and select by the actual saved instant."""
import pytest

from cwl_web.store import Store
from cwl_web.player_weights import record
from utils.clan_weight_store import ClanWeightStore, effective_weights
from utils.clan_weights import saved_sources


@pytest.fixture
def linked(tmp_path):
    store = Store(tmp_path / 'linked.sqlite')
    ledger = ClanWeightStore(store.path, transaction_factory=store.tx)
    ledger.save({'tag': '#R2Y', 'name': 'Family', 'members': [
        {'tag': '#P2Y', 'name': 'Player', 'town_hall': 17}]},
        [{'tag': '#P2Y', 'weight': 150000, 'revision': 0, 'storages': 5}], 'staff')
    return store, ledger


@pytest.mark.parametrize('manual_time,clan_time,expected', [
    ('2026-10-30T15:00:00+00:00', '2026-10-30T14:00:00+00:00', 160000),
    ('2026-10-30T13:00:00+00:00', '2026-10-30T14:00:00+00:00', 150000),
    ('2026-10-30T10:00:00-04:00', '2026-10-30T14:00:00+00:00', 150000),
    ('2026-10-30T10:30:00-04:00', '2026-10-30T14:00:00+00:00', 160000),
])
def test_newest_wins_without_deleting_either_ledger(linked, manual_time, clan_time, expected):
    store, ledger = linked
    with store.tx() as db:
        record(db, '#P2Y', 160000, 1, 'staff', recorded_at=manual_time)
        db.execute('UPDATE clan_player_weights SET updated_at=?', (clan_time,))
        before = [db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in
                  ('player_weights', 'player_weight_events', 'clan_player_weights', 'clan_player_weight_history')]
        assert effective_weights(db, ['#P2Y'])['#P2Y']['weight'] == expected
        assert saved_sources(db, ['#P2Y'])['#P2Y']['weight'] == expected
        after = [db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0] for table in
                 ('player_weights', 'player_weight_events', 'clan_player_weights', 'clan_player_weight_history')]
        assert before == after == [1, 1, 1, 1]
    assert ledger.for_members(['#P2Y'])['#P2Y']['weight'] == expected
    assert ledger.for_members(['#P2Y'])['#P2Y']['revision'] == 1


def test_newer_manual_blank_is_authoritative(linked):
    store, ledger = linked
    with store.tx() as db:
        record(db, '#P2Y', None, 1, 'staff', recorded_at='2099-01-01T00:00:00Z')
        assert saved_sources(db, ['#P2Y'])['#P2Y']['weight'] is None
    assert ledger.for_members(['#P2Y'])['#P2Y']['weight'] is None


def test_naive_legacy_time_is_not_guessed(linked):
    store, _ = linked
    with store.tx() as db:
        record(db, '#P2Y', 160000, 1, 'staff', recorded_at='2026-10-30T14:00:00')
        with pytest.raises(ValueError, match='timezone'):
            effective_weights(db, ['#P2Y'])


def test_roster_write_and_clan_write_share_revision_and_keep_legacy(linked):
    from utils.clan_weight_store import WeightConflict
    store, ledger = linked
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES(1,'November')")
        db.execute("INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,'#P2Y','1','main',0,'Player',17)")
        record(db, '#P2Y', 120000, 1, 'old', recorded_at='2020-01-01T00:00:00Z')
        assert ClanWeightStore.save_roster(db, 1, '#P2Y',
            {'weight': 170000, 'revision': 1, 'storages': 5}, 'roster-staff')
    assert ledger.for_members(['#P2Y'])['#P2Y']['weight'] == 170000
    assert store.one('SELECT revision FROM roster_meta')['revision'] == 1
    assert store.one('SELECT weight FROM player_weights')['weight'] == 120000
    with store.tx() as db:
        with pytest.raises(WeightConflict, match='Changed by someone else'):
            ClanWeightStore.save_roster(db, 1, '#P2Y', {'weight': 180000, 'revision': 1}, 'stale')
    with pytest.raises(WeightConflict, match='Changed by someone else'):
        ledger.save_existing('#P2Y', {'weight': 180000, 'revision': 1}, 'stale')
    ledger.save_existing('#P2Y', {'weight': None, 'revision': 2}, 'clan-staff')
    with store.tx() as db:
        assert saved_sources(db, ['#P2Y'])['#P2Y']['weight'] is None
        ClanWeightStore.save_roster(db, 1, '#P2Y', {'weight': 179000, 'revision': 3}, 'roster-staff')
    with store.tx() as db:
        ClanWeightStore.save_roster(db, 1, '#P2Y', {'weight': None, 'revision': 4}, 'roster-staff')
    assert ledger.for_members(['#P2Y'])['#P2Y']['weight'] is None
    assert store.one('SELECT revision FROM roster_meta')['revision'] == 4
    history = store.rows('SELECT actor_id,source FROM clan_player_weight_history ORDER BY id')
    assert [(row['actor_id'], row['source']) for row in history] == [
        ('staff', 'Clan weights'), ('roster-staff', 'Roster'), ('clan-staff', 'Clan weights'),
        ('roster-staff', 'Roster'), ('roster-staff', 'Roster')]
    assert len(store.rows('SELECT * FROM player_weight_events')) == 1
