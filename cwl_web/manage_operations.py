"""FWA management adapters over the bot's existing Mongo records."""
import copy
import re
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from utils import fwa_blacklist
from utils.fwa_points_parser import sanitize_tag
from utils.user_copy import needs_permissions
from . import server_management as shared
from utils.manage_operations_runtime import revision, runtime_snapshot, refresh_base_image_cache, public_band_error

API = shared.API + '/operations'
LABELS = {'fwa_points':'FWA points','fwa_sync':'FWA sync reminders','fwa_weight':'TH weight ranges','fwa_blacklist':'Clan blacklist','fwa_bases':'FWA bases','band_monitor':'BAND monitor'}

def field(key,label,value,kind='text',**kw):
    return dict(key=key,label=label,value=value,type=kind,**kw)

def document(section, row, fields, **kw):
    return dict(id=section,label=LABELS[section],description='Shared with Discord /manage.',group='War',revision=revision(row),fields=fields,**kw)

async def cas(collection, row_id, before, changes):
    # Match actual prior fields: Discord writers do not all increment a revision.
    query={'_id':row_id}
    for key in changes:
        query[key]=before[key] if key in before else {'$exists':False}
    try:
        result=await collection.update_one(query,{'$set':changes},upsert=not before)
    except DuplicateKeyError:
        raise web.HTTPConflict(text='Settings changed. Refresh and review your edit.') from None
    if not result.matched_count and not result.upserted_id:
        raise web.HTTPConflict(text='Settings changed. Refresh and review your edit.')

def public_url(value):
    from ipaddress import ip_address
    try:
        url=urlsplit(value)
        if url.scheme!='https' or not url.hostname or url.username or url.password: return False
        if url.hostname.lower() in {'localhost'} or '.' not in url.hostname: return False
        try: return ip_address(url.hostname).is_global
        except ValueError: return True
    except ValueError:return False

def checked(values, allowed):
    if not isinstance(values,dict) or set(values)-set(allowed):
        raise web.HTTPBadRequest(text='Unknown setting. Refresh this page.')
    return values

