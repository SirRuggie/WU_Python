"""Reviewed multi-clan actions using independent native worker jobs."""
import time
import uuid
from urllib.parse import quote
from aiohttp import web
from . import server_management as shared
from .manage_content import fingerprint
from utils import lazy_cwl_store as store, return_bulk, return_reminder_settings as destinations
from utils.manage_web_worker import WORKER_ID

API=shared.API
LABELS={'schedule':'Schedule return reminders','save':'Save current clan members','replace':'Replace saved lists','send':'Send return reminders','start':'Start return reminders now','pause':'Pause reminders','resume':'Resume reminders','clear':'Close saved lists','away':'Check who is away'}


async def available(db):
    result={}
    for section in ('MAIN','FWA'):
        for row in await store.list_active(db,section=section):
            result[section+':'+row['clan_tag']]=dict(section=section,tag=row['clan_tag'],name=row.get('clan_name') or row['clan_tag'],revision=fingerprint(row),active=True)
    directory=await db.clans.find({'type':{'$in':['FWA','Tactical','Flexible Fun','Competitive']}}).to_list(length=201)
    if len(directory)>200:raise web.HTTPServiceUnavailable(text='Clan directory is too large. Narrow it in Discord first.')
    from .providers import tag
    for clan in directory:
        section='FWA' if clan['type']=='FWA' else 'MAIN'; value=tag(clan['tag']); key=section+':'+value
        result.setdefault(key,dict(section=section,tag=value,name=clan.get('name') or value,revision=fingerprint(None),active=False))
    return result


def eligible(items,operation):
    return {key:item for key,item in items.items() if (not item['active'] if operation=='save' else operation=='start' or item['active']) and (operation not in ('start','pause','resume','schedule') or item['section']=='FWA')}


async def page(request):
    await shared.require_manage(request,'cwl_rosters')
    operation=request.match_info.get('operation')
    if operation not in LABELS:raise web.HTTPNotFound()
    async with shared.mongo(request) as db:
        items=eligible(await available(db),operation)
        channels=await destinations.load(db)
    revision=fingerprint({'items':items,'channels':channels})
    fields=[dict(key='clans',label='Choose clans',type='multiselect',value=[],required=True,options=[dict(value=key,label=f"{item['name']} · {item['section']}") for key,item in sorted(items.items(),key=lambda pair:pair[1]['name'].casefold())])]
    if operation in ('start','resume'):
        fields.append(dict(key='every_minutes',label='Reminder interval',type='select',value='60',options=[dict(value='30',label='Every 30 minutes'),dict(value='60',label='Every hour'),dict(value='120',label='Every 2 hours')]))
    effective=destinations.channels(channels)
    return web.json_response(dict(id='return-bulk-'+operation,label=LABELS[operation],description='Each clan has its own result. Completed clans are never included in failed-only retries.'+ (f" Main channel: {effective['MAIN']}. FWA channel: {effective['FWA']}." if operation=='send' else ''),group='War',revision=revision,fields=fields,action_only=True,
        warning='Select Main or FWA clans below. Main scheduled reminders are not available.' if operation not in ('start','pause','resume','schedule') else 'FWA clans only. Resuming keeps the original seven-day limit.',
        actions=[dict(id='run',label=LABELS[operation],confirm=LABELS[operation]+' for the selected clans?'+(' This can send Discord messages immediately.' if operation in ('send','start') else ''),endpoint='/manage/return-bulk/'+operation+'/run')]))


def request_id(body):
    try:return str(uuid.UUID(body.get('request_id')))
    except (ValueError,TypeError,AttributeError):raise web.HTTPBadRequest(text='Reload the page before trying this action.') from None


async def ready(db):
    row=await db.bot_config.find_one({'_id':WORKER_ID}) or {}
    if time.time()-row.get('checked_at',0)>60:raise web.HTTPServiceUnavailable(text='The bot is not ready. Nothing was queued.')


def response(key):
    return web.json_response(dict(status='pending',status_url='/manage/return-batches/'+key+'/status',message='Queued. Each clan will show its own result.'))


