"""Tests for Discord-link expansion used by the clan movement tracker."""

import asyncio

from utils import clash_links


class _Response:
    def __init__(self, status=200, payload=None, body=""):
        self.status = status
        self.payload = payload
        self.body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self):
        return self.payload

    async def text(self):
        return self.body


class _Session:
    def __init__(self, response, calls, **_kwargs):
        self.response = response
        self.calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_shared_lookup_uses_bearer_token_and_normalizes_items(monkeypatch):
    calls = []
    response = _Response(payload={"items": [
        {"player_tag": "abc"},
        {"player_tag": "#ABC"},
        {"player_tag": " #def "},
        {"not_a_tag": True},
    ]})
    monkeypatch.setenv(clash_links.LINK_API_TOKEN_ENV, "secret")
    monkeypatch.setattr(
        clash_links.aiohttp,
        "ClientSession",
        lambda **kwargs: _Session(response, calls, **kwargs),
    )

    result = asyncio.run(clash_links._lookup_shared_links(
        discord_ids=["123456789012345"],
    ))

    assert result == response.payload["items"]
    assert calls == [(
        clash_links.LINK_API_URL,
        {
            "json": {
                "discord_ids": ["123456789012345"],
                "player_tags": [],
            },
            "headers": {"Authorization": "Bearer secret"},
        },
    )]


def test_v2_account_lookup_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv(clash_links.LINK_API_TOKEN_ENV, raising=False)
    assert asyncio.run(clash_links._lookup_shared_links(
        discord_ids=["123456789012345"],
    )) is None


def test_v2_account_lookup_rejects_wrong_payload_shape(monkeypatch):
    monkeypatch.setenv(clash_links.LINK_API_TOKEN_ENV, "secret")
    monkeypatch.setattr(
        clash_links.aiohttp,
        "ClientSession",
        lambda **kwargs: _Session(_Response(payload=[]), [], **kwargs),
    )
    assert asyncio.run(clash_links._lookup_shared_links(
        discord_ids=["123456789012345"],
    )) is None


def test_discord_id_resolves_every_owned_tag_and_filters_echo(monkeypatch):
    calls = []

    async def fake_lookup(**kwargs):
        calls.append(kwargs)
        return [
            {"player_tag": "#MAIN", "user_id": "123"},
            {"player_tag": "#ALT", "user_id": "123"},
            {"player_tag": "#OTHER", "user_id": "999"},
        ]

    monkeypatch.setattr(clash_links, "_lookup_shared_links", fake_lookup)

    result = asyncio.run(clash_links.resolve_tags(123))

    assert calls == [{"discord_ids": ["123"]}]
    assert result == ["#MAIN", "#ALT"]


def test_discord_id_resolution_preserves_failure(monkeypatch):
    async def failed(**_kwargs):
        return None

    monkeypatch.setattr(clash_links, "_lookup_shared_links", failed)
    assert asyncio.run(clash_links.resolve_tags(123)) is None


def test_discord_id_resolution_can_succeed_with_no_links(monkeypatch):
    async def empty(**_kwargs):
        return []

    monkeypatch.setattr(clash_links, "_lookup_shared_links", empty)
    assert asyncio.run(clash_links.resolve_tags(123)) == []


def test_family_players_expand_to_all_accounts_for_their_discord_owners(monkeypatch):
    calls = []

    async def fake_discord_ids(tags):
        calls.append(("tags", tags))
        return {"#H0ME": "123"}

    async def fake_lookup(**kwargs):
        calls.append(("ids", kwargs))
        return [
            {"player_tag": "#H0ME", "user_id": "123"},
            {"player_tag": "#ALT", "user_id": "123"},
            {"player_tag": "#SOMEONE_ELSE", "user_id": "999"},
        ]

    monkeypatch.setattr(clash_links, "resolve_discord_ids", fake_discord_ids)
    monkeypatch.setattr(clash_links, "_lookup_shared_links", fake_lookup)
    result = asyncio.run(clash_links.resolve_family_linked_tags(
        ["#H0ME", "#UNLINKED"]
    ))

    assert calls == [
        ("tags", ["#H0ME", "#UNLINKED"]),
        ("ids", {"discord_ids": ["123"]}),
    ]
    assert result == ["#ALT", "#H0ME"]


def test_family_expansion_preserves_lookup_failure(monkeypatch):
    async def failed(_player_tags):
        return None

    monkeypatch.setattr(clash_links, "resolve_discord_ids", failed)
    assert asyncio.run(clash_links.resolve_family_linked_tags(["#HOME"])) is None


def test_family_expansion_returns_empty_when_no_roster_players_are_linked(monkeypatch):
    async def no_links(_player_tags):
        return {}

    monkeypatch.setattr(clash_links, "resolve_discord_ids", no_links)
    assert asyncio.run(clash_links.resolve_family_linked_tags(["#HOME"])) == []


def test_player_tags_resolve_to_discord_ids(monkeypatch):
    async def fake_lookup(**kwargs):
        assert kwargs == {"player_tags": ["#H0ME", "#MISSING"]}
        return [{"player_tag": "#H0ME", "user_id": "123", "is_verified": True}]

    monkeypatch.setattr(clash_links, "_lookup_shared_links", fake_lookup)
    assert asyncio.run(clash_links.resolve_discord_ids(
        ["#H0ME", "#MISSING"]
    )) == {"#H0ME": "123"}
