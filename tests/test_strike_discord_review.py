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


def test_component_bounds_hold_with_many_clans_and_five_weights():
    async def run():
        alphabet = '0289PYLQGRJCUV'
        tags = [f'#P{alphabet[i // len(alphabet)]}{alphabet[i % len(alphabet)]}' for i in range(30)]
        clans = [{'tag': value, 'name': f'Clan {index:02}', 'type': 'FWA'} for index, value in enumerate(tags)]
        rows = [{'player_tag': f'#R{i}', 'player_name': f'Player {i}', 'last_seen_clan_tag': tags[i % 30],
                 'current_clan_tag': tags[i % 30], 'active_strikes': 3, 'weight': 140000 + i * 100,
                 'replacement_priority': 'normal', 'town_hall': 15, 'member_id': 111222333444555666}
                for i in range(60)]
        class FullStore(Store):
            async def replacement(self, *args, **kwargs): return rows
        state = {'_id': 'a' * 32, 'guild_id': 123, 'clan_tags': [tags[0]], 'member_id': None,
                 'weights': [143000, 173000, 150000, 160000, 170000], 'page': 0, 'refresh_warning': True}
        with patch.object(strikes, 'cached_weights', lambda _tags: {}):
            panels = await strikes.replacement_panel(FullStore(clans), state, notice='Test notice')
        payload, attachments = panels[0].build()
        assert attachments == []
        children = payload['components']
        # Discord's Components V2 limit is 40 components in total, nested ones included.
        nested = sum(1 + len(c.get('components', [])) for c in children)
        assert 1 + nested <= 40 and len([c for c in children if c['type'].name == 'ACTION_ROW']) <= 5
        text = '\n'.join(c['content'] for c in children if c['type'].name == 'TEXT_DISPLAY')
        assert len(text) < 4000
        menu = next(c['components'][0] for c in children if c['type'].name == 'ACTION_ROW'
                    and c['components'][0]['type'].name == 'TEXT_SELECT_MENU')
        assert len(menu['options']) <= 25
        assert [o['value'] for o in menu['options'] if o.get('default')] == [tags[0]]
        for child in children:
            for item in child.get('components', []):
                assert len(item.get('custom_id', '')) <= 100
    asyncio.run(run())


def test_modal_submission_updates_private_source_panel_and_normalizes_several_weights():
    from unittest.mock import AsyncMock
    import hikari

    async def run():
        state = {'_id': 'token', 'guild_id': 123, 'weights': []}
        interaction = SimpleNamespace(message=object(),
            components=[[SimpleNamespace(custom_id='weight', value='143, 173k, 150000')]],
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
                                         {'$set': {'weights': [143000, 173000, 150000], 'page': 0}})
        assert state['weights'] == [143000, 173000, 150000]
        interaction.edit_initial_response.assert_awaited_once()
        assert interaction.edit_initial_response.await_args.kwargs['user_mentions'] is False
        ctx.defer.assert_not_awaited()
        ctx.respond.assert_not_awaited()
    asyncio.run(run())


def test_six_weights_are_rejected_without_saving():
    from unittest.mock import AsyncMock

    async def run():
        state = {'_id': 'token', 'guild_id': 123, 'weights': []}
        interaction = SimpleNamespace(message=object(),
            components=[[SimpleNamespace(custom_id='weight', value='1,2,3,4,5,6')]],
            create_initial_response=AsyncMock(), edit_initial_response=AsyncMock())
        ctx = SimpleNamespace(interaction=interaction, defer=AsyncMock(), respond=AsyncMock())
        updates = AsyncMock()
        render = AsyncMock(return_value=['panel'])
        with patch.object(strikes, '_replacement_action_state', AsyncMock(return_value=state)), \
             patch.object(strikes, 'update_state', updates), \
             patch.object(strikes, 'replacement_panel', render):
            await strikes.replacement_weight_submit(ctx, 'token', mongo=object())
        updates.assert_not_awaited()
        assert render.await_args.kwargs['notice'] == 'Enter up to 5 weights.'
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
        interaction.edit_initial_response.assert_not_awaited()
        assert ctx.respond.await_args.kwargs['ephemeral'] is True
    asyncio.run(run())


def test_other_member_cannot_replace_public_panel():
    from unittest.mock import AsyncMock
    async def run():
        ctx = SimpleNamespace(user=SimpleNamespace(id=2),
                              interaction=SimpleNamespace(guild_id=123), respond=AsyncMock())
        updates = AsyncMock()
        with patch.object(strikes, 'get_state', AsyncMock(return_value={
                'user_id': 1, 'guild_id': 123})), patch.object(strikes, 'update_state', updates):
            result = await strikes.replacement_clear(ctx, 'token', mongo=object())
        assert result is None
        updates.assert_not_awaited()
        assert ctx.respond.await_args.kwargs['ephemeral'] is True
    asyncio.run(run())


def test_removed_controls_have_no_handlers():
    for name in ('replacement_th', 'replacement_sort', 'replacement_clan_page'):
        assert not hasattr(strikes, name)


def test_replacement_command_responds_privately():
    from unittest.mock import AsyncMock
    async def run():
        ctx = SimpleNamespace(user=SimpleNamespace(id=1), guild_id=123,
                              defer=AsyncMock(), respond=AsyncMock())
        command = strikes.Replacements.__new__(strikes.Replacements)
        command.member = None
        with patch.object(strikes, 'authorized', AsyncMock(return_value=True)), \
             patch.object(strikes, 'insert_state', AsyncMock()), \
             patch.object(strikes, 'replacement_panel', AsyncMock(return_value=[])):
            await command.invoke(ctx, mongo=object(), coc_client=object())
        ctx.defer.assert_awaited_once_with(ephemeral=True)
        assert ctx.respond.await_args.kwargs['ephemeral'] is True
    asyncio.run(run())


def test_member_and_clan_selects_are_owner_only_and_save_validated_values():
    from unittest.mock import AsyncMock
    async def run():
        other = SimpleNamespace(user=SimpleNamespace(id=2), interaction=SimpleNamespace(guild_id=123, values=['99']),
                                respond=AsyncMock())
        updates = AsyncMock()
        with patch.object(strikes, 'get_state', AsyncMock(return_value={'user_id': 1, 'guild_id': 123})), \
             patch.object(strikes, 'update_state', updates):
            assert await strikes.replacement_member(other, 'token', mongo=object()) is None
        updates.assert_not_awaited()
        assert other.respond.await_args.kwargs['ephemeral'] is True
        owner = SimpleNamespace(user=SimpleNamespace(id=1),
                                interaction=SimpleNamespace(guild_id=123, values=['123456789012345678']),
                                respond=AsyncMock())
        state = {'_id': 'token', 'user_id': 1, 'guild_id': 123}
        with patch.object(strikes, 'get_state', AsyncMock(return_value=state)), \
             patch.object(strikes, 'authorized', AsyncMock(return_value=True)), \
             patch.object(strikes, 'update_state', updates), \
             patch.object(strikes, 'replacement_panel', AsyncMock(return_value=['ok'])):
            await strikes.replacement_member(owner, 'token', mongo=object())
        updates.assert_awaited_once_with(unittest_any(), 'token', {'$set': {'member_id': 123456789012345678, 'page': 0}})
    asyncio.run(run())


def unittest_any():
    from unittest.mock import ANY
    return ANY
