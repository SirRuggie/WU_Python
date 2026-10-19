"""Reviewed Gauntlet delivery through the bot-owned, durable Manage queue."""
from datetime import timedelta
import uuid
import hikari
from pymongo.errors import DuplicateKeyError
from aiohttp import web
from .manage_bridge import GUILD_ID, API
from .manage_content import fingerprint


def snapshot(components):
    """Equivalent snapshot for Discord JSON and Hikari component objects."""
    from extensions.commands import content
    if components and isinstance(components[0], dict):
        children = [node for parent in components for node in parent.get('components', [])]
        texts = [node['content'] for node in children if node.get('type') == 10]
        media = [content.canonical_media_url(item['media']['url']) for node in children if node.get('type') == 12 for item in node.get('items', [])]
    else:
        texts = [node.content for node in content.text_nodes(components)]
        media = [content.canonical_media_url(url) for url in content.media_snapshot(components)]
    return {'text': texts, 'media': media}


async def review(request, key):
    from .server_management import mongo, discord
    from extensions.commands import content
    if key not in content.DOCUMENTS or key == 'rite-of-passage':
        raise web.HTTPNotFound(text='This message is only used in private ticket panels')
    async with mongo(request) as db:
        sections, media, revision = await content.template_for(db, content.DOCUMENTS[key], GUILD_ID)
        destination = await content.destination_for(db, GUILD_ID, key)
        target = await content.published_for(db, GUILD_ID, key)
    live = None
    if target:
        post = await discord(request, 'GET', f"/channels/{target['channel_id']}/messages/{target['message_id']}")
        live = snapshot(post.get('components', []))
    return dict(document=key, template_revision=revision, template=fingerprint({'sections':sections,'media':media}), destination=destination, target=target, post=live, sections=sections)


async def page(request):
    from .server_management import require_manage, discord
    from extensions.commands import content
    await require_manage(request, 'recruit')
    key = request.match_info['document']
    data = await review(request, key)
    fields = [{'key':f'section.{i}', 'label':label, 'type':'textarea', 'value':data['sections'][i], 'readonly':True} for i,label in enumerate(content.BLOCK_LABELS[key])]
    channel = data['destination'] or (data['target'] or {}).get('channel_id')
    fields.insert(0, {'key':'channel','label':'Posting channel','type':'text','value':str(channel or 'Choose a posting channel first'),'readonly':True})
    channel_name = None
    if channel:
        channel_data = await discord(request, 'GET', f'/channels/{channel}')
        if str(channel_data.get('guild_id')) != str(GUILD_ID):
            raise web.HTTPForbidden(text='The posting channel is not in this server.')
        channel_name = '#' + channel_data.get('name', str(channel))
    existing_channel = channel_name
    if data['target'] and data['target']['channel_id'] != channel:
        existing = await discord(request, 'GET', f"/channels/{data['target']['channel_id']}")
        if str(existing.get('guild_id')) != str(GUILD_ID):
            raise web.HTTPForbidden(text='The existing post is not in this server.')
        existing_channel = '#' + existing.get('name', str(data['target']['channel_id']))
    actions = []
    for action, label, enabled in [('send','Send new post',key != 'apply' and data['destination']), ('update','Update existing post',data['target'])]:
        if enabled:
            actions.append({'id':action,'label':label,'confirm':f'{label} in Discord? Review the channel and saved message above first.', 'endpoint':API + f'/manage/publish/{key}/{action}'})
    return web.json_response({'id':'publish--'+key,'label':'Publish '+content.DOCUMENTS[key].label,'group':'Welcome messages','description':'Publish the saved message to Discord.', 'posting_channel':channel_name, 'existing_channel':existing_channel, 'destination_editor':API + '/manage/content/destination--' + key if key != 'apply' else None, 'target_url':f"https://discord.com/channels/{GUILD_ID}/{data['target']['channel_id']}/{data['target']['message_id']}" if data['target'] else None, 'revision':fingerprint(data),'fields':fields,'readonly':True,'actions':actions})


async def queue(request):
    from .server_management import require_manage, queue_action
    await require_manage(request, 'recruit', write=True)
    key = request.match_info['document']
    action = request.match_info['action']
    if action not in ('send','update'):
        raise web.HTTPNotFound()
    data = await review(request, key)
    body = await request.json()
    if not isinstance(body, dict) or body.get('revision') != fingerprint(data):
        raise web.HTTPConflict(text='The message, post, or channel changed. Reload and review before publishing.')
    if action == 'send' and (key == 'apply' or not data['destination']):
        raise web.HTTPBadRequest(text='Choose a posting channel. Apply posts must be created through ticket setup.')
    if action == 'update' and not data['target']:
        raise web.HTTPBadRequest(text='There is no saved post to update')
    return await queue_action(request, 'recruit', action, data, fingerprint(data))


