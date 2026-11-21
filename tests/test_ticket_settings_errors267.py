"""Precheck certainty and diagnostic safety; every effect is an isolated mock."""
import asyncio
from copy import deepcopy
import logging
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest
from cwl_web import change_history
from extensions.commands.tickets import settings, thread_service
from utils import manage_web_worker as worker
from utils.member_profiles import ProfileOutcomeUncertain
from utils.ticket_settings import settings_revision
from test_manage_web_worker import ManageWorkerTests
from test_ticket_creation import _valid_parent_rest

REASON = 'handler role Recruitment Team is missing View Channel in the candidate channel #warrior-desk'


@pytest.fixture
def operation(monkeypatch):
    helper = ManageWorkerTests()
    cfg = {'_id': 'config', 'ticket_target_guild_id': worker.GUILD_ID,
           'main_candidate_parent': 20, 'main_staff_parent': 21, 'main_thread_recruiter_role': 40,
           'fwa_candidate_parent': 20, 'fwa_staff_parent': 21, 'fwa_thread_recruiter_role': 40,
           'ticket_archive_quiet_days': 1}
    row = helper.row()
    row.update(section='ticket_settings', action='save', values={'ticket_archive_quiet_days': 2}, revision=settings_revision(cfg))
    mongo = helper.db(row)
    mongo.ticket_setup = NS(find_one=AsyncMock(side_effect=lambda _query: deepcopy(cfg)), update_one=AsyncMock())
    rest = NS(fetch_my_user=AsyncMock(return_value=NS(id=99)), create_message=AsyncMock(), edit_message=AsyncMock())
    ctx = NS(user=NS(id=1), member=NS(display_name='Staff'), guild_id=worker.GUILD_ID, dashboard_actor={'user_id': '1'})
    monkeypatch.setattr(worker, 'context', AsyncMock(return_value=ctx))
    monkeypatch.setattr(settings.ticket_runtime, 'get_rollout', AsyncMock(return_value=NS(
        phase='thread_default', valid=True, thread_intake=NS(guild_id=worker.GUILD_ID, channel_id=20))))
    monkeypatch.setattr(change_history, 'begin', AsyncMock(return_value='history267'))
    monkeypatch.setattr(change_history, 'finish', AsyncMock())
    return row, mongo, NS(rest=rest), ctx


def receipt(mongo):
    return next(call.args[1]['$set'] for call in reversed(mongo.bot_config.update_one.await_args_list)
                if call.args[0].get('status') == 'running')


@pytest.mark.parametrize('action', ['save', 'check', 'restore_desk_entry'])
def test_known_precheck_failure_is_failed_before_history_config_or_discord_effects(operation, monkeypatch, action):
    row, mongo, bot, _ctx = operation
    row['action'] = action
    monkeypatch.setattr(thread_service, 'validate_thread_parents', AsyncMock(side_effect=thread_service.ThreadConfigurationError(REASON)))
    native_save = AsyncMock(); repair = AsyncMock()
    monkeypatch.setattr(settings, 'save', native_save)
    monkeypatch.setattr(settings, 'repair_desk_entry', repair)
    asyncio.run(worker.poll(bot, mongo))
    result = receipt(mongo)
    assert result['status'] == 'failed'
    assert result['message'] == f'Ticket settings check failed: {REASON}. Nothing was saved or posted.'
    native_save.assert_not_awaited(); repair.assert_not_awaited()
    change_history.begin.assert_not_awaited(); change_history.finish.assert_not_awaited()
    mongo.ticket_setup.update_one.assert_not_awaited()
    bot.rest.create_message.assert_not_awaited(); bot.rest.edit_message.assert_not_awaited()


