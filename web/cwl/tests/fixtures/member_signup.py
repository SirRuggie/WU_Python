"""Member-only review with temporary SQLite, fake Mongo and blocked external IO."""
import asyncio
import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(os.environ['WU_FIXTURE_BACKEND'])
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(Path(__file__).parent)]
import qa_network_guard  # noqa: E402
from aiohttp import web
from cwl_web import create_app
from cwl_web.manage_bridge import GUILD_ID
from test_cwl_dashboard_integration import MemoryMongo
from utils.cwl_campaign import cycle_id, default_campaign

PORT = int(sys.argv[2])
assert 8900 <= PORT <= 8999
folder = tempfile.TemporaryDirectory(prefix='wu-member-signup-')
identity = {'id': '100000000000000001', 'username': 'Luke fixture', 'guild_owner': False}
app = create_app(db_path=folder.name + '/sample.sqlite', dev_fixture=True,
                 dev_identity=identity, secure_cookies=False, static_dir=Path(sys.argv[1]))
provider = app['providers']
tags = ['#P222222Y', '#Q222222Y', '#G222222Y', '#L222222Y', '#R222222Y',
        '#C222222Y', '#J222222Y', '#V222222Y', '#U222222Y']
names = ['Aurora 032', 'Ace', 'Blaze', 'Cinder', 'Delta', 'Echo', 'Falcon', 'Gale', 'Halo']
owners = [identity['id']] * 5 + ['100000000000000002'] + ['100000000000000003'] * 3
provider.players = {tag: {'tag': tag, 'name': name, 'town_hall': 18,
                         'current_clan_tag': None, 'current_clan_name': None}
                    for tag, name in zip(tags, names)}

async def linked_tags(uid):
    return {tag: True for tag, owner in zip(tags, owners) if owner == str(uid)}

async def linked_owner(tag):
    return owners[tags.index(tag)] if tag in tags else None

provider.linked_tags = linked_tags
provider.linked_owner = linked_owner
mongo = MemoryMongo()
app['manage_bridge_mongo'] = mongo
now = datetime.now(timezone.utc)
with app['store'].tx() as db:
    db.execute("UPDATE seasons SET label='Open · 2 days' WHERE id=1")
    db.execute('UPDATE member_season SET season_id=1 WHERE id=1')
    for sid, label in [(2, 'Closed · 18 hours'), (3, 'Taking longer'), (4, 'Published'),
                       (5, 'Hidden'), (6, 'No campaign')]:
        db.execute('INSERT INTO seasons(id,label,status,signup_open) VALUES(?,?,?,?)',
                   (sid, label, 'draft', int(sid == 6)))
    for sid in range(1, 7):
        for index in (0, 1, 5):
            pool = 'lazy' if index == 1 else 'main'
            db.execute('INSERT INTO signups(season_id,tag,user_id,player_name,town_hall,pool,prefer_crystal_1_or_lower) VALUES(?,?,?,?,18,?,0)',
                       (sid, tags[index], owners[index], names[index], pool))
            db.execute('INSERT INTO roster_entries(season_id,tag,kept) VALUES(?,?,0)', (sid, tags[index]))
        if sid < 6:
            cycle = f'2026-{sid + 4:02}'
            deadline = now + (timedelta(days=2) if sid == 1 else timedelta(hours=-6) if sid == 2 else timedelta(days=-3))
            campaign = default_campaign()
            campaign['signup_deadline'] = {'at': deadline.isoformat()}
            key = cycle_id(GUILD_ID, cycle)
            mongo.bot_config.documents[key] = {'_id': key, 'campaign': campaign}
            db.execute('INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES(?,?)', (sid, cycle))
    for sid in (4, 5):
        db.execute('INSERT INTO roster_publications(id,season_id,version,revision,published_by,published_at,joining_instructions,assigned_count,unassigned_count,clans_json,withdrawn_at) VALUES(?,?,1,0,?,?,?,1,2,?,?)',
                   (sid, sid, identity['id'], now.isoformat(), '', '[]', now.isoformat() if sid == 5 else None))
        for index in (0, 1, 5):
            db.execute('INSERT INTO publication_accounts(publication_id,tag,user_id,player_name,town_hall,pool,prefer_crystal_1_or_lower,assigned_clan_tag,assigned_clan_name,kept) VALUES(?,?,?,?,18,?,0,?,?,0)',
                       (sid, tags[index], owners[index], names[index], 'lazy' if index == 1 else 'main',
                        '#R222222Y' if index == 0 else None, 'Fixture Family' if index == 0 else None))

requests = []

def counts():
    return [dict(row) for row in app['store'].rows('SELECT s.season_id,s.pool,COUNT(*) signups,SUM(r.assigned_clan_tag IS NOT NULL) assigned,SUM(r.kept) locks FROM signups s JOIN roster_entries r ON s.season_id=r.season_id AND s.tag=r.tag GROUP BY s.season_id,s.pool')]

baseline = counts()

@web.middleware
async def log_requests(request, handler):
    if request.path.startswith('/api/'):
        requests.append({'method': request.method, 'path': request.path_qs})
    return await handler(request)

app.middlewares.insert(0, log_requests)

async def state(request):
    return web.json_response({'baseline': baseline, 'current': counts(), 'requests': requests,
                              'database': folder.name + '/sample.sqlite'})

async def member(request):
    number = request.query.get('member', '1')
    if number not in ('1', '2', '3'):
        raise web.HTTPBadRequest()
    app['dev_identity'] = {**identity, 'id': '10000000000000000' + number}
    return web.Response(text='Member selected. Sign out and Open local test session to use this identity.')

async def scenario(request):
    sid = int(request.query.get('season', '1'))
    if sid not in range(1, 7):
        raise web.HTTPBadRequest()
    with app['store'].tx() as db:
        db.execute('UPDATE member_season SET season_id=? WHERE id=1', (sid,))
    return web.Response(text='Isolated scenario selected. Reload the dashboard.')

app.router.add_get('/qa/state', state)
app.router.add_get('/qa/member', member)
app.router.add_get('/qa/scenario', scenario)

if __name__ == '__main__':
    web.run_app(app, host='127.0.0.1', port=PORT)
