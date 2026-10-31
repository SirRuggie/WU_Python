"""Isolated UI sample: in-memory commands/history; no Discord transport or production data."""
import json
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import tour_deadline as fixture
from aiohttp import web
from utils.text_commands import validate

app = fixture.app
assert app['dev_fixture']
with app['store'].tx() as db:
    db.execute('INSERT OR REPLACE INTO grants(user_id,granted_by,permissions) VALUES(?,?,?)',(fixture.identity['id'],'fixture',json.dumps(['text_commands'])))
rows = {name: {**validate({'command':name,'text':'Welcome to the family.','blocks':[{'type':'text','text':'Read the rules before joining.'}]*6}),
                    'revision':'1','use_count':3,'last_used_at':datetime.now(timezone.utc).isoformat(),
                    'last_outcome':{'status':'error','at':datetime.now(timezone.utc).isoformat(),'channel_id':'111111111111111111','reason':'An image link was not found.'}}
        for name in ('!lazy','!rules')}
channels=[{'id':'111111111111111111','name':'general','type':0},{'id':'222222222222222222','name':'staff','type':0}]
roles=[{'id':'333333333333333333','name':'Member'},{'id':'444444444444444444','name':'Leader'}]
entries=[]

@web.middleware
async def sample(request, handler):
    path=request.path.removeprefix('/api/cwl')
    if path=='/manage/text-command-scope':return web.json_response({'channels':channels,'roles':roles})
    if path=='/manage/text-command-roles':return web.json_response({'roles':roles})
    if path=='/manage/text-command-test-channels':return web.json_response({'channels':channels})
    if path=='/manage/text-command-deleted':return web.json_response({'commands':[e['before']['command'] for e in entries if e['action']=='delete']})
    if path=='/manage/history':return web.json_response({'entries':entries})
    if path=='/manage/text-commands' and request.method=='GET':return web.json_response({'commands':list(rows.values())})
    if path.startswith('/manage/text-commands') and request.method in ('POST','PATCH','DELETE'):
        body=await request.json(); name=path.rsplit('/',1)[-1] if request.method!='POST' else body['values']['command']
        before=deepcopy(rows.get(name,{}))
        if request.method=='DELETE':rows.pop(name,None);after={}
        else:
            after={**body['values'],'revision':str(int(before.get('revision','0'))+1)};rows[name]=after
        entries.insert(0,{'id':str(len(entries)+1),'actor_name':'Fixture staff','at':datetime.now(timezone.utc).isoformat(),'action':'delete' if request.method=='DELETE' else 'edit','status':'saved','before':before,'after':after,'changed':['text']})
        return web.json_response(after or {'ok':True})
    if path=='/manage/text-command-test':raise web.HTTPForbidden(text='Fixture does not send Discord messages.')
    return await handler(request)

app.middlewares.insert(0,sample)
if __name__=='__main__':web.run_app(app,host='127.0.0.1',port=fixture.PORT)
