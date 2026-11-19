"""The persistent FWA base panel: stateless menu, private base reply, panel reset."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari

from extensions.commands import bases_panel
from extensions.components import registered_functions
from utils import town_halls
from test_town_halls_discord_bases_245 import snapshot, walk, built  # noqa: F401


def panel_menu():
    payload = built(bases_panel.panel_components())
    return next(item for item in walk(payload) if item['type'] == hikari.ComponentType.TEXT_SELECT_MENU)


def test_panel_menu_is_persistent_and_lists_registry_bases(snapshot, monkeypatch):
    monkeypatch.setattr(bases_panel, 'town_hall_emoji', lambda level: '<:th16:123456789012345678>' if level == 16 else '')
    menu = panel_menu()
    assert menu['custom_id'] == 'fwa_bases_panel:'
    assert [item['value'] for item in menu['options']] == ['th19', 'th19_new']
    texts = [item.get('content', '') for item in walk(built(bases_panel.panel_components()))]
    assert any('Select your Town Hall' in text for text in texts)
    note = next(text for text in texts if 'TH16 and higher' in text)
    assert note.startswith('<:') and '- **Non-merged**' in note and '- **Merged**' in note
    assert texts[-1] == '-# Only you can see your base.'
    container = built(bases_panel.panel_components())[0]
    assert container['components'][0]['type'] == hikari.ComponentType.MEDIA_GALLERY
    assert 'FWA_Bases_Banner.jpg' in str(container['components'][0])
    action = registered_functions['fwa_bases_panel']
    assert action.no_return and not action.preload_state and not action.requires_state


def test_panel_menu_is_disabled_without_base_links(monkeypatch):
    monkeypatch.setattr(town_halls, '_snapshot', None)
    menu = panel_menu()
    assert menu['disabled'] and menu['custom_id'] == 'fwa_bases_panel:'


def selection(value):
    return NS(interaction=NS(values=[value]), respond=AsyncMock())


def test_selection_replies_privately_with_base_image_and_link_then_resets_panel(snapshot):
    ctx = selection('th19_new')
    asyncio.run(bases_panel.fwa_bases_panel(ctx=ctx))
    first, second = ctx.respond.await_args_list
    assert first.kwargs['ephemeral'] is True
    nodes = list(walk(built(first.kwargs['components'])))
    assert any(item.get('content') == '## Town Hall 19 Non-merged' for item in nodes)
    assert any(item['type'] == hikari.ComponentType.MEDIA_GALLERY for item in nodes)
    assert any(item['type'] == hikari.ComponentType.BUTTON and item.get('url') for item in nodes)
    assert not any('<@' in str(item.get('content', '')) for item in nodes)
    assert second.kwargs['edit'] is True and 'ephemeral' not in second.kwargs


def test_unavailable_selection_says_so_privately_and_resets_panel(snapshot):
    ctx = selection('th11')
    asyncio.run(bases_panel.fwa_bases_panel(ctx=ctx))
    first, second = ctx.respond.await_args_list
    assert first.args == ('This base is no longer available.',) and first.kwargs['ephemeral'] is True
    assert second.kwargs['edit'] is True


def test_th16_heading_has_no_emoji_without_registry(monkeypatch):
    monkeypatch.setattr(town_halls, '_snapshot', None)
    assert bases_panel.th16_note().startswith('**TH16 and higher**')
