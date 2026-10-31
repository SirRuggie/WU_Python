import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from utils import text_commands as core
from cwl_web.text_commands import validate_scope

CHANNEL = '111111111111111111'
ROLE = '222222222222222222'

@pytest.mark.parametrize('channels,roles,member_roles,allowed', [
    ([], [], [], True), ([CHANNEL], [ROLE], [ROLE], True),
    (['333333333333333333'], [], [], False), ([], [ROLE], [], False),
])
def test_scope_precedes_reply_delete_and_cooldown(channels, roles, member_roles, allowed):
    async def run():
        core._recent.clear()
        row = core.validate({'command':'!scope','text':'Reply',
                             'allowed_channel_ids':channels,'allowed_role_ids':roles})
        target = NS(find_one=AsyncMock(return_value=row), update_one=AsyncMock())
        rest = NS(create_message=AsyncMock(),delete_message=AsyncMock())
        event = NS(guild_id=core.GUILD_ID,channel_id=CHANNEL,message=NS(
            id=5,content='!scope',author=NS(id=7,is_bot=False),webhook_id=None,
            member=NS(role_ids=member_roles)))
        with patch.object(core,'collection',return_value=target),patch(
            'utils.text_command_files.load_files',AsyncMock(return_value={})):
            assert await core.handle(event,None,NS(rest=rest)) is allowed
        assert rest.create_message.await_count == int(allowed)
        assert rest.delete_message.await_count == int(allowed)
        assert bool(core._recent) is allowed
    asyncio.run(run())

@pytest.mark.parametrize('key', ['allowed_channel_ids','allowed_role_ids'])
@pytest.mark.parametrize('bad', [None, '123', [123], ['bad'], [CHANNEL]*101])
def test_scope_input_rejected(key,bad):
    with pytest.raises(ValueError):core.validate({'command':'!scope','text':'Reply',key:bad})


def test_scope_destination_and_managed_roles_rejected():
    async def run():
        actor={'roles':[{'id':ROLE,'managed':True}]}
        with pytest.raises(web.HTTPBadRequest):
            await validate_scope(None,actor,{'allowed_channel_ids':[],'allowed_role_ids':[ROLE]})
        with patch('cwl_web.server_management.discord',AsyncMock(return_value=[])):
            with pytest.raises(web.HTTPBadRequest):
                await validate_scope(None,actor,{'allowed_channel_ids':[CHANNEL],'allowed_role_ids':[]})
    asyncio.run(run())


def test_scope_choices_hide_managed_roles_and_foreign_channel_types():
    async def run():
        import json
        from cwl_web import text_commands as api
        actor={'roles':[{'id':ROLE,'name':'Members'},{'id':'333333333333333333','name':'Managed','managed':True},{'id':str(core.GUILD_ID),'name':'everyone'}]}
        channels=[{'id':CHANNEL,'name':'general','type':0},{'id':'444444444444444444','name':'voice','type':2}]
        auth=AsyncMock(return_value=actor)
        with patch.object(api,'require_manage',auth),patch('cwl_web.server_management.discord',AsyncMock(return_value=channels)):
            body=json.loads((await api.scope_options(None)).text)
        assert body['roles']==[{'id':ROLE,'name':'Members'}]
        assert body['channels']==[channels[0]]
        auth.assert_awaited_once_with(None,'text_commands')
    asyncio.run(run())


@pytest.mark.parametrize('parent,allowed', [(CHANNEL, True), ('999999999999999999', False), (None, False)])
def test_thread_inherits_allowed_parent(parent, allowed):
    from unittest.mock import Mock
    thread = NS(parent_id=parent) if parent else None
    cache = NS(get_thread=Mock(return_value=thread))
    row = core.validate({'command': '!scope', 'text': 'Reply', 'allowed_channel_ids': [CHANNEL]})
    event = NS(channel_id=444444444444444444)
    assert asyncio.run(core.within_scope(row, event, NS(cache=cache))) is allowed
    cache.get_thread.assert_called_once_with(event.channel_id)


@pytest.mark.parametrize('explicit_clear', [False, True])
def test_old_tab_preserves_scope_and_explicit_empty_clears(explicit_clear):
    from contextlib import asynccontextmanager
    import json
    from cwl_web import text_commands as api, change_history
    from test_text_commands import values

    async def run():
        prior = {**core.validate(values(allowed_channel_ids=[CHANNEL], allowed_role_ids=[ROLE])), 'revision': 'current'}
        target = NS(find_one=AsyncMock(return_value=prior), update_one=AsyncMock(return_value=NS(matched_count=1)))
        @asynccontextmanager
        async def database(_):
            yield NS()
        submitted = values()
        if explicit_clear:
            submitted.update(allowed_channel_ids=[], allowed_role_ids=[])
        request = NS(method='PATCH', match_info={'name': '!cwl'}, json=AsyncMock(return_value={'values': submitted, 'revision': 'current'}))
        finish = AsyncMock()
        with patch.object(api, 'require_manage', AsyncMock(return_value={'user_id': '1'})), patch.object(api, 'mongo', database), patch.object(api, 'collection', return_value=target), patch.object(change_history, 'begin', AsyncMock(return_value='h')), patch.object(change_history, 'finish', finish):
            result = json.loads((await api.save(request)).text)
        for key in ('allowed_channel_ids', 'allowed_role_ids'):
            expected = [] if explicit_clear else prior[key]
            assert result[key] == expected
            assert target.update_one.await_args.args[1]['$set'][key] == expected
            assert finish.await_args.args[2][key] == expected
    asyncio.run(run())
