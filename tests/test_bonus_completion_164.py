"""Owner588 completion requirements preserve every other manual/raffle rule."""
from copy import deepcopy
from unittest.mock import patch
import pytest
from cwl_web import bonuses
from utils.cwl_bonus_raffle import lazy_eligibility, eligibility


def view(*, complete=True, status='stale', recommended=True, reason=''):
    account = dict(tag='#P', player_name='Player', pool='main', assigned_clan_tag='#A',
                   roster_changed=False, already_confirmed_this_cycle=False,
                   source_complete=complete, source_status=status, recommended=recommended,
                   eligibility_reason='Meets configured dashboard rules' if recommended else 'Below configured participation threshold',
                   reason=reason, selected=True)
    return dict(accounts=[account], season_status='draft', cycle='2026-11',
                publication_version=1, active_other_cycles=[],
                clans=[dict(tag='#A',name='Clan A',slots=1)],cycle_confirmed=[],
                revision=4, award_status='not_awarded')


def preview(data):
    before = deepcopy(data)
    with patch.object(bonuses, '_view', return_value=data):
        result = bonuses._preview(None, 1)
    assert data == before
    assert result['fingerprint'] == bonuses._fingerprint(before)
    assert result['selected'] == before['accounts']
    return result


def test_complete_raw_stale_needs_no_participation_reason():
    result = preview(view())
    assert result['can_confirm'] is True
    assert result['warnings'] == []
    assert result['blocking_reasons'] == []


@pytest.mark.parametrize('reason', ['', 'Staff reviewed', 'Previously saved selection'])
def test_incomplete_cannot_be_confirmed_with_any_reason(reason):
    result = preview(view(complete=False, status='partial', reason=reason))
    assert result['can_confirm'] is False
    assert 'CWL results are not complete for Player' in result['blocking_reasons']
    assert 'Use Check Clash now to refresh results.' in result['blocking_reasons']


def test_complete_below_threshold_still_needs_staff_reason_and_warning_ack():
    result = preview(view(recommended=False))
    assert result['can_confirm'] is False
    assert 'Add a reason for Player' in result['blocking_reasons']
    assert len(result['warnings']) == 1
    result = preview(view(recommended=False, reason='Reviewed exception'))
    assert result['can_confirm'] is True
    assert len(result['warnings']) == 1


def test_refresh_instruction_follows_all_incomplete_accounts_once():
    data = view(complete=False, reason='Reviewed')
    data['clans'][0]['slots'] = 3
    data['accounts'] += [{**data['accounts'][0], 'tag': '#Q', 'player_name': 'Second'}]
    result = preview(data)
    assert result['can_confirm'] is False
    assert result['warnings'] == []
    assert result['blocking_reasons'] == [
        'CWL results are not complete for Player',
        'CWL results are not complete for Second',
        'Use Check Clash now to refresh results.',
    ]


@pytest.mark.parametrize('reason', ['', 'Staff override'])
def test_neither_raffle_path_can_override_incomplete_results(reason):
    account = dict(tag='#P',pool='lazy',assigned_clan_tag='#A',in_current_roster=True,
                   source_complete=False,source_status='partial',attacks=7,stars=21,
                   bonus_review={'override_reason':reason})
    assert lazy_eligibility(account) == 'Complete participation results are unavailable'
    assert eligibility(account,4) == 'Results are not complete'
    account['source_complete'] = True
    account['source_status'] = 'stale'
    assert lazy_eligibility(account) is None
    assert eligibility(account,4) is None


@pytest.mark.parametrize('reason', ['', 'Staff override'])
def test_incomplete_keeps_other_flag_reasons_and_cannot_override_them(reason):
    account = dict(tag='#P',pool='lazy',assigned_clan_tag='#A',in_current_roster=True,
                   source_complete=False,source_status='partial',attacks=7,stars=21,
                   bonus_review={'flags':['left_family'],'override_reason':reason})
    result = lazy_eligibility(account)
    assert result == 'Left the family; Complete participation results are unavailable'
    account['source_complete'] = True
    if reason:
        assert lazy_eligibility(account) is None
    else:
        assert lazy_eligibility(account) == 'Left the family'
