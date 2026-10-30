import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from cwl_web import war_reminders as api
from utils.war_reminders import copied_settings, settings
from utils.war_reminder_store import SettingsConflict


def test_copy_never_copies_channel_and_targets_without_channel_stay_off():
    source = settings({'enabled': True, 'channel_id': '123456789012345678', 'minutes': [30]})
    target = settings({'channel_id': '987654321098765432', 'minutes': [60]})
    result = copied_settings(source, target, ['enabled', 'minutes'])
    assert result['channel_id'] == target['channel_id'] and result['enabled']
    assert result['minutes'] == [30] and target['minutes'] == [60]
    missing = copied_settings(source, None, ['enabled', 'minutes'])
    assert missing['channel_id'] == '' and missing['enabled'] is False
    with pytest.raises(ValueError): copied_settings(source, target, ['channel_id'])


@pytest.fixture
def setup(monkeypatch):
    source = settings({'minutes': [30]})
    before = settings({'channel_id': '987654321098765432'})
    store = NS(
        clan=AsyncMock(side_effect=lambda tag: {'tag': tag, 'name': tag}),
        get_settings=AsyncMock(side_effect=lambda tag: source if tag == '#P0LY' else before),
        save_settings=AsyncMock(),
    )
    @asynccontextmanager
    async def mongo(request): yield NS()
    monkeypatch.setattr(api, 'mongo', mongo)
    monkeypatch.setattr(api, 'WarReminderStore', lambda db: store)
    monkeypatch.setattr(api, 'require_manage', AsyncMock(return_value={'user_id': 'staff', 'name': 'Jamie'}))
    monkeypatch.setattr(api, 'channel', AsyncMock())
    body = {'revision': api.revision(source), 'fields': ['minutes'], 'targets': [
        {'tag': '#P2Y', 'revision': api.revision(before)},
        {'tag': '#P8Y', 'revision': api.revision(before)},
    ]}
    request = NS(match_info={'tag': '#P0LY'}, json=AsyncMock(return_value=body))
    return request, body, store


def test_each_target_uses_own_version_and_records_history_context(setup):
    request, body, store = setup
    body['targets'][0]['revision'] = 'stale'
    result = json.loads(asyncio.run(api.copy_settings(request)).body)['results']
    assert [r['ok'] for r in result] == [False, True]
    assert store.save_settings.await_count == 1
    args = store.save_settings.await_args
    assert args.args[0] == '#P8Y' and args.args[2]['minutes'] == [30]
    assert args.args[2]['channel_id'] == '987654321098765432'
    assert args.kwargs['history_context'][1]['name'] == 'Jamie'


def test_concurrent_target_cas_failure_does_not_block_other_targets(setup):
    request, body, store = setup
    store.save_settings.side_effect = [SettingsConflict(), None]
    result = json.loads(asyncio.run(api.copy_settings(request)).body)['results']
    assert [r['ok'] for r in result] == [False, True]
    assert store.save_settings.await_count == 2


def test_source_change_aborts_before_any_target_write(setup):
    request, body, store = setup
    body['revision'] = 'stale'
    with pytest.raises(web.HTTPConflict): asyncio.run(api.copy_settings(request))
    store.save_settings.assert_not_awaited()


def test_denied_before_read_or_write(setup, monkeypatch):
    request, body, store = setup
    monkeypatch.setattr(api, 'require_manage', AsyncMock(side_effect=web.HTTPForbidden()))
    with pytest.raises(web.HTTPForbidden): asyncio.run(api.copy_settings(request))
    request.json.assert_not_awaited()
    store.save_settings.assert_not_awaited()


@pytest.mark.parametrize('targets', [[], [{'tag': '#P2Y'}], [{'tag': '#P0LY', 'revision': 'x'}], [{'tag': '#P2Y', 'revision': 'x'}] * 2])
def test_malformed_or_duplicate_targets_write_nothing(setup, targets):
    request, body, store = setup
    body['targets'] = targets
    with pytest.raises(web.HTTPBadRequest): asyncio.run(api.copy_settings(request))
    store.save_settings.assert_not_awaited()
