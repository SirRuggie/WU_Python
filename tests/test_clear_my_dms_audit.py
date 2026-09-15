"""Independent adversarial checks for the self-service DM clear."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import clear_my_dms
from utils import startup


class _History:
    """Lazy multi-page-shaped history; iteration must reach every item."""

    def __init__(self, pages):
        self.pages = pages

    async def __aiter__(self):
        for page in self.pages:
            for message in page:
                yield message


def _message(message_id: int, author_id: int):
    return SimpleNamespace(id=message_id, author=SimpleNamespace(id=author_id))


def _bot_with_history(pages, *, bot_id=9001):
    rest = SimpleNamespace(
        fetch_messages=lambda channel_id, **kwargs: _History(pages),
        delete_message=AsyncMock(),
    )
    return SimpleNamespace(
        get_me=lambda: SimpleNamespace(id=bot_id),
        rest=rest,
    )


def test_history_sweep_exhausts_pages_and_preserves_every_non_bot_message():
    # More than Discord's usual 100-message page size, split across pages and
    # with IDs old enough that bulk-delete's 14-day constraint would be unsafe.
    old_bot = [_message(i, 9001) for i in range(1, 121)]
    user = [_message(200 + i, 42) for i in range(7)]
    other_bot = [_message(300 + i, 8008) for i in range(4)]
    confirmation = _message(500, 9001)
    bot = _bot_with_history([old_bot[:100], old_bot[100:] + user, other_bot + [confirmation]])

    deleted = asyncio.run(clear_my_dms._delete_through_cutoff(
        bot, channel_id=77, cutoff_id=500
    ))

    assert deleted == 121
    assert [call.args for call in bot.rest.delete_message.await_args_list] == [
        (77, message.id) for message in old_bot + [confirmation]
    ]


def test_fixed_cutoff_is_passed_to_history_and_newer_bot_message_survives():
    seen = {}
    older = _message(499, 9001)
    confirmation = _message(500, 9001)
    # A real Discord paginator excludes this because before=cutoff+1. Keep it
    # out of the fake result and assert the exact bound given to REST.
    newer = _message(501, 9001)

    class Rest:
        delete_message = AsyncMock()

        def fetch_messages(self, channel_id, **kwargs):
            seen.update(channel_id=channel_id, **kwargs)
            return _History([[older, confirmation]])

    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=9001), rest=Rest())
    assert asyncio.run(clear_my_dms._delete_through_cutoff(
        bot, channel_id=77, cutoff_id=confirmation.id
    )) == 2
    assert seen == {"channel_id": 77, "before": 501}
    assert newer.id not in [call.args[1] for call in bot.rest.delete_message.await_args_list]


def test_other_failure_reports_partial_progress():
    messages = [_message(1, 9001), _message(2, 9001), _message(3, 9001)]
    bot = _bot_with_history([messages])
    bot.rest.delete_message.side_effect = [None, RuntimeError("rate path")]

    with pytest.raises(clear_my_dms._PurgeFailure) as raised:
        asyncio.run(clear_my_dms._delete_through_cutoff(bot, channel_id=77, cutoff_id=3))

    assert raised.value.deleted == 1
    assert isinstance(raised.value.__cause__, RuntimeError)


def test_dm_guard_requires_exact_dm_recipient_and_channel():
    bot = SimpleNamespace(rest=SimpleNamespace(fetch_channel=AsyncMock(return_value=SimpleNamespace(
        type=hikari.ChannelType.DM, recipient=SimpleNamespace(id=42)
    ))))
    valid = SimpleNamespace(guild_id=None, interaction=SimpleNamespace(channel_id=77))
    wrong_channel = SimpleNamespace(guild_id=None, interaction=SimpleNamespace(channel_id=78))
    guild = SimpleNamespace(guild_id=1, interaction=SimpleNamespace(channel_id=77))

    assert asyncio.run(clear_my_dms._requester_dm(valid, bot, user_id=42, channel_id=77))
    assert not asyncio.run(clear_my_dms._requester_dm(wrong_channel, bot, user_id=42, channel_id=77))
    assert not asyncio.run(clear_my_dms._requester_dm(guild, bot, user_id=42, channel_id=77))


def test_confirmation_states_scope_and_fixed_cutoff_semantics():
    rendered = str(clear_my_dms._confirmation("opaque-action"))
    assert "all messages authored by WUBOT" in rendered
    assert "Your messages are preserved" in rendered
    assert "including the oldest messages and this confirmation" in rendered
    assert "Future reminders and a future `/todo` command remain enabled" in rendered


def test_command_module_is_discovered_at_startup():
    assert "extensions.commands.clear_my_dms" in startup.load_cogs(
        disallowed={"example"}, disallowed_folders={"tickets"}
    )


def test_confirm_catches_partial_sweep_failure_and_records_terminal_state(monkeypatch):
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=42), channel_id=77,
        respond=AsyncMock(),
    )
    mongo = SimpleNamespace(component_state=SimpleNamespace(update_one=AsyncMock()))
    receipts = []

    async def valid(*_args, **_kwargs):
        return True

    async def claim(*_args, **_kwargs):
        return {"cutoff_id": 500}

    async def partial(*_args, **_kwargs):
        raise clear_my_dms._PurgeFailure(17, RuntimeError("REST stopped"))

    async def receipt(_bot, channel_id, content):
        receipts.append((channel_id, content))

    monkeypatch.setattr(clear_my_dms, "_requester_dm", valid)
    monkeypatch.setattr(clear_my_dms, "_claim", claim)
    monkeypatch.setattr(clear_my_dms.todo, "clear_dm_history_through", partial)
    monkeypatch.setattr(clear_my_dms, "_temporary_receipt", receipt)

    asyncio.run(clear_my_dms.clear_my_dms_confirm(
        ctx=ctx, action_id="action", bot=SimpleNamespace(), mongo=mongo
    ))

    update = mongo.component_state.update_one.await_args.args[1]["$set"]
    assert update["status"] == "failed"
    assert update["deleted_count"] == 17
    assert "17 WUBOT-authored messages" in receipts[0][1]


def test_cancel_consumes_request_without_starting_any_purge(monkeypatch):
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=42), channel_id=77,
        respond=AsyncMock(),
    )

    async def valid(*_args, **_kwargs):
        return True

    cancel = AsyncMock(return_value=True)
    monkeypatch.setattr(clear_my_dms, "_requester_dm", valid)
    monkeypatch.setattr(clear_my_dms, "_cancel", cancel)

    asyncio.run(clear_my_dms.clear_my_dms_cancel(
        ctx=ctx, action_id="action", bot=SimpleNamespace(), mongo=SimpleNamespace()
    ))

    cancel.assert_awaited_once()
    ctx.respond.assert_awaited_once_with("No messages were deleted.", ephemeral=True)


def test_pre_cutoff_todo_delivery_cannot_activate_after_clear(monkeypatch):
    owner = clear_my_dms.todo.todo_sessions.session_id(42, 77)
    clear_my_dms.todo._dm_history_clear_cutoffs.clear()
    clear_my_dms.todo._dm_history_clear_cutoffs[owner] = 500
    takeover = AsyncMock()
    monkeypatch.setattr(clear_my_dms.todo, "_takeover_locked", takeover)
    ctx = SimpleNamespace(user=SimpleNamespace(id=42), channel_id=77)
    message = SimpleNamespace(id=499, webhook_id=None)

    activated = asyncio.run(clear_my_dms.todo._activate_auto_panel(
        ctx, SimpleNamespace(), SimpleNamespace(), message, [], "war"
    ))

    assert activated is False
    takeover.assert_not_awaited()
