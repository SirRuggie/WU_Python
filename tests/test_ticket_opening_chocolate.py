import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from types import SimpleNamespace
import uuid

import hikari
import pytest
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)
from pymongo import AsyncMongoClient, ReturnDocument

from extensions.commands.fwa.chocolate_links import chocolate_url, is_valid_tag
from extensions.commands.tickets import console, thread_service


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _contents(components):
    built = [component.build() for component in components]
    return [str(node["content"]) for node in _walk(built) if "content" in node]


def _buttons(components):
    built = [component.build() for component in components]
    return [node for node in _walk(built) if "custom_id" in node]


def _ticket(*, kind="fwa", count=0, state="ready", observed_extra=()):
    accounts = [
        {
            "tag": f"#P{index:07d}",
            "name": f"Player {index:02d}",
            "town_hall": 18,
            "profile_status": "loaded",
        }
        for index in range(1, count + 1)
    ]
    tags = [account["tag"] for account in accounts]
    return {
        "_id": "ticket_501",
        "type": "ticket",
        "ticket_type": kind,
        "ticket_number": 501,
        "guild_id": 10,
        "user_id": 30,
        "username": "Applicant",
        "display_name": "Applicant Display",
        "status": "open",
        "location": {"id": 101, "staff_space_id": 102},
        "player_tags": [*tags, *observed_extra],
        "linked_accounts": {
            "state": state,
            "current": accounts,
            "current_tags": tags,
            "retry_required": state in {"pending", "failed"},
            "revision": 1,
        },
    }


def test_questionnaire_preserves_production_prompts_and_keeps_chocolate_staff_only():
    main = repr(thread_service._questionnaire_components(
        "main", None, ticket=_ticket(kind="main", count=1)
    ))
    fwa = repr(thread_service._questionnaire_components(
        "fwa", None, ticket=_ticket(count=37)
    ))

    assert "how you hear about Warriors United?" in main
    assert "What was the hook that reeled you in?" in main
    assert "We found **1 linked account**" in main
    assert "how you hear about our FWA Operation?" in fwa
    assert "Donations are better with the update" in fwa
    assert "We found **37 linked accounts**" in fwa
    assert "cc.fwafarm.com" not in fwa


@pytest.mark.parametrize(
    ("state", "needle"),
    [
        ("pending", "being checked automatically"),
        ("failed", "could not be reached"),
        ("empty", "No linked accounts found"),
    ],
)
def test_candidate_account_state_never_conflates_failure_with_zero(state, needle):
    copy = thread_service._candidate_account_copy(_ticket(count=0, state=state))
    assert needle in copy
    if state == "failed":
        assert "No linked accounts found" not in copy


def test_chocolate_checklist_is_a_single_message_identified_by_its_title():
    marker, view = console.build_staff_chocolate_checklist(_ticket(count=1))
    assert marker == "ticket-chocolate:ticket_501"
    contents = _contents(view)
    assert sum(map(len, contents)) <= console.DISCORD_MESSAGE_TEXT_LIMIT
    assert sum(content.count("cc.fwafarm.com") for content in contents) == 1
    assert "No Chocolate blacklist verdict was checked automatically" in "\n".join(contents)


@pytest.mark.parametrize("count", [1, 16, 20])
def test_chocolate_checklist_under_one_page_has_no_pagination_buttons(count):
    _marker, view = console.build_staff_chocolate_checklist(_ticket(count=count))
    assert _buttons(view) == []
    contents = _contents(view)
    assert sum(content.count("cc.fwafarm.com") for content in contents) == count
    assert not any("Page " in content for content in contents)


