"""Discord /strikes replacements panel: private, FWA-only, shared slot rules."""
import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import hikari
import pytest

from extensions.commands import strikes
from utils.dashboard_urls import STRIKES_URL
from utils.recruit_links import LinksResult


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def to_list(self, length=None): return self.rows


class Collection:
    def __init__(self, rows): self.rows = rows
    def find(self, *_args, **_kwargs): return Cursor(self.rows)


def candidate(tag, *, count=0, priority='normal', weight=None, th=15, clan='#P2Y',
              manual=False, member=None, **extra):
    return {'player_tag': tag, 'player_name': tag.lstrip('#'), 'current_clan_tag': clan,
            'last_seen_clan_tag': clan, 'active_strikes': count, 'replacement_priority': priority,
            'weight': weight, 'town_hall': th, 'is_manual': manual, 'member_id': member,
            'clan_is_current': True, **extra}


def make_store(rows, clans=None):
    calls = []
    class Store:
        mongo = SimpleNamespace(
            clans=Collection(clans or [{'tag': '#P2Y', 'name': 'Edrag Rush', 'type': 'FWA'},
                                       {'tag': '#L2L', 'name': 'Lazy', 'type': 'normal'}]),
            strike_profiles=Collection([{'player_tag': row['player_tag']} for row in rows]))
        async def replacement(self, *args, **kwargs):
            calls.append((args, kwargs))
            return rows
    return Store(), calls


def render(rows, state, clans=None, linked=frozenset(), links=None):
    store, calls = make_store(rows, clans)
    state = {'_id': 'tok', 'guild_id': 1, 'clan_tags': [], 'weights': [], 'member_id': None,
             'page': 0, **state}
    links = links or (LinksResult(sources={value: ('ClashKing',) for value in linked}) if linked is not None
                      else LinksResult(unavailable=('ClashKing', 'ClashPerk'),
                                                  forward_unavailable=('ClashKing', 'ClashPerk')))
    with patch.object(strikes, 'cached_weights', lambda _tags: {}), \
            patch.object(strikes.recruit_links, 'resolve', AsyncMock(return_value=links)):
        panel = asyncio.run(strikes.replacement_panel(store, state))
    payload, _ = panel[0].build()
    return payload, calls


def text_of(payload):
    return '\n'.join(item['content'] for item in payload['components'] if item['type'].name == 'TEXT_DISPLAY')


def rows_of(payload):
    return [item for item in payload['components'] if item['type'].name == 'ACTION_ROW']


def test_list_mode_uses_the_marked_or_three_strike_pool_and_shows_member_note_and_left_clan():
    rows = [candidate('#ONE', count=1), candidate('#TWO', count=2),
            candidate('#THREE', count=3, member=111222333444555666),
            candidate('#MARK', manual=True, note=None, replacement_note='fill me', departed=True),
            candidate('#LAZ', count=5, clan='#L2L')]
    payload, calls = render(rows, {})
    text = text_of(payload)
    assert '#ONE' not in text and '#TWO' not in text      # 1-2 strikes are not slots
    assert '#LAZ' not in text                              # non-FWA clan
    assert '`#THREE`' in text and '<@111222333444555666>' in text
    assert 'fill me' in text and 'Left clan' in text
    assert '2 accounts' in text
    assert calls[0][0][1] is None and calls[0][1]['browse_all'] is True


def test_controls_present_and_removed_controls_absent():
    payload, _ = render([candidate('#THREE', count=3)], {})
    rows = rows_of(payload)
    kinds = [row['components'][0]['type'].name for row in rows]
    assert kinds == ['TEXT_SELECT_MENU', 'USER_SELECT_MENU', 'BUTTON']
    ids = [c.get('custom_id', '') for row in rows for c in row['components']]
    assert not any(value.startswith(('strike_replace_th', 'strike_replace_sort',
                                     'strike_replace_clan_page')) for value in ids)
    labels = [c.get('label') for c in rows[2]['components']]
    assert labels == ['Set weights', 'Previous', 'Next', 'Clear', 'Open on dashboard']
    assert rows[2]['components'][-1]['url'].startswith(STRIKES_URL)
    for row in rows:
        for item in row['components']:
            assert len(item.get('custom_id', '')) <= 100


