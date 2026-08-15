import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
import pytest

from extensions import components
from extensions.commands import poll as poll_command


NOW = datetime(2026, 8, 14, 12, 0, tzinfo=timezone.utc)


def _poll(
    poll_id="abc123def456",
    *,
    option_count=3,
    votes=None,
    active=True,
    guild_id=7,
    ends_at=NOW + timedelta(hours=1),
):
    labels = ("Goblin Machine", "Mother Witch", "Super Mini P.E.K.K.A")
    return {
        "_id": poll_id,
        "guild_id": guild_id,
        "channel_id": 70,
        "message_id": 700,
        "creator_id": 999,
        "created_at": NOW,
        "ends_at": ends_at,
        "title": "Which card should lead?",
        "description": "Choose one for the next round.",
        "ping_role_id": None,
        "options": [
            {"id": index, "text": label}
            for index, label in enumerate(labels[:option_count], start=1)
        ],
        "votes": dict(votes or {}),
        "active": active,
    }


def _walk_payload(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_payload(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk_payload(child)


def _built_payload(component):
    payload = component.build()
    return payload[0] if isinstance(payload, tuple) else payload


def _container_children(view):
    return _built_payload(view[0])["components"]


def _payload_nodes(view):
    return list(_walk_payload([_built_payload(component) for component in view]))


def _payload_text(view):
    return "\n".join(
        str(node["content"])
        for node in _payload_nodes(view)
        if "content" in node
    )


def _custom_ids(view):
    return [
        str(node["custom_id"])
        for node in _payload_nodes(view)
        if "custom_id" in node
    ]


def _vote_rows(view):
    rows = []
    for child in _container_children(view):
        if child.get("type") != hikari.ComponentType.ACTION_ROW:
            continue
        if any(
            str(component.get("custom_id", "")).startswith("poll_vote:")
            for component in child.get("components", ())
        ):
            rows.append(child)
    return rows


@pytest.mark.parametrize("option_count", [2, 3])
def test_public_poll_renders_one_numbered_vote_button_per_option(option_count):
    document = _poll(option_count=option_count)

    view = poll_command.build_poll_components(document)
    vote_rows = _vote_rows(view)
    vote_ids = [
        custom_id
        for custom_id in _custom_ids(view)
        if custom_id.startswith("poll_vote:")
    ]

    assert len(vote_rows) == 1
    assert [
        button["label"] for button in vote_rows[0]["components"]
    ] == [str(option_id) for option_id in range(1, option_count + 1)]
    assert all(
        button["style"] == hikari.ButtonStyle.PRIMARY
        for button in vote_rows[0]["components"]
    )
    assert all(
        "emoji" not in button
        for button in vote_rows[0]["components"]
    )
    assert all(
        button.get("disabled", False) is False
        for button in vote_rows[0]["components"]
    )
    assert vote_ids == [
        f"poll_vote:{document['_id']}|{option_id}"
        for option_id in range(1, option_count + 1)
    ]
    text = _payload_text(view)
    for option in document["options"]:
        assert option["text"] in text


def test_vote_counts_ignore_unknown_choices_and_results_cover_all_outcomes():
    winner = _poll(votes={"11": 2, "22": 2, "33": 1, "44": 99})
    counts, total = poll_command._option_counts(winner)

    assert counts == {1: 1, 2: 2, 3: 0}
    assert total == 3
    assert poll_command._result_text(winner, counts, total) == (
        "Winner: **Mother Witch** with **2** votes."
    )

    tie = _poll(votes={"11": 1, "22": 2})
    tie_counts, tie_total = poll_command._option_counts(tie)
    tie_result = poll_command._result_text(tie, tie_counts, tie_total)
    assert tie_result == (
        "Tie: **Goblin Machine / Mother Witch** with **1** vote each."
    )

    empty = _poll(votes={})
    empty_counts, empty_total = poll_command._option_counts(empty)
    assert poll_command._result_text(empty, empty_counts, empty_total) == (
        "No votes were cast."
    )


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ({}, "No votes were cast."),
        ({"11": 1, "22": 2}, "Tie: **Goblin Machine / Mother Witch**"),
        ({"11": 2, "22": 2, "33": 1}, "Winner: **Mother Witch**"),
    ],
)
def test_closed_public_poll_renders_no_vote_tie_and_winner_results(votes, expected):
    text = _payload_text(poll_command.build_poll_components(
        _poll(votes=votes, active=False)
    ))

    assert "Poll closed." in text
    assert expected in text