async def publish(bot, mongo, row, ctx):
    from extensions.commands import content
    values = row['values']; key = values['document']; action = row['action']
    if key not in content.DOCUMENTS or key == 'rite-of-passage' or action not in ('send','update'):
        raise ValueError('Choose a public onboarding message')
    document = content.DOCUMENTS[key]
    sections, media, revision = await content.template_for(mongo, document, GUILD_ID)
    if revision != values['template_revision'] or fingerprint({'sections':sections,'media':media}) != values['template']:
        raise ValueError('The saved message changed. Reload and review before publishing.')
    destination = await content.destination_for(mongo, GUILD_ID, key)
    if destination != values['destination']:
        raise ValueError('The posting channel changed. Reload before publishing.')
    target = await content.published_for(mongo, GUILD_ID, key)
    if target != values['target']:
        raise ValueError('The published post changed. Reload before publishing.')
    if action == 'send' and target:
        existing = await bot.rest.fetch_message(target['channel_id'], target['message_id'])
        if snapshot(existing.components) != values['post']:
            raise ValueError('The Discord post changed. Reload and review before sending.')
    if action == 'send':
        if key == 'apply' or not destination:
            raise ValueError('Choose a posting channel. Use ticket setup to create Apply posts.')
        channel = await bot.rest.fetch_channel(destination)
        if int(getattr(channel,'guild_id',0)) != GUILD_ID or channel.type not in content._DESTINATION_TYPES:
            raise ValueError('Choose a text or announcement channel in this server.')
        permissions = await content.destination_permissions(bot, GUILD_ID, channel)
        needed = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES | hikari.Permissions.ATTACH_FILES
        if not permissions & hikari.Permissions.ADMINISTRATOR and permissions & needed != needed:
            raise ValueError('The bot needs View Channel, Send Messages, and Attach Files permissions.')
        ready, issue = await content._ready_for_destination(ctx, bot, channel, permissions, key)
        if not ready:
            raise ValueError(issue or 'Onboarding roles or next channels need attention.')
        rendered = await content.render(document, sections, media=media, action_id=uuid.uuid4().hex)
        # Native durable send claim also protects direct/replayed dispatches.
        try:
            await mongo.bot_config.insert_one({'_id':'content_send:'+row['_id'], 'guild_id':GUILD_ID,'document':key,'channel_id':destination,'requested_by':int(row['user_id']),'created_at':content.utcnow()})
        except DuplicateKeyError:
            raise ValueError('This send was already attempted. Check the channel before sending again.') from None
        message = await bot.rest.create_message(channel=destination, components=rendered, **content.NO_MENTIONS)
        try:
            await content.remember_published(mongo,GUILD_ID,key,destination,int(message.id),int(row['user_id']))
        except Exception:
            return {'message':'Post sent, but its link could not be saved. Do not send again.', 'url':f'https://discord.com/channels/{GUILD_ID}/{destination}/{message.id}'}
        return {'message':'New post sent.', 'url':f'https://discord.com/channels/{GUILD_ID}/{destination}/{message.id}'}
    if not target or (destination and target['channel_id'] != destination):
        raise ValueError('The posting channel must match the saved post.')
    lease = f"content_publish:{target['channel_id']}:{target['message_id']}"; token=uuid.uuid4().hex
    try:
        await mongo.bot_config.update_one({'_id':lease,'until':{'$lte':content.utcnow()}},{'$set':{'until':content.utcnow()+timedelta(minutes=1),'token':token}},upsert=True)
    except DuplicateKeyError:
        raise ValueError('Another update is in progress. Try again shortly.') from None
    try:
        loaded = await content.loaded_published_target(bot,GUILD_ID,document,target,int(ctx.interaction.application_id))
        message = await bot.rest.fetch_message(target['channel_id'],target['message_id'])
        if int(message.author.id) != int(ctx.interaction.application_id) or content.component_shape(message.components) != content.component_shape(await content.baseline(document)) or not content.acknowledgement_id(message.components, document):
            raise ValueError('The saved message is no longer a supported bot post.')
        if snapshot(message.components) != values['post']:
            raise ValueError('The Discord post changed. Reload and review before updating.')
        if await content.published_for(mongo,GUILD_ID,key) != target:
            raise ValueError('The active post changed. Reload before updating.')
        acknowledgement = content.acknowledgement_id(message.components,document)
        rendered = await content.render(document,sections,media=media,action_id=acknowledgement)
        ids = {aid for url in content.media_snapshot(rendered) if (aid:=content.discord_attachment_id(url)) is not None}
        attachments = [attachment for attachment in getattr(message,'attachments',()) if str(attachment.id) in ids]
        await bot.rest.edit_message(target['channel_id'],target['message_id'],components=rendered,attachments=attachments,**content.NO_MENTIONS)
    finally:
        await mongo.bot_config.delete_one({'_id':lease,'token':token})
    return {'message':'Existing post updated.', 'url':f"https://discord.com/channels/{GUILD_ID}/{target['channel_id']}/{target['message_id']}"}


def routes(app):
    app.router.add_get(API+'/manage/publish/{document}',page)
    app.router.add_post(API+'/manage/publish/{document}/{action}',queue)
