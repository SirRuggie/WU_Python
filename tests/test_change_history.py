import asyncio,json,copy
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock,patch
import pytest
from aiohttp import web
from cwl_web import change_history as history, manage_content as content, server_management as shared
from test_cwl_web_manage_content import db


def test_edit_restore_stale_and_cross_target_protection():
 async def run():
  mongo=db()
  @asynccontextmanager
  async def database(_):yield mongo
  auth=AsyncMock(return_value={'user_id':'123','member':{'nick':'Staff name'}})
  request=NS(match_info={'item':'question--attack_strategies'},method='PATCH',path='/save',json=AsyncMock(return_value={'revision':0,'values':{'sections.0':'Updated heading {recruit}'}}))
  with patch.object(shared,'mongo',database),patch.object(shared,'require_manage',auth),patch.object(history,'mongo',database),patch.object(history,'require_manage',auth):
   saved=json.loads((await content.item_handler(request)).text)
   row=next(row for row in mongo.bot_config.rows.values() if row.get('kind')=='dashboard_history')
   assert row['status']=='saved' and row['actor_name']=='Staff name'
   assert row['before']!=row['after']
   restore=NS(query={'target':row['target']},json=AsyncMock(return_value={'id':row['_id'],'side':'before','revision':saved['revision']}))
   restored=json.loads((await history.restore(restore)).text)
   assert restored['revision']==2
   assert history.fields(restored)==row['before']
   assert len([r for r in mongo.bot_config.rows.values() if r.get('action')=='restore'])==1
   with pytest.raises(web.HTTPConflict):await history.restore(restore)
   restore.query['target']='/api/cwl/manage/content/war--win'
   with pytest.raises(web.HTTPNotFound):await history.restore(restore)
   auth.side_effect=web.HTTPForbidden()
   with pytest.raises(web.HTTPForbidden):await history.restore(restore)
 asyncio.run(run())


def test_before_image_failure_prevents_mutation_and_preview_never_journals():
 async def run():
  mongo=db();original_insert=mongo.bot_config.insert_one
  @asynccontextmanager
  async def database(_):yield mongo
  req=NS(match_info={'item':'question--attack_strategies'},method='POST',path='/preview',json=AsyncMock(return_value={'revision':0,'values':{'sections.0':'New {recruit}'}}))
  with patch.object(shared,'mongo',database),patch.object(shared,'require_manage',AsyncMock(return_value={'user_id':'1'})):
   await content.item_handler(req)
   assert not mongo.bot_config.rows
   mongo.bot_config.insert_one=AsyncMock(side_effect=RuntimeError('history unavailable'))
   req.method='PATCH';req.path='/save'
   with pytest.raises(RuntimeError):await content.item_handler(req)
   assert not mongo.bot_config.rows
   mongo.bot_config.insert_one=original_insert
 asyncio.run(run())


def test_incomplete_record_cannot_restore_and_unknown_actions_rejected():
 async def run():
  mongo=db()
  @asynccontextmanager
  async def database(_):yield mongo
  target='/api/cwl/manage/content/war--win'
  token=await history.begin(mongo,target,{'user_id':'1'},{'a':'before'})
  req=NS(query={'target':target},json=AsyncMock(return_value={'id':token,'side':'before','revision':0}))
  with patch.object(history,'mongo',database),patch.object(history,'require_manage',AsyncMock()):
   with pytest.raises(web.HTTPNotFound):await history.restore(req)
  mongo.bot_config.update_one=AsyncMock(return_value=NS(matched_count=0))
  with pytest.raises(RuntimeError):await history.finish(mongo,token,{'a':'after'})
 asyncio.run(run())
 for target in ['/manage/roles','/manage/ticket-settings/tools','/manage/operations/fwa_weight/new','/manage/text-commands/!bad/name']:
  with pytest.raises(web.HTTPBadRequest):history.target_info(target)


def test_ticket_restore_preserves_request_id_and_checks_current_permission():
 async def run():
  from cwl_web import manage_tickets
  mongo=db()
  @asynccontextmanager
  async def database(_):yield mongo
  target='/api/cwl/manage/ticket-settings/timers'
  token=await history.begin(mongo,target,{'user_id':'1'},{'ticket_inactivity_minutes':10080})
  await history.finish(mongo,token,{'ticket_inactivity_minutes':1440})
  req=NS(query={'target':target},json=AsyncMock(return_value={'id':token,'side':'before','revision':'current','request_id':'idempotent'}))
  save=AsyncMock(return_value=web.json_response({'status_url':'/test'}))
  auth=AsyncMock()
  with patch.object(history,'mongo',database),patch.object(history,'require_manage',auth),patch.object(manage_tickets,'save',save):
   await history.restore(req)
   proxy=save.await_args.args[0]
   assert await proxy.json()=={'revision':'current','values':{'ticket_inactivity_minutes':10080},'request_id':'idempotent'}
   auth.assert_awaited_with(req,'ticket_settings',write=True)
 asyncio.run(run())


