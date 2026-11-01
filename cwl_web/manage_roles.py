"""Discord role tools using the same hierarchy helpers as /manage."""
import re
import asyncio
import time
import unicodedata
from uuid import UUID
from types import SimpleNamespace as NS
from aiohttp import web
from .server_management import API, GUILD_ID, discord, require_manage, mongo
from extensions.commands.recruit import perms
from utils.role_permissions import role_is_manageable


def member(data, guild_id=GUILD_ID):
    return NS(id=int(data['user']['id']), role_ids=tuple(map(int, data.get('roles', []))), guild_id=guild_id)


def role(data):
    return NS(id=int(data['id']), name=data['name'], position=int(data.get('position', 0)),
              permissions=int(data.get('permissions', 0)), is_managed=data.get('managed', False))


def sid(value):
    if not isinstance(value, str) or not value.isdigit() or not 15 <= len(value) <= 22:
        raise web.HTTPBadRequest(text='Choose a valid Discord member or role.')
    return value


async def hierarchy(request, actor):
    me = await discord(request, 'GET', '/users/@me')
    bot_data = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{me["id"]}')
    roles = {int(r['id']): role(r) for r in actor['roles']}
    bot_member = member(bot_data)
    guild = NS(id=GUILD_ID, owner_id=int(actor['guild']['owner_id']), get_role=roles.get,
               get_member=lambda uid: bot_member if int(uid) == int(me['id']) else None)
    bot = NS(get_me=lambda: NS(id=int(me['id'])))
    return roles, guild, bot, member(actor['member'])


async def dashboard_grant_roles(request, actor):
    """Non-owners must not manage the roles that confer dashboard access."""
    from utils.dashboard_access import OWNER_IDS, AccessRepository
    if actor['user_id'] in OWNER_IDS:
        return set()
    async with mongo(request) as shared:
        policy = await AccessRepository(shared.bot_config).read()
    return {g['id'] for g in (policy or {}).get('grants', []) if g['kind'] == 'role'}


async def page(request):
    actor = await require_manage(request, 'roles')
    role_map, guild, bot, actor_member = await hierarchy(request, actor)
    protected = await dashboard_grant_roles(request, actor)
    options = [{'value': str(r.id), 'label': r.name} for r in role_map.values()
               if str(r.id) not in protected and role_is_manageable(guild, bot, r) and perms.actor_can_manage_role(actor_member, guild, r)]
    current_role_options = [{'value': str(r.id), 'label': r.name} for r in role_map.values() if r.id != GUILD_ID]
    return web.json_response({'id': 'roles', 'label': 'Member roles', 'description': 'Choose a member and roles, then add or remove them.',
        'group': 'Server', 'revision': 'live', 'fields': [
            {'key': 'member_id', 'label': 'Member', 'type': 'member', 'value': '', 'required': True, 'options': [], 'current_role_options': current_role_options},
            {'key': 'role_ids', 'label': 'Roles', 'type': 'multiselect', 'value': [], 'required': True, 'options': options}],
        'actions': [
            {'id': 'add', 'endpoint': API + '/roles/add', 'label': 'Add roles', 'confirm': 'Add the selected roles to this member?'},
            {'id': 'remove', 'endpoint': API + '/roles/remove', 'label': 'Remove roles', 'confirm': 'Remove the selected roles from this member?'}],
        'action_only': True})


def member_option(data, role_names=None):
    user = data['user']
    user_id = str(user['id'])
    username = str(user.get('username') or user_id)
    display_name = str(data.get('nick') or user.get('global_name') or username)
    avatar = data.get('avatar') or user.get('avatar')
    if isinstance(avatar, str) and re.fullmatch(r'[a-zA-Z0-9_]+', avatar):
        folder = f'guilds/{GUILD_ID}/users/{user_id}/avatars' if data.get('avatar') else f'avatars/{user_id}'
        extension = 'gif' if avatar.startswith('a_') else 'png'
        avatar_url = f'https://cdn.discordapp.com/{folder}/{avatar}.{extension}?size=64'
    else:
        discriminator = str(user.get('discriminator') or '0')
        index = int(discriminator) % 5 if discriminator.isdigit() and int(discriminator) else (int(user_id) >> 22) % 6
        avatar_url = f'https://cdn.discordapp.com/embed/avatars/{index}.png'
    return {'value': user_id, 'id': user_id, 'label': f'{display_name} (@{username})',
            'display_name': display_name, 'username': username, 'avatar_url': avatar_url,
            'role_ids': [str(value) for value in data.get('roles', [])],
            'role_names': [(role_names or {}).get(str(value), str(value)) for value in data.get('roles', [])]}


def search_text(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


async def searchable_members(request, *, force=False):
    """Discord's search is prefix-only. Cache a complete paged directory instead."""
    state = request.app.setdefault('member_search_directory', {'lock': asyncio.Lock()})
    async with state['lock']:
        if not force and time.monotonic() - state.get('loaded_at', -1000) < 60:
            return state['rows']
        rows = []
        after = None
        while True:
            page = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members',
                                 params={'limit': '1000', **({'after': after} if after else {})})
            rows.extend(page)
            if len(page) < 1000:
                break
            cursor = str(page[-1]['user']['id'])
            if cursor == after:
                raise web.HTTPServiceUnavailable(text='Member list could not finish loading. Try again.')
            after = cursor
        state.update(rows=rows, loaded_at=time.monotonic())
        return rows


