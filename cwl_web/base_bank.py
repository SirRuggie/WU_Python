"""Authenticated member adapter for the public Base bank read model."""

import asyncio
import time
from aiohttp import web
from utils.base_bank import read_base_bank, FWA_TH_LEVELS
from .server_management import mongo


async def read(request):
    from .app import _require

    _require(request)
    level = request.query.get("level")
    if set(request.query) - {"level"} or (
        level is not None and level not in FWA_TH_LEVELS
    ):
        raise web.HTTPBadRequest(text="Choose an available base level")
    cache = request.app.get("base_bank_cache")
    if cache is None or time.monotonic() >= cache[0]:
        try:
            async with asyncio.timeout(8):
                async with mongo(request) as client:
                    rows, details = await read_base_bank(client)
        except TimeoutError:
            raise web.HTTPServiceUnavailable(
                text="Base bank is unavailable. Try again shortly."
            )
        cache = (time.monotonic() + 30, rows, details)
        request.app["base_bank_cache"] = cache
    if level is not None:
        if level not in cache[2]:
            raise web.HTTPNotFound(text="This base is not available")
        result = dict(key=level, **cache[2][level])
    else:
        result = {"bases": cache[1]}
    return web.json_response(result, headers={"Cache-Control": "private, no-store"})


def routes():
    return [web.get("/api/cwl/bases", read)]