def test_clan_menu_lists_fwa_clans_with_candidates_only_and_defaults_to_all():
    clans = [{'tag': '#P2Y', 'name': 'Edrag Rush', 'type': 'FWA'},
             {'tag': '#Q0Q', 'name': 'Empty FWA', 'type': 'FWA'},
             {'tag': '#L2L', 'name': 'Lazy', 'type': 'normal'}]
    rows = [candidate('#A', count=3), candidate('#B', count=4, clan='#L2L')]
    payload, _ = render(rows, {}, clans)
    menu = rows_of(payload)[0]['components'][0]
    assert [o['value'] for o in menu['options']] == ['#P2Y']
    assert menu['min_values'] == 0 and menu['placeholder'] == 'All FWA clans'
    assert 'Some clans hidden' not in text_of(payload)


def test_more_than_25_clans_show_the_busiest_25_with_dashboard_note():
    alphabet = '0289PYLQGRJCUV'
    tags = [f'#C{alphabet[i // 14]}{alphabet[i % 14]}' for i in range(30)]
    clans = [{'tag': t, 'name': f'Clan {t}', 'type': 'FWA'} for t in tags]
    rows = [candidate(f'#X{i}', count=3, clan=t) for i, t in enumerate(tags)]
    rows += [candidate(f'#Y{i}', count=3, clan=tags[29]) for i in range(3)]
    payload, _ = render(rows, {}, clans)
    options = [o['value'] for o in rows_of(payload)[0]['components'][0]['options']]
    assert len(options) == 25 and tags[29] in options     # most candidates is kept
    assert 'Some clans hidden; use the dashboard' in text_of(payload)


def test_weights_mode_groups_best_three_per_weight_with_gap_and_priority():
    rows = [candidate(f'#S{i}', count=3, weight=140000 + i * 1000, member=111222333444555666)
            for i in range(5)]
    rows += [candidate('#ONE', count=1, weight=143000)]
    payload, _ = render(rows, {'weights': [143000, 173000]})
    text = text_of(payload)
    assert '### 143k' in text and '### 173k' in text
    assert text.count('`#S') == 6 and '#ONE' not in text
    assert 'Gap 0k' in text and 'Normal' in text and '3 active strikes' in text
    assert '<@111222333444555666>' in text and 'Edrag Rush' in text
    assert strikes.emoji_for(15, {'ranges': {}}) in text
    nav = rows_of(payload)[2]['components']
    assert nav[1].get('disabled') and nav[2].get('disabled')


def test_empty_weight_group_and_member_pool_includes_zero_strike_accounts():
    rows = [candidate('#ZERO', count=0, weight=150000, member=7777777777777777777)]
    payload, _ = render(rows, {'weights': [150000]})
    assert 'No slot in these clans.' in text_of(payload)
    payload, _ = render(rows, {'weights': [150000], 'member_id': 7777777777777777777},
                        linked={'#ZERO'})
    assert '`#ZERO`' in text_of(payload)


def test_member_select_matches_linked_accounts_even_without_cached_member_id():
    rows = [candidate('#NOID', weight=150000, member=None), candidate('#STALE', weight=150000, member=99),
            candidate('#UNLINKED', weight=150000, member=7777777777777777777)]
    payload, _ = render(rows, {'weights': [150000], 'member_id': 7777777777777777777},
                        linked={'#NOID', '#STALE'})
    text = text_of(payload)
    assert '`#NOID`' in text and '`#STALE`' in text and '`#UNLINKED`' not in text


def test_member_select_with_nothing_usable_shows_message_and_an_empty_pool():
    # #NOID would be in the pool if the member filter were skipped.
    rows = [candidate('#NOID', weight=150000, count=3)]
    payload, _ = render(rows, {'weights': [150000], 'member_id': 7777777777777777777}, linked=None)
    text = text_of(payload)
    assert 'Account links are unavailable. Try again.' in text
    assert '`#NOID`' not in text and 'No slot in these clans.' in text
    assert 'Some linked accounts were left out.' not in text


