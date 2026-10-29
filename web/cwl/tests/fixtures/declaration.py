"""Read-only Declaration review: temp SQLite, fake providers, loopback network guard."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import player_cards as fixture
from aiohttp import web
from datetime import datetime, timezone, timedelta
import json, asyncio

# All SQL here seeds the isolated TemporaryDirectory, never a production database.
with fixture.app['store'].tx() as db:
    db.execute("UPDATE seasons SET label='Published v1' WHERE id=1")
    db.execute("UPDATE seasons SET label='Never published' WHERE id=2")
    db.execute("INSERT INTO seasons(id,label,status,signup_open) VALUES(3,'Hidden v1','draft',0),(4,'Draft changed','draft',0)")
    db.execute("UPDATE lineup_rules SET capacity=NULL WHERE tag=?", (fixture.clans[4],))
    db.execute("UPDATE lineup_rules SET capacity=30 WHERE tag=?", (fixture.clans[6],))
    db.execute("UPDATE signups SET user_id='' WHERE tag=?", (fixture.players[17],))
    db.execute("UPDATE roster_entries SET assigned_clan_tag=NULL WHERE tag=?", (fixture.players[90],))
    for sid in (3,4):
        for table in ('signups','roster_entries','lineup','lineup_rules'):
            columns=[r['name'] for r in db.execute(f'PRAGMA table_info({table})')]
            selection=','.join(str(sid) if c=='season_id' else c for c in columns)
            db.execute(f"INSERT INTO {table} ({','.join(columns)}) SELECT {selection} FROM {table} WHERE season_id=1")

@web.middleware
async def locations(request, handler):
    response=await handler(request)
    if request.path.endswith('/arrival-check') and response.status==200:
        result=json.loads(response.text)
        for a in result['accounts']:
            i=fixture.players.index(a['tag']) if a['tag'] in fixture.players else 0
            clan=a['assigned_clan_tag']; current=clan
            # First clan: 15 fresh arrivals + one late player. Other clans cover all cases.
            if i==0 or (i>=16 and i%6==0):current=fixture.clans[1] if clan!=fixture.clans[1] else fixture.clans[2]
            if i>=16 and i%6==1:current='#Y9Y9Y9Y'
            if i>=16 and i%6==2:current=None
            checked=(datetime.now(timezone.utc)-timedelta(minutes=12 if i>=16 and i%6==3 else 1)).isoformat()
            if i>=16 and i%6==4:checked=None
            name=fixture.names[fixture.clans.index(current)] if current in fixture.clans else 'Outside Family' if current else None
            a.update(current_clan_tag=current,current_clan_name=name,current_clan_checked_at=checked,current_clan_status='current' if checked else 'unavailable',outside_family=current not in fixture.clans,location_updating=False)
        result['updating']=False
        response=web.json_response(result)
    return response
fixture.app.middlewares.insert(0,locations)

async def main():
    runner=web.AppRunner(fixture.app);await runner.setup();await web.TCPSite(runner,'127.0.0.1',fixture.PORT).start()
    async with fixture.ClientSession(cookie_jar=fixture.CookieJar(unsafe=True)) as session:
        base=f'http://127.0.0.1:{fixture.PORT}/api/cwl'
        await session.post(base+'/dev/login');me=await(await session.get(base+'/auth/me')).json()
        for sid in (1,3,4):
            draft=await(await session.get(base+f'/seasons/{sid}/publication')).json()
            response=await session.post(base+f'/seasons/{sid}/publication',headers={'X-CSRF-Token':me['csrf_token']},json={'revision':draft['draft_revision'],'acknowledge_unassigned':True,'joining_instructions':'Fixture only'})
            assert response.status==201,await response.text()
        draft=await(await session.get(base+'/seasons/3/publication')).json()
        response=await session.post(base+'/seasons/3/publication/withdraw',headers={'X-CSRF-Token':me['csrf_token']},json={'revision':draft['draft_revision'],'version':1});assert response.status==200
    with fixture.app['store'].tx() as db:
        db.execute('DELETE FROM roster_entries WHERE season_id=4 AND tag=?',(fixture.players[17],))
        db.execute('DELETE FROM signups WHERE season_id=4 AND tag=?',(fixture.players[17],))
        db.execute('UPDATE roster_entries SET assigned_clan_tag=? WHERE season_id=4 AND tag=?',(fixture.clans[1],fixture.players[0]))
    fixture.baseline=fixture.state();fixture.requests.clear()
    print(json.dumps({'ready':True,'counts':fixture.baseline}),flush=True)
    await asyncio.Event().wait()
asyncio.run(main())
