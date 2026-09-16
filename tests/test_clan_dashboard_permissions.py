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
    "add_clan_page", "add_clan", "add_clan_modal", "remove_clan_select",
    "clan_remove_menu", "remove_clan", "choose_clan_select", "clan_edit_menu",
    "edit_clan", "edit_thread", "update_logo", "logo_upload_guide",
    "logo_url_modal", "update_logo_modal", "back_to_clan_edit", "edit_roles",
    "edit_channels", "update_emoji", "emoji_url_modal", "emoji_from_logo",
    "update_emoji_modal", "update_general_info", "edit_general",
})
EXPECTED_FWA_CHILDREN = frozenset({
    "fwa_back_to_main", "fwa_th_select", "fwa_update_link", "fwa_link_submit",
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
    assert CLAN_CHILD_ACTIONS | FWA_CHILD_ACTIONS <= components.registered_functions.keys()


@pytest.mark.parametrize("action", ["remove_clan", "add_clan", "add_clan_modal"])
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
    [("remove_clan", True), ("add_clan", False), ("add_clan_modal", False)],
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


def test_all_six_legacy_modal_openers_have_opener_metadata():
    for action in (
        "add_clan", "logo_url_modal", "emoji_url_modal",
        "fwa_update_link", "fwa_image_urls", "fwa_update_descriptions",
    ):
        registration = components.registered_functions[action]
        assert registration.opens_modal is True
        assert registration.is_modal is False


def test_add_clan_modal_acknowledges_before_coc_or_mongo(monkeypatch):
    events = []

    class Interaction:
        member = SimpleNamespace(get_roles=lambda: (SimpleNamespace(id=ROLE_ID),))
        components = ((SimpleNamespace(custom_id="clantag", value="#ABC"),),)

        async def create_initial_response(self, response_type):
            events.append(("ack", response_type))

        async def edit_initial_response(self, **_kwargs):
            events.append(("edit",))

    ctx = SimpleNamespace(
        interaction=Interaction(),
        member=Interaction.member,
        respond=AsyncMock(),
    )
    clan = SimpleNamespace(tag="#ABC", name="Alpha")

    class Coc:
        async def get_clan(self, *, tag):
            events.append(("coc", tag))
            return clan

    class Clans:
        async def update_one(self, *_args, **_kwargs):
            events.append(("mongo",))

    async def fake_index(_mongo):
        events.append(("index",))

    async def fake_menu(*_args, **_kwargs):
        return []

    monkeypatch.setattr(update_clan_info, "ensure_clan_tag_index", fake_index)
    monkeypatch.setattr(update_clan_info, "clan_edit_menu", fake_menu)
    asyncio.run(update_clan_info.add_clan_modal.__wrapped__._func(
        ctx=ctx,
        coc_client=Coc(),
        mongo=SimpleNamespace(clans=Clans()),
    ))

    assert events[0] == ("ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    assert [event[0] for event in events[1:4]] == ["coc", "index", "mongo"]


@pytest.mark.parametrize(
    ("handler", "field_values"),
    [
        ("fwa_link_submit", {"base_link": "https://link.clashofclans.com/example"}),
        ("fwa_descriptions_submit", {"base_information": "Info", "upgrade_notes": ""}),
    ],
)
def test_fwa_modal_submits_acknowledge_before_database(handler, field_values):
    events = []

    class Interaction:
        member = SimpleNamespace(get_roles=lambda: (SimpleNamespace(id=ROLE_ID),))
        components = (tuple(
            SimpleNamespace(custom_id=name, value=value)
            for name, value in field_values.items()
        ),)

        async def create_initial_response(self, response_type):
            events.append(("ack", response_type))

        async def edit_initial_response(self, **_kwargs):
            events.append(("edit",))

    class FwaCollection:
        async def update_one(self, *_args, **_kwargs):
            events.append(("mongo",))

        async def find_one(self, *_args, **_kwargs):
            return {"_id": "fwa_config"}

    interaction = Interaction()
    ctx = SimpleNamespace(
        interaction=interaction,
        member=interaction.member,
        respond=AsyncMock(),
    )
    asyncio.run(getattr(fwa_data, handler).__wrapped__._func(
        ctx=ctx,
        action_id="th16",
        mongo=SimpleNamespace(fwa_data=FwaCollection()),
    ))

    assert events[0] == ("ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    assert events.index(("ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)) < events.index(("mongo",))
