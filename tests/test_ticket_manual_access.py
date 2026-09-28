import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import hikari
from extensions.commands.tickets import thread_service as service


def test_manual_access_is_member_only_and_keeps_parent_readonly():
    p = hikari.Permissions
    old = SimpleNamespace(id=30, allow=p.USE_EXTERNAL_EMOJIS | p.SEND_MESSAGES,
                          deny=p.VIEW_CHANNEL | p.MANAGE_MESSAGES)
    channel = SimpleNamespace(type=hikari.ChannelType.GUILD_TEXT, guild_id=10,
                              permission_overwrites={30: old})
    rest = SimpleNamespace(
        fetch_channel=AsyncMock(return_value=channel),
        fetch_guild=AsyncMock(return_value=SimpleNamespace(owner_id=99)),
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=30,role_ids=[])),
        fetch_roles=AsyncMock(return_value=[]), edit_permission_overwrite=AsyncMock())
    asyncio.run(service.grant_manual_applicant_access(rest,service.ThreadParents(10,20,21,40),user_id=30,actor_id=50))
    call=rest.edit_permission_overwrite.call_args
    assert call.args == (20,30)
    assert call.kwargs['target_type'] == hikari.PermissionOverwriteType.MEMBER
    required=p.VIEW_CHANNEL|p.READ_MESSAGE_HISTORY|p.SEND_MESSAGES_IN_THREADS|p.EMBED_LINKS|p.ATTACH_FILES
    assert call.kwargs['allow'] & required == required
    assert not call.kwargs['deny'] & required
    assert call.kwargs['deny'] & p.SEND_MESSAGES
    assert not call.kwargs['allow'] & p.SEND_MESSAGES
    assert call.kwargs['allow'] & p.USE_EXTERNAL_EMOJIS
    assert call.kwargs['deny'] & p.MANAGE_MESSAGES


def test_existing_sufficient_permissions_are_not_rewritten():
    rest=SimpleNamespace(
        fetch_channel=AsyncMock(return_value=SimpleNamespace(type=hikari.ChannelType.GUILD_TEXT,guild_id=10)),
        fetch_guild=AsyncMock(return_value=SimpleNamespace(owner_id=30)),
        fetch_member=AsyncMock(return_value=SimpleNamespace(id=30)),
        fetch_roles=AsyncMock(return_value=[]), edit_permission_overwrite=AsyncMock())
    asyncio.run(service.grant_manual_applicant_access(rest,service.ThreadParents(10,20,21,40),user_id=30,actor_id=50))
    rest.edit_permission_overwrite.assert_not_awaited()
