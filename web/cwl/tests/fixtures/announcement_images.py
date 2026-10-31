"""Announcement/image sequence review with isolated SQLite, Mongo and fake Discord."""
import asyncio
import html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import player_cards as fixture
sys.path.insert(0, str(fixture.ROOT / 'tests') if hasattr(fixture, 'ROOT') else str(Path(__file__).resolve().parents[4] / 'tests'))
from aiohttp import web
from test_cwl_dashboard_integration import MemoryMongo
from cwl_web.manage_bridge import GUILD_ID
from cwl_web.roster_sequence_jobs import SequenceJobs
from utils import cwl_campaign, cwl_web_bridge

app = fixture.app
mongo = MemoryMongo()
app['manage_bridge_mongo'] = mongo
channels = [{'id': '111111111111111111', 'name': 'main-cwl', 'type': 0},
            {'id': '222222222222222222', 'name': 'lazy-cwl', 'type': 0},
            {'id': '333333333333333333', 'name': 'staff-tests', 'type': 0}]
posts, pictures = [], {}

class Options:
    async def list_channels(self): return channels
    async def list_roles(self): return [{'id': '444444444444444444', 'name': 'CWL players'}]
app['announcement_transport'] = Options()

async def discord(method, path, **kwargs):
    if method == 'GET':
        channel = next((item for item in channels if path == '/channels/' + item['id']), None)
        return {'guild_id': str(GUILD_ID), 'type': 0, 'roles': [], **(channel or {})}
    assert method in ('POST', 'PATCH')
    payload = kwargs.get('json')
    images = []
    if 'data' in kwargs:
        for header, _, value in kwargs['data']._fields:
            if header['name'] == 'payload_json': payload = json.loads(value)
            else: images.append(value)
    message = str(555555555555555550 + len(posts))
    for page, value in enumerate(images): pictures[f'{message}-{page}'] = value
    posts.append({'method': method, 'path': path, 'payload': payload, 'message_id': message, 'images': len(images)})
    return {'id': message}
app['server_management_discord'] = discord

async def state(request): return web.json_response({'posts': posts, 'counts': fixture.state()['counts']})
async def picture(request): return web.Response(body=pictures[request.match_info['key']], content_type='image/png')
def content(value):
    if isinstance(value, dict): return '\n'.join(part for part in [str(value.get('content', ''))] + [content(v) for k,v in value.items() if k != 'content'] if part)
    if isinstance(value, list): return '\n'.join(part for item in value if (part := content(item)))
    return ''
def buttons(value):
    if isinstance(value, dict):
        own = '<span class=button>'+html.escape(str(value['label']))+'</span>' if value.get('type') == 2 and value.get('label') else ''
        return own + ''.join(buttons(v) for v in value.values())
    if isinstance(value, list): return ''.join(buttons(item) for item in value)
    return ''

async def channel_view(request):
    channel = request.query.get('channel', channels[1]['id'])
    cards = []
    for item in posts:
        if channel not in item['path']: continue
        images = ''.join(f'<img src="/qa/files/{item["message_id"]}-{page}.png">' for page in range(item['images']))
        cards.append('<article><pre>'+html.escape(content(item['payload']))+'</pre>'+images+buttons(item['payload'])+'</article>')
    return web.Response(text='<meta name="viewport" content="width=device-width,initial-scale=1"><style>body{margin:12px;background:#18212d;color:#eee;font:16px sans-serif}article{padding:12px;margin:12px 0;border:1px solid #667;max-width:700px}.button{display:inline-block;padding:12px;border:1px solid #8799af;border-radius:8px;margin:8px 0}pre{white-space:pre-wrap;font:inherit}img{width:100%;height:auto}</style><h1>Isolated fake Discord channel</h1>'+''.join(cards),content_type='text/html')
app.router.add_get('/qa/sequence', state)
app.router.add_get('/qa/channel', channel_view)
app.router.add_get('/qa/files/{key}.png', picture)

