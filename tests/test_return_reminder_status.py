from datetime import datetime, timedelta, timezone
from utils.return_reminder_status import return_status

NOW = datetime(2026, 10, 21, tzinfo=timezone.utc)


def row(**settings):
    return {'players': [{'tag': '#ABC'}], 'expires_at': NOW + timedelta(days=15),
            'reminders': settings}


def test_no_list_and_manual_are_not_reported_as_scheduled():
    assert return_status(None, 'FWA', now=NOW)['state'] == 'not_saved'
    result = return_status(row(enabled=True), 'MAIN', now=NOW)
    assert result['state'] == 'manual'
    assert result['every_minutes'] is None


def test_paused_and_never_started_are_distinct():
    assert return_status(row(enabled=False), 'FWA', now=NOW)['state'] == 'idle'
    assert return_status(row(enabled=False, started_at=NOW), 'FWA', now=NOW)['state'] == 'paused'


def test_seven_day_limit_wins_over_enabled_configuration():
    result = return_status(row(enabled=True, started_at=NOW-timedelta(days=7)), 'FWA', now=NOW)
    assert result['state'] == 'expired'
    assert result['expires_at'] == NOW.isoformat()


def test_seasonal_cutoff_wins_over_seven_day_window():
    current = row(enabled=True, started_at=NOW)
    current['expires_at'] = NOW - timedelta(seconds=1)
    assert return_status(current, 'FWA', now=NOW)['state'] == 'expired'


def test_naive_mongo_dates_and_dictionary_players_are_supported_without_mutation():
    current = row(enabled=True, started_at=NOW.replace(tzinfo=None), every_minutes=120,
                  last_sent_at=NOW.replace(tzinfo=None))
    current['players'] = {'#ABC': {'tag': '#ABC'}}
    result = return_status(current, 'FWA', now=NOW)
    assert result['state'] == 'scheduled'
    assert result['players'] == 1
    assert result['every_minutes'] == 120
    assert result['last_sent_at'] == NOW.isoformat()
    assert current['reminders']['started_at'].tzinfo is None