PARTIAL = 'Some linked accounts were left out.'


def test_member_select_keeps_a_tag_linked_to_two_users_and_labels_only_that_row():
    rows = [candidate('#CLEAN', weight=150000), candidate('#DISPUTED', weight=150000)]
    links = LinksResult(sources={'#CLEAN': ('ClashKing',)}, conflicts=('#DISPUTED',))
    payload, _ = render(rows, {'weights': [150000], 'member_id': 7777777777777777777}, links=links)
    text = text_of(payload)
    assert '`#CLEAN`' in text and '`#DISPUTED`' in text and PARTIAL not in text
    assert text.count('Linked to two Discord users') == 1
    assert text.index('Linked to two Discord users') > text.index('`#DISPUTED`')
    assert 'unavailable' not in text


def test_member_select_with_a_failed_provider_but_sources_keeps_them_and_notes_it():
    rows = [candidate('#CLEAN', weight=150000)]
    links = LinksResult(sources={'#CLEAN': ('ClashKing',)}, unavailable=('ClashPerk',),
                         forward_unavailable=('ClashPerk',))
    payload, _ = render(rows, {'weights': [150000], 'member_id': 7777777777777777777}, links=links)
    assert '`#CLEAN`' in text_of(payload) and PARTIAL in text_of(payload)


def test_member_select_in_list_mode_without_weights_lists_linked_accounts_and_notes_partial():
    rows = [candidate('#CLEAN', count=0), candidate('#DISPUTED', count=3), candidate('#OTHER', count=3)]
    links = LinksResult(sources={'#CLEAN': ('ClashKing',)}, conflicts=('#DISPUTED',),
                        unavailable=('ClashPerk',),
                         forward_unavailable=('ClashPerk',))
    payload, _ = render(rows, {'member_id': 7777777777777777777}, links=links)
    text = text_of(payload)
    assert '`#CLEAN`' in text and '`#DISPUTED`' in text and '#OTHER' not in text
    assert PARTIAL in text and '2 accounts' in text and text.count('Linked to two Discord users') == 1


def test_member_select_does_not_require_verified_links():
    links = LinksResult(sources={'#CLEAN': ('ClashPerk',)}, verified={'#CLEAN': False})
    payload, _ = render([candidate('#CLEAN', weight=150000)],
                        {'weights': [150000], 'member_id': 7777777777777777777}, links=links)
    assert '`#CLEAN`' in text_of(payload) and PARTIAL not in text_of(payload)


def test_member_select_clean_links_show_no_partial_note():
    payload, _ = render([candidate('#CLEAN', weight=150000)],
                        {'weights': [150000], 'member_id': 7777777777777777777}, linked={'#CLEAN'})
    assert PARTIAL not in text_of(payload)


def test_list_mode_pages_five_at_a_time_and_sorts_by_priority():
    rows = [candidate(f'#P{i}', count=3) for i in range(7)] + [
        candidate('#TOP', count=3, priority='replace_first')]
    payload, _ = render(rows, {})
    text = text_of(payload)
    assert text.index('#TOP') < text.index('#P0') and 'Page 1/2 · 8 accounts' in text
    assert rows_of(payload)[2]['components'][2].get('disabled') is not True
    payload, _ = render(rows, {'page': 1})
    assert 'Page 2/2' in text_of(payload) and '#TOP' not in text_of(payload)


def test_dashboard_link_carries_weights_clans_and_member():
    url = strikes.replacement_dashboard_url({'weights': [143000, 173000], 'clan_tags': ['#ABC123'],
                                             'member_id': 123456789012345678})
    assert url == (STRIKES_URL + '?view=replacements&slot_weight=143000&slot_weight=173000'
                   '&slot_clan=%23ABC123&slot_member=123456789012345678')
    query = parse_qs(urlparse(url).query)
    assert query['slot_clan'] == ['#ABC123']


