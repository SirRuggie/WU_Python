"""Recruit question tools authorize every click without gating recruit responses."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.recruit import questions


def context(*roles, permissions=hikari.Permissions.NONE, guild_id=1):
    return SimpleNamespace(
        guild_id=guild_id,
        member=SimpleNamespace(role_ids=roles, permissions=permissions),
        respond=AsyncMock(), defer=AsyncMock(),
    )


@pytest.mark.parametrize('roles,permissions,allowed', [
    ((), hikari.Permissions.ADMINISTRATOR, True),
    ((1554256650817511447,), hikari.Permissions.NONE, True),
    ((1554257110794244196,), hikari.Permissions.NONE, True),
    ((), hikari.Permissions.NONE, False),
    ((1003797104088592444,), hikari.Permissions.NONE, False),
    ((), hikari.Permissions.MANAGE_GUILD, False),
])
def test_exact_admin_or_recruiter_policy(roles, permissions, allowed):
    ctx = context(*roles, permissions=permissions)
    assert asyncio.run(questions.require_question_recruiter(ctx)) is allowed
    assert ctx.respond.await_count == (0 if allowed else 1)


def test_dms_fail_closed_even_with_role():
    ctx = context(1554256650817511447, guild_id=None)
    assert not asyncio.run(questions.require_question_recruiter(ctx))


@pytest.mark.parametrize('name', [
    'primary_questions', 'fwa_questions', 'explanations', 'keep_it_moving', 'th_select',
])
def test_unauthorized_sending_action_stops_before_reads_or_writes(name):
    ctx = context(1003797104088592444)
    # No interaction, database or REST methods: authorization must run first.
    asyncio.run(getattr(questions, name)(user_id=22, ctx=ctx, bot=object(), mongo=object()))
    ctx.respond.assert_awaited_once()
    assert ctx.respond.call_args.kwargs['ephemeral'] is True


def test_slash_command_refuses_before_creating_session():
    ctx = context()
    asyncio.run(questions.RecruitQuestions.invoke(object(), ctx, mongo=object(), bot=object()))
    ctx.respond.assert_awaited_once()


def test_slash_command_allows_each_authorized_identity(monkeypatch):
    insert = AsyncMock()
    panel = AsyncMock(return_value=[])
    monkeypatch.setattr(questions, 'insert_state', insert)
    monkeypatch.setattr(questions, 'recruit_questions_page', panel)
    for ctx in (context(1554256650817511447), context(1554257110794244196),
                context(permissions=hikari.Permissions.ADMINISTRATOR)):
        ctx.interaction = SimpleNamespace(id=99)
        command = SimpleNamespace(user=SimpleNamespace(id=22))
        asyncio.run(questions.RecruitQuestions.invoke(command, ctx, mongo=object(), bot=object()))
    assert insert.await_count == 3
    assert panel.await_count == 3


def test_removed_role_is_rechecked_on_existing_panel():
    ctx = context(1554256650817511447)
    assert asyncio.run(questions.require_question_recruiter(ctx))
    ctx.member.role_ids = ()
    asyncio.run(questions.primary_questions(user_id=22, ctx=ctx, bot=object(), mongo=object()))
    ctx.respond.assert_awaited_once()
