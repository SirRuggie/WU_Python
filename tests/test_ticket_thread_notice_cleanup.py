import asyncio
from types import SimpleNamespace

import hikari

from extensions.commands.tickets import handlers


class _Collection:
    async def find_one(self, query):
        assert query == {"_id": "config"}
        return {
            "ticket_target_guild_id": 500,
            "main_staff_parent": 100,
            "fwa_staff_parent": 101,
        }


class _Rest:
    def __init__(self, thread=None, fetch_error=None, delete_error=None):
        self.thread = thread
        self.fetch_error = fetch_error
        self.delete_error = delete_error
        self.deleted = []

    async def fetch_channel(self, channel_id):
        if self.fetch_error:
            raise self.fetch_error
        return self.thread

    async def delete_message(self, channel_id, message_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((channel_id, message_id))


def _event(*, message_type=18, author_id=99, guild_id=500, parent_id=100,
           reference_channel_id=200):
    message = SimpleNamespace(
        type=message_type,
        author=SimpleNamespace(id=author_id),
        message_reference=SimpleNamespace(channel_id=reference_channel_id),
    )
    return SimpleNamespace(
        message=message, guild_id=guild_id, channel_id=parent_id, message_id=300,
    )


def _bot(rest):
    return SimpleNamespace(get_me=lambda: SimpleNamespace(id=99), rest=rest)


def _mongo():
    return SimpleNamespace(ticket_setup=_Collection())


def _thread(**overrides):
    values = {
        "id": 200,
        "parent_id": 100,
        "guild_id": 500,
        "owner_id": 99,
        "type": hikari.ChannelType.GUILD_PUBLIC_THREAD,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _cleanup(event=None, thread=None, *, rest=None):
    rest = rest or _Rest(thread)
    asyncio.run(handlers._remove_bot_thread_created_notice(
        event or _event(), _bot(rest), _mongo(),
    ))
    return rest


def test_deletes_bot_notice_for_bot_owned_thread_in_configured_staff_parent():
    rest = _cleanup(thread=_thread())

    assert rest.deleted == [(100, 300)]


def test_preserves_non_notice_and_non_bot_messages():
    rest = _Rest(_thread())

    asyncio.run(handlers._remove_bot_thread_created_notice(
        _event(message_type=0), _bot(rest), _mongo(),
    ))
    asyncio.run(handlers._remove_bot_thread_created_notice(
        _event(author_id=55), _bot(rest), _mongo(),
    ))

    assert rest.deleted == []


def test_preserves_notices_outside_configured_parent_or_guild():
    rest = _Rest(_thread())

    asyncio.run(handlers._remove_bot_thread_created_notice(
        _event(parent_id=102), _bot(rest), _mongo(),
    ))
    asyncio.run(handlers._remove_bot_thread_created_notice(
        _event(guild_id=501), _bot(rest), _mongo(),
    ))

    assert rest.deleted == []


def test_preserves_notice_when_reference_is_not_bot_owned_child_thread():
    for thread in (
        _thread(parent_id=999),
        _thread(guild_id=501),
        _thread(owner_id=55),
        _thread(type=hikari.ChannelType.GUILD_PRIVATE_THREAD),
        _thread(id=201),
    ):
        rest = _cleanup(thread=thread)
        assert rest.deleted == []


def test_cleanup_failures_are_logged_and_ignored(caplog):
    rest = _Rest(_thread(), delete_error=RuntimeError("delete failed"))

    asyncio.run(handlers._remove_bot_thread_created_notice(
        _event(), _bot(rest), _mongo(),
    ))

    assert "ticket thread-created notice cleanup failed" in caplog.text
    assert "delete failed" not in caplog.text
    assert rest.deleted == []
