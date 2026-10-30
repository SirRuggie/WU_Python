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
from .manage_clans import tag, public as public_clan
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
        try:
            await store.save_settings(row['tag'], before, config, actor['user_id'], history_context=(row, actor))
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


BASE = API+'/clans/{tag}/war-reminders'
routes = [
    web.get(API+'/war-reminders/overview', overview),
    web.get(BASE, read), web.put(BASE, save),
    web.post(BASE+'/preview', preview), web.post(BASE+'/test', test_send),
]
