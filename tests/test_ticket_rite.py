import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.tickets import rite, setup, surface
from utils.constants import GOLDENROD_ACCENT


def context(user=1):
    return SimpleNamespace(user=SimpleNamespace(id=user),member=SimpleNamespace(role_ids=()),
        guild_id=10,channel_id=20,defer=AsyncMock(),respond=AsyncMock(),
        interaction=SimpleNamespace(message=SimpleNamespace(id=30),edit_initial_response=AsyncMock()))


def test_public_panel_has_one_path_gateway_and_my_ticket():
    panel=setup.create_public_ticket_embed()[0]
    assert panel.accent_color==GOLDENROD_ACCENT
    assert [x.custom_id for x in panel.components[-1].components]==['ticket_v2_rite_open','ticket_v2_my_ticket']
    assert surface.THREAD_PUBLIC_PANEL_ACTIONS=={'ticket_v2_rite_open'}
    private=rite.path_panel('session')[0]
    rows=[c for c in private.components if c.type==hikari.ComponentType.ACTION_ROW]
    assert [r.components[0].custom_id for r in rows]==['ticket_v2_rite_choose:session:main','ticket_v2_rite_choose:session:fwa']
    assert 'Rite_of_Passage.jpg' in str(private.components[-1].items[0].media)


def test_gateway_is_private_and_remembers_authorized_original_message(monkeypatch):
    ctx=context(); mongo=object()
    gate=AsyncMock(return_value=SimpleNamespace(allowed=True,route='thread'))
    save=AsyncMock()
    monkeypatch.setattr(rite.ticket_runtime,'route_public_intake',gate)
    monkeypatch.setattr(rite,'insert_state',save)
    asyncio.run(rite.open_paths(ctx=ctx,mongo=mongo))
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    assert gate.call_args.kwargs['message_id']==30
    state=save.call_args.args[1]
    assert (state['owner_id'],state['source_message_id'])==(1,30)
    ctx.interaction.edit_initial_response.assert_awaited_once()


@pytest.mark.parametrize('kind',['main','fwa'])
def test_choice_reuses_normal_intake_with_original_source(monkeypatch,kind):
    ctx=context();ctx.interaction.message.id=999
    state={'type':'ticket_rite_paths','owner_id':1,'guild_id':10,'channel_id':20,'source_message_id':30}
    monkeypatch.setattr(rite,'get_state',AsyncMock(return_value=state))
    create=AsyncMock();monkeypatch.setattr(rite.handlers,'handle_create_ticket',create)
    asyncio.run(rite.choose_path(ctx=ctx,action_id='session:'+kind,mongo=object(),bot=object()))
    assert create.call_args.kwargs['_source_message_id']==30
    assert create.call_args.kwargs['action_id']=='public:'+kind


@pytest.mark.parametrize('state',[None,{'type':'ticket_rite_paths','owner_id':2,'guild_id':10,'channel_id':20}])
def test_expired_or_other_members_chooser_cannot_create_ticket(monkeypatch,state):
    ctx=context();monkeypatch.setattr(rite,'get_state',AsyncMock(return_value=state))
    create=AsyncMock();monkeypatch.setattr(rite.handlers,'handle_create_ticket',create)
    asyncio.run(rite.choose_path(ctx=ctx,action_id='session:main',mongo=object(),bot=object()))
    create.assert_not_awaited()
    assert ctx.respond.call_args.kwargs['ephemeral'] is True
