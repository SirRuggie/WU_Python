import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import manage_links as command
from utils import link_management as service


class Response:
    def __init__(self, status, payload):
        self.status, self.payload = status, payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.payload


class Session:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


def test_http_contract_and_tag_encoding():
    session = Session([Response(200, {}), Response(200, {})])
    client = service.LinkClient(session, "test-credential")

    async def run():
        await client.request("DELETE", 123, "#P0Y")
        await client.request("POST", 456, "poy")

    asyncio.run(run())
    assert session.calls == [
        ("DELETE", f"{service.BASE_URL}/123/%23P0Y", {
            "headers": {"Authorization": "Bearer test-credential"},
        }),
        ("POST", f"{service.BASE_URL}/456", {
            "headers": {"Authorization": "Bearer test-credential"},
            "json": {"player_tag": "#P0Y"},
        }),
    ]


def test_full_inventory_includes_hidden_and_sorts_unverified_first():
    session = Session([Response(200, {"items": [
        {"user_id": "123", "player_tag": "#P0Y", "is_verified": True, "hidden": True},
        {"user_id": "123", "player_tag": "#Q2L", "is_verified": False, "hidden": False},
    ]})])
    links = asyncio.run(service.LinkClient(session, "token").links(123))
    assert [link.tag for link in links] == ["#Q2L", "#P0Y"]
    assert links[-1].hidden


@pytest.mark.parametrize("payload", [{}, {"items": None}, {"items": [{}]}, {
    "items": [{"user_id": "999", "player_tag": "#P0Y", "is_verified": False, "hidden": False}],
}])
def test_invalid_inventory_fails_closed(payload):
    client = service.LinkClient(Session([Response(200, payload)]), "token")
    with pytest.raises(service.LinkError):
        asyncio.run(client.links(123))


def test_unauthorized_token_does_not_write():
    session = Session([Response(401, {"message": "do not expose response"})])
    with pytest.raises(service.LinkError, match="denied account-management access"):
        asyncio.run(service.run_batch(service.LinkClient(session, "token"), 123, "all"))
    assert [call[0] for call in session.calls] == ["GET"]


def test_configuration_does_not_reuse_developer_token(monkeypatch):
    monkeypatch.delenv(service.TOKEN_ENV, raising=False)
    monkeypatch.setenv("CLASHKING_API_TOKEN", "lookup-only")
    with pytest.raises(service.LinkError, match="not configured"):
        asyncio.run(service.manage_links(123, "all"))


class MemoryClient(service.LinkClient):
    def __init__(self):
        self.owners = {"#P0Y": 123, "#Q2L": 123}
        self.writes = []
        self.add_failure = None
        self.delete_failure = None
        self.commit_before_error = False

    async def links(self, user_id):
        return [service.Link(tag) for tag, owner in self.owners.items() if owner == user_id]

    async def request(self, method, user_id, tag=None):
        self.writes.append((method, user_id, tag))
        if method == "DELETE":
            if self.delete_failure:
                raise self.delete_failure
            assert self.owners[tag] == user_id
            del self.owners[tag]
        elif method == "POST":
            if user_id == 456 and self.add_failure:
                if self.commit_before_error:
                    self.owners[tag] = user_id
                raise self.add_failure
            assert tag not in self.owners
            self.owners[tag] = user_id
        return {}


def test_unlink_all_and_single_tag_scope():
    client = MemoryClient()
    result = asyncio.run(service.run_batch(client, 123, "poy"))
    assert result.completed == ["#P0Y"]
    assert client.owners == {"#Q2L": 123}
    result = asyncio.run(service.run_batch(client, 123, " ALL "))
    assert result.completed == ["#Q2L"]
    assert client.owners == {}


def test_transfer_all_to_selected_user():
    client = MemoryClient()
    result = asyncio.run(service.run_batch(client, 123, "all", 456))
    assert result.completed == ["#P0Y", "#Q2L"]
    assert client.owners == {"#P0Y": 456, "#Q2L": 456}


