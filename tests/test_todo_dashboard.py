"""Regression tests for /todo rendering and component routing."""

import asyncio

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
