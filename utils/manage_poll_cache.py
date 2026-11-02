"""Loop-local management cadence, never authorization or durable receipts."""

import asyncio
from contextlib import contextmanager
import time
from dataclasses import dataclass, field
import weakref


@dataclass
class PollState:
    heartbeat_at: float = float("-inf")
    heartbeat_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    band_at: float = float("-inf")
    band_values: dict | None = None
    images_at: float = float("-inf")
    images_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    activation_at: float = float("-inf")
    sweep_at: float = float("-inf")
    ready_at: float = float("-inf")
    ready: object = None


_STATES = weakref.WeakKeyDictionary()


def state_for(mongo):
    loop = asyncio.get_running_loop()
    prior = _STATES.get(loop)
    if prior is None or prior[0] is not mongo:
        prior = (mongo, PollState())
        _STATES[loop] = prior
    return prior[1]


@contextmanager
def timed_step(logger, stage):
    started = time.perf_counter()
    try:
        yield
    finally:
        elapsed = 1000 * (time.perf_counter() - started)
        write = (
            logger.info
            if elapsed >= 1000
            else logger.debug
        )
        write("Web worker timing stage=%s elapsed_ms=%.2f", stage, elapsed)
