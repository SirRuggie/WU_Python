"""Ticket settings and isolated test controls backed by native bot operations."""
from aiohttp import web
from .server_management import API, GUILD_ID, mongo, require_manage, queue_action
from .manage_content import fingerprint

FIELDS = {f'{kind}_{name}' for kind in ('main','fwa') for name in ('candidate_parent','staff_parent','thread_recruiter_role')} | {'ticket_staff_viewer_role_ids','ticket_inactivity_minutes','ticket_archive_quiet_days'}


def validated_settings(values):
    if not isinstance(values,dict) or set(values)-FIELDS:
        raise ValueError('Unknown ticket setting.')
    clean={}
    for key,value in values.items():
        if key=='ticket_staff_viewer_role_ids':
            if not isinstance(value,list) or len(value)>25 or any(not isinstance(v,str) or not v.isdigit() for v in value):
                raise ValueError('Choose valid viewer roles.')
            clean[key]=list(map(int,value))
        elif key=='ticket_inactivity_minutes':
            if type(value) is not int or not 1440<=value<=525600:raise ValueError('Open-ticket wait must be 1 to 365 days in minutes.')
            clean[key]=value
        elif key=='ticket_archive_quiet_days':
            if type(value) is not int or not 0<=value<=365:raise ValueError('Archive wait must be 0 to 365 days.')
            clean[key]=value
        else:
            if not isinstance(value,str) or not value.isdigit() or not 15<=len(value)<=22:raise ValueError('Choose a channel or role.')
            clean[key]=int(value)
    return clean


def history_values(cfg,part):
    if part=='timers':return {'ticket_inactivity_minutes':cfg.get('ticket_inactivity_minutes',10080),'ticket_archive_quiet_days':cfg.get('ticket_archive_quiet_days',1)}
    if part=='viewers':return {'ticket_staff_viewer_role_ids':[str(x) for x in cfg.get('ticket_staff_viewer_role_ids',[])]}
    return {f'{part}_{key}':str(cfg.get(f'{part}_{key}') or '') for key in ('candidate_parent','staff_parent','thread_recruiter_role')}


def field(key,label,value,kind='text',**extra):
    return dict(key=key,label=label,value=value,type=kind,**extra)


async def settings(request):
    await require_manage(request,'ticket_settings')
    async with mongo(request) as db:cfg=await db.ticket_setup.find_one({'_id':'config'}) or {}
    part=request.match_info.get('part')
    result=dict(id='ticket_settings',label='Ticket settings',description='Choose the ticket settings to change.',group='Recruitment',revision=fingerprint(cfg),fields=[])
    if not part:
        result['documents']=[dict(id=key,label=label,endpoint='/manage/ticket-settings/'+key) for key,label in [('timers','Ticket wait times'),('main','Main application channels'),('fwa','FWA application channels'),('viewers','Staff viewing access'),('tools','Ticket panel tools')]]
    elif part=='timers':
        result['description']='Set when staff review inactive tickets and when resolved tickets are archived.'
        result['fields']=[field('ticket_inactivity_minutes','Open-ticket review wait (minutes)',cfg.get('ticket_inactivity_minutes',10080),'number',min=1440,max=525600,description='Staff are asked to review silent tickets. Tickets are not denied automatically.'),field('ticket_archive_quiet_days','Archive resolved tickets after quiet days',cfg.get('ticket_archive_quiet_days',1),'number',min=0,max=365,description='0 turns automatic archiving off. History is kept.')]
    elif part in ('main','fwa'):
        result['description']='Choose application channels and the recruiter role.'
        result['fields']=[field(f'{part}_{key}',label,str(cfg.get(f'{part}_{key}') or ''),kind) for key,label,kind in [('candidate_parent','Recruit channel','channel'),('staff_parent','Staff channel','channel'),('thread_recruiter_role','Recruiter role','role')]]
        result['warning']='The recruit channel must match the active Apply panel. Moving intake requires updating that binding first.'
    elif part=='viewers':
        result['description']='Choose additional roles that can view tickets.'
        result['fields']=[field('ticket_staff_viewer_role_ids','Extra staff viewer roles',[str(x) for x in cfg.get('ticket_staff_viewer_role_ids',[])],'multiselect',description='Viewing access does not grant permission to make ticket decisions.',source='roles')]
    elif part=='tools':
        result['description']='Check ticket setup or restore a missing panel.'
        result['action_only']=True
        result['fields']=[field('console_channel','Staff console channel','','channel')]
        result['actions']=[dict(id=x,label=l,confirm=c,endpoint='/manage/ticket-settings/actions/'+x) for x,l,c in [('check','Check setup','Check current ticket channels and bot permissions? No messages are sent.'),('restore_entry','Restore Apply panel','Restore the public Apply message in its bound channel?'),('restore_console','Restore staff console','Restore the staff console in the selected channel?')]]
    else:raise web.HTTPNotFound()
    return web.json_response(result)


