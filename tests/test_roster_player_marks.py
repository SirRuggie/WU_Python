"""Season-independent staff marks never infer or modify Strikes filler rules."""

import pytest
from cwl_web.store import Store
from utils import roster_player_marks as marks
from utils.cwl_balance import balance_accounts


def test_migration_marks_cas_audit_and_cross_season_revision(tmp_path):
    path = tmp_path / "fixture.sqlite"
    store = Store(str(path))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES (1,'one'),(2,'two')")
        before = {
            row["name"]: db.execute(
                'SELECT COUNT(*) FROM "' + row["name"] + '"'
            ).fetchone()[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    Store(str(path))
    with store.tx() as db:
        after = {
            name: db.execute('SELECT COUNT(*) FROM "' + name + '"').fetchone()[0]
            for name in before
        }
        assert before == after
        assert not marks.mark(db, "#P2Y")["roster_filler"]
        old, new = marks.save(db, "#P2Y", True, 0, "staff")
        assert old["revision"] == 0 and new["revision"] == 1
        assert marks.incoming_regular(db, ["#P2Y", "#Q2Y"]) == ["#Q2Y"]
        assert [
            r[0]
            for r in db.execute("SELECT revision FROM roster_meta ORDER BY season_id")
        ] == [1, 1]
        with pytest.raises(marks.MarkConflict):
            marks.save(db, "#P2Y", False, 0, "other")
        assert marks.save(db, "#P2Y", True, 1, "staff")[1] == new
        assert (
            db.execute("SELECT COUNT(*) FROM roster_player_mark_audit").fetchone()[0]
            == 1
        )
        marks.save(db, "#P2Y", False, 1, "staff")
        assert not marks.mark(db, "#P2Y")["roster_filler"]
        assert (
            db.execute("SELECT COUNT(*) FROM roster_player_mark_audit").fetchone()[0]
            == 2
        )


def test_filler_is_manual_only_balance_and_still_occupies_capacity():
    clan = dict(
        tag="host",
        pool="lazy",
        capacity=15,
        min_weight=None,
        max_weight=None,
        archived=False,
    )
    accounts = [
        dict(
            tag=str(i),
            assigned_clan_tag="host",
            effective_weight=100,
            pool="lazy",
            kept=False,
            manual_weight=None,
            source_status="current",
            roster_filler=True,
        )
        for i in range(15)
    ]
    accounts.append(
        dict(accounts[0], tag="regular", assigned_clan_tag=None, roster_filler=False)
    )
    placements, skipped = balance_accounts(
        accounts, [clan], [a["tag"] for a in accounts], ["host"], True
    )
    assert not placements
    assert len([r for r in skipped if r["reason"] == "filler_manual_only"]) == 15
    assert {"tag": "regular", "reason": "full"} in skipped


# Reuse the existing isolated HTTP fixture setup without inheriting its tests.
from tests import test_cwl_web_roster as _fixtures

_RosterFixture = _fixtures.RosterTests
import unittest


class FillerHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = _RosterFixture.asyncSetUp
    asyncTearDown = _RosterFixture.asyncTearDown
    auth = _RosterFixture.auth
    call = _RosterFixture.call
    revision = _RosterFixture.revision
    signup = _RosterFixture.signup
    host = _RosterFixture.host

    async def test_staff_only_mark_conflict_undo_and_cross_season(self):
        body = dict(revision=await self.revision(), roster_filler=True, mark_revision=0)
        path = f"/seasons/{self.sid}/roster-filler/%23Q2Y"
        denied = await self.call("PATCH", path, self.member, json=body)
        self.assertEqual(denied.status, 403)
        response = await self.call("PATCH", path, self.owner, json=body)
        self.assertEqual(response.status, 200, await response.text())
        stale = await self.call("PATCH", path, self.owner, json=body)
        self.assertEqual(stale.status, 409)
        roster = await (
            await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        ).json()
        undone = await self.call(
            "POST",
            f"/seasons/{self.sid}/roster/undo",
            self.owner,
            json=dict(revision=roster["revision"], undo_id=roster["undo"]["id"]),
        )
        self.assertEqual(undone.status, 200, await undone.text())
        with self.app["store"].tx() as db:
            self.assertFalse(marks.mark(db, "#Q2Y")["roster_filler"])
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM roster_player_mark_audit").fetchone()[
                    0
                ],
                2,
            )

    async def test_roster_editor_scope_allowed_signup_only_denied_and_bad_inputs(self):
        import json

        headers = self.auth("777")
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO grants(user_id,granted_by,permissions) VALUES ('777','owner',?)",
                (json.dumps(["cwl_signups"]),),
            )
        path = f"/seasons/{self.sid}/roster-filler/%23Q2Y"
        body = dict(revision=await self.revision(), roster_filler=True, mark_revision=0)
        self.assertEqual(
            (await self.call("PATCH", path, headers, json=body)).status, 403
        )
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE grants SET permissions=? WHERE user_id='777'",
                (json.dumps(["cwl_roster"]),),
            )
        allowed = await self.call("PATCH", path, headers, json=body)
        self.assertEqual(allowed.status, 200, await allowed.text())
        for bad in [
            dict(body, revision=await self.revision(), roster_filler=1),
            dict(body, revision=await self.revision(), mark_revision=True),
        ]:
            self.assertEqual(
                (await self.call("PATCH", path, headers, json=bad)).status, 400
            )
        with self.app["store"].tx() as db:
            self.assertEqual(
                db.execute(
                    "SELECT actor_id FROM roster_player_mark_audit WHERE tag='#Q2Y'"
                ).fetchone()[0],
                "777",
            )

    async def test_full_15_and_30_fillers_bypass_regular_does_not(self):
        await self.signup("lazy", "#Q2Y")
        await self.signup("lazy", "#G2Y")
        await self.host("#J2Y", "lazy")
        for cap in (15, 30):
            with self.app["store"].tx() as db:
                db.execute("DELETE FROM roster_entries WHERE season_id=?", (self.sid,))
                db.execute(
                    "UPDATE lineup_rules SET capacity=? WHERE season_id=?",
                    (cap, self.sid),
                )
                for i in range(cap):
                    db.execute(
                        "INSERT OR IGNORE INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,?,?,'lazy',0,'Seat',16)",
                        (self.sid, "#SEAT" + str(i), "100"),
                    )
                    db.execute(
                        "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                        (self.sid, "#SEAT" + str(i), "#J2Y"),
                    )
            body = dict(revision=await self.revision(), assigned_clan_tag="#J2Y")
            regular = await self.call(
                "PATCH", f"/seasons/{self.sid}/roster/%23Q2Y", self.owner, json=body
            )
            self.assertEqual(regular.status, 409)
            with self.app["store"].tx() as db:
                value = marks.mark(db, "#Q2Y")
                marks.save(db, "#Q2Y", True, value["revision"], "staff")
            filler = await self.call(
                "PATCH",
                f"/seasons/{self.sid}/roster/%23Q2Y",
                self.owner,
                json=dict(body, revision=await self.revision()),
            )
            self.assertEqual(filler.status, 200, await filler.text())
            blocked = await self.call(
                "PATCH",
                f"/seasons/{self.sid}/roster/%23G2Y",
                self.owner,
                json=dict(body, revision=await self.revision()),
            )
            self.assertEqual(blocked.status, 409)
            with self.app["store"].tx() as db:
                value = marks.mark(db, "#Q2Y")
                marks.save(db, "#Q2Y", False, value["revision"], "staff")