@pytest.mark.parametrize('when', ['second_validation', 'after_config_write', 'after_discord_post'])
def test_later_thread_configuration_failure_stays_uncertain_and_is_not_retried(operation, monkeypatch, caplog, when):
    row, mongo, bot, _ctx = operation
    detail = 'late setup failure after the initial check'
    if when == 'second_validation':
        monkeypatch.setattr(settings, 'validate', AsyncMock(side_effect=['Ready', thread_service.ThreadConfigurationError(detail)]))
    else:
        monkeypatch.setattr(settings, 'validate', AsyncMock(return_value='Ready'))
        async def partial(*_args):
            if when == 'after_config_write':
                await mongo.ticket_setup.update_one({'_id': 'config'}, {'$set': {'ticket_archive_quiet_days': 2}})
            else:
                await bot.rest.create_message(20, content='fixture')
            raise thread_service.ThreadConfigurationError(detail)
        monkeypatch.setattr(settings, 'save' if when == 'after_config_write' else 'repair_desk_entry', partial)
        if when == 'after_discord_post': row['action'] = 'restore_desk_entry'
    with caplog.at_level(logging.WARNING, logger=worker.__name__):
        asyncio.run(worker.poll(bot, mongo))
    result = receipt(mongo)
    assert result['status'] == 'uncertain'
    assert 'could not confirm' in result['message']
    assert 'ThreadConfigurationError' in caplog.text and detail in caplog.text
    assert mongo.bot_config.find_one_and_update.await_count == 2  # one claim, then empty
    if when != 'after_discord_post': change_history.begin.assert_awaited_once()
    if when == 'after_config_write': mongo.ticket_setup.update_one.assert_awaited_once()
    if when == 'after_discord_post': bot.rest.create_message.assert_awaited_once()
    change_history.finish.assert_not_awaited()


@pytest.mark.parametrize('error', [RuntimeError('response missing'), ProfileOutcomeUncertain('known partial update')])
def test_every_uncertain_exception_logs_class_and_message(operation, monkeypatch, caplog, error):
    _row, mongo, bot, _ctx = operation
    monkeypatch.setattr(worker, 'dispatch', AsyncMock(side_effect=error))
    with caplog.at_level(logging.WARNING, logger=worker.__name__): asyncio.run(worker.poll(bot, mongo))
    assert receipt(mongo)['status'] == 'uncertain'
    assert type(error).__name__ in caplog.text and str(error) in caplog.text


def test_uncertain_warning_redacts_credentials_urls_and_log_newlines(operation, monkeypatch, caplog):
    _row, mongo, bot, _ctx = operation
    monkeypatch.setenv('SAMPLE_API_TOKEN', 'fixture-env-secret-267')
    detail = 'response missing fixture-env-secret-267 token=inline-secret password="two word secret" Authorization: Bearer bearer-secret https://example.test/?api_key=url-secret mongodb://user:db-secret@host/db\nforged-line'
    monkeypatch.setattr(worker, 'dispatch', AsyncMock(side_effect=RuntimeError(detail)))
    with caplog.at_level(logging.WARNING, logger=worker.__name__): asyncio.run(worker.poll(bot, mongo))
    warning = next(record.message for record in caplog.records if 'Management uncertain' in record.message)
    assert 'RuntimeError' in warning and 'response missing' in warning
    for secret in ('fixture-env-secret-267', 'inline-secret', 'two word secret', 'bearer-secret', 'url-secret', 'db-secret'):
        assert secret not in warning
    assert '\n' not in warning and '\r' not in warning


def test_permission_error_uses_available_role_and_channel_names_without_ids():
    rest = _valid_parent_rest(mentionable=True, bot_can_mention=True)
    original_roles, original_channel = rest.fetch_roles, rest.fetch_channel
    role_id = 888888888888888888
    async def roles(guild):
        return [*(await original_roles(guild)), NS(id=role_id, name='Recruitment Team', permissions=hikari.Permissions.NONE)]
    async def channel(channel_id):
        value = await original_channel(channel_id)
        value.name = 'warrior-desk' if channel_id == 20 else 'ticket-staff'
        return value
    rest.fetch_roles, rest.fetch_channel = roles, channel
    parents = thread_service.ThreadParents(10, 20, 21, 40, staff_thread_role_ids=(role_id,), private_staff=True)
    with pytest.raises(thread_service.ThreadConfigurationError) as failure:
        asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
    assert 'Recruitment Team' in str(failure.value) and '#warrior-desk' in str(failure.value)
    assert str(role_id) not in str(failure.value)


