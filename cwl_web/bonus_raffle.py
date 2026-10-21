"""Authorized HTTP adapters for staff-reviewed bonus raffles."""
import asyncio
import hashlib
import json
import sqlite3
from aiohttp import web
from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUnavailable, DiscordTransport
from utils.cwl_bonus_raffle_store import RaffleConflict, RaffleStore
from .bonuses import _view, _require_draft, _bump, _validate_revision, _cas


def _state(db, sid):
    from .app import _fail
    result = _view(db, sid, current_roster=True)
    if result is None:
        _fail(404, 'Season not found')
    rounds = {r['clan_tag']: len(json.loads(r['war_tags_json'])) for r in db.execute('SELECT clan_tag,war_tags_json FROM participation_group_observations WHERE season_id=? AND cycle=?', (sid, result['cycle']))}
    for account in result['accounts']:
        account['season_rounds'] = rounds.get(account['assigned_clan_tag'])
    store = RaffleStore(db, sid)
    return {**result, 'policies': store.policies(), 'draws': store.draws()}


def _selection(body):
    from .app import _fail
    if body.get('pool') not in ('main', 'lazy'):
        _fail(400, 'Choose Main or Lazy CWL')
    if not isinstance(body.get('clan_tag'), str) or len(body['clan_tag']) > 20:
        _fail(400, 'Choose a hosting clan')
    if type(body.get('slots')) is not int or not 1 <= body['slots'] <= 50:
        _fail(400, 'Enter 1–50 available bonuses, as shown in-game')
    return body['pool'], body['clan_tag'], body['slots']


async def state(request):
    from .app import _require, _sid, _store
    _require(request, 'editor')
    with _store(request).tx() as db:
        result = _state(db, _sid(request))
    return web.json_response(result)


async def refresh_results(request):
    from .app import _require, _sid, _store
    from .participation_sync import sync_season
    _require(request, 'editor')
    sid = _sid(request)
    await sync_season(request.app, sid, force=True)
    with _store(request).tx() as db:
        result = _state(db, sid)
    return web.json_response(result)


async def policy(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'pool', 'minimum', 'revision'} or body['pool'] not in ('main', 'lazy') or type(body['minimum']) is not int or not 0 <= body['minimum'] <= 7:
        _fail(400, 'Choose a CWL pool and a minimum of 0–7 attacks')
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        _cas(db, sid, _validate_revision(body, _fail), _fail)
        RaffleStore(db, sid).save_policy(body['pool'], body['minimum'])
        _bump(db, sid, actor)
        result = _state(db, sid)
    return web.json_response(result)


async def preview(request):
    from .app import _require, _sid, _store, _json, _fail
    _require(request, 'editor')
    body = await _json(request)
    if set(body) != {'pool', 'clan_tag', 'slots'}:
        _fail(400, 'Expected CWL pool, hosting clan and bonus count')
    selection = _selection(body)
    sid = _sid(request)
    with _store(request).tx() as db:
        _require_draft(db, sid, _fail)
        result = RaffleStore(db, sid).preview(_state(db, sid), *selection)
    return web.json_response(result)


async def draw(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'pool', 'clan_tag', 'slots', 'fingerprint'} or not isinstance(body.get('fingerprint'), str) or len(body['fingerprint']) != 64:
        _fail(400, 'Review qualifying accounts before drawing')
    selection = _selection(body)
    sid = _sid(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            RaffleStore(db, sid).draw(_state(db, sid), *selection, body['fingerprint'], actor)
            result = _state(db, sid)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return web.json_response(result)


def _draw_id(request):
    from .app import _fail
    try:
        return int(request.match_info['draw_id'])
    except ValueError:
        _fail(400, 'Invalid saved draw')


async def approve(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    if await _json(request) != {}:
        _fail(400, 'Unexpected approval fields')
    sid, draw_id = _sid(request), _draw_id(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            prior = RaffleStore(db, sid).get(draw_id)
            RaffleStore(db, sid).approve(draw_id, _state(db, sid), actor)
            if not prior['approved_at']:
                _bump(db, sid, actor)
            result = _state(db, sid)
    except (RaffleConflict, sqlite3.IntegrityError) as exc:
        _fail(409, str(exc) if isinstance(exc, RaffleConflict) else 'Bonus selections changed. Refresh and review')
    return web.json_response(result)


async def cancel(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) != {'reason'} or not isinstance(body['reason'], str) or not 1 <= len(body['reason'].strip()) <= 500:
        _fail(400, 'Explain why this draw needs to be cancelled (up to 500 characters)')
    sid = _sid(request)
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            RaffleStore(db, sid).cancel(_draw_id(request), actor, body['reason'].strip())
            result = _state(db, sid)
    except RaffleConflict as exc:
        _fail(409, str(exc))
    return web.json_response(result)


async def send(request):
    from .app import _require, _sid, _store, _json, _fail
    actor = _require(request, 'editor')['user_id']
    body = await _json(request)
    if set(body) not in ({'channel_id'}, {'channel_id', 'retry'}) or type(body.get('retry', False)) is not bool or not isinstance(body['channel_id'], str) or not body['channel_id'].isdigit() or not 15 <= len(body['channel_id']) <= 22:
        _fail(400, 'Choose an announcement channel')
    channel_id = body['channel_id']
    sid, draw_id = _sid(request), _draw_id(request)
    transport = request.app.get('announcement_transport') or DiscordTransport()
    try:
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            prior = RaffleStore(db, sid).get(draw_id)
            if prior['delivery'] and not (prior['delivery']['status'] == 'failed' and body.get('retry') is True):
                return web.json_response(_state(db, sid))
        channel = await transport.get_channel(channel_id)
        if channel['id'] != channel_id:
            _fail(503, 'Discord channel lookup did not match')
        with _store(request).tx() as db:
            _require_draft(db, sid, _fail)
            messages = RaffleStore(db, sid).reserve_delivery(draw_id, channel_id, actor, retry=body.get('retry', False))
    except RaffleConflict as exc:
        _fail(409, str(exc))
    except (AnnouncementRejected, AnnouncementUnavailable):
        _fail(503, 'Channel unavailable or outside this server. Choose a usable server channel')
    try:
        for index, message in messages:
            nonce = hashlib.blake2s(f'bonus:{sid}:{draw_id}:{index}'.encode(), digest_size=12).hexdigest()
            message_id = await transport.send(channel_id, message, nonce)
            with _store(request).tx() as db:
                RaffleStore(db, sid).page_sent(draw_id, index, message_id)
    except asyncio.CancelledError:
        # Restart/cancellation leaves the durable reservation unresolved, never replayed.
        raise
    except Exception as exc:
        rejected = isinstance(exc, AnnouncementRejected)
        with _store(request).tx() as db:
            RaffleStore(db, sid).finish_delivery(draw_id, 'failed' if rejected else 'uncertain',
                'Delivery stopped. Check Discord and the receipts below; this announcement will not resend automatically.')
    else:
        with _store(request).tx() as db:
            RaffleStore(db, sid).finish_delivery(draw_id, 'sent')
    with _store(request).tx() as db:
        result = _state(db, sid)
    return web.json_response(result)


def routes():
    from .app import API
    base = API + '/seasons/{season_id}/bonus-raffle'
    return [web.get(base, state), web.post(base + '/refresh-results', refresh_results), web.patch(base + '/policy', policy),
            web.post(base + '/preview', preview), web.post(base + '/draw', draw),
            web.post(base + '/{draw_id}/approve', approve), web.post(base + '/{draw_id}/cancel', cancel), web.post(base + '/{draw_id}/send', send)]