def test_chocolate_checklist_paginates_46_accounts_20_per_page_with_prev_disabled():
    ticket = _ticket(count=46)
    marker, view = console.build_staff_chocolate_checklist(ticket, page=1)
    contents = _contents(view)
    assert any("· 1–20 of 46" in content for content in contents)
    assert any("Page 1 of 3" in content for content in contents)
    assert sum(content.count("cc.fwafarm.com") for content in contents) == 20

    buttons = _buttons(view)
    assert len(buttons) == 2
    prev_button, next_button = buttons
    assert prev_button["disabled"] is True
    assert next_button["disabled"] is False
    assert prev_button["custom_id"] == f"ticket_v2_chocolate_page:{ticket['_id']}|0"
    assert next_button["custom_id"] == f"ticket_v2_chocolate_page:{ticket['_id']}|2"
    assert marker == f"ticket-chocolate:{ticket['_id']}"


def test_chocolate_checklist_next_page_shows_the_next_20_accounts():
    ticket = _ticket(count=46)
    _marker, view = console.build_staff_chocolate_checklist(ticket, page=2)
    contents = _contents(view)
    assert any("· 21–40 of 46" in content for content in contents)
    assert any("Page 2 of 3" in content for content in contents)
    assert sum(content.count("cc.fwafarm.com") for content in contents) == 20

    prev_button, next_button = _buttons(view)
    assert prev_button["disabled"] is False
    assert next_button["disabled"] is False


def test_chocolate_checklist_last_page_disables_next():
    ticket = _ticket(count=46)
    _marker, view = console.build_staff_chocolate_checklist(ticket, page=3)
    contents = _contents(view)
    assert any("· 41–46 of 46" in content for content in contents)
    assert any("Page 3 of 3" in content for content in contents)
    assert sum(content.count("cc.fwafarm.com") for content in contents) == 6

    prev_button, next_button = _buttons(view)
    assert prev_button["disabled"] is False
    assert next_button["disabled"] is True


def test_chocolate_excludes_observed_but_no_longer_linked_tag():
    ticket = _ticket(count=1, observed_extra=("#OLDTAG",))
    _marker, view = console.build_staff_chocolate_checklist(ticket)
    copy = "\n".join(_contents(view))
    assert "#P0000001" in copy
    assert "#OLDTAG" not in copy


@pytest.mark.parametrize(
    ("ticket", "needle", "expected_links"),
    [
        (_ticket(count=0, state="empty"), "No accounts are currently linked", 0),
        (_ticket(count=0, state="failed"), "latest linked-account refresh failed", 0),
        (_ticket(count=1, state="failed"), "last confirmed current snapshot", 1),
    ],
)
def test_chocolate_zero_and_failure_states_are_truthful(ticket, needle, expected_links):
    _marker, view = console.build_staff_chocolate_checklist(ticket)
    copy = "\n".join(_contents(view))
    assert needle in copy
    assert copy.count("cc.fwafarm.com") == expected_links
    assert "No Chocolate blacklist verdict was checked automatically" in copy


def test_main_ticket_never_builds_chocolate_content():
    assert console.build_staff_chocolate_checklist(_ticket(kind="main", count=37)) is None


def test_shared_chocolate_url_is_used_for_every_player_link():
    assert chocolate_url("#abc123") == (
        "https://cc.fwafarm.com/cc_n/member.php?tag=ABC123"
    )


@pytest.mark.parametrize("tag", ("##abc123", "# abc 123", "##  a b c 1 2 3"))
def test_chocolate_url_tolerates_doubled_hash_and_internal_spaces(tag):
    """`main`'s `/fwa chocolate` accepts a doubled leading `#` and internal
    spaces; the shared parser must stay just as lenient."""
    assert chocolate_url(tag) == (
        "https://cc.fwafarm.com/cc_n/member.php?tag=ABC123"
    )


@pytest.mark.parametrize("tag", ("#ABC?123", "#ABC&123", "#ABC#123"))
def test_chocolate_url_rejects_punctuation_that_could_change_the_query(tag):
    assert not is_valid_tag(tag)
    with pytest.raises(ValueError, match="letters or numbers"):
        chocolate_url(tag)


