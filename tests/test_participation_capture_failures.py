"""Capture diagnostics name the failed clan/round without member data."""
import json
import logging
import asyncio
from types import SimpleNamespace

from cwl_web.participation_sync import _capture_failure
from cwl_web.participation_sync import _fetch_wars
from cwl_web.providers import ProviderUnavailable


def test_capture_failure_names_clan_round_war_reason_in_result_and_journal(caplog):
    details = []
    with caplog.at_level(logging.WARNING, logger='cwl_web.participation_sync'):
        result = _capture_failure(details, clan_tag='#CLAN', clan_name='Family',
            reason='war_state_regression', war_tag='#WAR', round_number=2)
    assert details == [result]
    assert result == {'clan_tag': '#CLAN', 'clan_name': 'Family', 'round': 2,
                      'war_tag': '#WAR', 'reason': 'war_state_regression'}
    assert len(caplog.records) == 1
    assert json.loads(caplog.records[0].getMessage().removeprefix('CWL capture failure ')) == result


def test_capture_failure_deduplicates_exact_events_without_hiding_another_round(caplog):
    details = []
    with caplog.at_level(logging.WARNING, logger='cwl_web.participation_sync'):
        for number in (1, 1, 2):
            _capture_failure(details, clan_tag='#CLAN', clan_name=None,
                             reason='unavailable', war_tag='#WAR', round_number=number)
    assert [r['round'] for r in details] == [1, 2]
    assert all(r['clan_name'] == '#CLAN' for r in details)
    assert len(caplog.records) == 2


def test_external_clan_name_stays_one_json_journal_event(caplog):
    details = []
    with caplog.at_level(logging.WARNING, logger='cwl_web.participation_sync'):
        result = _capture_failure(details, clan_tag='#CLAN', clan_name='Name\n%s<script>', reason='http_503')
    message = caplog.records[0].getMessage()
    assert '\n' not in message
    assert json.loads(message.removeprefix('CWL capture failure ')) == result
    assert result['clan_name'] == 'Name\n%s<script>'
    assert result['round'] is None and result['war_tag'] is None


def test_war_fetch_keeps_http_status_without_retrying_or_exposing_provider_text():
    calls = []
    async def fail(tag):
        calls.append(tag)
        error = ProviderUnavailable('SECRET_PROVIDER_TEXT')
        error.status_code = 503
        raise error
    details = []
    rows = asyncio.run(_fetch_wars(SimpleNamespace(league_war=fail), ['#WAR'], diagnostics=details))
    assert calls == ['#WAR'] and rows == [('#WAR', None, 'unavailable')]
    assert details == [{'phase': 'war', 'tag': '#WAR', 'http_status': 503, 'error_type': 'ProviderUnavailable'}]
    result = []
    _capture_failure(result, clan_tag='#CLAN', clan_name='Family', reason='unavailable',
                     war_tag='#WAR', round_number=2, diagnostic=details[0])
    assert result[0]['http_status'] == 503 and result[0]['round'] == 2
    assert 'SECRET_PROVIDER_TEXT' not in json.dumps(result)
