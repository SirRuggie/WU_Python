"""Family clan editor over the same Mongo collection as Discord /clan."""
import re
from datetime import datetime,timezone
from uuid import uuid4
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern
from utils.constants import CLAN_TYPES,TH_LEVELS
from utils.mongo import ensure_clan_tag_index
from utils.media_store import MediaStore,MediaStoreError,clan_folder
from utils.url_safety import MAX_IMAGE_BYTES
from .server_management import API,GUILD_ID,require_manage,mongo,discord,queue_action
from .manage_operations import revision
from .providers import tag as normalize_tag,ProviderUnavailable
FIELDS=('name','type','th_requirements','leader_id','leader_role_id','role_id','chat_channel_id','announcement_id','rules_channel_id','leadership_channel_id','thread_id','logo','banner','profile','emoji')
IDS=('leader_id','leader_role_id','role_id','chat_channel_id','announcement_id','rules_channel_id','leadership_channel_id','thread_id')
def public(row):return {'tag':row['tag'],'revision':revision(row),**{k:str(row.get(k) or '') for k in FIELDS}}
def tag(request):
    try:return normalize_tag(request.match_info['tag'])
    except ValueError:raise web.HTTPBadRequest(text='Enter a valid clan tag.') from None

def match(row):
    # Match all prior fields, including values changed by native Discord controls.
    return {'_id':row['_id'],**{k:row[k] if k in row else {'$exists':False} for k in FIELDS}}

async def current(request,db,body):
    row=await db.clans.find_one({'tag':tag(request)})
    if not row:raise web.HTTPNotFound(text='Clan removed. Refresh the list.')
    if not isinstance(body,dict) or body.get('revision')!=revision(row):raise web.HTTPConflict(text='This clan changed in Discord or the dashboard. Reload before saving.')
    return row

async def listing(request):
    await require_manage(request,'clans')
    async with mongo(request) as db:rows=await db.clans.find({}).sort('name',1).to_list(length=None)
    return web.json_response({'clans':[public(row) for row in rows],'types':CLAN_TYPES,'town_halls':TH_LEVELS})

async def choices(request):
    actor=await require_manage(request,'clans')
    channels=await discord(request,'GET',f'/guilds/{GUILD_ID}/channels')
    active=await discord(request,'GET',f'/guilds/{GUILD_ID}/threads/active')
    channels += active.get('threads',[])
    return web.json_response({'roles':[{'id':str(r['id']),'name':r['name'],'managed':bool(r.get('managed')),'position':r.get('position',0),'color':r.get('color',0)} for r in sorted(actor['roles'],key=lambda role:role.get('position',0),reverse=True) if str(r['id'])!=str(GUILD_ID)],'channels':[{'id':str(c['id']),'name':c['name'],'type':c['type']} for c in channels if c['type'] in (0,5,10,11,12)]})

async def members(request):
    await require_manage(request,'clans')
    from .manage_roles import searchable_members, member_option
    query=request.query.get('q','').strip().casefold()[:80]
    rows=await searchable_members(request)
    result=[]
    for row in rows:
        user=row['user'];name=row.get('nick') or user.get('global_name') or user['username']
        if not query or query in ' '.join(str(v or '') for v in (name,user.get('username'),user['id'])).casefold():result.append({'id':str(user['id']),'name':name,'avatar_url':member_option(row)['avatar_url']})
    selected=request.query.get('selected','')
    shown=result[:50]
    if selected and re.fullmatch(r'\d{15,22}',selected) and not any(m['id']==selected for m in shown):
        existing=next((r for r in rows if str(r['user']['id'])==selected),None)
        if existing:
            user=existing['user'];shown.append({'id':selected,'name':existing.get('nick') or user.get('global_name') or user['username'],'avatar_url':member_option(existing)['avatar_url']})
    return web.json_response({'members':shown,'more':len(result)>50})

from utils.clan_dashboard_history import audit, finish_change, collection as history_collection

async def add(request):
    actor=await require_manage(request,'clans',write=True);body=await request.json()
    try:clan_tag=normalize_tag(body.get('tag',''))
    except (ValueError,AttributeError):raise web.HTTPBadRequest(text='Enter a valid clan tag.') from None
    try:info=await request.app['providers'].clan(clan_tag)
    except ProviderUnavailable:raise web.HTTPServiceUnavailable(text='Clash could not confirm this clan. Try again.') from None
    async with mongo(request) as db:
        if not await ensure_clan_tag_index(db):raise web.HTTPServiceUnavailable(text='Clan uniqueness check failed. Nothing was added.')
        row={'tag':clan_tag,**{k:0 if k in IDS else '' for k in FIELDS},'name':info['name'],'thread_message_id':0}
        try:result=await db.clans.update_one({'tag':clan_tag},{'$setOnInsert':row},upsert=True)
        except DuplicateKeyError:raise web.HTTPConflict(text='Clan was just added. Refresh the list.') from None
        if result.upserted_id:await audit(db,actor,'add',await db.clans.find_one({'tag':clan_tag}))
    return await listing(request)

async def change_names(request, actor, before, after):
    """Freeze available Discord labels without making a metadata outage block a save."""
    names = {}
    cache = {}
    roles = {str(role['id']): role.get('name') for role in actor.get('roles', [])}
    for field, value in after.items():
        if field not in IDS or before.get(field) == value:
            continue
        labels = {}
        for side, identity in (('before', before.get(field)), ('after', value)):
            if not identity:
                labels[side] = 'Not set'
                continue
            if field.endswith('role_id'):
                label = roles.get(str(identity))
            else:
                path = (f'/guilds/{GUILD_ID}/members/{identity}' if field == 'leader_id'
                        else f'/channels/{identity}')
                if path not in cache:
                    try:
                        cache[path] = await discord(request, 'GET', path)
                    except Exception:
                        cache[path] = {}
                data = cache[path]
                if field == 'leader_id':
                    user = data.get('user') or {}
                    label = data.get('nick') or user.get('global_name') or user.get('username')
                else:
                    label = data.get('name') if str(data.get('guild_id')) == str(GUILD_ID) else None
            labels[side] = label or 'Name not recorded'
        names[field] = labels
    return names

