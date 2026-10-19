"""Owner-granted text command editor with optimistic updates."""
from datetime import datetime, timezone
from uuid import uuid4
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from utils.text_commands import collection, validate, command_name, GUILD_ID, FIELDS, legacy_blocks
from .server_management import API, mongo, require_manage


def public(row):
    return {**{key:row.get(key,'') for key in ('command','text','title','description','image_url')},'enabled':row.get('enabled',True),'color':row.get('color','#e2b332'),'allow_pings':row.get('allow_pings',False),'choose_recipient':row.get('choose_recipient',False),'recipient_ping':row.get('recipient_ping',False),'blocks':row.get('blocks',legacy_blocks(row)),'revision':row['revision']}


async def listing(request):
    await require_manage(request, 'text_commands')
    async with mongo(request) as db:
        rows = await collection(db).find({'guild_id': GUILD_ID}).sort('command', 1).to_list(length=None)
    return web.json_response({'commands': [public(row) for row in rows]})


async def save(request):
    actor = await require_manage(request, 'text_commands', write=True)
    body = await (request.clone(client_max_size=256*1024) if isinstance(request,web.Request) else request).json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='Check the command fields.')
    try:
        values = validate(body.get('values'))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    from .command_images import preserve_images
    values=await preserve_images(request,values)
    revision = uuid4().hex
    now = datetime.now(timezone.utc)
    row = {**values, 'guild_id': GUILD_ID, 'revision': revision, 'updated_at': now, 'updated_by': actor['user_id']}
    async with mongo(request) as db:
        from utils.text_command_files import load_files
        from utils.text_command_actions import actions
        try:
            await load_files(db,values,metadata_only=True)
            for _,action in actions(values):
                if action['kind']!='reply':
                    await check_role(request,actor,action['role_id']);continue
                if action['command']!=values['command'] and not await collection(db).find_one({'_id':f'{GUILD_ID}:{action["command"]}','enabled':True}):raise ValueError('Choose an enabled saved reply.')
        except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
        target = collection(db)
        if request.method == 'POST':
            row.update(_id=f'{GUILD_ID}:{values["command"]}', created_at=now, created_by=actor['user_id'])
            try:
                await target.insert_one(row)
            except DuplicateKeyError:
                raise web.HTTPConflict(text='This command already exists. Select it to edit.') from None
        else:
            try:
                name = command_name(request.match_info['name'])
            except ValueError as exc:
                raise web.HTTPBadRequest(text=str(exc)) from None
            if name != values['command']:
                raise web.HTTPBadRequest(text='Create a new command to use a different name.')
            if not isinstance(body.get('revision'), str) or not body['revision']:
                raise web.HTTPBadRequest(text='Reload this command before saving.')
            before = await target.find_one({'_id': f'{GUILD_ID}:{name}'})
            if not before or before.get('revision') != body['revision']:
                raise web.HTTPConflict(text='This command changed or was deleted. Reload before saving.')
            from .change_history import begin, finish
            history_id = await begin(db, API+'/text-commands/'+name, actor,
                                     {key:value for key,value in public(before).items() if key!='revision'},
                                     getattr(request,'history_action','edit'))
            result = await target.update_one({'_id': f'{GUILD_ID}:{name}', 'revision': body['revision']}, {'$set': row})
            if not result.matched_count:
                raise web.HTTPConflict(text='This command changed or was deleted. Reload before saving.')
            await finish(db, history_id, values)
    return web.json_response(public(row), status=201 if request.method == 'POST' else 200)


async def delete(request):
    await require_manage(request, 'text_commands', write=True)
    body = await request.json()
    if not isinstance(body, dict) or not isinstance(body.get('revision'), str) or not body['revision']:
        raise web.HTTPBadRequest(text='Reload this command before deleting.')
    try:
        name = command_name(request.match_info['name'])
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    async with mongo(request) as db:
        result = await collection(db).delete_one({'_id': f'{GUILD_ID}:{name}', 'revision': body['revision']})
    if not result.deleted_count:
        raise web.HTTPConflict(text='This command changed or was deleted. Reload before deleting.')
    return web.json_response({'ok': True})

