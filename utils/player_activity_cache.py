"""Request-driven, process-local activity snapshots; never stores ledger core data."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time


@dataclass
class ActivityPayload:
    rows: list
    observations: list


@dataclass
class Snapshot:
    rows: list | None
    checked_at: datetime | None
    stale: bool
    refreshing: bool
    observations: list | None = None
    observations_checked_at: datetime | None = None


@dataclass
class _Entry:
    rows: list | None = None
    checked_at: datetime | None = None
    saved_at: float = 0
    retry_at: float = 0
    failed: bool = False
    task: asyncio.Task | None = None
    observations: list | None = None
    observations_started: float = 0
    observations_checked_at: datetime | None = None
    generation: int = 0


class ActivitySnapshots:
    """Call only after request authorization; loaders return unfiltered activity only.

    There is no timer. A request can start one bounded refresh per guild. Failed
    reads have a short request-driven cooldown and retain the last good value.
    """

    def __init__(self, *, timeout=12, clock=time.monotonic, wall_clock=None, logger=None):
        self.timeout = timeout
        self.clock = clock
        self.wall_clock = wall_clock or (lambda: datetime.now(timezone.utc))
        self.logger = logger or logging.getLogger(__name__)
        self.entries = {}
        self.closed = False

    async def get(self, guild_id, loader, *, wait=0, require_observations=False):
        if self.closed:
            raise RuntimeError('Activity snapshots are closed')
        entry = self.entries.setdefault(guild_id, _Entry())
        if entry.task is not None and entry.task.done():
            entry.task = None
        age = self.clock() - entry.saved_at
        observations_usable = entry.observations is not None and self.clock()-entry.observations_started <= 30
        needs_refresh = entry.rows is None or age > 30 or (require_observations and not observations_usable)
        if needs_refresh and entry.task is None and self.clock() >= entry.retry_at:
            entry.task = asyncio.create_task(self._refresh(entry, loader, entry.generation))
        # Shield shared refreshes from cancellation of an individual HTTP request.
        if entry.rows is None and wait and entry.task is not None:
            await asyncio.wait({entry.task}, timeout=wait)
        age = self.clock() - entry.saved_at
        usable = entry.rows is not None and age <= 600
        observations_usable = entry.observations is not None and self.clock()-entry.observations_started <= 30
        return Snapshot(deepcopy(entry.rows) if usable else None,
                        entry.checked_at if usable else None,
                        usable and age > 30, entry.task is not None,
                        deepcopy(entry.observations) if observations_usable else None,
                        entry.observations_checked_at if observations_usable else None)

    async def _refresh(self, entry, loader, generation):
        started, checked_at = self.clock(), self.wall_clock()
        try:
            rows = await asyncio.wait_for(loader(), timeout=self.timeout)
            observations = None
            if isinstance(rows, ActivityPayload):
                rows, observations = rows.rows, rows.observations
                if not isinstance(observations, list):
                    raise TypeError('Activity observations must be a list')
            if not isinstance(rows, list):
                raise TypeError('Activity snapshot loader must return a list')
            if generation != entry.generation or self.closed:
                return
            entry.rows = deepcopy(rows)
            entry.checked_at = self.wall_clock()
            entry.saved_at = self.clock()
            entry.retry_at = 0
            entry.failed = False
            entry.observations = deepcopy(observations)
            entry.observations_started = started
            entry.observations_checked_at = checked_at if observations is not None else None
        except asyncio.CancelledError:
            raise
        except Exception:
            if not entry.failed:
                self.logger.warning('Optional activity snapshot refresh failed', exc_info=True)
            entry.failed = True
            entry.retry_at = self.clock() + 30
        finally:
            entry.task = None

    def invalidate_observations(self, guild_id):
        entry = self.entries.get(guild_id)
        if entry is not None:
            entry.generation += 1
            entry.observations = None
            entry.observations_checked_at = None
            entry.retry_at = 0
            if entry.task is not None:
                entry.task.cancel()

    async def close(self):
        self.closed = True
        tasks = [entry.task for entry in self.entries.values() if entry.task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.entries.clear()