def test_transfer_failure_restores_source_and_stops_batch():
    client = MemoryClient()
    client.add_failure = service.LinkError("temporary failure")
    result = asyncio.run(service.run_batch(client, 123, "all", 456))
    assert result.completed == []
    assert "restored" in result.problem
    assert client.owners == {"#P0Y": 123, "#Q2L": 123}
    assert client.writes == [("DELETE", 123, "#P0Y"), ("POST", 456, "#P0Y"), ("POST", 123, "#P0Y")]


def test_lost_post_response_is_reconciled_without_rollback():
    client = MemoryClient()
    client.add_failure = service.LinkError("timeout")
    client.commit_before_error = True
    result = asyncio.run(service.run_batch(client, 123, "#P0Y", 456))
    assert result.completed == ["#P0Y"]
    assert client.owners["#P0Y"] == 456
    assert len(client.writes) == 2


def test_delete_failure_never_attempts_add():
    client = MemoryClient()
    client.delete_failure = service.LinkError("conflict")
    result = asyncio.run(service.run_batch(client, 123, "all", 456))
    assert not result.completed
    assert "conflict" in result.problem
    assert client.writes == [("DELETE", 123, "#P0Y")]


def test_destination_permission_is_checked_before_delete():
    client = MemoryClient()
    original = client.links

    async def links(user_id):
        if user_id == 456:
            raise service.LinkError("denied")
        return await original(user_id)

    client.links = links
    with pytest.raises(service.LinkError, match="denied"):
        asyncio.run(service.run_batch(client, 123, "all", 456))
    assert client.writes == []


@pytest.mark.parametrize("selection,destination", [("#GGG", None), ("bad/tag", None), ("all", 123)])
def test_invalid_selections_cannot_write(selection, destination):
    client = MemoryClient()
    with pytest.raises(service.LinkError):
        asyncio.run(service.run_batch(client, 123, selection, destination))
    assert client.writes == []


def context(permissions, guild_id=1):
    return SimpleNamespace(
        interaction=SimpleNamespace(member=SimpleNamespace(permissions=permissions)),
        guild_id=guild_id, user=SimpleNamespace(id=999),
        respond=AsyncMock(), defer=AsyncMock(),
    )


@pytest.mark.parametrize("permissions,guild_id", [
    (hikari.Permissions.NONE, 1),
    (hikari.Permissions.MANAGE_GUILD, 1),
    (hikari.Permissions.ADMINISTRATOR, None),
])
def test_non_admin_and_dm_denied_before_api(monkeypatch, permissions, guild_id):
    manage = AsyncMock()
    monkeypatch.setattr(service, "manage_links", manage)
    ctx = context(permissions, guild_id)
    asyncio.run(command.execute(ctx, SimpleNamespace(id=123, is_bot=False), "all"))
    manage.assert_not_awaited()
    assert ctx.respond.call_args.kwargs["ephemeral"] is True


def test_admin_transfer_passes_both_users_and_responds_privately(monkeypatch):
    manage = AsyncMock(return_value=service.Result(["#P0Y"], ["#P0Y"]))
    monkeypatch.setattr(service, "manage_links", manage)
    ctx = context(hikari.Permissions.ADMINISTRATOR)
    asyncio.run(command.execute(ctx, SimpleNamespace(id=123, is_bot=False), "all",
                                SimpleNamespace(id=456, is_bot=False)))
    manage.assert_awaited_once_with(123, "all", 456)
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    assert ctx.respond.call_args.kwargs["ephemeral"] is True
    assert "1 of 1" in ctx.respond.call_args.args[0]


def test_command_is_admin_only_guild_only_and_auto_discovered():
    from utils.startup import load_cogs
    assert command.group.default_member_permissions == hikari.Permissions.ADMINISTRATOR
    assert command.group.contexts == [hikari.ApplicationContextType.GUILD]
    assert "extensions.commands.manage_links" in load_cogs(set())
