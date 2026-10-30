"""Disposable seven-clan layout fixture with fake providers and blocked egress."""
import sys, tempfile, asyncio, json, time
from pathlib import Path
from datetime import datetime, timezone
import os
sys.path[:0] = [os.environ['WU_FIXTURE_BACKEND'], str(Path(__file__).resolve().parent)]
import qa_network_guard
from aiohttp import web
from cwl_web import create_app
from cwl_web.clan_weights import observations
from cwl_web.providers import ProviderUnavailable
PORT = int(sys.argv[2])
assert PORT == 0 or 8900 <= PORT <= 8999
folder = tempfile.TemporaryDirectory(prefix='wu-weight21-fixture-', dir=os.environ['HOME'])
app = create_app(db_path=folder.name + '/fixture.sqlite', dev_fixture=True, secure_cookies=False, static_dir=Path(sys.argv[1]))
p = app['providers']
ledger = app['clan_weight_trial']
requests = []
calls = []
mode = {'fail': False, 'deny': False}
rosters = {}
players = {}
clans = [{'tag': t, 'name': n, 'type': 'FWA'} for t, n in zip(['#R2Y', '#P2Y', '#Q2Y', '#G2Y', '#L2Y', '#C2Y', '#J2Y'], ['Aurora Warriors with a very long clan name', 'Birch Keep', 'Cedar Watch', 'Dawn Flight', 'Ember Knights', 'Forest Haven', 'Golden Guard'])]

def tag(n):
    return '#P' + ''.join(('0289PYLQGR'[int(x)] for x in str(n).zfill(5))) + 'Y'
for ci, c in enumerate(clans):
    rows = []
    for i in range(50):
        t = tag(ci * 50 + i)
        name = 'Alexandria extraordinarily long warrior name' if i == 0 else f'Warrior {ci + 1}-{i + 1:02}'
        rows.append({'tag': t, 'name': name, 'town_hall': 18, 'clan_position': i + 1})
        players[t] = {**rows[-1], 'current_clan_tag': c['tag'], 'current_clan_name': c['name']}
    rosters[c['tag']] = {**c, 'members': rows}
    changes = [{'tag': r['tag'], 'weight': 180000 if ci == 0 and i == 43 else 179000 - i * 1000, 'storages': 5, 'revision': 0} for i, r in enumerate(rows) if not (ci == 0 and i in (37, 49))]
    ledger.save(rosters[c['tag']], changes, 'fixture', 'Fixture staff')
departed = '#V2Y'
ledger.save({'tag': '#R2Y', 'name': clans[0]['name'], 'members': [{'tag': departed, 'name': 'Departed Änne', 'town_hall': 18}]}, [{'tag': departed, 'weight': 150000, 'storages': 5, 'revision': 0}], 'fixture', 'Fixture staff')
players[departed] = {'tag': departed, 'name': 'Departed Änne', 'town_hall': 18, 'current_clan_tag': '#U2Y', 'current_clan_name': 'Independent Clan'}

async def family():
    calls.append('family')
    return {'clans': clans, 'status': 'ok'}

async def roster(t):
    calls.append('roster:' + t)
    if mode['fail']:
        raise ProviderUnavailable('Fixture roster temporarily unavailable')
    return rosters[t]

async def player(t):
    calls.append('player:' + t)
    if t not in players:
        raise ProviderUnavailable('Fixture player unavailable')
    return players[t]

async def clan(t):
    return {'tag': t, 'name': next((c['name'] for c in clans if c['tag'] == t), 'Independent Clan'), 'cwl_league': 'Master League II'}

async def lineup(t):
    rows = rosters[t]['members']
    order = {r['tag']: i + 1 for i, r in enumerate(rows[:49]) if i != 47}
    order[departed] = 48
    return {'order': order, 'names': {departed: 'Departed Änne'}, 'state': 'inWar', 'end_time': '20261102T070000.000Z', 'opponent': 'Fixture Opponent'}
p.family_clans = family
p.clan_roster = roster
p.player = player
p.clan = clan
p.weight_war_lineup = lineup
with app['store'].tx() as db:
    for t, n in [(rosters['#R2Y']['members'][37]['tag'], 'Missing FWA'), ('#Y2Y', 'Outside Signup'), (departed, 'Departed Änne')]:
        db.execute("INSERT OR IGNORE INTO signups(season_id,tag,user_id,player_name,town_hall,pool,prefer_crystal_1_or_lower) VALUES(1,?,'505227988229554179',?,18,'main',0)", (t, n))
        db.execute('INSERT OR IGNORE INTO roster_entries(season_id,tag) VALUES(1,?)', (t,))
players['#Y2Y'] = {'tag': '#Y2Y', 'name': 'Outside Signup', 'town_hall': 18, 'current_clan_tag': '#U2Y', 'current_clan_name': 'Independent Clan'}

def state():
    return {'weights': ledger.all(), 'history': app['store'].rows('SELECT * FROM clan_player_weight_history ORDER BY id'), 'signups': app['store'].rows('SELECT * FROM signups ORDER BY tag')}
baseline = state()

@web.middleware
async def qa(req, handler):
    if req.path.startswith('/api/'):
        requests.append({'method': req.method, 'path': req.path_qs})
        if mode['deny'] and '/weight-trial/' in req.path:
            return web.json_response({'error': 'Fixture access revoked'}, status=403)
    return await handler(req)
app.middlewares.insert(0, qa)

async def qa_state(req):
    return web.json_response({'baseline': baseline, 'current': state(), 'requests': requests, 'provider_calls': calls, 'db': folder.name + '/fixture.sqlite'})

async def qa_mode(req):
    mode.update(await req.json())
    return web.json_response(mode)
app.router.add_get('/qa/state', qa_state)
app.router.add_post('/qa/mode', qa_mode)

async def main():
    for c in clans:
        await observations(app).refresh_roster(c['tag'])
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', PORT)
    await site.start()
    print(json.dumps({'ready': True, 'port': runner.addresses[0][1], 'db': folder.name + '/fixture.sqlite', 'rows': len(baseline['weights'])}), flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