def test_public_poll_shows_aggregates_without_voter_names():
    document = _poll(votes={"111": 1, "222": 2, "333": 2})

    text = _payload_text(poll_command.build_poll_components(document))

    assert "-# 3 votes · You can change your vote." in text
    assert "**67% · 2**" in text
    assert "<@111>" not in text
    assert "<@222>" not in text
    assert "<@333>" not in text


def test_public_poll_renderer_matches_the_approved_mobile_hierarchy():
    document = _poll(votes={})
    document["title"] = "Is this thing on"
    document["description"] = (
        "Testing 1, 2, 3\nPoppa Slay Slay can you hear me?"
    )
    labels = ("Yes", "No", "Let me turn my hearing aid on")
    document["options"] = [
        {"id": index, "text": label}
        for index, label in enumerate(labels, start=1)
    ]

    view = poll_command.build_poll_components(document)
    container = _built_payload(view[0])
    children = container["components"]
    text_children = [
        child["content"] for child in children if "content" in child
    ]
    empty_bar = "░" * poll_command.POLL_BAR_WIDTH

    assert container["accent_color"] == int(poll_command.GOLD_ACCENT)
    assert len(children) == 7
    assert len([
        node for node in _payload_nodes(view) if "type" in node
    ]) == 13
    assert text_children == [
        (
            "# 📊 Is this thing on\n"
            "Testing 1, 2, 3\nPoppa Slay Slay can you hear me?"
        ),
        (
            f"**1. Yes**\n{empty_bar} **0% · 0**\n"
            f"**2. No**\n{empty_bar} **0% · 0**\n"
            "**3. Let me turn my hearing aid on**\n"
            f"{empty_bar} **0% · 0**"
        ),
        (
            "-# 0 votes · You can change your vote.\n"
            f"-# ⏱️ Closes {poll_command._discord_timestamp(document['ends_at'])} · "
            f"<@{document['creator_id']}>"
        ),
    ]
    assert [children[index]["type"] for index in (1, 3)] == [
        hikari.ComponentType.SEPARATOR,
        hikari.ComponentType.SEPARATOR,
    ]
    assert all(children[index]["divider"] is True for index in (1, 3))
    assert all(
        children[index]["spacing"] == hikari.SpacingType.SMALL
        for index in (1, 3)
    )

    vote_rows = _vote_rows(view)
    assert len(vote_rows) == 1
    assert [button["label"] for button in vote_rows[0]["components"]] == [
        "1", "2", "3",
    ]
    admin_buttons = children[5]["components"]
    assert [button["label"] for button in admin_buttons] == [
        "View voters", "End poll",
    ]
    assert [button["style"] for button in admin_buttons] == [
        hikari.ButtonStyle.SECONDARY,
        hikari.ButtonStyle.SECONDARY,
    ]
    assert all(button.get("disabled", False) is False for button in admin_buttons)
    assert [button["custom_id"] for button in admin_buttons] == [
        f"poll_details:{document['_id']}",
        f"poll_end:{document['_id']}",
    ]
    assert document["_id"] not in _payload_text(view)
    assert "`" not in _payload_text(view)

    without_details = dict(document, description="")
    assert _container_children(
        poll_command.build_poll_components(without_details)
    )[0]["content"] == "# 📊 Is this thing on"


def test_public_poll_uses_exact_plain_twenty_cell_half_up_result_rows():
    document = _poll()
    labels = (
        "Minecraft", "Jackbox Party Pack", "Gartic Phone with custom prompts",
    )
    document["options"] = [
        {"id": index, "text": label}
        for index, label in enumerate(labels, start=1)
    ]
    choices = [1] * 12 + [2] * 7 + [3] * 3
    document["votes"] = {
        str(1000 + index): choice
        for index, choice in enumerate(choices)
    }

    result_text = _container_children(
        poll_command.build_poll_components(document)
    )[2]["content"]

    assert poll_command.POLL_BAR_WIDTH == 20
    assert poll_command._round_half_up(5, 2) == 3
    assert poll_command._round_half_up(20, 8) == 3
    assert poll_command._round_half_up(100, 8) == 13
    assert result_text == (
        "**1. Minecraft**\n"
        "███████████░░░░░░░░░ **55% · 12**\n"
        "**2. Jackbox Party Pack**\n"
        "██████░░░░░░░░░░░░░░ **32% · 7**\n"
        "**3. Gartic Phone with custom prompts**\n"
        "███░░░░░░░░░░░░░░░░░ **14% · 3**"
    )
    assert len(result_text.splitlines()) == 6
    assert not any(not line for line in result_text.splitlines())
    assert "`" not in result_text


