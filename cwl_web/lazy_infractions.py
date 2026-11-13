"""Staff list and send of the Lazy CWL infractions post.

Reads stored results and saved reviews only. Sends Components V2 messages through the
shared announcement transport with no mentions. Uncertain sends are never retried automatically.
"""
import asyncio
import hashlib
import json
import re
from pathlib import Path

from aiohttp import web

from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUnavailable, DiscordTransport
from utils import cwl_bonus_announcement as announcement
from utils import cwl_lazy_infractions as render
from utils.cwl_bonus_raffle_store import now
from .bonus_raffle import _state
from .bonuses import _require_draft

API = '/api/cwl'
GUILD_ID = '644963518025826315'
FOOTER_PATH = Path(__file__).resolve().parents[1] / 'assets' / render.FOOTER_FILE
ACTION = 'lazy_infractions_announcement'


def collect(db, sid):
    """Return (blockers, data). Stored data only; no Discord or Clash call."""
    view = _state(db, sid)
    names = {c['tag']: c['name'] for c in view.get('clans') or ()}
    names.update({c['tag']: c['name'] for c in view.get('lazy_hosts') or ()})
    data = render.build(view['accounts'], names, view['cycle'])
    blockers = []
    if not data['cycle']:
        blockers.append('Select the CWL month in Results first.')
    elif not data['clans']:
        blockers.append('No players have infractions to post.')
    return blockers, data


async def preview(request):
    from .app import _require, _sid, _store
    _require(request, 'editor')
    sid = _sid(request)
    with _store(request).tx() as db:
        blockers, data = collect(db, sid)
    pages = []
    if data['clans']:
        try:
            pages = [render.preview_parts(p) for p in render.messages(data)]
        except ValueError as exc:
            blockers.append(str(exc))
    return web.json_response({
        'cycle': data['cycle'], 'label': data['label'], 'clans': data['clans'],
        'exceptions': data['exceptions'], 'blockers': blockers, 'pages': pages,
        'player_count': sum(len(c['players']) for c in data['clans']),
        'clan_count': len(data['clans']), 'fingerprint': render.fingerprint(data)})


def _prior(db, sid, request_id):
    rows = db.execute("SELECT after_json FROM bonus_audit WHERE season_id=? AND action=? "
                      "AND json_extract(after_json,'$.request_id')=? ORDER BY id", (sid, ACTION, request_id)).fetchall()
    return [json.loads(row['after_json']) for row in rows]


def _audit(db, sid, actor, record):
    db.execute('INSERT INTO bonus_audit(season_id,actor_id,action,before_json,after_json,created_at) VALUES (?,?,?,?,?,?)',
               (sid, actor, ACTION, None, json.dumps(record), now()))


def _url(channel_id, message_id):
    return f'https://discord.com/channels/{GUILD_ID}/{channel_id}/{message_id}'


async def send(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'channel_id', 'request_id', 'fingerprint'}:
        _fail(400, 'Review the infractions and select a channel')
    channel_id, request_id = body['channel_id'], body['request_id']
    if not isinstance(channel_id, str) or not re.fullmatch(r'[0-9]{15,22}', channel_id):
        _fail(400, 'Select a channel')
    if (not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{24}', request_id)
            or not isinstance(body['fingerprint'], str) or len(body['fingerprint']) != 64):
        _fail(400, 'Review the infractions again')
    sid = _sid(request)
    transport = request.app.get('announcement_transport') or DiscordTransport()

    def checked(db):
        _require_draft(db, sid, _fail)
        prior = _prior(db, sid, request_id)
        if prior:
            done = next((row for row in prior if row.get('status') in ('sent', 'failed', 'uncertain')), None)
            if done:
                return None, done
            _fail(409, 'This send was already requested. Check Discord before you send again.')
        blockers, data = collect(db, sid)
        if blockers:
            _fail(409, blockers[0])
        if render.fingerprint(data) != body['fingerprint']:
            _fail(409, 'The infractions changed. Review the preview again.')
        return data, None

    with _store(request).tx() as db:
        data, done = checked(db)
    if done:
        return web.json_response(done)
    try:
        channel = await transport.get_channel(channel_id)
    except (AnnouncementRejected, AnnouncementUnavailable, ValueError):
        _fail(503, 'Channel unavailable or outside this server. Select a usable server channel.')
    if channel['id'] != channel_id:
        _fail(503, 'Discord channel lookup did not match')
    try:
        pages = render.messages(data)
    except ValueError as exc:
        _fail(409, str(exc))
    footer = FOOTER_PATH.read_bytes()
    record = {'request_id': request_id, 'channel_id': channel_id, 'cycle': data['cycle'],
              'clans': [c['tag'] for c in data['clans']],
              'players': [p['tag'] for c in data['clans'] for p in c['players']], 'pages': len(pages)}
    with _store(request).tx() as db:
        _, done = checked(db)
        if done:
            return web.json_response(done)
        # The reservation is durable before Discord sees anything.
        _audit(db, sid, actor, {**record, 'status': 'sending'})
    sent, status, failure = [], 'sent', None
    try:
        for index, payload in enumerate(pages):
            nonce = hashlib.blake2s(f'lazy-infractions:{sid}:{request_id}:{index}'.encode(), digest_size=12).hexdigest()
            attached = [(render.FOOTER_FILE, footer)] if render.FOOTER_FILE in announcement.attachments(payload) else []
            sent.append(await transport.send_components(channel_id, payload, nonce, files=attached))
    except asyncio.CancelledError:
        # Restart or cancel leaves the reservation unresolved; it is never replayed.
        raise
    except Exception as exc:
        status = 'failed' if isinstance(exc, AnnouncementRejected) and not sent else 'uncertain'
        failure = ('Discord rejected the message. Check bot permissions in the channel.' if status == 'failed'
                   else 'Delivery stopped. Check Discord before you send again; this will not resend automatically.')
    result = {**record, 'status': status, 'failure': failure,
              'message_ids': sent, 'urls': [_url(channel_id, m) for m in sent]}
    with _store(request).tx() as db:
        _audit(db, sid, actor, result)
    return web.json_response(result)


def routes():
    path = API + '/seasons/{season_id}/bonus-raffle/lazy-infractions'
    return [web.get(path, preview), web.post(path, send)]
