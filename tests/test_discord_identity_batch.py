import unittest
from unittest.mock import AsyncMock, patch
import test_cwl_web_roster as fixture


class DiscordIdentityBatch(unittest.IsolatedAsyncioTestCase):
    auth = fixture.RosterTests.auth
    call = fixture.RosterTests.call
    revision = fixture.RosterTests.revision
    asyncSetUp = fixture.RosterTests.asyncSetUp
    asyncTearDown = fixture.RosterTests.asyncTearDown

    async def test_one_directory_read_resolves_bounded_batch_without_role_fields(self):
        ids = [str(123456789012345678 + i) for i in range(75)]
        rows = [
            {
                "user": {"id": uid, "username": "fixture" + str(i), "avatar": None},
                "roles": ["1"],
            }
            for i, uid in enumerate(ids)
        ]
        with patch(
            "cwl_web.manage_roles.searchable_members", AsyncMock(return_value=rows)
        ) as directory:
            response = await self.call(
                "GET", "/staff-signup-members?ids=" + ",".join(ids), self.owner
            )
            self.assertEqual(response.status, 200, await response.text())
            data = await response.json()
            self.assertEqual(len(data["options"]), 75)
            self.assertFalse(data["truncated"])
            self.assertTrue(
                all(
                    r["role_ids"] == []
                    and r["role_names"] == []
                    and r["avatar_url"].startswith("https://cdn.discordapp.com/")
                    for r in data["options"]
                )
            )
            self.assertEqual(directory.await_count, 1)

    async def test_member_scope_and_malformed_batches_rejected_before_directory(self):
        with patch(
            "cwl_web.manage_roles.searchable_members", AsyncMock(return_value=[])
        ) as directory:
            self.assertEqual(
                (
                    await self.call(
                        "GET",
                        "/staff-signup-members?ids=123456789012345678",
                        self.member,
                    )
                ).status,
                403,
            )
            for query in (
                "",
                "bad",
                "123",
                "123456789012345678," + ",".join(["223456789012345678"] * 100),
            ):
                self.assertEqual(
                    (
                        await self.call(
                            "GET", "/staff-signup-members?ids=" + query, self.owner
                        )
                    ).status,
                    400,
                )
            directory.assert_not_awaited()


def test_strikes_batch_uses_existing_strikes_read_scope_without_cwl_permission():
    import asyncio, json
    from cwl_web import strikes, manage_roles
    from types import SimpleNamespace

    async def scenario():
        request = SimpleNamespace(method="GET", query={"ids": "123456789012345678"})

        async def allow(req, scope, *, write):
            assert req is request and scope == "strikes_read" and write is False

        rows = [
            {
                "user": {"id": "123456789012345678", "username": "Read only member"},
                "roles": ["private-role"],
            }
        ]
        with patch.object(strikes.shared, "require_manage", allow), patch.object(
            manage_roles, "searchable_members", AsyncMock(return_value=rows)
        ) as directory:
            response = await strikes.members(request)
            profile = json.loads(response.text)["options"][0]
            assert set(profile) == {"id", "display_name", "username", "avatar_url"}
            assert (
                profile["id"] == "123456789012345678"
                and "private-role" not in response.text
            )
            directory.assert_awaited_once()

    asyncio.run(scenario())
