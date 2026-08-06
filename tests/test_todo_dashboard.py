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


def test_dm_webhook_fallback_is_not_registered_for_automatic_edits(monkeypatch):
    recorded = []

    async def fake_record(*args, **kwargs):
        recorded.append((args, kwargs))

    monkeypatch.setattr(todo.todo_sessions, "record", fake_record)
    ctx = SimpleNamespace(
        guild_id=None, channel_id=99, user=SimpleNamespace(id=7),
    )
    message = SimpleNamespace(id=22, webhook_id=123)

    asyncio.run(todo._record_panel(ctx, object(), message, todo.VIEW_WAR))

    assert recorded == []


def test_guild_panel_is_not_registered_for_automatic_edits(monkeypatch):
    recorded = []

    async def fake_record(*args, **kwargs):
        recorded.append((args, kwargs))

    monkeypatch.setattr(todo.todo_sessions, "record", fake_record)
    ctx = SimpleNamespace(
        guild_id=123, channel_id=99, user=SimpleNamespace(id=7),
    )

    asyncio.run(todo._record_panel(
        ctx, object(), SimpleNamespace(id=22), todo.VIEW_WAR
    ))

    assert recorded == []


def test_panel_is_promoted_only_after_session_registration(monkeypatch):
    rest = _Rest()
    ctx = SimpleNamespace(channel_id=99)
    message = SimpleNamespace(id=11)

    async def rejected(*args, **kwargs):
        return False

    monkeypatch.setattr(todo, "_record_response", rejected)
    activated = asyncio.run(todo._activate_auto_panel(
        ctx, SimpleNamespace(rest=rest), object(), message, ["active"],
        todo.VIEW_WAR,
    ))
    assert activated is False
    assert rest.edits == []

    async def accepted(*args, **kwargs):
        return True

    monkeypatch.setattr(todo, "_record_response", accepted)
    activated = asyncio.run(todo._activate_auto_panel(
        ctx, SimpleNamespace(rest=rest), object(), message, ["active"],
        todo.VIEW_WAR,
    ))
    assert activated is True
    assert rest.edits == [(99, 11, {"components": ["active"]})]


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


def test_automatic_refresh_uses_latest_stored_view(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    rest = _Rest()
    marked = []

    async def fake_load(*args, **kwargs):
        return data, None

    async def fake_get(_mongo, message_id):
        assert message_id == 55
        return {"view": todo.VIEW_PRIVATE, "page": 0}

    async def fake_mark(_mongo, message_id, **kwargs):
        marked.append((message_id, kwargs))
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77, "view": todo.VIEW_WAR},
        SimpleNamespace(rest=rest), object(), object(),
    ))

    assert result == "updated"
    assert [(channel, message) for channel, message, _ in rest.edits] == [(66, 55)]
    payload = [component.build() for component in rest.edits[0][2]["components"]]
    assert "Private War Logs" in _payload_text(payload)
    assert "Rechecks about every 10 min" in _payload_text(payload)
    assert marked[0][0] == 55


def test_automatic_notice_keeps_the_stored_stop_time(monkeypatch):
    until = datetime(2026, 8, 6, 15, tzinfo=timezone.utc)
    rest = _Rest()

    async def fake_load(*args, **kwargs):
        assert kwargs["refresh_until"] == until
        return None, todo._notice(
            "Temporary problem", "Try again shortly.", auto_refresh=True,
            refresh_until=kwargs["refresh_until"], checked_at=1_725_000_000,
        )

    async def fake_get(_mongo, _message_id):
        return {"view": todo.VIEW_WAR, "page": 0, "refresh_until": until}

    async def fake_mark(*args, **kwargs):
        return True

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77,
         "refresh_until": until},
        SimpleNamespace(rest=rest), object(), object(),
    ))

    payload = [component.build() for component in rest.edits[0][2]["components"]]
    assert result == "updated"
    assert f"Stops <t:{int(until.timestamp())}:R>" in _payload_text(payload)


def test_automatic_refresh_reports_failed_when_schedule_cannot_advance(monkeypatch):
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}

    async def fake_load(*args, **kwargs):
        return data, None

    async def fake_get(_mongo, _message_id):
        return {"view": todo.VIEW_WAR, "page": 0}

    async def fake_mark(*args, **kwargs):
        return False

    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "mark_refreshed", fake_mark)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "failed"


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

    async def fake_get(_mongo, _message_id):
        return {"view": todo.VIEW_WAR, "page": 0}

    async def fake_remove(_mongo, message_id):
        removed.append(message_id)
        return True

    monkeypatch.setattr(todo.hikari, "NotFoundError", MissingMessage)
    monkeypatch.setattr(todo, "_load", fake_load)
    monkeypatch.setattr(todo.todo_sessions, "get", fake_get)
    monkeypatch.setattr(todo.todo_sessions, "remove", fake_remove)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=MissingRest()), object(), object(),
    ))

    assert result == "removed"
    assert removed == [55]


def test_automatic_refresh_postpones_transient_failure(monkeypatch):
    postponed = []

    async def failed_load(*args, **kwargs):
        raise RuntimeError("temporary API failure")

    async def fake_postpone(_mongo, message_id):
        postponed.append(message_id)
        return True

    monkeypatch.setattr(todo, "_load", failed_load)
    monkeypatch.setattr(todo.todo_sessions, "postpone", fake_postpone)
    todo._refresh_locks.clear()

    result = asyncio.run(todo._refresh_session(
        {"_id": 55, "channel_id": 66, "user_id": 77},
        SimpleNamespace(rest=_Rest()), object(), object(),
    ))

    assert result == "failed"
    assert postponed == [55]


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
