"""ID-only timings for private setup interactions and their remote reads."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import inspect
import logging
from time import perf_counter

log = logging.getLogger(__name__)
_click = ContextVar("warrior_click", default=None)


@contextmanager
def span(operation, **ids):
    started = perf_counter()
    try:
        yield
    finally:
        log.info(
            "warrior timing operation=%s click=%s ids=%s elapsed_ms=%.2f",
            operation,
            _click.get(),
            ids,
            (perf_counter() - started) * 1000,
        )


async def read(operation, awaitable, **ids):
    with span(operation, **ids):
        return await awaitable


def click(fn):
    signature = inspect.signature(fn)

    @wraps(fn)
    async def measured(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        ctx = bound.arguments.get("ctx")
        interaction = getattr(ctx, "interaction", None)
        token = _click.set(str(getattr(interaction, "id", 0)))
        try:
            with span(
                fn.__name__,
                guild_id=int(getattr(ctx, "guild_id", 0) or 0),
                actor_id=int(getattr(getattr(ctx, "user", None), "id", 0)),
            ):
                return await fn(*args, **kwargs)
        finally:
            _click.reset(token)

    return measured
