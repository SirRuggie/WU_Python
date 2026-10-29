"""Owner-only HTTP adapter for the dashboard Easter egg."""

import logging
import os
from pathlib import Path

from aiohttp import web

from utils.owner_prank_store import InvalidEvent, StaleRun, apply, read, signup_count
from .access_control import OWNER_IDS
from .server_management import discord


API = '/api/cwl/prank'
ASSETS = Path(__file__).with_name('owner_prank_assets')
ASSET_NAMES = frozenset({
    '78096.webp', '97730.webp', '102860.webp',
    '97711.webp', '160053.webp', '102809.webp', '102888.webp',
    '102845.webp', 'final-aq.webp',
})
TITLES = (
    '', 'Remove all signups?', 'Working...', 'HEY!! WHAT ARE YOU DOING?!',
    'Buttons Fear You', 'Trust Me, He Says', 'Relax, Nothing Broke',
    "We've Got Your Back", 'A Promise From Your Troops', 'Sound Familiar Yet?',
    "YOU'VE BEEN RICKROLLED!", 'LOL. You Thought.', 'A Message From Your Troops',
    'Am I Annoying You Yet?', 'One Last Thing, Chief...', 'Well, Look Who Survived.',
)
MESSAGES = {
    'prank_opened': '😈 He opened the bait. The trap is officially armed.',
    'prank_bait_yes': '💀 HE PRESSED YES. On "remove all signups." Our fearless owner, everyone.',
    'prank_bait_no': '😂 He pressed NO. Surprisingly responsible. Unfortunately, Ruggie planned for that.',
    'prank_jumpscare_seen': '🧙 Wizard deployed. Chief is now being professionally yelled at.',
    'prank_rickroll_seen': '🎶 WE GOT HIM. Rickroll delivered. Ruggie wins.',
    'prank_encore_1': '🤣 First escape attempt. He genuinely thought it was over.',
    'prank_encore_2': '💀 Second attempt. The Minion has entered the disrespect phase.',
    'prank_encore_3': "😂 Third attempt. Chief's patience is now at 1 HP.",
    'prank_encore_4': '🏳️ Fourth attempt. He is actively negotiating his release.',
    'prank_completed': '👑 Chief survived the entire prank. The Queen finally released him. Warriors United lives another day.',
}
LOG = logging.getLogger(__name__)


def _config():
    if os.getenv('PRANK_ENABLED', '').strip().lower() != 'true':
        return None
    notify = os.getenv('PRANK_NOTIFY_USER_ID', '').strip()
    target = os.getenv('PRANK_TARGET_USER_ID', '').strip()
    if not notify.isdecimal() or not target.isdecimal() or notify == target:
        return None
    if notify not in OWNER_IDS or target not in OWNER_IDS:
        return None
    return notify, target


def _actor(request):
    from .app import _session, _store
    config = _config()
    if not config:
        raise web.HTTPNotFound()
    try:
        session = _session(request)
    except web.HTTPException:
        raise web.HTTPNotFound() from None
    user_id = session['user_id']
    if user_id not in config:
        raise web.HTTPNotFound()
    return user_id, config, session, _store(request)


def _response(state, store, user_id, config):
    return web.json_response({
        'card': state['card'], 'branch': state['branch'],
        'completed_at': state['completed_at'], 'run': state['run'],
        'signup_count': signup_count(store),
        'can_replay': user_id == config[0] and bool(state['completed_at']),
    })


async def state(request):
    user_id, config, _, store = _actor(request)
    return _response(read(store, user_id), store, user_id, config)


async def event(request):
    user_id, config, _, store = _actor(request)
    from .app import _require
    _require(request)  # Reuses the dashboard's constant-time CSRF check.
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text='Expected JSON object.') from None
    if not isinstance(body, dict) or set(body) - {'event', 'card', 'branch', 'run'}:
        raise web.HTTPBadRequest(text='Invalid prank event.')
    try:
        updated, claimed = apply(store, user_id, body.get('event'), body.get('card'),
                                 body.get('run'), body.get('branch'),
                                 can_replay=user_id == config[0])
    except StaleRun as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    except InvalidEvent as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    if claimed:
        message = (f"🚪 Chief escaped early at card {body['card']}: "
                   f"{TITLES[body['card']]}. He couldn't handle the full Ruggie experience."
                   if claimed == 'prank_closed_early' else MESSAGES[claimed])
        if user_id == config[0]:
            message = '[TEST] ' + message
        try:
            channel = await discord(request, 'POST', '/users/@me/channels',
                                    json={'recipient_id': config[0]})
            await discord(request, 'POST', f"/channels/{channel['id']}/messages",
                          json={'content': message, 'allowed_mentions': {'parse': []}})
        except Exception:
            LOG.exception('Owner prank milestone delivery failed after durable claim')
    return _response(updated, store, user_id, config)


async def asset(request):
    _actor(request)
    name = request.match_info['name']
    if name not in ASSET_NAMES:
        raise web.HTTPNotFound()
    path = ASSETS / name
    if not path.is_file():
        raise web.HTTPNotFound()
    response = web.FileResponse(path)
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


routes = [web.get(API + '/state', state), web.post(API + '/event', event),
          web.get(API + '/assets/{name}', asset)]
