import pytest
from utils.replacement_view import replacement_page, best_slots


def row(tag, count, *, priority='normal', marked=False, weight=100000, clan='#Q2Y', th=16):
    return {'player_tag': tag, 'player_name': tag, 'active_strikes': count,
            'replacement_priority': priority, 'is_manual': marked, 'weight': weight,
            'last_seen_clan_tag': clan, 'town_hall': th}


def test_threshold_toggle_and_manual_mark_are_independent_of_strike_limit():
    rows = [row('#P2Y', 1), row('#G2Y', 2), row('#J2Y', 3), row('#C2Y', 0, marked=True)]
    assert {r['player_tag'] for r in replacement_page(rows)['items']} == {'#J2Y', '#C2Y'}
    assert replacement_page(rows, include_low=True)['total'] == 4


def test_top_ten_priority_strikes_then_lowest_weight_across_clans():
    rows = [row(f'#P{i}', 10 + i) for i in range(12)]
    rows += [row('#HIGH', 3, priority='high', clan='#J2Y'),
             row('#LOWER', 3, priority='high', weight=90000),
             row('#CHOP', 0, priority='replace_first', marked=True)]
    result = replacement_page(rows, clan='#Q2Y')
    assert [r['player_tag'] for r in result['top'][:3]] == ['#CHOP', '#LOWER', '#HIGH']
    assert len(result['top']) == 10
    assert all(r['last_seen_clan_tag'] == '#Q2Y' for r in result['items'])


def test_filters_apply_before_page_and_group_counts():
    rows = [row(f'#P{i:03}', i % 7, th=16 if i % 2 else 17) for i in range(273)]
    first = replacement_page(rows, town_hall=16, limit=25, sort='strikes')
    second = replacement_page(rows, town_hall=16, limit=25, offset=25, sort='strikes')
    assert first['total'] == second['total'] == sum(r['town_hall'] == 16 and r['active_strikes'] >= 3 for r in rows)
    assert not {r['player_tag'] for r in first['items']} & {r['player_tag'] for r in second['items']}
    assert first['groups'][0]['listed'] == first['total']


def test_best_three_slots_ignore_unknown_weight_and_order_gap():
    rows = [row('#A', 3, weight=None), row('#B', 4, weight=148000),
            row('#C', 5, weight=150000), row('#D', 4, weight=149000), row('#E', 8, weight=90000)]
    assert [r['player_tag'] for r in best_slots(rows, 149000)] == ['#D', '#C', '#B']


@pytest.mark.parametrize('kwargs', [{'offset': -1}, {'limit': 101}, {'town_hall': True}, {'sort': 'bad'}])
def test_invalid_filter_rejected(kwargs):
    with pytest.raises(ValueError):
        replacement_page([], **kwargs)


def test_replacement_revision_rejects_stale_set_and_clear_without_changing_strikes():
    import asyncio
    from copy import deepcopy
    from test_strike_ux_backend import setup
    from utils.strike_store import StrikeConflict

    async def scenario():
        db, service = setup()
        await db.clans.insert_one({'_id': 'family', 'tag': '#Q2Y'})
        original = deepcopy(db.strike_records.rows)
        first = await service.set_replacement_preference(1, '#P2Y', 'high', 'First', 9,
                                                        clan_tag='#Q2Y', expected_revision=0)
        assert first['revision'] == 1
        for action in ('edit', 'clear'):
            with pytest.raises(StrikeConflict):
                if action == 'edit':
                    await service.set_replacement_preference(1, '#P2Y', 'normal', 'Stale', 8,
                                                             clan_tag='#Q2Y', expected_revision=0)
                else:
                    await service.clear_replacement_preference(1, '#P2Y', 8, expected_revision=0)
        assert db.strike_profiles.rows['1:#P2Y']['replacement_note'] == 'First'
        cleared = await service.clear_replacement_preference(1, '#P2Y', 9, expected_revision=1)
        assert cleared['revision'] == 2 and not cleared['replacement_listed']
        with pytest.raises(StrikeConflict):
            await service.set_replacement_preference(1, '#P2Y', 'high', 'Old', 8,
                                                     clan_tag='#Q2Y', expected_revision=1)
        assert db.strike_records.rows == original
    asyncio.run(scenario())


FWA = {'#Q2Y', '#J2Y'}