async def save(request):
    actor=await require_manage(request,'clans',write=True);body=await request.json()
    values=body.get('values') if isinstance(body,dict) else None
    if not isinstance(values,dict) or set(values)-set(FIELDS):raise web.HTTPBadRequest(text='Unknown clan setting.')
    changes={}
    for key,value in values.items():
        if not isinstance(value,str):raise web.HTTPBadRequest(text='Check the clan fields.')
        value=value.strip()
        if key in IDS:
            if value and not re.fullmatch(r'\d{15,22}',value):raise web.HTTPBadRequest(text='Choose a valid Discord member, role or channel.')
            changes[key]=int(value or 0)
        else:
            if len(value)>(1000 if key in ('logo','banner','profile') else 120):raise web.HTTPBadRequest(text='Clan field is too long.')
            if key=='name' and not value:raise web.HTTPBadRequest(text='Enter the clan name.')
            if key=='type' and value not in ['',*CLAN_TYPES]:raise web.HTTPBadRequest(text='Choose a clan type.')
            if key=='th_requirements' and value not in ['',*TH_LEVELS]:raise web.HTTPBadRequest(text='Choose a Town Hall level.')
            if key in ('logo','banner','profile') and value:
                from utils.text_commands import public_url
                try:public_url(value,'image' if key!='profile' else 'profile')
                except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
            if key=='emoji' and value and not re.fullmatch(r'<a?:[A-Za-z0-9_]{2,32}:\d{15,22}>',value):raise web.HTTPBadRequest(text='Use a Discord emoji such as <:name:123456789012345678>.')
            changes[key]=value
    async with mongo(request) as db:
        row=await current(request,db,body)
        for key,value in changes.items():
            if not value or key not in IDS or str(value)==str(row.get(key)):continue
            if key=='leader_id':await discord(request,'GET',f'/guilds/{GUILD_ID}/members/{value}')
            elif key.endswith('role_id'):
                if value==GUILD_ID or not any(str(r['id'])==str(value) for r in actor['roles']):raise web.HTTPBadRequest(text='Choose a role in this server.')
            else:
                channel=await discord(request,'GET',f'/channels/{value}')
                if str(channel.get('guild_id'))!=str(GUILD_ID) or channel.get('type') not in ((10,11,12) if key=='thread_id' else (0,5)):raise web.HTTPBadRequest(text='Choose a channel in this server.')
        names = await change_names(request, actor, row, changes)
        event_id=await audit(db,actor,'before_edit',row)
        result=await db.clans.update_one(match(row),{'$set':changes})
        if not result.matched_count:raise web.HTTPConflict(text='Clan changed. Reload before saving.')
        await finish_change(db,event_id,{key:row.get(key) for key in changes},changes,names=names)
        latest=await db.clans.find_one({'tag':row['tag']})
        if not latest:raise web.HTTPConflict(text='Clan was removed. Refresh the list.')
        result=public(latest)
    return web.json_response(result)

async def remove(request):
    actor=await require_manage(request,'clans',write=True);body=await request.json()
    async with mongo(request) as db:
        row=await current(request,db,body)
        if body.get('confirm_tag')!=row['tag']:raise web.HTTPBadRequest(text='Enter the clan tag to confirm removal.')
        await audit(db,actor,'before_remove',row)
        result=await db.clans.delete_one(match(row))
        if not result.deleted_count:raise web.HTTPConflict(text='Clan changed. Reload before removing it.')
    return web.json_response({'ok':True})

async def image(request):
    await require_manage(request,'clans',write=True)
    slot=request.match_info['slot']
    if slot not in ('logo','banner'):raise web.HTTPBadRequest(text='Choose logo or banner.')
    async with mongo(request) as db:row=await current(request,db,{'revision':request.query.get('revision')})
    media=request.app.get('server_management_media') or MediaStore.from_env()
    try:
        if request.content_type=='application/json':
            body=await request.json();source=body.get('url') if isinstance(body,dict) else None
            from utils.text_commands import public_url
            public_url(source,'image')
            url=await media.upload_from_url(source,folder=clan_folder(row['name']),name=slot)
        else:
            data=bytearray()
            async for chunk in request.content.iter_chunked(65536):
                data.extend(chunk)
                if len(data)>MAX_IMAGE_BYTES:raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES,actual_size=len(data))
            url=await media.upload_bytes(bytes(data),folder=clan_folder(row['name']),name=slot)
    except (ValueError,MediaStoreError) as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response({'url':url})

async def action(request):
    await require_manage(request,'clans',write=True);body=await request.json()
    async with mongo(request) as db:row=await current(request,db,body)
    return await queue_action(request,'clans',request.match_info['action'],{'tag':row['tag']},revision(row))

routes=[web.get(API+'/clans',listing),web.post(API+'/clans',add),web.get(API+'/clan-choices',choices),web.get(API+'/clan-members',members),web.patch(API+'/clans/{tag}',save),web.delete(API+'/clans/{tag}',remove),web.post(API+'/clans/{tag}/images/{slot}',image),web.post(API+'/clans/{tag}/actions/{action}',action)]
