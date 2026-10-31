from datetime import datetime, timedelta, timezone

from utils.player_activity import baseline, activity_changed, observe

NOW = datetime(2026, 10, 31, tzinfo=timezone.utc)


def test_first_read_and_reset_do_not_claim_activity():
    first = observe(None, {'attackWins': 100, 'donations': 200}, now=NOW)
    assert 'last_seen_at' not in first
    reset = observe(first, {'attackWins': 0, 'donations': 0}, now=NOW + timedelta(hours=1))
    assert 'last_seen_at' not in reset
    active = observe(reset, {'attackWins': 1}, now=NOW + timedelta(hours=2))
    assert active['last_seen_source'] == 'clash_api'


def test_excluded_and_partial_fields():
    old = baseline({'trophies': 4900, 'donationsReceived': 10, 'attackWins': 10})
    assert not activity_changed(old, baseline({'trophies': 4950, 'donationsReceived': 20}))
    assert not activity_changed(old, baseline({'attackWins': 2}))
    assert activity_changed({'trophies': 5000}, {'trophies': 5001})
    assert activity_changed({'trophies': 4999}, {'trophies': 5000})
    assert not activity_changed({'trophies': 5100}, {'trophies': 5000})
    assert not activity_changed({}, {'attackWins': 5})


def test_upgrades_and_preferences_count_but_war_achievements_do_not():
    assert activity_changed({'warPreference': 'out'}, {'warPreference': 'in'})
    assert activity_changed(baseline({'heroes': [{'name': 'King', 'level': 1}]}),
                            baseline({'heroes': [{'name': 'King', 'level': 2}]}))
    assert baseline({'achievements': [{'name': 'War Hero', 'value': 100}]}) == {}
    assert activity_changed(baseline({'achievements': [{'name': 'Gold Grab', 'value': 1}]}),
                            baseline({'achievements': [{'name': 'Gold Grab', 'value': 2}]}))


def test_400_days_state_remains_bounded():
    state = None
    for day in range(400):
        state = observe(state, {'attackWins': day}, now=NOW + timedelta(days=day))
    assert len(state['active_days']) == 30
    assert state['active_days'][0] == (NOW + timedelta(days=370)).date().isoformat()


def test_newly_unlocked_units_count_after_an_existing_baseline():
    assert activity_changed(baseline({'heroes': []}), baseline({'heroes': [{'name': 'King', 'level': 1}]}))
    assert not activity_changed({'attackWins': 1}, baseline({'heroes': [{'name': 'King', 'level': 1}]}))
    assert not activity_changed(None, baseline({'heroes': [{'name': 'King', 'level': 1}]}))
