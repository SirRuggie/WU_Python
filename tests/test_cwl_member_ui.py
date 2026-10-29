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
    assert [len(row.components) for row in rows] == [1, 2, 2, 1]  # Select, pages, actions, clear.


def test_closed_signups_are_read_only_and_without_dead_pagination():
    saved = [{"tag": "#P2Y", "pool": "main", "player_name": "Player"}]
    closed = session("my_signups", season=CLOSED, signups=saved)
    assert "Player · Main CWL" in member._main_text(closed)
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


def test_highest_town_hall_first_with_stable_ties_unknown_last_and_review_order():
    rows = [
        {"tag": "#B", "town_hall": 12, "name": "Low"},
        {"tag": "#Z", "town_hall": 18, "name": "High Z"},
        {"tag": "#A", "town_hall": 18, "name": "High A"},
        {"tag": "#Q", "town_hall": None, "name": "Unknown"},
        {"tag": "#R", "town_hall": "bad", "name": "Malformed"},
    ]
    current = session("select_accounts", accounts=rows)
    current.pool = "lazy"
    assert [x["tag"] for x in member._accounts(current)] == ["#A", "#Z", "#B", "#Q", "#R"]
    assert rows[0]["tag"] == "#B"  # Sorting does not mutate the provider snapshot.
    current.selected = {"#B", "#Z", "#A"}
    current.screen = "review"
    text = member._main_text(current)
    assert text.index("High A") < text.index("High Z") < text.index("Low")


def test_multi_page_selection_has_clear_next_and_keeps_all_choices():
    from test_cwl_discord_member import Context
    rows = [{"tag": f"#P{i:03}", "name": f"Player {i}", "town_hall": 18 - i // 5}
            for i in reversed(range(31))]
    current = session("select_accounts", accounts=rows)
    current.pool = "lazy"
    token = "page-flow"
    member._sessions[token] = current

    def button(action):
        return next(b for row in member._components(token, current) for b in row.components
                    if getattr(b, "custom_id", "").startswith(f"cwl_member_{action}:"))

    async def click(action, values=()):
        await member._handle(Context(values=values), f"{token}:{current.version}", action)

    async def run():
        text = member._main_text(current)
        assert "one or more" in text and "Page 1 of 3" in text
        assert "Next page" in text and "stay selected" in text
        assert button("next").style == hikari.ButtonStyle.PRIMARY
        assert button("review").is_disabled
        menu = member._components(token, current)[0].components[0]
        first = [o.value for o in menu.options[:2]]
        assert menu.placeholder == "Choose one or more accounts"
        await click("select", first)
        await click("next")
        second = member._components(token, current)[0].components[0].options[0].value
        await click("select", [second])
        await click("next")
        assert "Page 3 of 3" in member._main_text(current)
        assert "last page" in member._main_text(current)
        assert button("next").is_disabled
        assert button("review").label == "Review signup"
        assert button("review").style == hikari.ButtonStyle.PRIMARY
        assert current.selected == {*first, second}
        await click("prev")
        await click("select", [])  # Deselect this page only.
        assert current.selected == set(first)
        await click("prev")
        menu = member._components(token, current)[0].components[0]
        assert {o.value for o in menu.options if o.is_default} == set(first)
        await click("review")
        assert current.screen == "review"
        assert current.selected == set(first)

    try:
        asyncio.run(run())
    finally:
        member._sessions.pop(token, None)


def test_public_cwl_group_contains_only_signup_and_retired_staff_group_stays_unregistered():
    from extensions.commands import cwl_dashboard
    assert member.cwl.name == "cwl"
    assert set(member.cwl.subcommands) == {"signup"}
    assert member.cwl.default_member_permissions in (hikari.UNDEFINED, None)
    registered = [getattr(x, "_command", None) for x in member.loader._loadables]
    assert registered == [member.cwl]
    assert not cwl_dashboard.cwl.subcommands
    assert not any(getattr(x, "_command", None) for x in cwl_dashboard.loader._loadables)


def test_signup_command_opens_private_home_without_dashboard_link_or_extra_click():
    from test_cwl_discord_member import Context
    from unittest.mock import patch
    ctx = Context()

    async def request(action, **fields):
        # Initial response must acknowledge privately before any network wait.
        assert len(ctx.followups) == 1
        assert action == "view"
        assert fields["include_accounts"] is False
        return {"season": OPEN, "signups": [], "accounts": [], "accounts_status": "not_loaded"}

    async def run():
        with patch("utils.cwl_member_client.request", request):
            await member.CwlMember.invoke(SimpleNamespace(), ctx)

    old_tokens = set(member._sessions)
    try:
        asyncio.run(run())
        initial = ctx.followups[0][1]
        assert initial["flags"] & hikari.MessageFlag.EPHEMERAL
        assert initial["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2
        assert initial["user_mentions"] is False
        assert len(initial["components"][0].components) == 1  # Loading text only.
        rendered = ctx.interaction.edits[-1]["components"][0]
        controls = [b for row in rendered.components[1:] for b in row.components]
        assert {b.custom_id.split(":")[0] for b in controls} == {
            "cwl_member_signup", "cwl_member_my_signups", "cwl_member_assignments"}
        assert all(b.style != hikari.ButtonStyle.LINK for b in controls)
        assert "dashboard" not in rendered.components[0].content.lower()
    finally:
        for token in set(member._sessions) - old_tokens:
            member._sessions.pop(token, None)


def test_signup_command_rejects_other_server_before_loading():
    from test_cwl_discord_member import Context
    from unittest.mock import patch
    ctx = Context(guild_id=999)
    with patch("utils.cwl_member_client.request") as request:
        asyncio.run(member.CwlMember.invoke(SimpleNamespace(), ctx))
    request.assert_not_called()
    assert ctx.interaction.edits == []
    assert ctx.followups[0][1]["ephemeral"] is True
