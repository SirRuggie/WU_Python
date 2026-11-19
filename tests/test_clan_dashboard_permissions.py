import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions import components
from extensions.commands.clan.dashboard import fwa_data, update_clan_info
from extensions.commands.clan.dashboard.permissions import (
    CLAN_CHILD_ACTIONS,
    FWA_CHILD_ACTIONS,
)


ROLE_ID = 993015846442127420


EXPECTED_CLAN_CHILDREN = frozenset({
    "clan_image_upload", "dashboard_image_submit", "add_clan_page", "add_clan", "add_clan_modal", "remove_clan_select",
    "clan_remove_menu", "remove_clan", "choose_clan_select", "clan_edit_menu",
    "edit_clan", "edit_thread", "update_logo", "logo_upload_guide",
    "logo_url_modal", "update_logo_modal", "back_to_clan_edit", "edit_roles",
    "edit_channels", "update_emoji", "emoji_url_modal", "emoji_from_logo",
    "update_emoji_modal", "update_general_info", "edit_general",
})
EXPECTED_FWA_CHILDREN = frozenset({
    "fwa_image_upload", "fwa_back_to_main", "fwa_th_select", "fwa_update_link", "fwa_link_submit",
    "fwa_update_images", "fwa_image_urls", "fwa_images_submit",
    "fwa_update_descriptions", "fwa_th_select_return", "fwa_descriptions_submit",
    "fwa_upload_guide",
})


class _DispatchContext:
    def __init__(self, action, *, authorized):
        roles = (SimpleNamespace(id=ROLE_ID),) if authorized else ()
        self.user = SimpleNamespace(id=10)
        self.member = SimpleNamespace(get_roles=lambda: roles)
        self.interaction = SimpleNamespace(
            custom_id=f"{action}:value",
            member=self.member,
        )
        self.events = []

    async def respond(self, *args, **kwargs):
        self.events.append(("respond", args, kwargs))

    async def defer(self, **kwargs):
        self.events.append(("defer", kwargs))


def test_guard_action_sets_exactly_cover_every_persistent_child():
    assert CLAN_CHILD_ACTIONS == EXPECTED_CLAN_CHILDREN
    assert FWA_CHILD_ACTIONS == EXPECTED_FWA_CHILDREN
    assert CLAN_CHILD_ACTIONS.isdisjoint(FWA_CHILD_ACTIONS)
    assert all(components._resolve(name) is not None
               for name in CLAN_CHILD_ACTIONS | FWA_CHILD_ACTIONS)


@pytest.mark.parametrize("action", ["remove_clan", "add_clan", "add_clan_modal", "clan_image_upload", "fwa_image_upload", "dashboard_image_submit"])
def test_dispatch_refuses_revoked_role_before_any_child_handler(monkeypatch, action):
    calls = []

    async def sentinel(**kwargs):
        calls.append(kwargs)

    original = components.registered_functions[action]
    monkeypatch.setitem(
        components.registered_functions,
        action,
        replace(original, fn=sentinel, preload_state=False, requires_state=False),
    )
    ctx = _DispatchContext(action, authorized=False)
    asyncio.run(components._dispatch(ctx, mongo=SimpleNamespace()))

    assert calls == []
    assert not any(event[0] == "defer" for event in ctx.events)
    assert ctx.events[0][0] == "respond"
    assert ctx.events[0][2]["ephemeral"] is True


@pytest.mark.parametrize(
    ("action", "dispatcher_defers"),
    [("remove_clan", True), ("add_clan", True), ("add_clan_modal", False)],
)
def test_dispatch_allows_current_role_for_nonmodal_opener_and_submit(
    monkeypatch, action, dispatcher_defers
):
    calls = []

    async def sentinel(**kwargs):
        calls.append(kwargs)

    original = components.registered_functions[action]
    monkeypatch.setitem(
        components.registered_functions,
        action,
        replace(original, fn=sentinel, preload_state=False, requires_state=False),
    )
    ctx = _DispatchContext(action, authorized=True)
    asyncio.run(components._dispatch(ctx, mongo=SimpleNamespace()))

    assert len(calls) == 1
    assert calls[0]["action_id"] == "value"
    assert any(event[0] == "defer" for event in ctx.events) is dispatcher_defers


def test_retired_fwa_openers_are_nonmodal_dashboard_links():
    for action in (
        "fwa_image_upload",
        "fwa_update_link", "fwa_image_urls", "fwa_update_descriptions",
    ):
        registration = components._resolve(action)
        assert registration.opens_modal is False
        assert registration.is_modal is False


def test_old_add_modal_redirects_without_clash_or_database_writes():
    ctx = SimpleNamespace(member=SimpleNamespace(get_roles=lambda: (SimpleNamespace(id=ROLE_ID),)), respond=AsyncMock())
    mongo = SimpleNamespace(clans=SimpleNamespace(update_one=AsyncMock()))
    asyncio.run(update_clan_info.add_clan_modal.__wrapped__._func(ctx=ctx, mongo=mongo))
    assert "Edit this on the dashboard" in ctx.respond.await_args.args[0]
    mongo.clans.update_one.assert_not_awaited()


@pytest.mark.parametrize(
    ("handler", "field_values"),
    [
        ("fwa_link_submit", {"base_link": "https://link.clashofclans.com/example"}),
        ("fwa_descriptions_submit", {"base_information": "Info", "upgrade_notes": ""}),
    ],
)
def test_retired_fwa_modal_submits_link_without_database(handler, field_values):
    member = SimpleNamespace(get_roles=lambda: (SimpleNamespace(id=ROLE_ID),))
    ctx = SimpleNamespace(member=member, respond=AsyncMock())
    collection = SimpleNamespace(find_one=AsyncMock(), update_one=AsyncMock())
    asyncio.run(getattr(fwa_data, handler).__wrapped__._func(
        ctx=ctx, action_id="th16|expired", mongo=SimpleNamespace(fwa_data=collection),
    ))
    collection.find_one.assert_not_awaited()
    collection.update_one.assert_not_awaited()
    payload = ctx.respond.await_args.kwargs
    assert "Town Halls" in str(payload["components"][0].build())
    assert payload["ephemeral"] is True
    assert payload["user_mentions"] is payload["role_mentions"] is payload["mentions_everyone"] is False
