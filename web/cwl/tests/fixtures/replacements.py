"""273-account loopback fixture: fake ledger/providers/Discord, no external writes."""
import sys, os, tempfile, json, hashlib, asyncio
from pathlib import Path
from datetime import datetime, timedelta, timezone
ROOT = Path(os.environ['WU_FIXTURE_BACKEND'])
sys.path[:0] = [str(ROOT), str(ROOT / 'tests'), str(Path(__file__).parent)]
import qa_network_guard
from aiohttp import web
from cwl_web import create_app
from cwl_web.strikes import GUILD_ID
from test_strike_ux_backend import setup, record, Collection
PORT = int(sys.argv[2])
assert PORT == 0 or 8900 <= PORT <= 8999
folder = tempfile.TemporaryDirectory(prefix='wu-replacements-', dir=os.environ['HOME'])
app = create_app(db_path=folder.name+'/fixture.sqlite', dev_fixture=True, secure_cookies=False, static_dir=Path(sys.argv[1]))
db, ledger = setup()
for name in ('members','bot_config','member_events','ticket_setup'):
    setattr(db,name,Collection())
app['server_management_mongo'] = db
app['strike_service'] = ledger
alphabet = '0289PYLQGRJCUV'
def tag(n):
    return '#P'+alphabet[n//169 % 13]+alphabet[n//13 % 13]+alphabet[n % 13]+'Y'
clans = [{'tag':tag(i+1000),'name':f'Fixture clan {i+1:02}', 'type':'FWA' if i<10 else 'CWL Hosting'} for i in range(12)]
players = {tag(i):{'tag':tag(i),'name':f'Sample player {i+1:03}','town_hall':15+i%4,'current_clan_tag':clans[i%12]['tag'],'current_clan_name':clans[i%12]['name']} for i in range(273)}
async def family(): return {'clans':clans,'status':'ok','source':'fixture','checked_at':datetime.now(timezone.utc).isoformat()}
async def player(value): return players[value].copy()
async def clan(value): return {**next(c for c in clans if c['tag']==value), 'members':[p.copy() for p in players.values() if p['current_clan_tag']==value]}
async def weights(tags): return {t:{'weight':140000+list(players).index(t)%40*1000,'source_name':'Fixture'} for t in tags if t in players}
async def discord(method,path,**kwargs):
    assert method == 'GET', 'Fixture forbids Discord writes'
    if path.endswith('/roles'): return []
    if path.endswith('/members'): return []
    return {'user':{'id':path.rsplit('/',1)[-1],'username':'Fixture staff'},'roles':[]}
app['providers'].family_clans=family
app['providers'].player=player
app['providers'].clan=clan
app['providers'].weights=weights
app['server_management_discord']=discord
baseline={}
async def seed(app):
    now=datetime.now(timezone.utc)
    for c in clans: await db.clans.insert_one({'_id':c['tag'],**c})
    for i,p in enumerate(players.values()):
        await db.strike_profiles.insert_one({'_id':f"{GUILD_ID}:{p['tag']}",'guild_id':GUILD_ID,'player_tag':p['tag'],'player_name':p['name'],'current_clan_tag':p['current_clan_tag'],'roster_seen_at':now,'weight':140000+i%40*1000,'town_hall':p['town_hall'],'revision':2,**({'replacement_listed':True,'replacement_clan_tag':p['current_clan_tag'],'replacement_priority':'replace_first' if i%4==0 else 'high','replacement_note':'Fixture priority'} if i%11==0 else {})})
        for j in range(i%5+1):
            await db.strike_records.insert_one(record(f'{i}-{j}',p['tag'],guild_id=GUILD_ID,player_name=p['name'],clan_tag=p['current_clan_tag'],expires_at=now+timedelta(days=30)))
    baseline.update(state())
def state():
    return {'profiles':len(db.strike_profiles.rows),'strikes':len(db.strike_records.rows),'clans':len(db.clans.rows),'strike_hash':hashlib.sha256(json.dumps(db.strike_records.rows,sort_keys=True,default=str).encode()).hexdigest()}
async def qa_state(request): return web.json_response({'baseline':baseline,'current':state()})
app.on_startup.append(seed)
app.router.add_get('/qa/state',qa_state)
async def main():
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '127.0.0.1', PORT)
    await site.start()
    print(json.dumps({'ready': True, 'port': runner.addresses[0][1]}), flush=True)
    await asyncio.Event().wait()
if __name__ == '__main__':
    asyncio.run(main())
