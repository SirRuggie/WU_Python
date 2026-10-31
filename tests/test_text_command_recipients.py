import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import pytest,hikari
from utils import text_commands as core

def command(**kw):return core.validate(dict(command='!hello',text='Welcome @everyone <@999>',choose_recipient=True,recipient_ping=True,**kw))

def test_recipient_payload_allows_only_selected_recipient():
 for kind in ('user','role'):
  row=command(allow_pings=False); data=core.payload(row,recipient=(kind,123))
  assert data['mentions_everyone'] is False
  assert data['user_mentions']==([123] if kind=='user' else False)
  assert data['role_mentions']==([123] if kind=='role' else False)
  assert data['components'][0].build()[0]['content']==('<@123>' if kind=='user' else '<@&123>')
  assert all(component.build()[0]['type'] != 17 for component in data['components'])
  data=core.payload({**row,'recipient_ping':False},recipient=(kind,123))
  assert data['user_mentions']==([123] if kind=='user' else False)
  assert data['role_mentions']==([123] if kind=='role' else False)

def test_old_button_fingerprint_is_preserved():
 import hashlib,json
 row=core.validate(dict(command='!old',text='hello'))
 historical_fields=('command','enabled','text','title','description','image_url',
                    'color','blocks','allow_pings')
 old={key:row.get(key) for key in historical_fields}
 expected=hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()[:16]
 assert core.fingerprint(row)==expected
 assert core.fingerprint({**row,'delete_trigger':False})==expected
 with pytest.raises(ValueError):core.validate(dict(command='!bad',text='hi',choose_recipient='yes'))
 with pytest.raises(ValueError):core.validate(dict(command='!bad',blocks=[{'type':'text','text':'x'*3990}],choose_recipient=True))




def test_prefix_requires_inline_recipient_without_sending_saved_reply():
 async def run():
  core._recent.clear(); row=command();event=NS(guild_id=core.GUILD_ID,channel_id=8,message=NS(content='!hello',author=NS(id=7,is_bot=False),webhook_id=None))
  bot=NS(rest=NS(create_message=AsyncMock()))
  with patch.object(core,'collection',return_value=NS(find_one=AsyncMock(return_value=row))):
   await core.handle(event,None,bot);assert bot.rest.create_message.await_args.kwargs['content']=='Use !hello @person or !hello @role.'
 asyncio.run(run())

@pytest.mark.parametrize('saved_ping',[False,True])
@pytest.mark.parametrize('chosen_ping',[False,True])
@pytest.mark.parametrize('kind',['user','role'])
def test_saved_and_chosen_pings_are_independent(saved_ping,chosen_ping,kind):
 row=command(allow_pings=saved_ping)
 row['recipient_ping']=chosen_ping
 row['text']='Hello <@999> <@&888> @everyone'
 data=core.payload(row,recipient=(kind,123))
 users=([999] if saved_ping else [])+([123] if kind=='user' else [])
 roles=([888] if saved_ping else [])+([123] if kind=='role' else [])
 assert data['user_mentions']==(sorted(users) or False)
 assert data['role_mentions']==(sorted(roles) or False)
 assert data['mentions_everyone'] is saved_ping

def test_recipient_is_inside_existing_embed():
 row=command(blocks=[{'type':'text','text':'Welcome'}])
 data=core.payload(row,recipient=('user',123))
 card=data['components'][-1].build()[0]
 assert card['type']==17
 assert card['components'][0]['content']=='<@123>'
 assert card['components'][1]['content']=='Welcome'
 assert data['user_mentions']==[123]

@pytest.mark.parametrize('kind',['user','role'])
def test_inline_recipient_delivers_embed_without_picker(kind):
 async def run():
  core._recent.clear()
  row=command(blocks=[{'type':'text','text':'Hello'}])
  mention='<@&123>' if kind=='role' else '<@123>'
  event=NS(guild_id=core.GUILD_ID,channel_id=8,message=NS(id=555,content='!hello '+mention,author=NS(id=7,is_bot=False),webhook_id=None))
  rest=NS(create_message=AsyncMock(),delete_message=AsyncMock(),fetch_member=AsyncMock(),fetch_roles=AsyncMock(return_value=[NS(id=123,is_mentionable=True)]))
  with patch.object(core,'collection',return_value=NS(find_one=AsyncMock(return_value=row))),patch('utils.text_command_files.load_files',AsyncMock(return_value={})):
   assert await core.handle(event,None,NS(rest=rest))
   assert rest.create_message.await_count==1
   rest.delete_message.assert_awaited_once_with(8,555)
   data=rest.create_message.await_args.kwargs
   assert data['components'][-1].build()[0]['components'][0]['content']==mention
   assert data['role_mentions' if kind=='role' else 'user_mentions']==[123]
 asyncio.run(run())

@pytest.mark.parametrize('send_fails',[False,True])
def test_trigger_cleanup_never_deletes_before_delivery_or_resends(send_fails):
 async def run():
  core._recent.clear(); row=command()
  event=NS(guild_id=core.GUILD_ID,channel_id=8,message=NS(id=555,content='!hello <@123>',author=NS(id=7,is_bot=False),webhook_id=None))
  operations=[]
  async def send(*a,**kw):
   operations.append('send')
   if send_fails:raise RuntimeError('delivery failed')
  async def delete(*a,**kw):
   operations.append('delete');raise RuntimeError('permission denied')
  rest=NS(create_message=AsyncMock(side_effect=send),delete_message=AsyncMock(side_effect=delete),fetch_member=AsyncMock())
  with patch.object(core,'collection',return_value=NS(find_one=AsyncMock(return_value=row))),patch('utils.text_command_files.load_files',AsyncMock(return_value={})):
   await core.handle(event,None,NS(rest=rest))
  assert operations==(['send'] if send_fails else ['send','delete'])
  assert rest.create_message.await_count==1
 asyncio.run(run())
