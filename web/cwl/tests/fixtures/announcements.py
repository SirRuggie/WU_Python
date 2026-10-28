"""Isolated announcement review: temporary SQLite, MemoryMongo, fake Discord only."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.environ['WU_FIXTURE_BACKEND'])
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(os.environ['WU_FIXTURE_BACKEND']) / 'tests'))
import qa_network_guard
from aiohttp import web, ClientSession, CookieJar
from cwl_web import create_app
from cwl_web.manage_bridge import GUILD_ID
from test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign, cwl_web_bridge

static, port = Path(sys.argv[1]), int(sys.argv[2])
assert 8900 <= port <= 8999
folder = tempfile.TemporaryDirectory(prefix='wu-announcements-fixture-')
app = create_app(db_path=folder.name + '/fixture.sqlite', dev_fixture=True, secure_cookies=False, static_dir=static)
mongo = MemoryMongo()
app['manage_bridge_mongo'] = mongo
requests, fake_posts, outbound = [], [], []
mode = {'no_send': False, 'stale_worker': False, 'slow': False}
channels = [{'id': '111111111111111111', 'name': 'main-cwl', 'type': 0}, {'id': '222222222222222222', 'name': 'lazy-cwl', 'type': 0}, {'id': '444444444444444444', 'name': 'staff-tests', 'type': 0}]

class FakeDiscord:
    async def list_channels(self):
        return channels
    async def list_roles(self):
        return [{'id': '333333333333333333', 'name': 'CWL players'}]
    async def get_channel(self, cid):
        return {**next(c for c in channels if c['id'] == str(cid)), 'guild_id': str(GUILD_ID)}

app['announcement_transport'] = FakeDiscord()
async def discord(method, path, **kwargs):
    if method == 'GET':
        return {'guild_id': str(GUILD_ID), 'type': 0}
    fake_posts.append({'method': method, 'path': path, 'payload': kwargs})
    return {'id': '555555555555555555'}
app['server_management_discord'] = discord
original_allowed = qa_network_guard._allowed

def guarded(address):
    try:
        original_allowed(address)
    except RuntimeError:
        outbound.append(str(address))
        raise
qa_network_guard._allowed = guarded

@web.middleware
async def qa(request, handler):
    if request.path.startswith('/api/'):
        requests.append({'at': datetime.now(timezone.utc).isoformat(), 'method': request.method, 'path': request.path_qs})
    if request.path.endswith('/manage-bridge'):
        if mode['slow']:
            await asyncio.sleep(13)
        if not mode['stale_worker']:
            await cwl_web_bridge.mark_worker_alive(mongo, GUILD_ID)
    response = await handler(request)
    if mode['no_send'] and request.path.endswith('/auth/me') and response.status == 200:
        payload = json.loads(response.text)
        payload['is_owner'] = False
        payload['dashboard_permissions'] = [p for p in payload.get('dashboard_permissions', []) if p != 'cwl_send']
        response = web.json_response(payload)
    return response
app.middlewares.insert(0, qa)

def state():
    return {
        'counts': [dict(r) for r in app['store'].rows("SELECT s.season_id,s.pool,COUNT(*) signups,SUM(r.assigned_clan_tag IS NOT NULL) assigned,SUM(r.kept) locks FROM signups s JOIN roster_entries r ON s.season_id=r.season_id AND s.tag=r.tag GROUP BY s.season_id,s.pool")],
        'publications': [dict(r) for r in app['store'].rows('SELECT season_id,version,withdrawn_at FROM roster_publications ORDER BY season_id,version')],
        'bindings': [dict(r) for r in app['store'].rows('SELECT * FROM manage_campaign_bindings ORDER BY season_id')],
        'send_records': len([v for v in mongo.bot_config.documents.values() if v.get('kind') == cwl_web_bridge.REQUEST_KIND]),
        'fake_posts': len(fake_posts),
    }
baseline = None
async def qa_state(request):
    return web.json_response({'baseline': baseline, 'current': state(), 'requests': requests, 'outbound_attempts': outbound, 'db': folder.name + '/fixture.sqlite'})
async def qa_mode(request):
    values = await request.json()
    for key in mode:
        if key in values:
            mode[key] = bool(values[key])
    if mode['stale_worker']:
        await mongo.bot_config.update_one({'_id': cwl_web_bridge.worker_id(GUILD_ID)}, {'$set': {'updated_at': '2020-01-01T00:00:00Z'}})
    return web.json_response(mode)
app.router.add_get('/qa/state', qa_state)
app.router.add_post('/qa/mode', qa_mode)

async def main():
    global baseline
    with app['store'].tx() as db:
        db.execute("UPDATE seasons SET label='November 2026'")
        for sid, label in [(2, 'December 2026'), (3, 'January 2027'), (4, 'February 2027'), (5, 'March 2027'), (6, 'April 2027')]:
            db.execute("INSERT INTO seasons(id,label,status,signup_open) VALUES (?,?,'draft',0)", (sid, label))
        for tag, name in [('#QG02CY8LG', 'Warriors United'), ('#P02CY8LQ', 'Morning Woods')]:
            db.execute('INSERT INTO clans(tag,name) VALUES (?,?)', (tag, name))
        for sid in range(1, 7):
            for ci, clan_tag in enumerate(['#QG02CY8LG', '#P02CY8LQ']):
                pool = 'main' if ci == 0 else 'lazy'
                db.execute('INSERT INTO lineup(season_id,tag) VALUES (?,?)', (sid, clan_tag))
                db.execute('INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES (?,?,?,15)', (sid, clan_tag, pool))
                for n in range(3):
                    tag = '#QG02CY' + 'PL'[ci] + 'YLC'[n]
                    db.execute('INSERT INTO signups(season_id,tag,user_id,player_name,town_hall,pool,prefer_crystal_1_or_lower) VALUES (?,?,?,?,?,?,0)', (sid, tag, '505227988229554179', ['Aurora', 'Blaze', 'Cinder'][n], 18-n, pool))
                    db.execute('INSERT INTO roster_entries(season_id,tag,assigned_clan_tag,kept,manual_weight) VALUES (?,?,?,?,?)', (sid, tag, clan_tag, int(n == 0), 175000-n*1000))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '127.0.0.1', port).start()
    base = f'http://127.0.0.1:{port}/api/cwl'
    async with ClientSession(cookie_jar=CookieJar(unsafe=True)) as session:
        await session.post(base + '/dev/login')
        me = await (await session.get(base + '/auth/me')).json()
        for sid in range(1, 7):
            for version in range(2 if sid == 3 else 1):
                draft = await (await session.get(base + f'/seasons/{sid}/publication')).json()
                response = await session.post(base + f'/seasons/{sid}/publication', headers={'X-CSRF-Token': me['csrf_token']}, json={'revision': draft['draft_revision'], 'acknowledge_unassigned': True, 'joining_instructions': 'Finish your war, then join your assigned clan.'})
                assert response.status == 201, await response.text()
            if sid == 5:
                draft = await (await session.get(base + f'/seasons/{sid}/publication')).json()
                response = await session.post(base + f'/seasons/{sid}/publication/withdraw', headers={'X-CSRF-Token': me['csrf_token']}, json={'revision': draft['draft_revision'], 'version': 1})
                assert response.status == 200, await response.text()
    for sid, cycle in [(1, '2026-11'), (2, '2026-12'), (3, '2027-01'), (4, '2027-02'), (5, '2027-03'), (6, '2027-04')]:
        if sid != 1:
            with app['store'].tx() as db:
                db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES (?,?)', (sid, cycle))
        draft = await cwl_campaign.new_draft(mongo, GUILD_ID, 1, cycle)
        campaign = draft['campaign']
        for index, pool in enumerate(['main', 'lazy']):
            item = campaign['messages']['roster']['variants'][pool]
            item.update(destination_channel_id=int(channels[index]['id']), title='Your CWL roster', body='Your clan assignment is ready. Finish your current war before moving.', role_ids=[333333333333333333], media_url='', enabled=True)
            item['buttons'] = [{'label': 'My clan assignments', 'url': f'https://dash.warriorsunited.cc/assignments?season={sid}'}]
            if sid == 2:
                item['buttons'] = []
        # Seed the fake campaign snapshot; links are never followed by the review browser.
        await mongo.bot_config.update_one({'_id': cwl_campaign.cycle_id(GUILD_ID, cycle)}, {'$set': {'campaign': campaign, 'revision': 1, 'kind': 'cwl_campaign', 'cycle': cycle, 'guild_id': GUILD_ID}}, upsert=True)
        states = {3: ['sent', 'failed'], 4: ['uncertain', 'stale'], 6: ['pending', 'sending']}.get(sid, [])
        for pool, status in zip(['main', 'lazy'], states):
            await mongo.bot_config.update_one({'_id': cwl_web_bridge.request_id(GUILD_ID, cycle, pool)}, {'$set': {'kind': cwl_web_bridge.REQUEST_KIND, 'status': status, 'publication_version': 1, 'cycle': cycle, 'pool': pool, 'guild_id': GUILD_ID, 'updated_at': '2026-10-27T13:10:00Z', 'error': 'Channel unavailable' if status == 'failed' else None}}, upsert=True)
            if status == 'sent':
                await cwl_campaign.record_delivery(mongo, GUILD_ID, cycle, {'occurrence_id': cwl_campaign.occurrence_id(cycle, 'roster', pool), 'status': 'sent', 'message_url': 'https://discord.com/channels/1/2/3', 'at': '2026-10-27T13:10:00Z'})
    await cwl_web_bridge.mark_worker_alive(mongo, GUILD_ID)
    baseline = state()
    requests.clear()
    print(json.dumps({'ready': True, 'baseline': baseline}), flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