async def load_document(db, section, item=None, *, source_snapshot=None):
    if section=='band_monitor':
        row=await db.bot_config.find_one({'_id':'manage-web-band-status'}) or {}
        checked_at = row.get('checked_at')
        checked_at_label = 'Not checked'
        fresh = False
        if type(checked_at) in (int, float):
            try:
                checked_at_label = datetime.fromtimestamp(checked_at, timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                fresh = 0 <= time.time() - checked_at < 120
            except (ValueError, OverflowError, OSError):
                pass
        unavailable = 'Status unavailable'
        fields = [
            field('task', 'Monitor', row.get('task', 'Not checked') if fresh else unavailable),
            field('checked_at', 'Last status check', checked_at_label),
            field('startup', 'Startup', row.get('startup', 'Not checked') if fresh else unavailable),
            field('key', 'BAND connection', ('Configured' if row.get('key_ready') else 'Missing') if fresh else unavailable),
            field('health', 'Poll health', row.get('health', 'Not checked') if fresh else unavailable),
            field('last_success', 'Last successful check', str(row.get('last_success') or 'Not checked')),
            field('last_error', 'Last recorded problem', public_band_error(row.get('last_error')) or 'None recorded'),
            field('debug', 'Debug logging', bool(row.get('debug', False)) if fresh else unavailable,
                  'boolean' if fresh else 'text'),
        ]
        return document(section, row, fields, readonly=True,
                        warning=('Use Check status for current information. Debug turns off on restart.'
                                 if fresh else 'Status is outdated or unavailable. Check status before relying on these results.'),
                        actions=[{'id': 'status', 'label': 'Check status'},
                                 {'id': 'debug_on', 'label': 'Enable debug logging', 'advanced': True},
                                 {'id': 'debug_off', 'label': 'Disable debug logging', 'advanced': True}])
    if section=='fwa_weight':
        from .town_halls import required, document as town_halls_document
        row = await required(db)
        return town_halls_document(row, 'add' if item == 'new' else item)
    if section=='fwa_bases':
        raise web.HTTPGone(text='FWA bases moved to Town Halls. Refresh this page.')
    if section=='fwa_blacklist':
        rows=await fwa_blacklist.list_blacklisted(db)
        if not item:
            return document(section,rows,[],documents=[{'id':r['_id'],'label':r.get('name') or r['_id'],'endpoint':f'/manage/operations/{section}/{r["_id"]}'} for r in rows]+[{'id':'new','label':'Add clan','endpoint':f'/manage/operations/{section}/new'}])
        row=next((r for r in rows if r['_id']==item),{})
        if source_snapshot is not None:source_snapshot.update(copy.deepcopy(row))
        if item!='new' and not row:raise web.HTTPNotFound(text='This clan is no longer on the blacklist.')
        return document(section,row,[field('tag','Clan tag','#'+item if item!='new' else '',readonly=item!='new'),field('name','Clan name',row.get('name',''),max_length=100,readonly=item!='new')],actions=[] if item=='new' else [{'id':'remove','label':'Remove clan','confirm':'Remove this clan from the shared blacklist?'}])
    if section=='fwa_points':
        from extensions.tasks import fwa_points_monitor as monitor
        row=await db.fwa_points.find_one({'_id':'config'}) or {}
        if source_snapshot is not None:source_snapshot.update(copy.deepcopy(row))
        watch=await monitor.effective_watch_list(await monitor.load_config(db),db,strict=True)
        if not item:
            return document(section,row,[],documents=[{'id':'settings','label':'Monitoring settings','endpoint':'/manage/operations/fwa_points/settings'}]+[{'id':c['tag'],'label':c.get('name') or c['tag'],'endpoint':f'/manage/operations/fwa_points/{c["tag"]}'} for c in watch])
        if item!='settings':
            clan=next((entry for entry in watch if entry['tag']==item),None)
            if not clan:raise web.HTTPNotFound(text='This clan is not watched.')
            record=await db.fwa_points.find_one({'_id':item}) or {}
            result=document(section,record,[field('name','Clan',clan.get('name') or item),field('verdict','Latest result',record.get('raw_verdict') or 'No result yet'),field('war','War number',str(record.get('war_number','Unknown'))),field('sync','Sync number',str(record.get('sync_number','Unknown'))),field('points','Point balance',str(record.get('point_balance','Unknown'))),field('updated','Last updated',str(record.get('scraped_at','Unknown')))],readonly=True)
            result['label']=clan.get('name') or item
            return result
        return document(section,row,[field('enabled','Monitoring enabled',bool(row.get('enabled',monitor.DEFAULT_ENABLED)),'boolean',readonly=True),field('watch_list','Extra clans', '\n'.join(f'{c["tag"]} {c.get("name","")}' for c in row.get('watch_list',[])),'textarea',description='One clan per line: #TAG Clan name. Family FWA clans are included automatically.')],preview=[{'text':'Family FWA clans are included automatically. Extra clans can be edited below.'}],actions=[{'id':'enable','label':'Start monitoring'},{'id':'disable','label':'Pause monitoring'}],warning='Saved settings do not prove monitoring is running. Use Check status.')
    if section=='fwa_sync':
        from extensions.tasks.band_sync_schema import CONFIG_ID, normalize_config
        row=await db.fwa_sync_config.find_one({'_id':CONFIG_ID}) or {}
        if source_snapshot is not None:source_snapshot.update(copy.deepcopy(row))
        effective = normalize_config(row)
        return document(section,row,[field('enabled','Reminders enabled',effective['enabled'],'boolean'),field('panel_channel_id','Signup channel',str(effective['panel_channel_id'] or ''),'channel'),field('band_url','BAND fallback link',effective['band_url'])],warning="Changes start at the next bot check. That is within 5 minutes.",actions=[{'id':'check_feed','label':'Check calendar','description':'Checks the feed without sending messages.'},{'id':'test_dm','label':'Send me a test DM','description':'Sends a test only to you.','advanced':True}])
    raise web.HTTPNotFound()

async def check_channel_permissions(request, channel):
    """Match Discord's overwrite precedence for the bot's destination access."""
    me=await shared.discord(request,'GET','/users/@me')
    member=await shared.discord(request,'GET',f'/guilds/{shared.GUILD_ID}/members/{me["id"]}')
    roles=await shared.discord(request,'GET',f'/guilds/{shared.GUILD_ID}/roles')
    ids={str(x) for x in member.get('roles',[])}
    permissions=0
    for role in roles:
        if str(role['id']) in ids|{str(shared.GUILD_ID)}:permissions|=int(role.get('permissions',0))
    if permissions&8:return
    overwrites=channel.get('permission_overwrites',[])
    for overwrite in overwrites:
        if str(overwrite['id'])==str(shared.GUILD_ID):permissions=(permissions&~int(overwrite.get('deny',0)))|int(overwrite.get('allow',0))
    deny=allow=0
    for overwrite in overwrites:
        if overwrite.get('type')==0 and str(overwrite['id']) in ids:
            deny|=int(overwrite.get('deny',0));allow|=int(overwrite.get('allow',0))
    permissions=(permissions&~deny)|allow
    for overwrite in overwrites:
        if overwrite.get('type')==1 and str(overwrite['id'])==str(me['id']):permissions=(permissions&~int(overwrite.get('deny',0)))|int(overwrite.get('allow',0))
    needed=(1<<10)|(1<<11)|(1<<14)
    if permissions&needed!=needed:raise web.HTTPBadRequest(text=needs_permissions("View Channel", "Send Messages", "Embed Links", where="in this channel"))

async def read(request):
    section=request.match_info['section']; await shared.require_manage(request,section)
    if section == 'fwa_bases':
        from utils.town_halls import parse_variant_value
        item = request.match_info.get('item')
        try:
            suffix = '/' + str(parse_variant_value(item)[0]) if item else ''
        except ValueError:
            raise web.HTTPBadRequest(text='Select an available base level.') from None
        raise web.HTTPTemporaryRedirect(location='/api/cwl/manage/town-halls' + suffix)
    if section == 'fwa_weight':
        item = request.match_info.get('item')
        suffix = '/' + ('add' if item == 'new' else item) if item else ''
        raise web.HTTPTemporaryRedirect(location='/api/cwl/manage/town-halls' + suffix)
    async with shared.mongo(request) as db: result=await load_document(db,section,request.match_info.get('item'))
    return web.json_response(result)

async def save(request):
    from .app import _json
    section=request.match_info['section']
    if section == 'fwa_bases':
        await shared.require_manage(request, 'fwa_bases', write=True)
        raise web.HTTPGone(text='FWA bases moved to Town Halls. Refresh this page.')
    if section == 'fwa_weight':
        await shared.require_manage(request, 'fwa_weight', write=True)
        raise web.HTTPGone(text='TH weight ranges moved to Town Halls. Refresh this page.')
    item=request.match_info.get('item');actor=await shared.require_manage(request,section,write=True)
    body=await _json(request)
    async with shared.mongo(request) as db:
        source_snapshot={}
        current=await load_document(db,section,item,source_snapshot=source_snapshot)
        if body.get('revision')!=current['revision']:raise web.HTTPConflict(text='Settings changed in Discord or another browser. Refresh and review your edit.')
        if current.get('readonly'):
            raise web.HTTPBadRequest(text='This status is read-only. Use its available actions.')
        fields={f['key']:f for f in current['fields']};values=checked(body.get('values'),fields)
        if any(fields[k].get('readonly') for k in values):raise web.HTTPBadRequest(text='This setting cannot be edited.')
        for key,value in values.items():
            if fields[key]['type'] == 'number':
                if type(value) is not int or not fields[key].get('min', value) <= value <= fields[key].get('max', value):
                    raise web.HTTPBadRequest(text='Enter a whole number within the displayed range.')
            if fields[key]['type'] in {'text','textarea','channel'} and (not isinstance(value,str) or len(value)>4000):raise web.HTTPBadRequest(text='Enter valid text within 4,000 characters.')
        from .change_history import begin, finish, fields as history_fields
        history_target=shared.API+'/operations/'+section+('/'+item if item else '')
        history_id=await begin(db,history_target,actor,history_fields(current),getattr(request,'history_action','edit')) if section!='fwa_blacklist' and item!='new' else None
        try:
            if section=='fwa_blacklist':
                if item!='new':raise ValueError('Remove and re-add a clan to change its details.')
                tag=sanitize_tag(values.get('tag',''));name=values.get('name','').strip()
                if not tag or not name or len(name)>100:raise ValueError('Enter a valid clan tag and name.')
                if await db.fwa_blacklist.find_one({'_id':tag}):raise web.HTTPConflict(text='This clan is already on the blacklist.')
                await fwa_blacklist.add_blacklisted(db,tag,name,int(actor['user_id']),actor.get('member',{}).get('nick') or 'Dashboard staff','manual')
                item=tag
            elif section=='fwa_points':
                row=source_snapshot;entries=[]
                for line in values.get('watch_list','').splitlines():
                    parts=line.strip().split(maxsplit=1)
                    if not parts:continue
                    tag=sanitize_tag(parts[0])
                    if not tag:raise ValueError('Enter one valid clan tag per line.')
                    if tag not in {x['tag'] for x in entries}:entries.append({'tag':tag,'name':parts[1][:100] if len(parts)>1 else tag})
                if len(entries)>100:raise ValueError('Keep at most 100 extra clans.')
                if 'watch_list' in values:await cas(db.fwa_points,'config',row,{'watch_list':entries})
            elif section=='fwa_sync':
                from extensions.tasks.band_sync_schema import CONFIG_ID
                row=source_snapshot
                if 'enabled' in values and not isinstance(values['enabled'],bool):raise ValueError("Select enabled or disabled.")
                if values.get('band_url') and not public_url(values['band_url']):raise ValueError('Use a public HTTPS link.')
                if 'panel_channel_id' in values:
                    if not re.fullmatch(r'[0-9]{15,22}', values['panel_channel_id']):
                        raise ValueError("Select a signup channel in this server.")
                    channel=await shared.discord(request,'GET','/channels/'+values['panel_channel_id'])
                    if str(channel.get('guild_id'))!=str(shared.GUILD_ID) or channel.get('type') not in (0,5):raise ValueError("Select a text channel in this server.")
                    await check_channel_permissions(request,channel)
                    values['panel_channel_id']=int(values['panel_channel_id'])
                if values:await cas(db.fwa_sync_config,CONFIG_ID,row,values)
            result=await load_document(db,section,item)
            if history_id: await finish(db,history_id,history_fields(result))
        except (ValueError,TypeError,KeyError) as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response(result)

async def action(request):
    from .app import _json
    section=request.match_info['section'];item=request.match_info.get('item');action_id=request.match_info['action'];await shared.require_manage(request,section,write=True)
    body=await _json(request)
    if section=='fwa_blacklist' and action_id=='remove':
        async with shared.mongo(request) as db:
            source_snapshot={}
            current=await load_document(db,section,item,source_snapshot=source_snapshot)
            if current['revision']!=body.get('revision'):raise web.HTTPConflict(text='This entry changed. Refresh first.')
            if not await fwa_blacklist.remove_blacklisted(db,item,expected_added_at=source_snapshot.get('added_at')):raise web.HTTPConflict(text='This entry changed. Refresh first.')
        return web.json_response({'message':'Clan removed.','removed':True,'return_endpoint':'/manage/operations/fwa_blacklist','return_label':'Clan blacklist'})
    if (section,action_id) not in {('fwa_points','enable'),('fwa_points','disable'),('fwa_sync','check_feed'),('fwa_sync','test_dm'),('band_monitor','status'),('band_monitor','debug_on'),('band_monitor','debug_off')}:
        raise web.HTTPNotFound(text='Unknown action.')
    return await shared.queue_action(request,section,action_id,body.get('values',{}),body.get('revision'))

async def upload_base(request):
    await shared.require_manage(request, 'fwa_bases', write=True)
    raise web.HTTPGone(text='FWA bases moved to Town Halls. Refresh this page.')

routes=[web.post(API+'/fwa_bases/{item}/upload/{slot}',upload_base),web.get(API+'/{section}',read),web.patch(API+'/{section}',save),web.get(API+'/{section}/{item}',read),web.patch(API+'/{section}/{item}',save),web.post(API+'/{section}/actions/{action}',action),web.post(API+'/{section}/{item}/actions/{action}',action)]
