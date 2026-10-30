"""Native CWL return snapshots, distinct from signup placement rosters."""
from urllib.parse import quote
from aiohttp import web
from .server_management import API, mongo, require_manage, queue_action
from .manage_content import fingerprint
from utils import lazy_cwl_store as store
from utils import return_reminder_settings
from utils.return_reminder_status import return_status
from .providers import tag


async def page(request):
    await require_manage(request,'cwl_rosters')
    pool=request.match_info.get('pool'); clan_tag=request.match_info.get('tag')
    async with mongo(request) as db:
        if not pool:
            clans=await db.clans.find({'type':{'$in':['FWA','Tactical','Flexible Fun','Competitive','CWL']}}).to_list(length=201)
            if len(clans)>200:raise web.HTTPServiceUnavailable(text='Clan directory is too large. Use search in Discord for now.')
            documents=[
                dict(id='return-channels',label='Settings · Return channels',endpoint='/manage/return-channels'),
                dict(id='return-history',label='Results · Recent group actions',endpoint='/manage/return-batches'),
            ]
            from .manage_return_bulk import LABELS
            documents.extend(dict(id='return-bulk-'+operation,label='Multiple clans · '+label,endpoint='/manage/return-bulk/'+operation) for operation,label in LABELS.items() if operation != 'schedule')
            for section in ('MAIN','FWA'):
                active=await store.list_active(db,section=section)
                saved={r['clan_tag']:r for r in active}
                available={r['clan_tag']:r.get('clan_name',r['clan_tag']) for r in active}
                for clan in clans:
                    if (section=='FWA') == (clan.get('type')=='FWA'):
                        available[tag(clan['tag'])]=clan.get('name') or clan['tag']
                for clan,name in sorted(available.items(),key=lambda item:item[1].casefold()):
                    documents.append({'id':section+clan,'return_section':section,'clan_tag':clan,'clan_name':name,'label':f'{name} · {section}', 'return_status':return_status(saved.get(clan),section), 'endpoint':f'/manage/return-reminders/{section}/{quote(clan,safe="")}'})
            return web.json_response({'id':'cwl_rosters','label':'CWL return reminders','description':'Saved home-clan members. These are separate from CWL signup placements.','group':'War','revision':'index','fields':[],'documents':documents})
        try:pool=store.normalize_section(pool);clan_tag=tag(clan_tag)
        except ValueError as exc:raise web.HTTPBadRequest(text='Choose a valid clan.') from exc
        current=await store.get_active(db,clan_tag,section=pool)
        destination=await return_reminder_settings.destination(db,pool)
    base=f'/manage/return-reminders/{pool}/{quote(clan_tag,safe="")}'
    def f(key,label,value,kind='text',**kw):return dict(key=key,label=label,value=value,type=kind,**kw)
    fields=[f('clan_tag','Clan tag',clan_tag,readonly=True),f('section','Home clan type',pool,readonly=True),f('destination','Return channel',str(destination),'channel',readonly=True)]
    actions=[('save','Save current clan members','Save the clan’s current members as its return list?')]
    if current:
        players=current.get('players',[])
        if isinstance(players,dict):players=list(players.values())
        fields.extend([f('player_tag','Add player tag',''),f('player_tags','Saved players to remove',[],'multiselect',options=[{'value':p['tag'],'label':f"{p.get('name') or p['tag']} · {p['tag']}"} for p in players]),f('every_minutes','Reminder interval (minutes)',(current.get('reminders') or {}).get('every_minutes') or 60,'select',options=[{'value':'30','label':'Every 30 minutes'},{'value':'60','label':'Every hour'},{'value':'120','label':'Every 2 hours'}])])
        actions=[('away','Check who is away','Check current clan locations? No reminders are sent.'),('add','Add player','Add this player to the saved list?'),('remove','Remove selected players','Remove these players from the return list?'),('send','Send return reminder now','Send a Discord return reminder for this clan now?'),('replace','Replace saved list','Replace this list with current clan members? The previous list’s reminders stop.'),('clear','Close saved list','Close this saved list and stop its reminders?')]
        if pool=='FWA':actions[4:4]=[('start','Start return reminders','Start now with the selected interval? This can send Discord messages immediately and replaces any future start. Earlier stop limits remain.'),('pause','Pause reminders','Pause this clan’s return reminders?'),('resume','Resume reminders','Resume reminders? This does not restart the seven-day limit.')]
    return web.json_response({'id':pool+clan_tag,'label':(current or {}).get('clan_name') or clan_tag,'description':'Manage the home-clan return list.','group':'War','revision':fingerprint(current),'fields':fields,'action_only':True,
        'return_status':return_status(current,pool),
        'warning':f"{len((current or {}).get('players',[]))} saved players. Main reminders are manual. FWA reminders stop after seven days or at the seasonal cutoff.",
        'actions':[dict(id=k,label=l,confirm=c,advanced=k in ('replace','clear','add','remove'),endpoint=base+'/actions/'+k) for k,l,c in actions]})


async def action(request):
    await require_manage(request,'cwl_rosters',write=True)
    body=await request.json()
    if not isinstance(body,dict) or not isinstance(body.get('values',{}),dict):raise web.HTTPBadRequest()
    values=dict(body.get('values',{}))
    try:
        values['clan_tag']=tag(request.match_info['tag']); values['section']=store.normalize_section(request.match_info['pool'])
        if request.match_info['action']=='add':values['player_tag']=tag(values.get('player_tag'))
        if request.match_info['action']=='remove':
            selected=values.get('player_tags')
            if not isinstance(selected,list) or not 1<=len(selected)<=50:raise ValueError('Select 1 to 50 players.')
            values['player_tags']=[tag(x) for x in selected]
        if request.match_info['action'] in ('start','resume'):
            interval=int(values.get('every_minutes',60))
            if interval not in (30,60,120):raise ValueError('Choose 30 minutes, 1 hour, or 2 hours.')
            values['every_minutes']=interval
            if values['section']!='FWA':raise ValueError('Main return reminders are sent manually.')
    except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from exc
    return await queue_action(request,'cwl_rosters',request.match_info['action'],values,body.get('revision'))


routes=[web.get(API+'/return-reminders',page),web.get(API+'/return-reminders/{pool}/{tag}',page),web.post(API+'/return-reminders/{pool}/{tag}/actions/{action}',action)]
