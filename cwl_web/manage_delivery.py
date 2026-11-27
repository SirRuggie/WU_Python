"""Reviewed Gauntlet delivery through the bot-owned, durable Manage queue."""
from datetime import timedelta
import uuid
import hikari
from pymongo.errors import DuplicateKeyError
from aiohttp import web
from .manage_bridge import GUILD_ID, API
from .manage_content import fingerprint
from utils.user_copy import needs_permissions


def _bound(key):
    """Apply and Warrior Desk posts are bound to ticket intake; Ticket settings posts them."""
    from extensions.commands import content
    return key in content.BOUND_PANELS


def snapshot(components):
    """Equivalent snapshot for Discord JSON and Hikari component objects."""
    from extensions.commands import content

    def value(node, key, default=None):
        return node.get(key, default) if isinstance(node, dict) else getattr(node, key, default)

    def walk(nodes):
        for node in nodes:
            yield node
            yield from walk(value(node, 'components', ()) or ())
            accessory = value(node, 'accessory')
            if accessory is not None:
                yield from walk((accessory,))

    texts, media = [], []
    for node in walk(components):
        kind = value(node, 'type')
        if kind == hikari.ComponentType.TEXT_DISPLAY:
            text = value(node, 'content')
            if not isinstance(text, str):
                raise ValueError('The Discord post has invalid text')
            texts.append(text)
        elif kind in (hikari.ComponentType.MEDIA_GALLERY, hikari.ComponentType.THUMBNAIL):
            items = value(node, 'items', ()) if kind == hikari.ComponentType.MEDIA_GALLERY else (node,)
            for item in items:
                resource = value(item, 'media')
                url = value(resource, 'url', resource)
                if url is None or not str(url):
                    raise ValueError('The Discord post has invalid media')
                media.append(content.canonical_media_url(str(url)))
    return {'text': texts, 'media': media}


async def review(request, key, *, allow_ambiguous_display=False):
    from .server_management import mongo, discord
    from extensions.commands import content
    from utils.gauntlet_content import layout_for, AMBIGUOUS_NOTICE
    if key not in content.DOCUMENTS or content.is_template_only(key):
        raise web.HTTPNotFound(text='This message is only used in private ticket panels')
    async with mongo(request) as db:
        try:
            options = {'allow_ambiguous_display': True} if allow_ambiguous_display else {}
            sections, media, revision = await content.template_for(db, content.DOCUMENTS[key], GUILD_ID, **options)
        except ValueError as error:
            if key != 'family-particulars':
                raise
            message = 'The saved message is invalid. Reopen it for staff review.'
            if (type(error) is ValueError and len(error.args) == 1
                    and type(error.args[0]) is str and error.args[0] == AMBIGUOUS_NOTICE):
                message = AMBIGUOUS_NOTICE
            raise web.HTTPBadRequest(text=message) from None
        ambiguous = layout_for(key, sections) == "ambiguous"
        if ambiguous and not allow_ambiguous_display:
            raise web.HTTPBadRequest(text=AMBIGUOUS_NOTICE)
        destination = await content.destination_for(db, GUILD_ID, key)
        target = await content.published_for(db, GUILD_ID, key)
        derived = {}
        if key in {'about-us', 'wu-faq'}:
            try:
                rendered = await content.render(content.DOCUMENTS[key], sections, media=media,
                                                preview=True, mongo=db, guild_id=GUILD_ID)
            except ValueError as error:
                raise web.HTTPBadRequest(text=str(error)) from None
            from .manage_content import serialize_components
            derived = {'rendered_snapshot': snapshot(rendered),
                       'rendered_preview': serialize_components(rendered, 'gauntlet--' + key)}
    live = None
    if target and not ambiguous:
        post = await discord(request, 'GET', f"/channels/{target['channel_id']}/messages/{target['message_id']}")
        live = snapshot(post.get('components', []))
    return dict(document=key, template_revision=revision, template=fingerprint({'sections':sections,'media':media}), destination=destination, target=target, post=live, sections=sections, **derived)


