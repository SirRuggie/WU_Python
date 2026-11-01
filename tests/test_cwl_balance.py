from collections import Counter
import random

from utils.cwl_balance import balance_accounts


def account(i, weight=179000, host=None, **extra):
    return dict(tag=str(i), effective_weight=weight, assigned_clan_tag=host,
                kept=False, manual_weight=None, source_status='current', pool='lazy', **extra)


def hosts():
    return [dict(tag=str(i), pool='lazy', capacity=15, min_weight=None,
                 max_weight=None, archived=False) for i in range(3)]


def resulting(accounts, placements):
    moves = {p['tag']: p['assigned_clan_tag'] for p in placements}
    return [(moves.get(a['tag'], a['assigned_clan_tag']), a['effective_weight']) for a in accounts]


def test_nine_equal_weights_spread_three_each_then_next_weights():
    accounts = [account(i, 179000 - (i // 9) * 1000) for i in range(45)]
    plan, skipped = balance_accounts(accounts, hosts(), [a['tag'] for a in accounts], ['0', '1', '2'])
    assert not skipped
    counts = Counter(resulting(accounts, plan))
    assert set(counts.values()) == {3}
    assert Counter(c for c, w in resulting(accounts, plan)) == {'0': 15, '1': 15, '2': 15}


def test_full_clans_can_exchange_selected_accounts():
    accounts = [account(i, 179000 - (i // 15) * 1000, str(i // 15)) for i in range(45)]
    plan, skipped = balance_accounts(accounts, hosts(), [a['tag'] for a in accounts], ['0', '1', '2'])
    assert not skipped and plan
    assert set(Counter(resulting(accounts, plan)).values()) == {5}


def test_locks_missing_and_unavailable_are_unchanged():
    accounts = [account(i, host='0') for i in range(3)]
    accounts[0]['kept'] = True
    accounts[1]['effective_weight'] = None
    accounts[2]['source_status'] = 'unavailable'
    plan, skipped = balance_accounts(accounts, hosts(), ['0', '1', '2'], ['1', '2'])
    assert not plan
    assert {a['reason'] for a in skipped} == {'locked', 'missing_weight', 'source_unavailable'}
    plan, _ = balance_accounts(accounts, hosts(), ['0'], ['1'], True)
    assert plan == [{'tag': '0', 'assigned_clan_tag': '1'}]


def test_weight_range_includes_both_boundaries_and_excludes_missing():
    clan = hosts()[0]
    clan.update(min_weight=172000, max_weight=179000)
    for weight, inside in ((171999, False), (172000, True),
                           (179000, True), (179001, False), (None, False)):
        plan, skipped = balance_accounts([account(1, weight)], [clan], ['1'], ['0'])
        if inside:
            assert plan == [{'tag': '1', 'assigned_clan_tag': '0'}]
            assert skipped == []
        else:
            assert plan == []
            assert skipped == [{'tag': '1', 'reason':
                                'missing_weight' if weight is None else 'no_eligible_rule'}]


def test_pool_range_and_failed_accounts_preserve_slots():
    accounts = [account(i, host='0') for i in range(15)] + [account(20, 100000, '1')]
    clans = hosts()
    clans[0]['pool'] = 'main'
    clans[1]['min_weight'] = 170000
    plan, skipped = balance_accounts(accounts, clans, [a['tag'] for a in accounts], ['0', '1'])
    assert len(plan) == 14
    assert len(skipped) == 2
    assert Counter(c for c, _ in resulting(accounts, plan))['1'] == 15


def test_random_capacity_no_unselected_moves_determinism():
    rng = random.Random(14)
    for _ in range(100):
        accounts = [account(i, rng.choice([None, 175000, 177000, 179000]), str(i // 15)) for i in range(45)]
        for a in accounts:
            a['kept'] = rng.choice([True, False])
        chosen = [a['tag'] for a in accounts if rng.random() > .2]
        plan, skipped = balance_accounts(accounts, hosts(), chosen, ['1', '2'])
        assert (plan, skipped) == balance_accounts(list(reversed(accounts)), hosts(), chosen, ['2', '1'])
        assert max(Counter(c for c, _ in resulting(accounts, plan)).values()) <= 15
        assert all(p['tag'] in chosen and not next(a for a in accounts if a['tag'] == p['tag'])['kept'] for p in plan)


def test_filler_weight_band_is_retained_when_replanning_equal_weight_candidates():
    rows = [account('f', 100000, '0', roster_filler=True), dict(account('heavy', 200000, '1'), kept=True), account('x', 100000), account('y', 100000)]
    plan, skipped = balance_accounts(rows, hosts()[:2], ['f', 'x', 'y'], ['0', '1'])
    assert {'tag':'f','reason':'filler_manual_only'} in skipped
    assert not any(p['tag']=='f' for p in plan)
    assert plan[0] == {'tag':'x','assigned_clan_tag':'1'}
