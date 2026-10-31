"""Resolve new image destinations from the confirmed announcement, not old settings."""
from aiohttp import web
from .manage_bridge import _mongo, _required_binding, GUILD_ID
from utils.cwl_web_bridge import get_roster_send_status
from utils.cwl_roster_image_store import RosterImageStore


async def new_post_destination(request, sid, pool):
    storage = RosterImageStore(request.app['store'])
    sequence = storage.pool_sequence(sid, pool)
    if sequence and sequence['status'] != 'complete':
        raise web.HTTPConflict(text='Finish or resume the announcement image sequence first')
    cycle = _required_binding(request, sid)
    async with _mongo(request) as mongo:
        status = await get_roster_send_status(mongo, GUILD_ID, cycle, pool)
        if not status or status.get('status') != 'sent':
            raise web.HTTPConflict(text='Send the roster announcement first; its images follow automatically')
        # The saved receipt owns the destination even if later campaign settings change.
        receipt = status.get('receipt') or {}
        channel = str(receipt.get('channel_id') or '')
        import re
        if not re.fullmatch(r'\d{15,22}', channel):
            raise web.HTTPConflict(text='The announcement has no saved destination receipt')
        return channel
