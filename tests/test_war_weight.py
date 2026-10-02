import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hikari
import pytest
from pymongo.errors import DuplicateKeyError
from utils import war_weight as store
from extensions.commands.fwa import weight
from extensions.commands import fwa_weight_dashboard as ui


def run(coro):
    return asyncio.run(coro)


def test_minimum_filters_reference_not_calculation():
    config = store.defaults()
    config['minimum_th'] = 13
    text = weight.format_weight_reference_guide(130000, 13, config)
    assert '(TH12)' not in text and '(TH13)' in text and '(TH18)' in text
    assert weight.determine_town_hall(120000, store.ranges(config))[:2] == (12, 'exact')


def test_new_th_changes_bounds_gap_and_upgrade():
    config = store.edit_entry(store.defaults(), 19, 181000, 190000)
    ranges = store.ranges(config)
    assert weight.determine_town_hall(190000, ranges)[:2] == (19, 'exact')
    assert weight.determine_town_hall(190001, ranges)[1] == 'above'
    assert weight.determine_town_hall(180500, ranges)[:2] == (18, 'between')
    assert 'TH19' in weight.get_upgrade_info(180000, 18, ranges)
    assert '(TH19)' in weight.format_weight_reference_guide(185000, 19, config)


@pytest.mark.parametrize('th,low,high,emoji', [(19,180000,190000,''), (19,190000,180000,''), (19,0,190000,''), (100,181000,190000,''), (19,181000,500001,''), (19,181000,190000,'@everyone')])
def test_invalid_entries(th, low, high, emoji):
    with pytest.raises(ValueError):
        store.edit_entry(store.defaults(), th, low, high, emoji)


def test_named_emoji_and_fallback():
    config = store.edit_entry(store.defaults(), 19, 181000, 190000)
    emoji = hikari.CustomEmoji(id=123456789012345678, name='TH_19', is_animated=False)
    assert store.emoji_for(19, config, [emoji]) == str(emoji)
    assert store.emoji_for(19, config) == '🏛️'
    config['ranges']['19']['emoji'] = str(emoji)
    assert store.emoji_for(19, config) == str(emoji)


def test_save_rejects_stale_revision(monkeypatch):
    coll = SimpleNamespace(replace_one=AsyncMock(side_effect=DuplicateKeyError('duplicate')))
    monkeypatch.setattr(store, 'collection', lambda m: coll)
    with pytest.raises(ValueError, match='Someone changed'):
        run(store.save(object(), 1, store.defaults(), 2))


@pytest.mark.parametrize('change', ['user_id', 'guild_id', 'type', 'permission'])
def test_editor_checks_owner_guild_type_and_permission(monkeypatch, change):
    state = dict(type='war_weight_editor', user_id=1, guild_id=2)
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), interaction=SimpleNamespace(guild_id=2, member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR)))
    if change == 'permission':
        ctx.interaction.member.permissions = hikari.Permissions.NONE
    else:
        state[change] = 'wrong'
    monkeypatch.setattr(ui, 'get_state', AsyncMock(return_value=state))
    with pytest.raises(ValueError):
        run(ui.session(ctx, object(), 'token'))


def walk(node):
    if isinstance(node, list):
        for item in node:
            yield from walk(item)
    elif isinstance(node, dict):
        yield node
        for key in ('components', 'accessory'):
            if key in node:
                yield from walk(node[key])


def test_editor_builds_discord_payload(monkeypatch):
    monkeypatch.setattr(store, 'load', AsyncMock(return_value=store.defaults()))
    monkeypatch.setattr(ui, 'insert_state', AsyncMock())
    state = dict(type='war_weight_editor', user_id=1, guild_id=2, manage_token='x'*32)
    result = run(ui.panel(object(), state))
    nodes = list(walk([r.build()[0] for r in result]))
    assert len(nodes) <= 40
    assert all(len(n.get('custom_id', '')) <= 100 for n in nodes)
    assert all(len(n.get('options', [])) <= 25 for n in nodes)


def test_add_modal_builds(monkeypatch):
    state = dict(type='war_weight_editor', user_id=1, guild_id=2, manage_token='x', revision=0)
    monkeypatch.setattr(ui, 'session', AsyncMock(return_value=state))
    monkeypatch.setattr(ui, 'insert_state', AsyncMock())
    monkeypatch.setattr(store, 'load', AsyncMock(return_value=store.defaults()))
    ctx = SimpleNamespace(respond_with_modal=AsyncMock(), respond=AsyncMock())
    run(ui.show_modal(ctx, 'x', object(), add=True))
    kwargs = ctx.respond_with_modal.call_args.kwargs
    for row in kwargs['components']:
        built = row.build()[0]
        assert len(built['components'][0]['label']) <= 45


def test_calculator_uses_saved_settings(monkeypatch):
    config = store.edit_entry(store.defaults(), 19, 181000, 190000)
    config['minimum_th'] = 13
    monkeypatch.setattr(store, 'load', AsyncMock(return_value=config))
    ctx = SimpleNamespace(guild_id=2, channel_id=3, defer=AsyncMock(), interaction=SimpleNamespace(delete_initial_response=AsyncMock()))
    bot = SimpleNamespace(cache=SimpleNamespace(get_emojis_view=lambda: {}), rest=SimpleNamespace(create_message=AsyncMock()))
    run(weight.WeightCommand.invoke(SimpleNamespace(weight=38000), ctx, bot, object()))
    nodes = list(walk([r.build()[0] for r in bot.rest.create_message.call_args.kwargs['components']]))
    text = '\n'.join(n.get('content', '') for n in nodes)
    assert 'Town Hall 19' in text and 'TH13–TH19' in text
    assert '(TH12)' not in text