def test_deleted_staff_section_can_be_restored():
 async def run():
  from test_cwl_dashboard_integration import MemoryCollection
  mongo=db();mongo.ticket_staff_templates=MemoryCollection()
  @asynccontextmanager
  async def database(_):yield mongo
  auth=AsyncMock(return_value={'user_id':'1'})
  req=NS(match_info={'item':'staff--main','action':'add'},method='POST',path='/add',json=AsyncMock(return_value={'revision':0}))
  with patch.object(shared,'mongo',database),patch.object(shared,'require_manage',auth),patch.object(history,'mongo',database),patch.object(history,'require_manage',auth):
   added=json.loads((await content.item_handler(req)).text)
   action=next(a for a in added['actions'] if a['id'].startswith('remove-'))
   req.match_info['action']=action['id'];req.json.return_value={'revision':1}
   removed=json.loads((await content.item_handler(req)).text)
   row=next(r for r in mongo.bot_config.rows.values() if r.get('action')==action['id'])
   restore=NS(query={'target':row['target']},json=AsyncMock(return_value={'id':row['_id'],'side':'before','revision':removed['revision']}))
   restored=json.loads((await history.restore(restore)).text)
   assert history.fields(restored)==history.fields(added)
 asyncio.run(run())


def test_text_command_restore_keeps_name_and_uses_current_revision():
 async def run():
  from cwl_web import text_commands
  from test_text_commands import values
  mongo=db();original=values();current={**original,'text':'New reply','revision':'current'}
  target=NS(find_one=AsyncMock(return_value=current),update_one=AsyncMock(return_value=NS(matched_count=1)))
  @asynccontextmanager
  async def database(_):yield mongo
  auth=AsyncMock(return_value={'user_id':'1'})
  token=await history.begin(mongo,'/api/cwl/manage/text-commands/!cwl',{'user_id':'1'},original)
  await history.finish(mongo,token,{k:v for k,v in current.items() if k!='revision'})
  req=NS(query={'target':'/manage/text-commands/%21cwl'},json=AsyncMock(return_value={'id':token,'side':'before','revision':'current'}))
  with patch.object(history,'mongo',database),patch.object(history,'require_manage',auth),patch.object(text_commands,'mongo',database),patch.object(text_commands,'require_manage',auth),patch.object(text_commands,'collection',return_value=target):
   result=json.loads((await history.restore(req)).text)
   assert result['text']==original['text'] and result['command']=='!cwl'
   assert target.update_one.await_args.args[0]['revision']=='current'
   assert result['revision']!='current'
 asyncio.run(run())


def test_ticket_worker_journals_success_and_never_confirms_failed_write():
 async def run():
  from utils import manage_web_worker as worker
  from extensions.commands.tickets import settings
  mongo=db();cfg={'_id':'config','ticket_inactivity_minutes':10080,'ticket_archive_quiet_days':1}
  mongo.ticket_setup=NS(find_one=AsyncMock(side_effect=lambda _:copy.deepcopy(cfg)))
  ctx=NS(member=NS(display_name='Ticket staff'));bot=NS(rest=object())
  row={'section':'ticket_settings','action':'save','values':{'ticket_archive_quiet_days':2},'revision':content.fingerprint(cfg),'user_id':'1','history_action':'restore'}
  async def save(*args):cfg['ticket_archive_quiet_days']=2;return 'Saved'
  with patch.object(settings,'save',save):await worker.dispatch(bot,mongo,row,ctx)
  entry=next(iter(mongo.bot_config.rows.values()))
  assert entry['status']=='saved' and entry['action']=='restore'
  assert entry['before']['ticket_archive_quiet_days']==1 and entry['after']['ticket_archive_quiet_days']==2
  row['revision']=content.fingerprint(cfg)
  with patch.object(settings,'save',AsyncMock(side_effect=ValueError('validation failed'))):
   with pytest.raises(ValueError):await worker.dispatch(bot,mongo,row,ctx)
  assert [r['status'] for r in mongo.bot_config.rows.values()]==['saved','pending']
 asyncio.run(run())


def test_native_message_history_uses_same_target_and_can_restore():
 async def run():
  from utils.dashboard_native_history import save_message
  from utils import recruit_question_content as questions
  mongo=db();key='attack_strategies';item=content.descriptor('question--'+key)
  before=await content.load(mongo,item);changed=copy.deepcopy(before);changed['sections'][0]='Native change {recruit}'
  await save_message(questions.save_template,'question',mongo,content.GUILD_ID,key,changed,0,123)
  entry=next(r for r in mongo.bot_config.rows.values() if r.get('kind')=='dashboard_history')
  assert entry['action']=='discord_edit' and entry['status']=='saved'
  assert entry['target']=='/api/cwl/manage/content/question--attack_strategies'
  @asynccontextmanager
  async def database(_):yield mongo
  auth=AsyncMock(return_value={'user_id':'456'})
  req=NS(query={'target':entry['target']},json=AsyncMock(return_value={'id':entry['_id'],'side':'before','revision':1}))
  with patch.object(history,'mongo',database),patch.object(history,'require_manage',auth),patch.object(shared,'mongo',database),patch.object(shared,'require_manage',auth):
   result=json.loads((await history.restore(req)).text)
  assert history.fields(result)==history.fields(content.schema(item,before))
  assert len([r for r in mongo.bot_config.rows.values() if r.get('kind')=='dashboard_history'])==2
 asyncio.run(run())
