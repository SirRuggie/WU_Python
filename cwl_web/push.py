"""Explicitly opted-in browser reminders, using durable per-device settings."""
import asyncio
import base64
import hashlib
import json
import logging
import os
import time
from urllib.parse import urlsplit

from aiohttp import web
from .providers import ProviderUnavailable

API = '/api/cwl/push'
LOG = logging.getLogger(__name__)
MAX_OFFSET_MINUTES = 24 * 60
MAX_REMINDER_TIMES = 5
FRESH_ACCOUNTS_TIMEOUT = 20
FRESH_VIEW_TIMEOUT = 20
FRESH_CHECK_TIMEOUT = 75
SCHEMA = '''
CREATE TABLE IF NOT EXISTS push_subscriptions (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, subscription TEXT NOT NULL,
 enabled INTEGER NOT NULL DEFAULT 0, tags TEXT NOT NULL, war INTEGER NOT NULL,
 cwl INTEGER NOT NULL, offsets TEXT NOT NULL, updated_at INTEGER NOT NULL,
 test_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS push_owner ON push_subscriptions(user_id);
CREATE TABLE IF NOT EXISTS push_deliveries (
 subscription_id TEXT NOT NULL REFERENCES push_subscriptions(id) ON DELETE CASCADE,
 event TEXT NOT NULL, offset INTEGER NOT NULL, expires_at INTEGER NOT NULL,
 PRIMARY KEY(subscription_id,event,offset)
);
'''


def config():
    private = os.getenv('CWL_PUSH_VAPID_PRIVATE_KEY', '').strip()
    public = os.getenv('CWL_PUSH_VAPID_PUBLIC_KEY', '').strip()
    subject = os.getenv('CWL_PUSH_VAPID_SUBJECT', '').strip()
    return private, public, subject


def available():
    private, public, subject = config()
    return bool(private and os.path.isfile(private) and os.access(private, os.R_OK) and public and subject.startswith(('mailto:', 'https://')))


def _subscription(value):
    if not isinstance(value, dict) or not isinstance(value.get('endpoint'), str):
        raise web.HTTPBadRequest(text='Invalid push subscription')
    endpoint = value['endpoint']
    try:
        url = urlsplit(endpoint)
        host = (url.hostname or '').lower()
    except ValueError:
        raise web.HTTPBadRequest(text='Invalid push service URL') from None
    allowed = host in {'fcm.googleapis.com', 'updates.push.services.mozilla.com', 'web.push.apple.com'} or host.endswith('.notify.windows.com')
    try:
        port = url.port
    except ValueError:
        port = -1
    if not allowed or url.scheme != 'https' or port not in (None, 443) or url.username or url.password or url.fragment or len(endpoint) > 4096:
        raise web.HTTPBadRequest(text='Unsupported browser push service')
    keys = value.get('keys', {})
    normalized = {}
    for key, size in [('p256dh', 65), ('auth', 16)]:
        raw = keys.get(key) if isinstance(keys, dict) else None
        try:
            if not isinstance(raw, str) or len(raw) > 128:
                raise ValueError()
            decoded = base64.b64decode(raw + '=' * (-len(raw) % 4), altchars=b'-_', validate=True)
            if len(decoded) != size or (key == 'p256dh' and decoded[0] != 4):
                raise ValueError()
        except Exception:
            raise web.HTTPBadRequest(text='Invalid browser push keys') from None
        normalized[key] = raw
    return {'endpoint': endpoint, 'keys': normalized}


def _public(row):
    return {key: row[key] for key in ('id', 'updated_at')} | {
        'enabled': bool(row['enabled']), 'tags': json.loads(row['tags']),
        'war': bool(row['war']), 'cwl': bool(row['cwl']), 'offsets': json.loads(row['offsets'])}


async def settings(request):
    from .app import _require
    uid = _require(request)['user_id']
    with request.app['store'].tx() as db:
        rows = db.execute('SELECT * FROM push_subscriptions WHERE user_id=?', (uid,)).fetchall()
    return web.json_response({'available': available(), 'public_key': config()[1] if available() else None,
                              'subscriptions': [_public(row) for row in rows]})


