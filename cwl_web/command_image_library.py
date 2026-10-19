"""Reusable artwork catalog; stored beside command settings, with live usage."""
import hashlib
from datetime import datetime, timezone
from urllib.parse import urlsplit, unquote
from pymongo.write_concern import WriteConcern
from aiohttp import web
from utils.text_commands import GUILD_ID, collection as commands, walk_blocks, legacy_blocks, public_url
from .server_management import mongo, require_manage, API


def collection(db):
    return db.bot_config.database.get_collection('text_command_images',write_concern=WriteConcern(w='majority',wtimeout=10000))


def image_slots(row):
    for _, block in walk_blocks(row.get('blocks',legacy_blocks(row))):
        if block['type']=='image':yield block
        elif block['type']=='gallery':
            for item in block['items']:
                if not urlsplit(item['url']).path.lower().endswith(('.mp4','.webm','.mov','.m4v')):yield item
        elif block['type']=='section' and block['accessory']['type']=='thumbnail':yield block['accessory']


def image_name(url,name=''):
    return (name.strip() or unquote(urlsplit(url).path.rsplit('/',1)[-1]) or 'Image')[:120]


async def remember(request,url,name='',actor=None,category=None):
    key=hashlib.sha256(f'{GUILD_ID}:{url}'.encode()).hexdigest()
    async with mongo(request) as db:
        await collection(db).update_one({'_id':key},{'$setOnInsert':{
            'guild_id':GUILD_ID,'url':url,'name':image_name(url,name),
            **({'folder':category} if category is not None else {}),
            'created_at':datetime.now(timezone.utc),'created_by':str((actor or {}).get('user_id',''))}},upsert=True)


def merge_images(saved,rows):
    images={item['url']:{'url':item['url'],'name':item['name'],'commands':[],'stored':item.get('stored',True),'archived':item.get('archived',False),'folder':item.get('folder','')} for item in saved}
    for row in rows:
        for slot in image_slots(row):
            url=slot['url']
            try:public_url(url,'image')
            except ValueError:continue
            item=images.setdefault(url,{'url':url,'name':image_name(url,slot.get('description','')),'commands':[],'stored':False,'archived':False,'folder':''})
            if row['command'] not in item['commands']:item['commands'].append(row['command'])
    for item in images.values():item['commands'].sort()
    return sorted(images.values(),key=lambda item:(item['name'].casefold(),item['url']))


async def listing(request):
    await require_manage(request,'text_commands')
    async with mongo(request) as db:
        saved=await collection(db).find({'guild_id':GUILD_ID}).to_list(length=None)
        rows=await commands(db).find({'guild_id':GUILD_ID}).to_list(length=None)
    return web.json_response({'images':merge_images(saved,rows)})

async def update(request):
    actor=await require_manage(request,'text_commands',write=True)
    body=await request.json()
    if not isinstance(body,dict):raise web.HTTPBadRequest(text='Choose an image.')
    url=body.get('url');name=body.get('name');archived=body.get('archived');folder=body.get('folder')
    if folder is not None and (not isinstance(folder,str) or len(folder)>120 or any(ord(c)<32 for c in folder)):raise web.HTTPBadRequest(text='Use a folder name up to 120 characters.')
    if not isinstance(name,str) or not 1<=len(name.strip())<=120 or not isinstance(archived,bool):raise web.HTTPBadRequest(text='Enter an image name up to 120 characters.')
    async with mongo(request) as db:
        saved=await collection(db).find({'guild_id':GUILD_ID}).to_list(length=None)
        rows=await commands(db).find({'guild_id':GUILD_ID}).to_list(length=None)
        item=next((item for item in merge_images(saved,rows) if item['url']==url),None)
        if item is None:raise web.HTTPNotFound(text='Image not found. Reopen the library.')
        key=hashlib.sha256(f'{GUILD_ID}:{url}'.encode()).hexdigest()
        await collection(db).update_one({'_id':key},{'$set':{'guild_id':GUILD_ID,'url':url,'name':name.strip(),'archived':archived,'folder':folder.strip() if folder is not None else item.get('folder',''),'stored':item['stored'],'updated_by':str(actor['user_id']),'updated_at':datetime.now(timezone.utc)}},upsert=True)
    return web.json_response({**item,'name':name.strip(),'archived':archived,'folder':folder.strip() if folder is not None else item.get('folder','')})

routes=[web.get(API+'/text-command-images',listing),web.patch(API+'/text-command-images',update)]


async def sync_r2(request):
    """Index one page of the public artwork bucket. Never rename/move/delete objects."""
    import asyncio
    from pymongo import UpdateOne
    from .command_images import store
    await require_manage(request,'text_commands',write=True)
    body=await request.json()
    cursor=body.get('cursor') if isinstance(body,dict) else None
    if cursor is not None and (not isinstance(cursor,str) or not 1<=len(cursor)<=4096):raise web.HTTPBadRequest(text='Refresh the gallery again.')
    media=store(request)
    try:
        config=media._require_config()
        page=await asyncio.to_thread(media._s3().list_objects_v2,Bucket=config.bucket,MaxKeys=1000,**({'ContinuationToken':cursor} if cursor else {}))
    except Exception as exc:
        raise web.HTTPServiceUnavailable(text='Could not read the R2 image list. Saved images are still available.') from exc
    updates=[]
    for obj in page.get('Contents',[]):
        key=obj['Key']
        if not key.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp','.svg','.avif','.ico')):continue
        url=media.public_url(key)
        updates.append(UpdateOne({'_id':hashlib.sha256(f'{GUILD_ID}:{url}'.encode()).hexdigest()},{'$setOnInsert':{
            'guild_id':GUILD_ID,'url':url,'name':image_name(url),'folder':key.rpartition('/')[0][:120],
            'stored':True,'created_at':datetime.now(timezone.utc)}},upsert=True))
    if updates:
        async with mongo(request) as db:await collection(db).bulk_write(updates,ordered=False)
    return web.json_response({'indexed':len(updates),'cursor':page.get('NextContinuationToken') if page.get('IsTruncated') else None})

routes.append(web.post(API+'/text-command-images/sync',sync_r2))
