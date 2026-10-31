"""Bounded cached adaptation of the public bulk account-link resolver."""
import asyncio
import time
from utils import recruit_links


async def account_owners(request, tags):
    wanted = tuple(sorted(set(tags)))
    state = request.app.setdefault('activity_link_cache', {'lock': asyncio.Lock()})
    async with state['lock']:
        if state.get('tags') == wanted and time.monotonic() < state.get('until', 0):
            return state['result']
        async with asyncio.timeout(8):
            result = await recruit_links.resolve_players(list(wanted))
        state.update(tags=wanted, result=result, until=time.monotonic()+60)
        return result