@pytest.mark.parametrize(
    ("votes", "expected"),
    [
        ({"111": 1}, "-# 1 vote · You can change your vote."),
        ({"111": 1, "222": 2}, "-# 2 votes · You can change your vote."),
    ],
)
def test_public_poll_quiet_total_footer_uses_singular_plural_grammar(
    votes, expected,
):
    footer = _container_children(
        poll_command.build_poll_components(_poll(votes=votes))
    )[-1]["content"]

    assert footer.splitlines()[0] == expected


def test_closed_poll_keeps_results_admin_details_and_quiet_footer_only():
    document = _poll(
        option_count=2,
        votes={"11": 1, "22": 1},
        active=False,
    )
    document["ended_at"] = NOW

    view = poll_command.build_poll_components(document)
    text = _payload_text(view)
    custom_ids = _custom_ids(view)
    children = _container_children(view)

    assert "**100% · 2**" in text
    assert "**Poll closed.** Winner: **Goblin Machine** with **2** votes." in text
    assert "You can change your vote" not in text
    assert not any(custom_id.startswith("poll_vote:") for custom_id in custom_ids)
    assert not any(custom_id.startswith("poll_end:") for custom_id in custom_ids)
    assert f"poll_details:{document['_id']}" in custom_ids
    assert document["_id"] not in text
    assert children[-1]["content"] == (
        f"-# ⏱️ Closed {poll_command._discord_timestamp(NOW)} · "
        f"<@{document['creator_id']}>"
    )


def test_named_voter_view_is_the_only_renderer_that_lists_voters():
    document = _poll(votes={"333": 2, "111": 1, "222": 2})

    text = _payload_text(poll_command.build_named_voter_components(document))

    assert "Named voters" in text
    assert "<@111>" in text
    assert "<@222>, <@333>" in text
    assert "Super Mini P.E.K.K.A — 0" in text
    assert "No votes" in text


def test_poll_lists_render_active_recent_and_empty_states_without_names():
    active = _poll("active-one", votes={"111": 1})
    ended = _poll("ended-two", votes={"222": 2}, active=False)

    active_text = _payload_text(
        poll_command.build_poll_list_components([active], active_only=True)
    )
    recent_text = _payload_text(
        poll_command.build_poll_list_components([active, ended], active_only=False)
    )
    empty_text = _payload_text(
        poll_command.build_poll_list_components([], active_only=True)
    )

    assert "Active polls" in active_text
    assert "active-one" in active_text
    assert "closes <t:" in active_text
    assert "Recent polls" in recent_text
    assert "ended-two" in recent_text
    assert "closed" in recent_text
    assert "/poll view poll-id:<id>" in recent_text
    assert "There are no open polls" in empty_text
    assert "<@111>" not in active_text
    assert "<@222>" not in recent_text


class _PermissionContext:
    def __init__(self, *, guild_id, permissions):
        self.guild_id = guild_id
        self.member = SimpleNamespace(permissions=permissions)
        self.responses = []

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def test_runtime_admin_guard_rejects_dms_and_non_admins_but_accepts_admins():
    dm = _PermissionContext(
        guild_id=None, permissions=hikari.Permissions.ADMINISTRATOR,
    )
    member = _PermissionContext(
        guild_id=7, permissions=hikari.Permissions.VIEW_CHANNEL,
    )
    admin = _PermissionContext(
        guild_id=7, permissions=hikari.Permissions.ADMINISTRATOR,
    )

    assert not asyncio.run(poll_command._require_admin(dm))
    assert not asyncio.run(poll_command._require_admin(member))
    assert asyncio.run(poll_command._require_admin(admin))
    assert len(dm.responses) == 1
    assert len(member.responses) == 1
    assert not admin.responses
    assert dm.responses[0][1]["ephemeral"] is True
    assert member.responses[0][1]["ephemeral"] is True