def test_staff_opening_neutralizes_applicant_markdown():
    ticket = _ticket()
    ticket.update({
        "display_name": (
            "**not bold** [not a link](https://invalid) > quote @everyone"
        ),
        "username": "`not code`_either_ <@123456789012345678>",
    })
    copy = "\n".join(_contents(thread_service._staff_opening_components(ticket)))

    assert "\\*\\*not bold\\*\\*" in copy
    assert "\\[not a link\\]\\(https://invalid\\)" in copy
    assert "\\> quote" in copy
    assert "\\`not code\\`\\_either\\_" in copy
    assert "@everyone" not in copy
    assert "<@123456789012345678>" not in copy


def test_chocolate_link_labels_neutralize_hostile_account_names():
    ticket = _ticket(count=1)
    ticket["linked_accounts"]["current"][0]["name"] = (
        "**not bold** [not a link](https://invalid) > quote @everyone"
    )
    _marker, view = console.build_staff_chocolate_checklist(ticket)
    copy = "\n".join(_contents(view))

    assert "\\*\\*not bold\\*\\*" in copy
    assert "\\[not a link\\]\\(https://invalid\\)" in copy
    assert "\\> quote" in copy
    assert "@everyone" not in copy


class _StateCollection:
    def __init__(self):
        self.document = None
        self.renewals = 0

    async def update_one(self, query, update, **kwargs):
        if self.document is None and kwargs.get("upsert"):
            self.document = {"_id": query["_id"]}
            self.document.update(deepcopy(update.get("$setOnInsert", {})))
        if self.document is None:
            return SimpleNamespace(matched_count=0)
        if "lease_owner" in query and self.document.get("lease_owner") != query["lease_owner"]:
            return SimpleNamespace(matched_count=0)
        expected_generation = query.get("refresh_generation")
        if isinstance(expected_generation, int) and self.document.get("refresh_generation") != expected_generation:
            return SimpleNamespace(matched_count=0)
        if (
            "lease_owner" in query
            and "lease_until" in update.get("$set", {})
        ):
            self.renewals += 1
        self.document.update(deepcopy(update.get("$set", {})))
        for field, amount in update.get("$inc", {}).items():
            self.document[field] = int(self.document.get(field) or 0) + int(amount)
        for field in update.get("$unset", {}):
            self.document.pop(field, None)
        return SimpleNamespace(matched_count=1)

    async def find_one_and_update(self, _query, update, **_kwargs):
        self.document.update(deepcopy(update.get("$set", {})))
        for field, amount in update.get("$inc", {}).items():
            self.document[field] = int(self.document.get(field) or 0) + int(amount)
        return deepcopy(self.document)

    async def find_one(self, _query):
        return deepcopy(self.document or {})


class _Messages:
    def __init__(self, messages):
        self.messages = messages

    async def to_list(self):
        return list(self.messages)


class _Rest:
    def __init__(self):
        self.messages = []
        self.creates = 0
        self.edits = 0

    def fetch_messages(self, _channel_id):
        return _Messages(self.messages)

    async def create_message(self, **kwargs):
        self.creates += 1
        message = SimpleNamespace(
            id=900 + self.creates,
            author=SimpleNamespace(id=7),
            components=kwargs["components"],
        )
        self.messages.append(message)
        return message

    async def edit_message(self, **kwargs):
        self.edits += 1
        for message in self.messages:
            if message.id == kwargs["message"]:
                message.components = kwargs["components"]
                return
        raise AssertionError("message to edit was not found")


def test_chocolate_current_check_requires_latest_visible_marked_pages(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    first = _ticket(count=1)

    asyncio.run(console.deliver_staff_identity_context(bot, mongo, first))
    assert asyncio.run(console.staff_chocolate_context_is_current(
        bot, mongo, first
    )) is True

    changed = _ticket(count=2)
    assert asyncio.run(console.staff_chocolate_context_is_current(
        bot, mongo, changed
    )) is False
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, changed))
    assert asyncio.run(console.staff_chocolate_context_is_current(
        bot, mongo, changed
    )) is True


