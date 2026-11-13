import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import hikari
import pytest

from extensions.commands import manage_links as command
from utils import clashperk_link_writes as writes


class Response:
    def __init__(self, status, payload=None):
        self.status, self.payload = status, payload or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self, **kwargs):
        return self.payload


class Session:
    """Fake aiohttp session. Any network use outside .post fails the test."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.posts = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def post(self, url, **kwargs):
        self.posts.append((url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake(monkeypatch):
    state = SimpleNamespace(owners={}, lookups=[], session=None, tokens=["tok-1", "tok-2"], token_calls=[])

    async def lookup(*, player_tags=None, discord_ids=None):
        state.lookups.append(player_tags)
        if state.owners is None:
            return None
        return [{"tag": t, "userId": u, "verified": False, "name": "x", "username": "y"}
                for t, u in state.owners.items() if t in player_tags]

    async def token(session, *, rejected=None):
        state.token_calls.append(rejected)
        return state.tokens.pop(0) if state.tokens else None

    monkeypatch.setattr(writes.clashperk_links, "lookup", lookup)
    monkeypatch.setattr(writes.clashperk_links, "get_access_token", token)
    monkeypatch.setattr(writes.aiohttp, "ClientSession", lambda **kw: state.session)
    monkeypatch.setattr(writes, "_lock", asyncio.Lock())
    return state


def run(user, tag):
    return asyncio.run(writes.create_link(user, tag))


def test_links_free_tag_with_exact_body_and_reads_back(fake):
    class Accepting(Session):
        def post(self, url, **kwargs):
            fake.owners["#P0Y"] = "123"
            return super().post(url, **kwargs)

    fake.session = Accepting([Response(201, {"message": "ok"})])
    result = run(123, " p0y ")
    assert result.status == writes.LINKED and result.wrote and result.verified is False
    assert fake.session.posts == [(writes.clashperk_links.BASE_URL + "/links", {
        "json": {"playerTag": "#P0Y", "userId": "123", "apiToken": None},
        "headers": {"Authorization": "Bearer tok-1"}, "allow_redirects": False,
    })]
    assert fake.lookups == [["#P0Y"], ["#P0Y"]]


@pytest.mark.parametrize("tag", ["", "all", "#XYZ", "#P0Y P0Y", "#" + "P" * 13])
def test_invalid_tag_makes_no_call(fake, tag):
    fake.session = Session([])
    assert run(123, tag).status == writes.INVALID
    assert fake.lookups == [] and fake.session.posts == []


def test_unreadable_owner_blocks_write(fake):
    fake.owners, fake.session = None, Session([])
    result = run(123, "#P0Y")
    assert result.status == writes.UNAVAILABLE and not result.wrote
    assert fake.session.posts == []


def test_other_owner_is_never_overwritten(fake):
    fake.owners, fake.session = {"#P0Y": "456"}, Session([])
    result = run(123, "#P0Y")
    assert result.status == writes.OTHER_OWNER and not result.wrote
    assert fake.session.posts == []


def test_same_owner_is_noop(fake):
    fake.owners, fake.session = {"#P0Y": "123"}, Session([])
    assert run(123, "#P0Y").status == writes.ALREADY_LINKED
    assert fake.session.posts == []


def test_401_refreshes_token_once(fake):
    class Accepting(Session):
        def post(self, url, **kwargs):
            response = super().post(url, **kwargs)
            if response.status == 201:
                fake.owners["#P0Y"] = "123"
            return response

    fake.session = Accepting([Response(401), Response(201)])
    assert run(123, "#P0Y").status == writes.LINKED
    assert fake.token_calls == [None, "tok-1"]
    assert fake.session.posts[1][1]["headers"] == {"Authorization": "Bearer tok-2"}


def test_missing_key_writes_nothing(fake):
    fake.tokens, fake.session = [], Session([])
    assert run(123, "#P0Y").status == writes.UNAVAILABLE
    assert fake.session.posts == []


@pytest.mark.parametrize("code,text", [("FORBIDDEN", "refused this link"), ("BAD_REQUEST", "rejected the player"),
                                       (None, "rejected this link")])
def test_rejection_is_mapped_and_not_retried(fake, code, text):
    fake.session = Session([Response(403, {"code": code, "message": "<@&1> raw text"} if code else {})])
    result = run(123, "#P0Y")
    assert result.status == writes.REJECTED and text in result.message
    assert "raw text" not in result.message
    assert len(fake.session.posts) == 1 and len(fake.lookups) == 1


@pytest.mark.parametrize("failure", [asyncio.TimeoutError(), aiohttp.ClientConnectionError(), Response(500)])
def test_uncertain_write_is_never_retried(fake, failure):
    fake.session = Session([failure, Response(201)])
    result = run(123, "#P0Y")
    assert result.status == writes.UNKNOWN and result.wrote
    assert len(fake.session.posts) == 1


def test_uncertain_write_confirmed_by_read_back(fake):
    class CommitThenTimeout(Session):
        def post(self, url, **kwargs):
            fake.owners["#P0Y"] = "123"
            return super().post(url, **kwargs)

    fake.session = CommitThenTimeout([asyncio.TimeoutError()])
    assert run(123, "#P0Y").status == writes.LINKED


def test_concurrent_duplicates_write_once(fake):
    class Accepting(Session):
        def post(self, url, **kwargs):
            fake.owners["#P0Y"] = "123"
            return super().post(url, **kwargs)

    fake.session = Accepting([Response(201)])

    async def both():
        return await asyncio.gather(writes.create_link(123, "#P0Y"), writes.create_link(123, "#P0Y"))

    statuses = sorted(r.status for r in asyncio.run(both()))
    assert statuses == [writes.ALREADY_LINKED, writes.LINKED]
    assert len(fake.session.posts) == 1


def context(permissions, guild_id=644963518025826315):
    return SimpleNamespace(
        interaction=SimpleNamespace(member=SimpleNamespace(permissions=permissions)),
        guild_id=guild_id, user=SimpleNamespace(id=999),
        respond=AsyncMock(), defer=AsyncMock(),
    )


@pytest.mark.parametrize("permissions,guild_id", [(hikari.Permissions.NONE, 1), (hikari.Permissions.ADMINISTRATOR, None)])
def test_command_denies_non_admin_and_dm(monkeypatch, permissions, guild_id):
    create = AsyncMock()
    monkeypatch.setattr(writes, "create_link", create)
    ctx = context(permissions, guild_id)
    asyncio.run(command.link_clashperk(ctx, SimpleNamespace(id=123, is_bot=False), "#P0Y"))
    create.assert_not_awaited()
    assert ctx.respond.call_args.kwargs["ephemeral"] is True


def test_command_denies_bot_user(monkeypatch):
    create = AsyncMock()
    monkeypatch.setattr(writes, "create_link", create)
    ctx = context(hikari.Permissions.ADMINISTRATOR)
    asyncio.run(command.link_clashperk(ctx, SimpleNamespace(id=123, is_bot=True), "#P0Y"))
    create.assert_not_awaited()


def test_command_reply_is_private_and_mention_free(monkeypatch):
    from extensions.commands import linked_accounts as accounts
    accounts._result_cache[123] = (0.0, None)
    create = AsyncMock(return_value=writes.LinkResult(writes.LINKED, "#P0Y", "Linked in ClashPerk.", False, True))
    monkeypatch.setattr(writes, "create_link", create)
    ctx = context(hikari.Permissions.ADMINISTRATOR)
    asyncio.run(command.link_clashperk(ctx, SimpleNamespace(id=123, is_bot=False), "p0y"))
    create.assert_awaited_once_with(123, "p0y")
    ctx.defer.assert_awaited_once_with(ephemeral=True)
    kwargs = ctx.respond.call_args.kwargs
    assert kwargs["ephemeral"] is True and kwargs["user_mentions"] is False and kwargs["role_mentions"] is False
    assert "Not verified" in ctx.respond.call_args.args[0]
    assert 123 not in accounts._result_cache


def test_other_owner_reports_owner_username(fake):
    fake.owners, fake.session = {"#P0Y": "456"}, Session([])
    result = run(123, "#P0Y")
    assert result.status == writes.OTHER_OWNER and result.owner == "y"
