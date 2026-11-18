"""In-process periodic job observation; no persistence, endpoint or delivery retry."""

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import math
import re
import time


_log = logging.getLogger(__name__)
_ERROR_WINDOW = 300.0
_ERROR_LIMIT = 256
_errors = OrderedDict()
_jobs = {}


@dataclass
class _Job:
    started: float
    interval: float
    last_success: datetime | None = None
    last_success_monotonic: float | None = None
    warned: bool = False
    running: bool = False
    last_error: str | None = None


def log_failure(logger, name, error):
    """Keep stack frames, redact exception values, and bound repeated signatures.

    Exception text can contain provider payloads, URLs or credentials. A fresh
    exception carrying only the error class avoids logging those values or the
    original exception chain; the original traceback still identifies every
    failing code frame. No locals are captured.
    """
    now = time.monotonic()
    tb = error.__traceback__
    last = tb
    while last is not None and last.tb_next is not None:
        last = last.tb_next
    location = (last.tb_frame.f_code.co_filename, last.tb_lineno) if last else None
    kind = type(error).__name__
    key = (name, type(error).__module__, type(error).__qualname__, location)
    previous = _errors.get(key)
    if previous is None or now - previous[0] >= _ERROR_WINDOW or now < previous[0]:
        _errors[key] = (now, False)
        _errors.move_to_end(key)
        while len(_errors) > _ERROR_LIMIT:
            _errors.popitem(last=False)
        safe = Exception(kind)
        safe.__suppress_context__ = True
        logger.exception("Background job failed job=%s error=%s", name, kind,
                         exc_info=(Exception, safe, tb))
    elif not previous[1]:
        _errors[key] = (previous[0], True)
        logger.warning("Background job failure repeated job=%s error=%s; traceback rate-limited", name, kind)


def _stale(job, now):
    anchor = job.last_success_monotonic
    if anchor is None:
        anchor = job.started
    # Monotonic time is used for health; a wall-clock adjustment is irrelevant.
    return now >= anchor and now - anchor >= 3 * job.interval


def _warn(name, job, logger):
    if not job.warned and _stale(job, time.monotonic()):
        job.warned = True
        logger.warning("Background job has no success for three intervals job=%s", name)


def job_health():
    """Return a detached process-local observation, not a public health API."""
    now = time.monotonic()
    return {name: {"last_success": job.last_success, "running": job.running,
                   "stale": _stale(job, now), "last_error": job.last_error}
            for name, job in _jobs.items()}


async def cancel_and_wait(tasks):
    """Cancel owned tasks once and finish their cleanup despite another cancel."""
    tasks = tuple(tasks)
    for task in tasks:
        if not task.done():
            task.cancel()
    drained = asyncio.gather(*tasks, return_exceptions=True)
    cancelled = False
    while not drained.done():
        try:
            await asyncio.shield(drained)
        except asyncio.CancelledError:
            cancelled = True
    results = drained.result()
    if cancelled:
        raise asyncio.CancelledError()
    return results


async def run_periodic(name, job, interval, *, once=False, logger=None):
    """Run serialized iterations, immediate first run then completion + interval.

    ``once=True`` observes exactly one iteration under an existing scheduler;
    it creates no second cadence or admission path. False means incomplete work
    and never advances last_success. Exceptions are observed, not replayed here;
    existing durable owners decide whether any later iteration may send again.
    """
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", name):
        raise ValueError("A stable internal job name is required")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or not math.isfinite(interval) or interval <= 0:
        raise ValueError("A finite positive interval is required")
    logger = logger or _log
    state = _jobs.setdefault(name, _Job(time.monotonic(), float(interval)))
    if state.running:
        raise RuntimeError("Periodic job already has an owner")
    state.interval = float(interval)
    state.running = True

    async def watch():
        while True:
            await asyncio.sleep(interval)
            _warn(name, state, logger)

    monitor = asyncio.create_task(watch(), name="health:" + name)
    try:
        while True:
            _warn(name, state, logger)
            try:
                result = await job()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                state.last_error = type(error).__name__
                log_failure(logger, name, error)
            else:
                if result is not False:
                    state.last_success = datetime.now(timezone.utc)
                    state.last_success_monotonic = time.monotonic()
                    state.last_error = None
                    if state.warned:
                        logger.info("Background job recovered job=%s", name)
                        state.warned = False
                    for key in list(_errors):
                        if key[0] == name or key[0].startswith(name + "."):
                            _errors.pop(key, None)
                else:
                    state.last_error = "Incomplete"
            if once:
                return result if state.last_error is None else False
            await asyncio.sleep(interval)
    finally:
        try:
            await cancel_and_wait([monitor])
        finally:
            state.running = False