async def save(request):
    await require_manage(request,'ticket_settings',write=True)
    body=await request.json()
    if not isinstance(body,dict):raise web.HTTPBadRequest(text='Invalid settings.')
    try:validated_settings(body.get('values'))
    except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from exc
    return await queue_action(request,'ticket_settings','save',body['values'],body.get('revision'))


async def settings_action(request):
    body=await request.json()
    if not isinstance(body,dict):raise web.HTTPBadRequest()
    return await queue_action(request,'ticket_settings',request.match_info['action'],body.get('values',{}),body.get('revision'))


async def testing(request):
    actor=await require_manage(request,'ticket_testing')
    from extensions.commands.tickets import testing_service
    from .server_management import allowed
    async with mongo(request) as db:
        current=await testing_service.active_window(testing_service.test_mongo(db))
        admin=await allowed(actor,'ticket_settings',db)
    result=dict(id='ticket_testing',label='Test tickets',description='Test tickets are stored separately from live applications.',group='Recruitment',revision=fingerprint(current),fields=[],action_only=True,
        warning='Test window is open.' if current else 'Test window is closed.')
    if admin:
        result['fields']=[field('duration_minutes','Test window length (minutes)',60,'number',min=1,max=1440),field('cleanup_minutes','Cleanup wait (minutes)',60,'number',min=0,max=10080),field('allowed_user_ids','Testers',[str(x) for x in (current or {}).get('allowed_user_ids',[])],'multiselect',options=[],source='members'),field('allowed_role_ids','Tester roles',[str(x) for x in (current or {}).get('allowed_role_ids',[])],'multiselect',source='roles'),field('allow_admins','Allow administrators',(current or {}).get('allow_admins',True),'boolean')]
        actions=[('end','Close test window'),('access','Save tester access'),('clear','Clear test tickets')] if current else [('start','Open test window'),('clear','Clear test tickets')]
    else:actions=[]
    if current:actions += [('main','Open my Main test ticket'),('fwa','Open my FWA test ticket')]
    result['actions']=[dict(id=key,label=label,confirm=label+'? This affects only the test area.',endpoint='/manage/ticket-testing/actions/'+key) for key,label in actions]
    return web.json_response(result)


async def testing_action(request):
    body=await request.json()
    if not isinstance(body,dict) or not isinstance(body.get('values',{}),dict):raise web.HTTPBadRequest()
    return await queue_action(request,'ticket_testing',request.match_info['action'],body.get('values',{}),body.get('revision'))


routes=[web.get(API+'/ticket-settings',settings),web.get(API+'/ticket-settings/{part}',settings),web.patch(API+'/ticket-settings/{part}',save),web.post(API+'/ticket-settings/actions/{action}',settings_action),web.get(API+'/ticket-testing',testing),web.post(API+'/ticket-testing/actions/{action}',testing_action)]
