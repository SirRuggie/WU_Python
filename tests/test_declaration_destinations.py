import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from aiohttp import web
from hikari import Permissions
from cwl_web.declaration_destinations import issue, destination, channels
from cwl_web.server_management import GUILD_ID

BOT = "123456789012345678"
CHANNEL = "234567890123456789"
RIGHTS = int(Permissions.VIEW_CHANNEL | Permissions.SEND_MESSAGES)


def test_channel_ownership_type_and_overwrite_permissions():
    actor = dict(user_id=BOT, role_ids=set(), permissions=RIGHTS)
    row = dict(id=CHANNEL, guild_id=str(GUILD_ID), type=0)
    assert issue(row, actor) is None
    assert issue(dict(row, type=5), actor) is None
    assert issue(dict(row, type=2), actor)
    assert issue(dict(row, guild_id="999999999999999999"), actor)
    assert issue(
        dict(
            row,
            permission_overwrites=[
                {
                    "id": str(GUILD_ID),
                    "type": 0,
                    "deny": str(int(Permissions.SEND_MESSAGES)),
                    "allow": "0",
                }
            ],
        ),
        actor,
    )
    assert issue(row, dict(actor, permissions=0))


def test_live_directory_excludes_foreign_voice_and_marks_unavailable_channels():
    async def run():
        rows = [
            dict(id=CHANNEL, name="available", type=0),
            dict(
                id="345678901234567890",
                name="denied",
                type=5,
                permission_overwrites=[
                    {
                        "id": BOT,
                        "type": 1,
                        "deny": str(int(Permissions.SEND_MESSAGES)),
                        "allow": "0",
                    }
                ],
            ),
            dict(id="456789012345678901", name="voice", type=2),
            dict(
                id="567890123456789012",
                guild_id="999999999999999999",
                name="foreign",
                type=0,
            ),
        ]

        async def fake(method, path, **kwargs):
            assert method == "GET"
            if path == "/users/@me":
                return {"id": BOT}
            if path.endswith("/roles"):
                return [{"id": str(GUILD_ID), "permissions": str(RIGHTS)}]
            if "/members/" in path:
                return {"roles": []}
            if path.endswith("/channels"):
                return rows
            if path == "/channels/" + CHANNEL:
                return dict(rows[0], guild_id=str(GUILD_ID))
            raise AssertionError(path)

        request = SimpleNamespace(app={"server_management_discord": fake})
        result = await channels(request)
        assert len(result) == 2 and result[0]["can_send"] and not result[1]["can_send"]
        assert (await destination(request, CHANNEL))["id"] == CHANNEL
        with pytest.raises(ValueError):
            await destination(request, "@everyone")

    asyncio.run(run())
