"""Bounded raw directory reads only; authorization is always evaluated live."""

import asyncio
from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import time
from aiohttp import web

KEY = web.AppKey("members_directory_reads", object)
METADATA = web.RequestKey("members_directory_metadata", dict)
TTL = 60
PATH = "/api/cwl/manage/members/overview"


@dataclass
class Read:
    value: dict
    captured_at: datetime
    cached: bool
    generation: int

    def metadata(self):
        return dict(
            cached=self.cached,
            checked_at=self.captured_at.isoformat(),
            max_age_seconds=TTL,
        )


@dataclass
class Pending:
    generation: int
    task: object = None
    readers: int = 0


class DirectoryCache:
    def __init__(self, *, clock=time.monotonic):
        self.clock = clock
        self.generation = 0
        self.value = None
        self.loaded = float("-inf")
        self.captured_at = None
        self.pending = None
        self.receipts = OrderedDict()

    def invalidate(self):
        self.generation += 1
        self.value = None
        self.pending = None

    async def read(self, fetch, *, force=False):
        if (
            not force
            and self.value is not None
            and 0 <= self.clock() - self.loaded < TTL
        ):
            return Read(deepcopy(self.value), self.captured_at, True, self.generation)
        entry = self.pending
        if entry is None or entry.task.done():
            entry = Pending(self.generation)
            self.pending = entry

            async def load():
                started = self.clock()
                stamp = datetime.now(timezone.utc)
                value = await fetch()
                if self.generation == entry.generation and self.pending is entry:
                    self.value, self.loaded, self.captured_at = (
                        deepcopy(value),
                        started,
                        stamp,
                    )
                return value, stamp

            entry.task = asyncio.create_task(load(), name="members-directory-read")

            def finished(task):
                if not task.cancelled():
                    task.exception()  # Retrieve errors if the reader disconnected.
                if self.pending is entry:
                    self.pending = None

            entry.task.add_done_callback(finished)
        entry.readers += 1
        try:
            value, stamp = await asyncio.shield(entry.task)
            return Read(deepcopy(value), stamp, False, entry.generation)
        finally:
            entry.readers -= 1
            if not entry.readers and not entry.task.done():
                if self.pending is entry:
                    self.pending = None
                entry.task.cancel()  # No orphaned fetch after all HTTP readers leave.

    def observe(self, key, version):
        if self.receipts.get(key) == version:
            return
        self.receipts[key] = version
        self.receipts.move_to_end(key)
        while len(self.receipts) > 128:
            self.receipts.popitem(last=False)
        self.invalidate()


def eligible(request):
    return (
        getattr(request, "method", None) == "GET"
        and getattr(request, "path", None) == PATH
    )


def state(app):
    if KEY not in app:
        app[KEY] = DirectoryCache()
    return app[KEY]


def invalidate(app):
    cache = app.get(KEY)
    if cache is not None:
        cache.invalidate()


def observe_job(app, row):
    cache = app.get(KEY)
    if (
        cache is not None
        and row.get("section") in {"roles", "member_profiles"}
        and row.get("status") in {"done", "error", "uncertain"}
    ):
        cache.observe("job:" + row["_id"], row["status"])


def observe_run(app, run, children):
    cache = app.get(KEY)
    done = sum(
        child.get("status") in {"done", "error", "uncertain"} for child in children
    )
    if cache is not None and done:
        cache.observe("run:" + run["_id"], done)
