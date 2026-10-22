"""Read-only, permission-scoped staff attention summary."""
import time
from types import SimpleNamespace
from aiohttp import web
from .server_management import API, GUILD_ID, identity, allowed, mongo
from .access_control import SECTION_SCOPE

DESTINATIONS = {'clan_weights':'weight-trial','clans':'clan-management','text_commands':'text-commands','cwl':'roster',
 'recruitment':'applications-settings','tickets':'applications-settings','member_roles':'members-settings',
 'fwa':'fwa-settings','server_tools':'connections-settings'}
REPRESENTATIVES = {'clans':'clans','text_commands':'text_commands','cwl':'cwl','recruitment':'recruit',
 'tickets':'ticket_settings','member_roles':'roles','fwa':'fwa_points','server_tools':'band_monitor'}

def cwl_summary(store):
    return store.rows('''SELECT s.id, s.label, COUNT(u.tag) AS signed_up,
        SUM(CASE WHEN u.tag IS NOT NULL AND (r.assigned_clan_tag IS NULL OR r.assigned_clan_tag='') THEN 1 ELSE 0 END) AS unplaced
        FROM seasons s LEFT JOIN signups u ON u.season_id=s.id
        LEFT JOIN roster_entries r ON r.season_id=u.season_id AND r.tag=u.tag
        WHERE s.status!='archived' GROUP BY s.id ORDER BY s.id DESC''')

async def overview(request):
    actor = await identity(request)
    async with mongo(request) as db:
        grants = {scope for scope, section in REPRESENTATIVES.items() if await allowed(actor,section,db)}
        from .access_control import CWL_PERMISSIONS
        from utils.dashboard_access import OWNER_IDS
        effective_scopes = set(actor.get('dashboard_scopes', []))
        if str(actor['user_id']) in OWNER_IDS or effective_scopes & set(CWL_PERMISSIONS):
            grants.add('cwl')
        if 'clan_weights' in effective_scopes:
            grants.add('clan_weights')
        if not grants:raise web.HTTPForbidden(text='Staff access is required.')
        result = {'checked_at':time.time(),'seasons':[], 'tickets':None,'failures':[], 'failures_count':0,'warnings':[]}
        if 'cwl' in grants:
            from .app import _store
            result['seasons'] = cwl_summary(_store(request))
        if grants & {'tickets','recruitment'}:
            from extensions.commands.tickets.perms import is_recruiter
            from extensions.commands.tickets.store import RUNTIME_FILTER
            member = SimpleNamespace(guild_id=GUILD_ID,role_ids=actor['role_ids'],permissions=actor['permissions'])
            if await is_recruiter(member,db):
                query = {**RUNTIME_FILTER,'guild_id':GUILD_ID,'status':'open'}
                count = await db.tickets.count_documents(query)
                hub = await db.ticket_setup.find_one({'_id':'ticket_console_hub'}) or {}
                channel = str(hub.get('channel_id') or '')
                result['tickets'] = {'open':count,'url':f'https://discord.com/channels/{GUILD_ID}/{channel}' if channel.isdigit() else None}
            else:result['warnings'].append('Ticket counts require Discord recruiter access.')
        sections = [section for section,scope in SECTION_SCOPE.items() if scope in grants or (scope.startswith('cwl_') and 'cwl' in grants)]
        query = {'kind':'manage_web_request','guild_id':GUILD_ID,'user_id':actor['user_id'],
                 'section':{'$in':sections},'status':{'$in':['failed','uncertain']},'created_at':{'$gte':time.time()-7*86400}}
        result['failures_count'] = await db.bot_config.count_documents(query)
        rows = await db.bot_config.find(query,{'section':1,'action':1,'status':1,'created_at':1}).sort('created_at',-1).limit(5).to_list(length=5)
        result['failures'] = [{'id':str(row['_id']),'action':str(row.get('action','Action')).replace('_',' '),
            'status':row['status'],'at':row['created_at'],'destination':DESTINATIONS.get(SECTION_SCOPE[row['section']], 'cwl-returns')} for row in rows]
        result['areas'] = [DESTINATIONS[scope] for scope in DESTINATIONS if scope in grants or (scope.startswith('cwl_') and 'cwl' in grants)]
    response = web.json_response(result)
    response.headers['Cache-Control']='no-store'
    return response

routes = [web.get(API+'/staff-overview',overview)]