def test_dashboard_link_stays_within_512_characters_and_says_when_clans_are_left_out():
    alphabet = '0289PYLQGRJCUV'
    clans = [f'#{alphabet[index // 5]}{alphabet[index % 5]}YYLQ0G8' for index in range(25)]
    state = {'weights': [143000, 173000, 150000, 160000, 170000], 'clan_tags': clans,
             'member_id': 123456789012345678}
    url, left_out = strikes.replacement_dashboard_link(state)
    assert len(url) <= 512 and left_out
    query = parse_qs(urlparse(url).query)
    assert len(query['slot_weight']) == 5 and query['slot_member'] == ['123456789012345678']
    assert query['slot_clan'] == clans[:len(query['slot_clan'])] and 0 < len(query['slot_clan']) < 25
    assert strikes.replacement_dashboard_url(state) == url
    fwa = [{'tag': value, 'name': f'Clan {value}', 'type': 'FWA'} for value in clans]
    payload, _ = render([candidate('#A', count=3)], state, fwa)
    assert 'Some clans not in link' in text_of(payload)
    assert not strikes.replacement_dashboard_link({'weights': [143000], 'clan_tags': clans[:2]})[1]


def test_command_replies_privately_with_mentions_suppressed_and_member_option():
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), guild_id=123, defer=AsyncMock(), respond=AsyncMock())
    inserted = AsyncMock()
    command = strikes.Replacements.__new__(strikes.Replacements)
    command.member = SimpleNamespace(id=555666777888999000)
    with patch.object(strikes, 'authorized', AsyncMock(return_value=True)), \
         patch.object(strikes, 'insert_state', inserted), \
         patch.object(strikes, 'replacement_panel', AsyncMock(return_value=[])):
        asyncio.run(command.invoke(ctx, mongo=object(), coc_client=object()))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    kwargs = ctx.respond.await_args.kwargs
    assert kwargs['ephemeral'] is True
    assert kwargs['user_mentions'] is False and kwargs['mentions_everyone'] is False
    assert inserted.await_args.args[1]['member_id'] == 555666777888999000


def test_command_refuses_without_staff_access():
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), guild_id=123, defer=AsyncMock(), respond=AsyncMock())
    command = strikes.Replacements.__new__(strikes.Replacements)
    command.member = None
    with patch.object(strikes, 'authorized', AsyncMock(return_value=False)), \
         patch.object(strikes, 'insert_state', AsyncMock()) as inserted:
        asyncio.run(command.invoke(ctx, mongo=object(), coc_client=object()))
    inserted.assert_not_awaited()
    assert ctx.respond.await_args.kwargs['ephemeral'] is True


@pytest.mark.parametrize('text,expected', [
    ('143, 173, 150', [143000, 173000, 150000]), ('143k 173000', [143000, 173000]),
    ('143;173', [143000, 173000])])
def test_parse_weights_accepts_up_to_five_values(text, expected):
    assert strikes.parse_weights(text) == expected


@pytest.mark.parametrize('text,message', [
    ('', 'Enter 1 to 5'), ('1,2,3,4,5,6', 'up to 5'), ('143, abc', '"abc"')])
def test_parse_weights_rejects_bad_input_naming_the_value(text, message):
    with pytest.raises(ValueError, match=message):
        strikes.parse_weights(text)


def test_stale_clan_is_marked_last_known():
    payload, _ = render([candidate('#S2L', count=3, clan_is_current=False)], {})
    assert 'Last known' in text_of(payload)


def _worst_case(note_length):
    weights = [100000, 120000, 140000, 160000, 180000]
    rows = [candidate(f'#W{group}{number}', weight=weight + number, member=111222333444555666,
                      manual=True, departed=True, clan_is_current=False, count=3,
                      player_name='N' * 24, replacement_note='n' * note_length)
            for group, weight in enumerate(weights) for number in range(3)]
    clans = [{'tag': '#P2Y', 'name': 'C' * 24, 'type': 'FWA'}]
    links = LinksResult(conflicts=tuple(row['player_tag'] for row in rows))
    state = {'weights': weights, 'member_id': 111222333444555666}
    return render(rows, state, clans, links=links)[0]


