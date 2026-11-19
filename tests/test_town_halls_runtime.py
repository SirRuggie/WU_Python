"""Fixture-only cadence and authorization checks; no bot or DB connections."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
import pytest
import asyncio
from functools import wraps

def runs_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run

from utils import manage_operations_runtime as runtime, town_halls
from utils.manage_poll_cache import state_for
from utils import manage_web_worker as worker

GUILD = 644963518025826315

@runs_async
async def test_refresh_cadence_is_five_minutes_including_failures():
    mongo = object()
    with patch.object(town_halls, 'refresh_snapshot', AsyncMock(return_value=False)) as refresh, patch.object(runtime.time, 'monotonic', return_value=1000):
        assert not await runtime.refresh_town_halls_cache(mongo)
        assert not await runtime.refresh_town_halls_cache(mongo)
        refresh.assert_awaited_once_with(mongo, GUILD, log_failure=True, expected_revision=None)
    with patch.object(town_halls, 'refresh_snapshot', AsyncMock(return_value=True)) as refresh, patch.object(runtime.time, 'monotonic', return_value=1300):
        assert await runtime.refresh_town_halls_cache(mongo)
        refresh.assert_awaited_once()

@runs_async
async def test_forced_startup_attempt_logs_one_error_not_warning(caplog):
    mongo = object()
    state_for(mongo).town_halls_at = 999999
    with patch.object(town_halls, 'refresh_snapshot', AsyncMock(return_value=False)) as refresh:
        assert not await runtime.refresh_town_halls_cache(mongo, force=True, startup=True)
    refresh.assert_awaited_once_with(mongo, GUILD, log_failure=False, expected_revision=None)
    assert len(caplog.records) == 1
    assert caplog.records[0].levelname == 'ERROR'
    assert 'Town Halls not migrated' in caplog.text


def row(**changes):
    return dict(guild_id=GUILD, section='town_halls', action='refresh', values={}, revision=7, **changes)

@runs_async
@pytest.mark.parametrize('key,value', [('guild_id', 123), ('section', 'roles'), ('action', 'save'), ('values', {'emoji': 'bad'}), ('revision', True), ('revision', '7'), ('revision', -1)])
async def test_bad_request_never_reads_registry(key, value):
    request = row(); request[key] = value
    with patch.object(town_halls, 'load', AsyncMock()) as load:
        with pytest.raises(ValueError):
            await runtime.apply_town_halls_refresh(object(), request, {'user_id':'123'})
        load.assert_not_awaited()

@runs_async
async def test_revoked_permission_never_reads_registry():
    with patch('utils.dashboard_access.dashboard_allowed', AsyncMock(return_value=False)), patch.object(town_halls, 'load', AsyncMock()) as load:
        with pytest.raises(ValueError, match='access changed'):
            await runtime.apply_town_halls_refresh(object(), row(), {'user_id':'123'})
        load.assert_not_awaited()

@runs_async
@pytest.mark.parametrize('document', [None, {'revision':8}])
async def test_missing_or_stale_revision_never_refreshes(document):
    with patch('utils.dashboard_access.dashboard_allowed', AsyncMock(return_value=True)), patch.object(town_halls, 'load', AsyncMock(return_value=document)), patch.object(runtime, 'refresh_town_halls_cache', AsyncMock()) as refresh:
        with pytest.raises(ValueError):
            await runtime.apply_town_halls_refresh(object(), row(), {'user_id':'123'})
        refresh.assert_not_awaited()

@runs_async
async def test_worker_dispatch_refreshes_without_discord_or_writes():
    mongo = SimpleNamespace(bot_config=SimpleNamespace(insert_one=AsyncMock(), update_one=AsyncMock()))
    actor = {'user_id':'123'}
    with patch('utils.dashboard_access.dashboard_allowed', AsyncMock(return_value=True)) as allowed, patch.object(town_halls, 'load', AsyncMock(return_value={'revision':7})), patch.object(runtime, 'refresh_town_halls_cache', AsyncMock(return_value=True)) as refresh:
        result = await worker.dispatch(None, mongo, row(), SimpleNamespace(dashboard_actor=actor))
    allowed.assert_awaited_once_with(actor, 'fwa_weight', mongo, write=True)
    refresh.assert_awaited_once_with(mongo, force=True, expected_revision=7)
    assert result['revision'] == 7
    mongo.bot_config.insert_one.assert_not_awaited()
    mongo.bot_config.update_one.assert_not_awaited()


@runs_async
async def test_concurrent_registry_edit_cannot_produce_success_for_prior_revision(monkeypatch):
    from copy import deepcopy
    from test_town_halls import registry
    newer = registry(); newer['_id'] = str(GUILD); newer['revision'] = 8
    older = deepcopy(newer); older['revision'] = 7
    monkeypatch.setattr(town_halls, '_snapshot', deepcopy(newer))
    monkeypatch.setattr(town_halls, '_snapshot_guild', str(GUILD))
    with patch('utils.dashboard_access.dashboard_allowed', AsyncMock(return_value=True)), patch.object(town_halls, 'load', AsyncMock(side_effect=[older, newer])):
        with pytest.raises(ValueError, match='could not refresh'):
            await runtime.apply_town_halls_refresh(object(), row(), {'user_id':'123'})
    assert town_halls.snapshot(GUILD) == newer