@pytest.mark.parametrize('role_source', ['current', 'mapped_main', 'mapped_fwa', 'mapped_account', 'mapped_staff', 'shared', 'viewer', 'unrelated'])
def test_manage_threads_allows_configured_handler_roles_but_not_unrelated_roles(role_source):
    rest = _valid_parent_rest(mentionable=True, bot_can_mention=True)
    original_roles, original_channel = rest.fetch_roles, rest.fetch_channel
    role_id = 888888888888888888
    async def roles(guild):
        items = await original_roles(guild)
        if role_source != 'current':
            # Keep the current handler safe independently so the new role is
            # the exact role whose membership-bypass gate this case exercises.
            for item in items:
                if item.id == 40:
                    item.permissions &= ~hikari.Permissions.MANAGE_THREADS
        items.append(NS(id=role_id, name='Unrelated observers' if role_source == 'unrelated' else 'Configured ticket handlers',
                        permissions=hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.MANAGE_THREADS,
                        is_managed=False))
        return items
    async def channel(channel_id):
        value = await original_channel(channel_id)
        value.name = 'warrior-desk' if channel_id == 20 else 'ticket-staff'
        if channel_id == 21 and role_source == 'current':
            value.permission_overwrites.append(NS(id=role_id, type=hikari.PermissionOverwriteType.ROLE,
                                                 allow=hikari.Permissions.NONE, deny=hikari.Permissions.VIEW_CHANNEL))
        return value
    rest.fetch_roles, rest.fetch_channel = roles, channel
    # Current-handler case must not introduce an unrelated bypass role.
    if role_source == 'current':
        async def only_current_roles(guild):
            return [item for item in await original_roles(guild)]
        rest.fetch_roles = only_current_roles
    class Members:
        def limit(self, _amount): return self
        def __aiter__(self):
            async def iterate():
                for item in (): yield item
            return iterate()
    rest.fetch_members = lambda _guild: Members()
    extra = {}
    if role_source.startswith('mapped_'):
        extra['staff_role_config'] = ((role_source.removeprefix('mapped_'), role_id),)
    elif role_source == 'shared':
        extra['shared_staff_role_ids'] = (role_id,)
    elif role_source == 'viewer':
        extra['staff_viewer_role_ids'] = (role_id,)
    parents = thread_service.ThreadParents(10, 20, 21, 40, staff_thread_role_ids=(40,), private_staff=True, **extra)
    if role_source == 'unrelated':
        with pytest.raises(thread_service.ThreadConfigurationError) as failure:
            asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
        assert 'Unrelated observers' in str(failure.value) and 'Manage Threads' in str(failure.value)
        assert str(role_id) not in str(failure.value)
    else:
        channels = asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
        assert [item.id for item in channels] == [20, 21]


@pytest.mark.parametrize('source', ['snapshot', 'overwrite'])
@pytest.mark.parametrize('handler', [False, True])
def test_member_manage_threads_exception_requires_a_configured_handler_role(source, handler):
    rest = _valid_parent_rest(mentionable=True, bot_can_mention=True)
    original_roles, original_channel, original_member = rest.fetch_roles, rest.fetch_channel, rest.fetch_member
    member_id = 888888888888888888
    display_name = 'Configured handler member' if handler else 'Unrelated member'
    member = NS(id=member_id, display_name=display_name, role_ids=[40, 51] if handler else [50, 51])
    async def roles(guild):
        values = await original_roles(guild)
        for role in values:
            if role.id == 40:
                role.permissions &= ~hikari.Permissions.MANAGE_THREADS
        # Neither role alone combines View + Manage Threads. The member does.
        return [*values, NS(id=51, name='Thread helpers', permissions=hikari.Permissions.MANAGE_THREADS, is_managed=False)]
    async def channel(channel_id):
        value = await original_channel(channel_id)
        value.name = 'warrior-desk' if channel_id == 20 else 'ticket-staff'
        if source == 'overwrite' and channel_id == 21:
            value.permission_overwrites.append(NS(id=member_id, type=hikari.PermissionOverwriteType.MEMBER,
                                                 allow=hikari.Permissions.VIEW_CHANNEL, deny=hikari.Permissions.NONE))
        return value
    async def fetch_member(guild, user_id):
        return member if user_id == member_id else await original_member(guild, user_id)
    class Members:
        def limit(self, _amount): return self
        def __aiter__(self):
            async def iterate(): yield member
            return iterate()
    rest.fetch_roles, rest.fetch_channel, rest.fetch_member = roles, channel, fetch_member
    rest.fetch_members = lambda _guild: Members()
    parents = thread_service.ThreadParents(10, 20, 21, 40, staff_thread_role_ids=(40,), private_staff=True)
    if handler:
        channels = asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
        assert [item.id for item in channels] == [20, 21]
    else:
        with pytest.raises(thread_service.ThreadConfigurationError) as failure:
            asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
        assert display_name in str(failure.value)
        assert str(member_id) not in str(failure.value)


