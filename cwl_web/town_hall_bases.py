"""Town Hall base HTTP field adaptation; storage stays in utils.town_halls."""
from aiohttp import web

from utils import town_halls as registry
from . import server_management as shared

PREFIX = 'bases.'
MOVED_MESSAGE = 'FWA bases moved to Town Halls. Refresh this page.'


async def permissions(actor, db):
    return (await shared.allowed(actor, 'fwa_weight', db, write=True),
            await shared.allowed(actor, 'fwa_bases', db, write=True))


def fields(doc, level, *, editable):
    item = doc['levels'][str(level)].get('bases', {})
    result = []
    for path in registry.BASE_PATHS:
        parts = path.split('.')
        if level < registry.MERGED_DEFENSES_FROM and parts[0] == 'non_merged':
            continue
        value = item.get(parts[0], {}).get(parts[1], '') if len(parts) == 2 else item.get(path, '')
        image = path in ('war_image', 'active_image')
        text = path.endswith(('instructions', 'upgrade_notes'))
        group = 'Base images' if image else registry.variant_label(level, parts[0]) or 'Base'
        label = {'war_image': 'War base image', 'active_image': 'Active base image',
                 'link': 'Base link', 'instructions': 'Base instructions', 'upgrade_notes': 'Upgrade notes'}[parts[-1]]
        field = dict(key=PREFIX + path, label=label, value=value,
                     type='textarea' if text else 'text', group=group,
                     readonly=not editable, max_length=4000 if text else 4096)
        if image and editable:
            from utils.url_safety import MAX_IMAGE_BYTES
            field.update(upload_endpoint=f'/manage/town-halls/{level}/upload/{path}',
                         upload_label='Upload image', upload_max_bytes=MAX_IMAGE_BYTES)
        result.append(field)
    return result


def decorate(document, doc, level, *, can_weight, can_bases):
    """Saved metadata drives section status; drafts never affect visibility."""
    document['base_management'] = True
    document['partial_save'] = True
    document['fields'] += fields(doc, level, editable=can_bases)
    document['section_readonly'] = {field['group']: not can_weight if field['group'] == 'Town Hall' else not can_bases
                                    for field in document['fields']}
    for field in document['fields']:
        if field.get('group') == 'Town Hall':
            field['readonly'] = not can_weight
    bases = doc['levels'][str(level)].get('bases', {})
    variants = ('merged',) if level < registry.MERGED_DEFENSES_FROM else ('merged', 'non_merged')
    document['base_status'] = {registry.variant_label(level, variant) or 'Base': bool(bases.get(variant, {}).get('link'))
                               for variant in variants}
    document['base_originals'] = {PREFIX + path: registry.base_field_snapshot(doc, level, path)
                                  for path in registry.BASE_PATHS}
    return document


async def upload(request):
    from utils.media_store import MediaStore, MediaStoreError, fwa_base_folder, FWA_WAR_BASE_NAME, FWA_ACTIVE_BASE_NAME
    from utils.url_safety import MAX_IMAGE_BYTES
    await shared.require_manage(request, 'fwa_bases', write=True)
    item, slot = request.match_info['item'], request.match_info['slot']
    if slot not in ('war_image', 'active_image'):
        raise web.HTTPBadRequest(text='Select a base image.')
    try:
        level = int(item)
        if str(level) != item or not 1 <= level <= 99:
            raise ValueError()
    except ValueError:
        raise web.HTTPNotFound(text='This Town Hall is not in the list.') from None
    async with shared.mongo(request) as db:
        doc = await registry.load(db, shared.GUILD_ID)
    if doc is None:
        raise web.HTTPServiceUnavailable(text=registry.MISSING_MESSAGE)
    if item not in doc['levels'] or level < doc['lowest_fwa_town_hall']:
        raise web.HTTPNotFound(text='Bases are for FWA Town Hall levels only.')
    if request.query.get('revision') != str(doc['revision']):
        raise web.HTTPConflict(text='Base settings changed. Refresh before uploading.')
    if request.content_length is not None and request.content_length > MAX_IMAGE_BYTES:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES, actual_size=request.content_length)
    data = bytearray()
    async for chunk in request.content.iter_chunked(65536):
        data.extend(chunk)
        if len(data) > MAX_IMAGE_BYTES:
            raise web.HTTPRequestEntityTooLarge(max_size=MAX_IMAGE_BYTES, actual_size=len(data))
    media = request.app.get('server_management_media') or MediaStore.from_env()
    try:
        url = await media.upload_bytes(bytes(data), folder=fwa_base_folder(f'th{level}'),
                                       name=FWA_WAR_BASE_NAME if slot == 'war_image' else FWA_ACTIVE_BASE_NAME)
    except MediaStoreError:
        raise web.HTTPBadRequest(text='Image upload failed. Check the file and try again.') from None
    # Upload creates media only. Registry CAS happens solely on explicit Save.
    return web.json_response({'url': url})
