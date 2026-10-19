"""Configure shared return destinations without sending a message."""
from aiohttp import web
from utils import return_reminder_settings as settings
from . import server_management as shared
from .manage_operations import cas, revision, check_channel_permissions, checked


def descriptor(row):
    channels = settings.channels(row)
    return dict(id='cwl_return_channels', label='Return reminder channels',
        description='Choose where Main and FWA return reminders are sent. Discord /manage uses the same channels.',
        group='War', revision=revision(row), fields=[
            dict(key=field, label=label, type='channel', value=str(channels[section]))
            for section, field, label in [('MAIN', 'main_channel_id', 'Main return channel'),
                                          ('FWA', 'fwa_channel_id', 'FWA return channel')]],
        warning='Saving changes the destination for future reminders. Existing schedules continue. No message is sent now.')


async def read(request):
    await shared.require_manage(request, 'cwl_rosters')
    async with shared.mongo(request) as db:
        return web.json_response(descriptor(await settings.load(db)))


async def save(request):
    actor = await shared.require_manage(request, 'cwl_rosters', write=True)
    from .app import _json
    body = await _json(request)
    values = checked(body.get('values'), settings.FIELDS.values())
    if not values:
        raise web.HTTPBadRequest(text='Choose a return channel to change.')
    changes = {}
    for key, value in values.items():
        if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 15 <= len(value) <= 22:
            raise web.HTTPBadRequest(text='Choose a channel from this server.')
        channel = await shared.discord(request, 'GET', '/channels/' + value)
        if str(channel.get('guild_id')) != str(shared.GUILD_ID) or channel.get('type') not in (0, 5):
            raise web.HTTPBadRequest(text='Choose a text channel in this server.')
        await check_channel_permissions(request, channel)
        changes[key] = int(value)
    async with shared.mongo(request) as db:
        row = await settings.load(db)
        if body.get('revision') != revision(row):
            raise web.HTTPConflict(text='Return channels changed. Refresh and review your edit.')
        # Include both values so a simultaneous edit of either destination conflicts.
        effective = settings.channels(row)
        changes = {**{field: effective[section] for section, field in settings.FIELDS.items()}, **changes}
        await cas(db.bot_config, settings.DOCUMENT_ID, row, changes)
        result = descriptor(await settings.load(db))
    return web.json_response(result)


routes = [web.get(shared.API + '/return-channels', read), web.patch(shared.API + '/return-channels', save)]
