"""Prior wins, per-host sit-outs and atomic fixture-only history imports."""
import asyncio
from copy import deepcopy
import io
import json
from pathlib import Path
import sqlite3

import pytest

from cwl_web.store import Store
from cwl_web.participation_sync import settings_view
from utils.cwl_bonus_raffle_store import RaffleStore, RaffleConflict
from utils.cwl_bonus_raffle import lazy_eligibility
from tools.import_prior_lazy_winners import read_rows, check_rows, apply_checked, print_table
from test_cwl_dashboard_state import Collection
from utils.cwl_dashboard_state import MongoDashboardState

FIXTURE = Path(__file__).parent / 'fixtures' / 'prior_lazy_winners_230.tsv'


class Players:
    def __init__(self, rows, missing=None):
        self.rows = {r['player_tag']: 'Official fixture ' + r['player_tag'] for r in rows}
        self.missing = missing
        self.calls = []

    async def player(self, tag):
        self.calls.append(tag)
        if tag == self.missing:
            raise KeyError(tag)
        return {'tag': tag, 'name': self.rows[tag]}


def checked(store, missing=None):
    rows = read_rows(FIXTURE)
    provider = Players(rows, missing)
    with sqlite3.connect(Path(store.path).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None) as db:
        db.row_factory = sqlite3.Row
        result = asyncio.run(check_rows(db, rows, provider))
    assert len(provider.calls) == len({row['player_tag'] for row in rows})
    return result