# Prevent pytest from collecting the imported fixture class a second time.
del _RosterFixture


def test_declaration_marks_and_low_th_never_infer_filler_unknown_stays_flagged():
    from utils.declaration_extras import extras_for

    members = [
        dict(tag="#LOW", name="Low", town_hall=9),
        dict(tag="#UNKNOWN", name="Unknown", town_hall=None),
        dict(tag="#MARKED", name="Marked", town_hall=16),
        dict(tag="#ASSIGNED", name="Assigned", town_hall=8),
    ]
    assignments = [dict(tag="#ASSIGNED", assigned_clan_tag="#HOST")]
    saved = {
        "#MARKED": dict(roster_filler=True, revision=3),
        "#ASSIGNED": dict(roster_filler=True, revision=1),
    }
    extras = extras_for("#HOST", members, assignments, {}, roster_marks=saved)
    assert [r["tag"] for r in extras] == ["#UNKNOWN"]
    low = extras_for(
        "#HOST", members, assignments, {}, roster_marks=saved, category="low_th"
    )
    assert {r["tag"] for r in low} == {"#LOW", "#ASSIGNED"}
    assert not next(r for r in low if r["tag"] == "#LOW")["roster_filler"]
    assert next(r for r in low if r["tag"] == "#ASSIGNED")["roster_filler"]
    fillers = extras_for(
        "#HOST", members, assignments, {}, roster_marks=saved, category="fillers"
    )
    assert {r["tag"] for r in fillers} == {"#MARKED", "#ASSIGNED"}
    assert sum(r["assigned_here"] for r in fillers) == 1
    assert fillers[0]["roster_filler_revision"] in (1, 3)


class FillerWorkflowHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = _fixtures.RosterTests.asyncSetUp
    asyncTearDown = _fixtures.RosterTests.asyncTearDown
    auth = _fixtures.RosterTests.auth
    call = _fixtures.RosterTests.call
    revision = _fixtures.RosterTests.revision
    signup = _fixtures.RosterTests.signup
    host = _fixtures.RosterTests.host

    def seats(self, db, host, count):
        for i in range(count):
            value = host + "SEAT" + str(i)
            db.execute(
                "INSERT OR IGNORE INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,?,?,'lazy',0,'Seat',16)",
                (self.sid, value, "100"),
            )
            db.execute(
                "INSERT OR REPLACE INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                (self.sid, value, host),
            )

    async def test_mixed_bulk_publish_new_season_and_assignment_undo(self):
        for tag in ("#Q2Y", "#G2Y"):
            await self.signup("lazy", tag)
        await self.host("#J2Y", "lazy")
        with self.app["store"].tx() as db:
            self.seats(db, "#J2Y", 14)
            marks.save(db, "#Q2Y", True, 0, "staff")
        path = f"/seasons/{self.sid}/roster/assignments"
        mixed = await self.call(
            "PATCH",
            path,
            self.owner,
            json=dict(
                revision=await self.revision(),
                tags=["#Q2Y", "#G2Y"],
                assigned_clan_tag="#J2Y",
            ),
        )
        self.assertEqual(mixed.status, 200, await mixed.text())
        roster = await (
            await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        ).json()
        self.assertEqual(
            sum(a["assigned_clan_tag"] == "#J2Y" for a in roster["accounts"]), 16
        )
        undo = await self.call(
            "POST",
            f"/seasons/{self.sid}/roster/undo",
            self.owner,
            json=dict(revision=roster["revision"], undo_id=roster["undo"]["id"]),
        )
        self.assertEqual(undo.status, 200, await undo.text())
        # At full capacity a mixed request must roll back both accounts.
        with self.app["store"].tx() as db:
            self.seats(db, "#J2Y", 15)
        mixed = await self.call(
            "PATCH",
            path,
            self.owner,
            json=dict(
                revision=await self.revision(),
                tags=["#Q2Y", "#G2Y"],
                assigned_clan_tag="#J2Y",
            ),
        )
        self.assertEqual(mixed.status, 409)
        filler = await self.call(
            "PATCH",
            path,
            self.owner,
            json=dict(
                revision=await self.revision(), tags=["#Q2Y"], assigned_clan_tag="#J2Y"
            ),
        )
        self.assertEqual(filler.status, 200)
        pub = await self.call(
            "POST",
            f"/seasons/{self.sid}/publication",
            self.owner,
            json=dict(
                revision=await self.revision(),
                acknowledge_unassigned=True,
                joining_instructions="",
            ),
        )
        self.assertEqual(pub.status, 201, await pub.text())
        removed = await self.call(
            "DELETE", f"/seasons/{self.sid}/signups/%23Q2Y", self.member
        )
        self.assertEqual(removed.status, 200, await removed.text())
        arrival = await (
            await self.call(
                "GET",
                f"/seasons/{self.sid}/arrival-check?source=published&background=1",
                self.owner,
            )
        ).json()
        self.assertTrue(
            next(a for a in arrival["accounts"] if a["tag"] == "#Q2Y")["roster_filler"]
        )

        response = await self.call(
            "POST",
            "/seasons",
            self.owner,
            json={"label": "Next season", "signup_open": True},
        )
        sid = (await response.json())["id"]
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,'#Q2Y','100','lazy',0,'Carry',16)",
                (sid,),
            )
        carried = await (
            await self.call("GET", f"/seasons/{sid}/roster", self.owner)
        ).json()
        self.assertTrue(
            next(a for a in carried["accounts"] if a["tag"] == "#Q2Y")["roster_filler"]
        )

    async def test_swap_fillers_into_overfull_and_undo_without_moving_marks(self):
        for tag in ("#Q2Y", "#G2Y"):
            await self.signup("lazy", tag)
        await self.host("#J2Y", "lazy")
        await self.host("#R2Y", "lazy")
        with self.app["store"].tx() as db:
            self.seats(db, "#J2Y", 15)
            self.seats(db, "#R2Y", 15)
            for tag, host in (("#Q2Y", "#J2Y"), ("#G2Y", "#R2Y")):
                marks.save(db, tag, True, 0, "staff")
                db.execute(
                    "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                    (self.sid, tag, host),
                )
        swapped = await self.call(
            "POST",
            f"/seasons/{self.sid}/roster/swap",
            self.owner,
            json=dict(
                revision=await self.revision(), left_tag="#Q2Y", right_tag="#G2Y"
            ),
        )
        self.assertEqual(swapped.status, 200, await swapped.text())
        roster = await (
            await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
        ).json()
        undo = await self.call(
            "POST",
            f"/seasons/{self.sid}/roster/undo",
            self.owner,
            json=dict(revision=roster["revision"], undo_id=roster["undo"]["id"]),
        )
        self.assertEqual(undo.status, 200, await undo.text())
        with self.app["store"].tx() as db:
            self.assertTrue(marks.mark(db, "#Q2Y")["roster_filler"])
            self.assertEqual(
                db.execute(
                    "SELECT assigned_clan_tag FROM roster_entries WHERE season_id=? AND tag='#Q2Y'",
                    (self.sid,),
                ).fetchone()[0],
                "#J2Y",
            )


