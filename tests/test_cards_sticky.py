import asyncio
from types import SimpleNamespace

import hikari
import pytest

from extensions.tasks import cards_sticky as sticky


class _Messages:
    """Stands in for the LazyIterator returned by fetch_messages."""

    def __init__(self, messages):
        self.messages = messages

    def limit(self, count):
        return _Awaitable(self.messages[:count])


class _Awaitable:
    def __init__(self, value):
        self.value = value

    def __await__(self):
        async def _resolve():
            return self.value
        return _resolve().__await__()


class _Rest:
    def __init__(self, *, newest_id=None, post_id=999, fetch_error=None):
        self.newest_id = newest_id
        self.post_id = post_id
        self.fetch_error = fetch_error
        self.created = []
        self.deleted = []
        self.delete_error = None

    def fetch_messages(self, channel_id):
        if self.fetch_error:
            raise self.fetch_error
        latest = (
            [SimpleNamespace(id=self.newest_id)]
            if self.newest_id is not None
            else []
        )
        return _Messages(latest)

    async def create_message(self, channel, components, flags=None):
        self.created.append((channel, components, flags))
        return SimpleNamespace(id=self.post_id)

    async def delete_message(self, channel_id, message_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((channel_id, message_id))


class _Config:
    def __init__(self, document=None):
        self.document = document
        self.writes = []

    async def find_one(self, _query):
        return dict(self.document) if self.document else None

    async def update_one(self, query, update, upsert=False):
        self.writes.append((query, update, upsert))
        self.document = dict(self.document or {})
        self.document.update(update.get("$set", {}))


def _install(monkeypatch, rest, config):
    monkeypatch.setattr(sticky, "bot_instance", SimpleNamespace(rest=rest))
    monkeypatch.setattr(sticky, "mongo_client", SimpleNamespace(bot_config=config))


def _http_error(kind):
    """Build a hikari HTTP error without hitting the network."""
    return kind(url="https://discord.test", headers={}, raw_body="denied")


def test_no_repost_when_the_notice_is_already_the_newest_message(monkeypatch):
    """The whole point of the timer is burial; an unburied notice needs nothing."""
    rest = _Rest(newest_id=555)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert rest.created == []
    assert rest.deleted == []
    assert config.writes == []


def test_buried_notice_is_reposted_and_the_old_one_removed(monkeypatch):
    rest = _Rest(newest_id=777, post_id=888)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert len(rest.created) == 1
    channel, components, flags = rest.created[0]
    assert channel == sticky.STICKY_CHANNEL_ID
    assert flags == hikari.MessageFlag.IS_COMPONENTS_V2
    assert components
    # The new message is recorded before the old one is deleted, so a crash
    # cannot strand an untracked notice that every later cycle would duplicate.
    assert config.writes[0][1]["$set"]["message_id"] == 888
    assert rest.deleted == [(sticky.STICKY_CHANNEL_ID, 555)]


def test_first_ever_run_posts_without_deleting_anything(monkeypatch):
    rest = _Rest(newest_id=None, post_id=42)
    config = _Config(None)
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert len(rest.created) == 1
    assert rest.deleted == []
    assert config.writes[0][1]["$set"]["message_id"] == 42


def test_already_deleted_previous_message_is_not_an_error(monkeypatch):
    rest = _Rest(newest_id=777, post_id=888)
    rest.delete_error = hikari.NotFoundError(
        url="https://discord.test", headers={}, raw_body="gone"
    )
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert len(rest.created) == 1
    assert config.writes


def test_missing_send_permission_does_not_write_state(monkeypatch):
    """A forbidden post must not record a message id that does not exist."""
    rest = _Rest(newest_id=777)

    async def _forbidden(channel, components, flags=None):
        raise _http_error(hikari.ForbiddenError)

    rest.create_message = _forbidden
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert config.writes == []
    assert rest.deleted == []


def test_unreadable_channel_still_reposts(monkeypatch):
    """If the newest message cannot be read, fall back to reposting."""
    rest = _Rest(newest_id=555, post_id=888)
    rest.fetch_error = _http_error(hikari.ForbiddenError)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert len(rest.created) == 1


def test_moving_channels_deletes_the_notice_left_behind(monkeypatch):
    """Changing STICKY_CHANNEL_ID must not strand the old channel's notice."""
    rest = _Rest(newest_id=555, post_id=888)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": 111222333,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert rest.created[0][0] == sticky.STICKY_CHANNEL_ID
    assert rest.deleted == [(111222333, 555)]


def test_notice_names_the_command_the_dm_and_the_manual_route():
    """The three things a reader has to leave with."""
    text = " ".join(
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content")
    )

    assert "/cards" in text
    assert "DM" in text
    assert "Find trades" in text
    # Manual entry has to be visible or the screenshot-averse just bounce.
    assert "hand" in text.lower() or "manual" in text.lower()


def test_notice_stays_short_enough_to_actually_be_read():
    text = " ".join(
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content")
    )

    assert len(text.split()) <= 70, "the whole point is that people read it"