class _InteractionContext:
    def __init__(self, *, user_id=123, admin=False, modal_values=None):
        self.guild_id = 7
        self.channel_id = 70
        self.user = SimpleNamespace(id=user_id)
        permissions = (
            hikari.Permissions.ADMINISTRATOR
            if admin
            else hikari.Permissions.VIEW_CHANNEL
        )
        self.member = SimpleNamespace(permissions=permissions)
        self.interaction = SimpleNamespace(
            guild_id=7,
            member=self.member,
            components=[
                [SimpleNamespace(custom_id=custom_id, value=value)]
                for custom_id, value in (modal_values or {}).items()
            ],
        )
        self.deferred = []
        self.responses = []

    async def defer(self, **kwargs):
        self.deferred.append(kwargs)

    async def respond(self, *args, **kwargs):
        self.responses.append((args, kwargs))


def test_modal_submission_posts_one_role_whitelist_and_persists_before_scheduling(
    monkeypatch,
):
    ctx = _InteractionContext(
        admin=True,
        modal_values={
            "title": "Choose the next card",
            "description": "Clash of Cards player poll",
            "option_1": "Goblin Machine",
            "option_2": "Mother Witch",
            "option_3": "",
        },
    )
    calls = []

    class Rest:
        async def create_message(self, **kwargs):
            calls.append(("message", kwargs))
            return SimpleNamespace(id=700)

    async def delete_state(_mongo, state_id):
        calls.append(("delete_state", state_id))

    async def create_poll(_mongo, document, *, observed_at):
        calls.append(("store", document.copy(), observed_at))
        return document

    monkeypatch.setattr(poll_command, "delete_state", delete_state)
    monkeypatch.setattr(poll_command.poll_store, "create_poll", create_poll)
    monkeypatch.setattr(
        poll_command, "_schedule_poll", lambda document: calls.append(("schedule", document)),
    )

    asyncio.run(poll_command.poll_create_submit(
        ctx=ctx,
        action_id="modal-state",
        user_id=123,
        guild_id=7,
        channel_id=70,
        duration_hours=24,
        ping_role_id=555,
        mongo=object(),
        bot=SimpleNamespace(rest=Rest()),
    ))

    message_kwargs = next(call[1] for call in calls if call[0] == "message")
    stored = next(call[1] for call in calls if call[0] == "store")
    assert message_kwargs["role_mentions"] == [555]
    assert message_kwargs["user_mentions"] is False
    assert message_kwargs["mentions_everyone"] is False
    assert message_kwargs["mentions_reply"] is False
    assert stored["guild_id"] == 7
    assert stored["message_id"] == 700
    assert [option["text"] for option in stored["options"]] == [
        "Goblin Machine", "Mother Witch",
    ]
    assert [call[0] for call in calls].index("store") < [
        call[0] for call in calls
    ].index("schedule")
    assert ctx.deferred == [{"ephemeral": True}]
    assert ctx.responses[-1][1]["ephemeral"] is True


def test_public_vote_is_guild_scoped_and_records_the_clicker(monkeypatch):
    ctx = _InteractionContext(user_id=456)
    document = _poll()
    updated = _poll(votes={"456": 2})
    calls = []

    async def get_poll(_mongo, **kwargs):
        calls.append(("get", kwargs))
        return document

    async def record_vote(_mongo, **kwargs):
        calls.append(("vote", kwargs))
        return updated

    async def sync(_mongo, _bot, received):
        calls.append(("sync", received))
        return True

    monkeypatch.setattr(poll_command.poll_store, "get_poll", get_poll)
    monkeypatch.setattr(poll_command.poll_store, "record_vote", record_vote)
    monkeypatch.setattr(poll_command, "_sync_poll_message", sync)
    poll_command._poll_locks.clear()

    asyncio.run(poll_command.poll_vote(
        ctx=ctx,
        action_id=f"{document['_id']}|2",
        mongo=object(),
        bot=object(),
    ))

    vote_call = next(call[1] for call in calls if call[0] == "vote")
    assert vote_call == {
        "guild_id": 7,
        "poll_id": document["_id"],
        "user_id": 456,
        "choice": 2,
    }
    assert any(call[0] == "sync" for call in calls)
    assert ctx.responses[-1][1]["ephemeral"] is True


