"""Bonus review is durable staff selection history, never an in-game award."""

import unittest

import test_cwl_web_roster as roster_fixtures


class BonusTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = roster_fixtures.RosterTests.asyncSetUp
    asyncTearDown = roster_fixtures.RosterTests.asyncTearDown
    auth = roster_fixtures.RosterTests.auth
    call = roster_fixtures.RosterTests.call
    revision = roster_fixtures.RosterTests.revision
    signup = roster_fixtures.RosterTests.signup

    @property
    def base(self):
        return f"/seasons/{self.sid}/bonuses"

    async def setup_published(self):
        await self.signup("main", "#P2Y")
        self.assertEqual((await self.call("POST", "/clans", self.owner, json={"tag": "#C2Y"})).status, 201)
        self.assertEqual((await self.call(
            "PATCH", f"/seasons/{self.sid}/roster/%23P2Y", self.owner,
            json={"revision": await self.revision(), "assigned_clan_tag": "#C2Y", "kept": True},
        )).status, 200)
        response = await self.call(
            "POST", f"/seasons/{self.sid}/publication", self.owner,
            json={"revision": await self.revision(), "acknowledge_unassigned": True, "joining_instructions": ""},
        )
        self.assertEqual(response.status, 201, await response.text())
        self.assertEqual((await self.call(
            "POST", f"/seasons/{self.sid}/participation/sync-settings", self.owner,
            json={"cycle": "2026-10", "enabled": False},
        )).status, 200)

    async def view(self):
        response = await self.call("GET", self.base, self.owner)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def settings(self, revision, *, slots=1, min_attacks=None, min_stars=None, cooldown=None):
        return await self.call(
            "PATCH", self.base + "/settings", self.owner,
            json={"revision": revision, "policy": {
                "min_attacks": min_attacks, "min_stars": min_stars, "cooldown_months": cooldown,
            }, "clans": [{"tag": "#C2Y", "slots": slots}]},
        )

    async def select(self, revision, reason="Staff review"):
        return await self.call(
            "PATCH", self.base + "/draft", self.owner,
            json={"revision": revision, "selections": [{"tag": "#P2Y", "reason": reason}]},
        )

    async def preview(self):
        response = await self.call("GET", self.base + "/preview", self.owner)
        self.assertEqual(response.status, 200, await response.text())
        return await response.json()

    async def test_auth_default_unset_rules_and_validation(self):
        await self.setup_published()
        data = await self.view()
        self.assertEqual(data["cycle"], "2026-10")
        self.assertEqual(data["revision"], 0)
        self.assertEqual(data["policy"], {
            "min_attacks": None, "min_stars": None, "cooldown_months": None,
        })
        self.assertIsNone(data["accounts"][0]["recommended"])
        self.assertEqual(data["history_scope"], "dashboard_confirmations_only")
        self.assertEqual((await self.call("GET", self.base, self.member)).status, 403)
        self.assertEqual((await self.call("GET", self.base)).status, 401)
        no_csrf = {key: value for key, value in self.owner.items() if key != "X-CSRF-Token"}
        self.assertEqual((await self.call(
            "PATCH", self.base + "/draft", no_csrf,
            json={"revision": 0, "selections": []},
        )).status, 403)
        for slots in (-1, 51, True):
            self.assertEqual((await self.settings(0, slots=slots)).status, 400)
        self.assertEqual((await self.settings(0, min_attacks=8)).status, 400)
        self.assertEqual((await self.settings(0, min_stars=22)).status, 400)
        self.assertEqual((await self.settings(0, cooldown=25)).status, 400)
        self.assertEqual((await self.settings(0, slots=None)).status, 200)
        self.assertEqual((await self.settings(0, slots=1)).status, 409)

    async def test_preview_confirm_replay_void_and_snapshot_retention(self):
        await self.setup_published()
        self.assertEqual((await self.settings(0, slots=1)).status, 200)
        self.assertEqual((await self.select(1)).status, 200)
        preview = await self.preview()
        self.assertTrue(preview["can_confirm"])
        self.assertTrue(preview["warnings"])
        self.assertEqual(preview["capacity"][0]["selected_count"], 1)
        body = {"revision": preview["revision"], "fingerprint": preview["fingerprint"], "acknowledge_warnings": False}
        self.assertEqual((await self.call("POST", self.base + "/confirm", self.owner, json=body)).status, 409)
        body["acknowledge_warnings"] = True
        first = await self.call("POST", self.base + "/confirm", self.owner, json=body)
        self.assertEqual(first.status, 200, await first.text())
        data = await first.json()
        self.assertEqual(len(data["history"]), 1)
        row = data["history"][0]
        self.assertEqual(row["record_type"], "dashboard_selection_not_game_award")
        self.assertEqual((row["tag"], row["clan_tag"], row["cycle"]), ("#P2Y", "#C2Y", "2026-10"))
        self.assertIsNone(row["voided_at"])
        batch = self.app["store"].one(
            "SELECT snapshot_json FROM bonus_batches WHERE season_id=?", (self.sid,),
        )
        import json
        snapshot = json.loads(batch["snapshot_json"])
        self.assertEqual(snapshot["capacity"][0]["slots"], 1)
        self.assertEqual(snapshot["selected"][0]["tag"], "#P2Y")
        self.assertEqual(snapshot["policy"]["min_attacks"], None)
        replay = await self.call("POST", self.base + "/confirm", self.owner, json=body)
        self.assertEqual(replay.status, 200)
        self.assertEqual(len((await replay.json())["history"]), 1)
        self.assertEqual((await self.select(data["revision"])).status, 200)
        retry_preview = await self.preview()
        self.assertFalse(retry_preview["can_confirm"])
        self.assertTrue(any("already confirmed" in text for text in retry_preview["blocking_reasons"]))
        self.assertEqual((await self.call(
            "POST", self.base + f"/{row['id']}/void", self.owner,
            json={"revision": (await self.view())["revision"], "reason": "Entered in error"},
        )).status, 200)
        data = await self.view()
        self.assertEqual(data["history"][0]["void_reason"], "Entered in error")
        self.assertIsNotNone(data["history"][0]["voided_at"])
        self.assertEqual((await self.call(
            "POST", self.base + f"/{row['id']}/void", self.owner,
            json={"revision": data["revision"], "reason": "Again"},
        )).status, 409)
        self.assertGreaterEqual(len(self.app["store"].rows(
            "SELECT * FROM bonus_audit WHERE season_id=?", (self.sid,),
        )), 4)

    async def test_preview_invalidates_on_participation_change_and_capacity_required(self):
        await self.setup_published()
        self.assertEqual((await self.select(0)).status, 200)
        first = await self.preview()
        self.assertFalse(first["can_confirm"])
        self.assertTrue(any("slots" in text for text in first["blocking_reasons"]))
        self.assertEqual((await self.settings(1, slots=0)).status, 200)
        second = await self.preview()
        self.assertFalse(second["can_confirm"])
        self.assertTrue(any("exceed" in text for text in second["blocking_reasons"]))
        self.assertEqual((await self.settings(2, slots=1)).status, 200)
        third = await self.preview()
        participation = await self.call(
            "PATCH", f"/seasons/{self.sid}/participation/%23P2Y", self.owner,
            json={"publication_version": 1, "revision": 0, "attacks": 2, "stars": 5, "notes": "Verified"},
        )
        self.assertEqual(participation.status, 200, await participation.text())
        stale = await self.call(
            "POST", self.base + "/confirm", self.owner,
            json={"revision": third["revision"], "fingerprint": third["fingerprint"], "acknowledge_warnings": True},
        )
        self.assertEqual(stale.status, 409)
        self.assertEqual((await self.view())["history"], [])

    async def test_incomplete_source_requires_reason_and_warning_ack(self):
        await self.setup_published()
        participation = await self.call(
            "PATCH", f"/seasons/{self.sid}/participation/%23P2Y", self.owner,
            json={"publication_version": 1, "revision": 0, "attacks": 7, "stars": 21, "notes": ""},
        )
        self.assertEqual(participation.status, 200)
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO participation_source_results("
                "season_id,cycle,tag,attacks,stars,status,complete,checked_at,warning"
                ") VALUES (?,?,?,?,?,?,?,?,?)",
                (self.sid, "2026-10", "#P2Y", 1, 3, "partial", 0,
                 "2026-10-14T16:00:00+00:00", "Only one war observed"),
            )
        self.assertEqual((await self.settings(
            0, slots=1, min_attacks=1, min_stars=1, cooldown=0,
        )).status, 200)
        self.assertEqual((await self.select(1, reason="")).status, 200)
        preview = await self.preview()
        self.assertTrue(preview["selected"][0]["recommended"])
        self.assertFalse(preview["can_confirm"])
        self.assertTrue(preview["warnings"])
        self.assertTrue(any("reason" in item for item in preview["blocking_reasons"]))
        self.assertEqual((await self.select(2, reason="Staff checked partial source")).status, 200)
        preview = await self.preview()
        self.assertTrue(preview["can_confirm"])
        self.assertEqual((await self.call(
            "POST", self.base + "/confirm", self.owner,
            json={"revision": preview["revision"], "fingerprint": preview["fingerprint"],
                  "acknowledge_warnings": False},
        )).status, 409)

    async def test_cycle_wide_capacity_counts_other_seasons(self):
        await self.setup_published()
        with self.app["store"].tx() as db:
            other = db.execute("INSERT INTO seasons(label) VALUES ('Other season')").lastrowid
            batch = db.execute(
                "INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (other, "2026-10", 0, "other", "{}", "staff", "2026-10-01T00:00:00+00:00"),
            ).lastrowid
            db.execute(
                "INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch, other, "2026-10", 1, "#Q2Y", "Other", "main", "#C2Y", "Host", 7, 21, "test", "[]", "staff", "2026-10-01T00:00:00+00:00"),
            )
        self.assertEqual((await self.settings(0, slots=1)).status, 200)
        self.assertEqual((await self.select(1)).status, 200)
        preview = await self.preview()
        self.assertEqual(preview["capacity"][0]["confirmed_count"], 1)
        self.assertFalse(preview["can_confirm"])
        self.assertTrue(any("exceed" in text for text in preview["blocking_reasons"]))
        self.assertEqual((await self.settings(2, slots=2)).status, 200)
        preview = await self.preview()
        self.assertTrue(preview["can_confirm"])

    async def test_same_season_prior_month_counts_for_cooldown_and_blocks_reuse(self):
        await self.setup_published()
        with self.app["store"].tx() as db:
            batch = db.execute(
                "INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (self.sid, "2026-09", 99, "older", "{}", "staff", "2026-09-20T00:00:00+00:00"),
            ).lastrowid
            db.execute(
                "INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch, self.sid, "2026-09", 1, "#P2Y", "Player", "main", "#C2Y", "Host", 7, 21, "test", "[]", "staff", "2026-09-20T00:00:00+00:00"),
            )
        participation = await self.call(
            "PATCH", f"/seasons/{self.sid}/participation/%23P2Y", self.owner,
            json={"publication_version": 1, "revision": 0, "attacks": 7, "stars": 21, "notes": ""},
        )
        self.assertEqual(participation.status, 200)
        self.assertEqual((await self.settings(
            0, slots=2, min_attacks=1, min_stars=1, cooldown=2,
        )).status, 200)
        data = await self.view()
        self.assertEqual(data["accounts"][0]["last_confirmed_bonus"]["cycle"], "2026-09")
        self.assertFalse(data["accounts"][0]["recommended"])
        self.assertEqual(data["active_other_cycles"], ["2026-09"])
        self.assertEqual((await self.select(1)).status, 200)
        preview = await self.preview()
        self.assertFalse(preview["can_confirm"])
        self.assertTrue(any("create a new season" in text for text in preview["blocking_reasons"]))

    async def test_archived_read_only_and_cooldown_only_prior_month(self):
        await self.setup_published()
        with self.app["store"].tx() as db:
            prior_season = db.execute(
                "INSERT INTO seasons(label,signup_open) VALUES ('Prior cycle',0)"
            ).lastrowid
            batch = db.execute(
                "INSERT INTO bonus_batches(season_id,cycle,base_revision,fingerprint,snapshot_json,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (prior_season, "2026-09", 99, "prior", "{}", "staff", "2026-09-20T00:00:00+00:00"),
            ).lastrowid
            db.execute(
                "INSERT INTO bonus_confirmations(batch_id,season_id,cycle,publication_version,tag,player_name,pool,clan_tag,clan_name,attacks,stars,reason,warnings_json,confirmed_by,confirmed_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (batch, prior_season, "2026-09", 1, "#P2Y", "Player", "main", "#C2Y", "Host", 7, 21, "test", "[]", "staff", "2026-09-20T00:00:00+00:00"),
            )
        participation = await self.call(
            "PATCH", f"/seasons/{self.sid}/participation/%23P2Y", self.owner,
            json={"publication_version": 1, "revision": 0, "attacks": 7, "stars": 21, "notes": ""},
        )
        self.assertEqual(participation.status, 200)
        self.assertEqual((await self.settings(0, slots=1, min_attacks=1, min_stars=1, cooldown=2)).status, 200)
        data = await self.view()
        account = data["accounts"][0]
        self.assertFalse(account["recommended"])
        self.assertIn("cooldown", account["eligibility_reason"])
        self.assertEqual(account["last_confirmed_bonus"]["cycle"], "2026-09")
        self.assertEqual((await self.call(
            "PATCH", f"/seasons/{self.sid}", self.owner, json={"status": "archived"},
        )).status, 200)
        self.assertEqual((await self.call(
            "PATCH", self.base + "/draft", self.owner,
            json={"revision": 1, "selections": []},
        )).status, 423)
        self.assertEqual((await self.call("GET", self.base, self.owner)).status, 200)