def test_additive_old_database_migration_preserves_existing_rows(tmp_path):
    path = tmp_path / "old.sqlite"
    store = Store(str(path))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(label) VALUES ('Old')")
        db.execute("DROP TABLE roster_player_mark_audit")
        db.execute("DROP TABLE roster_player_marks")
        names = [
            r[0]
            for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        ]
        before = {
            name: [tuple(r) for r in db.execute('SELECT * FROM "' + name + '"')]
            for name in names
        }
    Store(str(path))
    with store.tx() as db:
        assert before == {
            name: [tuple(r) for r in db.execute('SELECT * FROM "' + name + '"')]
            for name in names
        }
        assert not marks.marks(db)
        assert (
            db.execute("SELECT COUNT(*) FROM roster_player_mark_audit").fetchone()[0]
            == 0
        )


def test_low_th_never_creates_a_stored_roster_mark(tmp_path):
    store = Store(str(tmp_path / "low.sqlite"))
    with store.tx() as db:
        rows = marks.overlay(
            db, [dict(tag="#LOW", town_hall=9), dict(tag="#SMALL", town_hall=1)]
        )
        assert all(
            not row["roster_filler"] and row["roster_filler_revision"] == 0
            for row in rows
        )
        assert not marks.marks(db)


def test_strikes_filler_remains_an_independent_clan_scoped_setting(tmp_path):
    import asyncio
    from types import SimpleNamespace as S
    from unittest.mock import AsyncMock
    from utils.strike_store import StrikeService

    profiles = S(update_one=AsyncMock(), find_one=AsyncMock())
    strike = StrikeService(S(strike_profiles=profiles))
    result = asyncio.run(strike.set_filler(1, "#P2Y", True, 123, clan_tag="#J2Y"))
    assert result["filler"] is True and result["filler_clan_tag"] == "#J2Y"
    store = Store(str(tmp_path / "independent.sqlite"))
    with store.tx() as db:
        marks.save(db, "#P2Y", True, 0, "staff")
        marks.save(db, "#P2Y", False, 1, "staff")
    assert profiles.update_one.await_count == 1
    assert profiles.update_one.await_args.args[1]["$set"]["filler"] is True
