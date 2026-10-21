"""Per-clan settings and immediate sample sends, protected by clan access."""
from datetime import datetime, timezone
from functools import partial
import json
import asyncio
import time
from uuid import UUID
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from utils import war_reminders as reminders
from .server_management import API, GUILD_ID, require_manage, mongo, discord
from .manage_clans import tag
from .manage_operations import revision


async def clan(request, db):
    row = await db.clans.find_one({'tag': tag(request)})
    if not row:
        raise web.HTTPNotFound(text='Clan removed. Refresh the directory.')
    return row


async def channel(request, value):
    if not value:
        raise web.HTTPBadRequest(text='Choose a channel first.')
    found = await discord(request, 'GET', f'/channels/{value}')
    if str(found.get('guild_id')) != str(GUILD_ID) or found.get('type') not in (0, 5):
        raise web.HTTPBadRequest(text='Choose a text or announcement channel in this server.')


async def read(request):
    await require_manage(request, 'clans')
    async with mongo(request) as db:
        row = await clan(request, db)
        config = await reminders.collection(db).find_one({'_id': row['tag']})
        history = await reminders.collection(db, 'war_reminder_deliveries').find({'clan_tag': row['tag']}, {'_id': 0}).sort('at', -1).limit(15).to_list(length=15)
        state = await reminders.collection(db, 'war_reminder_status').find_one({'_id': row['tag']}, {'_id': 0})
    return web.json_response(dict(settings=reminders.settings(config), revision=revision(config), history=history, status=state), dumps=partial(json.dumps, default=lambda value: value.replace(tzinfo=timezone.utc).isoformat() if isinstance(value, datetime) and value.tzinfo is None else value.isoformat() if isinstance(value, datetime) else str(value)))


def candidate(body):
    try:
        return reminders.validate(body.get('settings'))
    except (ValueError, AttributeError) as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None


async def save(request):
    actor = await require_manage(request, 'clans', write=True)
    body = await request.json()
    config = candidate(body)
    if config['channel_id']:
        await channel(request, config['channel_id'])
    async with mongo(request) as db:
        row = await clan(request, db)
        coll = reminders.collection(db)
        before = await coll.find_one({'_id': row['tag']})
        if body.get('revision') != revision(before):
            raise web.HTTPConflict(text='Reminders changed. Reload before saving.')
        query = {'_id': row['tag'], 'version': before.get('version') if before else {'$exists': False}}
        try:
            result = await coll.update_one(query, {'$set': {**config, 'updated_by': actor['user_id'], 'updated_at': datetime.now(timezone.utc)}, '$inc': {'version': 1}}, upsert=before is None)
        except DuplicateKeyError:
            raise web.HTTPConflict(text='Reminders changed. Reload before saving.') from None
        if not result.matched_count and not result.upserted_id:
            raise web.HTTPConflict(text='Reminders changed. Reload before saving.')
    return await read(request)


async def preview(request):
    actor = await require_manage(request, 'clans')
    body = await request.json()
    config = candidate(body)
    event = event_key(body)
    async with mongo(request) as db:
        row = await clan(request, db)
    return web.json_response({'messages': await test_messages(request, row, config, event, body, actor)})


async def test_messages(request, row, config, event, body, actor):
    """Use only the authenticated editor's accounts; attack counts remain simulated."""
    from .providers import ProviderUnavailable
    if any(type(body.get(key, False)) is not bool for key in ('use_my_accounts', 'mention_me')):
        raise web.HTTPBadRequest(text='Check the test options.')
    sample = reminders.sample(row, event)
    if body.get('use_my_accounts'):
        uid = str(actor['user_id'])
        cache = request.app.setdefault('war_reminder_test_accounts', {})
        cached = cache.get(uid)
        if not cached or cached[0] < time.monotonic():
            providers = request.app['providers']
            try:
                tags = await providers.linked_tags(uid)
                if not tags:
                    raise web.HTTPBadRequest(text='No linked accounts found for your Discord account. Use sample players or link an account first.')
                # One compact test message, even for editors with many accounts.
                profiles = await asyncio.gather(*(providers.player(tag) for tag in sorted(tags)[:15]))
            except ProviderUnavailable:
                raise web.HTTPServiceUnavailable(text='Could not load your linked accounts. Try again shortly or use sample players.') from None
            if len(cache) >= 100:
                cache.clear()
            cache[uid] = (time.monotonic()+300, profiles)
        else:
            profiles = cached[1]
        sample['members'] = [dict(tag=p['tag'], name=p['name'], th=p['town_hall'], position=i+1,
                                  used=i % 2) for i, p in enumerate(profiles)]
    payloads = reminders.messages(sample, config, event, test=True,
        tester=str(actor['user_id']) if body.get('mention_me') else None)
    if body.get('use_my_accounts'):
        for payload in payloads:
            payload['content'] = payload['content'].replace('Sample players', 'Your linked accounts · Simulated attacks')
    return payloads


def event_key(body):
    value = str(body.get('event', '60'))
    if value != 'start' and (not value.isascii() or not value.isdigit() or not 1 <= int(value) <= 1440):
        raise web.HTTPBadRequest(text='Choose a reminder time to preview.')
    return value


async def test_send(request):
    actor = await require_manage(request, 'clans', write=True)
    body = await request.json()
    config = candidate(body)
    event = event_key(body)
    try:
        request_id = str(UUID(body.get('request_id', '')))
    except (ValueError, TypeError, AttributeError):
        raise web.HTTPBadRequest(text='Reload the test form and try again.') from None
    if type(body.get('mention_me', False)) is not bool:
        raise web.HTTPBadRequest(text='Check the test notification option.')
    await channel(request, config['channel_id'])
    async with mongo(request) as db:
        row = await clan(request, db)
        payload = (await test_messages(request, row, config, event, body, actor))[0]
        coll = reminders.collection(db, 'war_reminder_deliveries')
        key = 'test:'+request_id
        receipt = dict(_id=key, clan_tag=row['tag'], at=datetime.now(timezone.utc), event=event,
                       channel_id=config['channel_id'], status='sending', test=True, actor=actor['user_id'])
        try:
            await coll.insert_one(receipt)
        except DuplicateKeyError:
            raise web.HTTPConflict(text='This test was already submitted. Check delivery history before sending another.') from None
        try:
            sent = await discord(request, 'POST', f"/channels/{config['channel_id']}/messages", json=payload)
        except Exception:
            await coll.update_one({'_id': key}, {'$set': {'status': 'uncertain', 'detail': 'Discord did not confirm delivery. Check the channel before sending another test.'}})
            raise
        url = f"https://discord.com/channels/{GUILD_ID}/{config['channel_id']}/{sent['id']}"
        await coll.update_one({'_id': key}, {'$set': {'status': 'sent', 'url': url}})
    return web.json_response({'url': url})


BASE = API+'/clans/{tag}/war-reminders'
routes = [web.get(BASE, read), web.put(BASE, save), web.post(BASE+'/preview', preview), web.post(BASE+'/test', test_send)]
