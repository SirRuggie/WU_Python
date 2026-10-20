"""Discord replacement component bounds and clan-page navigation."""

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from extensions.commands import strikes


class Cursor:
    def __init__(self, rows): self.rows = rows
    async def to_list(self, length=None): return self.rows


class Collection:
    def __init__(self, rows): self.rows = rows
    def find(self, *args, **kwargs): return Cursor(self.rows)


class Store:
    def __init__(self, clans):
        self.mongo = SimpleNamespace(clans=Collection(clans), strike_profiles=Collection([]))
    async def replacement(self, *args, **kwargs): return []


def test_clan_page_moves_while_other_clan_remains_selected_and_component_bounds_hold():
    async def run():
        alphabet = '0289PYLQGRJCUV'
        tags = [f'#P{alphabet[i // len(alphabet)]}{alphabet[i % len(alphabet)]}' for i in range(30)]
        clans = [{'tag': value, 'name': f'Clan {index:02}'} for index, value in enumerate(tags)]
        state = {'_id': 'a' * 32, 'guild_id': 123, 'clan_tag': tags[0],
                 'town_hall': 4, 'weight': 149000, 'sort': 'priority',
                 'page': 0, 'clan_page': 1, 'refresh_warning': True}
        async def weights(_tags): return {}
        with patch.object(strikes, 'live_weights', weights):
            panels = await strikes.replacement_panel(Store(clans), state, notice='Test notice')
        payload, attachments = panels[0].build()
        assert attachments == []
        children = payload['components']
        assert len(children) <= 10
        menus = [child['components'][0] for child in children if child['type'].name == 'ACTION_ROW'
                 and child['components'][0]['type'].name == 'TEXT_SELECT_MENU']
        clan_menu = menus[0]
        options = clan_menu['options']
        assert len(options) <= 25
        assert tags[24] in [option['value'] for option in options]
        assert tags[0] not in [option['value'] for option in options]
        for child in children:
            for item in child.get('components', []):
                assert len(item['custom_id']) <= 100
    asyncio.run(run())


def test_modal_submission_updates_private_source_panel_and_normalizes_149():
    from unittest.mock import AsyncMock
    import hikari

    async def run():
        state = {'_id': 'token', 'guild_id': 123, 'weight': None}
        interaction = SimpleNamespace(message=object(),
            components=[[SimpleNamespace(custom_id='weight', value='149')]],
            create_initial_response=AsyncMock(), edit_initial_response=AsyncMock())
        ctx = SimpleNamespace(interaction=interaction, defer=AsyncMock(), respond=AsyncMock())
        updates = AsyncMock()
        mongo = object()
        render = AsyncMock(return_value=['private-panel'])
        with patch.object(strikes, '_replacement_action_state', AsyncMock(return_value=state)), \
             patch.object(strikes, 'update_state', updates), \
             patch.object(strikes, 'replacement_panel', render):
            await strikes.replacement_weight_submit(ctx, 'token', mongo=mongo)
        interaction.create_initial_response.assert_awaited_once_with(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        updates.assert_awaited_once_with(mongo, 'token',
                                         {'$set': {'weight': 149000, 'sort': 'weight', 'page': 0}})
        assert state['weight'] == 149000
        interaction.edit_initial_response.assert_awaited_once()
        ctx.defer.assert_not_awaited()
        ctx.respond.assert_not_awaited()
    asyncio.run(run())


def test_revoked_modal_actor_cannot_change_state_or_publish_result():
    from unittest.mock import AsyncMock
    import hikari

    async def run():
        interaction = SimpleNamespace(message=object(),
            components=[[SimpleNamespace(custom_id='weight', value='149')]],
            create_initial_response=AsyncMock(), edit_initial_response=AsyncMock())
        ctx = SimpleNamespace(interaction=interaction, defer=AsyncMock(), respond=AsyncMock())
        updates = AsyncMock()
        with patch.object(strikes, '_replacement_action_state', AsyncMock(return_value=None)), \
             patch.object(strikes, 'update_state', updates):
            await strikes.replacement_weight_submit(ctx, 'token', mongo=object())
        interaction.create_initial_response.assert_awaited_once_with(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
        updates.assert_not_awaited()
        interaction.edit_initial_response.assert_awaited_once()
        ctx.respond.assert_not_awaited()
    asyncio.run(run())
