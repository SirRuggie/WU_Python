"""Staff web facade over the native Manage CWL campaign and bot-owned queue."""
from utils.cwl_roster_messages import roster_button
import copy
import re
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import urlsplit

from aiohttp import web
from .mongo_operations import BudgetedCollection
from .mongo_client import get_client
from pymongo.errors import PyMongoError
from utils import cwl_campaign
from utils.mongo_routes import collection_for, load_routes

GUILD_ID = 644963518025826315
API = '/api/cwl'


@asynccontextmanager
async def _mongo(request):
    injected = request.app.get('manage_bridge_mongo')
    if injected is not None:
        yield injected
        return
    client = get_client(request.app)
    if client is None:
        raise web.HTTPServiceUnavailable(text="Automatic messages are not set up.")
    routes = load_routes()
    facade = SimpleNamespace(**{name: BudgetedCollection(collection_for(client, name, routes=routes), 10)
                               for name in ('bot_config', 'cwl_reminder', 'cwl_pending_reminders')})
    try:
        yield facade
    except PyMongoError as exc:
        raise web.HTTPServiceUnavailable(text="Automatic messages are not available. Refresh before you try again.") from exc


def _binding(request, sid):
    from .app import _store, _season
    with _store(request).tx() as db:
        _season(db, sid)
        row = db.execute('SELECT cycle FROM manage_campaign_bindings WHERE season_id=?', (sid,)).fetchone()
    return row['cycle'] if row else None


def _required_binding(request, sid):
    cycle = _binding(request, sid)
    if cycle is None:
        raise web.HTTPConflict(text="Select the matching Manage CWL month first")
    return cycle


def _pool(request):
    pool = request.match_info['pool']
    if pool not in cwl_campaign.AUDIENCES:
        raise web.HTTPNotFound(text='Unknown CWL pool')
    return pool


def _delivery(value):
    if not value:
        return None
    receipt = value.get('receipt') or {}
    return {
        'status': value.get('status', 'pending'),
        'publication_version': value.get('publication_version') if type(value.get('publication_version')) is int else None,
        'message_url': value.get('message_url') or receipt.get('message_url'),
        'error': value.get('error') or value.get('failure'),
        'requested_at': value.get('created_at'),
        'started_at': value.get('started_at'),
        'updated_at': value.get('updated_at'),
        'sent_at': receipt.get('at') or receipt.get('updated_at'),
    }


async def _worker_ready(mongo):
    row = await mongo.bot_config.find_one({'_id': f'cwl:web-worker:{GUILD_ID}'})
    try:
        at = datetime.fromisoformat(row['updated_at'].replace('Z', '+00:00'))
        return 0 <= (datetime.now(timezone.utc) - at).total_seconds() < 60
    except (TypeError, KeyError, ValueError):
        return False