async def save(request):
    from .app import _require
    uid = _require(request)['user_id']
    if not available():
        raise web.HTTPServiceUnavailable(text='Notifications are not configured yet')
    body = await request.json()
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text='Invalid reminder settings')
    sub = _subscription(body.get('subscription'))
    for key in ('enabled', 'war', 'cwl'):
        if type(body.get(key)) is not bool:
            raise web.HTTPBadRequest(text='Choose reminder settings')
    tags, offsets = body.get('tags'), body.get('offsets')
    if not isinstance(tags, list) or not tags or len(tags) > 100 or any(not isinstance(t, str) for t in tags):
        raise web.HTTPBadRequest(text='Select linked accounts')
    if not isinstance(offsets, list) or not offsets or len(offsets) > MAX_REMINDER_TIMES or len(set(str(n) for n in offsets)) != len(offsets) or any(type(n) is not int or not 1 <= n <= MAX_OFFSET_MINUTES for n in offsets):
        raise web.HTTPBadRequest(text='Choose up to 5 different reminder times, from 1 minute to 24 hours')
    if body['enabled'] and not (body['war'] or body['cwl']):
        raise web.HTTPBadRequest(text='Select War or CWL')
    try:
        links = await asyncio.wait_for(request.app['providers'].linked_tags(uid), 10)
    except Exception as exc:
        raise ProviderUnavailable('Linked accounts could not be checked; reminder settings were not changed') from exc
    if not set(tags) <= set(links):
        raise web.HTTPForbidden(text='Only your linked accounts can receive reminders')
    sid = hashlib.sha256(sub['endpoint'].encode()).hexdigest()
    with request.app['store'].tx() as db:
        existing = db.execute('SELECT * FROM push_subscriptions WHERE id=?', (sid,)).fetchone()
        # A browser changing Discord identities must explicitly remove its old subscription first.
        if existing and existing['user_id'] != uid:
            raise web.HTTPConflict(text='Unsubscribe this browser before using another Discord account')
        count = db.execute('SELECT COUNT(*) FROM push_subscriptions WHERE user_id=?', (uid,)).fetchone()[0]
        if not existing and count >= 10:
            raise web.HTTPBadRequest(text='Remove an old device before adding another')
        db.execute('INSERT INTO push_subscriptions(id,user_id,subscription,enabled,tags,war,cwl,offsets,updated_at) VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET subscription=excluded.subscription,enabled=excluded.enabled,tags=excluded.tags,war=excluded.war,cwl=excluded.cwl,offsets=excluded.offsets,updated_at=excluded.updated_at',
                   (sid, uid, json.dumps(sub), int(body['enabled']), json.dumps(sorted(set(tags))), int(body['war']), int(body['cwl']), json.dumps(sorted(set(offsets), reverse=True)), int(time.time())))
        row = db.execute('SELECT * FROM push_subscriptions WHERE id=?', (sid,)).fetchone()
    return web.json_response(_public(row))


async def remove(request):
    from .app import _require
    uid = _require(request)['user_id']
    with request.app['store'].tx() as db:
        db.execute('DELETE FROM push_subscriptions WHERE id=? AND user_id=?', (request.match_info['sid'], uid))
    return web.json_response({'ok': True})


def send(subscription, payload):
    """No redirects/proxies: subscriptions may only target known browser services."""
    import requests
    from pywebpush import webpush, WebPushException
    class DirectSession(requests.Session):
        def request(self, *args, **kwargs):
            kwargs['allow_redirects'] = False
            kwargs['timeout'] = 15
            return super().request(*args, **kwargs)
    private, _, subject = config()
    with DirectSession() as session:
        session.trust_env = False
        try:
            response = webpush(subscription_info=_subscription(subscription), data=json.dumps(payload),
                               vapid_private_key=private, vapid_claims={'sub': subject},
                               ttl=120, timeout=15, requests_session=session)
            return 'sent' if 200 <= response.status_code < 300 else 'failed'
        except WebPushException as exc:
            return 'expired' if exc.response is not None and exc.response.status_code in (404, 410) else 'failed'
        except Exception as exc:
            LOG.warning('Push delivery failed: %s', type(exc).__name__)
            return 'failed'


