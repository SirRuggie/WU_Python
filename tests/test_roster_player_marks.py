"""Season-independent staff marks never infer or modify Strikes filler rules."""

import sqlite3
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
