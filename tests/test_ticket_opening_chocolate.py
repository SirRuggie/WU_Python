import asyncio
from copy import deepcopy
from types import SimpleNamespace

import hikari
import pytest

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


@pytest.mark.parametrize(
    ("count", "expected_groups", "expected_group_sizes"),
    [
        (1, 1, [1]),
        (16, 1, [16]),
        (30, 2, [20, 10]),
        (37, 2, [20, 17]),
    ],
)
def test_chocolate_checklist_has_one_link_per_current_account_in_safe_groups(
    count, expected_groups, expected_group_sizes
):
    panels = console.build_staff_chocolate_checklist(_ticket(count=count))
    assert len(panels) == expected_groups
    assert [marker.rsplit(":", 1)[-1] for marker, _view in panels] == [
        str(index) for index in range(1, expected_groups + 1)
    ]
    for (_marker, view), expected_size in zip(panels, expected_group_sizes):
        contents = _contents(view)
        assert sum(map(len, contents)) <= console.DISCORD_MESSAGE_TEXT_LIMIT
        assert sum(content.count("cc.fwafarm.com") for content in contents) == expected_size
    all_copy = "\n".join(
        content for _marker, view in panels for content in _contents(view)
    )
    assert all_copy.count("cc.fwafarm.com") == count
    assert "No Chocolate blacklist verdict was checked automatically" in all_copy


def test_chocolate_excludes_observed_but_no_longer_linked_tag():
    ticket = _ticket(count=1, observed_extra=("#OLDTAG",))
    copy = "\n".join(
        content
        for _marker, view in console.build_staff_chocolate_checklist(ticket)
        for content in _contents(view)
    )
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
    copy = "\n".join(
        content
        for _marker, view in console.build_staff_chocolate_checklist(ticket)
        for content in _contents(view)
    )
    assert needle in copy
    assert copy.count("cc.fwafarm.com") == expected_links
    assert "No Chocolate blacklist verdict was checked automatically" in copy


def test_main_ticket_never_builds_chocolate_content():
    assert console.build_staff_chocolate_checklist(
        _ticket(kind="main", count=37)
    ) == []


def test_shared_chocolate_url_is_used_for_every_player_link():
    assert chocolate_url("#abc123") == (
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
    copy = "\n".join(
        content
        for _marker, view in console.build_staff_chocolate_checklist(ticket)
        for content in _contents(view)
    )

    assert "\\*\\*not bold\\*\\*" in copy
    assert "\\[not a link\\]\\(https://invalid\\)" in copy
    assert "\\> quote" in copy
    assert "@everyone" not in copy


class _StateCollection:
    def __init__(self):
        self.document = None

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

    refreshed = _ticket(count=30)
    third = asyncio.run(console.deliver_staff_identity_context(bot, mongo, refreshed))
    assert third == 901
    assert (rest.creates, rest.edits) == (3, 2)
    assert len(states.document["chocolate_message_ids"]) == 2

    # Simulate a lost Chocolate ID checkpoint. Marker recovery must reuse both
    # committed messages rather than posting duplicates after restart.
    states.document.pop("chocolate_message_ids")
    states.document.pop("chocolate_fingerprints")
    before_creates = rest.creates
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, refreshed))
    assert rest.creates == before_creates
    assert len(states.document["chocolate_message_ids"]) == 2


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

    assert creates_after_recovery == 3
    assert rest.creates == creates_after_recovery
    assert (rest.archived, rest.locked) == (True, True)
    copy = "\n".join(
        content for message in rest.messages for content in _contents(message.components)
    )
    assert copy.count("cc.fwafarm.com") == 30


def test_chocolate_delivery_retires_pages_after_current_links_shrink(monkeypatch):
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
    assert rest.creates == 3

    observed = tuple(original["player_tags"])
    unlinked = _ticket(count=0, state="empty", observed_extra=observed)
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, unlinked))

    assert len(states.document["chocolate_message_ids"]) == 1
    all_copy = "\n".join(
        content for message in rest.messages for content in _contents(message.components)
    )
    assert "page retired" in all_copy
    assert "cc.fwafarm.com" not in all_copy
    edits_after_retirement = rest.edits
    asyncio.run(console.deliver_staff_identity_context(bot, mongo, unlinked))
    assert rest.edits == edits_after_retirement


def test_chocolate_recovery_retires_uncheckpointed_pages_after_accounts_shrink(
    monkeypatch,
):
    async def none(*_args, **_kwargs):
        return []

    monkeypatch.setattr(console.flag_store, "list_for_identity", none)
    monkeypatch.setattr(console.store, "history_for", none)
    states = _StateCollection()
    rest = _Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=states)

    asyncio.run(console.deliver_staff_identity_context(bot, mongo, _ticket(count=37)))
    states.document.pop("chocolate_message_ids")
    states.document.pop("chocolate_fingerprints")
    asyncio.run(console.deliver_staff_identity_context(
        bot, mongo, _ticket(count=1)
    ))

    copy = "\n".join(
        content for message in rest.messages for content in _contents(message.components)
    )
    assert "page retired" in copy
    assert copy.count("cc.fwafarm.com") == 1
    assert len(states.document["chocolate_message_ids"]) == 1
