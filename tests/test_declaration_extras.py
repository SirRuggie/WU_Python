import unittest
from unittest.mock import AsyncMock, patch
import test_cwl_web_roster as roster_tests
from cwl_web.providers import ProviderUnavailable
from utils.declaration_extras import extras_for


def test_account_tags_not_owner_identity_determine_membership():
    accounts = [
        {
            "tag": "#P2Y",
            "user_id": "100",
            "assigned_clan_tag": "#C2Y",
            "assigned_clan_name": "Target",
        },
        {
            "tag": "#Q2Y",
            "user_id": "100",
            "assigned_clan_tag": "#R2Y",
            "assigned_clan_name": "Other",
        },
        {"tag": "#G2Y", "user_id": "100", "assigned_clan_tag": None},
    ]
    members = [
        {"tag": tag, "name": tag, "town_hall": 16, "user_id": "100"}
        for tag in ("#P2Y", "#Q2Y", "#G2Y", "#V2Y")
    ]
    rows = extras_for("#C2Y", members, accounts, {})
    assert {r["tag"] for r in rows} == {"#Q2Y", "#G2Y", "#V2Y"}
    assert {r["tag"]: r["context"] for r in rows} == {
        "#Q2Y": "Assigned to Other",
        "#G2Y": "Signed up, unplaced",
        "#V2Y": "Not signed up",
    }


class DeclarationExtrasHTTP(unittest.IsolatedAsyncioTestCase):
    auth = roster_tests.RosterTests.auth
    call = roster_tests.RosterTests.call
    signup = roster_tests.RosterTests.signup
    revision = roster_tests.RosterTests.revision
    asyncSetUp = roster_tests.RosterTests.asyncSetUp
    asyncTearDown = roster_tests.RosterTests.asyncTearDown

    async def prepare(self):
        for tag in ("#P2Y", "#Q2Y", "#G2Y"):
            await self.signup("lazy", tag)
        with self.app["store"].tx() as db:
            db.executemany(
                "INSERT INTO clans(tag,name,pool) VALUES (?,?,?)",
                [
                    ("#C2Y", "Lazy target", "lazy"),
                    ("#R2Y", "Other lazy", "lazy"),
                    ("#J2Y", "Main host", "main"),
                ],
            )
            db.executemany(
                "INSERT INTO lineup(season_id,tag) VALUES (?,?)",
                [(self.sid, tag) for tag in ("#C2Y", "#R2Y", "#J2Y")],
            )
            db.executemany(
                "INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES (?,?,?,15)",
                [
                    (self.sid, "#C2Y", "lazy"),
                    (self.sid, "#R2Y", "lazy"),
                    (self.sid, "#J2Y", "main"),
                ],
            )
            db.executemany(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                [(self.sid, "#P2Y", "#C2Y"), (self.sid, "#Q2Y", "#R2Y")],
            )
        self.provider = AsyncMock(
            side_effect=lambda value: {
                "tag": value,
                "name": value,
                "members": (
                    [
                        {"tag": tag, "name": tag, "town_hall": 16}
                        for tag in ("#P2Y", "#Q2Y", "#G2Y", "#V2Y")
                    ]
                    if value == "#C2Y"
                    else []
                ),
            }
        )
        self.providers.clan_roster = self.provider
        self.path = f"/seasons/{self.sid}/declaration-extras"

    async def publish(self):
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/publication",
            self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": "fixture",
            },
        )
        self.assertEqual(response.status, 201, await response.text())

    async def read(self, query="?source=draft"):
        response = await self.call("GET", self.path + query, self.owner)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_extras_context_main_excluded_and_cached_empty_clan(self):
        await self.prepare()
        data = await self.read()
        rows = {r["tag"]: r for r in data["clans"]}
        self.assertEqual(set(rows), {"#C2Y", "#R2Y"})
        self.assertEqual(rows["#C2Y"]["count"], 3)
        self.assertEqual(rows["#R2Y"]["count"], 0)
        self.assertEqual(rows["#R2Y"]["extras"], [])
        self.assertTrue(rows["#C2Y"]["checked_at"])
        await self.read()
        self.assertEqual(self.provider.await_count, 2)
        self.assertNotIn(
            "#J2Y", [call.args[0] for call in self.provider.await_args_list]
        )

    async def test_failed_read_never_becomes_zero_even_with_prior_cache(self):
        await self.prepare()
        original = await self.read()
        stamp = original["clans"][0]["checked_at"]
        self.provider.side_effect = ProviderUnavailable("fixture outage")
        rows = (await self.read("?source=draft&refresh=1"))["clans"]
        self.assertTrue(
            all(
                r["status"] == "unavailable"
                and r["count"] is None
                and r["extras"] is None
                for r in rows
            )
        )
        self.assertEqual(rows[0]["checked_at"], stamp)

    async def test_cold_failure_and_incomplete_member_names_are_unavailable(self):
        await self.prepare()
        self.provider.side_effect = ProviderUnavailable("fixture cold outage")
        rows = (await self.read())["clans"]
        self.assertTrue(
            all(r["count"] is None and r["checked_at"] is None for r in rows)
        )
        self.provider.side_effect = lambda value: {
            "tag": value,
            "name": value,
            "members": [{"tag": "#V2Y", "name": None}],
        }
        rows = (await self.read("?source=draft&refresh=1"))["clans"]
        self.assertTrue(
            all(r["count"] is None and r["status"] == "unavailable" for r in rows)
        )

    async def test_published_and_draft_use_their_own_assignments(self):
        await self.prepare()
        await self.publish()
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE roster_entries SET assigned_clan_tag='#C2Y' WHERE season_id=? AND tag='#Q2Y'",
                (self.sid,),
            )
        published = await self.read("?source=published&basis=1")
        draft = await self.read("?source=draft")
        target = next(c for c in published["clans"] if c["tag"] == "#C2Y")
        self.assertEqual(target["count"], 2)
        self.assertEqual(target["unpublished_count"], 1)
        self.assertEqual(target["unpublished"][0]["tag"], "#Q2Y")
        self.assertEqual(target["unpublished"][0]["context"], "Assigned to Lazy target")
        self.assertFalse(target["unpublished"][0]["assigned_here"])
        self.assertTrue(target["unpublished"][0]["not_published_yet"])
        self.assertEqual({row["tag"] for row in target["extras"]}, {"#G2Y", "#V2Y"})
        self.assertEqual(
            next(c for c in draft["clans"] if c["tag"] == "#C2Y")["count"], 2
        )
        self.assertEqual(
            (
                await self.call(
                    "GET", self.path + "?source=published&basis=999", self.owner
                )
            ).status,
            409,
        )

    async def test_permissions_missing_publication_bad_source_and_stale_completion(
        self,
    ):
        await self.prepare()
        self.assertEqual((await self.call("GET", self.path, self.member)).status, 403)
        self.assertEqual(
            (await self.call("GET", self.path + "?source=invalid", self.owner)).status,
            400,
        )
        self.assertEqual(
            (
                await self.call("GET", self.path + "?source=published", self.owner)
            ).status,
            409,
        )
        from cwl_web.declaration_extras import snapshot

        calls = []

        def changed(request, source):
            value = snapshot(request, source)
            calls.append(True)
            return value if len(calls) == 1 else (value[0], value[1], value[2] + 1)

        with patch("cwl_web.declaration_extras.snapshot", side_effect=changed):
            self.assertEqual(
                (
                    await self.call("GET", self.path + "?source=draft", self.owner)
                ).status,
                409,
            )

    async def test_signup_after_publication_uses_current_signup_context(self):
        await self.prepare()
        with self.app["store"].tx() as db:
            db.execute(
                "DELETE FROM signups WHERE season_id=? AND tag='#G2Y'", (self.sid,)
            )
        await self.publish()
        await self.signup("lazy", "#G2Y")
        data = await self.read("?source=published")
        target = next(c for c in data["clans"] if c["tag"] == "#C2Y")
        player = next(r for r in target["extras"] if r["tag"] == "#G2Y")
        self.assertEqual(player["context"], "Signed up, unplaced")

    async def test_timeout_never_turns_cached_current_empty_into_zero(self):
        from types import SimpleNamespace

        cache = SimpleNamespace(
            refresh_roster=AsyncMock(side_effect=TimeoutError()),
            roster=lambda tag: {
                "status": "current",
                "value": {"members": []},
                "checked_at": "2026-11-01T05:00:00Z",
            },
        )
        await self.prepare()
        with patch("cwl_web.declaration_extras.observations", return_value=cache):
            rows = (await self.read())["clans"]
        self.assertTrue(
            all(
                r["status"] == "unavailable"
                and r["count"] is None
                and r["extras"] is None
                for r in rows
            )
        )


