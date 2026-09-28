"""Targeted, token-free lifecycle diagnostics for Gauntlet acknowledgements."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import logging
from time import perf_counter

ACTIONS = frozenset({
    'join_family_acknowledge', 'aboutus_acknowledge',
    'strikesystem_acknowledge', 'familyparticulars_acknowledge',
})
_log = logging.getLogger(__name__)
_trace = ContextVar('gauntlet_click_trace', default=None)


def event(stage, **fields):
    trace = _trace.get()
    if trace is None:
        return
    started, metadata = trace
    _log.info('gauntlet_click %s', {
        **metadata, 'stage': stage,
        'elapsed_ms': round((perf_counter() - started) * 1000, 1), **fields,
    })


@contextmanager
def click_trace(interaction):
    action = (getattr(interaction, 'custom_id', '') or '').partition(':')[0]
    if action not in ACTIONS:
        yield
        return
    metadata = {
        'interaction_id': str(interaction.id), 'action': action,
        'guild_id': str(interaction.guild_id), 'channel_id': str(interaction.channel_id),
        'message_id': str(getattr(getattr(interaction, 'message', None), 'id', '')),
        'user_id': str(interaction.user.id),
    }
    token = _trace.set((perf_counter(), metadata))
    try:
        created = getattr(interaction, 'created_at', None)
        age = round((datetime.now(timezone.utc) - created).total_seconds() * 1000, 1) if isinstance(created, datetime) else None
        event('received', interaction_age_ms=age)
        yield
    finally:
        event('finished')
        _trace.reset(token)


async def observed(stage, operation, *args, **kwargs):
    if _trace.get() is None:
        return await operation(*args, **kwargs)
    started = perf_counter()
    event(stage + '_started')
    try:
        result = await operation(*args, **kwargs)
    except BaseException as exc:
        # Never include exception text: HTTP errors may contain request tokens.
        event(stage + '_failed', duration_ms=round((perf_counter() - started) * 1000, 1),
              error_type=type(exc).__name__, discord_code=getattr(exc, 'code', None))
        raise
    event(stage + '_succeeded', duration_ms=round((perf_counter() - started) * 1000, 1))
    return result
