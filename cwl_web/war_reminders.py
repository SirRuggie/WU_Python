"""HTTP adapters for per-clan reminder settings, previews, and test delivery."""
from datetime import datetime, timezone
from functools import partial
import json
import re
from uuid import UUID

from aiohttp import web

from utils import war_reminders as reminders
from utils.war_reminder_store import SettingsConflict, WarReminderStore
from .server_management import API, GUILD_ID, require_manage, mongo, discord
from .manage_clans import tag, public as public_clan, change_names
from utils.war_reminder_health import health
from .manage_operations import revision
from .war_reminder_samples import test_messages


def json_value(value):
    if isinstance(value, datetime):
        return reminders.utc(value).isoformat()
    return str(value)


async def clan(request, store):
    row = await store.clan(tag(request))
    if not row:
        raise web.HTTPNotFound(text='Clan removed. Refresh the directory.')
    return row


async def channel(request, value):
    if not value:
        raise web.HTTPBadRequest(text='Choose a channel first.')
    found = await discord(request, 'GET', f'/channels/{value}')
    if str(found.get('guild_id')) != str(GUILD_ID) or found.get('type') not in (0, 5):
        raise web.HTTPBadRequest(text='Choose a text or announcement channel in this server.')


def candidate(body):
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='Check the reminder settings.')
    try:
        return reminders.validate(body.get('settings'))
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None


def event_key(body):
    value = str(body.get('event', '60'))
    if value != 'start' and (not re.fullmatch(r'[0-9]{1,4}', value) or not 1 <= int(value) <= 1440):
        raise web.HTTPBadRequest(text='Choose a reminder time to preview.')
    return value


async def read(request):
    await require_manage(request, 'clans')
    async with mongo(request) as db:
        store = WarReminderStore(db)
        row = await clan(request, store)
        config = await store.get_settings(row['tag'])
        history = await store.recent_deliveries(row['tag'])
        state = await store.get_status(row['tag'])
    return web.json_response(
        dict(settings=reminders.settings(config), revision=revision(config), history=history, status=state),
        dumps=partial(json.dumps, default=json_value),
    )


async def overview(request):
    await require_manage(request, 'clans')
    async with mongo(request) as db:
        rows = await WarReminderStore(db).family_overview()
    now = datetime.now(timezone.utc)
    entries = []
    for row, config, state, delivery in rows:
        category, label, detail = health(config, state, delivery, now)
        entries.append(dict(
            clan=public_clan(row), settings=reminders.settings(config),
            health=dict(category=category, label=label, detail=detail),
            checked_at=(state or {}).get('checked_at'), last_delivery=delivery,
        ))
    return web.json_response(dict(clans=entries, generated_at=now),
                             dumps=partial(json.dumps, default=json_value))


async def save(request):
    actor = await require_manage(request, 'clans', write=True)
    body = await request.json()
    config = candidate(body)
    if config['channel_id']:
        await channel(request, config['channel_id'])
    async with mongo(request) as db:
        store = WarReminderStore(db)
        row = await clan(request, store)
        before = await store.get_settings(row['tag'])
        if body.get('revision') != revision(before):
            raise web.HTTPConflict(text='Reminders changed. Reload before saving.')
        names = await change_names(request, actor, reminders.settings(before), config)
        try:
            await store.save_settings(row['tag'], before, config, actor['user_id'], history_context=(row, actor), history_names=names)
        except SettingsConflict:
            raise web.HTTPConflict(text='Reminders changed. Reload before saving.') from None
    return await read(request)


async def preview(request):
    actor = await require_manage(request, 'clans')
    body = await request.json()
    config = candidate(body)
    event = event_key(body)
    async with mongo(request) as db:
        row = await clan(request, WarReminderStore(db))
    messages = await test_messages(request, row, config, event, body, actor)
    return web.json_response({'messages': messages})


