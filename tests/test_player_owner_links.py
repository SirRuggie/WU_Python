import asyncio
from unittest.mock import AsyncMock

from utils import recruit_links


def lookup(monkeypatch, ck, cp):
    king = AsyncMock(return_value=ck)
    perk = AsyncMock(return_value=cp)
    monkeypatch.setattr(recruit_links.clash_links, '_lookup_shared_links', king)
    monkeypatch.setattr(recruit_links.clashperk_links, 'lookup', perk)
    result = asyncio.run(recruit_links.resolve_players(['#PYY', '#QCC', '#GCC', '#PYY']))
    king.assert_awaited_once_with(player_tags=['#GCC', '#PYY', '#QCC'])
    perk.assert_awaited_once_with(player_tags=['#GCC', '#PYY', '#QCC'])
    return result


def test_union_and_matching_owners(monkeypatch):
    result = lookup(monkeypatch,
        [{'player_tag': '#PYY', 'user_id': '123'}, {'player_tag': '#QCC', 'user_id': '456'}],
        [{'tag': '#PYY', 'userId': '123'}, {'tag': '#GCC', 'userId': '789'}])
    assert result.owners == {'#PYY': '123', '#QCC': '456', '#GCC': '789'}
    assert not result.conflicts and not result.unavailable


def test_conflicts_do_not_choose_arbitrary_owner(monkeypatch):
    result = lookup(monkeypatch, [{'player_tag': '#PYY', 'user_id': '123'}],
                    [{'tag': '#PYY', 'userId': '456'}])
    assert result.owners == {}
    assert result.conflicts == ('#PYY',)


def test_partial_provider_failure_keeps_other_links(monkeypatch):
    result = lookup(monkeypatch, None, [{'tag': '#PYY', 'userId': '123'}])
    assert result.owners == {'#PYY': '123'}
    assert result.unavailable == ('ClashKing',)


def test_bad_owner_not_used_for_mention(monkeypatch):
    result = lookup(monkeypatch, [], [{'tag': '#PYY', 'userId': 'bad'}, {'tag': '#FOREIGN', 'userId': '123'}])
    assert not result.owners
    assert result.unavailable == ('ClashPerk',)
