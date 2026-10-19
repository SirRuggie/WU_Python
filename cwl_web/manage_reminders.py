"""Web editor for the existing Manage campaign; the bot remains the scheduler."""
import copy
import re
from datetime import datetime, timezone

from aiohttp import web
from utils import cwl_campaign, cwl_sequence
from utils.cwl_web_bridge import campaign_generation
from .manage_bridge import API, GUILD_ID, _mongo, _worker_ready


def _object(value, allowed, label):
    if not isinstance(value, dict) or set(value) - set(allowed):
        raise ValueError(f'Invalid {label} fields')
    return value


def _bool(value):
    if type(value) is not bool:
        raise ValueError('Enabled and paused settings must be true or false')
    return value


def _snowflake(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{15,22}', value):
        raise ValueError('Choose a valid Discord channel or role ID')
    return int(value)


def _candidate(loaded, patch):
    _object(patch, ('timezone', 'signup_deadline', 'reminder_sequence', 'messages'), 'campaign')
    candidate = copy.deepcopy(loaded['campaign'])
    if 'timezone' in patch:
        if not isinstance(patch['timezone'], str):
            raise ValueError('Choose a timezone')
        candidate['timezone'] = patch['timezone']
    if 'signup_deadline' in patch:
        candidate['signup_deadline'] = copy.deepcopy(patch['signup_deadline'])
    if 'reminder_sequence' in patch:
        seq = _object(patch['reminder_sequence'], ('enabled', 'mode', 'count', 'interval_hours', 'final_hours', 'min_gap_hours'), 'sequence')
        if _bool(seq.get('enabled')):
            candidate = cwl_sequence.configure(candidate, **{k: v for k, v in seq.items() if k != 'enabled'})
        else:
            candidate['reminder_sequence'] = {'enabled': False}
    messages = _object(patch.get('messages', {}), candidate['messages'], 'messages')
    for mid, changes in messages.items():
        if mid == 'roster':
            raise ValueError('Edit roster announcements in Publish roster')
        _object(changes, ('enabled', 'schedule', 'variants'), 'message')
        message = candidate['messages'][mid]
        if 'enabled' in changes:
            message['enabled'] = _bool(changes['enabled'])
        if 'schedule' in changes:
            message['schedule'] = copy.deepcopy(changes['schedule'])
            # Native transitional schedules otherwise override this field.
            candidate.get('schedules', {}).pop(mid, None)
        for pool, fields in _object(changes.get('variants', {}), cwl_campaign.AUDIENCES, 'audiences').items():
            _object(fields, ('title', 'body', 'media_url', 'destination_channel_id', 'role_ids', 'enabled'), 'variant (signup links are locked)')
            item = message['variants'][pool]
            for key, value in fields.items():
                if key == 'destination_channel_id':
                    item[key] = _snowflake(value)
                elif key == 'role_ids':
                    if not isinstance(value, list) or len(value) > 10:
                        raise ValueError('Choose up to 10 roles')
                    item[key] = list(dict.fromkeys(_snowflake(role) for role in value))
                elif key == 'enabled':
                    item[key] = _bool(value)
                else:
                    if not isinstance(value, str) or len(value) > 4000:
                        raise ValueError('Message text must be at most 4000 characters')
                    item[key] = value
    cwl_campaign.validate_campaign(candidate)
    cwl_campaign.resolve_schedule(candidate, loaded['cycle'])
    # Never allow any existing button to be changed by this editor. Newly
    # provisioned reminder slots copy the native template including its links.
    for mid, message in loaded['campaign']['messages'].items():
        for pool, item in message['variants'].items():
            if candidate['messages'][mid]['variants'][pool].get('buttons') != item.get('buttons'):
                raise ValueError('Signup links must remain unchanged until launch approval')
    return candidate


def _public_campaign(campaign):
    result = copy.deepcopy(campaign)
    for mid, message in result['messages'].items():
        message['schedule'] = copy.deepcopy(cwl_campaign._schedule_for(campaign, mid, message))
        for item in message['variants'].values():
            item['destination_channel_id'] = str(item['destination_channel_id'])
            item['role_ids'] = [str(role) for role in item.get('role_ids', [])]
    return result


async def _response(request, mongo, loaded, *, preview=False, protected=()):
    from .app import _store, _sid
    history = await cwl_campaign.history(mongo, GUILD_ID, loaded['cycle'])
    # History snapshots are large; expose receipts/actions, not stored campaigns.
    history = [{key: value for key, value in event.items() if key not in ('campaign', 'draft_id', '_id')} for event in history]
    for event in history:
        parts = str(event.get('occurrence_id', '')).split('|')
        if len(parts) == 3:
            event['message_id'], event['variant'] = parts[1], parts[2]
        if 'by' in event and event['by'] is not None:
            event['by'] = str(event['by'])
    sent = set(loaded.get('sent_occurrences', [])) | {x.get('occurrence_id') for x in loaded.get('deliveries', []) if x.get('status') == 'sent'}
    receipts = {x.get('occurrence_id'): x for x in loaded.get('deliveries', [])}
    schedule = []
    for item in loaded['schedule']:
        receipt = receipts.get(item['id'], {})
        if item['id'] in sent:
            status = 'sent'
        elif item['id'] in loaded.get('uncertain_occurrences', []):
            status = 'uncertain'
        elif item['id'] in loaded.get('skipped', []):
            status = 'skipped'
        elif receipt.get('status'):
            status = receipt['status']
        elif loaded['campaign'].get('paused'):
            status = 'paused'
        elif not loaded.get('activated'):
            status = 'inactive'
        elif not item['run_at']:
            status = 'manual'
        elif datetime.fromisoformat(item['run_at_utc']) < datetime.now(timezone.utc):
            status = 'elapsed'
        else:
            status = 'scheduled'
        schedule.append({**item, 'status': status})
    worker = await mongo.bot_config.find_one({'_id': f'cwl:web-worker:{GUILD_ID}'}) or {}
    season = _store(request).one('SELECT signup_open FROM seasons WHERE id=?', (_sid(request),))
    return {'cycle': loaded['cycle'], 'generation': campaign_generation(loaded),
            'worker_ready': await _worker_ready(mongo), 'activated': loaded['activated'],
            'campaign': _public_campaign(loaded['campaign']), 'deadline': loaded['deadline'],
            'schedule': schedule, 'history': history, 'signup_open': bool(season['signup_open']),
            'schedule_synced': (worker.get('schedule_generations') or {}).get(loaded['cycle']) == campaign_generation(loaded),
            'schedule_sync_at': worker.get('schedule_sync_at'),
            'links_locked': True, 'preview': preview, 'protected_sent': list(protected),
            'sync_note': 'The existing Manage bot reconciles saved schedules automatically.'}


async def status(request):
    from .app import _require, _sid
    _require(request, 'editor')
    cycle = None  # Use the same automatic month selection as Discord /manage.
    async with _mongo(request) as mongo:
        loaded = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
        return web.json_response(await _response(request, mongo, loaded))


async def _edit(request, preview=False):
    from .app import _require, _sid, _json, _store, _season, _audit
    from .announcements import _transport, AnnouncementRejected, AnnouncementUnavailable
    session = _require(request, 'editor')
    sid = _sid(request)
    cycle = None  # Reminder editing is independent of roster month bindings.
    body = await _json(request)
    with _store(request).tx() as db:
        if _season(db, sid)['status'] != 'draft':
            raise web.HTTPConflict(text='Season is archived')
    try:
        _object(body, ('generation', 'patch', 'repeat_monthly'), 'request')
        if not isinstance(body.get('generation'), str) or not isinstance(body.get('patch'), dict):
            raise ValueError('Review reminder settings before saving')
        repeat = _bool(body.get('repeat_monthly', True))
        async with _mongo(request) as mongo:
            loaded = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
            cycle = loaded['cycle']
            if body['generation'] != campaign_generation(loaded):
                raise web.HTTPConflict(text='Manage settings changed; refresh and review')
            candidate = _candidate(loaded, body['patch'])
            cwl_campaign._validate_future_signup(candidate, loaded, cycle)
            channels = {item['destination_channel_id'] for mid, message in candidate['messages'].items() if mid != 'roster' for item in message['variants'].values()}
            for channel in channels:
                await _transport(request).get_channel(str(channel))
            edited_roles = {role for changes in body['patch'].get('messages', {}).values()
                            for fields in changes.get('variants', {}).values()
                            for role in fields.get('role_ids', [])}
            if edited_roles:
                allowed_roles = {str(role['id']) for role in await _transport(request).list_roles()}
                if not edited_roles <= allowed_roles:
                    raise ValueError('Choose roles that exist in Warriors United')
            if repeat:
                recurring = cwl_campaign.monthly_campaign(candidate, cycle)
                for offset in range(1, 13):
                    cwl_campaign.resolve_schedule(recurring, cwl_campaign._month(cycle, candidate['timezone']).add(months=offset).format('YYYY-MM'))
            if preview:
                protected = cwl_campaign._protect_sent(candidate, loaded['campaign'], cycle, loaded['deliveries'], loaded.get('sent_occurrences', ()))
                planned = {**loaded, 'activated': True, 'campaign': candidate, 'schedule': cwl_campaign.resolve_schedule(candidate, cycle), 'deadline': cwl_campaign.signup_deadline(candidate, cycle).isoformat()}
                return web.json_response(await _response(request, mongo, planned, preview=True, protected=protected))
            draft = await cwl_campaign.new_draft(mongo, GUILD_ID, int(session['user_id']), cycle)
            try:
                if (draft['base_revision'] != loaded['revision'] or draft['defaults_base_revision'] != loaded['defaults_revision'] or draft.get('recurring_base_version') != loaded.get('recurring_version')):
                    raise web.HTTPConflict(text='Manage settings changed; refresh and review')
                saved = await cwl_campaign.apply_draft(mongo, draft['_id'], int(session['user_id']), expected_revision=loaded['revision'], candidate_campaign=candidate, require_future_signup=True, repeat_monthly=repeat, expected_generation=body['generation'])
            finally:
                await mongo.bot_config.delete_one({'_id': draft['_id'], 'user_id': int(session['user_id'])})
            with _store(request).tx() as db:
                _audit(db, sid, None, session['user_id'], 'manage_reminders_save', {'generation': body['generation']}, {'generation': campaign_generation(saved), 'repeat_monthly': repeat})
            return web.json_response(await _response(request, mongo, saved, protected=saved.get('protected_sent', [])))
    except AnnouncementRejected as exc:
        raise web.HTTPBadRequest(text='Choose Warriors United text channels') from exc
    except AnnouncementUnavailable as exc:
        raise web.HTTPServiceUnavailable(text='Discord channel validation unavailable') from exc
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    except RuntimeError as exc:
        raise web.HTTPConflict(text=str(exc)) from exc


async def preview(request):
    return await _edit(request, preview=True)


async def save(request):
    return await _edit(request)


async def pause(request):
    from .app import _require, _sid, _json, _store, _season, _audit
    session = _require(request, 'editor')
    sid = _sid(request)
    cycle = None  # Reminder editing is independent of roster month bindings.
    body = await _json(request)
    if set(body) != {'generation', 'paused'} or not isinstance(body['generation'], str) or type(body['paused']) is not bool:
        raise web.HTTPBadRequest(text='Review reminder settings and pause state first')
    with _store(request).tx() as db:
        if _season(db, sid)['status'] != 'draft':
            raise web.HTTPConflict(text='Season is archived')
    async with _mongo(request) as mongo:
        try:
            saved = await cwl_campaign.set_paused(mongo, GUILD_ID, body['paused'], cycle, int(session['user_id']), expected_generation=body['generation'])
        except RuntimeError as exc:
            raise web.HTTPConflict(text=str(exc)) from exc
        with _store(request).tx() as db:
            _audit(db, sid, None, session['user_id'], 'manage_reminders_pause', None, {'paused': body['paused']})
        return web.json_response(await _response(request, mongo, saved))


def routes():
    base = API + '/seasons/{season_id}/manage-reminders'
    return [web.get(base, status), web.patch(base, save), web.post(base + '/preview', preview), web.post(base + '/pause', pause)]
