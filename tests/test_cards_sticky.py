import asyncio
import pathlib
from types import SimpleNamespace

import hikari
import pytest

from extensions.tasks import cards_sticky as sticky
from utils.emoji import emojis


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
    """Bounded, but no longer minimal.

    An earlier version fitted in 70 words and somebody still read it and asked
    how to send a trade, because it said what the feature was instead of which
    buttons to press. Numbered steps cost words and are worth them; the cap
    exists so it cannot grow into something nobody reads.
    """
    body = [
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content") and not node.content.startswith("-#")
    ]

    assert len(" ".join(body).split()) <= 110


def test_every_step_is_its_own_block():
    """One wall of lines is what made it skimmable past rather than readable."""
    parts = [
        node for container in sticky._sticky_components()
        for node in container.components
    ]
    headings = [
        node.content for node in parts
        if hasattr(node, "content") and node.content.startswith("**")
    ]
    assert [h.splitlines()[0] for h in headings] == [
        "**1 · Add your cards**",
        "**2 · See who has it**",
        "**3 · Send the offer**",
        # Accepting is not the trade. Without this the list stopped one step
        # short of the thing it is asking people to do.
        "**4 · Send the cards**",
    ]
    # Gaps between the steps, not one continuous run of text.
    assert sum(1 for node in parts if hasattr(node, "divider")) >= 5


def test_the_notice_uses_the_commands_own_emoji():
    """The mark beside a step must be the mark on the button it names."""
    text = " ".join(
        node.content
        for container in sticky._sticky_components()
        for node in container.components
        if hasattr(node, "content")
    )
    for emoji, button in (
        (emojis.scan, "Scan screenshots"),
        (emojis.magnifier, "Find trades"),
        (emojis.card_swap, "Ask to swap"),
    ):
        assert str(emoji) in text, f"{button} is not marked like the command"
    # Entering cards by hand has no emoji in the command, so it gets none here
    # rather than an invented one.
    assert "✍️" not in text


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


def test_the_sticky_offers_a_way_out_for_someone_stuck():
    """Somebody read the notice and still asked; the button answers them."""
    ids = []
    for container in sticky._sticky_components():
        for node in container.components:
            for child in getattr(node, "components", ()) or ():
                custom_id = getattr(child, "custom_id", None)
                if custom_id:
                    ids.append(custom_id)
    assert "cards_help:sticky" in ids


def test_the_walkthrough_names_every_button_in_order():
    """Each step must match a label the reader can actually see on screen."""
    text = "\n".join(
        node.content
        for container in sticky._walkthrough()
        for node in container.components
        if hasattr(node, "content")
    )

    order = [
        "/cards", "Scan screenshots", "Find trades", "Ask to swap", "Accept",
        "same clan", "Yes, I sent it",
    ]
    positions = [text.index(label) for label in order]
    assert positions == sorted(positions), "the steps are out of order"

    # Nine numbered steps, none skipped.
    for step in range(1, 10):
        assert f"**{step}.**" in text, f"step {step} is missing"

    # Three phases, because setup happens once and trading happens often.
    for heading in ("First time only", "Every trade", "After they accept"):
        assert f"### {heading}" in text, heading

    # The things people got wrong: where the pictures go, the clan, and that
    # accepting is not the end of it.
    assert "DM" in text
    assert "by hand" in text
    assert "Did you send your card?" in text


def test_every_sticky_button_is_registered_with_the_dispatcher():
    """An unregistered custom_id is refused before any listener sees it.

    extensions/components.py listens to EVERY component interaction, resolves
    the name before the colon, and answers "this panel is out of date" when it
    finds nothing. A plain event listener in this module never gets a look in,
    which is exactly how the first version of the help button failed.
    """
    from extensions.components import _resolve

    ids = [
        child.custom_id
        for container in sticky._sticky_components()
        for node in container.components
        for child in getattr(node, "components", ()) or ()
        if getattr(child, "custom_id", None)
    ]
    assert ids, "the sticky has no interactive button at all"
    for custom_id in ids:
        name = custom_id.partition(":")[0]
        assert _resolve(name) is not None, (
            f"{custom_id} has no registered action, so clicking it is refused"
        )


def test_the_help_button_never_edits_the_sticky_itself():
    """The dispatcher's default reply is an edit of the clicked message.

    That message is the sticky, seen by everyone, so returning components
    would replace the notice with a private walkthrough for the whole channel.
    """
    from extensions.components import _resolve

    action = _resolve("cards_help")
    assert action.no_return is True


def test_the_fingerprint_notices_more_than_words(monkeypatch):
    """A text-only fingerprint would strand a picture or a button change.

    The notice only edits itself when its fingerprint moves. Adding the banner
    changed no text, so a words-only key would have left the live message
    without it indefinitely.
    """
    baseline = sticky._content_key()

    original = sticky._sticky_components

    def without_banner():
        containers = original()
        for container in containers:
            container._components = [
                node for node in container.components
                if not hasattr(node, "items")
            ]
        return containers

    monkeypatch.setattr(sticky, "_sticky_components", without_banner)
    assert sticky._content_key() != baseline, "an image change went unnoticed"


def test_the_banner_is_the_first_thing_in_the_notice():
    first = sticky._sticky_components()[0].components[0]
    assert hasattr(first, "items"), "the banner is not at the top"
    assert str(first.items[0].media).endswith(".jpg")


def test_the_banner_file_is_small_enough_to_repost_all_day():
    """It is re-uploaded on every repost, so the original 1.8MB was wasteful."""
    banner = pathlib.Path(sticky.STICKY_BANNER)
    assert banner.exists(), sticky.STICKY_BANNER
    assert banner.stat().st_size < 400_000, banner.stat().st_size
