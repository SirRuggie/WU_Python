"""Temporary SQLite and fake Discord only; never load production credentials."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import player_cards as fixture
from aiohttp import web
from cwl_web.server_management import GUILD_ID
from utils.cwl_roster_image_store import RosterImageStore

app = fixture.app
channels = [
    {'id': '111111111111111111', 'name': 'main-images', 'type': 0},
    {'id': '222222222222222222', 'name': 'lazy-images', 'type': 0},
    {'id': '333333333333333333', 'name': 'staff-tests', 'type': 0},
]
mode = {'delay': 0, 'next': '', 'no_send': False}
calls = []
baseline = None


class ChannelTransport:
    async def list_channels(self):
        return channels

    async def list_roles(self):
        return []


app['announcement_transport'] = ChannelTransport()


async def discord(method, path, *, roster_delivery=False, **kwargs):
    if method == 'GET':
        channel = next(c for c in channels if c['id'] == path.split('/')[-1])
        return {**channel, 'guild_id': str(GUILD_ID)}
    assert method in ('POST', 'PATCH'), 'The fixture forbids DELETE'
    payload = kwargs.get('json')
    files = 0
    if 'data' in kwargs:
        for header, _, value in kwargs['data']._fields:
            if header['name'] == 'payload_json':
                payload = json.loads(value)
            else:
                files += 1
    calls.append({'method': method, 'path': path, 'files': files, 'payload': payload})
    await asyncio.sleep(float(mode['delay']))
    outcome = mode['next']
    mode['next'] = ''
    if outcome == 'timeout':
        raise TimeoutError('Fake timeout after send')
    if outcome == '429':
        raise web.HTTPTooManyRequests(text='{"retry_after":0.2}', content_type='application/json')
    if outcome == '500':
        if roster_delivery:
            from cwl_web.server_management import DiscordDeliveryUncertain
            raise DiscordDeliveryUncertain('Fake Discord 500 after send')
        raise web.HTTPServiceUnavailable()
    if outcome == '404':
        raise web.HTTPNotFound()
    return {'id': path.split('/')[-1] if method == 'PATCH' else str(555555555555555555 + len(calls))}


app['server_management_discord'] = discord


def state():
    with app['store'].tx() as db:
        return {
            'counts': [dict(r) for r in db.execute(
                'SELECT s.season_id,s.pool,COUNT(*) signups,SUM(r.assigned_clan_tag IS NOT NULL) assigned,SUM(r.kept) locks '
                'FROM signups s JOIN roster_entries r ON s.season_id=r.season_id AND s.tag=r.tag GROUP BY s.season_id,s.pool')],
            'publications': [dict(r) for r in db.execute('SELECT season_id,version,withdrawn_at FROM roster_publications')],
            'image_posts': [dict(r) for r in db.execute('SELECT * FROM roster_image_posts')],
            'test_posts': db.execute('SELECT COUNT(*) FROM roster_test_messages').fetchone()[0],
        }


@web.middleware
async def controls(request, handler):
    if request.path == '/qa/images':
        if request.method == 'POST':
            values = await request.json()
            for key in mode:
                if key in values:
                    mode[key] = values[key]
            return web.json_response(mode)
        return web.json_response({'baseline': baseline, 'current': state(), 'discord': calls})
    response = await handler(request)
    if mode['no_send'] and request.path.endswith('/auth/me') and response.status == 200:
        body = json.loads(response.text)
        body['is_owner'] = False
        body['dashboard_permissions'] = [p for p in body['dashboard_permissions'] if p != 'cwl_send']
        return web.json_response(body)
    return response


app.middlewares.insert(0, controls)


async def main():
    global baseline
    with app['store'].tx() as db:
        # Keep all accounts but make the required two Main / six Lazy pools.
        for i, clan in enumerate(fixture.clans):
            pool = 'main' if i < 2 else 'lazy'
            db.execute('UPDATE lineup_rules SET pool=?,min_weight=NULL,max_weight=NULL WHERE tag=?', (pool, clan))
            db.execute('UPDATE signups SET pool=? WHERE tag IN (SELECT tag FROM roster_entries WHERE assigned_clan_tag=?)', (pool, clan))
        db.execute("INSERT INTO seasons(id,label,status,signup_open) VALUES(3,'Hidden roster','draft',0),(4,'Updated roster v2','draft',0)")
        for sid in (3, 4):
            for table in ('signups', 'roster_entries', 'lineup', 'lineup_rules'):
                cols = [r['name'] for r in db.execute(f'PRAGMA table_info({table})')]
                selection = ','.join(str(sid) if c == 'season_id' else c for c in cols)
                db.execute(f"INSERT INTO {table} ({','.join(cols)}) SELECT {selection} FROM {table} WHERE season_id=1")
    storage = RosterImageStore(app['store'])
    for pool, channel in zip(('main', 'lazy'), channels):
        storage.configure(pool, channel['id'], channel['name'], 'fixture')
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', fixture.PORT).start()
    base = f'http://127.0.0.1:{fixture.PORT}/api/cwl'
    async with fixture.ClientSession(cookie_jar=fixture.CookieJar(unsafe=True)) as session:
        await session.post(base + '/dev/login')
        me = await (await session.get(base + '/auth/me')).json()
        headers = {'X-CSRF-Token': me['csrf_token']}

        async def publish(sid):
            draft = await (await session.get(base + f'/seasons/{sid}/publication')).json()
            response = await session.post(base + f'/seasons/{sid}/publication', headers=headers, json={
                'revision': draft['draft_revision'], 'acknowledge_unassigned': True, 'joining_instructions': 'Fixture only'})
            assert response.status == 201, await response.text()

        for sid in (1, 3, 4):
            await publish(sid)
        draft = await (await session.get(base + '/seasons/3/publication')).json()
        response = await session.post(base + '/seasons/3/publication/withdraw', headers=headers,
                                      json={'revision': draft['draft_revision'], 'version': 1})
        assert response.status == 200, await response.text()
        # Seed v1 posts through the real endpoint and fake Discord for the update review.
        for i, clan in enumerate(fixture.clans):
            response = await session.post(base + f'/seasons/4/roster-image-posts/{clan.replace("#", "%23")}',
                headers=headers, json={'pool': 'main' if i < 2 else 'lazy', 'version': 1, 'request_id': f'{i:024x}'})
            assert response.status == 200, await response.text()
        with app['store'].tx() as db:
            db.execute("INSERT INTO clans(tag,name) VALUES('#U2Y','New hosting clan') ON CONFLICT(tag) DO UPDATE SET name=excluded.name")
            db.execute("INSERT OR IGNORE INTO lineup(season_id,tag) VALUES(4,'#U2Y')")
            db.execute("INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES(4,'#U2Y','lazy',15) ON CONFLICT(season_id,tag) DO UPDATE SET pool='lazy',capacity=15")
            db.execute("UPDATE roster_entries SET assigned_clan_tag='#U2Y' WHERE season_id=4 AND assigned_clan_tag=?", (fixture.clans[-1],))
        await publish(4)
    baseline = state()
    calls.clear()
    print(json.dumps({'ready': True, 'baseline': baseline}), flush=True)
    await asyncio.Event().wait()


asyncio.run(main())