async def members(request):
    try:
        actor = await require_manage(request, 'roles')
    except web.HTTPForbidden:
        # Ticket staff can select testers without receiving role-edit access.
        actor = await require_manage(request, 'ticket_settings')
    role_names = {str(row['id']): row['name'] for row in (actor or {}).get('roles', [])}
    query = request.query.get('q', '').strip()
    if len(query) > 80:
        raise web.HTTPBadRequest(text='Keep member searches under 81 characters.')
    after = request.query.get('after')
    exact_id = request.query.get('id')
    if after:
        sid(after)
    if exact_id and (query or after):
        raise web.HTTPBadRequest(text='Choose a member by ID or search by name, not both.')
    if query and after:
        raise web.HTTPBadRequest(text='Search cannot be combined with a member-list page.')
    mode = 'browse'
    next_page = None
    truncated = False
    try:
        if exact_id or (query.isdigit() and len(query) >= 15):
            data = [await discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{sid(exact_id or query)}')]
            mode = 'member'
        elif query:
            needle = search_text(query)
            directory = await searchable_members(request)
            matches = [row for row in directory if any(needle in search_text(value) for value in
                       (row.get('nick'), row['user'].get('global_name'), row['user'].get('username')))]
            matches.sort(key=lambda row: (search_text(row.get('nick') or row['user'].get('global_name') or row['user'].get('username')), int(row['user']['id'])))
            data = matches[:100]
            mode = 'search'
            truncated = len(matches) > 100
        else:
            data = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members', params={'limit': '50', **({'after': after} if after else {})})
            if len(data) == 50:
                next_page = str(data[-1]['user']['id'])
    except web.HTTPForbidden as exc:
        raise web.HTTPForbidden(text='Discord blocked member lookup. Ask an owner to check the bot’s server access and Server Members Intent.') from exc
    return web.json_response({'options': [member_option(row, role_names) for row in data],
                              'next': next_page, 'truncated': truncated, 'mode': mode})


async def change(request):
    actor = await require_manage(request, 'roles', write=True)
    operation = request.match_info['action']
    if operation not in ('add','remove'):
        raise web.HTTPNotFound()
    body = await request.json()
    if not isinstance(body, dict) or set(body) - {'revision', 'values', 'request_id'}:
        raise web.HTTPBadRequest(text='Choose one member and their roles.')
    # The dashboard supplies a request UUID; Discord role PUT/DELETE operations
    # remain idempotent, with current membership checked again on each request.
    if 'request_id' in body:
        try:
            request_id = body['request_id']
            if not isinstance(request_id, str) or str(UUID(request_id)) != request_id.lower():
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(text='Refresh this page and try the role change again.') from None
    values = body.get('values', {})
    if not isinstance(values, dict) or set(values) - {'member_id', 'role_ids'}:
        raise web.HTTPBadRequest(text='Choose one member and their roles.')
    target_id = sid(values.get('member_id'))
    selected = values.get('role_ids', [])
    if not isinstance(selected, list) or not 1 <= len(selected) <= 25 or len(set(map(str, selected))) != len(selected):
        raise web.HTTPBadRequest(text='Choose between 1 and 25 different roles.')
    selected = [sid(value) for value in selected]
    protected = await dashboard_grant_roles(request, actor)
    if protected.intersection(selected):
        raise web.HTTPForbidden(text='Only dashboard owners can add or remove roles that grant dashboard access.')
    target_data = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{target_id}')
    roles, guild, bot, actor_member = await hierarchy(request, actor)
    target = member(target_data)
    if not perms.actor_can_manage_member(actor_member, target, guild):
        raise web.HTTPForbidden(text='You can only change roles for members below your highest role. The server owner is excluded.')
    for selected_id in selected:
        candidate = roles.get(int(selected_id))
        if not role_is_manageable(guild, bot, candidate) or not perms.actor_can_manage_role(actor_member, guild, candidate):
            raise web.HTTPForbidden(text='One of these roles cannot be changed by you or the bot. No roles were changed.')
    changed, skipped = [], []
    for selected_id in selected:
        already = int(selected_id) in target.role_ids
        if already == (operation == 'add'):
            skipped.append(roles[int(selected_id)].name)
            continue
        try:
            await discord(request, 'PUT' if operation == 'add' else 'DELETE', f'/guilds/{GUILD_ID}/members/{target_id}/roles/{selected_id}')
        except web.HTTPException as exc:
            raise web.HTTPServiceUnavailable(text=f"Discord stopped the update after {len(changed)} role changes. Refresh this member before trying again.") from exc
        changed.append(roles[int(selected_id)].name)
    return web.json_response({'message': f"{'Added' if operation == 'add' else 'Removed'} {len(changed)} roles. {len(skipped)} already correct.", 'changed': changed, 'skipped': skipped})


async def role_members(request):
    await require_manage(request, 'roles')
    role_id = sid(request.match_info['role_id'])
    after = request.query.get('after')
    if after:
        sid(after)
    data = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members', params={'limit':'1000', **({'after':after} if after else {})})
    members = []
    for row in data:
        if role_id not in row.get('roles', []):
            continue
        profile = member_option(row)
        members.append({'id': str(row['user']['id']), 'name': row.get('nick') or row['user'].get('global_name') or row['user']['username'],
                        'discord_profile': {key: profile.get(key) for key in ('id', 'display_name', 'username', 'avatar_url')}})
    return web.json_response({'members': members, 'next': str(data[-1]['user']['id']) if len(data) == 1000 else None})


routes = [web.get(API+'/roles', page), web.get(API+'/members', members), web.get(API+'/roles/{role_id}/members', role_members), web.post(API+'/roles/{action}', change)]
