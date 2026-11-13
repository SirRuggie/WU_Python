import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from extensions.commands.tickets import link_account as la
from extensions.commands.tickets import player_info
from utils import clashperk_link_writes as writes
from utils.clan_weight_client import WeightClientError

TICKET = {"_id": "T1", "user_id": 123, "mentioned_tags": ["#2pp", "nope", "#QCC", "#2PP"]}


def text(components):
    return repr([c.build() for c in components])


@pytest.fixture
def env(monkeypatch):
    state = SimpleNamespace(ticket=dict(TICKET), access=None, calls=[])

    async def get_ticket(ctx, mongo, ticket_id):
        state.calls.append(("ticket", ticket_id))
        return state.ticket

    async def bridge(action, *, actor_id):
        state.calls.append(("access", actor_id))
        if state.access:
            raise state.access
        return {"allowed": True}

    state.create = AsyncMock(return_value=writes.LinkResult(writes.LINKED, "#2PP", "Linked in ClashPerk.", False, True))
    state.refresh = AsyncMock(return_value=(state.ticket, True))
    monkeypatch.setattr(player_info, "_get_ticket", get_ticket)
    monkeypatch.setattr(la, "bridge", bridge)
    monkeypatch.setattr(writes, "create_link", state.create)
    monkeypatch.setattr(player_info, "refresh_accounts", state.refresh)
    return state


CTX = SimpleNamespace(user=SimpleNamespace(id=999))


def run_link(tag="#2PP"):
    return asyncio.run(la.link(CTX, None, None, "T1", tag))


def test_links_applicant_and_refreshes(env):
    out = text(run_link())
    env.create.assert_awaited_once_with(123, "#2PP")
    env.refresh.assert_awaited_once()
    assert "Linked in ClashPerk." in out and "Linked Player Information" in out
    # Access is checked right before the write.
    assert env.calls[-1] == ("access", 999)


def test_without_permission_nothing_is_written(env):
    env.access = WeightClientError("You need weight saving access.", code="forbidden")
    out = text(run_link())
    assert la.NO_PERMISSION in out
    env.create.assert_not_awaited()
    env.refresh.assert_not_awaited()


def test_bridge_unavailable_writes_nothing(env):
    env.access = WeightClientError("Weight saving is unavailable now. Try again later.", code="unavailable")
    assert "unavailable now" in text(run_link())
    env.create.assert_not_awaited()


def test_non_recruiter_never_reaches_permission_or_write(env):
    env.ticket = None
    out = text(run_link())
    assert la.NOT_RECRUITER in out
    assert all(call[0] != "access" for call in env.calls)
    env.create.assert_not_awaited()


def test_other_owner_shows_escaped_name_and_changes_nothing(env):
    env.create.return_value = writes.LinkResult(writes.OTHER_OWNER, "#2PP", "x", owner="evil*_name")
    out = text(run_link())
    assert "different Discord user" in out and "evil\\\\*\\\\_name" in out
    env.refresh.assert_not_awaited()


@pytest.mark.parametrize("status", [writes.REJECTED, writes.UNAVAILABLE, writes.UNKNOWN, writes.INVALID])
def test_failed_link_does_not_refresh(env, status):
    env.create.return_value = writes.LinkResult(status, "#2PP", "ClashPerk rejected this link. Nothing was changed.")
    out = text(run_link())
    assert "rejected" in out
    env.refresh.assert_not_awaited()


def test_already_linked_still_refreshes(env):
    env.create.return_value = writes.LinkResult(writes.ALREADY_LINKED, "#2PP", "already linked")
    run_link()
    env.refresh.assert_awaited_once()


def test_refresh_busy_is_reported_after_link(env):
    env.refresh.side_effect = player_info.RefreshBusy("A player refresh is already running for this ticket.")
    out = text(run_link())
    assert "Linked in ClashPerk." in out and "did not refresh" in out


def test_invalid_typed_tag_never_writes(env):
    out = text(asyncio.run(la._confirm_or_error(CTX, None, "T1", "not a tag")))
    assert "valid player tag" in out
    env.create.assert_not_awaited()


def test_confirm_view_asks_before_write(env):
    out = text(asyncio.run(la._confirm_or_error(CTX, None, "T1", "2pp")))
    assert "ticket_link_confirm:T1|#2PP" in out and "Link `#2PP` to <@123>" in out
    env.create.assert_not_awaited()


def test_typed_tags_are_valid_unique_and_not_already_linked(monkeypatch):
    monkeypatch.setattr(la.account_sync, "snapshot_from_ticket",
                        lambda t: SimpleNamespace(current_accounts=[SimpleNamespace(tag="#QCC")]))
    assert la.typed_tags(TICKET) == ["#2PP"]


def test_start_view_without_typed_tags_has_only_entry_button(monkeypatch):
    monkeypatch.setattr(la.account_sync, "snapshot_from_ticket", lambda t: SimpleNamespace(current_accounts=[]))
    out = text(la.start_view({"_id": "T1", "user_id": 123}))
    assert "ticket_link_tag:T1" in out and "ticket_link_pick" not in out


def test_panel_has_link_control():
    ticket = {"_id": "T1", "user_id": 123}
    assert "ticket_link:T1" in text(player_info.panel(ticket))
