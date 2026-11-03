"""One pure Members row computation at a time, away from the HTTP event loop."""

import asyncio
from aiohttp import web

KEY = web.AppKey("member_row_work", object)


class RowWork:
    def __init__(self):
        self.gate = asyncio.Semaphore(1)
        self.active = set()
        self.closing = False

    async def run(self, function, *values):
        if self.closing:
            raise RuntimeError("Member read is shutting down")
        await self.gate.acquire()
        if self.closing:
            self.gate.release()
            raise RuntimeError("Member read is shutting down")
        # Only private request snapshots enter this thread: no request, client,
        # cursor, storage, transport or mutation callback is supplied.
        try:
            work = asyncio.create_task(asyncio.to_thread(function, *values))
        except BaseException:
            self.gate.release()
            raise
        self.active.add(work)

        def finished(task):
            self.active.discard(task)
            self.gate.release()
            if not task.cancelled():
                task.exception()

        work.add_done_callback(finished)
        # Cancelling an HTTP reader cannot release the gate while its pure,
        # bounded computation is still finishing, or multiply worker threads.
        return await asyncio.shield(work)

    async def close(self):
        self.closing = True
        if self.active:
            await asyncio.gather(*self.active, return_exceptions=True)


def install(app):
    app[KEY] = RowWork()

    async def cleanup(app):
        await app[KEY].close()

    app.on_cleanup.append(cleanup)


async def run(request, function, *values):
    app = getattr(request, "app", None)
    if app is None:  # Pure unit callers without an HTTP application.
        return await asyncio.to_thread(function, *values)
    worker = app.get(KEY)
    if worker is None:  # Minimal isolated fixture applications.
        worker = RowWork()
        app[KEY] = worker
    return await worker.run(function, *values)
