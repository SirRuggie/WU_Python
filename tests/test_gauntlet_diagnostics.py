import asyncio
import logging
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from utils.gauntlet_diagnostics import click_trace, observed, event


def interaction(identity=1, action='familyparticulars_acknowledge'):
    return SimpleNamespace(id=identity, custom_id=action+':private-state', guild_id=10,
        channel_id=20, message=SimpleNamespace(id=30), user=SimpleNamespace(id=40),
        created_at=datetime.now(timezone.utc), token='secret-token')


def test_trace_records_timing_without_tokens_or_payloads(caplog):
    caplog.set_level(logging.INFO, logger='utils.gauntlet_diagnostics')
    async def run():
        with click_trace(interaction()):
            await observed('acknowledgement', AsyncMock())
            await observed('role_assignment', AsyncMock())
            await observed('reply', AsyncMock(), content='private-message')
    asyncio.run(run())
    for stage in ('received','acknowledgement_succeeded','role_assignment_succeeded','reply_succeeded','finished'):
        assert stage in caplog.text
    assert 'interaction_age_ms' in caplog.text and 'duration_ms' in caplog.text
    assert 'secret-token' not in caplog.text and 'private-message' not in caplog.text
    assert 'private-state' not in caplog.text


def test_failure_is_logged_and_reraised_without_retry(caplog):
    caplog.set_level(logging.INFO, logger='utils.gauntlet_diagnostics')
    operation = AsyncMock(side_effect=RuntimeError('secret-token-in-http-error'))
    async def run():
        with click_trace(interaction()):
            with pytest.raises(RuntimeError):
                await observed('reply', operation)
    asyncio.run(run())
    operation.assert_awaited_once()
    assert 'reply_failed' in caplog.text and 'RuntimeError' in caplog.text
    assert 'reply_succeeded' not in caplog.text and 'secret-token' not in caplog.text


def test_other_actions_are_not_logged_and_context_is_cleared(caplog):
    caplog.set_level(logging.INFO, logger='utils.gauntlet_diagnostics')
    async def run():
        with click_trace(interaction(action='unrelated_action')):
            await observed('reply', AsyncMock())
        event('outside')
    asyncio.run(run())
    assert not caplog.records


def test_concurrent_clicks_keep_their_own_identifiers(caplog):
    caplog.set_level(logging.INFO, logger='utils.gauntlet_diagnostics')
    async def one(identity):
        with click_trace(interaction(identity)):
            await asyncio.sleep(0)
            event('marker', expected_id=str(identity))
    async def run():
        await asyncio.gather(one(1),one(2))
    asyncio.run(run())
    markers=[r.args for r in caplog.records if r.args['stage']=='marker']
    assert len(markers)==2
    assert all(m['interaction_id']==m['expected_id'] for m in markers)
