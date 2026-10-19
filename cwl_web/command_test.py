"""Send an inert, mention-free draft preview without changing saved triggers."""
import json,re
from datetime import datetime,timezone
import aiohttp
from aiohttp import web
from pymongo.errors import DuplicateKeyError
from pymongo.write_concern import WriteConcern
from utils.text_commands import GUILD_ID,validate,payload
from utils.text_command_files import load_files
from .server_management import API,require_manage,discord,mongo

async def channels(request):
    await require_manage(request,'text_commands',write=True)
    rows=await discord(request,'GET',f'/guilds/{GUILD_ID}/channels')
    return web.json_response({'channels':[{'id':str(c['id']),'name':c['name'],'type':c['type']} for c in rows if c['type'] in (0,5)]})

def disable_actions(value):
    if isinstance(value,dict):
        if 'custom_id' in value:value['disabled']=True
        for child in value.values():disable_actions(child)
    elif isinstance(value,list):
        for child in value:disable_actions(child)

async def send(request):
    actor=await require_manage(request,'text_commands',write=True)
    body=await (request.clone(client_max_size=256*1024) if isinstance(request,web.Request) else request).json()
    if not isinstance(body,dict):raise web.HTTPBadRequest(text='Choose a channel and review the message.')
    channel=body.get('channel_id','');nonce=body.get('request_id','')
    if not isinstance(channel,str) or not re.fullmatch(r'\d{15,22}',channel):raise web.HTTPBadRequest(text='Choose a channel.')
    if not isinstance(nonce,str) or not re.fullmatch(r'[a-f0-9]{24}',nonce):raise web.HTTPBadRequest(text='Reopen the test controls.')
    try:values=validate(body.get('values'))
    except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    destination=await discord(request,'GET',f'/channels/{channel}')
    if str(destination.get('guild_id'))!=str(GUILD_ID) or destination.get('type') not in (0,5):raise web.HTTPBadRequest(text='Choose a text channel in this server.')
    async with mongo(request) as db:
        try:rendered=payload(values,await load_files(db,values))
        except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
        data={'components':[c.build()[0] for c in rendered['components']], 'flags':32768,'allowed_mentions':{'parse':[]},'nonce':nonce,'enforce_nonce':True}
        disable_actions(data['components'])
        form=aiohttp.FormData()
        attachments=rendered.get('attachments',[])
        if attachments:
            data['attachments']=[{'id':i,'filename':item.filename} for i,item in enumerate(attachments)]
            for i,item in enumerate(attachments):form.add_field(f'files[{i}]',await item.read(),filename=item.filename,content_type='application/octet-stream')
            form.add_field('payload_json',json.dumps(data),content_type='application/json')
        audit=db.bot_config.database.get_collection('text_command_tests',write_concern=WriteConcern(w='majority',wtimeout=10000))
        key=f'{GUILD_ID}:{actor["user_id"]}:{nonce}'
        try:await audit.insert_one({'_id':key,'guild_id':GUILD_ID,'user_id':actor['user_id'],'command':values['command'],'channel_id':channel,'at':datetime.now(timezone.utc),'status':'sending'})
        except DuplicateKeyError:
            existing=await audit.find_one({'_id':key})
            if existing.get('url'):return web.json_response({'url':existing['url']})
            raise web.HTTPConflict(text='This test was already requested. Check the channel before sending another.') from None
        try:message=await discord(request,'POST',f'/channels/{channel}/messages',**({'data':form} if attachments else {'json':data}))
        except Exception:
            await audit.update_one({'_id':key},{'$set':{'status':'unconfirmed'}})
            raise
        url=f'https://discord.com/channels/{GUILD_ID}/{channel}/{message["id"]}'
        await audit.update_one({'_id':key},{'$set':{'status':'sent','url':url}})
    return web.json_response({'url':url})

routes=[web.get(API+'/text-command-test-channels',channels),web.post(API+'/text-command-test',send)]
