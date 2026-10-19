"""Shared Discord/web clan artwork and thread operations."""
import asyncio,re
from io import BytesIO
from datetime import timedelta
from PIL import Image
import hikari
from utils.image_fetch import fetch_public_image

async def replace_emoji(bot,mongo,row,url):
    def prepare():
        data=fetch_public_image(url)
        with Image.open(BytesIO(data)) as source:
            if source.width*source.height>40_000_000:raise ValueError('Image is too large.')
            image=source.convert('RGBA');image.thumbnail((128,128))
            out=BytesIO();image.save(out,format='PNG',optimize=True)
            if out.tell()>256*1024:raise ValueError('Emoji must be smaller than 256 KB.')
            return out.getvalue()
    data=await asyncio.to_thread(prepare)
    application=await bot.rest.fetch_application()
    name=(re.sub(r'[^a-zA-Z0-9_]','',row['name']) or 'clan')[:32]
    if len(name)<2:name='clan_'+name
    emoji=await bot.rest.create_application_emoji(application=application.id,name=name,image=hikari.Bytes(data,'emoji.png'))
    result=await mongo.clans.update_one({'_id':row['_id'],'emoji':row.get('emoji') if 'emoji' in row else {'$exists':False}},{'$set':{'emoji':emoji.mention}})
    if not result.matched_count:
        await bot.rest.delete_application_emoji(application=application.id,emoji=emoji.id)
        raise ValueError('Clan changed or was removed. Reload before updating its emoji.')
    # Preserve older emoji references in already-published messages.
    return emoji

async def ensure_thread(bot,mongo,row,guild_id):
    parent=1133096989748363294
    channel=await bot.rest.fetch_channel(parent)
    if int(channel.guild_id)!=int(guild_id):raise ValueError('Clan thread channel belongs to another server.')
    if row.get('thread_id'):
        try:
            existing=await bot.rest.fetch_channel(int(row['thread_id']))
            if int(existing.guild_id)==int(guild_id):return existing
        except hikari.NotFoundError:pass
    active=await bot.rest.fetch_active_threads(guild_id)
    archived=await bot.rest.fetch_public_archived_threads(parent)
    thread=next((t for t in [*active,*archived] if t.parent_id==parent and t.name==row['name']),None)
    if thread is None:thread=await bot.rest.create_thread(parent,hikari.ChannelType.GUILD_PUBLIC_THREAD,row['name'],auto_archive_duration=timedelta(days=1))
    result=await mongo.clans.update_one({'_id':row['_id'],'thread_id':row.get('thread_id') if 'thread_id' in row else {'$exists':False}},{'$set':{'thread_id':thread.id}})
    if not result.matched_count:raise ValueError('Clan changed. Thread was retained; refresh and review it.')
    return thread