def test_worst_case_slot_panel_stays_under_the_text_limit_and_keeps_every_row():
    payload = _worst_case(60)
    text = text_of(payload)
    assert sum(len(item['content']) for item in payload['components']
               if item['type'].name == 'TEXT_DISPLAY') <= strikes.PANEL_TEXT_LIMIT
    assert text.count('`#W') == 15
    assert text.count('<@111222333444555666>') == 15 + 1
    assert text.count('Linked to two Discord users') == 15
    assert text.count('Left clan') == 15
    assert 'n' * 60 not in text and 'n' * 5 in text   # notes were shortened, not rows


def test_normal_slot_panel_keeps_full_notes():
    payload = _worst_case(5)
    assert text_of(payload).count('n' * 5) >= 15
    note = 'x' * 60
    rows = [candidate('#ONE', count=3, replacement_note=note, manual=True)]
    assert note in text_of(render(rows, {})[0])


def _units(payload):
    return sum(len(item['content'].encode('utf-16-le')) // 2 for item in payload['components']
               if item['type'].name == 'TEXT_DISPLAY')


def ctag(number):
    return f'#P{"0289PYLQGRJCUV"[number // 14]}{"0289PYLQGRJCUV"[number % 14]}Y'


def test_realistic_worst_case_stays_under_the_limit_in_utf16_units_with_every_row():
    weights = [143345, 153877, 163012, 173499, 183901]
    clans = [{'tag': ctag(number), 'name': f'🔥Clan{number:02d}-longname'[:15], 'type': 'FWA'}
             for number in range(25)]
    rows = [candidate(f'#W{group}{number}', weight=weight + 4345 * (number + 1),
                      clan=ctag(group * 3 + number), member=111222333444555666,
                      manual=True, departed=True, clan_is_current=False, count=3,
                      player_name='😀' * 12, replacement_note='🔥' * 60)
            for group, weight in enumerate(weights) for number in range(3)]
    links = LinksResult(conflicts=tuple(row['player_tag'] for row in rows),
                        forward_unavailable=('ClashKing',))
    state = {'weights': weights, 'member_id': 111222333444555666, 'refresh_warning': True,
             'clan_tags': [clan['tag'] for clan in clans]}
    payload = render(rows, state, clans, links=links)[0]
    text = text_of(payload)
    assert _units(payload) <= strikes.PANEL_TEXT_LIMIT
    assert text.count('`#W') == 15
    assert text.count('<@111222333444555666>') >= 15
    assert text.count('Linked to two Discord users') == 15


def _scenarios():
    two = [{'tag': '#P2Y', 'name': 'Edrag Rush', 'type': 'FWA'}, {'tag': '#Q0Q', 'name': 'Second', 'type': 'FWA'}]
    spread = [candidate(f'#S{i}', count=3, weight=140000 + i * 1000, member=111222333444555666)
              for i in range(5)]
    return {
        'list': (render([candidate(f'#P{i}', count=3, member=111222333444555666 if i % 2 else None,
                                   manual=True, replacement_note='fill me', departed=i == 2)
                         for i in range(7)], {'page': 1})[0]),
        'weights': render(spread, {'weights': [143000, 173000]})[0],
        'clans': render([candidate('#A', count=3, weight=150000),
                         candidate('#B', count=3, weight=151000, clan='#Q0Q')],
                        {'clan_tags': ['#P2Y', '#Q0Q'], 'weights': [150000]}, two)[0],
        'member': render([candidate('#C', weight=150000)],
                         {'weights': [150000], 'member_id': 7777777777777777777, 'refresh_warning': True},
                         linked={'#C'})[0],
        'notes': render([candidate('#N', count=3, manual=True, replacement_note='x' * 60,
                                   clan_is_current=False, weight=150000)], {'weights': [150000]})[0],
        'empty': render([], {})[0],
    }