async def test(request):
    from .app import _require
    uid = _require(request)['user_id']
    if not available():
        raise web.HTTPServiceUnavailable(text='Notifications are not configured yet')
    now = int(time.time())
    with request.app['store'].tx() as db:
        row = db.execute('SELECT * FROM push_subscriptions WHERE id=? AND user_id=?', (request.match_info['sid'], uid)).fetchone()
        if not row:
            raise web.HTTPNotFound(text='Device subscription not found')
        if now - row['test_at'] < 60:
            raise web.HTTPTooManyRequests(text='Wait a minute before another test')
        db.execute('UPDATE push_subscriptions SET test_at=? WHERE id=?', (now, row['id']))
    result = await asyncio.to_thread(send, json.loads(row['subscription']), {'title': 'Warriors United reminders', 'body': 'Notifications are ready. Tap to open Tasks.', 'url': '/tasks', 'tag': 'wu-push-test'})
    if result == 'expired':
        with request.app['store'].tx() as db:
            db.execute('DELETE FROM push_subscriptions WHERE id=?', (row['id'],))
    if result != 'sent':
        raise web.HTTPServiceUnavailable(text='Notification could not be delivered. Re-enable reminders on this device.')
    return web.json_response({'ok': True})


def plan(snapshot, preferences, now):
    """Only current attacks, near a selected deadline; never replay old deadlines."""
    selected = set(json.loads(preferences['tags']))
    groups = {}
    for kind in ('war', 'cwl'):
        if not preferences[kind]:
            continue
        view = snapshot.get('views', {}).get(kind, {})
        if not view.get('ok'):
            continue
        for row in view.get('rows', []):
            end, remaining = row.get('ends_at'), row.get('remaining')
            clan = row.get('clan_tag')
            if not clan or row.get('tag') not in selected or row.get('state') != 'inWar' or not isinstance(end, (int, float)) or not isinstance(remaining, (int, float)) or remaining <= 0 or end <= now:
                continue
            for offset in json.loads(preferences['offsets']):
                due = end - offset * 60
                if preferences['updated_at'] <= due <= now and now - due <= 120:
                    event = f"{kind}:{clan}:{int(end)}"
                    key = (event, offset)
                    group = groups.setdefault(key, {'event': event, 'offset': offset, 'expires_at': int(end), 'clan': clan, 'clan_name': row.get('clan_name') or clan, 'kind': kind, 'accounts': {}})
                    group['accounts'][row['tag']] = {'tag': row['tag'], 'name': row.get('name') or row['tag'], 'remaining': int(remaining)}
    return list(groups.values())


async def _fresh_view(kind, load):
    """A slow/unavailable view must not discard the other fresh reminder view."""
    from .todo import _view, _unavailable
    try:
        return _view(await asyncio.wait_for(load, FRESH_VIEW_TIMEOUT))
    except Exception as exc:
        LOG.warning('Push %s data check failed: %s', kind, type(exc).__name__)
        return _unavailable('Fresh reminder data is unavailable')


async def fresh(app, uid):
    from .todo import get_clash_client, _history
    from utils import todo_data
    links = await asyncio.wait_for(app['providers'].linked_tags(uid), 10)
    with app['store'].tx() as db:
        rows = db.execute('SELECT tags,war,cwl FROM push_subscriptions WHERE user_id=? AND enabled=1', (uid,)).fetchall()
    selected = {tag for row in rows for tag in json.loads(row['tags'])}
    tags = [tag for tag in links if tag in selected][:100]
    if not tags:
        return {'views': {}}
    underlying = await get_clash_client(app)
    class FreshClient:
        # coc.py supports lookup_cache per request. Do not mutate shared client flags.
        def __getattr__(self, name):
            method = getattr(underlying, name)
            if name in {'get_player', 'get_clan_war', 'get_league_group', 'get_league_war'}:
                async def call(*args, **kwargs):
                    return await method(*args, **dict(kwargs, lookup_cache=False))
                return call
            return method
    client = FreshClient()
    sem = todo_data.new_semaphore()
    with todo_data.fresh_reads():
        accounts, _ = await asyncio.wait_for(
            todo_data.fetch_accounts(client, tags, sem=sem), FRESH_ACCOUNTS_TIMEOUT)
        candidates, _ = await _history(app, tags)
        builders = {'war': todo_data.build_war_view, 'cwl': todo_data.build_cwl_view}
        kinds = [kind for kind in builders if any(row[kind] for row in rows)]
        views = await asyncio.gather(*(
            _fresh_view(kind, builders[kind](client, accounts, sem=sem, candidates=candidates))
            for kind in kinds
        ))
    return {'views': dict(zip(kinds, views))}


