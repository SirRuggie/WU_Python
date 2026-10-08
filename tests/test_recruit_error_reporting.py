import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from utils import recruit_error_reporting as reporting


def context(rest=None):
    rest = rest or SimpleNamespace(create_message=AsyncMock())
    return SimpleNamespace(
        user=SimpleNamespace(id=123), guild_id=644963518025826315, channel_id=456,
        interaction=SimpleNamespace(
            id=789, custom_id='ticket_v2_create:public:main',
            app=SimpleNamespace(rest=rest), edit_initial_response=AsyncMock(),
        ),
    )


def test_exact_exception_and_only_developer_ping():
    ctx = context()
    async def run():
        try:
            raise ValueError('non-recruiter role 1004254963721060452 can view the staff parent')
        except ValueError:
            return await reporting.notify(ctx, 'Ticketing is not ready.')
    result = asyncio.run(run())
    args, kw = ctx.interaction.app.rest.create_message.call_args
    assert args == (1547244294757425212,)
    assert kw['user_mentions'] == [505227988229554179]
    assert kw['role_mentions'] is False and kw['mentions_everyone'] is False
    assert 'ValueError: non-recruiter role 1004254963721060452' in kw['content']
    assert 'ticket_v2_create:public:main' in kw['content']
    assert '<@123>' in kw['content']
    assert 'Server Dev has been notified' in result


def test_failed_notification_still_answers_without_false_success():
    ctx = context(SimpleNamespace(create_message=AsyncMock(side_effect=RuntimeError('Forbidden'))))
    asyncio.run(reporting.edit_error(ctx, content='Ticketing unavailable.'))
    answer = ctx.interaction.edit_initial_response.call_args.kwargs['content']
    assert 'has been notified' not in answer
    assert 'could not notify' in answer


def test_secrets_redacted_and_message_bounded(monkeypatch):
    monkeypatch.setenv('DISCORD_TOKEN', 'private-token-value')
    ctx = context()
    asyncio.run(reporting.notify(ctx, 'Failed', error=RuntimeError('private-token-value ' + 'x' * 4000)))
    text = ctx.interaction.app.rest.create_message.call_args.kwargs['content']
    assert 'private-token-value' not in text
    assert '[redacted]' in text
    assert len(text) <= 2000


def test_registry_scope_excludes_staff_settings():
    assert reporting.is_recruit_action(SimpleNamespace(name='ticket_v2_create', declared_at=''))
    assert reporting.is_recruit_action(SimpleNamespace(name='age', declared_at='extensions/commands/recruit/questions.py:346'))
    assert not reporting.is_recruit_action(SimpleNamespace(name='ticket_settings', declared_at='extensions/commands/tickets/settings.py:1'))


def test_full_long_issue_is_attached():
    ctx = context()
    asyncio.run(reporting.notify(ctx, 'Failed', error=RuntimeError('x' * 4000)))
    kw = ctx.interaction.app.rest.create_message.call_args.kwargs
    assert kw['attachment'].filename == 'recruit-error.txt'
    assert kw['attachment'].data == ('RuntimeError: ' + 'x' * 4000).encode()


def test_dispatcher_recruit_failure_sends_alert():
    from extensions import components
    from extensions.commands.tickets import handlers  # registers the action
    ctx = context()
    ctx.respond = AsyncMock()
    async def run():
        try:
            raise RuntimeError('database unavailable')
        except RuntimeError:
            await components._refuse(ctx, 'Something went wrong.')
    asyncio.run(run())
    assert 'RuntimeError: database unavailable' in ctx.interaction.app.rest.create_message.call_args.kwargs['content']
    assert 'has been notified' in ctx.respond.call_args.args[0]


def test_onboarding_private_error_reports_underlying_exception():
    from extensions.commands.setup.recruit_join_family import _private_error
    ctx = context()
    ctx.interaction.execute = AsyncMock()
    async def run():
        try:
            raise RuntimeError('Missing Manage Roles')
        except RuntimeError:
            await _private_error(ctx, 'I could not grant family access.')
    asyncio.run(run())
    assert 'Missing Manage Roles' in ctx.interaction.app.rest.create_message.call_args.kwargs['content']
    assert 'has been notified' in ctx.interaction.execute.call_args.kwargs['content']