def test_normal_panels_are_byte_identical_to_the_pre_bounding_output():
    expected = json.loads((Path(__file__).parent / 'fixtures' / 'strike_panel_snapshots.json').read_text(encoding='utf-8'))
    actual = {name: text_of(payload) for name, payload in _scenarios().items()}
    assert actual == expected


def _adversarial(*, clans=25, notice='n' * 180, names=15, member=1395728880991234567, flags=True):
    weights = [143345, 153877, 163012, 173499, 183901]
    emoji = '😀'
    fwa = [{'tag': ctag(number), 'name': emoji * names, 'type': 'FWA'} for number in range(clans)]
    rows = [candidate(f'#W{group}{number}', weight=weight + 4345 * (number + 1),
                      clan=ctag((group * 3 + number) % clans), member=member, manual=True,
                      departed=flags, clan_is_current=not flags, count=3,
                      player_name=emoji * names, replacement_note='🔥' * 60)
            for group, weight in enumerate(weights) for number in range(3)]
    links = LinksResult(conflicts=tuple(row['player_tag'] for row in rows) if flags else (),
                        forward_unavailable=('ClashKing',) if flags else ())
    state = {'weights': weights, 'member_id': member, 'refresh_warning': True,
             'clan_tags': [clan['tag'] for clan in fwa]}
    store, _ = make_store(rows, fwa)
    state = {'_id': 'tok', 'guild_id': 1, 'page': 0, **state}
    with patch.object(strikes, 'cached_weights', lambda _tags: {}), \
            patch.object(strikes.recruit_links, 'resolve', AsyncMock(return_value=links)):
        panel = asyncio.run(strikes.replacement_panel(store, state, notice=notice))
    return panel[0].build()[0], weights, member


def _no_broken_mention(text):
    return len(re.findall(r'<@', text)) == len(re.findall(r'<@\d+>', text))


def test_adversarial_panel_is_bounded_and_keeps_summary_weights_and_member():
    payload, weights, member = _adversarial()
    text = text_of(payload)
    summary = text.split('\n')[1]
    assert _units(payload) <= 3900
    assert summary.startswith('Weights 143.345k, 153.877k, 163.012k, 173.499k, 183.901k')
    assert '25 FWA clans' in summary and summary.endswith(f'<@{member}>')
    assert _no_broken_mention(text)
    capped = [line for line in text.split('\n') if line.startswith('nnn')]
    assert capped and all(len(line) == 120 and line.endswith('…') for line in capped)
    assert text.count('### ') == 5


def test_summary_cut_never_happens_even_when_everything_else_is_long():
    payload, _, member = _adversarial(notice='n' * 500, flags=True)
    text = text_of(payload)
    assert _units(payload) <= strikes.PANEL_TEXT_LIMIT
    assert f'<@{member}>' in text.split('\n')[1] and not text.split('\n')[1].endswith('…')


def _fixed_panel(clans, notice='', disputed=0, limit=None):
    fwa = [{'tag': ctag(number), 'name': f'C{number:02d}' * 5 + '😀' * 10, 'type': 'FWA'} for number in range(clans)]
    weights = [143345, 153877, 163012, 173499, 183901]
    rows = [candidate(f'#W{group}{number}', weight=weight + 4345 * (number + 1), clan=ctag(0), manual=True,
                      count=3, player_name='😀' * 15, replacement_note='note ' * 12,
                      member=111222333444555666, departed=True, clan_is_current=False)
            for group, weight in enumerate(weights) for number in range(3)]
    state = {'weights': weights, 'clan_tags': [clan['tag'] for clan in fwa], 'member_id': 111222333444555666}
    links = LinksResult(sources={row['player_tag']: ('ClashKing',) for row in rows},
                        conflicts=tuple(row['player_tag'] for row in rows[:disputed]))
    store, _ = make_store(rows, fwa)
    state = {'_id': 'tok', 'guild_id': 1, 'page': 0, **state}
    with patch.object(strikes, 'cached_weights', lambda _tags: {}), \
            patch.object(strikes.recruit_links, 'resolve', AsyncMock(return_value=links)), \
            patch.object(strikes, 'PANEL_TEXT_LIMIT', limit or strikes.PANEL_TEXT_LIMIT):
        return asyncio.run(strikes.replacement_panel(store, state, notice=notice))[0].build()[0]