def reminder_payload(item):
    """Keep the collapsed preview useful, with account details when expanded."""
    def label(value, limit):
        value = ' '.join(str(value).split())
        return value if len(value) <= limit else value[:limit - 1] + '…'

    accounts = list(item['accounts'].values())
    total = sum(account['remaining'] for account in accounts)
    count = len(accounts)
    lines = [f"{total} {'attack' if total == 1 else 'attacks'} remaining across {count} {'account' if count == 1 else 'accounts'}"]
    for account in accounts[:3]:
        remaining = account['remaining']
        lines.append(f"{label(account['name'], 40)}: {remaining} {'attack' if remaining == 1 else 'attacks'}")
    if count > 3:
        more = count - 3
        lines.append(f"+{more} more {'account' if more == 1 else 'accounts'} · Open Todo")
    hours, minutes = divmod(item['offset'], 60)
    timing = ' '.join(part for part in (f'{hours}h' if hours else '', f'{minutes}m' if minutes else '') if part)
    kind = '🏆 CWL' if item['kind'] == 'cwl' else '⚔️ War'
    return {
        'title': f"{label(item['clan_name'], 60)} · {kind} · {timing} remaining",
        'body': '\n'.join(lines),
        'url': '/tasks',
        'tag': 'wu-' + hashlib.sha256(f"{item['event']}:{item['offset']}".encode()).hexdigest()[:24],
    }


async def process_user(app, uid):
    with app['store'].tx() as db:
        active = db.execute('SELECT 1 FROM push_subscriptions WHERE user_id=? AND enabled=1 LIMIT 1', (uid,)).fetchone()
    if not active:
        return
    snapshot = await asyncio.wait_for(fresh(app, uid), FRESH_CHECK_TIMEOUT)
    now = int(time.time())
    with app['store'].tx() as db:
        subscriptions = db.execute('SELECT * FROM push_subscriptions WHERE user_id=? AND enabled=1', (uid,)).fetchall()
    for sub in subscriptions:
        for item in plan(snapshot, sub, now):
            with app['store'].tx() as db:
                current = db.execute('SELECT * FROM push_subscriptions WHERE id=? AND enabled=1', (sub['id'],)).fetchone()
                if not current or dict(current) != dict(sub):
                    break
                cursor = db.execute('INSERT OR IGNORE INTO push_deliveries VALUES (?,?,?,?)', (sub['id'], item['event'], item['offset'], item['expires_at']))
                claimed = bool(cursor.rowcount)
            if not claimed:
                continue
            payload = reminder_payload(item)
            result = await asyncio.to_thread(send, json.loads(sub['subscription']), payload)
            if result == 'failed':
                LOG.warning('Push clan reminder delivery failed; claim retained to avoid duplicate notification')
            if result == 'expired':
                with app['store'].tx() as db:
                    db.execute('DELETE FROM push_subscriptions WHERE id=?', (sub['id'],))
                break
            # Claim before delivery prevents duplicate alerts after process restart.
            # Do not retry ambiguous failures: delivery may already have succeeded.


async def worker(app):
    while True:
        try:
            with app['store'].tx() as db:
                db.execute('DELETE FROM push_deliveries WHERE expires_at<?', (int(time.time()) - 86400,))
                users = [row[0] for row in db.execute('SELECT DISTINCT user_id FROM push_subscriptions WHERE enabled=1')]
            sem = asyncio.Semaphore(3)
            async def one(uid):
                async with sem:
                    try:
                        await process_user(app, uid)
                    except Exception as exc:
                        LOG.warning('Push reminder check failed: %s', type(exc).__name__)
            await asyncio.gather(*(one(uid) for uid in users))
        except Exception as exc:
            LOG.warning('Push worker failed: %s', type(exc).__name__)
        await asyncio.sleep(45)


async def lifecycle(app):
    task = asyncio.create_task(worker(app)) if available() and not app['dev_fixture'] else None
    yield
    if task:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def routes():
    return [web.get(API, settings), web.put(API + '/subscriptions', save),
            web.delete(API + '/subscriptions/{sid}', remove), web.post(API + '/subscriptions/{sid}/test', test)]
