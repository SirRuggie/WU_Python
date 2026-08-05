"""Tests for Discord-link expansion used by the clan movement tracker."""

import asyncio

from utils import clash_links


def test_family_players_expand_to_all_accounts_for_their_discord_owners(monkeypatch):
    calls = []

    async def fake_resolve(identifiers):
        calls.append(identifiers)
        if len(calls) == 1:
            return {"#HOME": "123", "#UNLINKED": None}
        return {
            "#123": None,
            "#HOME": "123",
            "#ALT": 123,
            "#SOMEONE_ELSE": "999",
        }

    monkeypatch.setattr(clash_links, "_resolve_identifiers", fake_resolve)
    result = asyncio.run(clash_links.resolve_family_linked_tags(
        ["#HOME", "#UNLINKED"]
    ))

    assert calls == [["#HOME", "#UNLINKED"], ["123"]]
    assert result == ["#ALT", "#HOME"]


def test_family_expansion_preserves_lookup_failure(monkeypatch):
    async def failed(_identifiers):
        return None

    monkeypatch.setattr(clash_links, "_resolve_identifiers", failed)
    assert asyncio.run(clash_links.resolve_family_linked_tags(["#HOME"])) is None


def test_family_expansion_returns_empty_when_no_roster_players_are_linked(monkeypatch):
    async def no_links(_identifiers):
        return {"#HOME": None}

    monkeypatch.setattr(clash_links, "_resolve_identifiers", no_links)
    assert asyncio.run(clash_links.resolve_family_linked_tags(["#HOME"])) == []
