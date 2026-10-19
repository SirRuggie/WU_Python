"""Read-only ticket archive and Discord thread viewer. No transcript persistence."""
import re
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import urlparse
from aiohttp import web
from .server_management import API, GUILD_ID, identity, allowed, mongo, discord
from extensions.commands.tickets.perms import is_recruiter
from extensions.commands.tickets.store import RUNTIME_FILTER, BROWSE_PROJECTION

PAGE_SIZE = 20
READ = (1 << 10) | (1 << 16)
MANAGE_THREADS = 1 << 34

async def authorize(request, db):
    actor = await identity(request)
    if not await allowed(actor, 'ticket_settings', db):
        raise web.HTTPForbidden(text='Ticket dashboard access is required.')
    member = SimpleNamespace(id=int(actor['user_id']), guild_id=GUILD_ID,
                             role_ids=actor['role_ids'], permissions=actor['permissions'])
    if not await is_recruiter(member, db):
        raise web.HTTPForbidden(text='Discord recruiter access is required to read tickets.')
    return actor

def date_value(raw):
    try:
        return datetime.strptime(raw, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text='Choose a valid date.')

def filters(params):
    query = {**RUNTIME_FILTER, 'guild_id': GUILD_ID}
    status = params.get('status', 'closed')
    if status == 'closed': query['status'] = {'$in':['approved','denied','closed']}
    elif status in {'open','approved','denied'}: query['status'] = status
    elif status != 'all': raise web.HTTPBadRequest(text='Choose a ticket status.')
    kind = params.get('kind','all')
    if kind in {'main','fwa'}: query['ticket_type'] = kind
    elif kind != 'all': raise web.HTTPBadRequest(text='Choose Main, FWA or All.')
    text = params.get('q','').strip()
    if len(text)>80: raise web.HTTPBadRequest(text='Use a shorter search.')
    if text:
        escaped = re.escape(text)
        choices = [{key:{'$regex':escaped,'$options':'i'}} for key in ('username','display_name','player_tags')]
        number = text.lstrip('#')
        if number.isdigit() and len(number)<=22:
            choices += [{'user_id':number}]
            if int(number)<=9223372036854775807: choices += [{'ticket_number':int(number)}, {'user_id':int(number)}]
        query['$or'] = choices
    start,end = params.get('from',''),params.get('to','')
    if start or end:
        dates={}
        if start: dates['$gte']=date_value(start)
        if end:
            try: dates['$lt']=date_value(end)+timedelta(days=1)
            except OverflowError: raise web.HTTPBadRequest(text='Choose an earlier end date.')
        if start and end and dates['$gte']>=dates['$lt']: raise web.HTTPBadRequest(text='End date must be after start date.')
        query['created_at']=dates
    return query

def public_ticket(row):
    created=row.get('created_at')
    return {'id':str(row['_id']), 'number':row.get('ticket_number'), 'name':row.get('display_name') or row.get('username') or 'Unknown member',
            'user_id':str(row.get('user_id') or ''), 'kind':row.get('ticket_type',''), 'status':row.get('status',''),
            'created_at':created.isoformat() if isinstance(created,datetime) else None}

async def listing(request):
    query=filters(request.query)
    try: page=int(request.query.get('page','1'))
    except ValueError: raise web.HTTPBadRequest(text='Invalid page.')
    if not 1<=page<=10000: raise web.HTTPBadRequest(text='Invalid page.')
    async with mongo(request) as db:
        await authorize(request, db)
        rows=await db.tickets.find(query,{**BROWSE_PROJECTION,'display_name':1}).sort([('created_at',-1),('_id',-1)]).skip((page-1)*PAGE_SIZE).limit(PAGE_SIZE+1).to_list(length=PAGE_SIZE+1)
    return web.json_response({'tickets':[public_ticket(row) for row in rows[:PAGE_SIZE]],'has_more':len(rows)>PAGE_SIZE,'page':page})

def effective_permissions(actor, channel):
    permissions=int(actor['permissions'])
    if permissions&8: return permissions
    ids={str(value) for value in actor['role_ids']}
    overwrites=channel.get('permission_overwrites',[])
    for entry in overwrites:
        if str(entry['id'])==str(GUILD_ID):permissions=(permissions&~int(entry.get('deny',0)))|int(entry.get('allow',0))
    deny=allow=0
    for entry in overwrites:
        if entry.get('type')==0 and str(entry['id']) in ids:
            deny|=int(entry.get('deny',0));allow|=int(entry.get('allow',0))
    permissions=(permissions&~deny)|allow
    for entry in overwrites:
        if entry.get('type')==1 and str(entry['id'])==actor['user_id']:
            permissions=(permissions&~int(entry.get('deny',0)))|int(entry.get('allow',0))
    return permissions

async def check_thread(request, actor, channel_id):
    channel=await discord(request,'GET',f'/channels/{channel_id}')
    if str(channel.get('guild_id'))!=str(GUILD_ID) or channel.get('type') not in (10,11,12):
        raise web.HTTPForbidden(text='This ticket thread does not belong to this server.')
    parent=await discord(request,'GET',f'/channels/{channel["parent_id"]}')
    if str(parent.get('guild_id'))!=str(GUILD_ID):raise web.HTTPForbidden(text='Ticket channel is unavailable.')
    permissions=effective_permissions(actor,parent)
    if not permissions&8:
        if permissions&READ!=READ:raise web.HTTPForbidden(text='You do not have permission to read this conversation in Discord.')
        if channel['type']==12 and not permissions&MANAGE_THREADS:
            try: await discord(request,'GET',f'/channels/{channel_id}/thread-members/{actor["user_id"]}')
            except web.HTTPNotFound: raise web.HTTPForbidden(text='You are not a member of this private thread.')
    return channel

