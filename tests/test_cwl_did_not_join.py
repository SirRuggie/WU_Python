"""Did not join: a finished CWL with no league-group or war roster entry."""
from datetime import datetime, timedelta, timezone

from cwl_web.participation import current_account_view
from cwl_web.participation_display import decorate_participation_accounts
from utils.cwl_bonus_raffle import eligibility, lazy_eligibility
from utils.cwl_participation_status import ParticipationEvidence
from utils.cwl_working_roster import account_token

SNAPSHOT = {'tag': '#PYY', 'user_id': '1', 'player_name': 'Fixture', 'town_hall': 16,
            'pool': 'lazy', 'assigned_clan_tag': '#PQQ', 'assigned_clan_name': 'Family'}


def source(status, *, hours=2, ended=('#PQQ',)):
    checked = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    row = {'attacks': None, 'stars': None, 'status': status, 'complete': 0,
           'checked_at': checked, 'warning': None, 'roster_token': account_token(SNAPSHOT)}
    if status == 'no_data':
        row['ended_clans'] = frozenset(ended)
    return row


def test_raw_no_data_survives_the_stale_label():
    row = current_account_view(SNAPSHOT, None, source('no_data'))
    assert row['source_status'] == 'stale'
    assert row['source_no_show'] is True
    # Mid-CWL (group not ENDED) or another clan's finished group never proves a no-show.
    assert current_account_view(SNAPSHOT, None, source('no_data', ended=()))['source_no_show'] is False
    assert current_account_view(SNAPSHOT, None, source('no_data', ended=('#OTHER',)))['source_no_show'] is False
    assert current_account_view(SNAPSHOT, None, source('partial'))['source_no_show'] is False
    assert current_account_view(SNAPSHOT, None, None)['source_no_show'] is False


def test_did_not_join_needs_a_finished_group():
    row = current_account_view(SNAPSHOT, None, source('no_data'))
    ended = decorate_participation_accounts([row], {'#PQQ': ParticipationEvidence(group_state='ENDED')})
    live = decorate_participation_accounts([row], {'#PQQ': ParticipationEvidence(group_state='WAR')})
    unknown = decorate_participation_accounts([row], {})
    assert ended[0]['did_not_join'] is True
    assert live[0]['did_not_join'] is False
    assert unknown[0]['did_not_join'] is False
    unassigned = decorate_participation_accounts(
        [{**row, 'assigned_clan_tag': None}], {None: ParticipationEvidence(group_state='ENDED')})
    assert unassigned[0]['did_not_join'] is False
    assert 'did_not_join' not in row


def lazy_account(**patch):
    return {'tag': '#PYY', 'pool': 'lazy', 'assigned_clan_tag': '#PQQ', 'in_current_roster': True,
            'attacks': None, 'stars': None, 'source_complete': False, 'source_no_show': True,
            'bonus_review': {'override_reason': 'Staff checked'}, **patch}


def test_lazy_reason_cannot_cover_did_not_join():
    assert lazy_eligibility(lazy_account()) == 'Did not join the CWL clan'
    # Without the no-show fact, a reason still covers Not checked.
    assert lazy_eligibility(lazy_account(source_no_show=False)) is None


def test_main_did_not_join_is_excluded_without_blocking():
    account = {'in_current_roster': True, 'roster_changed': False, 'source_complete': False,
               'source_status': 'stale', 'attacks': None, 'source_no_show': True}
    assert eligibility(account, 3) == 'Did not join the CWL clan'
    assert eligibility({**account, 'source_no_show': False}, 3) == 'Results are not complete'


def test_manual_selection_names_did_not_join_without_refresh_hint():
    from copy import deepcopy
    from unittest.mock import patch
    from cwl_web import bonuses
    account = dict(tag='#P', player_name='Player', pool='main', assigned_clan_tag='#A',
                   roster_changed=False, already_confirmed_this_cycle=False,
                   source_complete=False, source_status='stale', source_no_show=True,
                   recommended=False, eligibility_reason='Results are not complete',
                   reason='', selected=True)
    data = dict(accounts=[account], season_status='draft', cycle='2026-11',
                publication_version=1, active_other_cycles=[],
                clans=[dict(tag='#A', name='Clan A', slots=1)], cycle_confirmed=[],
                revision=4, award_status='not_awarded')
    with patch.object(bonuses, '_view', return_value=deepcopy(data)):
        result = bonuses._preview(None, 1)
    assert result['can_confirm'] is False
    assert result['blocking_reasons'] == ['Player did not join the CWL clan']


def test_bonus_status_counts_did_not_join_as_captured():
    from unittest.mock import patch
    from cwl_web import bonus_raffle
    base = dict(pool='lazy', assigned_clan_tag='#A', assigned_clan_name='Clan A',
                host_valid=True, in_current_roster=True)
    state = dict(policies={'main': None}, clans=[dict(tag='#A', name='Clan A')],
                 accounts=[dict(base, tag='#P', source_complete=True, attacks=4, stars=9),
                           dict(base, tag='#Q', source_complete=False, source_no_show=True,
                                attacks=None, stars=None)],
                 allowances={}, draws=[], cycle='2026-11', season_status='draft')
    with patch.object(bonus_raffle, '_state', return_value=state):
        status = bonus_raffle._bonus_status(None, 1)
    assert status['pools']['lazy'][0]['results_state'] == 'captured'
    state['accounts'][1]['source_no_show'] = False
    with patch.object(bonus_raffle, '_state', return_value=state):
        status = bonus_raffle._bonus_status(None, 1)
    assert status['pools']['lazy'][0]['results_state'] == 'partial'


def test_did_not_join_status_is_final_not_incomplete():
    from utils.cwl_participation_status import effective_participation_status
    evidence = ParticipationEvidence(group_state='ENDED', group_current=True,
                                     active_wars_current=True, finalized_wars_usable=True)
    plain = effective_participation_status('stale', complete=False, has_results=False, evidence=evidence)
    assert plain['code'] == 'incomplete'
    status = effective_participation_status('stale', complete=False, has_results=False,
                                            evidence=evidence, did_not_join=True)
    assert status['code'] == 'did_not_join' and status['warning'] is None
    row = current_account_view(SNAPSHOT, None, source('no_data'))
    shown = decorate_participation_accounts([row], {'#PQQ': evidence})[0]
    assert shown['display_status']['code'] == 'did_not_join'


def test_source_row_adds_ended_clans_only_for_no_data():
    import sqlite3
    from cwl_web.participation_sync import source_row
    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE participation_source_results(season_id,cycle,tag,attacks,stars,status,complete,checked_at,warning,roster_token)')
    db.execute('CREATE TABLE participation_group_observations(season_id,cycle,clan_tag,state)')
    db.executemany('INSERT INTO participation_group_observations VALUES (1,"2026-11",?,?)',
                   [('#PQQ', 'ENDED'), ('#WAR', 'WAR')])
    db.executemany('INSERT INTO participation_source_results VALUES (1,"2026-11",?,NULL,NULL,?,0,NULL,NULL,NULL)',
                   [('#A', 'no_data'), ('#B', 'partial')])
    assert source_row(db, 1, '2026-11', '#A')['ended_clans'] == frozenset({'#PQQ'})
    assert 'ended_clans' not in source_row(db, 1, '2026-11', '#B').keys()
