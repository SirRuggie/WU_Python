import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import lightbulb
import linkd
import pytest

from utils import ticket_testing_context as scope
from utils.mongo import MongoClient


def test_action_prefix_is_idempotent_and_does_not_touch_modal_field_names():
    row = hikari.impl.MessageActionRowBuilder().add_interactive_button(hikari.ButtonStyle.PRIMARY, 'ticket_v2_console_view:abc', label='Open')
    container = hikari.impl.ContainerComponentBuilder(components=[row])
    marked = scope.prefix_components([container])
    assert marked[0].components[0].components[0].custom_id == 'tt|ticket_v2_console_view:abc'
    assert container.components[0].components[0].custom_id == 'ticket_v2_console_view:abc'
    assert scope.prefix_components(marked)[0].components[0].components[0].custom_id == 'tt|ticket_v2_console_view:abc'
    modal = hikari.impl.ModalActionRowBuilder().add_text_input('reason', 'Reason')
    result = scope.prefix_payload({'custom_id':'ticket_v2_custom_deny:abc','components':[modal]})
    assert result['custom_id'] == 'tt|ticket_v2_custom_deny:abc'
    assert result['components'][0].components[0].custom_id == 'reason'


def test_nested_dependencies_resolve_test_scope_and_restore_parent(monkeypatch):
    from extensions.commands.tickets import testing_service
    scoped = SimpleNamespace(is_ticket_test_scope=True)
    bot = SimpleNamespace(rest=SimpleNamespace())
    monkeypatch.setattr(testing_service,'test_bot',lambda _bot,_mongo:_bot)
    @lightbulb.di.with_di
    async def nested(mongo: MongoClient = lightbulb.di.INJECTED, app: hikari.GatewayBot = lightbulb.di.INJECTED):
        return mongo, app
    async def check():
        original = linkd.DI_CONTAINER.get(None)
        async with scope.test_dependencies(scoped,bot) as (_,testbot):
            db,app=await nested()
            assert db is scoped
            assert app is testbot
        assert linkd.DI_CONTAINER.get(None) is original
    asyncio.run(check())


def test_payload_never_enables_role_or_everyone_notifications():
    result=scope.prefix_payload({'role_mentions':True,'mentions_everyone':True,'user_mentions':[123]})
    assert result=={'role_mentions':False,'mentions_everyone':False,'user_mentions':[123]}


def test_non_ticket_action_cannot_enter_test_dispatch(monkeypatch):
    from extensions import components
    refused=AsyncMock()
    action=AsyncMock()
    monkeypatch.setattr(components,'_refuse',refused)
    monkeypatch.setattr(components,'_dispatch_impl',action)
    ctx=SimpleNamespace(interaction=SimpleNamespace(custom_id='tt|role_add:123'))
    asyncio.run(components._dispatch(ctx,SimpleNamespace()))
    refused.assert_awaited_once()
    action.assert_not_awaited()


def test_ordinary_controls_keep_production_routing(monkeypatch):
    from extensions import components
    action=AsyncMock()
    monkeypatch.setattr(components,'_dispatch_impl',action)
    mongo=SimpleNamespace()
    ctx=SimpleNamespace(interaction=SimpleNamespace(custom_id='ticket_v2_console_view:123'))
    asyncio.run(components._dispatch(ctx,mongo))
    action.assert_awaited_once_with(ctx,mongo)


def test_stale_test_window_controls_are_rejected_before_state_lookup(monkeypatch):
    from extensions import components
    from utils import ticket_testing_control
    scope_db = SimpleNamespace(tickets=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    monkeypatch.setattr(ticket_testing_control, 'require_test_access', AsyncMock(return_value=(scope_db, {'generation':'new'})))
    monkeypatch.setattr(components, '_resolve', lambda _: SimpleNamespace(is_modal=False,opens_modal=False))
    dispatch = AsyncMock()
    monkeypatch.setattr(components,'_dispatch_impl',dispatch)
    interaction=SimpleNamespace(custom_id='tt|ticket_v2_console_view:old',channel_id=12,app=object(),execute=AsyncMock())
    ctx=SimpleNamespace(interaction=interaction,defer=AsyncMock())
    asyncio.run(components._dispatch(ctx,object()))
    dispatch.assert_not_awaited()
    assert 'earlier test window' in interaction.execute.call_args.kwargs['content']
    assert scope_db.tickets.find_one.call_args.args[0]['window_generation']=='new'


def test_current_window_routes_state_and_nested_di_to_test_database(monkeypatch):
    from extensions import components
    from utils import ticket_testing_control
    from extensions.commands.tickets import testing_service
    scope_db=SimpleNamespace(is_ticket_test_scope=True,tickets=SimpleNamespace(find_one=AsyncMock(return_value={'mode':'test'})))
    monkeypatch.setattr(ticket_testing_control,'require_test_access',AsyncMock(return_value=(scope_db,{'generation':'new'})))
    monkeypatch.setattr(components,'_resolve',lambda _: SimpleNamespace(is_modal=False,opens_modal=False))
    monkeypatch.setattr(testing_service,'test_bot',lambda bot,_mongo:bot)
    seen=[]
    @lightbulb.di.with_di
    async def nested(mongo: MongoClient=lightbulb.di.INJECTED):
        return mongo
    async def dispatch(ctx,mongo):
        seen.append((ctx.interaction.custom_id,mongo,await nested(),ctx._test_already_deferred))
    monkeypatch.setattr(components,'_dispatch_impl',dispatch)
    interaction=SimpleNamespace(custom_id='tt|ticket_v2_console_view:new',channel_id=12,app=SimpleNamespace(rest=object()))
    ctx=SimpleNamespace(interaction=interaction,defer=AsyncMock())
    asyncio.run(components._dispatch(ctx,object()))
    assert seen==[('ticket_v2_console_view:new',scope_db,scope_db,True)]