async def page(request):
    from .server_management import require_manage, discord
    from extensions.commands import content
    await require_manage(request, 'recruit')
    key = request.match_info['document']
    data = await review(request, key, allow_ambiguous_display=True)
    from utils.gauntlet_content import layout_for, logical_sections, AMBIGUOUS_NOTICE
    if layout_for(key, data['sections']) == 'ambiguous':
        # Raw display is safe only here. Queue review and the delivery worker
        # keep rejecting ambiguous layouts before any durable or Discord effect.
        fields = [{'key':f'section.{i}', 'label':f'Raw saved field {i + 1}',
                   'type':'textarea', 'value':value, 'readonly':True}
                  for i, value in enumerate(data['sections'])]
        return web.json_response({
            'id':'publish--'+key, 'label':'Publish '+content.DOCUMENTS[key].label,
            'group':'Welcome messages', 'description':'Review the saved message.',
            'warning':AMBIGUOUS_NOTICE, 'posting_channel':None, 'existing_channel':None,
            'destination_editor':None, 'target_url':None, 'revision':fingerprint(data),
            'fields':fields, 'readonly':True, 'actions':[],
        })
    displayed = logical_sections(key, data['sections']) if key in content.BOXES else data['sections']
    fields = [{'key':f'section.{i}', 'label':label, 'type':'textarea', 'value':displayed[i], 'readonly':True} for i,label in content.editable_blocks(content.DOCUMENTS[key],data['sections'])]
    channel = data['destination'] or (data['target'] or {}).get('channel_id')
    fields.insert(0, {'key':'channel','label':'Posting channel','type':'text','value':str(channel or "Select a posting channel first"),'readonly':True})
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
    writable = layout_for(key, data['sections']) == 'standard'
    actions = []
    for action, label, enabled in [('send','Send new post',writable and not _bound(key) and data['destination']), ('update','Update existing post',data['target'])]:
        if enabled:
            actions.append({'id':action,'label':label,'confirm':f'{label} in Discord? Review the channel and saved message above first.', 'endpoint':API + f'/manage/publish/{key}/{action}'})
    response = {'id':'publish--'+key,'label':'Publish '+content.DOCUMENTS[key].label,'group':'Welcome messages','description':'Publish the saved message to Discord.', 'posting_channel':channel_name, 'existing_channel':existing_channel, 'destination_editor':API + '/manage/content/destination--' + key if not _bound(key) else None, 'target_url':f"https://discord.com/channels/{GUILD_ID}/{data['target']['channel_id']}/{data['target']['message_id']}" if data['target'] else None, 'revision':fingerprint(data),'fields':fields,'readonly':True,'actions':actions}
    if 'rendered_preview' in data:
        response['preview'] = data['rendered_preview']
    return web.json_response(response)


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
    if action == 'send':
        from utils.gauntlet_content import require_writable
        try:
            require_writable(key, data['sections'])
        except ValueError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from None
    if action == 'send' and (_bound(key) or not data['destination']):
        raise web.HTTPBadRequest(text="Select a posting channel. Apply and Warrior Desk posts are created in Ticket settings.")
    if action == 'update' and not data['target']:
        raise web.HTTPBadRequest(text='There is no saved post to update')
    return await queue_action(request, 'recruit', action, data, fingerprint(data))


async def reviewed_render(document, sections, media, mongo, values, *, action_id):
    """Compose the exact reviewed dependencies immediately before delivery."""
    from extensions.commands import content
    rendered = await content.render(document, sections, media=media, action_id=action_id,
                                    mongo=mongo, guild_id=GUILD_ID)
    if document.key in {'about-us', 'wu-faq'}:
        if 'rendered_snapshot' not in values or snapshot(rendered) != values['rendered_snapshot']:
            raise ValueError('Family Rules or the clan registry changed. Reload and review the complete post before publishing.')
    return rendered