def test_end_button_rechecks_admin_and_uses_manual_reason(monkeypatch):
    ctx = _InteractionContext(admin=True)
    document = _poll(active=False)
    received = []

    async def finalize(mongo, bot, **kwargs):
        received.append((mongo, bot, kwargs))
        return document, True

    monkeypatch.setattr(poll_command, "_finalize_poll", finalize)
    asyncio.run(poll_command.poll_end(
        ctx=ctx,
        action_id=document["_id"],
        mongo=object(),
        bot=object(),
    ))

    assert received[0][2] == {
        "guild_id": 7,
        "poll_id": document["_id"],
        "reason": "manual",
    }
    assert ctx.responses[-1][1]["ephemeral"] is True


def test_public_poll_payload_stays_within_discord_component_and_id_limits():
    for active in (True, False):
        document = _poll(option_count=3, active=active)
        document["description"] = "First detail line\nSecond detail line"
        document["ping_role_id"] = 555
        document["options"] = [
            {"id": index, "text": character * 80}
            for index, character in enumerate(("A", "B", "C"), start=1)
        ]
        if not active:
            document["ended_at"] = NOW
        view = poll_command.build_poll_components(document)
        nodes = _payload_nodes(view)
        custom_ids = _custom_ids(view)
        component_count = len([node for node in nodes if "type" in node])

        assert component_count == (14 if active else 11)
        assert component_count <= 40
        assert len(custom_ids) == len(set(custom_ids))
        assert custom_ids
        assert all(custom_id.count(":") == 1 for custom_id in custom_ids)
        assert all(len(custom_id) <= 100 for custom_id in custom_ids)
        assert all(
            len(str(node["label"])) <= 80
            for node in nodes if "label" in node
        )
        assert all(
            len(str(node["content"])) <= 4000
            for node in nodes if "content" in node
        )


def test_poll_group_registers_admin_only_management_subcommands():
    assert poll_command.poll.name == "poll"
    assert poll_command.poll.default_member_permissions == (
        hikari.Permissions.ADMINISTRATOR
    )
    assert set(poll_command.poll.subcommands) == {"create", "view", "active"}
    assert poll_command.poll.subcommands == {
        "create": poll_command.CreatePoll,
        "view": poll_command.ViewPoll,
        "active": poll_command.ActivePolls,
    }


def test_poll_actions_declare_dispatcher_ownership_and_state_requirements():
    expected = {
        "poll_create_submit": (poll_command.poll_create_submit, True, True),
        "poll_vote": (poll_command.poll_vote, False, False),
        "poll_details": (poll_command.poll_details, False, False),
        "poll_end": (poll_command.poll_end, False, False),
    }

    for name, (function, is_modal, requires_state) in expected.items():
        action = components.registered_functions[name]
        assert action.name == name
        assert action.fn is function
        assert action.no_return is True
        assert action.is_modal is is_modal
        assert action.requires_state is requires_state
        assert action.user_only is False
        assert action.opens_modal is False
        assert action.group is None


class _Scheduler:
    def __init__(self, *, running):
        self.running = running
        self.started = 0
        self.added = []

    def start(self):
        self.started += 1
        self.running = True

    def add_job(self, function, **kwargs):
        self.added.append((function, kwargs))

    def get_job(self, job_id):
        return next(
            (item for item in self.added if item[1].get("id") == job_id),
            None,
        )

    def remove_job(self, job_id):
        self.added = [
            item for item in self.added if item[1].get("id") != job_id
        ]


def test_schedule_poll_uses_stable_replacing_deadline_job(monkeypatch):
    scheduler = _Scheduler(running=True)
    monkeypatch.setattr(poll_command, "_scheduler", scheduler)
    document = _poll(ends_at=datetime(2026, 8, 14, 13, 0))

    poll_command._schedule_poll(document)

    assert len(scheduler.added) == 1
    function, kwargs = scheduler.added[0]
    assert function is poll_command._expire_poll
    assert kwargs["id"] == poll_command._job_id(document["_id"])
    assert kwargs["args"] == [document["guild_id"], document["_id"]]
    assert kwargs["replace_existing"] is True
    assert kwargs["trigger"].run_date == datetime(
        2026, 8, 14, 13, 0, tzinfo=timezone.utc,
    )
    for key, value in poll_command.POLL_JOB_OPTIONS.items():
        assert kwargs[key] == value


