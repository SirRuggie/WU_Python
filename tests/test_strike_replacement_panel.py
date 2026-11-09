"""Discord /strikes replacements panel: private, FWA-only, shared slot rules."""
import asyncio
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


def render(rows, state, clans=None, linked=frozenset()):
    store, calls = make_store(rows, clans)
    state = {'_id': 'tok', 'guild_id': 1, 'clan_tags': [], 'weights': [], 'member_id': None,
             'page': 0, **state}
    links = (LinksResult(sources={value: ('ClashKing',) for value in linked}) if linked is not None
             else LinksResult(unavailable=('ClashPerk',)))
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


def test_member_select_with_unavailable_links_shows_message_not_crash():
    rows = [candidate('#NOID', weight=150000)]
    payload, _ = render(rows, {'weights': [150000], 'member_id': 7777777777777777777}, linked=None)
    text = text_of(payload)
    assert 'Account links could not be verified. Try again.' in text and '`#NOID`' not in text


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
