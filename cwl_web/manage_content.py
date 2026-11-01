"""Schema-driven editors over the same recruitment records used by /manage."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from types import SimpleNamespace

from aiohttp import web
from pymongo.errors import DuplicateKeyError
from .manage_bridge import API, GUILD_ID


def modules():
    from extensions.commands import content as gauntlet
    from utils import recruit_question_content as questions, ticket_staff_content as staff, fwa_war_content as war
    return gauntlet, questions, staff, war


def catalog():
    gauntlet, questions, _, war = modules()
    result = []
    def add(prefix, key, label, permission, group, description):
        result.append(dict(id=f'{prefix}--{key}', label=label, permission=permission, group=group, description=description))
    for key, doc in gauntlet.DOCUMENTS.items():
        add('gauntlet', key, doc.label, 'recruit', 'Welcome messages', 'Preview and edit this private ticket message.' if key == 'rite-of-passage' else 'Preview, edit and publish this message.')
        if key not in {'apply', 'rite-of-passage'}:
            add('destination', key, f'{doc.label}: posting channel', 'recruit', 'Welcome messages', 'Choose the channel used by Discord /manage when posting this message.')
    for group in questions.GROUPS.values():
        for key in group['variants']:
            add('question', key, questions.VARIANT_LABELS[key], 'recruitment_questions', group['label'], 'Changes apply the next time this question is sent.')
    for key in ('main', 'fwa'):
        add('staff', key, f'{key.upper()} staff messages', 'recruitment_staff_thread', 'Recruitment staff', 'Changes apply to new tickets. Existing threads keep their messages.')
    for key in war.VARIANTS:
        add('war', key, f'{key.title()} war message', 'fwa_war_messages', 'FWA war messages', 'Changes apply the next time the bot sends this war plan.')
    return result


def descriptor(item_id):
    item = next((item for item in catalog() if item['id'] == item_id), None)
    if item is None:
        raise web.HTTPNotFound(text='Choose an available message')
    return item


def fingerprint(row):
    return hashlib.sha256(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()


async def load(db, item):
    gauntlet, questions, staff, war = modules()
    prefix, key = item['id'].split('--', 1)
    if prefix == 'gauntlet':
        sections, media, revision = await gauntlet.template_for(db, gauntlet.DOCUMENTS[key], GUILD_ID)
        return dict(sections=sections, media=media, revision=revision)
    if prefix == 'destination':
        row = await db.bot_config.find_one({'_id': gauntlet.destination_key(GUILD_ID, key)})
        return {'channel_id': str(row['channel_id']) if row and row.get('channel_id') else '', 'revision': fingerprint(row), '_row': row}
    if prefix == 'staff':
        return await staff.load(db, GUILD_ID, key)
    return await (questions if prefix == 'question' else war).load_template(db, GUILD_ID, key)


def schema(item, template):
    gauntlet, questions, staff, war = modules()
    prefix, key = item['id'].split('--', 1)
    fields = []
    def field(key, label, value, type='textarea', **extra):
        fields.append(dict(key=key, label=label, value=value, type=type, **extra))
    if prefix == 'destination':
        field('channel_id', 'Posting channel', template['channel_id'], 'channel')
    elif prefix == 'staff':
        for slot, section in template['sections'].items():
            label = staff.section_label(slot, section)
            field(f'sections.{slot}.title', f'{label}: title (optional)', section['title'], 'text')
            field(f'sections.{slot}.body', f'{label}: message', section['body'])
    else:
        module = {'gauntlet': gauntlet, 'question': questions, 'war': war}[prefix]
        for index, label in enumerate(module.BLOCK_LABELS[key]):
            field(f'sections.{index}', label, template['sections'][index])
        slots = dict(gauntlet.MEDIA_SLOTS[key]) if prefix == 'gauntlet' else getattr(module, 'MEDIA_LABELS', {}).get(key, {})
        for slot, label in slots.items():
            field(f'media.{slot}', label, template.get('media', {}).get(slot, ''), 'text', description='Public HTTPS image URL. Leave empty for original artwork.' if prefix == 'gauntlet' else 'Public HTTPS image URL.')
        if 'footer_url' in template and template['footer_url'] is not None:
            field('footer_url', 'Footer image', template['footer_url'], 'text')
        if 'accent' in template:
            field('accent', 'Accent color (hex)', f"#{template['accent']:06x}", 'text')
    from utils.url_safety import MAX_IMAGE_BYTES
    for entry in fields:
        if entry['key'].startswith('media.') or entry['key'] == 'footer_url':
            entry['upload_endpoint'] = API + '/manage/content/' + item['id'] + '/upload/' + entry['key']
            entry['upload_max_bytes'] = MAX_IMAGE_BYTES
            entry['upload_label'] = 'Upload ' + entry['label'].lower()
            purpose = ('Appears below the message text.' if entry['key'] == 'footer_url' or entry['key'] == 'media.footer'
                       else 'Replaces the ' + entry['label'].lower() + ' in this Discord message.')
            if entry['label'].startswith('Image '):
                purpose = 'Replaces image ' + entry['label'][6:] + ' in the message, counted from top to bottom.'
            entry['description'] = purpose + ' Save changes to apply this draft.' + (' Leave empty to use the original artwork.' if prefix == 'gauntlet' else '')
    actions = []
    if prefix == 'gauntlet' and key != 'rite-of-passage':
        actions.append(dict(id='load-published', label='Copy from Discord', advanced=True, description='Copy the current Discord post into this draft. Save to keep it.', confirm='Replace the editor draft with the published copy? Nothing is saved yet.', endpoint=API + '/manage/content/' + item['id'] + '/load-published'))
    if prefix != 'destination':
        actions.append(dict(id='reset', label='Reset to default', advanced=True, description='Replace saved text and artwork with the bot’s default message.', confirm='Reset saved text and artwork to the default message? Your saved edits will be replaced. This does not update the Discord post.', endpoint=API + '/manage/content/' + item['id'] + '/reset'))
    if prefix == 'staff':
        actions.append(dict(id='add', label='Add staff message', endpoint=API + '/manage/content/' + item['id'] + '/add'))
        for slot, section in template['sections'].items():
            if slot.startswith('custom_'):
                actions.append(dict(id='remove-' + slot, label='Remove ' + staff.section_label(slot, section), confirm='Remove this additional staff message?', endpoint=API + '/manage/content/' + item['id'] + '/remove-' + slot))
    return {**{k: v for k, v in item.items() if k != 'permission'}, 'endpoint': API + '/manage/content/' + item['id'], 'revision': template['revision'], 'fields': fields, 'preview_supported': prefix != 'destination', 'publish_endpoint': API + '/manage/publish/' + key if prefix == 'gauntlet' and key != 'rite-of-passage' else None, 'actions': actions}


def candidate(item, loaded, body):
    if not isinstance(body, dict) or set(body) - {'revision', 'values', 'request_id'} or not isinstance(body.get('values'), dict):
        raise ValueError('Provide the fields to save and their revision')
    if type(body.get('revision')) is not type(loaded['revision']) or body['revision'] != loaded['revision']:
        raise web.HTTPConflict(text='Someone changed this message. Reload it before saving.')
    allowed = {field['key'] for field in schema(item, loaded)['fields']}
    if set(body['values']) - allowed:
        raise ValueError('Unknown message fields')
    result = deepcopy(loaded)
    for path, value in body['values'].items():
        if not isinstance(value, str):
            raise ValueError('Message fields must be text')
        parts = path.split('.')
        if path == 'accent':
            import re
            if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                raise ValueError('Use a color such as #DAA520')
            result[path] = int(value[1:], 16)
        elif parts[0] == 'sections':
            if isinstance(result['sections'], list):
                result['sections'][int(parts[1])] = value
            else:
                result['sections'][parts[1]][parts[2]] = value
        elif parts[0] == 'media':
            if value or not item['id'].startswith('gauntlet--'):
                result.setdefault('media', {})[parts[1]] = value
            else:
                result.setdefault('media', {}).pop(parts[1], None)
        else:
            result[path] = value
    return result


# Only files referenced by native renderers can be exposed as preview artwork.
_ARTWORK = {}


def _preview_url(value):
    from .manage_operations import public_url
    return value if isinstance(value, str) and public_url(value) else None


def _emoji(value):
    if not isinstance(value, dict):
        return None
    if value.get('id') and str(value['id']).isdigit():
        return f"<{'a' if value.get('animated') else ''}:{value.get('name') or 'emoji'}:{value['id']}>"
    return str(value.get('name') or '') or None


def serialize_components(components, item_id):
    from pathlib import Path
    root = (Path(__file__).resolve().parents[1] / 'assets').resolve()
    attachments = {}
    payloads = []
    for component in components:
        if isinstance(component, dict):
            payload, resources = component, []  # Already rendered server-owned V2 payload.
        else:
            payload, resources = component.build()
        payloads.append(payload)
        for resource in resources:
            path = getattr(resource, 'path', None)
            if path is None:
                continue
            path = Path(path).resolve()
            if not path.is_relative_to(root) or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.gif', '.webp'} or not path.is_file():
                continue
            token = hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:24]
            _ARTWORK[(item_id, token)] = path
            attachments['attachment://' + resource.filename] = API + '/manage/content/' + item_id + '/artwork/' + token

    def image_url(value):
        return attachments.get(value) or _preview_url(value)

    def convert(node):
        kind = int(node.get('type', 0))
        children = [part for child in node.get('components', []) if (part := convert(child))]
        if kind == 17:
            result = {'type': 'container', 'children': children}
            if node.get('accent_color') is not None:
                result['accent'] = f"#{int(node['accent_color']):06x}"
            return result
        if kind == 10:
            return {'type': 'text', 'text': str(node.get('content', ''))}
        if kind == 14:
            return {'type': 'separator', 'divider': bool(node.get('divider', True))}
        if kind == 1:
            return {'type': 'row', 'children': children}
        if kind == 9:
            result = {'type': 'section', 'children': children}
            accessory = convert(node.get('accessory', {}))
            if accessory:result['accessory'] = accessory
            return result
        if kind == 12:
            return {'type': 'media', 'items': [
                {'url': image_url(entry.get('media', {}).get('url', '')),
                 'description': str(entry.get('description') or 'Message artwork')}
                for entry in node.get('items', [])
            ]}
        if kind == 11:
            return {'type': 'thumbnail', 'url': image_url(node.get('media', {}).get('url', '')),
                    'description': str(node.get('description') or 'Message image')}
        if kind == 2:
            result = {'type': 'button', 'label': str(node.get('label') or ''),
                      'style': int(node.get('style', 2)), 'emoji': _emoji(node.get('emoji'))}
            if _preview_url(node.get('url')):result['url'] = node['url']
            return result
        if kind in (3, 5, 6, 7, 8):
            return {'type': 'select', 'placeholder': str(node.get('placeholder') or 'Choose an option'),
                    'options': [{'label': str(option.get('label') or ''),
                                 'description': str(option.get('description') or ''),
                                 'emoji': _emoji(option.get('emoji'))}
                                for option in node.get('options', [])]}
        return None
    return [part for payload in payloads if (part := convert(payload))]


async def artwork(request):
    from .server_management import require_manage
    item = descriptor(request.match_info['item'])
    await require_manage(request, item['permission'])
    path = _ARTWORK.get((item['id'], request.match_info['token']))
    if path is None or not path.is_file():
        raise web.HTTPNotFound(text='Open the message preview again to load its artwork.')
    return web.FileResponse(path, headers={'Cache-Control': 'private, max-age=3600', 'X-Content-Type-Options': 'nosniff'})


async def editor_document(item, template):
    result = schema(item, template)
    if result['preview_supported']:
        result['preview'] = await preview(item, template)
    return result


async def preview(item, template):
    gauntlet, questions, staff, war = modules()
    prefix, key = item['id'].split('--', 1)
    if prefix == 'destination':
        return [{'type': 'text', 'text': f"Posting channel: {template['channel_id']}"}]
    if prefix == 'staff':
        staff.validate(key, template)
        return [{'type': 'container', 'children': [{'type': 'text', 'text': text}]} for _, text in staff.messages(key, template, recruiter_role=1)]
    if prefix == 'gauntlet':
        # Same native renderer validates text count, size and layout.
        components = await gauntlet.render(gauntlet.DOCUMENTS[key], template['sections'], media=template['media'], preview=True)
    elif prefix == 'question':
        components = questions.preview_template(template)
    else:
        components, _ = war.preview_template(template)
    return serialize_components(components, item['id'])


async def catalog_sections(request):
    from .server_management import require_manage
    allowed = {}
    result = []
    for item in catalog():
        permission = item['permission']
        if permission not in allowed:
            try:
                await require_manage(request, permission)
                allowed[permission] = True
            except web.HTTPForbidden:
                allowed[permission] = False
        result.append({**{k: v for k, v in item.items() if k != 'permission'},
                       'allowed': allowed[permission], 'endpoint': API + '/manage/content/' + item['id']})
    return result


async def index(request):
    from .server_management import require_manage
    allowed = {}
    result = []
    for item in catalog():
        permission = item['permission']
        if permission not in allowed:
            try:
                await require_manage(request, permission)
                allowed[permission] = True
            except web.HTTPForbidden:
                allowed[permission] = False
        if allowed[permission]:
            result.append({k: v for k, v in item.items() if k != 'permission'})
    return web.json_response({'sections': result})


async def item_handler(request):
    from .server_management import require_manage, mongo, discord
    item = descriptor(request.match_info['item'])
    actor = await require_manage(request, item['permission'], write=request.method != 'GET')
    gauntlet, questions, staff, war = modules()
    prefix, key = item['id'].split('--', 1)
    async with mongo(request) as db:
        loaded = await load(db, item)
        if request.method == 'GET':
            return web.json_response(await editor_document(item, loaded))
        try:
            body = await request.json()
            action = request.match_info.get('action')
            updated = candidate(item, loaded, dict(body, values=body.get('values', {})))
            if getattr(request, 'history_template', None) is not None:
                updated = deepcopy(request.history_template)
                updated['revision'] = loaded['revision']
            if action == 'load-published' and prefix == 'gauntlet':
                coordinates = await gauntlet.published_for(db, GUILD_ID, key)
                if not coordinates:
                    raise ValueError('No published post is saved for this message')
                channel = await discord(request, 'GET', f"/channels/{coordinates['channel_id']}")
                if str(channel.get('guild_id')) != str(GUILD_ID):
                    raise ValueError('The saved post is not in this server')
                post = await discord(request, 'GET', f"/channels/{coordinates['channel_id']}/messages/{coordinates['message_id']}")
                me = await discord(request, 'GET', '/users/@me')
                if str(post.get('author', {}).get('id')) != str(me['id']):
                    raise ValueError('The saved post was not sent by this bot')
                def convert(value):
                    if isinstance(value, dict):
                        return SimpleNamespace(**{name: convert(child) for name, child in value.items()})
                    if isinstance(value, list):
                        return [convert(child) for child in value]
                    return value
                components = convert(post.get('components', []))
                document = gauntlet.DOCUMENTS[key]
                if gauntlet.component_shape(components) != gauntlet.component_shape(await gauntlet.baseline(document)) or not gauntlet.acknowledgement_id(components, document):
                    raise ValueError('The saved post no longer matches this message type')
                sections = [node.content for node in gauntlet.text_nodes(components)]
                urls = gauntlet.media_snapshot(components)
                if len(urls) != len(gauntlet.MEDIA_SLOTS[key]):
                    raise ValueError('The published artwork layout changed')
                media = dict(zip((slot for slot, _ in gauntlet.MEDIA_SLOTS[key]), urls))
                await gauntlet.render(document, sections, media=media, preview=True)
                draft = {f'sections.{index}': value for index, value in enumerate(sections)}
                draft.update({f'media.{slot}': url for slot, url in media.items()})
                return web.json_response({'draft_values': draft, 'message': 'Published copy loaded. Save changes to keep it.'})
            if action == 'reset':
                if prefix == 'destination':
                    raise ValueError('Select a posting channel instead')
                if prefix == 'gauntlet':
                    components = await gauntlet.baseline(gauntlet.DOCUMENTS[key])
                    updated = dict(sections=[node.content for node in gauntlet.text_nodes(components)], media={}, revision=loaded['revision'])
                else:
                    updated = (staff.defaults(key) if prefix == 'staff' else (questions if prefix == 'question' else war).default_template(key))
                    updated['revision'] = loaded['revision']
            elif action == 'add' and prefix == 'staff':
                from uuid import uuid4
                updated['sections']['custom_' + uuid4().hex[:16]] = {'title': 'New staff message', 'body': 'Edit this message before opening new tickets.'}
            elif action and action.startswith('remove-custom_') and prefix == 'staff':
                slot = action.removeprefix('remove-')
                if slot not in updated['sections']:
                    raise ValueError('This message no longer exists')
                del updated['sections'][slot]
            elif action:
                raise web.HTTPNotFound(text='Unknown message action')
            rendered = await preview(item, updated)
            if request.path.endswith('/preview'):
                return web.json_response({**schema(item, updated), 'preview': rendered})
            from .change_history import begin, finish, fields
            history_id = await begin(db, API + '/manage/content/' + item['id'], actor, fields(schema(item, loaded)), getattr(request, 'history_action', action or 'edit'), loaded)
            if prefix == 'gauntlet':
                ctx = SimpleNamespace(user=SimpleNamespace(id=int(actor['user_id'])))
                if not await gauntlet._save(ctx, dict(updated, document=key, guild_id=GUILD_ID), db, dashboard=True):
                    raise web.HTTPConflict(text='Someone changed this message. Reload it before saving.')
            elif prefix == 'staff':
                await staff.save(db, GUILD_ID, key, updated, int(actor['user_id']))
            elif prefix == 'destination':
                value = updated['channel_id']
                if not value.isdigit() or len(value) not in range(15, 23):
                    raise ValueError('Choose a Discord text or announcement channel')
                channel = await discord(request, 'GET', f'/channels/{value}')
                if str(channel.get('guild_id')) != str(GUILD_ID) or channel.get('type') not in (0, 5):
                    raise ValueError('Choose a text or announcement channel in this server')
                row = loaded['_row']
                data = dict(guild_id=GUILD_ID, document=key, channel_id=int(value), updated_by=int(actor['user_id']), updated_at=datetime.now(timezone.utc))
                if row is None:
                    await db.bot_config.insert_one(dict(data, _id=gauntlet.destination_key(GUILD_ID, key)))
                else:
                    if not (await db.bot_config.update_one(row, {'$set': data})).matched_count:
                        raise web.HTTPConflict(text='Posting channel changed. Reload before saving.')
            else:
                module = questions if prefix == 'question' else war
                await module.save_template(db, GUILD_ID, key, updated, loaded['revision'], int(actor['user_id']))
            fresh = await load(db, item)
            document = await editor_document(item, fresh)
            await finish(db, history_id, fields(document), fresh)
            return web.json_response(document)
        except DuplicateKeyError:
            raise web.HTTPConflict(text='Someone changed this message. Reload before saving.') from None
        except ValueError as exc:
            if 'changed' in str(exc).lower() or 'another editor' in str(exc).lower():
                raise web.HTTPConflict(text=str(exc)) from None
            raise web.HTTPBadRequest(text=str(exc)) from None


async def upload(request):
    from .server_management import require_manage, mongo
    from utils.media_store import MediaStore, MediaStoreError, recruit_content_folder
    from utils.url_safety import MAX_IMAGE_BYTES
    item = descriptor(request.match_info['item'])
    await require_manage(request, item['permission'], write=True)
    async with mongo(request) as db:
        loaded = await load(db, item)
    revision = request.query.get('revision')
    if revision != str(loaded['revision']):
        raise web.HTTPConflict(text='This message changed. Reload before uploading.')
    slot = request.match_info['slot']
    fields = schema(item, loaded)['fields']
    if not any(field['key'] == slot and field.get('upload_endpoint') for field in fields):
        raise web.HTTPBadRequest(text='Choose an artwork field')
    if request.content_length is not None and request.content_length > MAX_IMAGE_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES, actual_size=request.content_length)
    chunks = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        chunks.extend(chunk)
        if len(chunks) > MAX_IMAGE_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES, actual_size=len(chunks))
    media = request.app.get('server_management_media') or MediaStore.from_env()
    try:
        url = await media.upload_bytes(bytes(chunks), folder=recruit_content_folder(GUILD_ID, item['id']), name=slot.replace('.', '-'))
    except MediaStoreError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from None
    return web.json_response({'url': url})


def routes(app):
    from . import manage_delivery
    manage_delivery.routes(app)
    app.router.add_get(API + '/manage/content/{item}/artwork/{token}', artwork)
    app.router.add_post(API + '/manage/content/{item}/upload/{slot}', upload)
    app.router.add_get(API + '/manage/content', index)
    app.router.add_get(API + '/manage/content/{item}', item_handler)
    app.router.add_patch(API + '/manage/content/{item}', item_handler)
    app.router.add_post(API + '/manage/content/{item}/preview', item_handler)
    app.router.add_post(API + '/manage/content/{item}/{action}', item_handler)