def safe_url(value):
    if not isinstance(value,str):return None
    try:
        parsed=urlparse(value)
        return value if parsed.scheme=='https' and parsed.netloc and not parsed.username and not parsed.password else None
    except ValueError:return None

def component_text(parts):
    text=[];links=[]
    for part in parts[:40]:
        if not isinstance(part,dict):continue
        if part.get('type')==10: text.append(str(part.get('content','')))
        if part.get('type')==2 and safe_url(part.get('url')):links.append({'name':part.get('label') or 'Open link','url':part['url']})
        if part.get('type')==12:
            for item in part.get('items',[])[:10]:
                media=item.get('media') or {}
                url=safe_url(media.get('proxy_url') or media.get('url'))
                if url:links.append({'name':item.get('description') or 'View image','url':url})
        children=part.get('components',[])
        accessory=part.get('accessory')
        if isinstance(accessory,dict):children=[*children,accessory]
        if children:
            sub,more=component_text(children);text.extend(sub);links.extend(more)
        if part.get('type') in (11,13):
            media=part.get('media') or part.get('file') or {}
            url=safe_url(media.get('proxy_url') or media.get('url'))
            if url:links.append({'name':'View attachment','url':url})
    return text,links

def message_view(row):
    author=row.get('author') or {}
    texts=[row.get('content') or '']
    extra,links=component_text(row.get('components') or [])
    texts.extend(extra)
    for embed in (row.get('embeds') or [])[:10]:
        texts.extend(str(embed.get(key) or '') for key in ('title','description'))
        for field in (embed.get('fields') or [])[:25]:texts.append(str(field.get('name',''))+'\n'+str(field.get('value','')))
        for key in ('image','thumbnail'):
            url=safe_url((embed.get(key) or {}).get('proxy_url') or (embed.get(key) or {}).get('url'))
            if url:links.append({'name':'View image','url':url})
    for item in (row.get('attachments') or [])[:10]:
        url=safe_url(item.get('url'))
        if url:links.append({'name':str(item.get('filename') or 'Attachment'),'url':url})
    text='\n\n'.join(t for t in texts if t).strip()
    for member in row.get('mentions') or []:
        text=re.sub(r'<@!?'+re.escape(str(member.get('id','')))+r'>',lambda _: '@'+str(member.get('global_name') or member.get('username') or 'member'),text)
    return {'id':str(row['id']), 'author':author.get('global_name') or author.get('username') or 'Discord',
            'at':row.get('timestamp'), 'edited':bool(row.get('edited_timestamp')), 'text':text,
            'attachments':links, 'bot':bool(author.get('bot'))}

async def conversation(request):
    ticket_id=request.match_info['ticket_id']
    if not re.fullmatch(r'ticket_[0-9]{1,22}',ticket_id):raise web.HTTPNotFound(text='Ticket not found.')
    space=request.query.get('space','applicant')
    if space not in {'applicant','staff'}:raise web.HTTPBadRequest(text='Choose a conversation.')
    before=request.query.get('before','')
    if before and not re.fullmatch(r'[0-9]{1,22}',before):raise web.HTTPBadRequest(text='Invalid message page.')
    async with mongo(request) as db:
        actor=await authorize(request,db)
        row=await db.tickets.find_one({**RUNTIME_FILTER,'guild_id':GUILD_ID,'_id':ticket_id}, BROWSE_PROJECTION)
    if not row:raise web.HTTPNotFound(text='Ticket not found.')
    location=row.get('location') or {}
    channel_id=str(location.get('staff_space_id' if space=='staff' else 'id') or '')
    if not channel_id.isdigit():raise web.HTTPNotFound(text='This ticket has no saved Discord thread.')
    # Always recheck live authorization, even when returning cached messages.
    try:
        channel=await check_thread(request,actor,channel_id)
    except web.HTTPNotFound as exc:
        raise web.HTTPNotFound(text='This Discord thread is no longer available. No saved conversation is available.') from exc
    cache=request.app.setdefault('ticket_message_cache',{})
    key=(channel_id,before)
    now=time.monotonic()
    for old in list(cache):
        if now-cache[old][0]>=15:cache.pop(old,None)
    if key in cache:
        payload=cache[key][1]
    else:
        raw=await discord(request,'GET',f'/channels/{channel_id}/messages',params={'limit':'50',**({'before':before} if before else {})})
        payload={'messages':[message_view(item) for item in reversed(raw)], 'older':str(raw[-1]['id']) if len(raw)==50 else None,'checked_at':time.time()}
        if len(cache)>=128:cache.pop(next(iter(cache)))
        cache[key]=(now,payload)
    response=web.json_response({**payload,'ticket':public_ticket(row),'archived':bool((channel.get('thread_metadata') or {}).get('archived')),
                              'discord_url':f'https://discord.com/channels/{GUILD_ID}/{channel_id}'})
    response.headers['Cache-Control']='no-store'
    return response

routes=[web.get(API+'/tickets',listing),web.get(API+'/tickets/{ticket_id}/messages',conversation)]
