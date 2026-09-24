"""Check actual Discord payloads for dashboard image delivery."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from hikari.impl import RESTClientImpl

from extensions.commands.clan.dashboard.dashboard import dashboard_page
from extensions.commands.clan.dashboard.fwa_data import build_th_edit_components


@pytest.mark.parametrize("guild_state", ["icon", "no_icon", "cache_miss"])
def test_root_dashboard_needs_no_attachment_upload(guild_state):
    icon = "https://cdn.discordapp.com/icons/123/icon.png?size=256"
    guild = None if guild_state == "cache_miss" else SimpleNamespace(
        make_icon_url=Mock(return_value=icon if guild_state == "icon" else None)
    )
    clans = SimpleNamespace(count_documents=AsyncMock(return_value=7))
    bot = SimpleNamespace(cache=SimpleNamespace(get_guild=Mock(return_value=guild)))
    panels = asyncio.run(dashboard_page._func(
        bot=bot, ctx=SimpleNamespace(guild_id=123), mongo=SimpleNamespace(clans=clans)
    ))
    rest = object.__new__(RESTClientImpl)
    body, form = rest._build_message_payload(components=panels)
    assert form is None
    assert not body.get("attachments")
    payload = body["components"][0]
    clans.count_documents.assert_awaited_once_with({})
    heading = payload["components"][0]
    if guild_state == "icon":
        assert heading["accessory"]["media"]["url"] == icon
        heading = heading["components"][0]
    else:
        assert heading["type"] == 10
    assert "`7`" in heading["content"]
    if guild is not None:
        guild.make_icon_url.assert_called_once_with(size=256)


def test_fwa_editor_preserves_base_images_without_file_uploads():
    war = "https://img.example.com/war.png"
    active = "https://img.example.com/active.png"
    panels = build_th_edit_components("th16", "", "", "", war, active)
    rest = object.__new__(RESTClientImpl)
    body, form = rest._build_message_payload(components=panels)
    assert form is None
    assert not body.get("attachments")
    payload = body["components"][0]
    galleries = [c for c in payload["components"] if c["type"] == 12]
    assert [g["items"][0]["media"]["url"] for g in galleries] == [war, active]


def test_clan_image_panel_previews_both_slots_and_offers_native_uploads():
    from extensions.commands.clan.dashboard.update_clan_info import update_logo_button
    mongo = SimpleNamespace(clans=SimpleNamespace(find_one=AsyncMock(return_value={
        "tag": "#ABC", "name": "Test Clan",
        "logo": "https://img.example.com/logo.png",
        "banner": "https://img.example.com/banner.png",
    })))
    panels = asyncio.run(update_logo_button.__wrapped__._func(
        ctx=SimpleNamespace(), action_id="#ABC", mongo=mongo,
    ))
    rest = object.__new__(RESTClientImpl)
    body, form = rest._build_message_payload(components=panels)
    assert form is None
    children = body["components"][0]["components"]
    galleries = [c for c in children if c["type"] == 12]
    assert len(galleries) == 2
    buttons = [b for row in children if row["type"] == 1 for b in row["components"]]
    ids = {b["custom_id"] for b in buttons}
    assert {"clan_image_upload:logo:#ABC", "clan_image_upload:banner:#ABC"} <= ids
    assert "immediately" in children[1]["content"]


def test_fwa_image_panel_targets_each_base_for_selected_town_hall():
    from extensions.commands.clan.dashboard.fwa_data import fwa_update_images
    panels = asyncio.run(fwa_update_images.__wrapped__._func(
        ctx=SimpleNamespace(), action_id="th18_new",
    ))
    payload, _ = panels[0].build()
    buttons = [b for row in payload["components"] if row["type"] == 1
               for b in row["components"]]
    assert {"fwa_image_upload:war:th18_new", "fwa_image_upload:active:th18_new"} <= {
        b["custom_id"] for b in buttons
    }


def test_legacy_image_commands_are_removed_but_native_actions_remain():
    from extensions.commands.clan import clan
    from extensions.commands.fwa import fwa
    from extensions.commands.help_catalog import command_paths
    from extensions.components import registered_functions

    assert "upload-images" not in clan.subcommands
    assert "upload-images" not in fwa.subcommands
    assert "/clan upload-images" not in command_paths()
    assert "/fwa upload-images" not in command_paths()
    for action in ("clan_image_upload", "fwa_image_upload"):
        assert registered_functions[action].opens_modal
    assert registered_functions["dashboard_image_submit"].is_modal


@pytest.mark.parametrize("kind", ["clan", "fwa"])
def test_old_instruction_buttons_redirect_to_native_upload_controls(kind):
    from extensions.commands.clan.dashboard import update_clan_info, fwa_data

    if kind == "clan":
        mongo = SimpleNamespace(clans=SimpleNamespace(find_one=AsyncMock(return_value={
            "tag": "#ABC", "name": "Test Clan",
        })))
        panels = asyncio.run(update_clan_info.logo_upload_guide.__wrapped__._func(
            ctx=SimpleNamespace(), action_id="#ABC", mongo=mongo,
        ))
        expected = {"clan_image_upload:logo:#ABC", "clan_image_upload:banner:#ABC"}
    else:
        panels = asyncio.run(fwa_data.fwa_upload_guide.__wrapped__._func(
            ctx=SimpleNamespace(), action_id="th16",
        ))
        expected = {"fwa_image_upload:war:th16", "fwa_image_upload:active:th16"}
    payload = panels[0].build()[0]
    rows = [c for c in payload["components"] if c["type"] == 1]
    assert expected <= {b["custom_id"] for row in rows for b in row["components"]}
    assert "upload-images" not in str(payload)