def test_chocolate_delivery_is_durable_duplicate_safe_and_updates_in_place(monkeypatch):
    async def no_flags(*_args, **_kwargs):
        return []

    async def no_history(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", no_flags)
    monkeypatch.setattr(console.store, "history_for", no_history)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    first_ticket = _ticket(count=1)

    first = asyncio.run(console.deliver_staff_identity_context(bot, mongo, first_ticket))
    second = asyncio.run(console.deliver_staff_identity_context(bot, mongo, first_ticket))
    assert first == second == 901
    assert (rest.creates, rest.edits) == (2, 0)

    # 30 accounts need pagination -- the checklist grows buttons and a page
    # counter, but it stays the same single message, so this is an edit,
    # never a second create.
    refreshed = _ticket(count=30)
    third = asyncio.run(console.deliver_staff_identity_context(bot, mongo, refreshed))
    assert third == 901
    assert (rest.creates, rest.edits) == (2, 2)
    assert len(states.document["chocolate_message_ids"]) == 1

    # Simulate a lost Chocolate ID checkpoint. Recovery must find the
    # committed message by its visible title text -- no marker line is
    # posted to Discord -- and reuse it rather than posting a duplicate.
    states.document.pop("chocolate_message_ids")
    states.document.pop("chocolate_fingerprints")
    before_creates = rest.creates
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, refreshed))
    assert rest.creates == before_creates
    assert len(states.document["chocolate_message_ids"]) == 1
    assert set(states.document["chocolate_message_ids"]) == {
        message.id for message in rest.messages
        if any("cc.fwafarm.com" in content for content in _contents(message.components))
    }


def test_freshly_posted_checklist_has_no_marker_text(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)

    asyncio.run(console.deliver_staff_identity_context(bot, mongo, _ticket(count=37)))

    assert rest.messages
    for message in rest.messages:
        for content in _contents(message.components):
            assert "ticket-chocolate:" not in content


def test_legacy_marker_message_is_still_recognised():
    """A message posted before this change still carries the old marker
    line; the structural finder must keep recognising it so already-open
    tickets keep working."""

    ticket = _ticket(count=1)
    marker, components = console.build_staff_chocolate_checklist(ticket)
    legacy_components = [*components, Text(content=f"-# {marker}")]
    message = SimpleNamespace(
        id=42,
        author=SimpleNamespace(id=7),
        components=legacy_components,
    )
    rest = _Rest()
    rest.messages.append(message)
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    found = asyncio.run(
        console._find_chocolate_messages(bot, 102, ticket["_id"])
    )
    assert found == [message]


def test_chocolate_delivery_renews_lease_before_every_rest_write(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)

    asyncio.run(console.deliver_staff_identity_context(
        bot, mongo, _ticket(count=37)
    ))

    # One create for the Applicant context panel, one for the single
    # paginated Chocolate checklist message -- regardless of how many
    # accounts (and therefore pages) it holds.
    assert rest.creates == 2
    assert states.renewals == rest.creates
    assert console.CONTEXT_LEASE > timedelta(seconds=150)


def test_chocolate_delivery_stops_after_takeover_during_slow_rest_call(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)

    async def scenario():
        states = _StateCollection()
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowRest(_Rest):
            async def create_message(self, **kwargs):
                if self.creates == 1:
                    started.set()
                    await release.wait()
                return await super().create_message(**kwargs)

        rest = SlowRest()
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
        mongo = SimpleNamespace(ticket_automation_state=states)
        delivery = asyncio.create_task(console.deliver_staff_identity_context(
            bot, mongo, _ticket(count=37)
        ))
        await started.wait()
        states.document["lease_owner"] = "takeover-owner"
        states.document["lease_until"] = (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        )
        release.set()

        assert await delivery is None
        assert rest.creates == 2
        assert states.document["lease_owner"] == "takeover-owner"
        assert states.document["delivery_state"] == "pending"

    asyncio.run(scenario())