def _bot_role_readiness_fixture(membership, *, manage_threads=True, fresh_bot_flag=True):
    rest = _valid_parent_rest(mentionable=True, bot_can_mention=True)
    original_roles, original_channel, original_member = rest.fetch_roles, rest.fetch_channel, rest.fetch_member
    role_id, member_id = 888888888888888888, 777777777777777777
    members = [NS(id=member_id, display_name='Automation bot', role_ids=[role_id], is_bot=True)]
    if membership == 'human':
        members.append(NS(id=member_id + 1, display_name='Human teammate', role_ids=[role_id], is_bot=False))
    elif membership == 'unknown':
        members.append(NS(id=member_id + 1, display_name='Unknown teammate', role_ids=[role_id]))
    elif membership == 'empty':
        members = []
    reads = []
    class Members:
        def limit(self, amount):
            assert amount == thread_service.STAFF_MEMBER_SCAN_LIMIT + 1
            return self
        def __aiter__(self):
            async def iterate():
                if membership == 'unavailable': raise RuntimeError('member list unavailable')
                for member in members: yield member
            return iterate()
    def fetch_members(guild):
        reads.append(guild)
        return Members()
    async def roles(guild):
        values = await original_roles(guild)
        permissions = hikari.Permissions.VIEW_CHANNEL
        if manage_threads: permissions |= hikari.Permissions.MANAGE_THREADS
        return [*values, NS(id=role_id, name='Master Bots', permissions=permissions, is_managed=False)]
    async def channel(channel_id):
        value = await original_channel(channel_id)
        value.name = 'warrior-desk' if channel_id == 20 else 'ticket-staff'
        if channel_id == 21:
            value.permission_overwrites.append(NS(id=member_id, type=hikari.PermissionOverwriteType.MEMBER,
                                                 allow=hikari.Permissions.VIEW_CHANNEL, deny=hikari.Permissions.NONE))
        return value
    async def fetch_member(guild, user_id):
        if user_id != member_id: return await original_member(guild, user_id)
        return NS(id=member_id, display_name='Fresh member', role_ids=[role_id], is_bot=fresh_bot_flag)
    rest.fetch_roles, rest.fetch_channel, rest.fetch_member, rest.fetch_members = roles, channel, fetch_member, fetch_members
    parents = thread_service.ThreadParents(10, 20, 21, 40, staff_thread_role_ids=(40,), private_staff=True)
    return rest, parents, reads, role_id, member_id


@pytest.mark.parametrize('manage_threads', [False, True])
@pytest.mark.parametrize('membership', ['bots', 'human', 'unknown', 'empty', 'unavailable'])
def test_only_nonempty_verified_all_bot_roles_pass_readiness(membership, manage_threads):
    rest, parents, reads, role_id, _member_id = _bot_role_readiness_fixture(membership, manage_threads=manage_threads)
    if membership == 'bots':
        channels = asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
        assert [item.id for item in channels] == [20, 21]
    elif membership == 'unavailable':
        with pytest.raises(RuntimeError, match='member list unavailable'):
            asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
    else:
        with pytest.raises(thread_service.ThreadConfigurationError) as failure:
            asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
        assert 'Master Bots' in str(failure.value)
        assert str(role_id) not in str(failure.value)
    assert reads == [10]  # no per-role or second member enumeration


@pytest.mark.parametrize('fresh_bot_flag', [False, None])
def test_snapshot_bot_role_proof_does_not_exempt_a_fresh_human_or_unknown_member(fresh_bot_flag):
    rest, parents, reads, _role_id, member_id = _bot_role_readiness_fixture('bots', fresh_bot_flag=fresh_bot_flag)
    with pytest.raises(thread_service.ThreadConfigurationError) as failure:
        asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
    assert 'Fresh member' in str(failure.value) and str(member_id) not in str(failure.value)
    assert reads == [10]


def test_mapped_handler_human_passes_remaining_staff_view_guard():
    from dataclasses import replace
    rest, parents, reads, role_id, _member_id = _bot_role_readiness_fixture('human', fresh_bot_flag=False)
    parents = replace(parents, staff_role_config=(('fwa', role_id),))
    channels = asyncio.run(thread_service.validate_thread_parents(rest, parents, bot_user_id=99))
    assert [item.id for item in channels] == [20, 21]
    assert reads == [10]