async def status(request):
    from .app import _require, _sid, _store
    from utils.cwl_web_bridge import campaign_generation, get_roster_send_status
    _require(request, 'editor')
    sid = _sid(request)
    cycle = _binding(request, sid)
    published = _store(request).one('SELECT version FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,))
    from .roster_sequence_review import describe
    from utils.cwl_roster_image_store import RosterImageStore
    image_store = RosterImageStore(_store(request))
    def sequence_status(sid, pool):
        return describe(image_store, sid, pool)
    result = {'cycle': cycle, 'generation': None, 'worker_ready': False, 'pools': {},
              'published_version': published['version'] if published else None}
    if not cycle:
        return web.json_response(result)
    async with _mongo(request) as mongo:
        loaded = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
        result['generation'] = campaign_generation(loaded)
        result['worker_ready'] = await _worker_ready(mongo)
        for pool in cwl_campaign.AUDIENCES:
            item = loaded['campaign']['messages']['roster']['variants'][pool]
            buttons = item.get('buttons', [])
            result['pools'][pool] = {
                'channel_id': str(item['destination_channel_id']) if item.get('destination_channel_id') else None,
                'title': item.get('title', ''), 'body': item.get('body', ''),
                'media_url': item.get('media_url', ''), 'buttons': buttons,
                'roster_url': buttons[0]['url'] if buttons else '',
                'role_ids': [str(role) for role in item.get('role_ids', [])],
                'enabled': loaded['campaign']['messages']['roster'].get('enabled', True) and item.get('enabled', True),
                'delivery': _delivery(await get_roster_send_status(mongo, guild_id=GUILD_ID, cycle=cycle, pool=pool)),
                'sequence': sequence_status(sid, pool),
            }
    return web.json_response(result)


async def bind(request):
    from .app import _require, _sid, _json, _store, _season, _audit
    from utils.cwl_web_bridge import get_roster_send_status
    session = _require(request, 'editor')
    body = await _json(request)
    cycle = body.get('cycle')
    if set(body) != {'cycle'} or not isinstance(cycle, str) or not re.fullmatch(r'20\d{2}-(0[1-9]|1[0-2])', cycle):
        raise web.HTTPBadRequest(text="Select a CWL month in YYYY-MM format")
    sid = _sid(request)
    previous = _binding(request, sid)
    async with _mongo(request) as mongo:
        await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
        if previous and previous != cycle:
            for pool in cwl_campaign.AUDIENCES:
                if await get_roster_send_status(mongo, guild_id=GUILD_ID, cycle=previous, pool=pool):
                    raise web.HTTPConflict(text="This season already has delivery activity. Keep its CWL month.")
    try:
        with _store(request).tx() as db:
            if _season(db, sid)['status'] != 'draft':
                raise web.HTTPConflict(text='Season is archived')
            current = db.execute('SELECT cycle FROM manage_campaign_bindings WHERE season_id=?', (sid,)).fetchone()
            if (current['cycle'] if current else None) != previous:
                raise web.HTTPConflict(text="The CWL month link changed. Refresh first.")
            db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,?) ON CONFLICT(season_id) DO UPDATE SET cycle=excluded.cycle', (sid, cycle))
            _audit(db, sid, None, session['user_id'], 'manage_campaign_bind', {'cycle': previous}, {'cycle': cycle})
    except sqlite3.IntegrityError as exc:
        raise web.HTTPConflict(text="That CWL month is already linked to another dashboard season") from exc
    return web.json_response({'cycle': cycle})


async def save_variant(request):
    from .app import _require, _sid, _json, _store, _season
    from .announcements import _transport, AnnouncementRejected, AnnouncementUnavailable
    from utils.cwl_web_bridge import campaign_generation, get_roster_send_status
    session = _require(request, 'editor')
    sid = _sid(request)
    cycle = _required_binding(request, sid)
    pool = _pool(request)
    body = await _json(request)
    required = {'generation', 'channel_id', 'body', 'roster_url'}
    if not required <= set(body) or set(body) - required - {'roster_button_label'}:
        raise web.HTTPBadRequest(text="The request is not complete. Refresh the page and try again.")
    if 'roster_button_label' in body:
        label = body['roster_button_label']
        if pool != 'lazy' or label != 'Lazy CWL guide' or not isinstance(label, str):
            raise web.HTTPBadRequest(text='Only the Lazy CWL guide label can be updated')
    if not isinstance(body['body'], str) or len(body['body']) > 4000:
        raise web.HTTPBadRequest(text='Announcement text must be at most 4000 characters')
    channel_id = str(body['channel_id'])
    if not re.fullmatch(r'\d{15,22}', channel_id):
        raise web.HTTPBadRequest(text="Select a Discord channel")
    url = body['roster_url']
    if not isinstance(url, str) or len(url) > 2048:
        raise web.HTTPBadRequest(text='Invalid roster link')
    try:
        parts = urlsplit(url)
        valid = parts.scheme == 'https' and parts.hostname and not parts.username and not parts.password and not any(c.isspace() for c in url)
    except ValueError:
        valid = False
    if not valid:
        raise web.HTTPBadRequest(text='Roster link must use HTTPS')
    with _store(request).tx() as db:
        if _season(db, sid)['status'] != 'draft':
            raise web.HTTPConflict(text='Season is archived')
    try:
        await _transport(request).get_channel(channel_id)
    except AnnouncementRejected as exc:
        raise web.HTTPBadRequest(text="Select a Warriors United text channel") from exc
    except AnnouncementUnavailable as exc:
        raise web.HTTPServiceUnavailable(text='Discord channel validation unavailable') from exc
    async with _mongo(request) as mongo:
        loaded = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
        if body['generation'] != campaign_generation(loaded):
            raise web.HTTPConflict(text="Manage settings changed. Refresh and review.")
        if 'roster_button_label' in body:
            current = loaded['campaign']['messages']['roster']['variants'][pool]
            buttons = current.get('buttons') or []
            matches = [index for index, button in enumerate(buttons)
                       if button.get('label') == 'LazyCWL Guide']
            if len(matches) != 1:
                raise web.HTTPConflict(text='The Lazy CWL guide button is missing or ambiguous. Review Manage settings.')
            if (channel_id != str(current.get('destination_channel_id'))
                    or body['body'] != current.get('body')
                    or not buttons or url != buttons[0].get('url')):
                raise web.HTTPBadRequest(text='Only the Lazy CWL guide label can change in this request')
        delivery = await get_roster_send_status(mongo, guild_id=GUILD_ID, cycle=cycle, pool=pool)
        if delivery and delivery.get('status') in ('sent', 'pending', 'sending', 'uncertain'):
            raise web.HTTPConflict(text='This announcement is sent or in progress; edit it through Manage after delivery review')
        draft = await cwl_campaign.new_draft(mongo, GUILD_ID, int(session['user_id']), cycle)
        try:
            # A fresh draft may load a different revision if Manage edited during validation.
            if (draft['base_revision'] != loaded['revision'] or draft.get('defaults_base_revision') != loaded['defaults_revision'] or draft.get('recurring_base_version') != loaded.get('recurring_version')):
                raise web.HTTPConflict(text="Manage settings changed. Refresh and review.")
            candidate = copy.deepcopy(draft['campaign'])
            item = candidate['messages']['roster']['variants'][pool]
            if 'roster_button_label' in body:
                item['buttons'][matches[0]]['label'] = body['roster_button_label']
            else:
                item['destination_channel_id'] = int(channel_id)
                item['body'] = body['body']
                if item.get('buttons'):
                    item['buttons'][0]['url'] = url
                else:
                    item['buttons'] = [roster_button(url)]
            saved = await cwl_campaign.apply_draft(mongo, draft['_id'], int(session['user_id']), expected_revision=loaded['revision'], candidate_campaign=candidate, **({'expected_generation': body['generation']} if 'roster_button_label' in body else {}))
            if cwl_campaign.occurrence_id(cycle, 'roster', pool) in saved.get('protected_sent', []):
                raise web.HTTPConflict(text='Manage sent this announcement during your edit; its posted settings were preserved')
        except (ValueError, RuntimeError) as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        finally:
            await mongo.bot_config.delete_one({'_id': draft['_id'], 'user_id': int(session['user_id'])})
    return web.json_response({'saved': True})