def counts(store):
    with store.tx() as db:
        return {r[0]: db.execute('SELECT COUNT(*) FROM "' + r[0] + '"').fetchone()[0]
                for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def test_dry_run_apply_idempotency_and_history_months(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label) VALUES ('Current month')")
        db.execute('UPDATE member_season SET season_id=1')
        db.execute("INSERT INTO clans(tag,name) VALUES ('#2CVJ0LVQG','Existing clan name')")
    before = counts(store)
    rows = checked(store)
    output = io.StringIO()
    print_table(rows, output)
    assert 'Official fixture' in output.getvalue() and 'clan new' in output.getvalue()
    assert counts(store) == before
    result = apply_checked(store, rows, 'fixture-actor')
    assert result == {'added': 82, 'skipped': []}
    with store.tx() as db:
        seasons = db.execute("SELECT * FROM seasons WHERE status='archived' ORDER BY label").fetchall()
        assert [row['label'] for row in seasons] == ['2026-08', '2026-09', '2026-10']
        for season in seasons:
            assert season['signup_open'] == 0
            assert settings_view(db, season['id'])['cycle'] == season['label']
            assert not settings_view(db, season['id'])['enabled']
            actual = {r[0] for r in db.execute('SELECT tag FROM lineup WHERE season_id=?', (season['id'],))}
            assert actual == {r['clan_tag'] for r in rows if r['cycle'] == season['label']}
            assert {r[0] for r in db.execute('SELECT pool FROM lineup_rules WHERE season_id=?', (season['id'],))} == {'lazy'}
        assert db.execute('SELECT name FROM clans WHERE tag=?', ('#2CVJ0LVQG',)).fetchone()[0] == 'Existing clan name'
        assert db.execute('SELECT season_id FROM member_season').fetchone()[0] == 1
        assert db.execute('SELECT COUNT(*) FROM bonus_imported_winners WHERE player_tag=?', ('#G0QQGQCGU',)).fetchone()[0] == 2
    after = counts(store)
    assert all(after[t] == before[t] for t in ('signups', 'roster_entries', 'bonus_raffle_draws',
                'bonus_confirmations', 'bonus_reviews', 'roster_publications'))
    again = checked(store)
    assert all(row['status'].startswith('already imported') for row in again)
    assert apply_checked(store, again, 'fixture-actor')['added'] == 0
    assert counts(store) == after


def test_existing_month_reused_and_wrong_binding_rolls_back_everything(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label) VALUES ('2026-09')")
        db.execute("INSERT INTO participation_sync_settings(season_id,cycle,enabled,updated_by,updated_at) VALUES (1,'2026-11',0,'staff','now')")
    before = counts(store)
    with pytest.raises(ValueError, match='different CWL month'):
        apply_checked(store, checked(store), 'staff')
    assert counts(store) == before
    with store.tx() as db:
        db.execute("UPDATE participation_sync_settings SET cycle='2026-09'")
    apply_checked(store, checked(store), 'staff')
    assert store.one("SELECT COUNT(*) n FROM seasons WHERE label='2026-09'")['n'] == 1
    assert store.one("SELECT status FROM seasons WHERE id=1")['status'] == 'draft'


def test_missing_tag_stops_apply_and_skip_lists_exact_rows(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    rows = checked(store, '#G0QQGQCGU')
    before = counts(store)
    with pytest.raises(ValueError, match='Tag not found'):
        apply_checked(store, rows, 'staff')
    assert counts(store) == before
    assert apply_checked(store, rows, 'staff', True) == {
        'added': 80, 'skipped': [('2026-10', '#G0QQGQCGU'), ('2026-08', '#G0QQGQCGU')]}


@pytest.mark.parametrize('months', [0, 1, 2, 3, 6])
def test_sit_out_lengths_wrap_year_and_old_clan_irrelevant(tmp_path, months):
    store = Store(tmp_path / 'fixture.db')
    apply_checked(store, checked(store), 'staff')
    with store.tx() as db:
        owner = RaffleStore(db, 1)
        # Latest Oct win, regardless of old host. Only new host length matters.
        for offset in range(1, 8):
            cycle = owner.shift_cycle('2026-10', offset)
            state = owner.sit_out('#G0QQGQCGU', cycle, months)
            assert state['three_cycle_cooldown'] == (offset <= months)
            assert state['prior_winner_cycle'] == '2026-10'
            assert state['eligible_again'] == owner.shift_cycle('2026-10', months + 1)


def test_voided_confirmation_and_main_win_ignored(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label) VALUES ('fixture')")
        db.execute("INSERT INTO bonus_batches(id,season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) VALUES (1,1,'2026-10',0,'f','{}','s','now')")
        for tag, pool, voided in [('#P2Y', 'lazy', 'now'), ('#Q2Y', 'main', None), ('#G2Y', 'lazy', None)]:
            db.execute("INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,reason,warnings_json,confirmed_by,confirmed_at,voided_at) VALUES (1,1,'2026-10',0,?,'fixture',?,'#OLD','reason','[]','s','now',?)", (tag, pool, voided))
        owner = RaffleStore(db, 1)
        assert not owner.sit_out('#P2Y', '2026-11', 3)['three_cycle_cooldown']
        assert not owner.sit_out('#Q2Y', '2026-11', 3)['three_cycle_cooldown']
        assert owner.sit_out('#G2Y', '2026-11', 3)['three_cycle_cooldown']


def test_restart_checkpoint_and_backup_include_imported_wins_and_lengths(tmp_path):
    from tools.backup.cwl_backup import snapshot
    source = tmp_path / 'source.db'
    store = Store(source)
    collection = Collection()
    owner = MongoDashboardState(collection)
    owner.seed(source)
    owner.restore(source)
    store = Store(source, durability=owner)
    apply_checked(store, checked(store), 'fixture')
    with store.tx() as db:
        sid = db.execute("SELECT id FROM seasons WHERE label='2026-10'").fetchone()[0]
        raffle = RaffleStore(db, sid)
        clan = raffle.sit_out_settings()[0]['tag']
        raffle.save_sit_out(clan, 6, 'fixture')
    owner.close()
    restored = tmp_path / 'replacement.db'
    restarted = MongoDashboardState(collection)
    restarted.restore(restored)
    new = Store(restored, durability=restarted)
    assert new.one('SELECT COUNT(*) n FROM bonus_imported_winners')['n'] == 82
    assert new.one('SELECT SUM(history_only) n FROM seasons')['n'] == 3
    with new.tx() as db:
        assert RaffleStore(db, sid).sit_out_settings()[0]['months'] == 6
    backup_counts = snapshot(restored, tmp_path / 'backup.db')
    assert backup_counts['bonus_imported_winners'] == 82
    restarted.close()


def test_invalid_input_and_upstream_unavailable_are_not_skippable(tmp_path):
    from cwl_web.providers import ProviderUnavailable
    path = tmp_path / 'bad.tsv'
    path.write_text(FIXTURE.read_text().replace('#JL0CP00U', '#BADTAG', 1))
    with pytest.raises(ValueError, match='Invalid Clash tag'):
        read_rows(path)
    class Down:
        async def player(self, tag):
            raise ProviderUnavailable('API unavailable')
    store = Store(tmp_path / 'fixture.db')
    with sqlite3.connect(Path(store.path).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None) as db, pytest.raises(ProviderUnavailable):
        db.row_factory = sqlite3.Row
        asyncio.run(check_rows(db, read_rows(FIXTURE), Down()))
    assert counts(store)['bonus_imported_winners'] == 0


def test_month_reuse_follows_settings_binding_not_display_label(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label,status) VALUES ('September staff history','archived')")
        db.execute("INSERT INTO participation_sync_settings(season_id,cycle,enabled,updated_by,updated_at) VALUES (1,'2026-09',0,'s','now')")
    apply_checked(store, checked(store), 'staff')
    assert store.one('SELECT COUNT(*) n FROM seasons')['n'] == 3
    assert store.one("SELECT COUNT(*) n FROM bonus_imported_winners WHERE season_id=1 AND cycle='2026-09'")['n'] > 0


def test_cli_default_dry_run_is_read_only_and_lists_api_names(tmp_path, capsys):
    from argparse import Namespace
    from tools.import_prior_lazy_winners import run
    path = tmp_path / 'fixture.db'
    store = Store(path)
    players = tmp_path / 'players.json'
    players.write_text(json.dumps({row['player_tag']: 'API fixture name' for row in read_rows(FIXTURE)}))
    before = counts(store)
    args = Namespace(tsv=FIXTURE, database=path, fixture_players=players,
                     apply=False, skip_missing=False, actor='')
    asyncio.run(run(args))
    assert counts(store) == before
    output = capsys.readouterr().out
    assert 'Dry run: no writes.' in output
    assert 'API fixture name' in output
    assert 'pasted name\tAPI name' in output


def test_reapply_preserves_staff_edits_and_all_database_rows(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    rows = checked(store)
    apply_checked(store, rows, 'staff')
    with store.tx() as db:
        host = db.execute('SELECT season_id,tag FROM lineup_rules LIMIT 1').fetchone()
        db.execute("UPDATE lineup_rules SET pool='main',capacity=30,sit_out_months=6 WHERE season_id=? AND tag=?", tuple(host))
        # Removing a hosting clan is a staff edit too; a repeat import must not restore it.
        another = db.execute('SELECT season_id,tag FROM lineup_rules WHERE tag<>? LIMIT 1', (host['tag'],)).fetchone()
        db.execute('DELETE FROM lineup_rules WHERE season_id=? AND tag=?', tuple(another))
        db.execute('DELETE FROM lineup WHERE season_id=? AND tag=?', tuple(another))
        before = '\n'.join(db.iterdump())
    assert apply_checked(store, checked(store), 'different-importer')['added'] == 0
    with store.tx() as db:
        assert '\n'.join(db.iterdump()) == before


def test_reused_month_is_not_marked_history_only(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label,status) VALUES ('2026-09','archived')")
    apply_checked(store, checked(store), 'staff')
    assert store.one('SELECT history_only FROM seasons WHERE id=1')['history_only'] == 0
    assert store.one('SELECT SUM(history_only) n FROM seasons')['n'] == 2


def test_new_import_rows_preserve_existing_month_clan_rules(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label) VALUES ('2026-09')")
        db.execute("INSERT INTO clans(tag,name) VALUES ('#2J9Q00UPJ','Existing official clan')")
        db.execute("INSERT INTO lineup VALUES (1,'#2J9Q00UPJ')")
        db.execute("INSERT INTO lineup_rules(season_id,tag,pool,capacity,sit_out_months) VALUES (1,'#2J9Q00UPJ','lazy',30,6)")
    apply_checked(store, checked(store), 'staff')
    assert store.one("SELECT pool,capacity,sit_out_months FROM lineup_rules WHERE season_id=1 AND tag='#2J9Q00UPJ'") == {
        'pool': 'lazy', 'capacity': 30, 'sit_out_months': 6}
    assert store.one('SELECT history_only FROM seasons WHERE id=1')['history_only'] == 0
    assert store.one("SELECT name FROM clans WHERE tag='#2J9Q00UPJ'")['name'] == 'Existing official clan'



def seed_pool_conflicts(store, pools=('main', 'main', 'main')):
    rows = read_rows(FIXTURE)
    seeded = []
    with store.tx() as db:
        for cycle, pool in zip(('2026-08', '2026-09', '2026-10'), pools):
            row = next(row for row in rows if row['cycle'] == cycle)
            sid = db.execute('INSERT INTO seasons(label) VALUES (?)', (cycle,)).lastrowid
            db.execute('INSERT OR IGNORE INTO clans(tag,name) VALUES (?,?)', (row['clan_tag'], row['clan_name']))
            db.execute('INSERT INTO lineup(season_id,tag) VALUES (?,?)', (sid, row['clan_tag']))
            db.execute('INSERT INTO lineup_rules(season_id,tag,pool,capacity,sit_out_months) VALUES (?,?,?,30,6)', (sid, row['clan_tag'], pool))
            seeded.append((cycle, row['clan_tag'], row['clan_name']))
    return seeded


def sql_image(store):
    with store.tx() as db:
        return '\n'.join(db.iterdump())


def test_all_new_row_pool_conflicts_are_listed_and_apply_changes_nothing(tmp_path, capsys):
    store = Store(tmp_path / 'fixture.db')
    conflicts = seed_pool_conflicts(store)
    before = sql_image(store)
    rows = checked(store)
    output = io.StringIO()
    print_table(rows, output)
    for cycle, tag, name in conflicts:
        assert f'Pool conflict: {cycle}' in output.getvalue()
        assert tag in output.getvalue() and name in output.getvalue()
    assert 'existing pool: main' in output.getvalue()
    from argparse import Namespace
    from tools.import_prior_lazy_winners import run
    players = tmp_path / 'players.json'
    players.write_text(json.dumps({row['player_tag']: 'API fixture name' for row in read_rows(FIXTURE)}))
    asyncio.run(run(Namespace(tsv=FIXTURE, database=store.path, fixture_players=players,
                             apply=False, skip_missing=False, actor='')))
    cli_output = capsys.readouterr().out
    assert cli_output.count('Pool conflict:') == 3
    for cycle, tag, name in conflicts:
        assert cycle in cli_output and tag in cli_output and name in cli_output
    assert 'Dry run: no writes.' in cli_output
    assert sql_image(store) == before
    with pytest.raises(ValueError) as failure:
        apply_checked(store, rows, 'staff')
    for cycle, tag, name in conflicts:
        assert cycle in str(failure.value) and tag in str(failure.value) and name in str(failure.value)
    assert sql_image(store) == before
    with store.tx() as db:
        db.execute("UPDATE lineup_rules SET pool='lazy'")
    assert apply_checked(store, checked(store), 'staff')['added'] == 82
    with store.tx() as db:
        assert all(r['capacity'] == 30 and r['sit_out_months'] == 6 for r in db.execute('SELECT capacity,sit_out_months FROM lineup_rules WHERE capacity=30'))


def test_apply_rechecks_conflict_after_async_preflight_without_holding_transaction(tmp_path):
    store = Store(tmp_path / 'fixture.db')
    seed_pool_conflicts(store, ('lazy', 'lazy', 'lazy'))
    with sqlite3.connect(Path(store.path).resolve().as_uri() + '?mode=ro', uri=True, isolation_level=None) as db:
        db.row_factory = sqlite3.Row
        class OutsideTransaction(Players):
            async def player(self, tag):
                assert not db.in_transaction
                await asyncio.sleep(0)
                return await super().player(tag)
        rows = asyncio.run(check_rows(db, read_rows(FIXTURE), OutsideTransaction(read_rows(FIXTURE))))
    with store.tx() as db:
        db.execute("UPDATE lineup_rules SET pool='main'")
    before = sql_image(store)
    with pytest.raises(ValueError, match='Pool conflict'):
        apply_checked(store, rows, 'staff')
    assert sql_image(store) == before



def test_duplicate_month_tag_is_rejected_before_import(tmp_path):
    path = tmp_path / 'duplicate.tsv'
    lines = FIXTURE.read_text().splitlines()
    path.write_text('\n'.join(lines + [lines[1]]) + '\n')
    with pytest.raises(ValueError, match='Duplicate month and tag'):
        read_rows(path)
