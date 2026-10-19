import asyncio,copy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import hikari,pytest
from utils import text_commands as core,text_command_actions as actions,text_command_files as files


def clean(blocks,**extra):return core.validate(dict(command='!menu',blocks=blocks,**extra))
def reply():return {'label':'More','action':{'kind':'reply','command':'!more'}}

def test_separate_cards_and_limits():
    row=clean([{'type':'text','text':'Before'}, {'type':'container','color':'#123456','spoiler':True,'blocks':[{'type':'text','text':'Card'}]}, {'type':'text','text':'After'}])
    parts=[c.build()[0] for c in core.payload(row)['components']]
    assert len(parts)==3 and parts[1]['accent_color']==0x123456 and parts[1]['spoiler']
    assert core.component_count(row['blocks'])==6
    with pytest.raises(ValueError):clean([{'type':'container','blocks':[{'type':'container','blocks':[{'type':'text','text':'no'}]}]}])
    with pytest.raises(ValueError):clean([{'type':'container','blocks':[{'type':'text','text':'x'*3000}]},{'type':'text','text':'y'*1001}])
    with pytest.raises(ValueError):clean([{'type':'actions','buttons':[reply()]*5}]*7)


def test_unique_controls_and_dropdown_values():
    row=clean([{'type':'container','blocks':[{'type':'actions','buttons':[reply(),reply()]},{'type':'select','options':[reply(),{**reply(),'label':'Other'}]}]}])
    parts=core.payload(row)['components'][0].build()[0]['components']
    buttons=parts[0]['components'];menu=parts[1]['components'][0]
    ids=[b['custom_id'] for b in buttons]+[menu['custom_id']]
    assert len(set(ids))==3 and max(map(len,ids))<=100
    assert [o['value'] for o in menu['options']]==['0','1']
    with pytest.raises(ValueError):clean([{'type':'select','options':[reply(),reply()]}])
    with pytest.raises(ValueError):clean([{'type':'select','options':[reply()]*26}])


def test_files_match_attachment_names_and_budget():
    file={'type':'file','file_id':'a'*64,'filename':'guide.txt','size':5,'spoiler':True}
    row=clean([file,file]);built=core.payload(row,{'a'*64:b'hello'})
    parts=built['components'][0].build()[0]['components']
    assert parts[0]['file']['url']=='attachment://0-guide.txt'
    assert parts[1]['file']['url']=='attachment://1-guide.txt'
    assert [f.filename for f in built['attachments']]==['0-guide.txt','1-guide.txt']
    with pytest.raises(ValueError):clean([{**file,'size':5*1024*1024}]*2)
    with pytest.raises(ValueError):clean([file]*11)
    with pytest.raises(ValueError):clean([{**file,'filename':'../secret'}])


def test_file_store_is_bounded_content_addressed_and_checked():
    async def run():
        coll=NS(update_one=AsyncMock(),find_one=AsyncMock())
        with patch.object(files,'collection',return_value=coll):
            first=await files.store_file(None,b'hello','../guide.txt','123')
            assert first['filename']=='guide.txt'
            assert first==await files.store_file(None,b'hello','guide.txt','123')
            assert coll.update_one.await_args.kwargs['upsert']
            for data in (b'',b'x'*(files.MAX_BYTES+1)):
                with pytest.raises(ValueError):await files.store_file(None,data,'a','123')
            row=clean([{'type':'file',**first}]);coll.find_one.return_value={**first,'data':b'hello'}
            assert await files.load_files(None,row)=={first['file_id']:b'hello'}
            coll.find_one.return_value={**first,'data':b'bad'}
            with pytest.raises(ValueError):await files.load_files(None,row)
            coll.find_one.return_value=None
            with pytest.raises(ValueError):await files.load_files(None,row,metadata_only=True)
    asyncio.run(run())


def interaction(row,path='0.0',select=False):
    return NS(custom_id='ct:!menu:'+core.fingerprint(row)+':'+path,guild_id=core.GUILD_ID,member=object(),application_id=7,message=NS(author=NS(id=7)),component_type=hikari.ComponentType.TEXT_SELECT_MENU if select else hikari.ComponentType.BUTTON,values=['0'],create_initial_response=AsyncMock(),edit_initial_response=AsyncMock(),execute=AsyncMock(),delete_initial_response=AsyncMock())


def test_actions_private_no_pings_stale_disabled_forged_and_missing():
    async def run():
        row=clean([{'type':'actions','buttons':[reply()]}]);target=core.validate(dict(command='!more',text='@everyone Hello',allow_pings=True))
        coll=NS(find_one=AsyncMock(side_effect=[row,target]))
        with patch.object(actions,'collection',return_value=coll):
            click=interaction(row);assert await actions.handle(click,None)
            args=click.execute.await_args.kwargs
            assert args['flags'] & hikari.MessageFlag.EPHEMERAL and args['flags'] & hikari.MessageFlag.IS_COMPONENTS_V2
            assert args['mentions_everyone'] is False and args['user_mentions'] is False
            click.delete_initial_response.assert_awaited_once()
            coll.find_one.side_effect=None
            for stored,foreign in [(None,False),({**row,'text':'Changed'},False),(row,True)]:
                coll.find_one.return_value=stored;click=interaction(row)
                if foreign:click.message.author.id=9
                await actions.handle(click,None);click.execute.assert_not_awaited();click.edit_initial_response.assert_awaited_once()
            coll.find_one.side_effect=[row,None];click=interaction(row);await actions.handle(click,None);click.execute.assert_not_awaited()
            coll.find_one.side_effect=[row];click=interaction(row,'99.99');await actions.handle(click,None);click.execute.assert_not_awaited()
    asyncio.run(run())


