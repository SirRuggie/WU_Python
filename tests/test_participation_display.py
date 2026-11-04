"""Display evidence leaves persisted capture and bonus policy inputs intact."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import sqlite3

from cwl_web.participation_display import (
    participation_evidence, decorate_participation_accounts,
)

NOW = datetime(2026, 11, 4, 11, tzinfo=timezone.utc)
STAMP = NOW.isoformat()
OLD = '2026-11-03T11:00:00+00:00'


def fixture():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE participation_sync_settings(season_id,cycle,last_checked_at);
    CREATE TABLE participation_group_observations(season_id,cycle,clan_tag,state,war_tags_json,observed_at);
    CREATE TABLE participation_war_observations(season_id,cycle,war_tag,clan_tag,state,ended,observed_at);
    CREATE TABLE participation_war_fetches(season_id,cycle,war_tag,ended,scanned_clans_json,observed_at);
    CREATE TABLE bonus_allowance_wars(season_id,cycle,war_tag);
    ''')
    db.execute('INSERT INTO participation_sync_settings VALUES(1,?,?)', ('2026-11', STAMP))
    for clan in ('#A', '#B'):
        db.execute('INSERT INTO participation_group_observations VALUES(1,?,?,?,?,?)',
                   ('2026-11', clan, 'WAR', json.dumps([['#END'], ['#LIVE'], ['#PREP']]), STAMP))
        for tag, state, ended in (('#END', 'ENDED', 1), ('#LIVE', 'WAR', 0), ('#PREP', 'PREPARATION', 0)):
            db.execute('INSERT INTO participation_war_observations VALUES(1,?,?,?,?,?,?)',
                       ('2026-11', tag, clan, state, ended, OLD if ended else STAMP))
    for tag, ended in (('#END', 1), ('#LIVE', 0), ('#PREP', 0)):
        db.execute('INSERT INTO participation_war_fetches VALUES(1,?,?,?,?,?)',
                   ('2026-11', tag, ended, json.dumps(['#A', '#B']), OLD if ended else STAMP))
    db.execute('INSERT INTO bonus_allowance_wars VALUES(1,?,?)', ('2026-11', '#END'))
    return db


def accounts():
    return [{'tag': '#P', 'assigned_clan_tag': '#A', 'source_status': 'stale',
             'source_complete': False, 'source_attacks': 1, 'source_stars': 3,
             'attacks': 1, 'stars': 3, 'revision': 2}]


def test_sealed_final_war_is_healthy_display_without_changing_raw_inputs_or_database():
    db = fixture()
    before = list(db.iterdump())
    rows = accounts()
    original = deepcopy(rows)
    writes = db.total_changes
    evidence = participation_evidence(db, 1, '2026-11', now=NOW)
    output = decorate_participation_accounts(rows, evidence)
    assert output[0]['display_status'] == {
        'code': 'in_progress', 'label': 'CWL in progress', 'warning': None,
        'failed_clan': False, 'round': 2,
    }
    assert rows == original
    assert {k: v for k, v in output[0].items() if k != 'display_status'} == original[0]
    assert db.total_changes == writes
    assert list(db.iterdump()) == before


def test_active_failure_is_attributed_without_treating_old_check_as_new_failure():
    db = fixture()
    db.execute("UPDATE participation_war_fetches SET observed_at=? WHERE war_tag='#LIVE'", (OLD,))
    evidence = participation_evidence(db, 1, '2026-11', now=NOW)
    assert decorate_participation_accounts(accounts(), evidence)[0]['display_status']['failed_clan'] is True
    later = datetime(2026, 11, 4, 12, tzinfo=timezone.utc)
    status = decorate_participation_accounts(accounts(), participation_evidence(db, 1, '2026-11', now=later))[0]['display_status']
    assert status['code'] == 'not_recent'
    assert status['failed_clan'] is False


def test_unsealed_final_result_does_not_fabricate_success():
    db = fixture()
    db.execute('DELETE FROM bonus_allowance_wars')
    status = decorate_participation_accounts(accounts(), participation_evidence(db, 1, '2026-11', now=NOW))[0]['display_status']
    assert status['code'] == 'not_recent'
    assert status['failed_clan'] is False


def test_other_clans_failed_war_does_not_mark_known_healthy_side_failed():
    db = fixture()
    rounds = json.dumps([['#END'], ['#LIVE', '#OTHER'], ['#PREP']])
    db.execute('UPDATE participation_group_observations SET war_tags_json=?', (rounds,))
    db.execute("DELETE FROM participation_war_observations WHERE clan_tag='#B' AND war_tag='#LIVE'")
    db.execute('INSERT INTO participation_war_observations VALUES(1,?,?,?,?,?,?)',
               ('2026-11', '#OTHER', '#B', 'WAR', 0, OLD))
    db.execute('INSERT INTO participation_war_fetches VALUES(1,?,?,?,?,?)',
               ('2026-11', '#OTHER', 0, json.dumps(['#A', '#B']), OLD))
    evidence = participation_evidence(db, 1, '2026-11', now=NOW)
    assert evidence['#A'].failure_reason is None
    assert evidence['#A'].active_wars_current is True
    assert evidence['#B'].failure_reason == 'war_unavailable'
    assert evidence['#B'].active_wars_current is False


def test_final_payload_decoration_preserves_policy_fingerprint_and_saved_snapshot():
    from cwl_web.participation_display import decorate_participation_payload
    from cwl_web.bonuses import _fingerprint
    from utils.cwl_bonus_raffle import eligibility, lazy_eligibility

    db = fixture()
    row = {**accounts()[0], 'source_complete': True, 'attacks': 7, 'stars': 21,
           'in_current_roster': True, 'pool': 'lazy'}
    payload = {'cycle': '2026-11', 'accounts': [row], 'fingerprint': 'existing-reviewed-token',
               'draws': [{'snapshot': {'cycle': '2026-10', 'winners': [row]}}]}
    before = deepcopy(payload)
    fingerprint = _fingerprint(payload)
    changes = db.total_changes
    output = decorate_participation_payload(db, 1, payload, now=NOW)
    assert payload == before
    assert payload['accounts'][0] is row
    assert payload['draws'][0]['snapshot']['winners'][0] is row
    assert output['accounts'][0] is not row
    assert output['accounts'][0] is not output['draws'][0]['snapshot']['winners'][0]
    assert _fingerprint(payload) == fingerprint
    assert output['fingerprint'] == 'existing-reviewed-token'
    assert output['accounts'][0]['display_status']['code'] == 'in_progress'
    assert {k: v for k, v in output['accounts'][0].items() if k != 'display_status'} == row
    assert eligibility(output['accounts'][0], 4) == eligibility(row, 4) is None
    assert lazy_eligibility(output['accounts'][0]) == lazy_eligibility(row) is None
    old = output['draws'][0]['snapshot']['winners'][0]
    assert old['display_status']['code'] == 'not_recent'
    assert {k: v for k, v in old.items() if k != 'display_status'} == row
    assert db.total_changes == changes


def test_fresh_ended_to_active_regression_is_a_named_failure_not_an_old_check():
    db = fixture()
    db.execute("UPDATE participation_war_fetches SET ended=0,observed_at=? WHERE war_tag='#END'", (STAMP,))
    facts = participation_evidence(db, 1, '2026-11', now=NOW)
    assert facts['#A'].failure_reason == 'war_state_regression'
    status = decorate_participation_accounts(accounts(), facts)[0]['display_status']
    assert status['failed_clan'] is True
    assert status['code'] == 'stale'


def test_initial_group_failure_names_only_captured_accounts_not_new_signups():
    db = fixture()
    db.execute("DELETE FROM participation_group_observations WHERE clan_tag='#A'")
    captured = {**accounts()[0], 'source_status': 'unavailable', 'source_attacks': None, 'source_stars': None}
    fresh_signup = {**captured, 'tag': '#NEW', 'source_status': 'never'}
    rows = [captured, fresh_signup]
    facts = participation_evidence(db, 1, '2026-11', now=NOW, accounts=rows)
    output = decorate_participation_accounts(rows, facts)
    assert output[0]['display_status']['failed_clan'] is True
    assert output[0]['display_status']['code'] == 'unavailable'
    assert output[1]['display_status']['failed_clan'] is False
    assert output[1]['display_status']['code'] == 'never'


def test_export_prefixed_status_preserves_columns_nulling_values_and_scope():
    from cwl_web.participation_display import decorate_participation_payload
    db = fixture()
    row = {'tag': '#P', 'assigned_clan_tag': '#A', 'participation_source_status': 'stale',
           'participation_source_complete': False, 'participation_source_attacks': 1,
           'participation_source_stars': 3, 'participation_attacks': 1}
    nulled = {**row, 'tag': '#OLD', 'participation_source_status': None, 'participation_attacks': None}
    payload = {'summary': {'cwl_month': '2026-11'}, 'rows': [row, nulled],
               'columns': ['tag', 'participation_attacks', 'participation_source_status'], 'counts': {'rows': 2}}
    original = deepcopy(payload)
    output = decorate_participation_payload(db, 1, payload, now=NOW)
    assert payload == original
    assert output['rows'][0]['participation_display_status']['code'] == 'in_progress'
    assert 'participation_display_status' not in output['rows'][1]
    assert output['rows'][1] == nulled
    assert output['columns'] == payload['columns'] and output['counts'] == {'rows': 2}
    assert {k: v for k, v in output['rows'][0].items() if k != 'participation_display_status'} == row


def test_manual_bonus_warning_words_change_after_policy_without_removing_reason_gate():
    from cwl_web.participation_display import decorate_participation_payload
    db = fixture()
    row = {**accounts()[0], 'player_name': 'Fixture', 'eligibility_reason': 'Meets configured rules'}
    warning = '#P Fixture: Meets configured rules; source stale / incomplete'
    payload = {'cycle': '2026-11', 'selected': [row], 'warnings': [warning],
               'blocking_reasons': ['Add a reason for Fixture'], 'can_confirm': False,
               'fingerprint': 'raw-policy-fingerprint'}
    before = deepcopy(payload)
    output = decorate_participation_payload(db, 1, payload, now=NOW)
    assert payload == before
    assert output['warnings'] == ['#P Fixture: Meets configured rules; CWL in progress']
    assert len(output['warnings']) == len(payload['warnings'])
    assert output['blocking_reasons'] == payload['blocking_reasons']
    assert output['can_confirm'] is False
    assert output['fingerprint'] == payload['fingerprint']