def slot_row(tag, count=3, *, weight=143000, clan='#Q2Y', marked=False, member=None,
             priority='normal', **extra):
    return {**row(tag, count, weight=weight, clan=clan, marked=marked, priority=priority),
            'member_id': member, **extra}


def tags(rows):
    return [r['player_tag'] for r in rows]


def test_slot_pool_includes_marked_zero_strike_and_excludes_one_or_two_strikes():
    from utils.replacement_view import slot_pool
    rows = [slot_row('#M', 0, marked=True), slot_row('#A', 1), slot_row('#B', 2), slot_row('#C', 3)]
    assert tags(slot_pool(rows, fwa_tags=FWA)) == ['#M', '#C']


def test_slot_pool_member_returns_all_their_fwa_accounts_whatever_the_strikes():
    from utils.replacement_view import slot_pool
    rows = [slot_row('#A', 0, member='7'), slot_row('#B', 1, member='7'),
            slot_row('#C', 5, member='8'), slot_row('#D', 0, member='7', clan='#NOTFWA')]
    assert tags(slot_pool(rows, fwa_tags=FWA, member_tags={'#A', '#B', '#D'})) == ['#A', '#B']


def test_slot_pool_member_matches_linked_tags_not_cached_member_id():
    from utils.replacement_view import slot_pool
    rows = [slot_row('#A', 0, member=None), slot_row('#B', 0, member='99'),
            slot_row('#C', 0, member='7'), slot_row('#E', 0, member='7')]
    assert tags(slot_pool(rows, fwa_tags=FWA, member_tags={'#A', '#B', '#E'})) == ['#A', '#B', '#E']
    assert tags(slot_pool(rows, fwa_tags=FWA, member_tags=set())) == []


def test_slot_pool_excludes_non_fwa_and_respects_clan_filter():
    from utils.replacement_view import slot_pool
    rows = [slot_row('#A', 5, clan='#NOTFWA'), slot_row('#B', 5, clan='#Q2Y'), slot_row('#C', 5, clan='#J2Y')]
    assert tags(slot_pool(rows, fwa_tags=FWA)) == ['#B', '#C']
    assert tags(slot_pool(rows, fwa_tags=FWA, clan_tags=['#J2Y'])) == ['#C']
    assert tags(slot_pool(rows, fwa_tags=FWA, clan_tags=['#NOTFWA'])) == []


def test_find_slots_orders_gap_then_priority_then_strikes_then_tag_and_caps_at_three():
    from utils.replacement_view import find_slots
    rows = [slot_row('#E', 3, weight=143000), slot_row('#D', 4, weight=143000),
            slot_row('#C', 3, weight=143000, priority='high'),
            slot_row('#B', 3, weight=143000, priority='replace_first'),
            slot_row('#F', 3, weight=142000), slot_row('#A', 3, weight=143000)]
    group = find_slots(rows, [143000], fwa_tags=FWA)[0]
    assert group['weight'] == 143000
    assert tags(group['slots']) == ['#B', '#C', '#D']
    assert [r['weight_difference'] for r in group['slots']] == [0, 0, 0]
    tie = find_slots([slot_row('#Z'), slot_row('#Y')], [143000], fwa_tags=FWA)[0]
    assert tags(tie['slots']) == ['#Y', '#Z']
    assert find_slots([slot_row('#F', weight=142000)], [143000], fwa_tags=FWA)[0]['slots'][0]['weight_difference'] == 1000


def test_find_slots_skips_unknown_weight_and_keeps_input_order_with_repeats():
    from utils.replacement_view import find_slots
    rows = [slot_row('#N', weight=None), slot_row('#Z', weight=0), slot_row('#K', weight=150000)]
    groups = find_slots(rows, [173000, 143000, 173000], fwa_tags=FWA)
    assert [g['weight'] for g in groups] == [173000, 143000, 173000]
    assert all(tags(g['slots']) == ['#K'] for g in groups)


def test_find_slots_includes_departed_account_in_grace_and_rejects_bad_weight_counts():
    from utils.replacement_view import find_slots
    gone = slot_row('#G', 0, marked=True, departed=True)
    assert tags(find_slots([gone], [143000], fwa_tags=FWA)[0]['slots']) == ['#G']
    for bad in ([], [1] * 6, [0], [True]):
        with pytest.raises(ValueError):
            find_slots([gone], bad, fwa_tags=FWA)
