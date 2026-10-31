"""Authenticated visit adaptation and owner-only aggregate reporting."""
import asyncio
import logging
from datetime import datetime, timezone
from contextlib import suppress

from aiohttp import web
from utils.dashboard_visit_store import VisitStore, LOCAL_TIMEZONE

LOG = logging.getLogger(__name__)


def record(request, session):
    from .access_control import request_scopes
    from .app import _owner
    try:
        request.app['visit_store'].record_session(
            session['user_id'], at=datetime.now(timezone.utc),
            is_staff=_owner(session) or bool(request_scopes(request, session['user_id'])),
        )
    except Exception:
        # Counting must not prevent an otherwise valid sign-in/session response.
        LOG.exception('Could not record daily dashboard visit')


async def summary(request):
    from .app import _require
    _require(request, 'owner')
    today = datetime.now(timezone.utc).astimezone(LOCAL_TIMEZONE).date()
    return web.json_response(request.app['visit_store'].aggregates(today))


async def lifecycle(app):
    async def cleanup():
        while True:
            try:
                app['visit_store'].prune(datetime.now(timezone.utc).astimezone(LOCAL_TIMEZONE).date())
            except Exception:
                LOG.exception('Could not prune expired dashboard visits')
            await asyncio.sleep(3600)
    task = asyncio.create_task(cleanup())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def setup(app):
    app['visit_store'] = VisitStore(app['store'])
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/api/cwl/manage/visitors', summary)
