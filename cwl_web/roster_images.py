"""Published roster PNG previews and explicitly requested, ping-free test posts."""
import asyncio
import json
import math
import re
from utils.cwl_roster_order import ordered_roster_clans
from utils.cwl_roster_messages import clan_image_message
from aiohttp import web, FormData
from .server_management import discord, GUILD_ID, DiscordDeliveryUncertain

def snapshot(request, version=None, clan_tag=None):
    from .app import _require, _sid, _store, _season
    _require(request,'editor')
    sid=_sid(request)
    with _store(request).tx() as db:
        season=dict(_season(db,sid))
        pub=db.execute('SELECT * FROM roster_publications WHERE season_id=? AND withdrawn_at IS NULL ORDER BY version DESC LIMIT 1',(sid,)).fetchone()
        if not pub: raise web.HTTPConflict(text='Finalize a roster first.')
        if version is not None and str(pub['version'])!=str(version):raise web.HTTPConflict(text='A newer roster is published. Refresh the preview.')
        rows=[dict(r) for r in db.execute('SELECT * FROM publication_accounts WHERE publication_id=? ORDER BY town_hall DESC,player_name,tag',(pub['id'],))]
        clans={c['tag']:c for c in json.loads(pub['clans_json'])}
    groups={}
    for row in rows:
        if not row['assigned_clan_tag']:continue
        key=row['assigned_clan_tag']
        group=groups.setdefault(key,{'tag':key,'name':row['assigned_clan_name'] or key,'pool':clans.get(key,{}).get('pool') or row['pool'],'capacity':clans.get(key,{}).get('capacity'),'league':clans.get(key,{}).get('cwl_league') or 'League unavailable','accounts':[]})
        group['accounts'].append(row)
    if clan_tag is not None:
        if clan_tag not in groups:raise web.HTTPNotFound(text='This clan has no players in the finalized roster.')
        return season,dict(pub),groups[clan_tag]
    return season,dict(pub),groups

def render(season, pub, group, page):
    from utils.cwl_roster_render import render as render_png
    try:
        return render_png(season, pub, group, page)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None

async def listing(request):
    season,pub,groups=snapshot(request)
    return web.json_response({'version':pub['version'],'season':season['label'],'clans':[{k:v for k,v in g.items() if k!='accounts'}|{'count':len(g['accounts']),'pages':math.ceil(len(g['accounts'])/15)} for g in ordered_roster_clans(groups.values())]})

async def metadata(request,group):
    from .clan_metadata import enrich
    await enrich(request,[group])
    group["league"]=group.get("cwl_league") or group["league"]

async def image(request):
    season,pub,group=snapshot(request,request.query.get('version'),request.match_info['tag'])
    try:page=int(request.query.get('page','1'))
    except ValueError:raise web.HTTPBadRequest(text='Unknown image page.') from None
    await metadata(request,group)
    data=await asyncio.to_thread(render,season,pub,group,page)
    return web.Response(body=data,content_type='image/png',headers={'Cache-Control':'private, no-store','Content-Disposition':f'inline; filename="roster-{group["tag"][1:]}-v{pub["version"]}-{page}.png"'})

async def send_test(request):
    from .app import _json,_sid,_store
    from .roster_image_posts import staff
    actor=staff(request, send=True);body=await _json(request);sid=_sid(request)
    if set(body)!={'version','channel_id','request_id'}:raise web.HTTPBadRequest(text='Choose a test channel.')
    channel=body['channel_id'];nonce=body['request_id']
    if not isinstance(channel,str) or not re.fullmatch(r'\d{15,22}',channel) or not isinstance(nonce,str) or not re.fullmatch(r'[a-f0-9]{24}',nonce):raise web.HTTPBadRequest(text='Choose a test channel.')
    season,pub,group=snapshot(request,body['version'],request.match_info['tag'])
    destination=await discord(request,'GET',f'/channels/{channel}')
    if str(destination.get('guild_id'))!=str(GUILD_ID) or destination.get('type') not in (0,5):raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    await metadata(request,group)
    pages=math.ceil(len(group['accounts'])/15)
    if pages>10:raise web.HTTPBadRequest(text='This roster is too large to send.')
    images=await asyncio.gather(*(asyncio.to_thread(render,season,pub,group,p) for p in range(1,pages+1)))
    key=f'roster-image:{actor["user_id"]}:{nonce}'
    with _store(request).tx() as db:
        old=db.execute('SELECT url FROM roster_test_messages WHERE id=?',(key,)).fetchone()
        if old:
            if old['url']:return web.json_response({'url':old['url']})
            raise web.HTTPConflict(text='Test delivery is unconfirmed. Check Discord before sending again.')
        db.execute('INSERT INTO roster_test_messages(id,season_id,pool,channel_id,actor_id) VALUES (?,?,?,?,?)',(key,sid,group['pool'],channel,actor['user_id']))
    form=FormData()
    payload = {**clan_image_message(group['name'], group['tag'], test=True),
               'nonce': nonce, 'enforce_nonce': True,
               'attachments': [{'id': i, 'filename': f'roster-{group["tag"][1:]}-{i+1}.png'}
                               for i in range(len(images))]}
    form.add_field('payload_json',json.dumps(payload))
    for i,data in enumerate(images):form.add_field(f'files[{i}]',data,filename=f'roster-{group["tag"][1:]}-{i+1}.png',content_type='image/png')
    try:
        message=await discord(request,'POST',f'/channels/{channel}/messages',data=form,roster_delivery=True)
    except DiscordDeliveryUncertain:
        raise web.HTTPServiceUnavailable(text='Test delivery is unconfirmed. Check Discord before sending again.') from None
    url=f'https://discord.com/channels/{GUILD_ID}/{channel}/{message["id"]}'
    with _store(request).tx() as db:db.execute('UPDATE roster_test_messages SET url=? WHERE id=?',(url,key))
    return web.json_response({'url':url})

def routes():
    prefix='/api/cwl/seasons/{season_id}/roster-images'
    return [web.get(prefix,listing),web.get(prefix+'/{tag}.png',image),web.post(prefix+'/{tag}/test',send_test)]
