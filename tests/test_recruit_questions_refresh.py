"""A single ten-minute countdown per source panel, shared by all dropdowns."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands.recruit import questions


def ctx(message_id=10, action='primary_questions'):
    return SimpleNamespace(
        interaction=SimpleNamespace(
            message=SimpleNamespace(id=message_id), custom_id=f'{action}:session',
            delete_initial_response=AsyncMock(),
        ), respond=AsyncMock(),
    )


def test_delay_remains_ten_minutes():
    assert questions.PANEL_REFRESH_DELAY_SECONDS == 600


def test_repeated_choices_share_first_countdown_and_new_panel_gets_own(monkeypatch):
    async def run():
        gate = asyncio.Event()
        async def delay(seconds):
            assert seconds == 600
            await gate.wait()
        sleep = AsyncMock(side_effect=delay)
        monkeypatch.setattr(questions.asyncio, 'sleep', sleep)
        panel = [object()]
        monkeypatch.setattr(questions, 'recruit_questions_page', AsyncMock(return_value=panel))
        first = ctx()
        task = asyncio.create_task(questions.refresh_questions_panel(first, 22))
        # Let the first timer register without relying on a real sleep.
        while not sleep.await_count:
            await asyncio.wait({task}, timeout=0)
        for action in ('fwa_questions', 'explanations', 'keep_it_moving', 'primary_questions'):
            another = ctx(action=action)
            await questions.refresh_questions_panel(another, 22)
            another.respond.assert_not_awaited()
        assert sleep.await_count == 1
        first.respond.assert_not_awaited()
        first.interaction.delete_initial_response.assert_not_awaited()
        gate.set(); await task
        first.interaction.delete_initial_response.assert_awaited_once()
        first.respond.assert_awaited_once_with(components=panel, ephemeral=True)
        assert not questions._panel_refresh_tasks
        await questions.refresh_questions_panel(ctx(11), 22)
        assert sleep.await_count == 2
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['deleted', 'send', 'cancel'])
def test_timer_slot_is_released_on_failure_or_shutdown(monkeypatch, failure):
    async def run():
        context = ctx()
        monkeypatch.setattr(questions, 'recruit_questions_page', AsyncMock(return_value=[]))
        if failure == 'cancel':
            entered = asyncio.Event()
            async def delay(_):
                entered.set(); await asyncio.Event().wait()
            monkeypatch.setattr(questions.asyncio, 'sleep', delay)
            task = asyncio.create_task(questions.refresh_questions_panel(context, 22))
            await entered.wait()
            await questions.stop_family_code_warning_tasks(None)
            assert task.cancelled()
            context.respond.assert_not_awaited()
        else:
            monkeypatch.setattr(questions.asyncio, 'sleep', AsyncMock())
            if failure == 'deleted':
                context.interaction.delete_initial_response.side_effect = hikari.NotFoundError(
                    url='https://discord.com', headers={}, raw_body=b'', message='Unknown message', code=10008)
                await questions.refresh_questions_panel(context, 22)
                context.respond.assert_not_awaited()
            else:
                context.respond.side_effect = RuntimeError('send failed')
                with pytest.raises(RuntimeError):
                    await questions.refresh_questions_panel(context, 22)
        assert not questions._panel_refresh_tasks
    asyncio.run(run())


def test_separate_panels_have_independent_countdowns(monkeypatch):
    async def run():
        gate = asyncio.Event(); both = asyncio.Event(); count = 0
        async def delay(_):
            nonlocal count
            count += 1
            if count == 2: both.set()
            await gate.wait()
        monkeypatch.setattr(questions.asyncio, 'sleep', delay)
        monkeypatch.setattr(questions, 'recruit_questions_page', AsyncMock(return_value=[]))
        a, b = ctx(10), ctx(20)
        tasks = [asyncio.create_task(questions.refresh_questions_panel(c, 22)) for c in (a, b)]
        await both.wait()
        assert len(questions._panel_refresh_tasks) == 2
        gate.set(); await asyncio.gather(*tasks)
        a.respond.assert_awaited_once(); b.respond.assert_awaited_once()
        assert not questions._panel_refresh_tasks
    asyncio.run(run())