async def send(request):
    from .app import _require, _sid, _json, _store, _season
    from utils.cwl_web_bridge import queue_roster_send, get_roster_send_status
    from .roster_image_posts import staff
    from .roster_sequence_review import prepare
    session = staff(request, send=True)
    sid = _sid(request)
    cycle = _required_binding(request, sid)
    pool = _pool(request)
    body = await _json(request)
    resend = 'deleted_message_id' in body or 'confirm_resend' in body
    expected_keys = {'generation', 'channel_id', 'version'} | ({'deleted_message_id', 'confirm_resend'} if resend else set())
    if set(body) != expected_keys or type(body.get('version')) is not int:
        raise web.HTTPBadRequest(text='Review the published version, channel and Manage settings before sending')
    with _store(request).tx() as db:
        if _season(db, sid)['status'] != 'draft':
            raise web.HTTPConflict(text='Season is archived')
        latest = db.execute('SELECT version FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1', (sid,)).fetchone()
        if latest is None or latest['version'] != body['version']:
            raise web.HTTPConflict(text="Published roster changed. Refresh and review.")
    if not isinstance(body['channel_id'], str) or not re.fullmatch(r'\d{15,22}', body['channel_id']) or not isinstance(body['generation'], str):
        raise web.HTTPBadRequest(text="The channel or saved automatic message settings are not valid.")
    async with _mongo(request) as mongo:
        if not await _worker_ready(mongo):
            raise web.HTTPServiceUnavailable(text='Manage delivery worker is unavailable; nothing queued')
        try:
            previous = await get_roster_send_status(mongo, guild_id=GUILD_ID, cycle=cycle, pool=pool)
            if resend:
                from .announcement_recovery import prepare_resend
                previous = await prepare_resend(request, mongo, sid=sid, cycle=cycle, pool=pool,
                                                body=body, actor=session, previous=previous)
            sequence = await prepare(request, sid, pool, cycle, body, session, previous)
            result = await queue_roster_send(mongo, guild_id=GUILD_ID, cycle=cycle, pool=pool,
                publication_version=body['version'], expected_generation=body['generation'],
                expected_channel_id=int(body['channel_id']), requested_by=int(session['user_id']),
                retry_failed=bool(previous and previous.get('status') in ('failed', 'stale')),
                sequence_id=sequence['sequence_id'])
        except (ValueError, RuntimeError) as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
    return web.json_response({'delivery': _delivery(result)}, status=202)


