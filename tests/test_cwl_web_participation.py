"""Staff participation ledger over immutable CWL publication snapshots."""

import unittest

import test_cwl_web_roster as roster_fixtures


class ParticipationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = roster_fixtures.RosterTests.asyncSetUp
    asyncTearDown = roster_fixtures.RosterTests.asyncTearDown
    auth = roster_fixtures.RosterTests.auth
    call = roster_fixtures.RosterTests.call
    revision = roster_fixtures.RosterTests.revision
    signup = roster_fixtures.RosterTests.signup

    @property
    def endpoint(self):
        return f"/seasons/{self.sid}/participation"

    async def publish(self):
        response = await self.call(
            "POST", f"/seasons/{self.sid}/publication", self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": "",
            },
        )
        self.assertEqual(response.status, 201, await response.text())
        return (await response.json())["published"]["version"]

    async def save(self, player_tag="#P2Y", revision=0, attacks=2, stars=5, notes="", publication_version=None):
        if publication_version is None:
            response = await self.call("GET", self.endpoint, self.owner)
            publication_version = (await response.json())["publication_version"] or 1
        return await self.call(
            "PATCH", self.endpoint + "/%23" + player_tag[1:],
            self.owner,
            json={
                "publication_version": publication_version,
                "revision": revision, "attacks": attacks,
                "stars": stars, "notes": notes,
            },
        )

    async def test_staff_only_csrf_and_unpublished_unknown_tag(self):
        response = await self.call("GET", self.endpoint, self.owner)
        self.assertEqual(response.status, 200)
        data = await response.json()
        self.assertEqual(data["publication_version"], None)
        self.assertEqual(data["accounts"], [])
        self.assertEqual(data["sync"]["status"], "never")
        self.assertEqual((await self.call("GET", self.endpoint, self.member)).status, 403)
        self.assertEqual((await self.call("GET", self.endpoint)).status, 401)
        await self.signup("main", "#P2Y")
        self.assertEqual((await self.save()).status, 409)
        await self.publish()
        self.assertEqual((await self.call(
            "PATCH", self.endpoint + "/%23P2Y", self.member,
            json={"publication_version": 1, "revision": 0, "attacks": 2, "stars": 5, "notes": ""},
        )).status, 403)
        no_csrf = {key: value for key, value in self.owner.items() if key != "X-CSRF-Token"}
        self.assertEqual((await self.call(
            "PATCH", self.endpoint + "/%23P2Y", no_csrf,
            json={"publication_version": 1, "revision": 0, "attacks": 2, "stars": 5, "notes": ""},
        )).status, 403)

    async def test_validation_row_cas_audit_and_no_roster_revision_bump(self):
        await self.signup("main", "#P2Y")
        await self.publish()
        roster_revision = await self.revision()
        for attacks, stars, notes in [
            (-1, 0, ""), (8, 0, ""), (True, 0, ""),
            (0, -1, ""), (0, 22, ""), (2, 7, ""),
            (1, True, ""), (None, None, "x" * 2001),
        ]:
            response = await self.save(attacks=attacks, stars=stars, notes=notes)
            self.assertEqual(response.status, 400, await response.text())
        response = await self.save(attacks=None, stars=None, notes="unknown")
        self.assertEqual(response.status, 200, await response.text())
        first = (await response.json())["account"]
        self.assertEqual(first["revision"], 1)
        self.assertEqual(first["recorded_publication_version"], 1)
        self.assertIsNone(first["attacks"])
        self.assertEqual(first["notes"], "unknown")
        self.assertEqual(first["updated_by"], self.owner_user_id)
        self.assertTrue(first["updated_at"].endswith("+00:00"))
        self.assertEqual((await self.save(revision=0)).status, 409)
        response = await self.save(revision=1, attacks=7, stars=21, notes="complete")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["account"]["revision"], 2)
        self.assertEqual(await self.revision(), roster_revision)
        rows = self.app["store"].rows(
            "SELECT * FROM participation_audit WHERE season_id=? AND tag=? ORDER BY id",
            (self.sid, "#P2Y"),
        )
        self.assertEqual([row["revision"] for row in rows], [1, 2])

    @property
    def owner_user_id(self):
        return "505227988229554179"

    async def test_republication_keeps_recorded_clan_identity(self):
        await self.signup("main", "#P2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        self.assertEqual(response.status, 201)
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": "#C2Y", "kept": True,
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        await self.publish()
        first = await self.save(notes="Recorded at original host")
        self.assertEqual(first.status, 200, await first.text())
        self.assertEqual((await first.json())["account"]["assigned_clan_tag"], "#C2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#J2Y"})
        self.assertEqual(response.status, 201)
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": "#J2Y", "kept": True,
            },
        )
        self.assertEqual(response.status, 200, await response.text())
        await self.publish()
        response = await self.call("GET", self.endpoint, self.owner)
        data = await response.json()
        self.assertEqual(data["publication_version"], 2)
        row = data["accounts"][0]
        self.assertEqual(row["assigned_clan_tag"], "#C2Y")
        self.assertEqual(row["recorded_publication_version"], 1)
        self.assertTrue(row["in_latest_publication"])
        self.assertTrue(row["roster_changed"])
        response = await self.save(revision=1, attacks=3, stars=7, notes="Later edit")
        self.assertEqual(response.status, 200)
        self.assertEqual((await response.json())["account"]["assigned_clan_tag"], "#C2Y")

    async def test_withdrawn_saved_account_retained_after_new_publication(self):
        await self.signup("main", "#P2Y")
        await self.publish()
        self.assertEqual((await self.save(notes="Played")).status, 200)
        response = await self.call(
            "DELETE", f"/seasons/{self.sid}/signups/%23P2Y", self.member,
        )
        self.assertEqual(response.status, 200, await response.text())
        await self.signup("lazy", "#Q2Y", True)
        await self.publish()
        response = await self.call("GET", self.endpoint, self.owner)
        data = await response.json()
        self.assertEqual([row["tag"] for row in data["accounts"]], ["#P2Y", "#Q2Y"])
        historical, fresh = data["accounts"]
        self.assertFalse(historical["in_latest_publication"])
        self.assertTrue(historical["roster_changed"])
        self.assertEqual(historical["notes"], "Played")
        self.assertEqual(historical["recorded_publication_version"], 1)
        self.assertTrue(fresh["in_latest_publication"])
        self.assertEqual(fresh["revision"], 0)
        self.assertEqual((await self.save("#P2Y", revision=1, notes="Final note")).status, 200)

    async def test_archived_season_is_read_only_but_staff_can_view(self):
        await self.signup("main", "#P2Y")
        await self.publish()
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}", self.owner,
            json={"status": "archived"},
        )
        self.assertEqual(response.status, 200)
        self.assertEqual((await self.save()).status, 423)
        self.assertEqual((await self.call("GET", self.endpoint, self.owner)).status, 200)



    async def test_first_save_rejects_republished_clan_race(self):
        await self.signup("main", "#P2Y")
        await self.publish()
        response = await self.call("GET", self.endpoint, self.owner)
        original = (await response.json())["accounts"][0]
        self.assertEqual(original["recorded_publication_version"], None)
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})
        self.assertEqual(response.status, 201)
        response = await self.call(
            "PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": "#C2Y", "kept": True,
            },
        )
        self.assertEqual(response.status, 200)
        await self.publish()
        stale = await self.save(
            publication_version=1, revision=0, notes="Old clan result",
        )
        self.assertEqual(stale.status, 409)
        self.assertEqual(self.app["store"].rows(
            "SELECT * FROM participation_records WHERE season_id=?",
            (self.sid,),
        ), [])
        fresh = await self.save(
            publication_version=2, revision=0, notes="New clan result",
        )
        self.assertEqual(fresh.status, 200)
        account = (await fresh.json())["account"]
        self.assertEqual(account["assigned_clan_tag"], "#C2Y")
        self.assertEqual(account["recorded_publication_version"], 2)
