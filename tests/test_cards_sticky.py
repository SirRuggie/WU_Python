import asyncio
from types import SimpleNamespace

import hikari
import pytest

from extensions.tasks import cards_sticky as sticky


class _Rest:
    def __init__(self, *, newest_id=None, post_id=999, fetch_error=None):
        self.newest_id = newest_id
        self.post_id = post_id
        self.fetch_error = fetch_error
        self.created = []
        self.deleted = []
        self.edited = []
        self.delete_error = None
        self.edit_error = None
        self.channel_fetches = 0

    async def fetch_channel(self, channel_id):
        self.channel_fetches += 1
        if self.fetch_error:
            raise self.fetch_error
        return SimpleNamespace(id=channel_id, last_message_id=self.newest_id)

    async def create_message(self, channel, components, flags=None, **kwargs):
        self.created.append((channel, components, flags))
        self.create_kwargs = kwargs
        return SimpleNamespace(id=self.post_id)

    async def delete_message(self, channel_id, message_id):
        if self.delete_error:
            raise self.delete_error
        self.deleted.append((channel_id, message_id))

    async def edit_message(self, channel, message, components, **kwargs):
        if self.edit_error:
            raise self.edit_error
        self.edited.append((channel, message))


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
        "content_key": sticky._content_key(),
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert rest.created == []
    assert rest.deleted == []
    assert rest.edited == []
    assert config.writes == []


def test_reworded_notice_is_edited_in_place_in_a_silent_channel(monkeypatch):
    """A quiet channel must not strand old wording until somebody talks."""
    rest = _Rest(newest_id=555)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
        "content_key": "whatever-it-used-to-say",
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    # Edited where it stands: no delete, no repost, nothing moves.
    assert rest.edited == [(sticky.STICKY_CHANNEL_ID, 555)]
    assert rest.created == []
    assert rest.deleted == []
    assert config.document["content_key"] == sticky._content_key()

    # And it settles: the next cycle has nothing left to do.
    rest.edited.clear()
    asyncio.run(sticky.refresh_sticky())
    assert rest.edited == []


def test_a_failed_edit_does_not_record_the_new_wording(monkeypatch):
    rest = _Rest(newest_id=555)
    rest.edit_error = RuntimeError("transient")
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
        "content_key": "stale",
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert config.document["content_key"] == "stale"


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
    assert flags & hikari.MessageFlag.IS_COMPONENTS_V2
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


def test_unreadable_channel_skips_instead_of_guessing(monkeypatch):
    """A blind repost would repeat every cycle for as long as the read fails."""
    rest = _Rest(newest_id=555, post_id=888)
    rest.fetch_error = _http_error(hikari.ForbiddenError)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert rest.created == []
    assert config.writes == []


def test_burial_check_reads_the_channel_not_a_page_of_messages(monkeypatch):
    """fetch_messages pulls 100 messages per call regardless of any limit."""
    rest = _Rest(newest_id=555)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert rest.channel_fetches == 1
    assert not hasattr(rest, "fetch_messages")


def test_a_delete_that_fails_is_retried_next_cycle(monkeypatch):
    rest = _Rest(newest_id=777, post_id=888)
    rest.delete_error = RuntimeError("transient")
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    # Still owed, so the next cycle picks it up rather than losing track of it.
    assert config.document["pending_deletes"] == [555]

    rest.delete_error = None
    rest.newest_id = 888
    asyncio.run(sticky.refresh_sticky())

    assert rest.deleted == [(sticky.STICKY_CHANNEL_ID, 555)]
    assert config.document["pending_deletes"] == []


def test_pending_deletes_cannot_grow_without_limit(monkeypatch):
    rest = _Rest(newest_id=777, post_id=888)
    rest.delete_error = RuntimeError("transient")
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
        "pending_deletes": list(range(100, 100 + sticky.MAX_PENDING_DELETES)),
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    assert len(config.document["pending_deletes"]) <= sticky.MAX_PENDING_DELETES


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
    # Why anyone would bother: family members, their clan, and the fact that
    # asking for a trade reaches the other player.
    assert "family" in text.lower()
    assert "clan" in text.lower()
    assert "offer" in text.lower() or "message" in text.lower()


def test_notice_avoids_shortenings_that_travel_badly():
    """Half the family reads this as a second language."""
    text = " ".join(
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content")
    ).lower()

    for slang in ("pics", "gonna", "wanna", "y'all", "chief", "dump"):
        assert slang not in text, f"{slang!r} does not travel"


def test_notice_stays_short_enough_to_actually_be_read():
    # The trailing support note is small print, not part of what a member has
    # to read to use the command, so it is not charged to the budget.
    body = [
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content") and not node.content.startswith("-#")
    ]

    assert len(" ".join(body).split()) <= 70, "the whole point is that people read it"


def test_support_contact_is_the_last_thing_and_rendered_small():
    nodes = [
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content")
    ]

    assert f"<@{sticky.SUPPORT_USER_ID}>" in nodes[-1]
    # `-#` only renders small at the start of a line.
    assert nodes[-1].startswith("-#")


def test_the_notice_neither_pings_nor_notifies(monkeypatch):
    """Two independent controls, and a message reposting all day needs both."""
    rest = _Rest(newest_id=777, post_id=888)
    config = _Config({
        "_id": sticky.CONFIG_ID,
        "channel_id": sticky.STICKY_CHANNEL_ID,
        "message_id": 555,
    })
    _install(monkeypatch, rest, config)

    asyncio.run(sticky.refresh_sticky())

    # allowed_mentions: the support mention does not ping that one person.
    assert rest.create_kwargs["user_mentions"] is False
    assert rest.create_kwargs["role_mentions"] is False
    assert rest.create_kwargs["mentions_everyone"] is False

    # The silent flag: the post itself does not notify the channel. Suppressing
    # mentions alone would not have stopped this.
    flags = rest.created[0][2]
    assert flags & hikari.MessageFlag.SUPPRESS_NOTIFICATIONS
    assert flags & hikari.MessageFlag.IS_COMPONENTS_V2