def test_only_the_clan_list_becomes_a_count_when_that_is_enough():
    full = text_of(_fixed_panel(2))
    assert 'C00' * 5 + '😀' * 10 + ', ' + 'C01' * 5 + '😀' * 10 in full.split('\n')[1] and 'FWA clans' not in full
    payload = _fixed_panel(25, '', 13)
    text = text_of(payload)
    assert _units(payload) <= strikes.PANEL_TEXT_LIMIT
    assert '25 FWA clans' in text.split('\n')[1] and 'C00' * 5 not in text.split('\n')[1]
    assert text.count('`#W') == 15 and 'More slots' not in text


def test_a_long_notice_is_left_alone_while_the_count_is_enough():
    text = text_of(_fixed_panel(25, 'n' * 180, 12))
    assert '25 FWA clans' in text.split('\n')[1]
    assert [len(line) for line in text.split('\n') if line.startswith('nnn')] == [180]


def test_one_selected_clan_reads_singular_and_all_rows_stay():
    text = text_of(_fixed_panel(1, 'n' * 180, 13, limit=3860))
    assert '1 FWA clan ·' in text and text.count('`#W') == 15


def test_best_row_only_keeps_full_names_when_that_is_enough():
    payload = _fixed_panel(25, 'n' * 180, 13, limit=2000)
    text = text_of(payload)
    assert text.count('`#W') == 5 and '😀' * 15 in text and _units(payload) <= 2000


def test_only_the_notice_line_is_capped_when_that_is_enough():
    text = text_of(_fixed_panel(25, 'n' * 180, 13))
    capped = [line for line in text.split('\n') if line.startswith('nnn')]
    assert capped == ['n' * 119 + '…']
    assert text.count('`#W') == 15 and 'More slots' not in text


def test_rows_beyond_the_second_go_first_and_the_best_two_per_weight_stay():
    payload = _fixed_panel(25, 'n' * 180, 13, limit=3800)
    text = text_of(payload)
    assert _units(payload) <= 3800 and text.count('`#W') == 10
    assert 'More slots on the dashboard.' in text
    sections = text.split('### ')[1:]
    assert len(sections) == 5 and all(section.count('`#W') == 2 for section in sections)
    assert _no_broken_mention(text)


def test_names_shrink_as_the_last_step_and_never_cut_mentions():
    payload = _fixed_panel(25, 'n' * 180, 13, limit=1400)
    text = text_of(payload)
    assert _units(payload) <= 1400 and text.count('`#W') == 5
    assert text.count('<@111222333444555666>') == 6 and _no_broken_mention(text)
    assert text.split('\n')[1].startswith('Weights 143.345k') and '25 FWA clans' in text.split('\n')[1]


def test_all_fwa_clans_only_when_none_selected_and_single_clan_wording():
    payload, _ = render([candidate('#A', count=3, weight=150000)], {'weights': [150000]})
    assert text_of(payload).split('\n')[1] == 'Weights 150k · All FWA clans'
    assert 'All FWA clans +' not in text_of(_adversarial()[0])


def test_selected_clans_over_the_limit_read_as_a_count():
    payload, _, _ = _adversarial(clans=15)
    assert '15 FWA clans' in text_of(payload).split('\n')[1]


def test_dropping_rows_keeps_the_best_row_per_weight_and_says_so():
    payload, weights, _ = _adversarial(notice='n' * 500)
    text = text_of(payload)
    assert 'More slots on the dashboard.' in text
    assert text.count('`#W') < 15 and _units(payload) <= strikes.PANEL_TEXT_LIMIT
    sections = text.split('### ')[1:]
    assert len(sections) == 5 and all('`#W' in section for section in sections)