def test_select_resolves_only_configured_option():
    async def run():
        row=clean([{'type':'select','options':[reply()]}]);target=core.validate(dict(command='!more',text='Hi'))
        coll=NS(find_one=AsyncMock(side_effect=[row,target]))
        with patch.object(actions,'collection',return_value=coll):
            click=interaction(row,'0',True);await actions.handle(click,None);click.execute.assert_awaited_once()
            coll.find_one.side_effect=[row];click=interaction(row,'0',True);click.values=['999'];await actions.handle(click,None);click.execute.assert_not_awaited()
    asyncio.run(run())


def test_roles_only_change_clicker_and_record_with_live_permissions():
    from utils import text_command_roles as role_core
    async def run():
        me=NS(id=7);author=NS(id=12,role_ids=[]);target=NS(id=99,role_ids=[])
        everyone=NS(id=core.GUILD_ID,position=0,permissions=hikari.Permissions.NONE,is_managed=False,name='everyone')
        assignable=NS(id=123456789012345678,position=1,permissions=hikari.Permissions.NONE,is_managed=False,name='CWL alerts')
        bot_role=NS(id=8,position=10,permissions=hikari.Permissions.MANAGE_ROLES,is_managed=False,name='Bot')
        rest=NS(fetch_roles=AsyncMock(return_value=[everyone,assignable,bot_role]),fetch_guild=AsyncMock(return_value=NS(owner_id=1)),fetch_my_user=AsyncMock(return_value=me),fetch_member=AsyncMock(side_effect=lambda guild,uid:{7:NS(id=7,role_ids=[8]),12:author,99:target}[uid]),add_role_to_member=AsyncMock(),remove_role_from_member=AsyncMock())
        events=NS(insert_one=AsyncMock(),update_one=AsyncMock())
        db=NS(bot_config=NS(find_one=AsyncMock(return_value={'permissions':['text_commands']}),database=NS(get_collection=lambda *a,**k:events)),ticket_setup=NS(find_one=AsyncMock(return_value={})))
        click=NS(id=1,app=NS(rest=rest),user=NS(id=99));row={'command':'!role','updated_by':'12'};action={'kind':'add_role','role_id':str(assignable.id)}
        assert 'added' in await role_core.perform(click,db,row,action)
        assert rest.add_role_to_member.await_args.args==(core.GUILD_ID,99,assignable.id)
        assert events.insert_one.await_args.args[0]['configured_by']=='12'
        assert events.update_one.await_args.args[1]['$set']['status']=='done'
        target.role_ids=[assignable.id]
        await role_core.perform(click,db,row,action)
        assert rest.add_role_to_member.await_count==1 # idempotent
        await role_core.perform(click,db,row,{**action,'kind':'remove_role'})
        assert rest.remove_role_from_member.await_args.args==(core.GUILD_ID,99,assignable.id)
        for change in ('privilege','hierarchy','managed','revoked','staff'):
            assignable.permissions=hikari.Permissions.NONE;assignable.position=1;assignable.is_managed=False
            db.bot_config.find_one.return_value={'permissions':['text_commands']};db.ticket_setup.find_one.return_value={}
            if change=='privilege':assignable.permissions=hikari.Permissions.ADMINISTRATOR
            if change=='hierarchy':assignable.position=11
            if change=='managed':assignable.is_managed=True
            if change=='revoked':db.bot_config.find_one.return_value={}
            if change=='staff':db.ticket_setup.find_one.return_value={'main_recruiter_role':assignable.id}
            with pytest.raises(ValueError):await role_core.perform(click,db,row,action)
        assert rest.add_role_to_member.await_count==1
    asyncio.run(run())


def test_dispatch_routes_trigger_controls_without_touching_other_handlers():
    async def run():
        from extensions import components
        handler=AsyncMock(return_value=True)
        with patch.object(actions,'handle',handler):
            ctx=NS(interaction=NS(custom_id='ct:!menu:version:0'))
            await components._dispatch(ctx,'database')
            handler.assert_awaited_once_with(ctx.interaction,'database')
    asyncio.run(run())


def test_upload_requires_editor_before_reading_body_and_enforces_cap():
    from cwl_web import text_commands as api
    from aiohttp import web
    async def run():
        request=NS(content_length=files.MAX_BYTES+1)
        with patch.object(api,'require_manage',AsyncMock(side_effect=web.HTTPForbidden())):
            with pytest.raises(web.HTTPForbidden):await api.upload_file(request)
        with patch.object(api,'require_manage',AsyncMock(return_value={'user_id':'123'})):
            with pytest.raises(web.HTTPRequestEntityTooLarge):await api.upload_file(request)
    asyncio.run(run())
