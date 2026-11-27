"""HTTP adaptation for the guild self-select role list and shared safe choices."""
import json

from aiohttp import web

from utils import server_roles as repository
from utils.role_permissions import role_is_self_selectable, actor_can_manage_role
from . import server_management as shared
from .manage_roles import hierarchy, dashboard_grant_roles


PATH = '/manage/server-roles'
ROLE_ERROR = "Select an unmanaged role with no permissions, below the app's highest role."


async def role_choices(request, actor):
    roles, guild, bot, person = await hierarchy(request, actor)
    protected = await dashboard_grant_roles(request, actor, include_owner=True)
    options = [dict(value=str(role.id), label=role.name, color=int(getattr(role, 'color', 0) or 0))
               for role in roles.values()
               if role_is_self_selectable(guild, bot, role)
               and actor_can_manage_role(person, guild, role)
               and str(role.id) not in protected]
    options.sort(key=lambda item: (item['label'].casefold(), item['value']))
    return options, {str(role.id): role.name for role in roles.values()}


async def require_safe_roles(request, actor, identifiers):
    options, names = await role_choices(request, actor)
    safe = {item['value'] for item in options}
    if any(str(identifier) not in safe for identifier in identifiers if identifier):
        raise web.HTTPBadRequest(text=ROLE_ERROR)
    return options, names


def document(row, options, conflicts=()):
    return dict(id='server_roles', label='Server roles',
                description='Roles members select in Roles and clan links.', group='Server',
                endpoint=PATH, revision=row['revision'], fields=[dict(
                    key='roles', label='Server roles', type='server_roles',
                    value=json.dumps(row['roles'], separators=(',', ':')), options=options,
                    role_conflicts=sorted({item['role_id'] for item in conflicts}))])


async def read(request):
    actor = await shared.require_manage(request, 'roles')
    options, _names = await role_choices(request, actor)
    async with shared.mongo(request) as mongo:
        row = await repository.load(mongo, shared.GUILD_ID)
        conflicts = await repository.town_hall_conflicts(mongo, shared.GUILD_ID, row['roles'])
    return web.json_response(document(row, options, conflicts))


async def save(request):
    from .app import _json
    actor = await shared.require_manage(request, 'roles', write=True)
    body = await _json(request)
    if not isinstance(body, dict) or type(body.get('revision')) is not int or not isinstance(body.get('values'), dict) or set(body['values']) != {'roles'}:
        raise web.HTTPBadRequest(text='Review the server roles before saving.')
    try:
        entries = repository.validate(json.loads(body['values']['roles']))
        options, _names = await require_safe_roles(request, actor, [item['role_id'] for item in entries])
        async with shared.mongo(request) as mongo:
            row = await repository.save(mongo, shared.GUILD_ID, entries, actor['user_id'], body['revision'])
    except repository.ServerRoleOverlap as error:
        raise web.HTTPBadRequest(text=str(error)) from None
    except repository.ServerRolesConflict as error:
        raise web.HTTPConflict(text=str(error)) from None
    except (ValueError, TypeError, KeyError) as error:
        raise web.HTTPBadRequest(text='Review every server role field before saving.') from error
    return web.json_response(document(row, options) | {'saved': True})


routes = [web.get(shared.API + '/server-roles', read), web.patch(shared.API + '/server-roles', save)]