async def publish(bot, mongo, row, ctx):
    from extensions.commands import content
    values = row['values']; key = values['document']; action = row['action']
    if key not in content.DOCUMENTS or content.is_template_only(key) or action not in ('send','update'):
        raise ValueError("Select a public onboarding message")
    document = content.DOCUMENTS[key]
    sections, media, revision = await content.template_for(mongo, document, GUILD_ID)
    from utils.gauntlet_content import layout_for, AMBIGUOUS_NOTICE
    if layout_for(key, sections) == "ambiguous":
        raise ValueError(AMBIGUOUS_NOTICE)
    if revision != values['template_revision'] or fingerprint({'sections':sections,'media':media}) != values['template']:
        raise ValueError('The saved message changed. Reload and review before publishing.')
    destination = await content.destination_for(mongo, GUILD_ID, key)
    if destination != values['destination']:
        raise ValueError('The posting channel changed. Reload before publishing.')
    target = await content.published_for(mongo, GUILD_ID, key)
    if target != values['target']:
        raise ValueError('The published post changed. Reload before publishing.')
    if action == 'send':
        from utils.gauntlet_content import require_writable
        require_writable(key, sections)
    if action == 'send' and target:
        existing = await bot.rest.fetch_message(target['channel_id'], target['message_id'])
        if snapshot(existing.components) != values['post']:
            raise ValueError('The Discord post changed. Reload and review before sending.')
    if action == 'send':
        if _bound(key) or not destination:
            raise ValueError("Select a posting channel. Apply and Warrior Desk posts are created in Ticket settings.")
        channel = await bot.rest.fetch_channel(destination)
        if int(getattr(channel,'guild_id',0)) != GUILD_ID or channel.type not in content._DESTINATION_TYPES:
            raise ValueError("Select a text or announcement channel in this server.")
        permissions = await content.destination_permissions(bot, GUILD_ID, channel)
        needed = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.SEND_MESSAGES | hikari.Permissions.ATTACH_FILES
        if not permissions & hikari.Permissions.ADMINISTRATOR and permissions & needed != needed:
            raise ValueError(needs_permissions("View Channel", "Send Messages", "Attach Files"))
        ready, issue = await content._ready_for_destination(ctx, bot, channel, permissions, key)
        if not ready:
            raise ValueError(issue or 'Onboarding roles or next channels need attention.')
        rendered = await reviewed_render(document, sections, media, mongo, values, action_id=uuid.uuid4().hex)
        # Native durable send claim also protects direct/replayed dispatches.
        try:
            await mongo.bot_config.insert_one({'_id':'content_send:'+row['_id'], 'guild_id':GUILD_ID,'document':key,'channel_id':destination,'requested_by':int(row['user_id']),'created_at':content.utcnow()})
        except DuplicateKeyError:
            raise ValueError('This send was already attempted. Check the channel before sending again.') from None
        # Recheck after the durable claim await; the reviewed dependencies must
        # still match the payload at the actual Discord boundary.
        rendered = await reviewed_render(document, sections, media, mongo, values, action_id=uuid.uuid4().hex)
        message = await bot.rest.create_message(channel=destination, components=rendered, **content.NO_MENTIONS)
        try:
            await content.remember_published(mongo,GUILD_ID,key,destination,int(message.id),int(row['user_id']))
        except Exception:
            return {'message':f'{document.label} sent, but its link could not be saved. Do not send again.', 'url':f'https://discord.com/channels/{GUILD_ID}/{destination}/{message.id}'}
        return {'message':f'{document.label}: New post sent.', 'url':f'https://discord.com/channels/{GUILD_ID}/{destination}/{message.id}'}
    if not target or (destination and target['channel_id'] != destination):
        raise ValueError('The posting channel must match the saved post.')
    lease = f"content_publish:{target['channel_id']}:{target['message_id']}"; token=uuid.uuid4().hex
    try:
        await mongo.bot_config.update_one({'_id':lease,'until':{'$lte':content.utcnow()}},{'$set':{'until':content.utcnow()+timedelta(minutes=1),'token':token}},upsert=True)
    except DuplicateKeyError:
        raise ValueError("Another update is in progress. Try again later.") from None
    try:
        loaded = await content.loaded_published_target(bot,GUILD_ID,document,target,int(ctx.interaction.application_id))
        message = await bot.rest.fetch_message(target['channel_id'],target['message_id'])
        if int(message.author.id) != int(ctx.interaction.application_id) or not await content.supported_post_shape(document, message.components) or document.acknowledgement and not content.acknowledgement_id(message.components, document):
            raise ValueError('The saved message is no longer a supported bot post.')
        if snapshot(message.components) != values['post']:
            raise ValueError('The Discord post changed. Reload and review before updating.')
        if await content.published_for(mongo,GUILD_ID,key) != target:
            raise ValueError('The active post changed. Reload before updating.')
        acknowledgement = content.acknowledgement_id(message.components,document)
        rendered = await reviewed_render(document, sections, media, mongo, values, action_id=acknowledgement or "public")
        ids = {aid for url in content.media_snapshot(rendered) if (aid:=content.discord_attachment_id(url)) is not None}
        attachments = [attachment for attachment in getattr(message,'attachments',()) if str(attachment.id) in ids]
        await bot.rest.edit_message(target['channel_id'],target['message_id'],components=rendered,attachments=attachments,**content.NO_MENTIONS)
    finally:
        await mongo.bot_config.delete_one({'_id':lease,'token':token})
    return {'message':f'{document.label}: Existing post updated.', 'url':f"https://discord.com/channels/{GUILD_ID}/{target['channel_id']}/{target['message_id']}"}


def routes(app):
    app.router.add_get(API+'/manage/publish/{document}',page)
    app.router.add_post(API+'/manage/publish/{document}/{action}',queue)
