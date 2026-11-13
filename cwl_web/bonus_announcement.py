"""Staff send of the combined Lazy CWL bonus announcement (all Lazy clans or one clan).

Reads approved draws and stored winners only. Sends Components V2 messages through the
shared announcement transport. Uncertain sends are never retried automatically.
"""
import asyncio
import hashlib
import json
import re
from pathlib import Path

from aiohttp import web

from extensions.cwl_discord_transport import AnnouncementRejected, AnnouncementUnavailable, DiscordTransport
from utils import cwl_bonus_announcement as render
from utils.cwl_bonus_raffle_store import RaffleStore, now
from .bonus_raffle import _bonus_status
from .bonuses import _require_draft
from .roster_owner_names import cached_owner_nicknames

API = '/api/cwl'
GUILD_ID = '644963518025826315'
FOOTER_PATH = Path(__file__).resolve().parents[1] / 'assets' / render.FOOTER_FILE
ACTION = 'lazy_bonus_announcement'


def _scope(scope, clan_tag):
    from .app import _fail
    if scope not in ('all', 'one'):
        _fail(400, 'Select All Lazy clans or One clan')
    if scope == 'one' and (not isinstance(clan_tag, str) or not re.fullmatch(r'#[0-9A-Z]{3,12}', clan_tag)):
        _fail(400, 'Select a Lazy clan')
    return scope, clan_tag if scope == 'one' else None


def collect(db, sid, scope, clan_tag):
    """Return (clan options, blockers, announcement data). Stored data only; no Discord call."""
    status = _bonus_status(db, sid)
    store = RaffleStore(db, sid)
    cycle = status['cycle']
    lazy = status['pools']['lazy']
    options = [{'tag': c['tag'], 'name': c['name'], 'draw_state': c['draw_state'],
                'ready': c['draw_state'] in ('approved', 'sent')} for c in lazy]
    blockers = []
    if not cycle:
        blockers.append('Select the CWL month in Results first.')
    if scope == 'one':
        chosen = [c for c in options if c['tag'] == clan_tag]
        if not chosen:
            blockers.append('This clan is not a Lazy clan with results this season.')
    else:
        chosen = options
        if not chosen:
            blockers.append('No Lazy clans have results this season.')
    for clan in chosen:
        if not clan['ready']:
            blockers.append(f"{clan['name']}: approve the winners first.")
    lengths = {row['tag']: row['months'] for row in store.sit_out_settings()}
    draws = [d for d in store.draws() if d['cycle'] == cycle and d['pool'] == 'lazy' and not d['cancelled_at']]
    current = {row['tag']: row for row in store.lazy_winners(cycle)} if cycle else {}
    clans = []
    for clan in chosen:
        if not clan['ready']:
            continue
        draw = next(d for d in draws if d['clan_tag'] == clan['tag'] and d['approved_at'])
        snapshot = draw['snapshot']
        winners = []
        for account in snapshot['winners']:
            if account['tag'] not in current:
                blockers.append(f"{clan['name']}: a winner was voided. Review the clan first.")
                continue
            winners.append({'tag': account['tag'], 'player_name': account.get('player_name') or '',
                            'user_id': account.get('user_id')})
        clans.append({'tag': clan['tag'], 'name': clan['name'], 'bonus_count': snapshot['slots'],
                      'sit_out_months': lengths.get(clan['tag'], 3), 'winners': winners})
    previous = RaffleStore.shift_cycle(cycle, -1) if cycle else None
    last = sorted(store.lazy_winners(previous), key=lambda r: r['tag']) if previous else []
    users = store.discord_users([row['tag'] for row in last] + [w['tag'] for c in clans for w in c['winners'] if not w['user_id']])
    for clan in clans:
        for winner in clan['winners']:
            winner['user_id'] = winner['user_id'] or users.get(winner['tag'])
    data = {'cycle': cycle, 'last_month_label': RaffleStore.month_label(previous) if previous else None,
            'last_month': [{'tag': r['tag'], 'player_name': r['player_name'], 'user_id': users.get(r['tag'])} for r in last],
            'clans': clans}
    return options, blockers, data


