import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch
import pytest
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from utils import text_commands as core
from cwl_web import text_commands as api


def values(**kwargs):
    return dict(command='!cwl', enabled=True, text='Join CWL **today**', title='', description='', image_url='', color='#e2b332', **kwargs)


def test_validation_and_payload():
    row=core.validate(values())
    assert core.command_name(' !CWL ')=='!cwl'
    for name in ('cwl','!','!cwl now','hello !cwl','!cwl\n!help','!'+('x'*33)):
        with pytest.raises(ValueError): core.command_name(name)
    for update in ({'text':'x'*2001},{'text':'','enabled':False},{'enabled':'yes'},{'image_url':'http://example.com/a.png'},{'image_url':'https://127.0.0.1/a'},{'image_url':'https://name:secret@example.com/a'}):
        with pytest.raises(ValueError): core.validate({**values(),**update})
    result=core.payload({**row,'text':'@everyone <@123>'})
    assert result['mentions_everyone'] is False and result['role_mentions'] is False and result['user_mentions'] is False
    rendered=core.payload(core.validate({**values(),'title':'CWL','description':'Details','image_url':'https://example.com/card.png'}))
    assert 'embed' not in rendered and 'content' not in rendered
    assert int(rendered['flags'])==32768
    component=rendered['components'][-1].build()[0]
    assert component['type']==17 and component['components'][0]['content']=='## CWL'



def test_handler_exact_match_guild_bot_cooldown_and_same_channel():
    async def run():
        core._recent.clear()
        target=NS(find_one=AsyncMock(return_value=core.validate(values())))
        bot=NS(rest=NS(create_message=AsyncMock()))
        event=NS(guild_id=core.GUILD_ID, channel_id=123, message=NS(author=NS(is_bot=False),content='!CWL',webhook_id=None))
        with patch.object(core,'collection',return_value=target):
            assert await core.handle(event,None,bot)
            assert bot.rest.create_message.await_args.args==(123,)
            assert await core.handle(event,None,bot)
            assert bot.rest.create_message.await_count==1
            event.channel_id=124;event.message.content='a !cwl'
            assert not await core.handle(event,None,bot)
            event.message.content='!cwl';event.message.author.is_bot=True
            assert not await core.handle(event,None,bot)
            event.message.author.is_bot=False;event.guild_id=1
            assert not await core.handle(event,None,bot)
            event.guild_id=core.GUILD_ID;event.message.webhook_id=77
            assert not await core.handle(event,None,bot)
            event.message.webhook_id=None;target.find_one.return_value=None
            assert not await core.handle(event,None,bot)
            assert target.find_one.await_args.args[0]['enabled'] is True
            assert bot.rest.create_message.await_count==1
    asyncio.run(run())


def test_api_create_duplicate_stale_edit_and_delete():
    async def run():
        from contextlib import asynccontextmanager
        target=NS(find_one=AsyncMock(return_value={**values(),'revision':'original'}),insert_one=AsyncMock(), update_one=AsyncMock(return_value=NS(matched_count=1)),delete_one=AsyncMock(return_value=NS(deleted_count=1)))
        @asynccontextmanager
        async def mongo(request):
            from test_recruit_question_content import ConfigCollection
            yield NS(bot_config=ConfigCollection())
        req=NS(method='POST',json=AsyncMock(return_value={'values':values()}),match_info={'name':'!cwl'})
        with patch.object(api,'require_manage',AsyncMock(return_value={'user_id':'owner'})) as auth,patch.object(api,'mongo',mongo),patch.object(api,'collection',return_value=target):
            assert (await api.save(req)).status==201
            row=target.insert_one.await_args.args[0]
            assert row['_id']==f'{core.GUILD_ID}:!cwl' and row['updated_by']=='owner'
            auth.assert_awaited_with(req,'text_commands',write=True)
            target.insert_one.side_effect=DuplicateKeyError('duplicate')
            with pytest.raises(web.HTTPConflict):await api.save(req)
            req.method='PATCH';req.json.return_value={'values':values(),'revision':'original'}
            assert (await api.save(req)).status==200
            assert target.update_one.await_args.args[0]['revision']=='original'
            target.update_one.return_value=NS(matched_count=0)
            with pytest.raises(web.HTTPConflict):await api.save(req)
            req.json.return_value={'revision':'original'}
            assert (await api.delete(req)).status==200
            target.delete_one.return_value=NS(deleted_count=0)
            with pytest.raises(web.HTTPConflict):await api.delete(req)
            auth.side_effect=web.HTTPForbidden()
            with pytest.raises(web.HTTPForbidden):await api.save(req)
    asyncio.run(run())


def test_v2_blocks_order_links_separators_and_mentions():
    blocks=[{'type':'text','text':'## Heading <@123>'},{'type':'separator','divider':False,'spacing':2},{'type':'image','url':'https://example.com/image.png','description':'Clan badge'},{'type':'buttons','buttons':[{'label':'Sign up','url':'https://cwl.ruggie.zone/'}]}]
    clean=core.validate({**values(),'blocks':blocks,'allow_pings':True})
    result=core.payload(clean)
    assert all(result[key] is True for key in ('mentions_everyone','user_mentions','role_mentions'))
    assert result['components'][0].build()[0]['type']==10
    container=result['components'][1].build()[0]
    assert [part['type'] for part in container['components']]==[10,14,12,1]
    assert container['components'][1]['divider'] is False
    assert container['components'][1]['spacing']==2
    button=container['components'][3]['components'][0]
    assert button['style']==5 and button['url']=='https://cwl.ruggie.zone/' and button['label']=='Sign up'
    assert 'custom_id' not in button
    assert not core.payload(core.validate({**values(),'blocks':blocks}))['mentions_everyone']


