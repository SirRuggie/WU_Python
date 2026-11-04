"""Authorization precedes raw snapshot ownership; cleanup precedes Mongo close."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from cwl_web import strikes, strike_activity_cache


def test_denied_activity_request_never_enters_handler_or_touches_cache():
    async def run():
        request = SimpleNamespace(app={}, query={'activity': 'true'}, method='GET')
        with patch.object(strikes.shared, 'require_manage', AsyncMock(side_effect=web.HTTPForbidden())), \
             patch.object(strikes, 'activity_accounts', AsyncMock()) as handler:
            with pytest.raises(web.HTTPForbidden):
                await strikes.accounts(request)
            handler.assert_not_awaited()
            assert strike_activity_cache.KEY not in request.app
    asyncio.run(run())


def test_app_cleanup_drains_refresh_before_mongo_is_closed():
    async def run():
        app = web.Application()
        stopped = asyncio.Event()
        started = asyncio.Event()
        async def mongo(app):
            yield
            assert stopped.is_set()
        async def load():
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()
        app.cleanup_ctx.append(mongo)
        app.cleanup_ctx.append(strike_activity_cache.lifecycle)
        cache = strike_activity_cache.snapshots(app)
        app.freeze()
        await app.startup()
        await cache.get(123, load)
        await started.wait()
        await app.cleanup()
        assert cache.closed and stopped.is_set()
    asyncio.run(run())
