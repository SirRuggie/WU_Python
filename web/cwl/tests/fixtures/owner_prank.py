"""Loopback-only owner prank preview with fake owners and fake Discord.

Usage: WU_FIXTURE_BACKEND=/absolute/isolated/backend python owner_prank.py
       /absolute/isolated/frontend/dist 8979
"""

import importlib
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

TARGET = '100000000000000001'
NOTIFY = '100000000000000002'
STAFF = '100000000000000003'
FAKE_OWNERS = frozenset({TARGET, NOTIFY})

# Override any inherited production configuration before importing the app.
os.environ.update({
    'PRANK_ENABLED': 'true',
    'PRANK_TARGET_USER_ID': TARGET,
    'PRANK_NOTIFY_USER_ID': NOTIFY,
})

import tour_deadline as fixture  # noqa: E402
import qa_network_guard  # noqa: E402,F401 - blocks every non-loopback socket
from aiohttp import web  # noqa: E402
from cwl_web import owner_prank  # noqa: E402
from utils import dashboard_access  # noqa: E402

app_module = importlib.import_module('cwl_web.app')
access_control = importlib.import_module('cwl_web.access_control')
for module in (app_module, access_control, owner_prank, dashboard_access):
    module.OWNER_IDS = FAKE_OWNERS

app = fixture.app
assert app['dev_fixture'] and Path(app['store'].path).is_relative_to(fixture.folder.name)
app['dev_identity'] = {'id': TARGET, 'username': 'Target fixture', 'guild_owner': False}

messages = []
identities = {
    'target': (TARGET, 'Target fixture'),
    'notify': (NOTIFY, 'Ruggie test fixture'),
    'staff': (STAFF, 'Staff fixture'),
}


async def fake_discord(method, path, **kwargs):
    if method != 'POST':
        raise RuntimeError('The prank fixture permits only fake DM POST calls.')
    if path == '/users/@me/channels':
        if kwargs.get('json') != {'recipient_id': NOTIFY}:
            raise RuntimeError('Unexpected fake DM recipient.')
        return {'id': 'fixture-prank-dm'}
    if path == '/channels/fixture-prank-dm/messages':
        payload = kwargs.get('json')
        if not isinstance(payload, dict) or payload.get('allowed_mentions') != {'parse': []}:
            raise RuntimeError('Unexpected fake DM payload.')
        messages.append(payload['content'])
        return {'id': str(len(messages))}
    raise RuntimeError('Unexpected Discord path in prank fixture.')


app['server_management_discord'] = fake_discord


def protected_counts():
    store = app['store']
    return {
        'signups': store.one('SELECT COUNT(*) AS count FROM signups')['count'],
        'roster_entries': store.one('SELECT COUNT(*) AS count FROM roster_entries')['count'],
        'roster_publications': store.one('SELECT COUNT(*) AS count FROM roster_publications')['count'],
        'by_season_and_pool': fixture.counts(),
    }


baseline = protected_counts()


def qa_snapshot():
    return {
        'baseline': baseline,
        'current': protected_counts(),
        'prank_rows': app['store'].rows(
            'SELECT user_id,card,branch,completed_at,notified,run,updated_at '
            'FROM owner_prank_state ORDER BY user_id'),
        'messages': list(messages),
        'selected_identity': app['dev_identity']['id'],
        'database': app['store'].path,
    }


def require_qa(request):
    if request.remote not in ('127.0.0.1', '::1') or not app['dev_fixture']:
        raise web.HTTPNotFound()


@web.middleware
async def prank_qa_state(request, handler):
    if request.path == '/qa/state':
        require_qa(request)
        if request.method != 'GET':
            raise web.HTTPMethodNotAllowed(request.method, ['GET'])
        return web.json_response(qa_snapshot())
    return await handler(request)


app.middlewares.insert(0, prank_qa_state)


async def select_identity(request):
    require_qa(request)
    choice = request.query.get('who')
    if choice not in identities:
        raise web.HTTPBadRequest(text='Choose target, notify, or staff.')
    uid, username = identities[choice]
    app['dev_identity'] = {'id': uid, 'username': username, 'guild_owner': False}
    return web.json_response({
        'selected_identity': uid,
        'message': 'Sign out and open a new local test session to use this identity.',
    })


async def reset_prank(request):
    require_qa(request)
    with app['store'].tx() as db:
        db.execute('DELETE FROM owner_prank_state')
    messages.clear()
    return web.json_response(qa_snapshot())


async def seed_prank(request):
    require_qa(request)
    try:
        body = await request.json()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text='Expected JSON object.') from None
    if not isinstance(body, dict) or set(body) - {'who', 'card', 'branch', 'completed'}:
        raise web.HTTPBadRequest(text='Invalid seed request.')
    choice = body.get('who', 'target')
    card = body.get('card')
    branch = body.get('branch', 'yes')
    completed = body.get('completed', False)
    if (choice not in ('target', 'notify') or type(card) is not int or not 1 <= card <= 15
            or branch not in ('yes', 'no') or type(completed) is not bool
            or completed and card != 15):
        raise web.HTTPBadRequest(text='Invalid prank seed.')
    uid = identities[choice][0]
    with app['store'].tx() as db:
        db.execute('INSERT INTO owner_prank_state(user_id,card,branch,completed_at,notified,run) '
                   "VALUES (?,?,?,CASE WHEN ? THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') ELSE NULL END,'[]',1) "
                   'ON CONFLICT(user_id) DO UPDATE SET card=excluded.card,branch=excluded.branch, '
                   'completed_at=excluded.completed_at,notified=excluded.notified,run=1, '
                   'updated_at=CURRENT_TIMESTAMP',
                   (uid, card, branch if card >= 2 else None, completed))
    return web.json_response(qa_snapshot())


app.router.add_get('/qa/prank/identity', select_identity)
app.router.add_post('/qa/prank/reset', reset_prank)
app.router.add_post('/qa/prank/seed', seed_prank)

if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=fixture.PORT)
