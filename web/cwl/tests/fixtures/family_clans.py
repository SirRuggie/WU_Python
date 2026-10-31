"""25-clan loopback UI fixture. All management responses are synthetic."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(os.environ['WU_FIXTURE_BACKEND'])
sys.path[:0] = [str(ROOT), str(Path(__file__).parent)]
import qa_network_guard
from aiohttp import web
from cwl_web import create_app

PORT = int(sys.argv[2])
assert PORT == 0 or 8900 <= PORT <= 8999
folder = tempfile.TemporaryDirectory(prefix='wu-family-', dir=os.environ['HOME'])
app = create_app(db_path=folder.name+'/fixture.sqlite', dev_fixture=True,
                 secure_cookies=False, static_dir=Path(sys.argv[1]))
alphabet = '0289PYLQGRJCUV'
clans = [dict(tag='#P'+alphabet[i//13]+alphabet[i%13]+'Y', name=f'Example clan {i+1:02}',
              type='FWA' if i < 10 else 'CWL', revision=str(i), logo='', banner='',
              leader_id='123456789012345678', leader_role_id='223456789012345678',
              role_id='', chat_channel_id='323456789012345678', announcement_id='',
              rules_channel_id='', leadership_channel_id='', thread_id='', profile='',
              emoji='', th_requirements='16') for i in range(25)]
channels = [{'id':'323456789012345678', 'name':'war-chat', 'type':0}]
def reminders(index):
    return dict(settings=dict(enabled=index<2, channel_id=channels[0]['id'] if index<2 else '',
                              minutes=[60], audience='remaining', war_started=True),
                revision='reminder-'+str(index), history=[], status={})
@web.middleware
async def fixture(request, handler):
    path = request.path
    if not path.startswith('/api/cwl/manage/'):
        return await handler(request)
    if request.method == 'POST' and path.endswith('/war-reminders/preview'):
        return web.json_response({'messages':[{'content':'Sample war reminder · 1h left'}]})
    if request.method != 'GET':
        return web.json_response({'error':'UI fixture: writes disabled'}, status=403)
    if path.endswith('/clan-choices'):
        return web.json_response({'roles':[{'id':'223456789012345678','name':'Clan leaders','managed':False,'position':3,'color':5793266}], 'channels':channels})
    if path.endswith('/clan-members'):
        return web.json_response({'members':[{'id':'123456789012345678','name':'Example leader','avatar_url':None}], 'more':False})
    if path.endswith('/clan-history'):
        return web.json_response({'events':[{'id':'fixture','action':'Before this change','at':datetime.now(timezone.utc).isoformat(),'actor':'Example staff','source':'Dashboard','clan':clans[0], 'present':True,'can_restore':False,'changes':[{'field':'Leader role','before':'Old leaders','after':'Clan leaders'}]}], 'more':False})
    if path.endswith('/clans'):
        return web.json_response({'clans':clans,'types':['FWA','CWL','Tactical','Flexible Fun'], 'town_halls':['16','17','18']})
    if path.endswith('/war-reminders/overview'):
        return web.json_response({'generated_at':datetime.now(timezone.utc).isoformat(),'clans':[{'clan':clan, **reminders(i), 'health':{'category':'healthy' if i<2 else 'off','label':'Ready' if i<2 else 'Off','detail':''},'checked_at':None,'last_delivery':None} for i,clan in enumerate(clans)]})
    if path.endswith('/usage'):
        return web.json_response({'links':[{'label':'Strikes tracking','href':'/clans/strikes'}]})
    if path.endswith('/war-reminders'):
        clan_tag = path.split('/')[-2]
        index = next((i for i,c in enumerate(clans) if c['tag']==clan_tag), 0)
        return web.json_response(reminders(index))
    return web.json_response({'error':'Fixture route not implemented'}, status=404)
app.middlewares.insert(0, fixture)
async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', PORT)
    await site.start()
    print(json.dumps({'ready':True,'port':runner.addresses[0][1]}), flush=True)
    await asyncio.Event().wait()
if __name__ == '__main__':
    asyncio.run(main())