def test_public_message_edits_disable_every_kind_of_mention():
    class Rest:
        def __init__(self):
            self.kwargs = None

        async def edit_message(self, **kwargs):
            self.kwargs = kwargs

    rest = Rest()
    outcome = asyncio.run(poll_command._edit_poll_message(
        SimpleNamespace(rest=rest), _poll(),
    ))

    assert outcome == ("synced", None)
    assert rest.kwargs["user_mentions"] is False
    assert rest.kwargs["role_mentions"] is False
    assert rest.kwargs["mentions_everyone"] is False
    assert rest.kwargs["mentions_reply"] is False


@pytest.mark.parametrize(
    ("outcome", "expected_store_call", "expected_result", "expects_retry"),
    [
        (("synced", None), "synced", True, False),
        (("unavailable", "NotFoundError"), "unavailable", True, False),
        (("retry", "ServerHTTPError"), "pending", False, True),
    ],
)
def test_message_sync_persists_success_terminal_and_transient_states(
    monkeypatch, outcome, expected_store_call, expected_result, expects_retry,
):
    scheduler = _Scheduler(running=True)
    calls = []

    async def edit(_bot, _document):
        return outcome

    async def mark_synced(_mongo, **kwargs):
        calls.append(("synced", kwargs))
        return _poll()

    async def mark_unavailable(_mongo, **kwargs):
        calls.append(("unavailable", kwargs))
        return _poll()

    async def mark_pending(_mongo, **kwargs):
        calls.append(("pending", kwargs))
        document = _poll()
        document["message_sync_pending"] = True
        return document

    monkeypatch.setattr(poll_command, "_scheduler", scheduler)
    monkeypatch.setattr(poll_command, "_edit_poll_message", edit)
    monkeypatch.setattr(
        poll_command.poll_store, "mark_message_synced", mark_synced,
    )
    monkeypatch.setattr(
        poll_command.poll_store, "mark_message_unavailable", mark_unavailable,
    )
    monkeypatch.setattr(
        poll_command.poll_store, "mark_message_sync_pending", mark_pending,
    )

    result = asyncio.run(poll_command._sync_poll_message(
        object(), object(), _poll(),
    ))

    assert result is expected_result
    assert [name for name, _kwargs in calls] == [expected_store_call]
    sync_jobs = [
        kwargs for _function, kwargs in scheduler.added
        if kwargs["id"].startswith(poll_command.POLL_SYNC_JOB_PREFIX)
    ]
    assert bool(sync_jobs) is expects_retry
    if sync_jobs:
        assert sync_jobs[0]["replace_existing"] is True
        assert sync_jobs[0]["args"] == [7, "abc123def456"]


def test_finalize_retries_render_for_an_already_ended_durable_poll(monkeypatch):
    ended = _poll(active=False)
    ended["message_sync_pending"] = True
    synced = []

    async def end_poll(_mongo, **_kwargs):
        return None

    async def get_poll(_mongo, **_kwargs):
        return ended

    async def sync(mongo, bot, document):
        synced.append((mongo, bot, document))
        return True

    monkeypatch.setattr(poll_command, "_scheduler", _Scheduler(running=False))
    monkeypatch.setattr(poll_command.poll_store, "end_poll", end_poll)
    monkeypatch.setattr(poll_command.poll_store, "get_poll", get_poll)
    monkeypatch.setattr(poll_command, "_sync_poll_message", sync)
    poll_command._poll_locks.clear()

    document, changed = asyncio.run(poll_command._finalize_poll(
        object(), object(), guild_id=7, poll_id=ended["_id"], reason="expired",
    ))

    assert document is ended
    assert changed is False
    assert len(synced) == 1


