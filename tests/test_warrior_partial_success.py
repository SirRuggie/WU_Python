"""Detached REST/cache objects prove freshness rather than aliasing a fake."""

import asyncio
import copy
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import hikari
import pytest
from extensions.commands import warrior
from extensions.warrior import core
from tests.test_warrior_setup import role
from tests.test_warrior_speed import fixture


def test_known_noops_share_one_fresh_guard_without_replacing_roles():
    async def check():
        c, m, b, _ = fixture()
        result = await core.change_roles(b, m, c, add=[61], remove=[60])
        assert result["unchanged"] == ["Role 61", "Role 60"]
        assert b.rest.fetch_guild.await_count == 1
        assert b.rest.fetch_roles.await_count == 1
        assert b.rest.fetch_member.await_count == 3
        b.rest.add_role_to_member.assert_not_awaited()
        b.rest.remove_role_from_member.assert_not_awaited()
        assert not hasattr(b.rest, "edit_member")

    asyncio.run(check())


def test_role_definition_is_reread_before_second_real_write():
    async def check():
        c, m, b, by_id = fixture()
        c["member"].role_ids = []
        cached = copy.deepcopy(by_id)
        b.cache.get_member = lambda g, u: cached[u]
        original = copy.deepcopy(c["roles"])
        changed = copy.deepcopy(original)
        next(r for r in changed if r.id == 61).permissions = (
            hikari.Permissions.ADMINISTRATOR
        )
        current = [original]
        b.rest.fetch_roles.side_effect = lambda g: copy.deepcopy(current[0])

        async def added(g, u, rid, **kwargs):
            target = copy.deepcopy(by_id[u])
            target.role_ids.append(rid)
            by_id[u] = target
            current[0] = changed

        b.rest.add_role_to_member.side_effect = added
        result = await core.change_roles(b, m, c, add=[60, 61])
        assert result["added"] == ["Role 60"] and result["failed"]
        assert b.rest.add_role_to_member.await_count == 1
        assert b.rest.fetch_roles.await_count == 2
        assert not next(r for r in c["roles"] if r.id == 61).permissions

    asyncio.run(check())


def test_confirmed_add_then_remove_uses_fresh_target_and_remains_incremental():
    async def check():
        c, m, b, by_id = fixture()

        async def added(g, u, rid, **kwargs):
            target = copy.deepcopy(by_id[u])
            target.role_ids.append(rid)
            by_id[u] = target

        b.rest.add_role_to_member.side_effect = added
        result = await core.change_roles(b, m, c, add=[60], remove=[60])
        assert result["added"] == ["Role 60"] and result["removed"] == ["Role 60"]
        b.rest.add_role_to_member.assert_awaited_once()
        b.rest.remove_role_from_member.assert_awaited_once()
        assert b.rest.fetch_roles.await_count == 2
        assert not hasattr(b.rest, "edit_member")

    asyncio.run(check())


@pytest.mark.parametrize(
    "verb,demote_after", [("quick", 1), ("quick", 3), ("set_th", 1)]
)
def test_panels_preserve_confirmed_changes_after_demotion(
    monkeypatch, verb, demote_after
):
    async def check():
        c, m, b, by_id = fixture()
        c["roles"] += [role(65, 2), role(66, 2)]
        b.cache.get_member = lambda g, u: copy.deepcopy(
            {20: c["actor"], 30: c["member"], 1: c["me"]}[u]
        )
        cfg = {
            "roles": {
                "family": 60,
                "recruit": 65,
                "strike_accepted": 66,
                "visitor": 61,
            },
            "townhalls": {"16": 60, "17": 61},
        }
        monkeypatch.setattr(core, "settings", AsyncMock(return_value=cfg))
        monkeypatch.setattr(
            core, "session", AsyncMock(return_value=({"_id": "partial"}, c))
        )
        monkeypatch.setattr(warrior, "home", AsyncMock(return_value=[]))
        applied = []

        async def added(g, u, rid, **kwargs):
            applied.append(rid)
            target = copy.deepcopy(by_id[u])
            target.role_ids.append(rid)
            by_id[u] = target
            if len(applied) == demote_after:
                lost = copy.deepcopy(by_id[20])
                lost.role_ids = []
                by_id[20] = lost

        b.rest.add_role_to_member.side_effect = added
        ctx = S(
            guild_id=10,
            user=S(id=20),
            defer=AsyncMock(),
            interaction=S(values=["60"], edit_initial_response=AsyncMock()),
        )
        await warrior.action(ctx, "partial:" + verb, mongo=m, bot=b, coc_client=None)
        output = repr(ctx.interaction.edit_initial_response.call_args)
        assert "Confirmed role changes" in output and f"{len(applied)} added" in output
        assert "Role 60" in output and "Recruitment Team" in output
        assert len(applied) == demote_after
        b.rest.remove_role_from_member.assert_not_awaited()
        args = ctx.interaction.edit_initial_response.call_args.kwargs
        assert (
            args["user_mentions"] is False
            and args["role_mentions"] is False
            and args["mentions_everyone"] is False
        )
        m.warrior_audit.update_one.assert_awaited()

    asyncio.run(check())


def test_post_write_status_failure_preserves_confirmed_result(monkeypatch):
    async def check():
        c, m, b, _ = fixture()
        monkeypatch.setattr(
            core, "session", AsyncMock(return_value=({"_id": "status"}, c))
        )
        monkeypatch.setattr(
            core,
            "refresh_target",
            AsyncMock(side_effect=RuntimeError("fixture status outage")),
        )
        ctx = S(
            guild_id=10,
            user=S(id=20),
            defer=AsyncMock(),
            interaction=S(values=["60"], edit_initial_response=AsyncMock()),
        )
        await warrior.action(ctx, "status:role_add", mongo=m, bot=b, coc_client=None)
        output = repr(ctx.interaction.edit_initial_response.call_args)
        assert (
            "Confirmed role changes" in output
            and "1 added" in output
            and "Role 60" in output
        )
        assert b.rest.add_role_to_member.await_count == 1

    asyncio.run(check())


def test_partial_panel_bounds_emoji_text_and_has_no_repeat_action():
    components = warrior.partial_role_panel(
        "fixture",
        {"added": ["😀" * 100] * 100, "removed": ["😀" * 100] * 100},
        "😀" * 1000,
    )
    payload = components[0].build()[0]

    def texts(node):
        return ([node["content"]] if node.get("type") == 10 else []) + [
            t for child in node.get("components", []) for t in texts(child)
        ]

    assert sum(len(text.encode("utf-16-le")) // 2 for text in texts(payload)) <= 4000
    assert "100 added, 100 removed" in repr(payload)
    assert "Return to Warrior Setup" in repr(payload) and "Retry" not in repr(payload)
