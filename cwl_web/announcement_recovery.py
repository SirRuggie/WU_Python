"""Read-only verification for an explicitly reviewed deleted announcement."""
import re

from aiohttp import web

from .server_management import DiscordItemNotFound, discord, GUILD_ID


def receipt_target(receipt):
    channel = str((receipt or {}).get('channel_id') or '')
    message = str((receipt or {}).get('message_id') or '')
    if not all(re.fullmatch(r'\d{15,22}', value) for value in (channel, message)):
        raise web.HTTPConflict(text='No verifiable announcement message receipt is available')
    return channel, message


async def deleted_in_discord(request, receipt):
    """Only Discord's unknown-message response is proof of deletion."""
    channel, message = receipt_target(receipt)
    destination = await discord(request, 'GET', f'/channels/{channel}')
    if str(destination.get('guild_id')) != str(GUILD_ID) or destination.get('type') not in (0, 5):
        raise web.HTTPForbidden(text='The announcement destination is unavailable in this server')
    try:
        await discord(request, 'GET', f'/channels/{channel}/messages/{message}', roster_delivery=True)
    except DiscordItemNotFound as exc:
        if exc.discord_code == 10008:
            return True
        raise
    return False


async def check(request):
    from .app import _sid
    from .manage_bridge import _mongo, _pool, _required_binding
    from .roster_image_posts import staff
    from utils.cwl_web_bridge import get_roster_send_status
    staff(request, send=True)
    sid = _sid(request)
    cycle, pool = _required_binding(request, sid), _pool(request)
    async with _mongo(request) as mongo:
        before = await get_roster_send_status(mongo, GUILD_ID, cycle, pool)
        if not before or before.get('status') != 'sent':
            raise web.HTTPConflict(text='The announcement status changed; refresh before reviewing')
        receipt = before.get('receipt')
        channel, message = receipt_target(receipt)
        deleted = await deleted_in_discord(request, receipt)
        after = await get_roster_send_status(mongo, GUILD_ID, cycle, pool)
        if not after or after.get('status') != 'sent' or receipt_target(after.get('receipt')) != (channel, message):
            raise web.HTTPConflict(text='The announcement receipt changed during the check; review again')
    return web.json_response({'deleted': deleted, 'channel_id': channel, 'message_id': message})


async def prepare_resend(request, mongo, *, sid, cycle, pool, body, actor, previous):
    """Apply the staff's explicit resend confirmation after a fresh Discord check."""
    from utils import cwl_campaign
    from utils.cwl_web_bridge import campaign_generation, reopen_deleted_request, get_roster_send_status
    from utils.cwl_roster_image_store import RosterImageStore, ImageConflict
    from .roster_sequence_review import _not_active
    if body.get('confirm_resend') is not True or not isinstance(body.get('deleted_message_id'), str):
        raise web.HTTPBadRequest(text='Confirm Send again: the announcement will ping its roles again')
    receipt = (previous or {}).get('receipt')
    channel, message = receipt_target(receipt)
    if message != body['deleted_message_id'] or (previous or {}).get('status') not in ('sent', 'failed'):
        raise web.HTTPConflict(text='The reviewed announcement changed; check it again')
    loaded = await cwl_campaign.load_campaign(mongo, GUILD_ID, cycle)
    configured = loaded['campaign']['messages']['roster']['variants'][pool].get('destination_channel_id')
    if campaign_generation(loaded) != body['generation'] or str(configured) != body['channel_id']:
        raise web.HTTPConflict(text='Announcement settings changed; review again')
    if not await deleted_in_discord(request, receipt):
        raise web.HTTPConflict(text='The announcement still exists; it cannot be sent again')
    storage = RosterImageStore(request.app['store'])
    _not_active(request, storage.pool_sequence(sid, pool))
    try:
        storage.archive_deleted_sequence(sid, pool, message, actor['user_id'])
        await reopen_deleted_request(mongo, guild_id=GUILD_ID, cycle=cycle, pool=pool,
                                     receipt=receipt, actor_id=actor['user_id'])
    except (ValueError, ImageConflict) as exc:
        raise web.HTTPConflict(text=str(exc)) from None
    return await get_roster_send_status(mongo, GUILD_ID, cycle, pool)