async def run(request):
    actor=await shared.require_manage(request,'cwl_rosters',write=True)
    operation=request.match_info['operation']
    if operation not in LABELS:raise web.HTTPNotFound()
    body=await request.json()
    if not isinstance(body,dict) or not isinstance(body.get('values'),dict):raise web.HTTPBadRequest()
    rid=request_id(body); values=body['values']; selected=values.get('clans')
    if set(values)-{'clans','every_minutes','schedule_start','schedule_end'} or not isinstance(selected,list) or not 1<=len(selected)<=50 or any(not isinstance(x,str) for x in selected) or len(set(selected))!=len(selected):raise web.HTTPBadRequest(text='Select between 1 and 50 different clans.')
    try:minutes=int(values.get('every_minutes',60))
    except (TypeError,ValueError):raise web.HTTPBadRequest(text='Choose a reminder interval.') from None
    if minutes not in (30,60,120):raise web.HTTPBadRequest(text='Choose 30 minutes, 1 hour, or 2 hours.')
    async with shared.mongo(request) as db:
        # Return an existing receipt before comparing new live state: network retries
        # after completed mutations must not fail merely because those mutations worked.
        key='manage-return-batch:'+return_bulk.digest([actor['user_id'],rid])
        existing=await db.bot_config.find_one({'_id':key,'kind':return_bulk.BATCH_KIND})
        schedule_values = {field:values[field] for field in ('schedule_start','schedule_end') if field in values}
        if operation != 'schedule' and schedule_values:
            raise web.HTTPBadRequest(text='Dates apply only to Schedule.')
        selection_key=return_bulk.digest([operation,sorted(selected),minutes,body.get('revision')] + ([schedule_values] if schedule_values else []))
        if existing:
            if existing.get('selection_key')!=selection_key:raise web.HTTPConflict(text='This request was already used for a different selection.')
            if existing.get("state")=="building":
                await return_bulk.queue(db,user_id=existing["user_id"],guild_id=existing["guild_id"],request_id=rid,operation=existing["operation"],items=existing["items"],minutes=existing["minutes"],retry_of=existing.get("retry_of"),selection_key=existing.get("selection_key"))
            return response(key)
        items=eligible(await available(db),operation);channels=await destinations.load(db)
        if body.get('revision')!=fingerprint({'items':items,'channels':channels}):raise web.HTTPConflict(text='The saved lists or channels changed. Refresh and review again.')
        if any(key not in items for key in selected):raise web.HTTPBadRequest(text='A selected clan is not available for this action.')
        await ready(db)
        snapshots=[]
        for key in selected:
            item=dict(items[key])
            if operation == 'schedule':
                from utils.return_schedule import validate_window
                current = await store.get_active(db,item['tag'],section=item['section'])
                if current is None or fingerprint(current) != item['revision']:
                    raise web.HTTPConflict(text='A clan list changed. Refresh and review again.')
                try:
                    start, end = validate_window(values.get('schedule_start'), values.get('schedule_end'), current)
                except ValueError as exc:
                    raise web.HTTPBadRequest(text=f"{item['name']}: {exc}") from exc
                item.update(schedule_start=start.isoformat(),schedule_end=end.isoformat())
            if operation=='send':item['destination']=destinations.channels(channels)[item['section']]
            snapshots.append(item)
        key=await return_bulk.queue(db,user_id=actor['user_id'],guild_id=shared.GUILD_ID,request_id=rid,operation=operation,items=snapshots,minutes=minutes,selection_key=selection_key)
    return response(key)


async def parent(request,db,actor):
    value=await db.bot_config.find_one({'_id':request.match_info['batch_id'],'kind':return_bulk.BATCH_KIND,'user_id':actor['user_id']})
    if not value:raise web.HTTPNotFound(text='This action is not available.')
    return value


async def history(request):
    actor=await shared.require_manage(request,'cwl_rosters')
    async with shared.mongo(request) as db:
        rows=await db.bot_config.find({'kind':return_bulk.BATCH_KIND,'user_id':actor['user_id']}).sort('created_at',-1).limit(20).to_list(length=20)
    from datetime import datetime,timezone
    return web.json_response(dict(id='return-history',label='Recent bulk actions',description='Open an action to see results or retry failed clans.',group='War',revision='history',fields=[],documents=[dict(id=row['_id'],label=LABELS[row['operation']]+' · '+datetime.fromtimestamp(row['created_at'],timezone.utc).strftime('%d %b %H:%M UTC'),endpoint='/manage/return-batches/'+row['_id']) for row in rows]))