@pytest.mark.parametrize('blocks',[
    [{'type':'unknown'}], [{'type':'text','text':''}], [{'type':'text','text':'a'*4001}],
    [{'type':'buttons','buttons':[]}], [{'type':'buttons','buttons':[{'label':'x','url':'javascript:alert(1)'}]}],
    [{'type':'buttons','buttons':[{'label':'x'*81,'url':'https://example.com'}]}],
    [{'type':'separator','spacing':True}], [{'type':'separator','divider':'yes'}],
    [{'type':'image','url':'https://127.0.0.1/a'}], [{'type':'text','text':'x','custom_id':'hack'}],
    [{'type':'separator'}]*16,
    [{'type':'buttons','buttons':[{'label':'x','url':'https://example.com'}]*5}]*7,
])
def test_v2_rejects_invalid_or_oversized_components(blocks):
    with pytest.raises(ValueError):core.validate({**values(),'blocks':blocks})


def test_total_text_limit_and_legacy_migration():
    with pytest.raises(ValueError):core.validate({**values(),'text':'a'*2000,'blocks':[{'type':'text','text':'b'*2001}]})
    old={**values(),'title':'Original title','description':'Original body','image_url':'https://example.com/image.png'}
    new=core.validate(old)
    assert new['blocks']==core.legacy_blocks(old)
    assert not new['allow_pings']
    assert core.validate(new)==new
    with pytest.raises(ValueError):core.validate({**values(),'allow_pings':'true'})


def test_mention_lookup_is_scoped_bounded_and_contains_only_names_ids():
 async def run():
  from cwl_web import manage_roles
  rows=[{'nick':'Sir Ruggie '+str(i),'user':{'id':str(i),'username':'person'+str(i)},'roles':['secret'],'joined_at':'private'} for i in range(30)]
  req=NS(query={'kind':'user','q':'rugg'})
  import json
  with patch.object(api,'require_manage',AsyncMock(return_value={'roles':[{'id':'7','name':'CWL Staff','permissions':'8'}]})) as auth,patch.object(manage_roles,'searchable_members',AsyncMock(return_value=rows)):
   result=json.loads((await api.mention_lookup(req)).text)
   assert len(result['matches'])==25
   assert all(set(row)=={'id','name'} for row in result['matches'])
   auth.assert_awaited_with(req,'text_commands')
   req.query={'kind':'role','q':'staff'}
   assert json.loads((await api.mention_lookup(req)).text)['matches']==[{'id':'7','name':'CWL Staff'}]
   req.query={'kind':'user','q':''}
   with pytest.raises(web.HTTPBadRequest):await api.mention_lookup(req)
   auth.side_effect=web.HTTPForbidden()
   with pytest.raises(web.HTTPForbidden):await api.mention_lookup(req)
 asyncio.run(run())


def test_named_gallery_and_sections_render_without_editor_metadata():
    blocks=[{'type':'text','name':'Title','text':'# Welcome'},
            {'type':'gallery','name':'Photos','items':[{'url':'https://example.com/a.png','description':'Clan badge','spoiler':True}]},
            {'type':'section','name':'Footer','texts':['-# Read more'], 'accessory':{'type':'button','label':'Open Clan','url':'https://example.com/clan'}}]
    clean=core.validate(values(blocks=blocks))
    assert clean['blocks'][0]['name']=='Title'
    components=core.payload(clean)['components'][-1].build()[0]['components']
    assert components[1]['items'][0]['spoiler'] is True
    assert components[2]['type']==9
    assert components[2]['accessory']['style']==5
    assert 'Title' not in str(components)
    blocks[2]['accessory']={'type':'thumbnail','url':'https://example.com/b.png','description':'Badge'}
    assert core.payload(core.validate(values(blocks=blocks)))['components'][-1].build()[0]['components'][2]['accessory']['type']==11


@pytest.mark.parametrize('block',[
 {'type':'text','text':'ok','name':'x'*81},
 {'type':'text','text':'ok','name':False},
 {'type':'gallery','items':[]},
 {'type':'gallery','items':[{'url':'https://example.com/a'}]*11},
 {'type':'gallery','items':[{'url':'https://127.0.0.1/a'}]},
 {'type':'section','texts':['a']*4,'accessory':{'type':'button','label':'Go','url':'https://example.com'}},
 {'type':'section','texts':['x'*4000],'accessory':{'type':'button','label':'Go','url':'https://example.com'}},
 {'type':'section','texts':['a'],'accessory':{'type':'button','label':'Go','url':'javascript:alert(1)'}},
])
def test_extended_blocks_reject_invalid_settings(block):
    with pytest.raises(ValueError):core.validate(values(blocks=[block]))
