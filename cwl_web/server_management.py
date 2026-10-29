"""Shared, live Discord authorization for the web /manage interface."""
import asyncio
import os
import json
from contextlib import asynccontextmanager

import aiohttp
from aiohttp import web
from utils.mongo import MongoClient

API = '/api/cwl/manage'
GUILD_ID = 644963518025826315


@asynccontextmanager
async def mongo(request):
    injected = request.app.get('server_management_mongo')
    if injected is not None:
        yield injected
        return
    uri = os.getenv('MONGODB_URI', '').strip()
    if not uri:
        raise web.HTTPServiceUnavailable(text='Server settings are not connected.')
    from pymongo.errors import PyMongoError
    client = MongoClient(uri, serverSelectionTimeoutMS=5000, timeoutMS=15000)
    try:
        yield client
    except PyMongoError as exc:
        raise web.HTTPServiceUnavailable(text='Server settings are unavailable. Try again shortly.') from exc
    finally:
        await client.close()


class DiscordDeliveryUncertain(Exception):
    """Discord may have accepted the request; never retry automatically."""


async def discord(request, method, path, *, roster_delivery=False, **kwargs):
    injected = request.app.get('server_management_discord')
    if injected:
        return await injected(method, path, **kwargs)
    token = os.getenv('DISCORD_TOKEN', '').strip()
    if not token:
        raise web.HTTPServiceUnavailable(text='Discord connection is not configured.')
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as client:
            async with client.request(method, 'https://discord.com/api/v10' + path,
                    headers={'Authorization': 'Bot ' + token}, **kwargs) as response:
                if response.status == 404:
                    raise web.HTTPNotFound(text='This Discord member or item is no longer available.')
                if response.status == 403:
                    raise web.HTTPForbidden(text='Discord does not allow this action. Check bot permissions.')
                if response.status == 429 and roster_delivery:
                    data = await response.json()
                    wait = max(0.0, float(data.get('retry_after', 1)))
                    raise web.HTTPTooManyRequests(text=json.dumps({'retry_after': wait}), content_type='application/json')
                if response.status >= 500 and roster_delivery:
                    raise DiscordDeliveryUncertain('Discord response did not confirm delivery')
                if response.status == 429:
                    raise web.HTTPServiceUnavailable(text='Discord is busy. Wait a moment before trying again.')
                if response.status not in (200, 201, 204):
                    raise web.HTTPServiceUnavailable(text='Discord could not complete this request. Refresh before trying again.')
                return await response.json() if response.status != 204 else None
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        if roster_delivery:
            raise DiscordDeliveryUncertain('Discord delivery could not be confirmed') from exc
        raise web.HTTPServiceUnavailable(text='Discord is unavailable. Try again shortly.') from exc


async def identity(request):
    from .app import _require
    session = _require(request)
    if 'manage_identity' in request:
        return request['manage_identity']
    uid = session['user_id']
    member, roles, guild = await asyncio.gather(
        discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{uid}'),
        discord(request, 'GET', f'/guilds/{GUILD_ID}/roles'),
        discord(request, 'GET', f'/guilds/{GUILD_ID}'))
    role_ids = {int(value) for value in member.get('roles', [])}
    permissions = 0
    for role in roles:
        if int(role['id']) in role_ids | {GUILD_ID}:
            permissions |= int(role.get('permissions', 0))
    owner = str(guild.get('owner_id')) == uid
    if owner:
        permissions |= 8
    result = {'user_id': uid, 'role_ids': role_ids, 'permissions': permissions,
              'guild_owner': owner, 'member': member, 'roles': roles, 'guild': guild}
    from .access_control import request_scopes
    from .app import _store
    result['dashboard'] = True
    result['dashboard_scopes'] = sorted(request_scopes(request, uid))
    request['manage_identity'] = result
    return result