def test_real_mongo_slow_page_takeover_fences_remaining_rest_writes(monkeypatch):
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        pytest.skip("TICKET_TEST_MONGODB_URI is required for the real-Mongo regression")

    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)

    async def scenario():
        client = AsyncMongoClient(uri, serverSelectionTimeoutMS=5_000)
        database_name = f"wu_staff_context_lease_{uuid.uuid4().hex}"
        database = client.get_database(database_name)
        mongo = SimpleNamespace(
            ticket_automation_state=database.ticket_automation_state,
        )
        started = asyncio.Event()
        release = asyncio.Event()

        class SlowRest(_Rest):
            async def create_message(self, **kwargs):
                if self.creates == 1:
                    started.set()
                    await release.wait()
                return await super().create_message(**kwargs)

        rest = SlowRest()
        bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
        state_id = "ticket_staff_context:ticket_501"
        try:
            await client.admin.command("ping")
            delivery = asyncio.create_task(console.deliver_staff_identity_context(
                bot, mongo, _ticket(count=37)
            ))
            await started.wait()
            active = await database.ticket_automation_state.find_one({"_id": state_id})
            stale_owner = active["lease_owner"]
            expired = datetime.now(timezone.utc) - timedelta(seconds=1)
            result = await database.ticket_automation_state.update_one(
                {"_id": state_id, "lease_owner": stale_owner},
                {"$set": {"lease_until": expired}},
            )
            assert result.matched_count == 1
            takeover_at = datetime.now(timezone.utc)
            winner = await database.ticket_automation_state.find_one_and_update(
                {
                    "_id": state_id,
                    "kind": "ticket_staff_context",
                    "lease_until": {"$lte": takeover_at},
                },
                {"$set": {
                    "lease_owner": "takeover-owner",
                    "lease_until": takeover_at + console.CONTEXT_LEASE,
                }},
                return_document=ReturnDocument.AFTER,
            )
            assert winner["lease_owner"] == "takeover-owner"
            release.set()

            assert await delivery is None
            assert rest.creates == 2
            durable = await database.ticket_automation_state.find_one({"_id": state_id})
            assert durable["lease_owner"] == "takeover-owner"
            assert durable["delivery_state"] == "pending"
            assert "delivered_at" not in durable
        finally:
            release.set()
            await client.drop_database(database_name)
            await client.close()

    asyncio.run(scenario())


def test_recovered_terminal_accounts_update_archived_checklist_without_duplicates(
    monkeypatch,
):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()

    class TerminalRest(_Rest):
        def __init__(self):
            super().__init__()
            self.archived = True
            self.locked = True

        async def fetch_channel(self, channel_id):
            return SimpleNamespace(
                id=channel_id,
                guild_id=10,
                parent_id=21,
                name=thread_service.thread_names("fwa", 501, "Applicant")[1],
                type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
                owner_id=7,
                is_archived=self.archived,
                is_locked=self.locked,
            )

        async def edit_channel(self, _channel_id, **kwargs):
            if "archived" in kwargs:
                self.archived = kwargs["archived"]
            if "locked" in kwargs:
                self.locked = kwargs["locked"]

    rest = TerminalRest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    opening = _ticket(count=1)
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, opening))
    assert rest.creates == 2

    recovered = _ticket(count=30)
    recovered["status"] = "denied"
    recovered["location"].update({
        "guild_id": 10,
        "staff_parent_id": 21,
    })
    asyncio.run(console.deliver_staff_identity_context(
        bot,
        mongo,
        recovered,
        reopen_terminal_thread=True,
    ))
    creates_after_recovery = rest.creates
    asyncio.run(console.deliver_staff_identity_context(
        bot,
        mongo,
        recovered,
        reopen_terminal_thread=True,
    ))

    # The same single checklist message is edited in place -- 30 accounts
    # never needs a second created message, only a paginated one.
    assert creates_after_recovery == 2
    assert rest.creates == creates_after_recovery
    # A decision never re-archives or re-locks the staff thread; it was
    # reopened once to deliver the recovered context and stays open.
    assert (rest.archived, rest.locked) == (False, False)
    copy = "\n".join(
        content for message in rest.messages for content in _contents(message.components)
    )
    # Only page 1 of the 30-account checklist is delivered/stored.
    assert copy.count("cc.fwafarm.com") == 20


