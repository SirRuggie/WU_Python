"""Permanent command artwork using the dashboard's existing R2 image store."""
from urllib.parse import urlsplit
from aiohttp import web
from utils.media_store import MediaStore,MediaStoreError
from utils.url_safety import MAX_IMAGE_BYTES
from utils.text_commands import GUILD_ID,walk_blocks,public_url
from .server_management import require_manage,API
from .command_image_library import remember, routes as library_routes

DISCORD_HOSTS={'cdn.discordapp.com','media.discordapp.net'}

def discord_image(url):
    try:
        parsed=urlsplit(url)
        return parsed.scheme=='https' and parsed.hostname in DISCORD_HOSTS and parsed.path.lower().endswith(('.png','.jpg','.jpeg','.gif','.webp'))
    except (ValueError,TypeError):return False

def store(request):return request.app.get('server_management_media') or MediaStore.from_env()
def folder():return f'content/command-triggers/{GUILD_ID}'

async def preserve_images(request,values):
    # Values have already passed schema validation. Never mutate caller-owned state.
    import copy
    result=copy.deepcopy(values);cache={};media=None
    for _,block in walk_blocks(result.get('blocks',[])):
        slots=[block] if block['type']=='image' else block['items'] if block['type']=='gallery' else [block['accessory']] if block['type']=='section' and block['accessory']['type']=='thumbnail' else []
        for slot in slots:
            url=slot['url']
            if not discord_image(url):continue
            if url not in cache:
                try:
                    if media is None:media=store(request)
                    cache[url]=await media.upload_from_url(url,folder=folder(),name='image')
                    await remember(request,cache[url],urlsplit(url).path.rsplit('/',1)[-1])
                except MediaStoreError as exc:raise web.HTTPBadRequest(text='Could not save the Discord image. Copy a fresh image link or upload the image file.') from exc
            slot['url']=cache[url]
    return result

def image_category(value):
    if value is None:return None
    if not isinstance(value,str) or len(value)>120 or any(ord(c)<32 for c in value):
        raise web.HTTPBadRequest(text='Use a category name up to 120 characters.')
    return value.strip()


async def upload(request):
    actor=await require_manage(request,'text_commands',write=True)
    if request.content_length is not None and request.content_length>MAX_IMAGE_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES,actual_size=request.content_length)
    category=image_category(request.query.get('category'))
    data=bytearray()
    async for chunk in request.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data)>MAX_IMAGE_BYTES:raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES,actual_size=len(data))
    try:url=await store(request).upload_bytes(bytes(data),folder=folder(),name='image')
    except MediaStoreError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    await remember(request,url,request.query.get('name',''),actor,**({'category':category} if category is not None else {}))
    return web.json_response({'url':url})

async def import_image(request):
    actor=await require_manage(request,'text_commands',write=True)
    body=await request.json()
    if not isinstance(body,dict):raise web.HTTPBadRequest(text='Paste a direct image link.')
    category=image_category(body.get('category'))
    try:source=public_url(body.get('url'),'image')
    except ValueError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    try:url=await store(request).upload_from_url(source,folder=folder(),name='image')
    except MediaStoreError as exc:raise web.HTTPBadRequest(text=str(exc)) from None
    await remember(request,url,urlsplit(source).path.rsplit('/',1)[-1],actor,**({'category':category} if category is not None else {}))
    return web.json_response({'url':url})

routes=[web.post(API+'/text-command-images/upload',upload),web.post(API+'/text-command-images/import',import_image)]

routes.extend(library_routes)
