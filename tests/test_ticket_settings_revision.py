"""Isolated settings load/heartbeat/save regressions; no Discord or database IO."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from cwl_web import change_history, manage_tickets
from cwl_web.manage_content import fingerprint
from extensions.commands.tickets import console, settings
from utils import manage_web_worker as worker
from utils.ticket_settings import settings_revision

RUNTIME_KEYS = (
    'thread_name_capability_version',
    'thread_name_capability_booted_at',
    'thread_name_capability_boot_id',
    'thread_name_capability_heartbeat_at',
)
AT = datetime(2026, 11, 21, 3, 30, tzinfo=timezone.utc)


def config():
    return {
        '_id': 'config', 'ticket_target_guild_id': worker.GUILD_ID,
        'main_candidate_parent': 111111111111111111,
        'main_staff_parent': 222222222222222222,
        'main_thread_recruiter_role': 333333333333333333,
        'fwa_candidate_parent': 444444444444444444,
        'fwa_staff_parent': 555555555555555555,
        'fwa_thread_recruiter_role': 666666666666666666,
        'desk_channel_id': 777777777777777777,
        'ticket_archive_quiet_days': 1, 'ticket_settings_revision': 4,
        'future_setting': {'enabled': True},
        'thread_name_capability_version': 1,
        'thread_name_capability_booted_at': AT,
        'thread_name_capability_boot_id': 'boot-before',
        'thread_name_capability_heartbeat_at': AT,
    }


class ConfigCollection:
    def __init__(self, cfg):
        self.doc = deepcopy(cfg)
        self.updates = []
        self.audit = NS(insert_one=AsyncMock(), update_one=AsyncMock())
        self.database = NS(get_collection=lambda _name, **_options: self.audit)

    async def find_one(self, query):
        assert query == {'_id': 'config'}
        return deepcopy(self.doc)

    async def update_one(self, query, update):
        self.updates.append((deepcopy(query), deepcopy(update)))
        for key, expected in query.items():
            if expected == {'$exists': False}:
                matches = key not in self.doc
            else:
                matches = self.doc.get(key) == expected
            if not matches:
                return NS(matched_count=0)
        self.doc.update(deepcopy(update.get('$set', {})))
        for key, amount in update.get('$inc', {}).items():
            self.doc[key] = self.doc.get(key, 0) + amount
        return NS(matched_count=1)


@pytest.fixture
def isolated(monkeypatch):
    collection = ConfigCollection(config())
    mongo = NS(ticket_setup=collection)

    @asynccontextmanager
    async def database(_request):
        yield mongo

    monkeypatch.setattr(manage_tickets, 'mongo', database)
    monkeypatch.setattr(manage_tickets, 'require_manage', AsyncMock(return_value={'user_id': '1'}))
    monkeypatch.setattr(manage_tickets, 'get_rollout', AsyncMock(return_value=NS(
        phase='thread_default', valid=True, desk_intake=None,
    )))
    monkeypatch.setattr(settings, 'validate', AsyncMock(return_value='Ready.'))
    monkeypatch.setattr(change_history, 'begin', AsyncMock(return_value='fixture-history'))
    monkeypatch.setattr(change_history, 'finish', AsyncMock())
    ctx = NS(guild_id=worker.GUILD_ID, user=NS(id=1), member=NS(display_name='Staff'),
             dashboard_actor={'user_id': '1'})
    return collection, mongo, NS(rest=object()), ctx


async def page_revision(part='timers'):
    request = NS(match_info={} if part is None else {'part': part})
    return json.loads((await manage_tickets.settings(request)).text)['revision']


def save_row(revision, *, action='save'):
    return {'section': 'ticket_settings', 'action': action, 'user_id': '1',
            'values': {'ticket_archive_quiet_days': 2}, 'revision': revision}


@pytest.mark.parametrize('key', RUNTIME_KEYS)
def test_runtime_key_changes_additions_and_removals_do_not_change_revision(key):
    cfg = config()
    before = deepcopy(cfg)
    expected = settings_revision(cfg)
    changed = dict(cfg, **{key: 'a new runtime observation'})
    assert settings_revision(changed) == expected
    changed.pop(key)
    assert settings_revision(changed) == expected
    assert cfg == before


@pytest.mark.parametrize('key', [
    'ticket_archive_quiet_days', 'desk_channel_id', 'ticket_settings_revision',
    'ticket_target_guild_id', 'main_candidate_parent', 'future_setting',
    'future_unknown_setting', 'thread_name_capability_future_setting',
])
def test_every_nonexcluded_key_remains_revision_sensitive(key):
    cfg = config()
    changed = dict(cfg, **{key: 'changed by another staff member'})
    assert settings_revision(changed) != settings_revision(cfg)


def test_revision_keeps_canonical_algorithm_and_input_unchanged():
    cfg = {key: value for key, value in config().items() if key not in RUNTIME_KEYS}
    cfg['other_timestamp'] = AT
    before = deepcopy(cfg)
    assert settings_revision(cfg) == fingerprint(cfg)
    assert settings_revision(dict(reversed(list(cfg.items())))) == settings_revision(cfg)
    assert settings_revision.__module__ == 'utils.ticket_settings'
    assert cfg == before


@pytest.mark.parametrize('part', [None, 'timers', 'main', 'fwa', 'desk', 'viewers', 'tools'])
def test_every_ticket_settings_page_uses_the_shared_revision(isolated, part):
    collection, *_ = isolated
    assert asyncio.run(page_revision(part)) == settings_revision(collection.doc)


@pytest.mark.parametrize('runtime_change', ['heartbeat', 'restart', 'stop'])
def test_load_then_runtime_change_then_actual_native_save_succeeds(isolated, runtime_change):
    collection, mongo, bot, ctx = isolated

    async def run():
        revision = await page_revision()
        if runtime_change == 'heartbeat':
            collection.doc['thread_name_capability_heartbeat_at'] = AT + timedelta(minutes=2)
        elif runtime_change == 'restart':
            collection.doc.update(dict(zip(RUNTIME_KEYS, [2, AT + timedelta(minutes=2), 'new-boot', AT + timedelta(minutes=2)])))
        else:
            for key in RUNTIME_KEYS:
                collection.doc.pop(key)
        runtime_before = {key: collection.doc[key] for key in RUNTIME_KEYS if key in collection.doc}
        result = await worker.dispatch(bot, mongo, save_row(revision), ctx)
        assert result == {'message': 'Settings validated and saved.'}
        assert collection.doc['ticket_archive_quiet_days'] == 2
        assert collection.doc['ticket_settings_revision'] == 5
        assert {key: collection.doc[key] for key in RUNTIME_KEYS if key in collection.doc} == runtime_before
        query, update = collection.updates[0]
        assert not set(RUNTIME_KEYS).intersection(query)
        assert update['$set'] == {'ticket_archive_quiet_days': 2}
        assert collection.audit.update_one.await_args.args[1]['$set']['state'] == 'committed'
        change_history.finish.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize('change', ['setting', 'counter_only', 'binding', 'unknown', 'edit_then_restore'])
def test_real_staff_changes_still_conflict_before_save(isolated, monkeypatch, change):
    collection, mongo, bot, ctx = isolated
    native_save = AsyncMock()
    monkeypatch.setattr(settings, 'save', native_save)

    async def run():
        revision = await page_revision()
        if change == 'setting':
            collection.doc['ticket_archive_quiet_days'] = 3
        elif change == 'binding':
            collection.doc['main_candidate_parent'] += 1
        elif change == 'unknown':
            collection.doc['future_setting'] = {'enabled': False}
        elif change == 'edit_then_restore':
            collection.doc['ticket_archive_quiet_days'] = 9
            collection.doc['ticket_archive_quiet_days'] = 1
            collection.doc['ticket_settings_revision'] += 1
        else:
            collection.doc['ticket_settings_revision'] += 1
        with pytest.raises(ValueError, match='Ticket settings changed. Reload before trying again.'):
            await worker.dispatch(bot, mongo, save_row(revision), ctx)
        native_save.assert_not_awaited()
        assert collection.updates == []
        change_history.begin.assert_not_awaited()

    asyncio.run(run())


def test_native_cas_still_blocks_a_staff_edit_after_worker_revision_check(isolated, monkeypatch):
    collection, mongo, bot, ctx = isolated

    validations = 0
    async def race(*_args):
        nonlocal validations
        validations += 1
        if validations == 2:  # worker precheck passed; native Save must still revalidate
            collection.doc['ticket_archive_quiet_days'] = 3
            collection.doc['ticket_settings_revision'] += 1

    monkeypatch.setattr(settings, 'validate', race)

    async def run():
        revision = await page_revision()
        with pytest.raises(ValueError, match='Settings changed while you were editing'):
            await worker.dispatch(bot, mongo, save_row(revision), ctx)
        assert collection.doc['ticket_archive_quiet_days'] == 3
        assert collection.doc['ticket_settings_revision'] == 5
        assert collection.audit.update_one.await_args.args[1]['$set']['state'] == 'conflict'
        change_history.finish.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize('action', ['save', 'check', 'restore_entry', 'restore_desk_entry', 'restore_console'])
def test_all_ticket_settings_actions_share_the_runtime_tolerant_guard(isolated, monkeypatch, action):
    collection, mongo, bot, ctx = isolated
    calls = {
        'save': ('save', AsyncMock(return_value='Saved')),
        'check': ('validate', AsyncMock(return_value='Ready')),
        'restore_entry': ('repair_entry', AsyncMock(return_value='Repaired')),
        'restore_desk_entry': ('repair_desk_entry', AsyncMock(return_value='Repaired')),
        'restore_console': ('configure_hub_here', AsyncMock()),
    }
    name, handler = calls[action]
    monkeypatch.setattr(console if action == 'restore_console' else settings, name, handler)

    async def run():
        revision = await page_revision()
        collection.doc['thread_name_capability_heartbeat_at'] = AT + timedelta(minutes=3)
        row = save_row(revision, action=action)
        if action == 'restore_console':
            row['values'] = {'console_channel': '111111111111111111'}
        await worker.dispatch(bot, mongo, row, ctx)
        handler.assert_awaited_once()

    asyncio.run(run())