async def status(request):
    actor=await shared.require_manage(request,'cwl_rosters')
    async with shared.mongo(request) as db:
        value=await parent(request,db,actor); rows=await return_bulk.children(db,value)
    result=return_bulk.summary(value,rows)
    if request.path.endswith('/status'):return web.json_response(result)
    actions=[]
    if result['status']=='done' and return_bulk.retryable(rows):
        actions=[dict(id='retry',label='Retry failed clans only',confirm='Retry only failed clans? Completed and uncertain actions are excluded.',endpoint='/manage/return-batches/'+value['_id']+'/retry')]
    return web.json_response(dict(id=value['_id'],label=LABELS[value['operation']],description=result['message'],group='War',revision=fingerprint(rows),readonly=True,fields=[dict(key='results',label='Clan results',type='textarea',value=result['result']['details'])],warning='Any clan marked “Check Discord” is excluded from retry. Refresh to update results.',actions=actions))


async def retry(request):
    actor=await shared.require_manage(request,'cwl_rosters',write=True)
    body=await request.json()
    if not isinstance(body,dict):raise web.HTTPBadRequest()
    rid=request_id(body)
    async with shared.mongo(request) as db:
        value=await parent(request,db,actor);rows=await return_bulk.children(db,value)
        selection_key=return_bulk.digest(['retry',value['_id'],body.get('revision')])
        # One retry batch per reviewed result, even across tabs or different UUIDs.
        rid=str(uuid.uuid5(uuid.NAMESPACE_URL,selection_key))
        key='manage-return-batch:'+return_bulk.digest([str(actor['user_id']),rid])
        existing=await db.bot_config.find_one({'_id':key,'kind':return_bulk.BATCH_KIND})
        if existing:
            if existing.get('selection_key')!=selection_key:raise web.HTTPConflict(text='This request was already used for another action.')
            if existing.get("state")=="building":
                await return_bulk.queue(db,user_id=existing["user_id"],guild_id=existing["guild_id"],request_id=rid,operation=existing["operation"],items=existing["items"],minutes=existing["minutes"],retry_of=existing.get("retry_of"),selection_key=existing.get("selection_key"))
            return response(key)
        if body.get('revision')!=fingerprint(rows) or return_bulk.summary(value,rows)['status']!='done':raise web.HTTPConflict(text='Results changed. Refresh before retrying.')
        failed=return_bulk.retryable(rows)
        if not failed:raise web.HTTPBadRequest(text='There are no failed clans to retry.')
        snapshots=[]
        for child in failed:
            pool=child['values']['section'];tag=child['values']['clan_tag'];current=await store.get_active(db,tag,section=pool)
            if fingerprint(current)!=child['revision']:raise web.HTTPConflict(text='A failed clan list changed. Start a new review for that clan.')
            item=dict(section=pool,tag=tag,name=child['clan_name'],revision=child['revision'])
            if value['operation']=='send':
                item['destination']=await destinations.destination(db,pool)
                if item['destination']!=child['values'].get('destination'):raise web.HTTPConflict(text='A return channel changed. Start a new review.')
            for field in ('schedule_start','schedule_end'):
                if field in child['values']: item[field] = child['values'][field]
            snapshots.append(item)
        await ready(db)
        key=await return_bulk.queue(db,user_id=actor['user_id'],guild_id=shared.GUILD_ID,request_id=rid,operation=value['operation'],items=snapshots,minutes=value['minutes'],retry_of=value['_id'],selection_key=selection_key)
    return response(key)


routes=[web.get(API+'/return-bulk/{operation}',page),web.post(API+'/return-bulk/{operation}/run',run),web.get(API+'/return-batches',history),web.get(API+'/return-batches/{batch_id}',status),web.get(API+'/return-batches/{batch_id}/status',status),web.post(API+'/return-batches/{batch_id}/retry',retry)]
