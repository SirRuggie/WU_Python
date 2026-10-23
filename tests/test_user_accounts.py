"""Public merged inventory behavior; no live Discord requests."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extensions.commands import accounts, user_accounts
from utils import recruit_links, todo_data


@pytest.fixture(autouse=True)
def clean_cache():
    user_accounts._results.clear()
    yield
    user_accounts._results.clear()


@pytest.mark.parametrize('value', ['', '0', '-1', '@everyone', '<@123>', '１２３', str(2**64)])
def test_invalid_ids(value):
    assert user_accounts.parse_discord_id(value) is None


def test_merge_deduplicates_and_preserves_partial_profiles(monkeypatch):
    king = AsyncMock(return_value=[
        {'player_tag': '#PYY', 'user_id': '123'},
        {'player_tag': '#PQQ', 'user_id': '123'},
    ])
    perk = AsyncMock(return_value=[
        {'tag': '#PYY', 'userId': '123'},
        {'tag': '#PGG', 'userId': '123'},
        {'tag': '#PLL', 'userId': '999'},
    ])
    monkeypatch.setattr(recruit_links.clash_links, '_lookup_shared_links', king)
    monkeypatch.setattr(recruit_links.clashperk_links, 'lookup', perk)
    fetch = AsyncMock(return_value=([
        todo_data.Account(tag='#PYY', name='Player', clan_tag=None, clan_name=None, town_hall=18),
    ], ['#PQQ: GatewayError']))
    monkeypatch.setattr(todo_data, 'fetch_accounts', fetch)
    async def run():
        data = await user_accounts.load_inventory(object(), 123, force=True)
        assert {entry.tag for entry in data.entries} == {'#PYY', '#PQQ', '#PGG'}
        assert (data.loaded_count, data.error_count, data.not_found_count) == (1, 1, 1)
        assert data.entries[0].link_sources == ('ClashKing', 'ClashPerk')
        assert await user_accounts.load_inventory(object(), 123) is data
        assert king.await_count == perk.await_count == 1
        user_accounts._results.clear()  # A restart reloads links for the same target.
        await user_accounts.load_inventory(object(), 123)
        await user_accounts.load_inventory(object(), 123, force=True)
        assert king.await_count == perk.await_count == 3
    asyncio.run(run())


@pytest.mark.parametrize('unavailable', [('ClashKing',), ('ClashPerk',), ('ClashKing', 'ClashPerk')])
def test_outages_never_claim_no_links(unavailable):
    data = accounts.AccountsData(unavailable_sources=unavailable)
    payload = str([c.build() for c in accounts.render_accounts(data, discord_id=123)])
    assert 'Account lookup incomplete' in payload
    assert 'No linked accounts' not in payload
    assert all(name in payload for name in unavailable)


def test_public_invocation_uses_requested_id_and_disables_mentions(monkeypatch):
    load = AsyncMock(return_value=accounts.AccountsData())
    monkeypatch.setattr(user_accounts, 'load_inventory', load)
    ctx = SimpleNamespace(user=SimpleNamespace(id=999), defer=AsyncMock(),
                          interaction=SimpleNamespace(edit_initial_response=AsyncMock()))
    asyncio.run(user_accounts.UserAccounts.invoke(
        SimpleNamespace(discord_id='123'), ctx, coc_client='client',
    ))
    ctx.defer.assert_awaited_once_with(ephemeral=False)
    load.assert_awaited_once_with('client', 123, force=True)
    kwargs = ctx.interaction.edit_initial_response.call_args.kwargs
    assert kwargs['user_mentions'] is kwargs['role_mentions'] is kwargs['mentions_everyone'] is False


def test_public_pages_keep_target_even_for_other_clicker(monkeypatch):
    data = accounts.AccountsData(entries=tuple(
        accounts.AccountEntry(f'#TAG{i}', accounts.STATUS_NOT_FOUND) for i in range(46)
    ))
    load = AsyncMock(return_value=data)
    monkeypatch.setattr(user_accounts, 'load_inventory', load)
    ctx = SimpleNamespace(user=SimpleNamespace(id=999))
    for page, first, last in [(0, 0, 19), (1, 20, 39), (2, 40, 45), (999, 40, 45)]:
        rendered = asyncio.run(user_accounts.user_accounts_page_handler(
            ctx, f'123:{page}', coc_client='client',
        ))
        payload = str([c.build() for c in rendered])
        assert f'`#TAG{first}`' in payload and f'`#TAG{last}`' in payload
        assert 'user_accounts_page:123:' in payload
        assert '999' not in payload
        load.assert_awaited_with('client', 123)


def test_malformed_button_does_not_load_or_replace_panel(monkeypatch):
    load = AsyncMock()
    monkeypatch.setattr(user_accounts, 'load_inventory', load)
    ctx = SimpleNamespace(respond=AsyncMock())
    assert asyncio.run(user_accounts.user_accounts_page_handler(
        ctx, 'invalid:1', coc_client='client',
    )) is None
    load.assert_not_awaited()