async def allowed(actor, section, db, *, write=False):
    if actor.get('dashboard'):
        from .access_control import dashboard_allowed
        return await dashboard_allowed(actor, section, db)
    admin = bool(actor['permissions'] & 8)
    roles = actor['role_ids']
    if section in {'recruit', 'recruitment_questions', 'recruitment_staff_thread'}:
        return admin or bool(actor['permissions'] & 32)
    if section == 'fwa_war_messages':
        return 769130325460254740 in roles
    if section == 'fwa_blacklist':
        return not write or 769130325460254740 in roles
    if section == 'fwa_bases':
        return 993015846442127420 in roles
    if section in {'fwa_points', 'fwa_sync', 'fwa_weight', 'band_monitor', 'cwl', 'cwl_rosters'}:
        return admin
    if section in {'roles', 'ticket_settings', 'ticket_testing'}:
        cfg = await db.ticket_setup.find_one({'_id': 'config'}) or {}
        if section == 'roles':
            configured = {int(cfg.get(key) or 0) for key in ('main_recruiter_role', 'fwa_recruiter_role')}
            return admin or bool(roles & (configured | {1003797104088592444}))
        target_admin = admin and int(cfg.get('ticket_target_guild_id') or 0) == GUILD_ID
        if target_admin:
            return True
        if section == 'ticket_testing' and not write:
            from extensions.commands.tickets import testing_service
            window = await testing_service.active_window(testing_service.test_mongo(db))
            return bool(window and int(window.get('guild_id') or 0) == GUILD_ID and testing_service.user_allowed(window, int(actor['user_id']), roles, is_admin=False))
        return False
    return False


async def require_manage(request, section, *, write=False):
    actor = await identity(request)
    async with mongo(request) as db:
        if not await allowed(actor, section, db, write=write):
            raise web.HTTPForbidden(text='You do not have access to this dashboard area. Ask a server owner.')
    return actor


async def catalog(request):
    actor = await identity(request)
    async with mongo(request) as db:
        sections = []
        for key, label, description, group, endpoint in (
            ('roles', 'Member roles', 'Add or remove roles. See who has a role.', 'Server', '/manage/roles'),
            ('ticket_settings', 'Ticket settings', 'Choose ticket channels, staff, and wait times.', 'Recruitment', '/manage/ticket-settings'),
            ('ticket_testing', 'Test tickets', 'Try tickets in a separate test area.', 'Recruitment', '/manage/ticket-testing'),
            ('band_monitor', 'BAND monitor', 'Check the bot’s calendar connection and debug mode.', 'War', '/manage/operations/band_monitor'),
            ('fwa_points', 'FWA points', 'Manage watched clans and points checks.', 'War', '/manage/operations/fwa_points'),
            ('fwa_sync', 'FWA sync reminders', 'Manage calendar reminders and their channel.', 'War', '/manage/operations/fwa_sync'),
            ('fwa_weight', 'War weights', 'Manage Town Hall weight ranges.', 'War', '/manage/operations/fwa_weight'),
            ('fwa_blacklist', 'Clan blacklist', 'View or change the shared clan blacklist.', 'War', '/manage/operations/fwa_blacklist'),
            ('fwa_bases', 'FWA bases', 'Manage base links, images, and guidance.', 'War', '/manage/operations/fwa_bases'),
            ('cwl_rosters', 'CWL return reminders', 'Manage saved clans and return reminders.', 'War', '/manage/return-reminders'),
        ):
            sections.append(dict(id=key, label=label, description=description, group=group, endpoint=endpoint,
                                 allowed=await allowed(actor, key, db)))
    from .manage_content import catalog_sections
    sections.extend(await catalog_sections(request))
    from .app import _session, _editor
    from .access_control import request_scopes
    from .app import _owner
    permissions = request_scopes(request, actor['user_id'])
    owner = _owner(_session(request))
    if owner or 'cwl_reminders' in permissions:
        sections.append(dict(id='cwl-messages',label='CWL messages and reminders',description='Edit scheduled reminders.',group='War',allowed=True,destination='reminders'))
    if owner or 'cwl_roster' in permissions:
        sections.append(dict(id='cwl-roster',label='CWL roster builder',description='Assign accounts and compare hosting clans.',group='War',allowed=True,destination='roster'))

    return web.json_response({'sections': sections})


