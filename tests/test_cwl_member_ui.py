"""Rendered private CWL member panels and navigation affordances."""

import asyncio
import time
from types import SimpleNamespace

import hikari

from extensions.commands import cwl_member as member
from utils.constants import GOLDENROD_ACCENT


GUILD_ID = 644963518025826315
OPEN = {"id": 9, "label": "October CWL", "status": "draft", "signup_open": True}
CLOSED = {"id": 9, "label": "October CWL", "status": "archived", "signup_open": False}


def session(screen, *, season=OPEN, **view):
    return member.MemberSession(123, GUILD_ID, time.monotonic(), screen=screen,
                                view={"season": season, **view})


def ids(rows):
    return [button.custom_id.split(":", 1)[0] for row in rows for button in row.components
            if hasattr(button, "custom_id")]


def test_panel_serializes_one_goldenrod_container_and_short_rows():
    home = session("home")
    built, files = member._panel(member._main_text(home), member._components("panel", home))[0].build()
    assert not files
    assert built["type"] == hikari.ComponentType.CONTAINER
    assert int(built["accent_color"]) == int(GOLDENROD_ACCENT)
    assert built["components"][0]["content"].startswith("## CWL · October CWL")
    assert [len(row["components"]) for row in built["components"][1:]] == [2, 1]

    pools = session("signup_pool")
    assert "no heroes upgrading" in member._main_text(pools)
    assert "upgrades are fine" in member._main_text(pools)
    assert [len(row.components) for row in member._components("panel", pools)] == [2, 2]


def test_select_menu_owns_account_list_and_allows_page_deselection():
    accounts = [{"tag": f"#P{i:02d}", "name": f"Player {i}", "verified": True, "town_hall": 17}
                for i in range(16)]
    panel = session("select_accounts", accounts=accounts)
    panel.pool = "lazy"
    panel.selected = {"#P00", "#P15"}
    rows = member._components("panel", panel)
    assert "Player 0" not in member._main_text(panel)
    assert rows[0].components[0].min_values == 0
    assert rows[0].components[0].options[0].is_default
    assert [len(row.components) for row in rows] == [1, 2, 1, 2]  # Select, actions, clear, pages.


def test_closed_signups_are_read_only_and_without_dead_pagination():
    saved = [{"tag": "#P2Y", "pool": "main", "player_name": "Player"}]
    closed = session("my_signups", season=CLOSED, signups=saved)
    assert "Player · #P2Y · Main" in member._main_text(closed)
    assert ids(member._components("panel", closed)) == ["cwl_member_home"]
    home = session("home", season=CLOSED)
    assert member._components("panel", home)[0].components[0].is_disabled


def test_withdrawal_identifies_account_and_published_instructions_have_every_page():
    saved = [{"tag": "#P2Y", "pool": "lazy", "player_name": "Player"}]
    withdraw = session("withdraw_confirm", signups=saved)
    withdraw.pending_tag = "#P2Y"
    assert "Player" in member._main_text(withdraw)
    assert "#P2Y" in member._main_text(withdraw)
    assert "Lazy" in member._main_text(withdraw)

    instructions = "First line\n" + "A" * 1900
    assigned = session("assignments", published={"joining_instructions": instructions}, assignments=[
        {"tag": "#P2Y", "player_name": "Player", "assigned_clan_name": "Clan"}
    ])
    assert "cwl_member_instructions" in ids(member._components("panel", assigned))
    assigned.screen = "instructions"
    pages = member._instruction_pages(assigned)
    assert len(pages) > 1
    assert "".join(pages) == "First line\n" + "A" * 1900
    for index, page in enumerate(pages):
        assigned.page = index
        assert page in member._main_text(assigned)


def test_legacy_entry_edit_clears_old_content_when_upgrading_to_v2():
    edited = []

    class Interaction:
        message = SimpleNamespace(flags=hikari.MessageFlag.EPHEMERAL)

        async def edit_initial_response(self, **kwargs):
            edited.append(kwargs)

    ctx = SimpleNamespace(interaction=Interaction())
    panel = session("home")
    asyncio.run(member._edit(ctx, "panel", panel))
    assert edited[0]["content"] is None
    assert edited[0]["embeds"] == []
    built, _ = edited[0]["components"][0].build()
    assert built["type"] == hikari.ComponentType.CONTAINER


def test_no_season_panel_has_clear_status_and_no_dead_controls():
    home = session("home", season=None)
    assert "not set up" in member._main_text(home)
    assert member._components("panel", home) == []


def test_pool_change_holds_when_account_provider_is_unavailable():
    saved = [{"tag": "#P2Y", "pool": "lazy", "player_name": "Player"}]
    current = session("signup_action", signups=saved, accounts_status="ok")
    current.pending_tag = "#P2Y"
    current.source_pools["#P2Y"] = "lazy"
    member._sessions["outage"] = current
    edits = []

    class Interaction:
        guild_id = GUILD_ID
        member = object()

        async def edit_initial_response(self, **kwargs):
            edits.append(kwargs)

    async def respond(*_args, **_kwargs):
        pass

    ctx = SimpleNamespace(user=SimpleNamespace(id=123), interaction=Interaction(), respond=respond)

    async def request(action, **_kwargs):
        assert action == "view"
        return {"season": OPEN, "signups": saved, "accounts": [], "accounts_status": "unavailable"}

    from unittest.mock import patch
    try:
        with patch("utils.cwl_member_client.request", request):
            asyncio.run(member._handle(ctx, "outage:0", "change_pool"))
        assert current.screen == "signup_action"
        assert "temporarily unavailable" in edits[-1]["components"][0].components[0].content
    finally:
        member._sessions.pop("outage", None)
