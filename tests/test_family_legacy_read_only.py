"""Every old clan edit action must stay read-only, including stale modals."""
import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from extensions.commands.clan.dashboard import update_clan_info, update_clan_info_general
from extensions.commands.clan.dashboard.read_only_clan import show_clan


def handlers():
    for module in (update_clan_info, update_clan_info_general):
        for node in ast.parse(Path(module.__file__).read_text()).body:
            if isinstance(node, ast.AsyncFunctionDef):
                yield module, node.name


@pytest.mark.parametrize("module,name", list(handlers()), ids=lambda value: getattr(value, "__name__", str(value)))
def test_legacy_action_reads_current_values_without_any_mutation(module, name):
    row = {"tag": "#P0LYQ", "name": "@everyone [External](https://example.test)", "type": "CWL", "logo": "https://images.example/logo.png"}
    collection = NS(find_one=AsyncMock(return_value=row))
    for method in ("update_one", "delete_one", "insert_one", "replace_one"):
        setattr(collection, method, AsyncMock(side_effect=AssertionError("Legacy write forbidden")))
    mongo = NS(clans=collection)
    ctx = NS(member=NS(get_roles=lambda: [NS(id=993015846442127420)]), respond=AsyncMock())
    asyncio.run(getattr(module, name).__wrapped__._func(ctx=ctx, action_id="confirm_#P0LYQ", mongo=mongo))
    response = ctx.respond.await_args
    assert "https://dash.warriorsunited.cc/clans/%23P0LYQ" in response.args[0]
    assert "Clan type: CWL" in response.args[0]
    assert "@everyone" not in response.args[0]
    assert len(response.args[0]) <= 2000
    assert response.kwargs["user_mentions"] is False
    assert response.kwargs["role_mentions"] is False
    assert response.kwargs["mentions_everyone"] is False
    for method in ("update_one", "delete_one", "insert_one", "replace_one"):
        getattr(collection, method).assert_not_awaited()


def test_unauthorized_legacy_control_does_not_read_clan():
    clans = NS(find_one=AsyncMock())
    ctx = NS(member=NS(get_roles=lambda: []), respond=AsyncMock())
    asyncio.run(show_clan(ctx, NS(clans=clans), "#P0LYQ"))
    clans.find_one.assert_not_awaited()
    assert "role required" in ctx.respond.await_args.args[0]
