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




def test_clan_image_panel_redirects_read_only():
    from extensions.commands.clan.dashboard.update_clan_info import update_logo_button
    mongo = SimpleNamespace(clans=SimpleNamespace(find_one=AsyncMock(return_value={"tag":"#ABC","name":"Test Clan","logo":"https://img.example.com/logo.png"})))
    ctx = SimpleNamespace(member=SimpleNamespace(get_roles=lambda: [SimpleNamespace(id=993015846442127420)]), respond=AsyncMock())
    asyncio.run(update_logo_button.__wrapped__._func(ctx=ctx,action_id="#ABC",mongo=mongo))
    text = ctx.respond.await_args.args[0]
    assert "https://img.example.com/logo.png" in text
    assert "https://dash.warriorsunited.cc/clans/%23ABC" in text










def test_fwa_editor_is_link_only_without_attachment_uploads():
    panels=build_th_edit_components('th19','','','','https://example.org/war.jpg','https://example.org/active.jpg')
    rest=object.__new__(RESTClientImpl)
    body,form=rest._build_message_payload(components=panels)
    assert form is None and not body.get('attachments')
    assert 'Town Hall bases are managed on the dashboard.' in str(body)
    assert 'https://example.org/war.jpg' not in str(body)


def test_old_image_actions_remain_but_do_not_open_upload_modals():
    from extensions.commands.clan.dashboard import image_uploads
    from extensions.components import registered_functions
    assert not registered_functions['clan_image_upload'].opens_modal
    assert not registered_functions['fwa_image_upload'].opens_modal
    assert registered_functions['dashboard_image_submit'].is_modal