def _ping(value):
    return value in ('1', 'true', True)


async def preview(request):
    from .app import _require, _sid, _store, _fail
    _require(request, 'editor')
    sid = _sid(request)
    scope, clan_tag = _scope(request.query.get('scope'), request.query.get('clan_tag'))
    ping = _ping(request.query.get('ping'))
    with _store(request).tx() as db:
        options, blockers, data = collect(db, sid, scope, clan_tag)
    users = {w['user_id'] for c in data['clans'] for w in c['winners'] if w['user_id']}
    users |= {r['user_id'] for r in data['last_month'] if r['user_id']}
    names = cached_owner_nicknames(request, users)
    pages = []
    if data['clans']:
        try:
            pages = [render.preview_parts(p) for p in render.messages(data, names, preview=True, ping=ping)]
        except ValueError as exc:
            blockers.append(str(exc))
    return web.json_response({
        'cycle': data['cycle'], 'scope': scope, 'clan_tag': clan_tag, 'ping': ping,
        'clans': options, 'blockers': blockers, 'pages': pages,
        'last_month_label': data['last_month_label'], 'last_month_count': len(data['last_month']),
        'clan_count': len(data['clans']),
        'ping_count': len(render.ping_users(data)) if ping else 0,
        'winner_count': sum(len(c['winners']) for c in data['clans']),
        'unlinked_count': sum(1 for c in data['clans'] for w in c['winners'] if not w['user_id'])
                          + sum(1 for r in data['last_month'] if not r['user_id']),
        'fingerprint': render.fingerprint(data, ping)})


def _prior(db, sid, request_id):
    rows = db.execute(f"SELECT after_json FROM bonus_audit WHERE season_id=? AND action=? "
                      f"AND json_extract(after_json,'$.request_id')=? ORDER BY id", (sid, ACTION, request_id)).fetchall()
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
    if set(body) != {'scope', 'clan_tag', 'ping', 'channel_id', 'request_id', 'fingerprint'}:
        _fail(400, 'Review the announcement and select a channel')
    scope, clan_tag = _scope(body['scope'], body['clan_tag'])
    channel_id, request_id, ping = body['channel_id'], body['request_id'], body['ping']
    if not isinstance(channel_id, str) or not re.fullmatch(r'[0-9]{15,22}', channel_id):
        _fail(400, 'Select an announcement channel')
    if (not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{24}', request_id)
            or type(ping) is not bool or not isinstance(body['fingerprint'], str) or len(body['fingerprint']) != 64):
        _fail(400, 'Review the announcement again')
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
        _, blockers, data = collect(db, sid, scope, clan_tag)
        if blockers:
            _fail(409, blockers[0])
        if render.fingerprint(data, ping) != body['fingerprint']:
            _fail(409, 'The announcement changed. Review the preview again.')
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
        pages = render.messages(data, ping=ping)
    except ValueError as exc:
        _fail(409, str(exc))
    footer = FOOTER_PATH.read_bytes()
    record = {'request_id': request_id, 'scope': scope, 'clan_tag': clan_tag, 'ping': ping,
              'channel_id': channel_id, 'cycle': data['cycle'], 'clans': [c['tag'] for c in data['clans']],
              'pages': len(pages)}
    with _store(request).tx() as db:
        data_again, done = checked(db)
        if done:
            return web.json_response(done)
        # The reservation is durable before Discord sees anything.
        _audit(db, sid, actor, {**record, 'status': 'sending'})
    sent, status, failure = [], 'sent', None
    try:
        for index, payload in enumerate(pages):
            nonce = hashlib.blake2s(f'lazy-bonus:{sid}:{request_id}:{index}'.encode(), digest_size=12).hexdigest()
            last = index == len(pages) - 1
            sent.append(await transport.send_components(
                channel_id, payload, nonce, files=[(render.FOOTER_FILE, footer)] if last else ()))
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
    base = API + '/seasons/{season_id}/bonus-raffle/lazy-announcement'
    return [web.get(base, preview), web.post(base, send)]
