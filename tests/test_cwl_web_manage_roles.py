"""Role changes validate the whole selection before issuing any Discord write."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from dashboard_access_fakes import AccessCollection
from cwl_web import manage_roles as roles


def test_one_forbidden_role_prevents_entire_selection():
    async def scenario():
        actor = {'user_id':'111111111111111111','roles':[{'id':'333333333333333333','name':'allowed','position':1}, {'id':'444444444444444444','name':'forbidden','position':99}], 'guild':{'owner_id':'999999999999999999'}, 'member':{'user':{'id':'111111111111111111'},'roles':[]}}
        request = NS(app={'server_management_mongo':NS(bot_config=AccessCollection())},match_info={'action':'add'}, json=AsyncMock(return_value={'values':{'member_id':'222222222222222222','role_ids':['333333333333333333','444444444444444444']}}))
        async def read(_request, method, path, **kwargs):
            assert method == 'GET', 'No writes are permitted before the full selection is checked'
            if path == '/users/@me':
                return {'id':'555555555555555555'}
            return {'user':{'id':path.rsplit('/',1)[-1]},'roles':[]}
        with patch.object(roles,'require_manage',AsyncMock(return_value=actor)), patch.object(roles,'discord',AsyncMock(side_effect=read)), patch.object(roles.perms,'actor_can_manage_member',return_value=True), patch.object(roles,'role_is_manageable',side_effect=lambda _g,_b,r:r.position < 99), patch.object(roles.perms,'actor_can_manage_role',return_value=True):
            with pytest.raises(web.HTTPForbidden):
                await roles.change(request)
    asyncio.run(scenario())


def test_target_hierarchy_blocks_even_if_roles_are_manageable():
    async def scenario():
        actor={'user_id':'111111111111111111','roles':[], 'guild':{'owner_id':'999999999999999999'}, 'member':{'user':{'id':'111111111111111111'},'roles':[]}}
        request=NS(app={'server_management_mongo':NS(bot_config=AccessCollection())},match_info={'action':'remove'},json=AsyncMock(return_value={'values':{'member_id':'222222222222222222','role_ids':['333333333333333333']}}))
        async def read(_request,method,path,**kwargs):
            assert method=='GET'
            return {'id':'555555555555555555'} if path=='/users/@me' else {'user':{'id':path.rsplit('/',1)[-1]},'roles':[]}
        with patch.object(roles,'require_manage',AsyncMock(return_value=actor)),patch.object(roles,'discord',AsyncMock(side_effect=read)),patch.object(roles.perms,'actor_can_manage_member',return_value=False):
            with pytest.raises(web.HTTPForbidden):
                await roles.change(request)
    asyncio.run(scenario())


def test_member_browse_pagination_and_profile_data():
    async def scenario():
        import json
        data=[{'user':{'id':str(222222222222222222+i),'username':'player','global_name':'Global','avatar':'abc'},'nick':'Server name','roles':['333333333333333333']} for i in range(50)]
        api=AsyncMock(return_value=data)
        request=NS(query={})
        with patch.object(roles,'require_manage',AsyncMock(return_value={'roles':[{'id':'333333333333333333','name':'Managed role'}]})),patch.object(roles,'discord',api):
            result=json.loads((await roles.members(request)).text)
            assert result['mode']=='browse' and result['next']==data[-1]['user']['id']
            assert result['options'][0]['display_name']=='Server name'
            assert result['options'][0]['role_ids']==['333333333333333333']
            assert result['options'][0]['role_names']==['Managed role']
            assert result['options'][0]['avatar_url'].startswith('https://cdn.discordapp.com/avatars/')
            assert api.call_args.kwargs['params']=={'limit':'50'}
            request.query={'after':result['next']}
            api.return_value=[]
            result=json.loads((await roles.members(request)).text)
            assert result['next'] is None
            assert api.call_args.kwargs['params']['after']==data[-1]['user']['id']
    asyncio.run(scenario())


def test_member_search_single_character_truncation_and_exact_lookup():
    async def scenario():
        import json
        row={'user':{'id':'222222222222222222','username':'player'},'roles':[]}
        api=AsyncMock(return_value=[{**row, 'user': {**row['user'], 'id': str(222222222222222222+i)}} for i in range(101)])
        request=NS(query={'q':'p'},app={})
        with patch.object(roles,'require_manage',AsyncMock(return_value={})),patch.object(roles,'discord',api):
            result=json.loads((await roles.members(request)).text)
            assert result['mode']=='search' and result['truncated'] and result['next'] is None
            assert api.call_args.kwargs['params']=={'limit':'1000'}
            api.return_value=row
            request.query={'id':row['user']['id']}
            result=json.loads((await roles.members(request)).text)
            assert result['mode']=='member' and len(result['options'])==1
            assert result['options'][0]['avatar_url'].startswith('https://cdn.discordapp.com/embed/avatars/')
            request.query={'q':row['user']['id']}
            assert json.loads((await roles.members(request)).text)['mode']=='member'
    asyncio.run(scenario())


def test_member_lookup_validation_and_forbidden_errors():
    async def scenario():
        api=AsyncMock(side_effect=web.HTTPForbidden())
        with patch.object(roles,'require_manage',AsyncMock(return_value={})),patch.object(roles,'discord',api):
            for query in ({'q':'a'*81},{'after':'nope'},{'q':'a','after':'222222222222222222'},{'id':'123'}):
                with pytest.raises(web.HTTPBadRequest):await roles.members(NS(query=query))
            api.assert_not_awaited()
            with pytest.raises(web.HTTPForbidden) as error:
                await roles.members(NS(query={}))
            assert 'Server Members Intent' in error.value.text
        api.reset_mock()
        with patch.object(roles,'require_manage',AsyncMock(side_effect=web.HTTPForbidden())),patch.object(roles,'discord',api):
            with pytest.raises(web.HTTPForbidden):await roles.members(NS(query={}))
            api.assert_not_awaited()
    asyncio.run(scenario())


def test_role_change_accepts_uuid_and_repeated_add_is_skipped():
    async def scenario():
        import json
        target='222222222222222222';selected='333333333333333333'
        actor={'user_id':'111111111111111111','roles':[{'id':selected,'name':'Member','position':1}], 'guild':{'owner_id':'999999999999999999'},'member':{'user':{'id':'111111111111111111'},'roles':[]}}
        body={'request_id':'5e20fa01-2494-4a19-b0c5-b2ecf527b657','values':{'member_id':target,'role_ids':[selected]}}
        request=NS(app={'server_management_mongo':NS(bot_config=AccessCollection())},match_info={'action':'add'},json=AsyncMock(return_value=body))
        current=[];writes=[]
        async def api(_request,method,path,**kwargs):
            if method=='PUT':
                writes.append(path);current.append(selected);return None
            if path=='/users/@me':return {'id':'555555555555555555'}
            uid=path.rsplit('/',1)[-1]
            return {'user':{'id':uid},'roles':list(current) if uid==target else []}
        with patch.object(roles,'require_manage',AsyncMock(return_value=actor)),patch.object(roles,'discord',api),patch.object(roles.perms,'actor_can_manage_member',return_value=True),patch.object(roles,'role_is_manageable',return_value=True),patch.object(roles.perms,'actor_can_manage_role',return_value=True):
            assert json.loads((await roles.change(request)).text)['changed']==['Member']
            assert json.loads((await roles.change(request)).text)['skipped']==['Member']
            assert len(writes)==1
            body['request_id']='not a uuid'
            with pytest.raises(web.HTTPBadRequest):await roles.change(request)
            assert len(writes)==1
    asyncio.run(scenario())


def test_page_only_offers_roles_actor_and_bot_can_manage():
    async def scenario():
        import json
        import hikari
        everyone=str(roles.GUILD_ID)
        actor_top='111111111111111112';bot_top='555555555555555556'
        allowed='333333333333333333';managed='444444444444444444'
        higher='666666666666666666';privileged='777777777777777777'
        permissions=int(hikari.Permissions.MANAGE_ROLES)
        all_roles=[{'id':everyone,'name':'everyone','position':0},
            {'id':actor_top,'name':'Staff','position':10,'permissions':permissions},
            {'id':bot_top,'name':'Bot','position':8,'permissions':permissions},
            {'id':allowed,'name':'Member','position':1},
            {'id':managed,'name':'Integration','position':1,'managed':True},
            {'id':higher,'name':'High','position':12},
            {'id':privileged,'name':'Admin','position':2,'permissions':int(hikari.Permissions.ADMINISTRATOR)}]
        actor={'user_id':'111111111111111111','roles':all_roles,'guild':{'owner_id':'999999999999999999'},'member':{'user':{'id':'111111111111111111'},'roles':[actor_top]}}
        async def api(_request,method,path,**kwargs):
            assert method=='GET'
            return {'id':'555555555555555555'} if path=='/users/@me' else {'user':{'id':'555555555555555555'},'roles':[bot_top]}
        with patch.object(roles,'require_manage',AsyncMock(return_value=actor)),patch.object(roles,'discord',api):
            result=json.loads((await roles.page(NS())).text)
        member_field,role_field=result['fields']
        assert role_field['options']==[{'value':allowed,'label':'Member'}]
        assert {r['value'] for r in member_field['current_role_options']}=={actor_top,bot_top,allowed,managed,higher,privileged}
    asyncio.run(scenario())


def test_substring_search_checks_all_names_and_reuses_complete_directory():
    async def scenario():
        import json
        first = [{'user': {'id': str(222222222222222222+i), 'username': f'player{i}'}, 'roles': []} for i in range(1000)]
        last = [
            {'user': {'id': '333333333333333331', 'username': 'other'}, 'nick': 'Sir Ruggie', 'roles': []},
            {'user': {'id': '333333333333333332', 'username': 'another', 'global_name': 'The RUGGIE account'}, 'roles': []},
            {'user': {'id': '333333333333333333', 'username': 'my_ruggie_alt'}, 'roles': []},
        ]
        transport = AsyncMock(side_effect=[first, last])
        request = NS(query={'q':'uGg'}, app={})
        with patch.object(roles,'require_manage',AsyncMock(return_value={})), patch.object(roles,'discord',transport):
            result=json.loads((await roles.members(request)).text)
            assert len(result['options']) == 3 and not result['truncated']
            assert transport.await_count == 2
            assert transport.await_args.kwargs['params']['after'] == first[-1]['user']['id']
            request.query = {'q': 'ruggie'}
            assert len(json.loads((await roles.members(request)).text)['options']) == 3
            assert transport.await_count == 2
            request.app['member_search_directory']['loaded_at'] -= 61
            transport.side_effect = [[]]
            assert json.loads((await roles.members(request)).text)['options'] == []
    asyncio.run(scenario())


def test_failed_directory_load_does_not_cache_partial_results():
    async def scenario():
        from aiohttp import web
        page=[{'user':{'id':str(222222222222222222+i),'username':'player'},'roles':[]} for i in range(1000)]
        request=NS(app={})
        with patch.object(roles,'discord',AsyncMock(side_effect=[page,web.HTTPServiceUnavailable()])):
            with pytest.raises(web.HTTPServiceUnavailable): await roles.searchable_members(request)
        assert 'rows' not in request.app['member_search_directory']
    asyncio.run(scenario())