def routes():
    from . import manage_reminders, roster_sequence_tests, announcement_recovery, announcement_settings, announcement_post_updates
    from .roster_sequence_review import resume as resume_sequence, recover as recover_sequence, repair_closing, assume_announcement
    return [web.get(API + '/seasons/{season_id}/manage-bridge', status),
            web.post(API + '/seasons/{season_id}/manage-bridge/bind', bind),
            web.patch(API + '/seasons/{season_id}/manage-bridge/{pool}', save_variant),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/send', send),
            web.get(API + '/seasons/{season_id}/manage-bridge/{pool}/check-message', announcement_recovery.check),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/sequence/resume', resume_sequence),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/sequence/assume', assume_announcement),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/sequence/recover', recover_sequence),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/sequence/closing/update', repair_closing),
            web.get(API + '/manage/announcement-test-channel', announcement_settings.read),
            web.put(API + '/manage/announcement-test-channel', announcement_settings.save),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/test-full', roster_sequence_tests.prepare),
            web.get(API + '/seasons/{season_id}/manage-bridge/{pool}/test-full/{request_id}', roster_sequence_tests.status),
            web.post(API + '/seasons/{season_id}/manage-bridge/{pool}/test', test_announcement)] + manage_reminders.routes() + announcement_post_updates.routes()

async def test_announcement(request):
    """Preview only: no role pings, campaign edits, or production delivery claims."""
    from .app import _require, _sid, _json, _store
    from .server_management import discord
    from utils.cwl_web_bridge import campaign_generation
    from .roster_image_posts import staff
    actor = staff(request, send=True)
    sid = _sid(request)
    cycle = _required_binding(request, sid)
    pool = _pool(request)
    body = await _json(request)
    if set(body) != {'channel_id','request_id','generation','body','roster_url'}:
        raise web.HTTPBadRequest(text="Select a test channel and review the message.")
    channel, nonce = body['channel_id'], body['request_id']
    if not isinstance(channel,str) or not re.fullmatch(r'\d{15,22}',channel) or not isinstance(nonce,str) or not re.fullmatch(r'[a-f0-9]{24}',nonce):
        raise web.HTTPBadRequest(text="Select a test channel and try again.")
    if not isinstance(body['body'],str) or len(body['body'])>4000 or not isinstance(body['roster_url'],str):
        raise web.HTTPBadRequest(text='Check the message and roster link.')
    destination = await discord(request,'GET',f'/channels/{channel}')
    if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0,5):
        raise web.HTTPBadRequest(text="Select a text channel in this server.")
    async with _mongo(request) as mongo:
        loaded = await cwl_campaign.load_campaign(mongo,GUILD_ID,cycle)
        if body['generation'] != campaign_generation(loaded):
            raise web.HTTPConflict(text='Message settings changed. Refresh before testing.')
        item = loaded['campaign']['messages']['roster']['variants'][pool]
        item['body'] = body['body']
        if item.get('buttons'):
            item['buttons'][0]['url'] = body['roster_url']
        else:
            item['buttons'] = [roster_button(body['roster_url'])]
        try:
            components = await cwl_campaign.render_message(loaded,'roster',pool,preview=True)
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from None
    key = f'{actor["user_id"]}:{nonce}'
    with _store(request).tx() as db:
        previous = db.execute('SELECT url FROM roster_test_messages WHERE id=?',(key,)).fetchone()
        if previous:
            if previous['url']: return web.json_response({'url':previous['url']})
            raise web.HTTPConflict(text='Test delivery is unconfirmed. Check Discord before trying again.')
        db.execute('INSERT INTO roster_test_messages(id,season_id,pool,channel_id,actor_id) VALUES (?,?,?,?,?)',(key,sid,pool,channel,actor['user_id']))
    message = await discord(request,'POST',f'/channels/{channel}/messages',json={
        'components':[component.build()[0] for component in components], 'flags':32768,
        'allowed_mentions':{'parse':[], 'roles':[]}, 'nonce':nonce,'enforce_nonce':True})
    url = f'https://discord.com/channels/{GUILD_ID}/{channel}/{message["id"]}'
    with _store(request).tx() as db:
        db.execute('UPDATE roster_test_messages SET url=? WHERE id=?',(url,key))
    return web.json_response({'url':url})
