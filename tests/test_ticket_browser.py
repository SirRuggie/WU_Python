import asyncio,json
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import ticket_browser as api

@pytest.fixture
def setup(monkeypatch):
 actor={'user_id':'123','role_ids':{42},'permissions':api.READ}
 row={'_id':'ticket_555','guild_id':api.GUILD_ID,'ticket_number':7,'ticket_type':'main','status':'approved','username':'Example','created_at':datetime.now(timezone.utc),'location':{'id':555,'staff_space_id':666}}
 class Cursor:
  def sort(self,*a):return self
  def skip(self,*a):return self
  def limit(self,*a):return self
  async def to_list(self,**kw):return [row]
 collection=NS(find_one=AsyncMock(return_value=row),find=lambda *a:Cursor())
 db=NS(tickets=collection)
 @asynccontextmanager
 async def mongo(_):yield db
 monkeypatch.setattr(api,'mongo',mongo)
 monkeypatch.setattr(api,'identity',AsyncMock(return_value=actor))
 monkeypatch.setattr(api,'allowed',AsyncMock(return_value=True))
 monkeypatch.setattr(api,'is_recruiter',AsyncMock(return_value=True))
 async def discord(req,method,path,**kw):
  assert method=='GET'
  if path.endswith('/messages'):return [{'id':'999','content':'Hello','author':{'username':'Example'},'timestamp':'2026-10-15T00:00:00Z'}]
  if path=='/channels/777':return {'id':'777','guild_id':str(api.GUILD_ID),'permission_overwrites':[]}
  if '/thread-members/' in path:return {'user_id':'123'}
  return {'id':path.split('/')[-1],'guild_id':str(api.GUILD_ID),'type':11,'parent_id':'777','thread_metadata':{'archived':True}}
 mock=AsyncMock(side_effect=discord);monkeypatch.setattr(api,'discord',mock)
 return NS(app={},query={},match_info={'ticket_id':'ticket_555'}),actor,db,mock

def test_archive_filters_escape_search_and_scope():
 q=api.filters({'q':'a.*','status':'closed','kind':'fwa','from':'2026-10-01','to':'2026-10-15'})
 assert q['guild_id']==api.GUILD_ID and q['runtime']
 assert q['status']=={'$in':['approved','denied','closed']}
 assert q['$or'][0]['username']['$regex']==r'a\.\*'
 assert q['created_at']['$lt'].day==16
 assert api.filters({'q':'9999999999999999999999'})['$or'][-1]=={'user_id':'9999999999999999999999'}
 for params in [{'status':'bad'},{'kind':'other'},{'from':'bad'},{'from':'2026-10-16','to':'2026-10-15'}]:
  with pytest.raises(web.HTTPBadRequest):api.filters(params)

def test_both_dashboard_scope_and_discord_recruiter_required(setup,monkeypatch):
 req,actor,db,discord=setup
 monkeypatch.setattr(api,'allowed',AsyncMock(return_value=False))
 with pytest.raises(web.HTTPForbidden):asyncio.run(api.conversation(req))
 db.tickets.find_one.assert_not_awaited();discord.assert_not_awaited()
 monkeypatch.setattr(api,'allowed',AsyncMock(return_value=True));monkeypatch.setattr(api,'is_recruiter',AsyncMock(return_value=False))
 with pytest.raises(web.HTTPForbidden):asyncio.run(api.listing(req))

def test_permission_overwrite_precedence():
 actor={'user_id':'123','role_ids':{42},'permissions':api.READ}
 parent={'permission_overwrites':[{'id':str(api.GUILD_ID),'type':0,'deny':api.READ,'allow':0},{'id':'42','type':0,'allow':api.READ,'deny':0},{'id':'123','type':1,'deny':1<<16,'allow':0}]}
 assert api.effective_permissions(actor,parent)&api.READ!=api.READ
 actor['permissions']=8
 assert api.effective_permissions(actor,parent)&8

def test_archived_messages_read_only_and_cached_after_authorization(setup,monkeypatch):
 req,actor,db,discord=setup
 first=json.loads(asyncio.run(api.conversation(req)).body)
 assert first['archived'] and first['messages'][0]['text']=='Hello'
 asyncio.run(api.conversation(req))
 assert sum(call.args[2].endswith('/messages') for call in discord.await_args_list)==1
 assert db.tickets.find_one.await_args.args[0]['guild_id']==api.GUILD_ID
 actor['permissions']=0
 with pytest.raises(web.HTTPForbidden):asyncio.run(api.conversation(req))
 assert sum(call.args[2].endswith('/messages') for call in discord.await_args_list)==1