async def choices(request):
    actor = await identity(request)
    async with mongo(request) as db:
        if not any([await allowed(actor, key, db) for key in ('roles','ticket_settings','recruit','fwa_sync','fwa_bases','cwl_rosters','band_monitor')]):
            raise web.HTTPForbidden(text='Staff access is required.')
    channels = await discord(request, 'GET', f'/guilds/{GUILD_ID}/channels')
    return web.json_response({'channels': [{'value': str(c['id']), 'label': '#' + c['name'], 'type': c['type']} for c in channels if c['type'] in (0,5)],
                             'roles': [{'value': str(r['id']), 'label': r['name']} for r in actor['roles'] if not r.get('managed') and str(r['id']) != str(GUILD_ID)]})


routes = [web.get(API, catalog), web.get(API + '/choices', choices)]


async def queue_action(request, section, action, values, revision):
    import hashlib
    import json
    import time
    from pymongo.errors import DuplicateKeyError
    from utils.manage_web_worker import ACTIONS, WORKER_ID
    actor = await require_manage(request, section, write=not (section == 'ticket_testing' and action in ('main', 'fwa')))
    if (section, action) not in ACTIONS or not isinstance(values, dict) or len(json.dumps(values)) > 24000:
        raise web.HTTPBadRequest(text='Choose a supported action.')
    payload = dict(section=section, action=action, values=values, revision=revision, user_id=actor['user_id'], guild_id=GUILD_ID)
    if section=='ticket_settings' and getattr(request,'history_action',None)=='restore': payload['history_action']='restore'
    body = await request.json()
    operation_id = body.get('request_id') if isinstance(body, dict) else None
    if operation_id is not None:
        import uuid
        try:
            operation_id = str(uuid.UUID(operation_id))
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(text='Invalid action identifier. Reload and try again.') from None
    serialized = json.dumps(payload, sort_keys=True)
    key = 'manage-web:' + hashlib.sha256((actor['user_id'] + ':' + operation_id if operation_id else serialized).encode()).hexdigest()
    payload_hash = hashlib.sha256(serialized.encode()).hexdigest()
    async with mongo(request) as db:
        worker = await db.bot_config.find_one({'_id': WORKER_ID}) or {}
        if time.time() - worker.get('checked_at', 0) > 60:
            raise web.HTTPServiceUnavailable(text='The bot is not ready. Nothing was queued. Try again shortly.')
        try:
            await db.bot_config.insert_one({'_id':key, 'kind':'manage_web_request', **payload, 'status':'pending', 'created_at':time.time(), 'payload_hash':payload_hash})
        except DuplicateKeyError:
            pass
        saved = await db.bot_config.find_one({'_id':key})
        if saved.get('payload_hash') not in (None, payload_hash):
            raise web.HTTPConflict(text='This action identifier was already used with different settings.')
    return web.json_response({'request_id':key, 'status':saved['status'], 'status_url':'/manage/requests/'+key,
                             'message':saved.get('message') or 'Queued. Waiting for the bot.'})


async def request_status(request):
    from .app import _require
    session = _require(request)
    async with mongo(request) as db:
        row = await db.bot_config.find_one({'_id':request.match_info['request_id'], 'kind':'manage_web_request', 'user_id':session['user_id']})
    if not row:
        raise web.HTTPNotFound(text='This action is no longer available.')
    await require_manage(request, row['section'])
    return web.json_response({'status':row['status'], 'message':row.get('message') or 'Waiting for the bot.', 'result':row.get('result')})


routes.append(web.get(API+'/requests/{request_id}', request_status))