async def mention_lookup(request):
    actor=await require_manage(request,'text_commands')
    query=request.query.get('q','').strip()
    kind=request.query.get('kind')
    if kind not in ('user','role') or not 2<=len(query)<=80:
        raise web.HTTPBadRequest(text='Type 2–80 characters to find a member or role.')
    from .manage_roles import searchable_members, search_text
    needle=search_text(query)
    if kind=='role':
        matches=[{'id':str(row['id']),'name':row['name']} for row in actor['roles'] if str(row['id'])!=str(GUILD_ID) and needle in search_text(row['name'])]
    else:
        directory=await searchable_members(request)
        matches=[]
        for member in directory:
            user=member['user'];name=member.get('nick') or user.get('global_name') or user['username']
            if any(needle in search_text(value or '') for value in (member.get('nick'),user.get('global_name'),user.get('username'))):
                matches.append({'id':str(user['id']),'name':name})
    return web.json_response({'matches':matches[:25]})

async def available_roles(request,actor):
    if 'trigger_role_choices' in request:return request['trigger_role_choices']
    from .manage_roles import hierarchy
    from utils.role_permissions import role_is_manageable
    from utils.text_command_roles import safe_role,protected_roles
    roles,guild,bot,_=await hierarchy(request,actor)
    async with mongo(request) as db:blocked=await protected_roles(db)
    choices=[{'id':str(r.id),'name':r.name} for r in roles.values() if safe_role(r,blocked) and role_is_manageable(guild,bot,r)]
    request['trigger_role_choices']=choices
    return choices

async def role_options(request):
    actor=await require_manage(request,'text_commands')
    return web.json_response({'roles':await available_roles(request,actor)})

async def check_role(request,actor,role_id):
    if not any(role['id']==role_id for role in await available_roles(request,actor)):
        raise ValueError('Choose a non-staff role below the bot’s highest role.')


async def role_activity(request):
    await require_manage(request,'text_commands')
    query={'guild_id':GUILD_ID}
    if request.query.get('command'):
        try:query['command']=command_name(request.query['command'])
        except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    async with mongo(request) as db:
        events=db.bot_config.database.get_collection('text_command_events')
        rows=await events.find(query).sort('at',-1).to_list(length=25)
    return web.json_response({'events':[{'id':r['_id'],'command':r['command'],'member':r.get('member_name',r['member_id']),'role':r.get('role_name',r['role_id']),'action':r['action'],'status':r['status'],'at':r['at'].isoformat()} for r in rows]})


async def upload_file(request):
    from utils.text_command_files import MAX_BYTES,store_file
    actor=await require_manage(request,'text_commands',write=True)
    if request.content_length is not None and request.content_length>MAX_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BYTES,actual_size=request.content_length)
    data=bytearray()
    async for chunk in request.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data)>MAX_BYTES:raise web.HTTPRequestEntityTooLarge(max_size=MAX_BYTES,actual_size=len(data))
    try:
        async with mongo(request) as db:result=await store_file(db,bytes(data),request.query.get('name','attachment.bin'),actor['user_id'])
    except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response(result)


routes = [web.get(API + '/text-command-activity', role_activity),web.get(API + '/text-command-roles', role_options),web.post(API + '/text-command-files', upload_file),web.get(API + '/text-command-mentions', mention_lookup),web.get(API + '/text-commands', listing), web.post(API + '/text-commands', save), web.patch(API + '/text-commands/{name}', save), web.delete(API + '/text-commands/{name}', delete)]

from .command_images import routes as image_routes
routes.extend(image_routes)
from .command_test import routes as test_routes
routes.extend(test_routes)
