"""Wording updates affect fresh defaults while saved compatibility stays exact."""
from copy import deepcopy
import json
from pathlib import Path

from utils import cwl_campaign as campaign

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/ste155_legacy_copy.json').read_text())


def test_unversioned_defaults_remain_exactly_the_deployed_legacy_copy():
    assert campaign.default_campaign(new_copy=False) == FIXTURE['unversioned_default']


def test_old_stored_typo_body_still_normalizes_exactly_as_deployed():
    assert 'your in' in FIXTURE['old_stored_body'] and 'less then' in FIXTURE['old_stored_body']
    assert campaign.LEGACY_SIGNUP_MAIN == FIXTURE['old_stored_body']
    stored = {'messages': {'signup': {'variants': {'main': {'body': FIXTURE['old_stored_body'], 'buttons': []}}}}}
    original = deepcopy(stored)
    assert campaign.normalize_signup_entry(stored) == FIXTURE['normalized_stored_campaign']
    assert stored == original


def test_current_copy_uses_the_new_version_and_plain_default_words():
    current = campaign.default_campaign()
    assert campaign.DEFAULT_COPY_VERSION == 128
    assert current[campaign.DEFAULT_COPY_FIELD] == 128
    for pool in campaign.AUDIENCES:
        assert '6. Select **Sign up**.' in current['messages']['signup']['variants'][pool]['body']
        assert 'Select **My clan assignments**' in current['messages']['roster']['variants'][pool]['body']
        assert 'Are you signed up already?' in current['messages']['reminder:1']['variants'][pool]['body']
        assert 'Signup reminder #1' in current['messages']['reminder:1']['variants'][pool]['title']


def test_saved_version127_normalization_does_not_gain_new_help_or_duplicate_text():
    old = deepcopy(FIXTURE['version127_defaults'])
    assert campaign.normalize_signup_entry(old) == FIXTURE['version127_normalized']
    assert old == FIXTURE['version127_defaults']


def test_sparse_saved_version127_uses_its_original_copy_baseline():
    assert campaign._saved_copy_baseline({campaign.DEFAULT_COPY_FIELD: 127}) == FIXTURE['version127_defaults']


def test_wording_version_changes_no_schedule_destination_role_or_button():
    old = deepcopy(FIXTURE['version127_defaults'])
    new = campaign.default_campaign()
    old.pop(campaign.DEFAULT_COPY_FIELD)
    new.pop(campaign.DEFAULT_COPY_FIELD)
    for mid in old['messages']:
        old['messages'][mid].pop('label')
        new['messages'][mid].pop('label')
        for pool in campaign.AUDIENCES:
            for field in ('title', 'body'):
                old['messages'][mid]['variants'][pool].pop(field)
                new['messages'][mid]['variants'][pool].pop(field)
    assert old == new


def test_same_custom_body_uses_the_stored127_and_current128_check_lines_side_by_side():
    bodies = {}
    for version, line in [(127, campaign.SIGNUP_CHECK_LINE), (128, campaign.CURRENT_SIGNUP_CHECK_LINE)]:
        saved = campaign.default_campaign(copy_version=version)
        saved['messages']['signup']['variants']['main']['body'] = 'Custom signup text'
        original = deepcopy(saved)
        result = campaign.normalize_signup_entry(saved)
        bodies[version] = result['messages']['signup']['variants']['main']['body']
        assert bodies[version] == 'Custom signup text\n\n' + line
        assert saved == original
    assert campaign.CURRENT_SIGNUP_CHECK_LINE not in bodies[127]
    assert campaign.SIGNUP_CHECK_LINE not in bodies[128]
