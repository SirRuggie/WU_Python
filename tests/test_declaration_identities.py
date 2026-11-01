import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
from cwl_web import declaration_identities as identities

UID = "123456789012345678"


def rows():
    return [
        {
            "extras": [{"tag": "#P" + str(i)} for i in range(25)],
            "low_th": [{"tag": "#LOW"}],
            "fillers": [{"tag": "#FILLER"}],
        }
    ]


def test_one_shared_batch_for_25_rows_and_low_th_without_per_row_directory(monkeypatch):
    clans = rows()
    lookup = AsyncMock(return_value={"#P0": UID, "#LOW": UID})
    directory = AsyncMock(
        return_value=[
            {
                "user": {
                    "id": UID,
                    "username": "family",
                    "global_name": "Family member",
                },
                "nick": "Family nick",
            }
        ]
    )
    monkeypatch.setattr(identities, "linked_owners", lookup)
    monkeypatch.setattr(identities, "searchable_members", directory)
    asyncio.run(identities.decorate(S(), clans))
    lookup.assert_awaited_once()
    directory.assert_awaited_once()
    assert len(lookup.await_args.args[0]) == 27
    assert clans[0]["extras"][0]["discord_profile"]["display_name"] == "Family nick"
    assert clans[0]["low_th"][0]["discord_id"] == UID
    assert "discord_id" not in clans[0]["extras"][1]
    assert "role_ids" not in clans[0]["extras"][0]["discord_profile"]


def test_link_or_directory_failure_keeps_all_member_rows_and_no_guessed_identity(
    monkeypatch,
):
    async def run():
        for stage in ("links", "directory"):
            clans = rows()
            lookup = (
                AsyncMock(side_effect=RuntimeError("Source unavailable"))
                if stage == "links"
                else AsyncMock(return_value={"#P0": UID})
            )
            directory = AsyncMock(side_effect=RuntimeError("Directory unavailable"))
            monkeypatch.setattr(identities, "linked_owners", lookup)
            monkeypatch.setattr(identities, "searchable_members", directory)
            await identities.decorate(S(), clans)
            assert len(clans[0]["extras"]) == 25 and not any(
                "discord_id" in row for row in clans[0]["extras"]
            )
            if stage == "links":
                directory.assert_not_awaited()

    asyncio.run(run())


def test_unlinked_or_nonmember_owners_have_no_identity_and_no_empty_lookup(monkeypatch):
    async def run():
        lookup = AsyncMock(return_value={})
        directory = AsyncMock()
        monkeypatch.setattr(identities, "linked_owners", lookup)
        monkeypatch.setattr(identities, "searchable_members", directory)
        await identities.decorate(S(), [])
        lookup.assert_not_awaited()
        clans = rows()
        await identities.decorate(S(), clans)
        directory.assert_not_awaited()
        lookup.return_value = {"#P0": UID}
        directory.return_value = []
        await identities.decorate(S(), clans)
        assert "discord_id" not in clans[0]["extras"][0]

    asyncio.run(run())


import unittest
from unittest.mock import patch
import test_declaration_extras as _extras_fixture


class DeclarationIdentityHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = _extras_fixture.DeclarationExtrasHTTP.asyncSetUp
    asyncTearDown = _extras_fixture.DeclarationExtrasHTTP.asyncTearDown
    auth = _extras_fixture.DeclarationExtrasHTTP.auth
    call = _extras_fixture.DeclarationExtrasHTTP.call
    signup = _extras_fixture.DeclarationExtrasHTTP.signup
    revision = _extras_fixture.DeclarationExtrasHTTP.revision
    prepare = _extras_fixture.DeclarationExtrasHTTP.prepare
    read = _extras_fixture.DeclarationExtrasHTTP.read

    async def test_editor_guard_before_optional_lookup_and_one_batch_per_check(self):
        await self.prepare()
        owners = AsyncMock(return_value={"#V2Y": UID})
        directory = AsyncMock(
            return_value=[
                {
                    "user": {
                        "id": UID,
                        "username": "family",
                        "global_name": "Family member",
                    }
                }
            ]
        )
        with patch.object(identities, "linked_owners", owners), patch.object(
            identities, "searchable_members", directory
        ):
            denied = await self.call("GET", self.path + "?source=draft", self.member)
            self.assertEqual(denied.status, 403)
            owners.assert_not_awaited()
            directory.assert_not_awaited()
            result = await self.read()
        owners.assert_awaited_once()
        directory.assert_awaited_once()
        members = [m for c in result["clans"] for m in c["extras"] or []]
        self.assertEqual(
            next(m for m in members if m["tag"] == "#V2Y")["discord_profile"][
                "display_name"
            ],
            "Family member",
        )


def test_optional_identity_batch_has_an_eight_second_budget_and_retains_rows(
    monkeypatch,
):
    import pytest

    budgets = []

    class Expired:
        async def __aenter__(self):
            raise TimeoutError()

        async def __aexit__(self, *args):
            return False

    def timeout(value):
        budgets.append(value)
        return Expired()

    lookup = AsyncMock()
    monkeypatch.setattr(identities, "linked_owners", lookup)
    monkeypatch.setattr(identities.asyncio, "timeout", timeout)
    clans = rows()
    asyncio.run(identities.decorate(S(), clans))
    assert budgets == [8] and len(clans[0]["extras"]) == 25
    lookup.assert_not_awaited()
