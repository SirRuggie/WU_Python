"""Regression tests for /todo rendering and component routing."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from extensions import components
from extensions.commands import todo
from utils import todo_data


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _private_rows(count: int):
    return [
        todo_data.Row(
            account=f"Player {index}",
            tag=f"#P{index}",
            clan_name=f"Clan {index}",
            clan_tag=f"#C{index}",
            used=0,
            limit=0,
            ends_at=None,
            reason="private",
        )
        for index in range(count)
    ]


def _payload_text(payload) -> str:
    return "\n".join(
        str(node.get("content", ""))
        for node in _walk(payload)
        if "content" in node
    )


def test_private_pager_ids_all_have_registered_actions():
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    data[todo.VIEW_PRIVATE] = todo_data.ViewData(rows=_private_rows(75))

    payload = [component.build() for component in todo.render_dashboard(
        todo.VIEW_PRIVATE, 0, data
    )]
    action_names = {
        node["custom_id"].partition(":")[0]
        for node in _walk(payload)
        if "custom_id" in node
    }

    assert "todo_private" in action_names
    assert action_names <= set(components.registered_functions)


def test_private_refresh_preserves_private_view(monkeypatch):
    called = {}

    async def fake_switch(ctx, view, action_id, coc_client, bot, **kwargs):
        called.update(view=view, action_id=action_id, force=kwargs.get("force"))
        return []

    monkeypatch.setattr(todo, "_switch", fake_switch)
    asyncio.run(todo.todo_refresh(
        object(), "private|2", object(), object(), mongo=object()
    ))

    assert called == {"view": todo.VIEW_PRIVATE, "action_id": "private|2", "force": True}


def test_incomplete_empty_view_never_renders_all_caught_up():
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    data[todo.VIEW_WAR] = todo_data.ViewData(
        notes=["⚠️ 1 linked account could not be loaded"],
        incomplete="1 linked account could not be loaded",
    )

    payload = [component.build() for component in todo.render_dashboard(
        todo.VIEW_WAR, 0, data
    )]
    text = "\n".join(
        str(node.get("content", ""))
        for node in _walk(payload)
        if "content" in node
    )

    assert "Couldn't check every linked account" in text
    assert "All caught up" not in text
    descriptions = [
        str(node["description"])
        for node in _walk(payload)
        if "description" in node
    ]
    assert "couldn't be read — try Check now" in descriptions


def test_account_failures_mark_empty_and_nonempty_views_incomplete():
    empty = todo._with_account_failures(todo_data.ViewData(), 2)
    populated = todo._with_account_failures(
        todo_data.ViewData(rows=_private_rows(1)), 2
    )

    assert empty.incomplete.startswith("2 linked account(s)")
    assert empty.notes == []
    assert populated.incomplete == empty.incomplete
    assert populated.notes == [f"⚠️ {empty.incomplete}"]


def test_footer_explains_dm_auto_refresh_with_exact_check_time():
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2024, 8, 31, tzinfo=timezone.utc)
    payload = [component.build() for component in todo.render_dashboard(
        todo.VIEW_WAR, 0, data, checked_at=1_725_000_000, auto_refresh=True,
        refresh_until=until,
    )]
    text = _payload_text(payload)

    assert "Checked <t:1725000000:R>" in text
    assert "Rechecks about every 10 min" in text
    assert f"Stops <t:{int(until.timestamp())}:R>" in text
    assert "cached, fetched" not in text


def test_footer_explains_automatic_checks_are_dm_only():
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    payload = [component.build() for component in todo.render_dashboard(
        todo.VIEW_WAR, 0, data, checked_at=1_725_000_000, auto_refresh=False
    )]

    assert "DM /todo for auto-checks" in _payload_text(payload)


def test_automatic_footer_treats_naive_mongo_deadline_as_utc():
    naive_utc = datetime(2026, 9, 4, 12, 30)
    base = todo._notice("To-do", "Ready", checked_at=1_725_000_000)

    promoted = todo._automatic_status_panel(
        base, checked_at=1_725_000_000, refresh_until=naive_utc,
    )

    text = _payload_text([component.build() for component in promoted])
    expected = int(naive_utc.replace(tzinfo=timezone.utc).timestamp())
    assert f"Stops <t:{expected}:R>" in text


class _Interaction:
    def __init__(self):
        self.edits = []
        self.deleted = 0

    async def edit_initial_response(self, **kwargs):
        self.edits.append(kwargs)
        return SimpleNamespace(id=22)

    async def delete_initial_response(self):
        self.deleted += 1


class _Rest:
    def __init__(self, failure=None):
        self.failure = failure
        self.creates = []
        self.edits = []

    async def create_message(self, channel_id, **kwargs):
        self.creates.append((channel_id, kwargs))
        if self.failure:
            raise self.failure
        return SimpleNamespace(id=11)

    async def edit_message(self, channel_id, message_id, **kwargs):
        self.edits.append((channel_id, message_id, kwargs))
        return SimpleNamespace(id=message_id)


def test_dm_delivery_is_standalone_and_removes_deferred_placeholder():
    interaction = _Interaction()
    rest = _Rest()
    ctx = SimpleNamespace(guild_id=None, channel_id=99, interaction=interaction)

    message, schedulable = asyncio.run(
        todo._deliver_panel(ctx, SimpleNamespace(rest=rest), ["panel"])
    )

    assert message.id == 11
    assert schedulable is True
    assert rest.creates == [(99, {"components": ["panel"]})]
    assert interaction.deleted == 1
    assert interaction.edits == []


def test_dm_delivery_falls_back_to_interaction_response():
    interaction = _Interaction()
    rest = _Rest(RuntimeError("rate limit route failed"))
    ctx = SimpleNamespace(guild_id=None, channel_id=99, interaction=interaction)

    components = todo._notice(
        "Temporary problem", "Try again shortly.", auto_refresh=True,
        checked_at=1_725_000_000,
    )
    message, schedulable = asyncio.run(
        todo._deliver_panel(ctx, SimpleNamespace(rest=rest), components)
    )

    assert message.id == 22
    assert schedulable is False
    assert interaction.deleted == 0
    fallback_payload = [component.build() for component in interaction.edits[0]["components"]]
    assert "Use Check now to update" in _payload_text(
        fallback_payload
    )


def test_guild_delivery_edits_ephemeral_interaction_response():
    interaction = _Interaction()
    rest = _Rest()
    ctx = SimpleNamespace(guild_id=123, channel_id=99, interaction=interaction)

    message, schedulable = asyncio.run(
        todo._deliver_panel(ctx, SimpleNamespace(rest=rest), ["panel"])
    )

    assert message.id == 22
    assert schedulable is False
    assert rest.creates == []
    assert interaction.edits == [{"components": ["panel"]}]


def test_todo_actions_own_their_response_through_the_lock():
    for name in (
        "todo_war", "todo_cwl", "todo_raid", "todo_private",
        "todo_nav", "todo_refresh",
    ):
        assert components.registered_functions[name].no_return is True


def test_panel_is_promoted_only_after_session_registration(monkeypatch):
    rest = _Rest()
    ctx = SimpleNamespace(channel_id=99, user=SimpleNamespace(id=7))
    message = SimpleNamespace(id=11)

    async def rejected(*args, **kwargs):
        return None

    monkeypatch.setattr(todo, "_takeover_locked", rejected)
    activated = asyncio.run(todo._activate_auto_panel(
        ctx, SimpleNamespace(rest=rest), object(), message, ["active"],
        todo.VIEW_WAR,
    ))
    assert activated is False
    assert rest.edits == []

    until = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

    async def accepted(*args, **kwargs):
        return "generation", until

    monkeypatch.setattr(todo, "_takeover_locked", accepted)
    active = todo._notice(
        "To-do", "Ready", auto_refresh=True, refresh_until=until,
    )
    activated = asyncio.run(todo._activate_auto_panel(
        ctx, SimpleNamespace(rest=rest), object(), message, active,
        todo.VIEW_WAR,
    ))
    assert activated is True
    assert [(channel, message) for channel, message, _ in rest.edits] == [(99, 11)]
    payload = [
        component.build()
        for component in rest.edits[0][2]["components"]
    ]
    assert f"Stops <t:{int(until.timestamp())}:R>" in _payload_text(payload)


def test_takeover_demotes_all_old_panels_before_claim(monkeypatch):
    events = []
    rest = _Rest()
    old_documents = [
        {"_id": "dm:7:99", "message_id": 10, "generation": "old"},
        {"_id": 12},
    ]

    async def read_owner(*args, **kwargs):
        return True, old_documents[0]

    async def active_panels(*args, **kwargs):
        return True, old_documents

    async def claim(*args, **kwargs):
        events.append(("claim", kwargs["expected_owner"]))
        return "new", datetime(2026, 9, 4, tzinfo=timezone.utc)

    async def cleanup(_mongo, documents):
        events.append(("cleanup", documents))
        return True

    original_edit = rest.edit_message

    async def edit(channel_id, message_id, **kwargs):
        events.append(("edit", message_id))
        return await original_edit(channel_id, message_id, **kwargs)

    rest.edit_message = edit
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "active_panels", active_panels)
    monkeypatch.setattr(todo.todo_sessions, "claim", claim)
    monkeypatch.setattr(todo.todo_sessions, "remove_legacy_rows", cleanup)

    claimed = asyncio.run(todo._takeover_locked(
        SimpleNamespace(rest=rest), object(), user_id=7, channel_id=99,
        message_id=11, view=todo.VIEW_WAR, page=0, kind="dashboard",
        trigger="command",
    ))

    assert claimed is not None
    assert events == [
        ("edit", 10),
        ("edit", 12),
        ("cleanup", old_documents),
        ("claim", old_documents[0]),
    ]
    for _channel, _message, kwargs in rest.edits:
        payload = [component.build() for component in kwargs["components"]]
        text = _payload_text(payload)
        assert "make it automatic" in text
        assert "Rechecks" not in text


def test_takeover_aborts_before_claim_when_old_panel_cannot_be_demoted(monkeypatch):
    claimed = []

    class FailingRest:
        async def edit_message(self, *args, **kwargs):
            raise RuntimeError("Discord unavailable")

    async def read_owner(*args, **kwargs):
        return True, {"_id": "dm:7:99", "message_id": 10, "generation": "old"}

    async def active_panels(*args, **kwargs):
        return True, [{"_id": "dm:7:99", "message_id": 10}]

    async def claim(*args, **kwargs):
        claimed.append(kwargs)
        return "new", datetime.now(timezone.utc)

    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "active_panels", active_panels)
    monkeypatch.setattr(todo.todo_sessions, "claim", claim)

    result = asyncio.run(todo._takeover_locked(
        SimpleNamespace(rest=FailingRest()), object(),
        user_id=7, channel_id=99, message_id=11, view=todo.VIEW_WAR,
        page=0, kind="dashboard", trigger="command",
    ))

    assert result is None
    assert claimed == []


def test_takeover_aborts_on_forbidden_old_panel(monkeypatch):
    claimed = []

    class Forbidden(Exception):
        pass

    class Rest:
        async def edit_message(self, *args, **kwargs):
            raise Forbidden

    async def read_owner(*args, **kwargs):
        return True, {"generation": "old", "message_id": 10}

    async def active_panels(*args, **kwargs):
        return True, [{"message_id": 10}]

    async def claim(*args, **kwargs):
        claimed.append(kwargs)

    monkeypatch.setattr(todo.hikari, "ForbiddenError", Forbidden)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "active_panels", active_panels)
    monkeypatch.setattr(todo.todo_sessions, "claim", claim)

    result = asyncio.run(todo._takeover_locked(
        SimpleNamespace(rest=Rest()), object(),
        user_id=7, channel_id=99, message_id=11, view=todo.VIEW_WAR,
        page=0, kind="dashboard", trigger="command",
    ))

    assert result is None
    assert claimed == []


def test_takeover_aborts_before_claim_when_legacy_cleanup_fails(monkeypatch):
    events = []

    class Rest:
        async def edit_message(self, _channel, message_id, **kwargs):
            events.append(("edit", message_id))

    async def read_owner(*args, **kwargs):
        return True, None

    async def active_panels(*args, **kwargs):
        return True, [{"_id": 10}]

    async def cleanup(*args, **kwargs):
        events.append(("cleanup", 10))
        return False

    async def claim(*args, **kwargs):
        events.append(("claim", 11))

    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "active_panels", active_panels)
    monkeypatch.setattr(todo.todo_sessions, "remove_legacy_rows", cleanup)
    monkeypatch.setattr(todo.todo_sessions, "claim", claim)

    result = asyncio.run(todo._takeover_locked(
        SimpleNamespace(rest=Rest()), object(),
        user_id=7, channel_id=99, message_id=11, view=todo.VIEW_WAR,
        page=0, kind="dashboard", trigger="command",
    ))

    assert result is None
    assert events == [("edit", 10), ("cleanup", 10)]


def test_takeover_continues_when_old_panel_is_already_gone(monkeypatch):
    class Gone(Exception):
        pass

    class Rest:
        async def edit_message(self, *args, **kwargs):
            raise Gone

    async def read_owner(*args, **kwargs):
        return True, {"generation": "old", "message_id": 10}

    async def active_panels(*args, **kwargs):
        return True, [{"message_id": 10}]

    async def claim(*args, **kwargs):
        return "new", datetime(2026, 9, 4, tzinfo=timezone.utc)

    async def cleanup(*args, **kwargs):
        return True

    monkeypatch.setattr(todo.hikari, "NotFoundError", Gone)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "active_panels", active_panels)
    monkeypatch.setattr(todo.todo_sessions, "claim", claim)
    monkeypatch.setattr(todo.todo_sessions, "remove_legacy_rows", cleanup)

    result = asyncio.run(todo._takeover_locked(
        SimpleNamespace(rest=Rest()), object(),
        user_id=7, channel_id=99, message_id=11, view=todo.VIEW_WAR,
        page=0, kind="dashboard", trigger="command",
    ))

    assert result is not None


def test_concurrent_new_panels_finish_with_one_latest_owner(monkeypatch):
    owner = None
    edits = []
    deadline = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

    class Rest:
        async def edit_message(self, channel_id, message_id, **kwargs):
            text = _payload_text([
                component.build() for component in kwargs["components"]
            ])
            edits.append((message_id, text))

    async def read_owner(*args, **kwargs):
        return True, dict(owner) if owner else None

    async def active_panels(*args, **kwargs):
        return True, [dict(owner)] if owner else []

    async def claim(*args, **kwargs):
        nonlocal owner
        expected = kwargs["expected_owner"]
        if owner is None:
            assert expected is None
        else:
            assert expected["generation"] == owner["generation"]
        generation = f"gen-{kwargs['message_id']}"
        owner = {
            "_id": "dm:7:99",
            "user_id": 7,
            "channel_id": 99,
            "message_id": kwargs["message_id"],
            "generation": generation,
            "refresh_until": deadline,
        }
        return generation, deadline

    async def cleanup(*args, **kwargs):
        return True

    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "active_panels", active_panels)
    monkeypatch.setattr(todo.todo_sessions, "claim", claim)
    monkeypatch.setattr(todo.todo_sessions, "remove_legacy_rows", cleanup)
    todo._refresh_locks.clear()
    bot = SimpleNamespace(rest=Rest())
    panel = todo._notice(
        "To-do", "Ready", auto_refresh=True, refresh_until=deadline,
    )

    async def activate(message_id):
        ctx = SimpleNamespace(channel_id=99, user=SimpleNamespace(id=7))
        return await todo._activate_auto_panel(
            ctx, bot, object(), SimpleNamespace(id=message_id), panel,
            todo.VIEW_WAR,
        )

    async def exercise():
        return await asyncio.gather(activate(11), activate(12))

    results = asyncio.run(exercise())

    assert results == [True, True]
    assert owner is not None
    current = owner["message_id"]
    previous = 12 if current == 11 else 11
    current_edits = [text for message, text in edits if message == current]
    previous_edits = [text for message, text in edits if message == previous]
    assert "Rechecks about every 10 min" in current_edits[-1]
    assert "make it automatic" in previous_edits[-1]


def test_neutral_footer_preserves_dashboard_controls():
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    active = todo.render_dashboard(
        todo.VIEW_WAR, 0, data, auto_refresh=True
    )
    neutral = todo._manual_fallback_panel(active, checked_at=1_725_000_000)
    active_payload = [component.build() for component in active]
    neutral_payload = [component.build() for component in neutral]

    def ids(payload):
        return {
            node["custom_id"] for node in _walk(payload) if "custom_id" in node
        }

    assert ids(neutral_payload) == ids(active_payload)
    assert "Checked <t:1725000000:R> · Use Check now to update" in _payload_text(
        neutral_payload
    )


def test_navigation_preserves_deadline_and_retired_panel_stays_manual(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    updates = []

    class Ctx:
        guild_id = None
        channel_id = 66
        user = SimpleNamespace(id=77)
        interaction = SimpleNamespace(message=SimpleNamespace(id=55))

        def __init__(self):
            self.responses = []

        async def respond(self, **kwargs):
            self.responses.append(kwargs)

    async def fake_load(*args, **kwargs):
        return data, None

    async def current_owner(*args, **kwargs):
        return True, {
            "_id": "dm:77:66", "message_id": 55, "generation": "gen",
            "refresh_until": until,
        }

    async def update(*args, **kwargs):
        updates.append(kwargs)
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", current_owner)
    monkeypatch.setattr(todo.todo_sessions, "update_navigation", update)
    todo._refresh_locks.clear()
    active_ctx = Ctx()

    asyncio.run(todo._switch(
        active_ctx, todo.VIEW_CWL, "2", object(), object(), mongo=object(),
        trigger="view:cwl",
    ))

    active_payload = [
        component.build()
        for component in active_ctx.responses[0]["components"]
    ]
    assert f"Stops <t:{int(until.timestamp())}:R>" in _payload_text(active_payload)
    assert updates[0]["page"] == 2
    assert "refresh_until" not in updates[0]

    async def different_owner(*args, **kwargs):
        return True, {
            "_id": "dm:77:66", "message_id": 99, "generation": "new",
            "refresh_until": until,
        }

    monkeypatch.setattr(todo.todo_sessions, "read_owner", different_owner)
    retired_ctx = Ctx()
    asyncio.run(todo._switch(
        retired_ctx, todo.VIEW_WAR, "0", object(), object(), mongo=object(),
        trigger="view:war",
    ))

    retired_payload = [
        component.build()
        for component in retired_ctx.responses[0]["components"]
    ]
    retired_text = _payload_text(retired_payload)
    assert "Use Check now to update" in retired_text
    assert "Rechecks" not in retired_text
    assert len(updates) == 1


def test_check_now_reactivates_panel_for_exact_claimed_window(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)

    class Ctx:
        guild_id = None
        channel_id = 66
        user = SimpleNamespace(id=77)
        interaction = SimpleNamespace(message=SimpleNamespace(id=55))

        def __init__(self):
            self.responses = []

        async def respond(self, **kwargs):
            self.responses.append(kwargs)

    async def fake_load(*args, **kwargs):
        assert kwargs["force"] is True
        return data, None

    async def takeover(*args, **kwargs):
        assert kwargs["message_id"] == 55
        assert kwargs["trigger"] == "refresh"
        return "new-generation", until

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo, "_takeover_locked", takeover)
    todo._refresh_locks.clear()
    ctx = Ctx()

    asyncio.run(todo._switch(
        ctx, todo.VIEW_WAR, "war|0", object(), object(), force=True,
        mongo=object(), trigger="refresh",
    ))

    payload = [component.build() for component in ctx.responses[0]["components"]]
    text = _payload_text(payload)
    assert f"Stops <t:{int(until.timestamp())}:R>" in text
    assert "Rechecks about every 10 min" in text


def test_check_now_on_webhook_fallback_stays_manual(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    takeovers = []

    class Ctx:
        guild_id = None
        channel_id = 66
        user = SimpleNamespace(id=77)
        interaction = SimpleNamespace(
            message=SimpleNamespace(id=55, webhook_id=123)
        )

        def __init__(self):
            self.responses = []

        async def respond(self, **kwargs):
            self.responses.append(kwargs)

    async def fake_load(*args, **kwargs):
        return data, None

    async def takeover(*args, **kwargs):
        takeovers.append(kwargs)
        return "gen", datetime.now(timezone.utc)

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo, "_takeover_locked", takeover)
    ctx = Ctx()

    asyncio.run(todo._switch(
        ctx, todo.VIEW_WAR, "war|0", object(), object(), force=True,
        mongo=object(), trigger="refresh",
    ))

    payload = [component.build() for component in ctx.responses[0]["components"]]
    text = _payload_text(payload)
    assert takeovers == []
    assert "Use Check now to update" in text
    assert "Rechecks" not in text


def test_rapid_dm_clicks_queue_before_loading_and_finish_in_order(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    owner = {
        "_id": "dm:77:66", "message_id": 55, "generation": "gen",
        "channel_id": 66, "user_id": 77, "view": todo.VIEW_WAR,
        "page": 0, "refresh_until": until,
    }
    first_load_entered = asyncio.Event()
    release_first_load = asyncio.Event()
    load_count = 0
    responses = []

    class Ctx:
        guild_id = None
        channel_id = 66
        user = SimpleNamespace(id=77)
        interaction = SimpleNamespace(message=SimpleNamespace(id=55))

        def __init__(self, label):
            self.label = label

        async def respond(self, **kwargs):
            responses.append(self.label)

    async def fake_load(*args, **kwargs):
        nonlocal load_count
        load_count += 1
        if load_count == 1:
            first_load_entered.set()
            await release_first_load.wait()
        return data, None

    async def read_owner(*args, **kwargs):
        return True, dict(owner)

    async def update_navigation(*args, **kwargs):
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(
        todo.todo_sessions, "update_navigation", update_navigation
    )
    todo._refresh_locks.clear()

    async def exercise():
        first = asyncio.create_task(todo._switch(
            Ctx("first"), todo.VIEW_WAR, "0", object(), object(),
            mongo=object(), trigger="view:war",
        ))
        await first_load_entered.wait()
        second = asyncio.create_task(todo._switch(
            Ctx("second"), todo.VIEW_PRIVATE, "0", object(), object(),
            mongo=object(), trigger="view:private",
        ))
        await asyncio.sleep(0)
        assert load_count == 1
        release_first_load.set()
        await asyncio.gather(first, second)

    asyncio.run(exercise())

    assert load_count == 2
    assert responses == ["first", "second"]


def test_manual_edit_holds_owner_lock_until_discord_then_auto_uses_new_view(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    owner = {
        "_id": "dm:77:66", "message_id": 55, "generation": "gen",
        "channel_id": 66, "user_id": 77, "view": todo.VIEW_WAR,
        "page": 0, "refresh_until": until,
    }
    manual_entered = asyncio.Event()
    release_manual = asyncio.Event()
    edit_order = []

    class Ctx:
        guild_id = None
        channel_id = 66
        user = SimpleNamespace(id=77)
        interaction = SimpleNamespace(message=SimpleNamespace(id=55))

        async def respond(self, **kwargs):
            manual_entered.set()
            await release_manual.wait()
            edit_order.append("manual")

    class Rest:
        async def edit_message(self, *args, **kwargs):
            edit_order.append("automatic")

    async def fake_load(*args, **kwargs):
        return data, None

    async def read_owner(*args, **kwargs):
        return True, dict(owner)

    async def update_navigation(*args, **kwargs):
        owner["view"] = kwargs["view"]
        owner["page"] = kwargs["page"]
        return True

    async def get_owner(*args, **kwargs):
        return True, dict(owner)

    async def mark(*args, **kwargs):
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "update_navigation", update_navigation)
    monkeypatch.setattr(todo.todo_sessions, "get", get_owner)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", mark)
    todo._refresh_locks.clear()

    async def exercise():
        manual = asyncio.create_task(todo._switch(
            Ctx(), todo.VIEW_PRIVATE, "0", object(), object(), mongo=object(),
            trigger="view:private",
        ))
        await manual_entered.wait()
        automatic = asyncio.create_task(todo._refresh_session(
            dict(owner), SimpleNamespace(rest=Rest()), object(), object(),
        ))
        await asyncio.sleep(0)
        assert edit_order == []
        release_manual.set()
        await manual
        assert await automatic == "updated"

    asyncio.run(exercise())

    assert edit_order == ["manual", "automatic"]
    assert owner["view"] == todo.VIEW_PRIVATE


def test_auto_edit_holds_owner_lock_until_discord_then_manual_wins(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    owner = {
        "_id": "dm:77:66", "message_id": 55, "generation": "gen",
        "channel_id": 66, "user_id": 77, "view": todo.VIEW_WAR,
        "page": 0, "refresh_until": until,
    }
    auto_entered = asyncio.Event()
    release_auto = asyncio.Event()
    edit_order = []

    class Rest:
        async def edit_message(self, *args, **kwargs):
            auto_entered.set()
            await release_auto.wait()
            edit_order.append("automatic")

    class Ctx:
        guild_id = None
        channel_id = 66
        user = SimpleNamespace(id=77)
        interaction = SimpleNamespace(message=SimpleNamespace(id=55))

        async def respond(self, **kwargs):
            edit_order.append("manual")

    async def fake_load(*args, **kwargs):
        return data, None

    async def read_owner(*args, **kwargs):
        return True, dict(owner)

    async def update_navigation(*args, **kwargs):
        owner["view"] = kwargs["view"]
        return True

    async def get_owner(*args, **kwargs):
        return True, dict(owner)

    async def mark(*args, **kwargs):
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "update_navigation", update_navigation)
    monkeypatch.setattr(todo.todo_sessions, "get", get_owner)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", mark)
    todo._refresh_locks.clear()

    async def exercise():
        automatic = asyncio.create_task(todo._refresh_session(
            dict(owner), SimpleNamespace(rest=Rest()), object(), object(),
        ))
        await auto_entered.wait()
        manual = asyncio.create_task(todo._switch(
            Ctx(), todo.VIEW_PRIVATE, "0", object(), object(), mongo=object(),
            trigger="view:private",
        ))
        await asyncio.sleep(0)
        assert edit_order == []
        release_auto.set()
        assert await automatic == "updated"
        await manual

    asyncio.run(exercise())

    assert edit_order == ["automatic", "manual"]
    assert owner["view"] == todo.VIEW_PRIVATE


def test_three_owner_lock_contenders_never_split_the_lock():
    todo._refresh_locks.clear()
    lock_ids = []
    inside = 0
    maximum = 0

    async def contender():
        nonlocal inside, maximum
        lock = todo._refresh_lock("dm:77:66")
        lock_ids.append(id(lock))
        async with lock:
            inside += 1
            maximum = max(maximum, inside)
            await asyncio.sleep(0)
            inside -= 1

    async def exercise():
        await asyncio.gather(*(contender() for _ in range(3)))

    asyncio.run(exercise())

    assert len(set(lock_ids)) == 1
    assert maximum == 1


def test_automatic_refresh_uses_latest_stored_view(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    rest = _Rest()
    marked = []

    async def fake_load(*args, **kwargs):
        return data, None

    async def fake_get(_mongo, owner_id, message_id, generation):
        assert owner_id == "dm:77:66"
        assert message_id == 55
        assert generation == "gen"
        return True, {"view": todo.VIEW_PRIVATE, "page": 0}

    async def fake_mark(_mongo, owner_id, message_id, generation, **kwargs):
        marked.append((owner_id, message_id, generation, kwargs))
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77, "view": todo.VIEW_WAR},
        SimpleNamespace(rest=rest), object(), object(),
    ))

    assert result == "updated"
    assert [(channel, message) for channel, message, _ in rest.edits] == [(66, 55)]
    payload = [component.build() for component in rest.edits[0][2]["components"]]
    assert "Private War Logs" in _payload_text(payload)
    assert "Rechecks about every 10 min" in _payload_text(payload)
    assert marked[0][:3] == ("dm:77:66", 55, "gen")


def test_automatic_notice_keeps_the_stored_stop_time(monkeypatch):
    until = datetime(2026, 8, 6, 15, tzinfo=timezone.utc)
    rest = _Rest()

    async def fake_load(*args, **kwargs):
        assert kwargs["refresh_until"] == until
        return None, todo._notice(
            "Temporary problem", "Try again shortly.", auto_refresh=True,
            refresh_until=kwargs["refresh_until"], checked_at=1_725_000_000,
        )

    async def fake_get(_mongo, _owner_id, _message_id, _generation):
        return True, {
            "view": todo.VIEW_WAR, "page": 0, "refresh_until": until,
        }

    async def fake_mark(*args, **kwargs):
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77,
         "refresh_until": until},
        SimpleNamespace(rest=rest), object(), object(),
    ))

    payload = [component.build() for component in rest.edits[0][2]["components"]]
    assert result == "updated"
    assert f"Stops <t:{int(until.timestamp())}:R>" in _payload_text(payload)


def test_automatic_refresh_reports_failed_when_schedule_cannot_advance(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    postponed = []

    async def fake_load(*args, **kwargs):
        return data, None

    async def fake_get(_mongo, _owner_id, _message_id, _generation):
        return True, {"view": todo.VIEW_WAR, "page": 0}

    async def fake_mark(*args, **kwargs):
        return False

    async def fake_postpone(*args, **kwargs):
        postponed.append((args, kwargs))
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    monkeypatch.setattr(todo.todo_sessions, "postpone", fake_postpone)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "failed"
    assert len(postponed) == 1


def test_automatic_refresh_postpones_mongo_read_failure(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    postponed = []

    async def fake_load(*args, **kwargs):
        return data, None

    async def failed_read(*args, **kwargs):
        return False, None

    async def fake_postpone(*args, **kwargs):
        postponed.append(args[1:4])
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", failed_read)
    monkeypatch.setattr(todo.todo_sessions, "postpone", fake_postpone)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "failed"
    assert postponed == [("dm:77:66", 55, "gen")]


def test_deployed_legacy_panel_keeps_refreshing_until_its_old_deadline(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    until = datetime(2026, 8, 6, 15, tzinfo=timezone.utc)
    marked = []

    async def fake_load(*args, **kwargs):
        return data, None

    async def read_owner(*args, **kwargs):
        return True, None

    async def fake_get(_mongo, owner_id, message_id, generation):
        assert (owner_id, message_id, generation) == ("dm:77:66", 55, None)
        return True, {
            "_id": 55, "view": todo.VIEW_WAR, "page": 0,
            "refresh_until": until,
        }

    async def fake_mark(_mongo, owner_id, message_id, generation, **kwargs):
        marked.append((owner_id, message_id, generation))
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77,
         "refresh_until": until},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "updated"
    assert marked == [("dm:77:66", 55, None)]


def test_legacy_scheduler_discards_row_when_current_owner_exists(monkeypatch):
    discarded = []

    class Rest:
        async def edit_message(self, *args, **kwargs):
            raise AssertionError("retired legacy panel must not be repainted")

    async def fake_load(*args, **kwargs):
        raise AssertionError("superseded legacy row must not load Clash data")

    async def read_owner(*args, **kwargs):
        return True, {
            "_id": "dm:77:66", "message_id": 99, "generation": "current",
        }

    async def discard(_mongo, document_id):
        discarded.append(document_id)
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "read_owner", read_owner)
    monkeypatch.setattr(todo.todo_sessions, "discard", discard)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=Rest()), object(), object(),
    ))

    assert result == "removed"
    assert discarded == [55]


def test_malformed_due_row_is_deleted_without_loading(monkeypatch):
    discarded = []

    async def should_not_load(*args, **kwargs):
        raise AssertionError("malformed row must not load Clash data")

    async def discard(_mongo, document_id):
        discarded.append(document_id)
        return True

    monkeypatch.setattr(todo, "_load", should_not_load)
    monkeypatch.setattr(todo.todo_sessions, "discard", discard)

    result = asyncio.run(todo._refresh_session(
        {"_id": "wrong-key", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "removed"
    assert discarded == ["wrong-key"]


def test_automatic_refresh_removes_missing_message_session(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    removed = []

    class MissingMessage(Exception):
        pass

    class MissingRest:
        async def edit_message(self, *args, **kwargs):
            raise MissingMessage

    async def fake_load(*args, **kwargs):
        return data, None

    async def fake_get(_mongo, _owner_id, _message_id, _generation):
        return True, {"view": todo.VIEW_WAR, "page": 0}

    async def fake_remove(_mongo, owner_id, message_id, generation):
        removed.append((owner_id, message_id, generation))
        return True

    monkeypatch.setattr(todo.hikari, "NotFoundError", MissingMessage)
    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "remove", fake_remove)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=MissingRest()), object(), object(),
    ))

    assert result == "removed"
    assert removed == [("dm:77:66", 55, "gen")]


def test_missing_message_is_postponed_when_mongo_removal_fails(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    postponed = []

    class MissingMessage(Exception):
        pass

    class MissingRest:
        async def edit_message(self, *args, **kwargs):
            raise MissingMessage

    async def fake_load(*args, **kwargs):
        return data, None

    async def fake_get(*args, **kwargs):
        return True, {"view": todo.VIEW_WAR, "page": 0}

    async def failed_remove(*args, **kwargs):
        return False

    async def fake_postpone(*args, **kwargs):
        postponed.append(args[1:4])
        return True

    monkeypatch.setattr(todo.hikari, "NotFoundError", MissingMessage)
    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "remove", failed_remove)
    monkeypatch.setattr(todo.todo_sessions, "postpone", fake_postpone)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=MissingRest()), object(), object(),
    ))

    assert result == "failed"
    assert postponed == [("dm:77:66", 55, "gen")]


def test_automatic_refresh_postpones_transient_failure(monkeypatch):
    postponed = []

    async def failed_load(*args, **kwargs):
        raise RuntimeError("temporary API failure")

    async def fake_postpone(_mongo, owner_id, message_id, generation):
        postponed.append((owner_id, message_id, generation))
        return True

    monkeypatch.setattr(todo, "_load", failed_load)
    monkeypatch.setattr(todo.todo_sessions, "postpone", fake_postpone)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": "dm:77:66", "message_id": 55, "generation": "gen",
         "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "failed"
    assert postponed == [("dm:77:66", 55, "gen")]


def test_auto_refresh_cycle_shares_one_negative_cache_cutoff(monkeypatch):
    cutoffs = []

    async def fake_due(_mongo):
        return [
            {"_id": 1, "channel_id": 10, "user_id": 100},
            {"_id": 2, "channel_id": 20, "user_id": 200},
        ]

    async def fake_refresh(*args, **kwargs):
        cutoffs.append(kwargs["recheck_negative_after"])
        return "updated"

    monkeypatch.setattr(todo.todo_sessions, "due", fake_due)
    monkeypatch.setattr(todo, "_refresh_session", fake_refresh)

    before = datetime.now(timezone.utc).timestamp()
    counts = asyncio.run(todo.run_auto_refresh_cycle(object(), object(), object()))
    after = datetime.now(timezone.utc).timestamp()

    assert counts["updated"] == 2
    assert len(cutoffs) == 2
    assert cutoffs[0] == cutoffs[1]
    expected_min = before - todo.todo_sessions.REFRESH_INTERVAL_SECONDS
    expected_max = after - todo.todo_sessions.REFRESH_INTERVAL_SECONDS
    assert expected_min - 0.01 <= cutoffs[0] <= expected_max + 0.01
