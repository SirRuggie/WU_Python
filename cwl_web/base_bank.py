"""Authenticated member adapter for the public Base bank read model."""

import asyncio
import time
from aiohttp import web
from utils.base_bank import read_base_bank
from utils.town_halls import TownHallsMissing, MISSING_MESSAGE, parse_variant_value, variant_label, MERGED_DEFENSES_FROM
from .server_management import mongo

GENERATION = web.AppKey('base_bank_cache_generation', int)


def invalidate(app):
    """Invalidate completed and in-flight reads after an explicit minimum Save."""
    app[GENERATION] = app.get(GENERATION, 0) + 1
    app.pop('base_bank_cache', None)


async def read(request):
    from .app import _require
    from .server_membership import BASE_BANK_JOIN, CHECK_UNAVAILABLE, server_member_status

    session = _require(request)
    member = await server_member_status(request, session["user_id"])
    if member is False:
        raise web.HTTPForbidden(text=BASE_BANK_JOIN)
    if member is None:
        raise web.HTTPServiceUnavailable(text=CHECK_UNAVAILABLE)
    level = request.query.get("level")
    if set(request.query) - {"level"}:
        raise web.HTTPBadRequest(text="Select an available base level")
    if level is not None:
        try:
            parse_variant_value(level)
        except ValueError:
            raise web.HTTPBadRequest(text="Select an available base level") from None
    cache = request.app.get("base_bank_cache")
    if cache is None or time.monotonic() >= cache[0]:
        try:
            async with asyncio.timeout(8):
                for _attempt in range(2):
                    generation = request.app.get(GENERATION, 0)
                    async with mongo(request) as client:
                        rows, details = await read_base_bank(client)
                    rows = [dict(row, variant_label=variant_label(row['town_hall'], row['variant'].replace('-', '_')))
                            for row in rows
                            if row['town_hall'] >= MERGED_DEFENSES_FROM or row['variant'] == 'merged']
                    details = {row['key']: details[row['key']] for row in rows}
                    if request.app.get(GENERATION, 0) != generation:
                        continue
                    cache = (time.monotonic() + 30, rows, details)
                    request.app['base_bank_cache'] = cache
                    break
                else:
                    raise web.HTTPServiceUnavailable(
                        text='Base bank settings changed. Try again.'
                    )
        except TownHallsMissing:
            raise web.HTTPServiceUnavailable(text=MISSING_MESSAGE) from None
        except TimeoutError:
            raise web.HTTPServiceUnavailable(
                text="Base bank is unavailable. Try again later."
            )
    if level is not None:
        if level not in cache[2]:
            raise web.HTTPNotFound(text="This base is not available")
        result = dict(key=level, **cache[2][level])
    else:
        result = {"bases": cache[1]}
    return web.json_response(result, headers={"Cache-Control": "private, no-store"})


def routes():
    return [web.get("/api/cwl/bases", read)]
