"""Private flag search handlers over fictional identities; no Discord or Mongo."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from functools import partial
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions import components as dispatcher
from extensions.commands.tickets import console, flags
from tests.test_component_state import _Collection
from utils import component_state

OWNER = 123456789012345678
GUILD = 223456789012345678
TARGET = 323456789012345678
TOKEN = "a" * 32


def nodes(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from nodes(child)
    elif isinstance(value, (tuple, list)):
        for child in value:
            yield from nodes(child)


def built(components):
    return list(nodes([component.build() for component in components]))


def ctx(*, owner=OWNER, guild=GUILD, values=(), tag="#ABC123"):
    return NS(
        user=NS(id=owner), guild_id=guild, member=NS(guild_id=guild),
        interaction=NS(values=list(values),
                       components=[[NS(custom_id="player_tag", value=tag)]],
                       edit_initial_response=AsyncMock()),
        defer=AsyncMock(), respond=AsyncMock(), respond_with_modal=AsyncMock(),
    )


def state(**changes):
    return {"_id": TOKEN, "type": "ticket_flags_lookup", "owner_id": OWNER,
            "guild_id": GUILD, "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
            **changes}


def mongo(*documents):
    return NS(component_state=_Collection(documents), button_store=_Collection())


@pytest.fixture
def allowed(monkeypatch):
    permission = AsyncMock(return_value=True)
    monkeypatch.setattr(console.perms, "is_recruiter", permission)
    return permission


def test_hub_check_flags_label_and_layout_version():
    view = console.build_hub_actions({"recruits": [], "account": [], "staff": []},
                                     counts={"recruits": 0, "account": 0, "staff": 0}, total=0)
    button = next(n for n in built(view) if n.get("custom_id") == "ticket_v2_flags_lookup:hub")
    assert button["label"] == "Check flags"
    assert console.HUB_LAYOUT_VERSION > 17


def test_old_button_opens_private_native_panel_with_bound_fixed_lifetime(allowed):
    c, m = ctx(), mongo()
    asyncio.run(console.flags_lookup_open(c, "hub", mongo=m))
    c.defer.assert_awaited_once_with(ephemeral=True)
    c.respond_with_modal.assert_not_awaited()
    answer = c.interaction.edit_initial_response.call_args.kwargs
    panel = built(answer["components"])
    text = "\n".join(n.get("content", "") for n in panel)
    assert "## Check flags" in text
    assert "Select a member, or search by player tag." in text
    assert "Discord ID" not in text
    pick = next(n for n in panel if n.get("type") == hikari.ComponentType.USER_SELECT_MENU)
    assert pick["placeholder"] == "Select a member"
    assert pick["min_values"] == pick["max_values"] == 1
    tag_button = next(n for n in panel if n.get("label") == "Search by player tag")
    token = pick["custom_id"].split(":", 1)[1]
    assert tag_button["custom_id"] == "ticket_v2_flags_tag_open:" + token
    saved = m.component_state.documents[token]
    assert saved["type"] == "ticket_flags_lookup"
    assert saved["owner_id"] == OWNER and saved["guild_id"] == GUILD
    assert saved["expires_at"] - saved["created_at"] == component_state.STATE_TTL
    assert all(answer[k] is False for k in ["user_mentions", "role_mentions", "mentions_everyone"])
    assert len([n for n in panel if "type" in n]) <= 40
    assert not m.button_store.documents


@pytest.mark.parametrize("action", ["member", "tag_open", "tag_submit"])
@pytest.mark.parametrize("bad", ["owner", "guild", "type", "expired", "missing", "permission"])
def test_every_private_action_rechecks_session_and_recruiter(allowed, monkeypatch, action, bad):
    d = state()
    if bad == "owner": d["owner_id"] += 1
    if bad == "guild": d["guild_id"] += 1
    if bad == "type": d["type"] = "ticket_member_history"
    if bad == "expired": d["expires_at"] = datetime.now(timezone.utc) - timedelta(seconds=1)
    if bad == "permission": allowed.return_value = False
    m = mongo(*([] if bad == "missing" else [d]))
    c = ctx(values=[str(TARGET)])
    lookup = AsyncMock()
    monkeypatch.setattr(flags, "show_flags", lookup)
    fn = {"member": "flags_lookup_pick", "tag_open": "flags_lookup_tag_open",
          "tag_submit": "flags_lookup_tag_submit"}[action]
    asyncio.run(getattr(console, fn)(c, TOKEN, mongo=m))
    lookup.assert_not_awaited()
    c.respond_with_modal.assert_not_awaited()
    assert c.respond.await_count or c.interaction.edit_initial_response.await_count
    if c.respond.await_count:
        assert c.respond.call_args.kwargs["ephemeral"] is True


def test_member_select_uses_existing_user_lookup_and_mentions_stay_off(allowed, monkeypatch):
    read = AsyncMock(return_value=[dict(kind="ghosted", reason="Keep <@123> and @everyone literal.", source="Fixture")])
    monkeypatch.setattr(flags.flag_store, "list_for_identity", read)
    m, c = mongo(state()), ctx(values=[str(TARGET)])
    asyncio.run(console.flags_lookup_pick(c, TOKEN, mongo=m))
    read.assert_awaited_once_with(m, discord_ids=(str(TARGET),), player_tags=())
    c.defer.assert_awaited_once_with(ephemeral=True)
    answer = c.interaction.edit_initial_response.call_args.kwargs
    assert all(answer[k] is False for k in ["user_mentions", "role_mentions", "mentions_everyone"])
    assert "Ghosted" in str(built(answer["components"]))
    assert len(m.component_state.documents) == 1


def test_tag_opener_is_one_player_tag_field_on_same_state(allowed):
    c = ctx()
    asyncio.run(console.flags_lookup_tag_open(c, TOKEN, mongo=mongo(state())))
    modal = c.respond_with_modal.call_args.kwargs
    assert modal["title"] == "Search by player tag"
    assert modal["custom_id"] == "ticket_v2_flags_tag_submit:" + TOKEN
    fields = [n for n in built(modal["components"]) if n.get("type") == hikari.ComponentType.TEXT_INPUT]
    assert len(fields) == 1
    assert fields[0]["custom_id"] == "player_tag"
    assert fields[0]["label"] == "Player tag" and fields[0]["placeholder"] == "#ABC123"
    assert "Discord ID" not in str(modal)
    c.defer.assert_not_awaited()


@pytest.mark.parametrize("tag", ["123456789012345678", "ABC123", "", "@member", "#!!", "#AB", "#ABC123 #DEF456"])
def test_tag_submit_rejects_invalid_input_before_lookup_with_exact_guidance(allowed, monkeypatch, tag):
    lookup = AsyncMock(); monkeypatch.setattr(flags, "show_flags", lookup)
    c = ctx(tag=tag)
    asyncio.run(console.flags_lookup_tag_submit(c, TOKEN, mongo=mongo(state())))
    lookup.assert_not_awaited()
    assert c.respond.call_args.args[0] == "Use a player tag that starts with #."
    assert c.respond.call_args.kwargs["ephemeral"] is True


def test_valid_tag_submit_uses_existing_normalizer_and_readonly_flag_output(allowed, monkeypatch):
    read = AsyncMock(return_value=[]); monkeypatch.setattr(flags.flag_store, "list_for_identity", read)
    c, m = ctx(tag=" #aBc123 "), mongo(state())
    asyncio.run(console.flags_lookup_tag_submit(c, TOKEN, mongo=m))
    read.assert_awaited_once_with(m, discord_ids=(), player_tags=("#ABC123",))
    assert all(c.interaction.edit_initial_response.call_args.kwargs[k] is False
               for k in ["user_mentions", "role_mentions", "mentions_everyone"])


@pytest.mark.parametrize("values", [[], ["not-a-member"], [str(TARGET), str(OWNER)], ["123"]])
def test_malformed_member_selection_never_queries_flags(allowed, monkeypatch, values):
    lookup = AsyncMock(); monkeypatch.setattr(flags, "show_flags", lookup)
    c = ctx(values=values)
    asyncio.run(console.flags_lookup_pick(c, TOKEN, mongo=mongo(state())))
    lookup.assert_not_awaited()
    assert c.respond.call_args.kwargs["ephemeral"] is True


def test_entry_permission_denied_never_creates_state_or_modal(allowed):
    allowed.return_value = False
    c, m = ctx(), mongo()
    asyncio.run(console.flags_lookup_open(c, "hub", mongo=m))
    assert not m.component_state.documents
    c.respond_with_modal.assert_not_awaited()


def test_actual_dispatch_registration_keeps_shared_hub_out_of_edit_ack(allowed, monkeypatch):
    c, m = ctx(), mongo()
    c.interaction.custom_id = "ticket_v2_flags_lookup:hub"
    action = dispatcher.registered_functions["ticket_v2_flags_lookup"]
    assert action.opens_modal and action.no_return and not action.preload_state
    # Supply the synthetic dependency while exercising the actual registered handler.
    monkeypatch.setitem(dispatcher.registered_functions, action.name,
                        replace(action, fn=partial(action.fn, mongo=m)))
    asyncio.run(dispatcher._dispatch(c, m))
    c.defer.assert_awaited_once_with(ephemeral=True)
    c.respond_with_modal.assert_not_awaited()
    for name, modal in [("ticket_v2_flags_pick", False), ("ticket_v2_flags_tag_open", False),
                        ("ticket_v2_flags_tag_submit", True)]:
        registered = dispatcher.registered_functions[name]
        assert registered.no_return and not registered.preload_state
        assert registered.is_modal is modal
        if not modal: assert registered.opens_modal
    assert "ticket_v2_flags_lookup_submit" not in dispatcher.registered_functions


@pytest.mark.parametrize("identity", [str(TARGET), "#ABC123"])
def test_shared_no_match_copy_names_member_or_tag_without_raw_id_prompt(allowed, monkeypatch, identity):
    monkeypatch.setattr(flags.flag_store, "list_for_identity", AsyncMock(return_value=[]))
    c = ctx()
    asyncio.run(flags.show_flags(c, mongo(), identity))
    text = "\n".join(n.get("content", "") for n in built(c.interaction.edit_initial_response.call_args.kwargs["components"]))
    assert "No flag matches that member or player tag." in text
    assert "Discord ID" not in text


@pytest.mark.parametrize("identity", ["123", "name", ""])
def test_shared_invalid_search_copy_never_asks_for_discord_id(allowed, monkeypatch, identity):
    read = AsyncMock(); monkeypatch.setattr(flags.flag_store, "list_for_identity", read)
    c = ctx()
    asyncio.run(flags.show_flags(c, mongo(), identity))
    text = "\n".join(n.get("content", "") for n in built(c.interaction.edit_initial_response.call_args.kwargs["components"]))
    assert "Discord ID" not in text
    assert "member" in text and "player tag" in text
    read.assert_not_awaited()


@pytest.mark.parametrize("action", ["ticket_v2_flags_pick", "ticket_v2_flags_tag_open", "ticket_v2_flags_tag_submit"])
def test_actual_private_dispatch_acknowledges_only_the_private_result(allowed, monkeypatch, action):
    c, m = ctx(values=[str(TARGET)]), mongo(state())
    c.interaction.custom_id = action + ":" + TOKEN
    registered = dispatcher.registered_functions[action]
    monkeypatch.setitem(dispatcher.registered_functions, action,
                        replace(registered, fn=partial(registered.fn, mongo=m)))
    monkeypatch.setattr(flags.flag_store, "list_for_identity", AsyncMock(return_value=[]))
    async def forbidden_preload(*_args, **_kwargs):
        raise AssertionError("dispatcher must not preload before private ack/modal")
    monkeypatch.setattr(dispatcher, "get_state", forbidden_preload)
    asyncio.run(dispatcher._dispatch(c, m))
    if action == "ticket_v2_flags_tag_open":
        c.defer.assert_not_awaited()
        c.respond_with_modal.assert_awaited_once()
    else:
        c.defer.assert_awaited_once_with(ephemeral=True)
        c.respond_with_modal.assert_not_awaited()