def test_terminal_reopen_and_unlock_each_require_a_fresh_lease():
    renewals = 0
    effects = []
    ticket = _ticket(count=1)
    ticket["status"] = "denied"
    ticket["location"].update({"guild_id": 10, "staff_parent_id": 21})

    async def renew():
        nonlocal renewals
        renewals += 1

    class Rest:
        async def fetch_channel(self, channel_id):
            return SimpleNamespace(
                id=channel_id,
                guild_id=10,
                parent_id=21,
                name=thread_service.thread_names("fwa", 501, "Applicant")[1],
                type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
                owner_id=7,
                is_archived=True,
                is_locked=True,
            )

        async def edit_channel(self, channel_id, **kwargs):
            assert renewals == len(effects) + 1
            effects.append((channel_id, kwargs))

    async def scenario():
        async with console._staff_context_write_window(
            Rest(),
            ticket,
            102,
            reopen_terminal_thread=True,
            expected_owner_id=7,
            renew_lease=renew,
        ):
            pass

    asyncio.run(scenario())
    assert renewals == 2
    assert [kwargs for _channel_id, kwargs in effects] == [
        {
            "archived": False,
            "reason": "Retrying committed ticket staff context",
        },
        {
            "locked": False,
            "reason": "Retrying committed ticket staff context",
        },
    ]


def test_chocolate_checklist_updates_in_place_when_accounts_shrink_to_zero(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    original = _ticket(count=37)
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, original))
    assert rest.creates == 2

    observed = tuple(original["player_tags"])
    unlinked = _ticket(count=0, state="empty", observed_extra=observed)
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, unlinked))

    # The single checklist message is reused -- losing every linked account
    # never retires it, it just shows the "no accounts" state instead.
    assert rest.creates == 2
    assert len(states.document["chocolate_message_ids"]) == 1
    all_copy = "\n".join(
        content for message in rest.messages for content in _contents(message.components)
    )
    assert "No accounts are currently linked" in all_copy
    assert "cc.fwafarm.com" not in all_copy
    assert "retired" not in all_copy

    edits_after_update = rest.edits
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, unlinked))
    assert rest.edits == edits_after_update


def test_chocolate_delivery_collapses_a_legacy_three_message_ticket(monkeypatch):
    """A ticket opened before this change can still have three per-page
    checklist messages sitting in its staff thread. The very next delivery
    must keep the oldest as the single paginated message and retire the
    other two -- never post a duplicate."""

    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    ticket = _ticket(count=46)

    def legacy_page(message_id, start, end):
        return SimpleNamespace(
            id=message_id,
            author=SimpleNamespace(id=7),
            components=[Container(
                accent_color=console.ACCENT_YELLOW,
                components=[Text(
                    content=f"## {console.CHOCOLATE_TITLE_PREFIX} · {start}–{end} of 46"
                )],
            )],
        )

    rest.messages.extend([
        legacy_page(10, 1, 20),
        legacy_page(11, 21, 40),
        legacy_page(12, 41, 46),
    ])

    asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket))

    assert states.document["chocolate_message_ids"] == [10]
    primary = next(message for message in rest.messages if message.id == 10)
    primary_contents = _contents(primary.components)
    assert any("· 1–20 of 46" in content for content in primary_contents)
    assert len(_buttons(primary.components)) == 2

    for stale_id in (11, 12):
        stale = next(message for message in rest.messages if message.id == stale_id)
        titles = [
            content for content in _contents(stale.components)
            if content.startswith("##")
        ]
        assert titles and titles[0].endswith("retired")
        assert _buttons(stale.components) == []

    # Reusing the primary and retiring the extras never re-creates anything.
    assert rest.creates == 1  # only the Applicant context panel


