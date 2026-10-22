"""Owner-only access editing and live request authorization."""
import json
from aiohttp import web
from pymongo.write_concern import WriteConcern
from utils.dashboard_access import (
    AccessRepository, AccessConflict, PERMISSIONS, GROUPS, OWNER_IDS, effective, expand_legacy,
)


def repository(db):
    collection = db.bot_config
    if hasattr(collection, 'with_options'):
        collection = collection.with_options(write_concern=WriteConcern(w='majority', j=True))
    return AccessRepository(collection)


def legacy_document(store):
    grants = []
    for row in store.rows('SELECT * FROM grants'):
        if row['user_id'] in OWNER_IDS:
            continue  # Owners are protected identities, never editable grant entries.
        values = json.loads(row['permissions'])
        permissions = expand_legacy(values)
        if 'clans' in values:
            permissions.add('clan_weights')
        grants.append(dict(kind='user', id=row['user_id'], label=row['user_id'], permissions=sorted(permissions)))
    return dict(revision=0, legacy=True, grants=grants, history=[])


@web.middleware
async def access_context(request, handler):
    from .app import COOKIE, _session
    from .server_management import mongo, discord, GUILD_ID
    public_paths = {'/api/cwl/auth/discord', '/api/cwl/auth/callback', '/api/cwl/config', '/api/cwl/dev/login'}
    if request.path in public_paths or not request.path.startswith('/api/cwl/') or not request.cookies.get(COOKIE):
        return await handler(request)
    session = _session(request)
    if session['user_id'] in OWNER_IDS:
        request['dashboard_permissions'] = set(PERMISSIONS)
        return await handler(request)
    # Isolated fixture apps use local legacy grants and never contact Discord.
    if request.app.get('dev_fixture') or not request.app.get('live_access'):
        return await handler(request)
    async with mongo(request) as db:
        document = await repository(db).read()
    if document is not None:
        roles = []
        if any(g['kind'] == 'role' for g in document['grants']):
            try:
                member = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{session["user_id"]}')
                roles = member.get('roles', [])
            except web.HTTPNotFound:
                roles = []
            except (web.HTTPServiceUnavailable, web.HTTPForbidden):
                roles = []
                request['access_warning'] = 'Discord roles could not be checked. Role-based staff access is unavailable; try again shortly.'
            # No cached role membership is used on failure; direct grants remain valid.
        request['dashboard_permissions'] = effective(document, session['user_id'], roles)
    return await handler(request)


def public_document(document):
    return {key: document[key] for key in ('revision', 'grants', 'history')} | {
        'owners': sorted(OWNER_IDS),
        'groups': [{'label': label, 'permissions': [dict(id=p, label=PERMISSIONS[p][0], description=PERMISSIONS[p][1]) for p in values]} for label, values in GROUPS.items()],
    }


async def access(request):
    from .app import _require, _store
    from .server_management import mongo
    _require(request, 'owner')
    async with mongo(request) as db:
        document = await repository(db).read()
    return web.json_response(public_document(document or legacy_document(_store(request))))


async def save(request):
    from .app import _require, _json, _store
    from .server_management import mongo, discord, GUILD_ID
    actor = _require(request, 'owner')
    body = await _json(request)
    kind, subject = body.get('kind'), body.get('id')
    revision, permissions = body.get('revision'), body.get('permissions')
    if kind not in ('user', 'role') or not isinstance(subject, str) or not subject.isdigit() or not 1 <= len(subject) <= 25:
        raise web.HTTPBadRequest(text='Choose a member or role.')
    if type(revision) is not int or revision < 0:
        raise web.HTTPBadRequest(text='Reload access before saving.')
    if (kind == 'user' and subject in OWNER_IDS) or (kind == 'role' and subject == str(GUILD_ID)):
        raise web.HTTPBadRequest(text='Owners and @everyone cannot be edited here.')
    if permissions is not None and (not isinstance(permissions, list) or not permissions or any(not isinstance(p, str) or p not in PERMISSIONS for p in permissions)):
        raise web.HTTPBadRequest(text='Choose at least one valid permission.')
    label = subject
    if permissions is not None:
        if kind == 'role':
            roles = await discord(request, 'GET', f'/guilds/{GUILD_ID}/roles')
            role = next((r for r in roles if str(r['id']) == subject), None)
            if not role or role.get('managed'):
                raise web.HTTPBadRequest(text='Choose an available server role.')
            label = role['name']
        else:
            member = await discord(request, 'GET', f'/guilds/{GUILD_ID}/members/{subject}')
            user = member.get('user', {})
            label = member.get('nick') or user.get('global_name') or user.get('username') or subject
    async with mongo(request) as db:
        repo = repository(db)
        document = await repo.read() or legacy_document(_store(request))
        try:
            saved = await repo.save(document, revision=revision, actor_id=actor['user_id'], kind=kind, subject_id=subject, permissions=permissions, label=label)
        except AccessConflict as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
    return web.json_response(public_document(saved))


async def roles(request):
    from .app import _require
    from .server_management import discord, GUILD_ID
    _require(request, 'owner')
    rows = await discord(request, 'GET', f'/guilds/{GUILD_ID}/roles')
    return web.json_response({'roles': [{'id': str(r['id']), 'name': r['name']} for r in rows if not r.get('managed') and str(r['id']) != str(GUILD_ID)]})