async def test_send(request):
    actor = await require_manage(request, 'clans', write=True)
    body = await request.json()
    config = candidate(body)
    event = event_key(body)
    try:
        request_id = str(UUID(body.get('request_id', '')))
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text='Reload the test form and try again.') from None
    await channel(request, config['channel_id'])
    async with mongo(request) as db:
        store = WarReminderStore(db)
        row = await clan(request, store)
        payloads = await test_messages(request, row, config, event, body, actor)
        key = 'test:'+request_id
        if not await store.claim_delivery(
            key, clan_tag=row['tag'], at=datetime.now(timezone.utc), event=event,
            channel_id=config['channel_id'], status='sending', test=True, actor=actor['user_id'],
        ):
            raise web.HTTPConflict(text='This test was already submitted. Check delivery history before sending another.')
        urls = []
        try:
            for payload in payloads:
                sent = await discord(request, 'POST', f"/channels/{config['channel_id']}/messages", json=payload)
                urls.append(f"https://discord.com/channels/{GUILD_ID}/{config['channel_id']}/{sent['id']}")
                await store.finish_delivery(key, urls=urls)
            await store.finish_delivery(key, status='sent', url=urls[0], urls=urls)
        except Exception:
            await store.finish_delivery(
                key, status='uncertain', urls=urls,
                detail='Discord did not confirm the full delivery. Check the channel before sending another test.',
            )
            raise
    return web.json_response({'url': urls[0], 'urls': urls})


async def copy_targets(request):
    await require_manage(request, 'clans')
    async with mongo(request) as db:
        store = WarReminderStore(db)
        source = await clan(request, store)
        rows = await store.copy_targets()
    return web.json_response({'clans': [
        {'tag': row['tag'], 'name': row['name'], 'type': row.get('type') or '',
         'revision': revision(config), 'settings': reminders.settings(config)}
        for row, config in rows if row['tag'] != source['tag']
    ]})


async def copy_settings(request):
    actor = await require_manage(request, 'clans', write=True)
    body = await request.json()
    if not isinstance(body, dict) or set(body) != {'revision', 'fields', 'targets'}:
        raise web.HTTPBadRequest(text='Review the reminder copy first.')
    try:
        reminders.copied_settings(None, None, body['fields'])
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    targets = body['targets']
    if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
        raise web.HTTPBadRequest(text='Choose between 1 and 100 clans.')
    from .providers import tag as normalize_tag
    seen = set()
    for target in targets:
        if not isinstance(target, dict) or set(target) != {'tag', 'revision'} or not isinstance(target['revision'], str):
            raise web.HTTPBadRequest(text='Refresh the target clans before copying.')
        try:
            valid_tag = normalize_tag(target['tag'])
        except (ValueError, TypeError, AttributeError):
            raise web.HTTPBadRequest(text='Choose a valid target clan.') from None
        if valid_tag != target['tag'] or valid_tag in seen or valid_tag == tag(request):
            raise web.HTTPBadRequest(text='Choose each other clan once.')
        seen.add(valid_tag)
    results = []
    async with mongo(request) as db:
        store = WarReminderStore(db)
        source = await clan(request, store)
        config = await store.get_settings(source['tag'])
        if body['revision'] != revision(config):
            raise web.HTTPConflict(text='Source reminders changed. Review the copy again.')
        for target in targets:
            target_tag = target['tag']
            try:
                row = await store.clan(target_tag)
                if not row:
                    raise ValueError('Clan removed. Refresh the list.')
                before = await store.get_settings(target_tag)
                if target['revision'] != revision(before):
                    raise SettingsConflict
                values = reminders.copied_settings(config, before, body['fields'])
                if values['channel_id']:
                    await channel(request, values['channel_id'])
                await store.save_settings(target_tag, before, values, actor['user_id'],
                                          history_context=(row, actor))
                results.append({'tag': target_tag, 'ok': True,
                                'message': 'Copied' if values['channel_id'] else 'Copied · Needs a channel · Off'})
            except SettingsConflict:
                results.append({'tag': target_tag, 'ok': False, 'message': 'Settings changed. Review this clan again.'})
            except (ValueError, web.HTTPBadRequest) as exc:
                results.append({'tag': target_tag, 'ok': False, 'message': exc.text if isinstance(exc, web.HTTPException) else str(exc)})
            except Exception:
                # A transport/storage failure may follow a successful write. Do
                # not repeat it automatically or expose upstream exception text.
                import logging
                logging.getLogger(__name__).exception('Reminder copy needs verification for %s', target_tag)
                results.append({'tag': target_tag, 'ok': False, 'message': 'Could not confirm the save. Check this clan before retrying.'})
    return web.json_response({'results': results})


BASE = API+'/clans/{tag}/war-reminders'
routes = [
    web.get(API+'/war-reminders/overview', overview),
    web.get(BASE, read), web.put(BASE, save),
    web.get(BASE+'/copy', copy_targets), web.post(BASE+'/copy', copy_settings),
    web.post(BASE+'/preview', preview), web.post(BASE+'/test', test_send),
]
