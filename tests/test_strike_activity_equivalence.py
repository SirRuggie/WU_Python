"""Ordinary-suite old/new output comparison; no Mongo opt-in or live data."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import random

import pytest

from tests.fixtures.strike_activity_955_reference import family_activity_rows_reference
from utils.player_activity_overview import activity_view_context, family_activity_rows
from utils.strike_store import status_of


def is_neutral(record):
    return record.get('source') == 'war' and (
        record.get('revoked_at') or record.get('kind') in ('mismatch', 'exempt', 'no_attack')
        or record.get('exemption'))


def is_monitored(record):
    return (record.get('source') == 'war' and record.get('capture_source') == 'clash_api'
            and not record.get('import_id') and record.get('war_type') != 'cwl')


@pytest.mark.parametrize('seed', range(24))
def test_randomized_war_rich_rows_equal_frozen_955_except_explicit_neutral_veto(seed):
    rng = random.Random(seed)
    now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
    profiles, activity, records = [], [], []
    for index in range(450):
        player = f'#P{index}'
        profile = {'player_tag': player, 'player_name': f'Profile {index}',
                   'current_clan_tag': rng.choice(['#FAMILY', '#OUT', None])}
        if rng.randrange(4) == 0:
            profile.update(departed_clan_tag='#FAMILY',
                           departed_last_seen_at=now-timedelta(days=rng.choice([2, 100])))
        profiles.append(profile)
        for number in range(rng.randrange(4)):
            record = {'player_tag': player, 'kind': 'strike', 'source': 'manual',
                      'occurred_at': now-timedelta(days=rng.randrange(14)),
                      'expires_at': now+timedelta(days=rng.choice([-1, 20]))}
            if rng.randrange(4) == 0:
                record['revoked_at'] = now
            records.append(record)
        # Real signal inputs, including duplicate legacy dispositions in both
        # orders and monitored strikes whose counts must survive the veto.
        war_key = f'war:{index}:0'
        monitored = {'player_tag': player, 'source': 'war', 'capture_source': 'clash_api',
                     'kind': 'completed', 'war_key': war_key,
                     'occurred_at': now-timedelta(days=1), 'missed_attacks': 2}
        if index % 5 == 0:
            monitored.update(kind='strike', expires_at=now+timedelta(days=30))
        neutral = {'player_tag': player, 'source': 'war', 'war_key': war_key,
                   'kind': rng.choice(['exempt', 'mismatch', 'no_attack'])}
        if index % 3 == 0:
            neutral['import_id'] = 'imported-neutral'
        elif index % 3 == 1:
            neutral.update(kind='strike', revoked_at=now, occurred_at=now,
                           expires_at=now+timedelta(days=30))
        else:
            neutral['exemption'] = 'approved'
        pair = [neutral, monitored] if rng.randrange(2) else [monitored, neutral]
        records.extend(pair if index % 4 in (2, 3) else [monitored] if index % 4 == 0 else [neutral])
        records.extend([
            {'player_tag': player, 'source': 'war', 'capture_source': 'clash_api',
             'kind': 'completed', 'war_key': f'war:{index}:1',
             'occurred_at': now-timedelta(days=3), 'missed_attacks': rng.randrange(3)},
            {'player_tag': player, 'source': 'war', 'capture_source': 'clash_api',
             'kind': 'strike', 'import_id': 'imported-strike', 'war_key': f'import:{index}',
             'occurred_at': now-timedelta(days=2), 'expires_at': now+timedelta(days=30)},
        ])
        if rng.randrange(4):
            item = {'tag': player, 'name': f'Activity {index}', 'updated_at': now,
                    'current_clan_tag': rng.choice(['#FAMILY', '#OUT', None]),
                    'last_seen_at': now-timedelta(days=rng.randrange(15)),
                    'recent_wars': [
                        {'war_key': f'war:{index}:{number}', 'occurred_at': now-timedelta(days=number+1),
                         'attacks_used': rng.randrange(3), 'attacks_available': 2}
                        for number in range(4)],
                    'raid_weekends': []}
            if rng.randrange(8) == 0:
                item['left_at'] = now-timedelta(days=rng.choice([2, 100]))
            activity.append(item)
    clans = [{'tag': '#FAMILY', 'name': 'Family'}]
    tags = {row['tag'] for row in activity}
    old_profiles = [p for p in profiles if p['current_clan_tag'] == '#FAMILY'
                    or p['player_tag'] in tags or (p.get('departed_clan_tag') == '#FAMILY'
                    and p['departed_last_seen_at'] >= now-timedelta(days=90))]
    totals = {}
    for profile in profiles:
        ledger = [r for r in records if r['player_tag'] == profile['player_tag'] and r['kind'] == 'strike']
        active = [r for r in ledger if status_of(r, now) == 'active']
        totals[profile['player_tag']] = {'active_strikes': len(active), 'total_strikes': len(ledger),
            'new_this_week': any(now-timedelta(days=7) <= r['occurred_at'] <= now for r in active)}
    core = {'profiles': profiles, 'clans': clans, 'clan_warning': False,
            'record_totals': totals,
            'replacements': [], 'strike_limit': 3}
    core['activity_headers'] = [
        {key: value for key, value in item.items() if key in ('tag', 'current_clan_tag', 'left_at')}
        for item in activity]
    before = deepcopy((core, activity, records))
    base = family_activity_rows_reference(activity, old_profiles, records, clans,
                                               replacements=[], strike_limit=3, now=now)
    veto_keys = {(r['player_tag'], r['war_key']) for r in records if is_neutral(r)}
    # Independent expected correction: mask only the colliding monitored war
    # provenance for the frozen reference, then run its unchanged implementation.
    # Every ledger record/date/kind remains, including active monitored strikes;
    # the manual source makes just that signal observation ineligible.
    resolved = [{**r, 'source': 'manual'} if is_monitored(r) and not is_neutral(r)
                and (r['player_tag'], r.get('war_key')) in veto_keys else r for r in records]
    expected = family_activity_rows_reference(activity, old_profiles, resolved, clans,
                                               replacements=[], strike_limit=3, now=now)
    actual = family_activity_rows(activity, **activity_view_context(core, activity, records, now=now), now=now)
    assert actual == expected
    assert [r['player_tag'] for r in base] == [r['player_tag'] for r in actual]
    monitored_keys = {(r['player_tag'], r['war_key']) for r in records if is_monitored(r) and not is_neutral(r)}
    collision_players = {player for player, _ in veto_keys & monitored_keys}
    # The retained veto is the sole permitted difference from base. Count and
    # replacement columns cannot change even on the deliberately mixed rows.
    for old, new in zip(base, actual):
        if old['player_tag'] not in collision_players:
            assert old == new
        for field in ('active_strikes', 'total_strikes', 'new_this_week', 'priority',
                      'marked_for_replacement', 'replacement_eligible_low', 'revision'):
            assert old[field] == new[field]
    cold = family_activity_rows([], **activity_view_context(core, None, None, now=now), now=now)
    cold_by_tag, filled_by_tag = {r['player_tag']: r for r in cold}, {r['player_tag']: r for r in actual}
    assert cold_by_tag.keys() <= filled_by_tag.keys()
    for player, row in cold_by_tag.items():
        assert row['active_strikes'] == filled_by_tag[player]['active_strikes']
        assert row['total_strikes'] == filled_by_tag[player]['total_strikes']
    assert (core, activity, records) == before


@pytest.mark.parametrize('activity_clan', ['#OUT', None])
def test_family_profile_with_conflicting_activity_clan_stays_hidden_like_955(activity_clan):
    now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
    profiles = [{'player_tag': '#PYY', 'current_clan_tag': '#FAMILY'}]
    activity = [{'tag': '#PYY', 'current_clan_tag': activity_clan, 'updated_at': now}]
    clans = [{'tag': '#FAMILY', 'name': 'Family'}]
    core = {'profiles': profiles, 'clans': clans, 'clan_warning': False,
            'record_totals': {}, 'replacements': [], 'strike_limit': 3}
    assert family_activity_rows_reference(activity, profiles, [], clans, now=now) == []
    assert family_activity_rows(activity, **activity_view_context(core, activity, [], now=now), now=now) == []


@pytest.mark.parametrize('reverse', [False, True])
def test_neutral_disposition_wins_over_monitored_row_in_either_order(reverse):
    from utils.player_activity_signals import activity_signals
    now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
    monitored = {'player_tag': '#PYY', 'source': 'war', 'capture_source': 'clash_api',
                 'kind': 'strike', 'war_key': 'same', 'occurred_at': now, 'missed_attacks': 2}
    neutral = {'player_tag': '#PYY', 'source': 'war', 'kind': 'exempt', 'war_key': 'same'}
    records = [monitored, neutral]
    if reverse:
        records.reverse()
    signals = activity_signals({}, records, now=now)
    assert signals['observed_wars'] == 0
    assert signals['no_attack_wars'] == 0


def test_unrelated_malformed_profile_and_strike_do_not_fail_selected_scope():
    now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
    core = {'profiles': [{'current_clan_tag': '#OUT'},
                         {'player_tag': '#PYY', 'current_clan_tag': '#FAMILY'}],
            'clans': [{'tag': '#FAMILY'}], 'clan_warning': False,
            'record_totals': {'#OUT': {'invalid': 1}}, 'replacements': [], 'strike_limit': 3}
    selected = activity_view_context(core, [], [], now=now)
    assert [p['player_tag'] for p in selected['profiles']] == ['#PYY']
    core['record_totals']['#PYY'] = {'invalid': 1}
    with pytest.raises(ValueError, match='Invalid strike dates'):
        family_activity_rows([], **activity_view_context(core, [], [], now=now), now=now)
    core['record_totals'] = {}
    core['profiles'][0]['current_clan_tag'] = '#FAMILY'
    with pytest.raises(ValueError, match='Invalid strike profile'):
        activity_view_context(core, [], [], now=now)


@pytest.mark.parametrize('departed_days', [None, 200])
def test_malformed_strike_for_hidden_activity_player_never_fails_filled_view(departed_days):
    now = datetime(2026, 11, 4, 8, tzinfo=timezone.utc)
    activity = [{'tag': '#OUT', 'current_clan_tag': '#OUTSIDE', 'updated_at': now}]
    if departed_days is not None:
        activity[0]['left_at'] = now-timedelta(days=departed_days)
    records = [{'player_tag': '#OUT', 'kind': 'strike', 'occurred_at': now}]
    clans = [{'tag': '#FAMILY'}]
    core = {'profiles': [], 'clans': clans, 'clan_warning': False,
            'record_totals': {'#OUT': {'invalid': 1}}, 'replacements': [], 'strike_limit': 3}
    assert family_activity_rows_reference(activity, [], records, clans, now=now) == []
    assert family_activity_rows(activity, **activity_view_context(core, activity, records, now=now), now=now) == []