def test_draft_move_classification_never_changes_published_membership():
    member = [{"tag": "#P2Y", "name": "Player", "town_hall": 16}]
    elsewhere = [{"tag": "#P2Y", "assigned_clan_tag": "#R2Y"}]
    here = [{"tag": "#P2Y", "assigned_clan_tag": "#C2Y"}]
    moved = extras_for(
        "#C2Y", member, elsewhere, {"#C2Y": "Target"}, current_accounts=here
    )
    assert moved[0]["not_published_yet"] is True
    assert moved[0]["assigned_here"] is False
    assert moved[0]["context"] == "Assigned to Target"
    # Published here stays part of readiness even after a draft move out.
    assert extras_for("#C2Y", member, here, {}, current_accounts=elsewhere) == []
    intruder = extras_for("#C2Y", member, elsewhere, {}, current_accounts=elsewhere)
    assert not intruder[0].get("not_published_yet")
    assert intruder[0]["assigned_here"] is False
    assert not extras_for("#C2Y", member, [], {})[0].get("not_published_yet")


def test_published_low_th_and_marked_fillers_never_become_unpublished_moves():
    for category, th, marked in (
        ("low_th", 8, False),
        ("fillers", 16, True),
        ("fillers", 8, True),
    ):
        assignment = [{"tag": "#P2Y", "assigned_clan_tag": "#C2Y"}]
        rows = extras_for(
            "#C2Y",
            [{"tag": "#P2Y", "name": "Rostered", "town_hall": th}],
            assignment,
            {"#C2Y": "Target"},
            current_accounts=assignment,
            roster_marks={"#P2Y": {"roster_filler": marked}},
            category=category,
        )
        assert len(rows) == 1
        assert rows[0]["assigned_here"] is True
        assert not rows[0].get("not_published_yet")
