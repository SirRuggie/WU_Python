"""Display status has no authority over stored results or bonus decisions."""
from dataclasses import replace

import pytest

from utils.cwl_participation_status import ParticipationEvidence, effective_participation_status


CURRENT = ParticipationEvidence(group_state='WAR', group_current=True,
    active_wars_current=True, finalized_wars_usable=True, round_number=2)


@pytest.mark.parametrize('raw', ['partial', 'preparation', 'stale'])
def test_in_progress_and_sealed_final_results_are_normal_not_failed(raw):
    result = effective_participation_status(raw, complete=False, has_results=True, evidence=CURRENT)
    assert result == {'code': 'in_progress', 'label': 'CWL in progress',
                      'warning': None, 'failed_clan': False, 'round': 2}


@pytest.mark.parametrize('has_results,code', [(True, 'stale'), (False, 'unavailable')])
def test_confirmed_group_or_live_war_failure_is_the_named_clan_failure(has_results, code):
    result = effective_participation_status('partial', complete=False, has_results=has_results,
        evidence=replace(CURRENT, failure_reason='unavailable'))
    assert result['code'] == code and result['failed_clan'] is True
    assert result['warning'] and 'could not refresh' in result['warning']


@pytest.mark.parametrize('complete,code', [(True, 'complete'), (False, 'incomplete')])
def test_ended_complete_and_incomplete_remain_distinct(complete, code):
    result = effective_participation_status('stale', complete=complete, has_results=True,
        evidence=replace(CURRENT, group_state='ENDED', round_number=7))
    assert result['code'] == code and result['failed_clan'] is False
    assert bool(result['warning']) is not complete


def test_wrong_month_is_not_hidden_by_current_war_evidence():
    result = effective_participation_status('season_mismatch', complete=False, has_results=True, evidence=CURRENT)
    assert result['code'] == 'season_mismatch' and result['warning']


@pytest.mark.parametrize('raw', [None, 'never', 'unavailable', 'no_data', 'unassigned'])
def test_clan_freshness_cannot_fabricate_an_account_result(raw):
    result = effective_participation_status(raw, complete=False, has_results=False, evidence=CURRENT)
    assert result['code'] not in ('complete', 'in_progress')
    assert result['failed_clan'] is False


def test_preparation_is_distinct_from_an_active_cwl_round():
    result = effective_participation_status('preparation', complete=False, has_results=False,
        evidence=replace(CURRENT, group_state='PREPARATION'))
    assert result['code'] == 'preparation' and result['warning'] is None


@pytest.mark.parametrize('field', ['group_current', 'active_wars_current', 'finalized_wars_usable'])
def test_missing_or_old_evidence_never_looks_like_a_success(field):
    result = effective_participation_status('stale', complete=True, has_results=True,
        evidence=replace(CURRENT, **{field: False}))
    assert result['code'] == 'not_recent' and result['warning']
    assert result['failed_clan'] is False  # An old check is not a newly failed fetch.