def test_chocolate_paging_does_not_change_the_delivery_fingerprint(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    ticket = _ticket(count=46)

    asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket))
    stored_fingerprint = states.document["chocolate_fingerprints"][0]
    chocolate_message_id = states.document["chocolate_message_ids"][0]
    edits_before_paging = rest.edits

    # A staff member clicking Next only edits the Discord message directly
    # (see ticket_console_chocolate_page); it never touches Mongo state.
    _marker, page2 = console.build_staff_chocolate_checklist(ticket, page=2)
    asyncio.run(rest.edit_message(
        channel=102, message=chocolate_message_id, components=page2,
        user_mentions=False, role_mentions=False, mentions_everyone=False,
    ))
    assert rest.edits == edits_before_paging + 1

    edits_before_redelivery = rest.edits
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket))

    assert rest.edits == edits_before_redelivery  # unchanged account list, no redelivery
    assert states.document["chocolate_fingerprints"][0] == stored_fingerprint
    # The message is left on the page the staff member navigated to.
    live = next(m for m in rest.messages if m.id == chocolate_message_id)
    assert any("· 21–40 of 46" in content for content in _contents(live.components))


def test_chocolate_account_list_change_resets_to_page_one(monkeypatch):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)
    ticket = _ticket(count=46)
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket))

    changed = _ticket(count=25)
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, changed))

    chocolate_message = next(
        message for message in rest.messages
        if any("cc.fwafarm.com" in content for content in _contents(message.components))
    )
    contents = _contents(chocolate_message.components)
    assert any("· 1–20 of 25" in content for content in contents)


def test_chocolate_page_button_renders_the_requested_page(monkeypatch):
    ticket = _ticket(count=46)

    async def find_one(_mongo, filt):
        assert filt == {"_id": ticket["_id"], "type": "ticket"}
        return ticket

    async def allowed(_member, _mongo):
        return True

    monkeypatch.setattr(console.store, "find_one", find_one)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)

    class Context:
        user = SimpleNamespace(id=1)
        member = object()
        interaction = SimpleNamespace(message=None)

    view = asyncio.run(console.ticket_console_chocolate_page(
        Context(), f"{ticket['_id']}|2", mongo=object(),
    ))
    contents = _contents(view)
    assert any("· 21–40 of 46" in content for content in contents)


def test_chocolate_page_button_refuses_non_recruiters_and_keeps_the_current_page(
    monkeypatch,
):
    ticket = _ticket(count=46)
    responses = []

    async def find_one(_mongo, _filt):
        return ticket

    async def denied(_member, _mongo):
        return False

    monkeypatch.setattr(console.store, "find_one", find_one)
    monkeypatch.setattr(console.perms, "is_recruiter", denied)

    _marker, page3 = console.build_staff_chocolate_checklist(ticket, page=3)

    class Context:
        user = SimpleNamespace(id=1)
        member = object()
        interaction = SimpleNamespace(message=SimpleNamespace(components=page3))

        async def respond(self, *args, **kwargs):
            responses.append((args, kwargs))

    view = asyncio.run(console.ticket_console_chocolate_page(
        Context(), f"{ticket['_id']}|1", mongo=object(),
    ))
    # None means "leave the shared message exactly as it is": the dispatcher
    # skips the edit, so the refused click cannot blank or move the page.
    assert view is None
    assert len(responses) == 1
    assert "Only recruiters" in responses[0][0][0]
