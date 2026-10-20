from types import SimpleNamespace
import asyncio
import pytest

from extensions.commands import strikes


def candidate(tag, *, strikes_count=0, priority='normal', weight=None, gap=None, th=4):
    return {'player_tag': tag, 'player_name': tag.lstrip('#'), 'current_clan_tag': '#P2Y',
            'active_strikes': strikes_count, 'replacement_priority': priority,
            'weight': weight, 'weight_difference': gap, 'town_hall': th}


def test_compact_panel_row_shows_clan_name_town_hall_and_zero_gap():
    line = strikes.replacement_browser_line(1, candidate('#P2Y2', strikes_count=2,
        priority='high', weight=149000, gap=0), {'#P2Y': 'Edrag Rush'})
    assert 'Edrag Rush · TH4 · 149k · Gap 0k' in line
    assert 'High · 2 active strikes' in line
    assert '`#P2Y2`' in line


def test_sort_modes_change_ranking_without_losing_unknown_weights():
    rows = [candidate('#A', strikes_count=1, priority='replace_first', weight=None, th=4),
            candidate('#B', strikes_count=3, weight=149000, gap=1000, th=15),
            candidate('#C', strikes_count=2, weight=147000, gap=2000, th=16)]
    tags = lambda mode: [row['player_tag'] for row in strikes.replacement_sort_rows(rows, mode, 148000)]
    assert tags('priority')[0] == '#A'
    assert tags('weight') == ['#B', '#C', '#A']
    assert tags('strikes') == ['#B', '#C', '#A']
    assert tags('th') == ['#C', '#B', '#A']


@pytest.mark.parametrize("weight", [None, 149000])
def test_panel_only_shows_struck_or_manually_listed_accounts(monkeypatch, weight):
    class Cursor:
        def __init__(self, rows): self.rows = rows
        async def to_list(self, length=None): return self.rows
    class Collection:
        def __init__(self, rows): self.rows = rows
        def find(self, *_args, **_kwargs): return Cursor(self.rows)
    calls = []
    class Store:
        mongo = SimpleNamespace(
            clans=Collection([{'tag': '#P2Y', 'name': 'Edrag Rush'}]),
            strike_profiles=Collection([{'player_tag': '#P2Y2'}]),
        )
        async def replacement(self, *args, **kwargs):
            calls.append((args, kwargs))
            return [candidate('#P2Y2', weight=149000),
                    candidate('#P2Y8', strikes_count=2),
                    {**candidate('#P2Y9', priority='replace_first'), 'is_manual': True},
                    {**candidate('#P2YG'), 'is_manual': True}]
    async def weights(_tags): return {}
    monkeypatch.setattr(strikes, 'cached_weights', lambda _tags: {})
    state = {'_id': 'token', 'guild_id': 1, 'clan_tag': '#P2Y', 'town_hall': 4,
             'weight': weight, 'sort': 'priority', 'page': 0, 'clan_page': 0}
    panel = asyncio.run(strikes.replacement_panel(Store(), state))
    assert len(panel) == 1
    assert calls[0][1]['browse_all'] is True
    assert calls[0][1]['family_scope'] == 'all'
    assert calls[0][1]['town_hall'] == 4
    assert calls[0][1]['clan_tag'] == '#P2Y'
    assert calls[0][0][1] == weight
    payload, _ = panel[0].build()
    text = str(payload)
    assert '#P2Y2' not in text
    assert '#P2Y8' in text
    assert '#P2Y9' in text
    assert '#P2YG' in text
    assert '3 accounts' in text
