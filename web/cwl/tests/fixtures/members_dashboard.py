"""Disconnected full-app Members sample: 1,448 people, memory-only role actions."""
import asyncio
from copy import deepcopy
from pathlib import Path
import sys
from aiohttp import web
sys.path.insert(0, str(Path(__file__).parent))
import member_timezone_dashboard as zones
from utils.member_timezones import COUNTRY_CHOICES, ZONE_CHOICES, SINGLE_ZONE, flag, zones_for_country
fixture = zones.fixture
members = zones.members
members.append(dict(discord_id='123456789013999999',name='Last fixture person',nickname=None,bot=False,status='Missing',profile=None,parsed=None,skip_reason=None))
assert len(members) == 1448
roles = [dict(id=str(333333333333333330+i),name=f'Fixture role {i}'+(' with a long readable name' if i==2 else '')) for i in range(1,21)]
for index, person in enumerate(members):
    person['username'] = f'fixture_user_{index}'
    person['role_ids'] = [roles[index%len(roles)]['id']] if index%3 else []
state = dict(review=None,run=None)
BASE='/api/cwl/manage/members'

def directory():
    return dict(members=members,roles=roles,manageable_roles=roles,
        countries=[dict(code=c,label=n,flag=flag(c),zone_id=SINGLE_ZONE.get(c),zones=[dict(id=k,label=k.upper()+' · '+text) for k,_,text in zones_for_country(c)]) for c,n in COUNTRY_CHOICES],
        zones=[dict(id=z,label=z.upper()+' · '+n) for z,_,n in ZONE_CHOICES],permission='member_roles')

@web.middleware
async def sample(request, handler):
    if not request.path.startswith(BASE):return await handler(request)
    fixture.requests.append(dict(method=request.method,path=request.path))
    if zones.state['denied']:return web.json_response({'error':'Fixture access revoked'},status=403)
    if request.path==BASE:return web.json_response(directory())
    body=await request.json() if request.can_read_body else {}
    if request.path==BASE+'/role-preview':
        selected=body.get('member_ids',[]);role=next((r for r in roles if r['id']==body.get('role_id')),None)
        if not role or not selected or len(set(selected))!=len(selected) or any(not any(m['discord_id']==i and not m['bot'] for m in members) for i in selected):return web.json_response({'error':'Invalid sample selection'},status=400)
        state['review']=dict(token='disconnected-review',selected=selected,count=len(selected),role=dict(role,protected=role==roles[-1]),operation=body['operation'])
        return web.json_response(state['review'])
    if request.path==BASE+'/role-confirm':
        review=state['review']
        if not review or body.get('token')!=review['token'] or body.get('selected')!=review['selected']:return web.json_response({'error':'Review sample selection again'},status=409)
        state['run']=dict(run_id='disconnected-role-run',state='queued',started_by=members[0]['discord_id'],rows=[dict(discord_id=i,status='waiting',message='',changed=False,role_id=review['role']['id'],operation=review['operation'],expected_role_ids=deepcopy(next(m for m in members if m['discord_id']==i)['role_ids'])) for i in review['selected']])
        return web.json_response(dict(run_id=state['run']['run_id'],state='queued'))
    if request.path==BASE+'/role-runs':return web.json_response(dict(runs=[dict(run_id=state['run']['run_id'])] if state['run'] and state['run']['state']=='queued' else []))
    if request.path==BASE+'/role-runs/disconnected-role-run/stop' and state['run']:
        state['run']['state']='stopped'
        for row in state['run']['rows']:
            if row['status']=='waiting':row.update(status='stopped',message='Stopped before this person started.')
        return web.json_response(dict(run_id=state['run']['run_id'],state='stopped'))
    if request.path==BASE+'/role-runs/disconnected-role-run' and state['run']:return web.json_response(state['run'])
    return web.json_response({'error':'Unsupported disconnected action'},status=400)

fixture.app.middlewares.insert(0,sample)
if __name__=='__main__':asyncio.run(fixture.main())
