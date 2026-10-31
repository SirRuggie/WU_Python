"""Authorized review and status for isolated full-post test jobs."""
import copy
import re
from urllib.parse import urlsplit

from aiohttp import web
from utils import cwl_campaign
from utils.cwl_web_bridge import campaign_generation
from utils.cwl_roster_image_store import RosterImageStore, ImageConflict
from utils.cwl_roster_messages import clan_image_message, closing_message
from .app import _json, _sid
from .manage_bridge import _mongo, _pool, _required_binding
from .roster_image_posts import staff
from .roster_sequence_review import frozen_plan
from .server_management import discord, GUILD_ID


def public_test(job):
    import json
    return {key: job[key] for key in ('request_id', 'status', 'next_step', 'error', 'channel_id')} | {
        'steps': len(json.loads(job['plan_json']))}


async def prepare(request):
    actor = staff(request, send=True)
    sid, pool = _sid(request), _pool(request)
    cycle = _required_binding(request, sid)
    body = await _json(request)
    if set(body) != {'channel_id', 'request_id', 'generation', 'body', 'roster_url', 'version'}:
        raise web.HTTPBadRequest(text='Review the full test before sending')
    channel, nonce = body['channel_id'], body['request_id']
    if (not isinstance(channel, str) or not re.fullmatch(r'\d{15,22}', channel)
            or not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{24}', nonce)
            or not isinstance(body['body'], str) or len(body['body']) > 4000
            or type(body['version']) is not int or body['version'] < 1
            or not isinstance(body['roster_url'], str)):
        raise web.HTTPBadRequest(text='Choose a test channel and valid published roster')
    try:
        url = urlsplit(body['roster_url'])
        valid_url = url.scheme == 'https' and url.hostname and not url.username and not url.password
    except ValueError:
        valid_url = False
    if not valid_url:
        raise web.HTTPBadRequest(text='Roster link must use HTTPS')
    storage = RosterImageStore(request.app['store'])
    prior = storage.test_sequence(nonce)
    if prior:
        # An exact reviewed request ID is a status replay, never another send.
        if (prior['season_id'], prior['pool'], prior['actor_id'], prior['channel_id'], prior['target_version']) != (sid, pool, str(actor['user_id']), channel, body['version']):
            raise web.HTTPConflict(text='Test request belongs to another review')
        return web.json_response({'test': public_test(prior)})
    destination = await discord(request, 'GET', f'/channels/{channel}')
    if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0, 5):
        raise web.HTTPBadRequest(text='Choose a text channel in this server')
    async with _mongo(request) as mongo:
        loaded = copy.deepcopy(await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle))
        if body['generation'] != campaign_generation(loaded):
            raise web.HTTPConflict(text='Message settings changed; review the test again')
        item = loaded['campaign']['messages']['roster']['variants'][pool]
        item['body'] = body['body']
        if item.get('buttons'):
            item['buttons'][0]['url'] = body['roster_url']
        else:
            item['buttons'] = [{'label': 'CWL Rosters', 'url': body['roster_url']}]
        try:
            components = await cwl_campaign.render_message(loaded, 'roster', pool, preview=True)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from None
    frozen = await frozen_plan(request, sid, pool, body['version'])
    plan = [{'kind': 'announcement', 'payload': {
        'components': [component.build()[0] for component in components],
        'flags': 32768, 'allowed_mentions': {'parse': [], 'roles': []},
    }}]
    for clan in frozen['clans']:
        payload = clan_image_message(clan['name'], clan['tag'], test=True)
        plan.append({**clan, 'kind': 'image', 'payload': payload,
                     'frozen': {**clan['frozen'], 'payload': payload}})
    plan.append({'kind': 'closing', 'payload': closing_message(test=True)})
    try:
        job = storage.prepare_test_sequence(request_id=nonce, sid=sid, pool=pool, version=body['version'],
                                           channel=channel, actor=str(actor['user_id']), plan=plan)
    except ImageConflict as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    return web.json_response({'test': public_test(job)}, status=202)


async def status(request):
    staff(request, send=True)
    job = RosterImageStore(request.app['store']).test_sequence(request.match_info['request_id'])
    if not job or job['season_id'] != _sid(request) or job['pool'] != _pool(request):
        raise web.HTTPNotFound(text='Test not found')
    return web.json_response({'test': public_test(job)})
