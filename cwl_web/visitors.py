"""Best-effort authenticated visit counting, isolated from durable dashboard data."""
import asyncio
import logging
import time
from datetime import datetime, timezone
from contextlib import suppress
from pathlib import Path

from aiohttp import web
from utils.dashboard_visit_store import VisitStore, LOCAL_TIMEZONE

LOG = logging.getLogger(__name__)
MAX_DAILY_CACHE = 100_000


class VisitCounter:
    """Event-loop-owned bounded cache; only first daily loads enter a worker."""

    def __init__(self, store):
        self.store = store
        self.day = None
        self.seen = set()
        self.pending = set()
        self.last_error = float('-inf')

    def log_failure(self):
        now = time.monotonic()
        if now - self.last_error >= 60:
            self.last_error = now
            LOG.exception('Could not update daily dashboard visits')

    async def record(self, user_id, at, is_staff):
        day = at.astimezone(LOCAL_TIMEZONE).date()
        if day != self.day:
            self.day, self.seen = day, set()
        key = (user_id, day)
        if key in self.seen or key in self.pending:
            return
        # At capacity, undercount instead of accumulating unbounded work/memory.
        if len(self.seen) + len(self.pending) >= MAX_DAILY_CACHE:
            return
        self.pending.add(key)
        try:
            classification = is_staff() if callable(is_staff) else is_staff
            await asyncio.to_thread(self.store.record_session, user_id, at=at, is_staff=classification)
            if day == self.day:
                self.seen.add(key)
        except Exception:
            self.log_failure()
        finally:
            self.pending.discard(key)


async def record(request, session):
    from .access_control import request_scopes
    from .app import _owner
    if session.get('is_bot'):
        return
    counter = request.app['visit_counter']
    try:
        await counter.record(
            session['user_id'], datetime.now(timezone.utc),
            lambda: _owner(session) or bool(request_scopes(request, session['user_id'])),
        )
    except Exception:
        counter.log_failure()


async def summary(request):
    from .app import _require
    _require(request, 'owner')
    today = datetime.now(timezone.utc).astimezone(LOCAL_TIMEZONE).date()
    return web.json_response(await asyncio.to_thread(request.app['visit_store'].aggregates, today))


async def lifecycle(app):
    async def cleanup():
        while True:
            try:
                today = datetime.now(timezone.utc).astimezone(LOCAL_TIMEZONE).date()
                await asyncio.to_thread(app['visit_store'].prune, today)
            except Exception:
                app['visit_counter'].log_failure()
            await asyncio.sleep(3600)
    task = asyncio.create_task(cleanup())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def setup(app):
    # MongoDashboardState.restore replaces only the exact main path and its journals;
    # encode serializes that connection only. This sibling is outside both paths.
    dashboard_path = Path(app['store'].path)
    app['visit_store'] = VisitStore(dashboard_path.with_name(dashboard_path.name + '.visits.sqlite3'))
    app['visit_counter'] = VisitCounter(app['visit_store'])
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/api/cwl/manage/visitors', summary)
