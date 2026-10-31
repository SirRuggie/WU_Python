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
