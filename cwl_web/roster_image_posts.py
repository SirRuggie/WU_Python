"""Staff authorization and HTTP adaptation for roster image delivery."""
import re
from aiohttp import web
from utils.cwl_roster_image_store import RosterImageStore
from .server_management import discord, GUILD_ID


def staff(request, *, send=False):
    from .app import _require, _owner
    from .access_control import request_scopes
    actor = _require(request, 'editor')
    if send and not _owner(actor) and 'cwl_send' not in request_scopes(request, actor['user_id']):
        raise web.HTTPForbidden(text='You do not have permission for this CWL action.')
    return actor


def store(request):
    return RosterImageStore(request.app['store'])


async def channels(request):
    staff(request, send=True)
    return web.json_response({'channels': store(request).channels()})


async def configure(request):
    from .app import _json
    actor = staff(request, send=True)
    body = await _json(request)
    if set(body) != {'pool', 'channel_id'} or body.get('pool') not in ('main', 'lazy'):
        raise web.HTTPBadRequest(text='Choose Main or Lazy and a text channel.')
    channel = body['channel_id']
    if not isinstance(channel, str) or not re.fullmatch(r'\d{15,22}', channel):
        raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    destination = await discord(request, 'GET', f'/channels/{channel}')
    if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0, 5):
        raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    return web.json_response(store(request).configure(body['pool'], channel, str(destination.get('name') or channel), actor['user_id']))


async def posts(request):
    from .app import _sid, _season
    staff(request)
    sid = _sid(request)
    with request.app['store'].tx() as db:
        _season(db, sid)
    return web.json_response(store(request).posts(sid))


def routes():
    return [web.get('/api/cwl/roster-image-channels', channels),
            web.put('/api/cwl/roster-image-channels', configure),
            web.get('/api/cwl/seasons/{season_id}/roster-image-posts', posts)]
