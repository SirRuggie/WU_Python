"""Published roster PNG previews and explicitly requested, ping-free test posts."""
import asyncio
import io
import json
import math
import re
import unicodedata
from urllib.parse import quote
from aiohttp import web, FormData
from PIL import Image, ImageDraw, ImageFont, ImageOps
from pathlib import Path
from functools import lru_cache
from .server_management import discord, GUILD_ID

FONT='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
BOLD='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'

@lru_cache(maxsize=1)
def background_art():
    # Local copy of the catalogued R2 original avoids a network dependency per render.
    with Image.open(Path(__file__).parent / 'assets' / 'roster-background.jpg') as image:
        return ImageOps.exif_transpose(image).convert('RGB')

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
        group=groups.setdefault(key,{'tag':key,'name':row['assigned_clan_name'] or key,'pool':clans.get(key,{}).get('pool') or row['pool'],'league':clans.get(key,{}).get('cwl_league') or 'League unavailable','accounts':[]})
        group['accounts'].append(row)
    if clan_tag is not None:
        if clan_tag not in groups:raise web.HTTPNotFound(text='This clan has no players in the finalized roster.')
        return season,dict(pub),groups[clan_tag]
    return season,dict(pub),groups

def render(season,pub,group,page):
    pages=math.ceil(len(group['accounts'])/15)
    if page<1 or page>pages:raise web.HTTPBadRequest(text='Unknown image page.')
    players=group['accounts'][(page-1)*15:page*15]
    width=1000;height=300+len(players)*70+90
    im=Image.new('RGB',(width,height),'#111214')
    # Keep the whole artwork visible even when a short roster makes a wide card.
    art=ImageOps.pad(background_art(),(width,height),method=Image.Resampling.LANCZOS,color='#111214')
    im=Image.blend(im,art,0.28)
    d=ImageDraw.Draw(im,'RGBA')
    gold='#f4cd64';white='#f5f4f0';muted='#bfc2c8'
    def text(x,y,value,size,color=white,maxwidth=900,bold=False):
        value=unicodedata.normalize('NFKC',str(value)).replace('\n',' ')
        font=ImageFont.truetype(BOLD if bold else FONT,size)
        while d.textlength(value,font=font)>maxwidth and size>12:
            size-=1;font=ImageFont.truetype(BOLD if bold else FONT,size)
        while d.textlength(value,font=font)>maxwidth and len(value)>1:value=value[:-2]+'…'
        d.text((x,y),value,font=font,fill=color)
    d.rectangle((0,0,width,10),fill=gold)
    text(42,32,'WARRIORS UNITED',38,gold,bold=True)
    text(42,90,f"{season['label']} · {'Main' if group['pool']=='main' else 'Lazy'} CWL",25,muted)
    text(42,140,group['name'],38,bold=True)
    text(42,196,f"{group['tag']} · {group['league']}",24,muted)
    text(42,240,f"FINAL ROSTER · VERSION {pub['version']}",18,gold)
    for i,a in enumerate(players):
        y=290+i*70
        d.rounded_rectangle((32,y,968,y+60),radius=10,fill=(28,29,33,150) if i%2==0 else (17,18,21,150),outline='#4a4431')
        text(48,y+16,str((page-1)*15+i+1),20,gold,maxwidth=45,bold=True)
        text(104,y+14,a['player_name'],25,maxwidth=440,bold=True)
        text(560,y+18,a['tag'],20,muted,maxwidth=250)
        text(855,y+16,f"TH {a['town_hall']}",21,gold,maxwidth=100,bold=True)
    text(42,height-66,f"{len(group['accounts'])} players · Page {page}/{pages}",22,gold)
    d.rectangle((0,height-10,width,height),fill=gold)
    buf=io.BytesIO();im.save(buf,format='PNG');return buf.getvalue()

async def listing(request):
    season,pub,groups=snapshot(request)
    return web.json_response({'version':pub['version'],'season':season['label'],'clans':[{k:v for k,v in g.items() if k!='accounts'}|{'count':len(g['accounts']),'pages':math.ceil(len(g['accounts'])/15)} for g in groups.values()]})

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
    from .app import _require,_json,_sid,_store,_audit
    actor=_require(request,'editor');body=await _json(request);sid=_sid(request)
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
        _audit(db,sid,group['tag'],actor['user_id'],'roster_image_test',None,{'channel_id':channel,'version':pub['version']})
    form=FormData()
    payload={'content':f'TEST · {group["name"]} · {season["label"]} · Roster v{pub["version"]}', 'allowed_mentions':{'parse':[]},'nonce':nonce,'enforce_nonce':True,'components':[{'type':1,'components':[{'type':2,'style':5,'label':'Open clan','url':f'https://link.clashofclans.com/en?action=OpenClanProfile&tag={quote(group["tag"],safe="")}'}]}]}
    form.add_field('payload_json',json.dumps(payload))
    for i,data in enumerate(images):form.add_field(f'files[{i}]',data,filename=f'roster-{group["tag"][1:]}-{i+1}.png',content_type='image/png')
    message=await discord(request,'POST',f'/channels/{channel}/messages',data=form)
    url=f'https://discord.com/channels/{GUILD_ID}/{channel}/{message["id"]}'
    with _store(request).tx() as db:db.execute('UPDATE roster_test_messages SET url=? WHERE id=?',(url,key))
    return web.json_response({'url':url})

def routes():
    prefix='/api/cwl/seasons/{season_id}/roster-images'
    return [web.get(prefix,listing),web.get(prefix+'/{tag}.png',image),web.post(prefix+'/{tag}/test',send_test)]