def test_startup_reconcile_ends_all_due_batches_and_schedules_open_polls(
    monkeypatch,
):
    mongo = object()
    bot = object()
    scheduler = _Scheduler(running=False)
    due_batches = [
        [_poll("due-one", guild_id=1, ends_at=NOW - timedelta(minutes=2))],
        [_poll("due-two", guild_id=2, ends_at=NOW - timedelta(minutes=1))],
        [],
    ]
    open_polls = [_poll("open-one", guild_id=3)]
    pending_sync = [_poll("sync-one", guild_id=4)]
    pending_sync[0]["message_sync_pending"] = True
    calls = []

    async def ensure_indexes(received_mongo):
        calls.append(("indexes", received_mongo))

    async def list_due(received_mongo, *, limit):
        calls.append(("due", received_mongo, limit))
        return due_batches.pop(0)

    async def list_open(received_mongo, *, limit):
        calls.append(("open", received_mongo, limit))
        return open_polls

    async def list_pending(received_mongo, *, limit):
        calls.append(("pending", received_mongo, limit))
        return pending_sync

    async def finalize(received_mongo, received_bot, **kwargs):
        calls.append(("finalize", received_mongo, received_bot, kwargs))
        return None, True

    async def recover(received_mongo, received_bot, **kwargs):
        calls.append(("sync", received_mongo, received_bot, kwargs["poll_id"]))
        return True

    scheduled = []
    monkeypatch.setattr(poll_command, "_mongo", mongo)
    monkeypatch.setattr(poll_command, "_bot", bot)
    monkeypatch.setattr(poll_command, "_scheduler", scheduler)
    monkeypatch.setattr(poll_command.poll_store, "ensure_indexes", ensure_indexes)
    monkeypatch.setattr(poll_command.poll_store, "list_due_polls", list_due)
    monkeypatch.setattr(
        poll_command.poll_store, "list_pending_message_sync", list_pending,
    )
    monkeypatch.setattr(poll_command.poll_store, "list_open_polls", list_open)
    monkeypatch.setattr(poll_command, "_finalize_poll", finalize)
    monkeypatch.setattr(poll_command, "_recover_pending_sync", recover)
    monkeypatch.setattr(poll_command, "_schedule_poll", scheduled.append)

    asyncio.run(poll_command._reconcile_poll_startup())

    assert scheduler.started == 1
    assert [call[2] for call in calls if call[0] == "due"] == [100, 100, 100]
    finalized = [call[3] for call in calls if call[0] == "finalize"]
    assert finalized == [
        {"guild_id": 1, "poll_id": "due-one", "reason": "expired"},
        {"guild_id": 2, "poll_id": "due-two", "reason": "expired"},
    ]
    assert [call[2] for call in calls if call[0] == "open"] == [None]
    assert [call[2] for call in calls if call[0] == "pending"] == [None]
    assert [call[3] for call in calls if call[0] == "sync"] == ["sync-one"]
    assert scheduled == open_polls
    assert calls[-1] == ("indexes", mongo)


def test_index_failure_does_not_block_deadline_recovery(monkeypatch):
    mongo = object()
    bot = object()
    scheduler = _Scheduler(running=False)
    open_poll = _poll("open-before-index")
    scheduled = []

    async def no_due(_mongo, *, limit):
        return []

    async def no_pending(_mongo, *, limit):
        return []

    async def open_polls(_mongo, *, limit):
        return [open_poll]

    async def indexes_fail(_mongo):
        raise RuntimeError("index permissions")

    monkeypatch.setattr(poll_command, "_mongo", mongo)
    monkeypatch.setattr(poll_command, "_bot", bot)
    monkeypatch.setattr(poll_command, "_scheduler", scheduler)
    monkeypatch.setattr(poll_command.poll_store, "list_due_polls", no_due)
    monkeypatch.setattr(
        poll_command.poll_store, "list_pending_message_sync", no_pending,
    )
    monkeypatch.setattr(poll_command.poll_store, "list_open_polls", open_polls)
    monkeypatch.setattr(poll_command.poll_store, "ensure_indexes", indexes_fail)
    monkeypatch.setattr(poll_command, "_schedule_poll", scheduled.append)

    with pytest.raises(RuntimeError, match="index permissions"):
        asyncio.run(poll_command._reconcile_poll_startup())

    assert scheduler.started == 1
    assert scheduled == [open_poll]
