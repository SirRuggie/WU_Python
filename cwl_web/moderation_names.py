"""Bounded current-member name lookup for authorized moderation history reads."""
import asyncio
import time
from collections import OrderedDict

from aiohttp import web

from .manage_roles import member_option
from .server_management import GUILD_ID, discord


async def resolve_names(request, ids):
    unique = {str(value) for value in ids if value and str(value).isascii()
              and str(value).isdigit() and 15 <= len(str(value)) <= 22}
    if not unique:
        return {}
    cache = request.app.setdefault('moderation_member_names', OrderedDict())
    gate = request.app.setdefault('moderation_name_gate', asyncio.Semaphore(3))

    async def lookup(uid):
        key = (GUILD_ID, uid)
        async with gate:
            cached = cache.get(key)
            if cached and cached[0] > time.monotonic():
                return uid, cached[1]
            try:
                member = await asyncio.wait_for(discord(
                    request, 'GET', f'/guilds/{GUILD_ID}/members/{uid}'), 3)
                if not isinstance(member, dict) or not isinstance(member.get('user'), dict) or str(member['user'].get('id')) != uid:
                    raise ValueError('Member identity unavailable')
                option = member_option(member)
                name = option.get('display_name')
                if not isinstance(name, str) or not name.strip() or name.strip().isdigit():
                    name = None
            except (web.HTTPException, TimeoutError, KeyError, TypeError, ValueError):
                name = None
            cache[key] = (time.monotonic() + (120 if name else 30), name)
            cache.move_to_end(key)
            while len(cache) > 256:
                cache.popitem(last=False)
            return uid, name

    tasks = [asyncio.create_task(lookup(uid)) for uid in sorted(unique)]
    try:
        done, _ = await asyncio.wait(tasks, timeout=3)
        return dict(task.result() for task in done)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