def test_private_thread_membership_and_cross_guild(setup,monkeypatch):
 req,actor,db,discord=setup
 async def private(req,method,path,**kw):
  if '/thread-members/' in path:raise web.HTTPNotFound()
  if path=='/channels/777':return {'guild_id':str(api.GUILD_ID),'permission_overwrites':[]}
  return {'guild_id':str(api.GUILD_ID),'type':12,'parent_id':'777'}
 monkeypatch.setattr(api,'discord',AsyncMock(side_effect=private))
 with pytest.raises(web.HTTPForbidden):asyncio.run(api.conversation(req))
 monkeypatch.setattr(api,'discord',AsyncMock(return_value={'guild_id':'999','type':11,'parent_id':'777'}))
 with pytest.raises(web.HTTPForbidden):asyncio.run(api.conversation(req))

def test_missing_or_forged_ticket_cannot_read_arbitrary_thread(setup):
 req,actor,db,discord=setup
 req.match_info['ticket_id']='../../channels/999'
 with pytest.raises(web.HTTPNotFound):asyncio.run(api.conversation(req))
 discord.assert_not_awaited()
 req.match_info['ticket_id']='ticket_555';db.tickets.find_one.return_value=None
 with pytest.raises(web.HTTPNotFound):asyncio.run(api.conversation(req))
 discord.assert_not_awaited()

def test_message_shapes_and_unsafe_attachment_urls():
 msg=api.message_view({'id':'1','content':'Hi <@123>','mentions':[{'id':'123','username':'Member'}],'author':{'username':'Bot','bot':True},'components':[{'type':17,'components':[{'type':10,'content':'Card text'},{'type':1,'components':[{'type':2,'url':'https://example.com','label':'Guide'}]}]}], 'attachments':[{'filename':'bad','url':'javascript:alert(1)'},{'filename':'image.png','url':'https://cdn.discordapp.com/file.png'}], 'embeds':[{'title':'Title','description':'Description'}]})
 assert 'Hi @Member' in msg['text'] and 'Card text' in msg['text'] and 'Title' in msg['text']
 assert len(msg['attachments'])==2 and msg['bot']

def test_thread_choice_and_cursor_are_validated(setup):
 req,*_=setup
 for params in [{'space':'secret'},{'before':'not-an-id'}]:
  req.query=params
  with pytest.raises(web.HTTPBadRequest):asyncio.run(api.conversation(req))


def test_flew_the_coop_filter_and_text_search_are_identity_scoped():
    identities = {
        api.flag_store.FLAG_FLEW_THE_COOP: ([123456789012345678], ['#ABC123']),
    }
    filtered = api.filters({'flag': 'flew_the_coop'}, identities)
    assert filtered['$and'][0]['$or'] == [
        {'user_id': {'$in': [123456789012345678, '123456789012345678']}},
        {'player_tags': {'$in': ['#ABC123']}},
        {'playerTags': {'$in': ['#ABC123']}},
        {'player_tag': {'$in': ['#ABC123']}},
        {'tag': {'$in': ['#ABC123']}},
    ]
    searched = api.filters({'q': 'Flew the Coop'}, identities)
    assert searched['$or'][-5:] == filtered['$and'][0]['$or']
    with pytest.raises(web.HTTPBadRequest):
        api.filters({'flag': 'unknown'})


def test_public_ticket_includes_flag_reason_but_only_safe_summary_fields():
    ticket = api.public_ticket(
        {'_id': 'ticket_555', 'ticket_number': 7, 'username': 'Example', 'user_id': 123,
         'ticket_type': 'main', 'status': 'approved'},
        [{'kind': api.flag_store.FLAG_FLEW_THE_COOP, 'active': True,
          'reason': 'Left after applying', 'discord_ids': [123], 'added_by': 999}],
    )
    assert ticket['status'] == 'approved'
    assert ticket['flags'] == [{'kind': 'flew_the_coop', 'label': 'Flew the Coop', 'reason': 'Left after applying'}]
    assert 'discord_ids' not in ticket['flags'][0]
    assert 'added_by' not in ticket['flags'][0]
