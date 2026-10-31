"""Shared test destination; this endpoint never sends a message."""
import re
from aiohttp import web
from utils.cwl_roster_image_store import RosterImageStore, ImageConflict
from .roster_image_posts import staff
from .server_management import discord, GUILD_ID


async def read(request):
    staff(request, send=True)
    return web.json_response(RosterImageStore(request.app['store']).test_channel())


async def save(request):
    from .app import _json
    actor = staff(request, send=True)
    body = await _json(request)
    if (set(body) != {'channel_id', 'expected_revision'}
            or not isinstance(body['channel_id'], str)
            or not re.fullmatch(r'\d{15,22}', body['channel_id'])
            or type(body['expected_revision']) is not int or body['expected_revision'] < 0):
        raise web.HTTPBadRequest(text='Choose a test channel and a valid revision')
    channel = await discord(request, 'GET', '/channels/' + body['channel_id'])
    if (str(channel.get('guild_id')) != str(GUILD_ID) or channel.get('type') not in (0, 5)
            or str(channel.get('id')) != body['channel_id'] or not channel.get('name')):
        raise web.HTTPBadRequest(text='Choose a text or announcement channel in this server')
    try:
        result = RosterImageStore(request.app['store']).configure_test_channel(
            body['channel_id'], channel['name'], actor['user_id'], body['expected_revision'])
    except ImageConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    return web.json_response(result)