async def main():
    names = ['Zulu 30', 'Alpha 30', 'Zulu 15', 'Alpha 15', 'W. U. Lazy.126', 'W. U. Lazy.128', 'W. U. Lazy.125', 'W. U. Lazy.127']
    fixture.names[:] = names
    with app['store'].tx() as db:
        for index, tag in enumerate(fixture.clans):
            pool = 'main' if index < 4 else 'lazy'
            db.execute('UPDATE clans SET name=? WHERE tag=?', (names[index], tag))
            db.execute('UPDATE lineup_rules SET pool=?,capacity=?,min_weight=NULL,max_weight=NULL WHERE tag=?', (pool,30 if index < 2 else 15,tag))
            db.execute('UPDATE signups SET pool=? WHERE tag IN (SELECT tag FROM roster_entries WHERE assigned_clan_tag=?)', (pool,tag))
        db.execute("INSERT INTO manage_campaign_bindings(season_id,cycle) VALUES(1,'2026-11')")
    draft = await cwl_campaign.new_draft(mongo, GUILD_ID, 1, '2026-11')
    campaign = draft['campaign']
    for pool, channel in zip(('main', 'lazy'), channels):
        campaign['messages']['roster']['variants'][pool].update(destination_channel_id=int(channel['id']), title='Your CWL roster', body='Your clan assignment is ready.', role_ids=[444444444444444444], media_url='', enabled=True,
            buttons=[{'label':'My assignments','url':'https://dash.warriorsunited.cc/assignments?season=1'}])
    await mongo.bot_config.update_one({'_id':cwl_campaign.cycle_id(GUILD_ID,'2026-11')},{'$set':{'campaign':campaign,'revision':1}},upsert=True)
    runner = web.AppRunner(app); await runner.setup()
    site = web.TCPSite(runner,'127.0.0.1',fixture.PORT)
    await site.start()
    fixture.PORT = runner.addresses[0][1]
    assert fixture.PORT != 8767
    async with fixture.ClientSession(cookie_jar=fixture.CookieJar(unsafe=True)) as session:
        base = f'http://127.0.0.1:{fixture.PORT}/api/cwl'
        await session.post(base+'/dev/login')
        me=await (await session.get(base+'/auth/me')).json()
        publication=await (await session.get(base+'/seasons/1/publication')).json()
        result=await session.post(base+'/seasons/1/publication',headers={'X-CSRF-Token':me['csrf_token']},json={'revision':publication['draft_revision'],'acknowledge_unassigned':True,'joining_instructions':'Fixture only'})
        assert result.status==201,await result.text()
    jobs=SequenceJobs(app);app['roster_sequence_jobs']=jobs
    async def sender(guild,cycle,message,pools,**kwargs):
        loaded=await cwl_campaign.load_campaign(mongo,guild,cycle)
        for pool in pools:
            item=loaded['campaign']['messages']['roster']['variants'][pool]
            components=await cwl_campaign.render_message(loaded,'roster',pool,preview=False)
            receipt=await discord('POST',f'/channels/{item["destination_channel_id"]}/messages',json={'components':[component.build()[0] for component in components],'allowed_mentions':{'roles':[str(role) for role in item['role_ids']]}})
            await cwl_campaign.record_delivery(mongo,guild,cycle,{'occurrence_id':cwl_campaign.occurrence_id(cycle,'roster',pool),'status':'sent','channel_id':item['destination_channel_id'],'message_id':receipt['id']})
        return True
    async def poll():
        while True:
            await cwl_web_bridge.process_pending_roster_requests(mongo,sender,guild_id=GUILD_ID)
            jobs.poll()
            await asyncio.sleep(.25)
    task=asyncio.create_task(poll())
    print(json.dumps({'ready':True,'port':fixture.PORT}),flush=True)
    try: await asyncio.Event().wait()
    finally: task.cancel(); await runner.cleanup()

if __name__=='__main__': asyncio.run(main())
