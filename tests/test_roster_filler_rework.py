import asyncio
import logging
import unittest
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from cwl_web.store import Store
from cwl_web.app import _auto_plan, _roster_rows, _rule_rows
from utils import roster_player_marks as marks
from utils.cwl_balance import balance_accounts
import test_roster_player_marks as _fixtures


class FillerReworkHTTP(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = _fixtures.FillerWorkflowHTTP.asyncSetUp
    asyncTearDown = _fixtures.FillerWorkflowHTTP.asyncTearDown
    auth = _fixtures.FillerWorkflowHTTP.auth
    call = _fixtures.FillerWorkflowHTTP.call
    revision = _fixtures.FillerWorkflowHTTP.revision
    signup = _fixtures.FillerWorkflowHTTP.signup
    host = _fixtures.FillerWorkflowHTTP.host
    seats = _fixtures.FillerWorkflowHTTP.seats

    async def test_archived_mark_423_and_stale_season_with_fresh_mark_revision(self):
        path = f"/seasons/{self.sid}/roster-filler/%23Q2Y"
        response = await self.call(
            "PATCH",
            path,
            self.owner,
            json=dict(
                revision=await self.revision(), mark_revision=0, roster_filler=True
            ),
        )
        saved = await response.json()
        self.assertEqual(response.status, 200)
        stale = await self.call(
            "PATCH",
            path,
            self.owner,
            json=dict(
                revision=saved["revision"] - 1,
                mark_revision=saved["mark_revision"],
                roster_filler=False,
            ),
        )
        self.assertEqual(stale.status, 409)
        with self.app["store"].tx() as db:
            db.execute("UPDATE seasons SET status='archived' WHERE id=?", (self.sid,))
        archived = await self.call(
            "PATCH",
            path,
            self.owner,
            json=dict(
                revision=saved["revision"],
                mark_revision=saved["mark_revision"],
                roster_filler=False,
            ),
        )
        self.assertEqual(archived.status, 423)
        with self.app["store"].tx() as db:
            self.assertTrue(marks.mark(db, "#Q2Y")["roster_filler"])
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM roster_player_mark_audit").fetchone()[
                    0
                ],
                1,
            )

    async def test_filler_overflow_allows_seat_neutral_swaps_but_regular_overflow_blocks_regular(
        self,
    ):
        for value in ("#P2Y", "#Q2Y", "#G2Y"):
            await self.signup("lazy", value)
        await self.host("#J2Y", "lazy")
        await self.host("#R2Y", "lazy")
        with self.app["store"].tx() as db:
            self.seats(db, "#J2Y", 14)
            self.seats(db, "#R2Y", 14)
            marks.save(db, "#Q2Y", True, 0, "staff")
            for value, host in (("#P2Y", "#J2Y"), ("#Q2Y", "#J2Y"), ("#G2Y", "#R2Y")):
                db.execute(
                    "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                    (self.sid, value, host),
                )

        async def swap(left, right):
            return await self.call(
                "POST",
                f"/seasons/{self.sid}/roster/swap",
                self.owner,
                json=dict(
                    revision=await self.revision(), left_tag=left, right_tag=right
                ),
            )

        regular = await swap("#P2Y", "#G2Y")
        self.assertEqual(regular.status, 200, await regular.text())
        filler = await swap("#Q2Y", "#P2Y")
        self.assertEqual(filler.status, 200, await filler.text())
        with self.app["store"].tx() as db:
            self.assertEqual(marks.assigned_counts(db, self.sid, "#J2Y"), (16, 0))
            rows = _rule_rows(db, self.sid)
            self.assertEqual(
                next(c for c in rows if c["tag"] == "#R2Y")["assigned_filler_count"], 1
            )
            db.execute(
                "DELETE FROM roster_entries WHERE season_id=? AND tag=?",
                (self.sid, "#R2YSEAT0"),
            )
            db.execute(
                "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (?,'#V2Y','100','lazy',0,'Regular',16)",
                (self.sid,),
            )
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,'#V2Y','#R2Y')",
                (self.sid,),
            )
        denied = await swap("#P2Y", "#V2Y")
        self.assertEqual(denied.status, 409)

    async def test_swap_and_move_undo_restore_filler_overflow_exactly(self):
        for tag in ("#P2Y", "#Q2Y", "#G2Y"):
            await self.signup("lazy", tag)
        await self.host("#J2Y", "lazy")
        await self.host("#R2Y", "lazy")
        with self.app["store"].tx() as db:
            self.seats(db, "#J2Y", 14)
            marks.save(db, "#Q2Y", True, 0, "staff")
            for tag, host in (("#P2Y", "#J2Y"), ("#Q2Y", "#J2Y"), ("#G2Y", "#R2Y")):
                db.execute(
                    "INSERT INTO roster_entries(season_id,tag,assigned_clan_tag) VALUES (?,?,?)",
                    (self.sid, tag, host),
                )

        def placements():
            with self.app["store"].tx() as db:
                return [
                    tuple(r)
                    for r in db.execute(
                        "SELECT tag,assigned_clan_tag,kept FROM roster_entries WHERE season_id=? ORDER BY tag",
                        (self.sid,),
                    )
                ]

        for mode in ("swap", "move"):
            before = placements()
            if mode == "swap":
                response = await self.call(
                    "POST",
                    f"/seasons/{self.sid}/roster/swap",
                    self.owner,
                    json=dict(
                        revision=await self.revision(),
                        left_tag="#P2Y",
                        right_tag="#G2Y",
                    ),
                )
            else:
                response = await self.call(
                    "PATCH",
                    f"/seasons/{self.sid}/roster/%23P2Y",
                    self.owner,
                    json=dict(revision=await self.revision(), assigned_clan_tag="#R2Y"),
                )
            self.assertEqual(response.status, 200, await response.text())
            roster = await self.call("GET", f"/seasons/{self.sid}/roster", self.owner)
            receipt = (await roster.json())["undo"]
            undone = await self.call(
                "POST",
                f"/seasons/{self.sid}/roster/undo",
                self.owner,
                json=dict(revision=await self.revision(), undo_id=receipt["id"]),
            )
            self.assertEqual(undone.status, 200, await undone.text())
            self.assertEqual(placements(), before)


def test_auto_and_balance_include_immovable_filler_weight(tmp_path):
    store = Store(str(tmp_path / "weights.sqlite"))
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES (1,'one')")
        for host in ("#J2Y", "#R2Y"):
            db.execute(
                "INSERT INTO clans(tag,name,pool) VALUES (?, ?, ?)",
                (host, host, "lazy"),
            )
            db.execute("INSERT INTO lineup(season_id,tag) VALUES (1,?)", (host,))
            db.execute(
                "INSERT INTO lineup_rules(season_id,tag,pool,capacity) VALUES (1,?,'lazy',15)",
                (host,),
            )
        for tag, weight, host in (
            ("#P2Y", 170000, "#J2Y"),
            ("#Q2Y", 100000, "#J2Y"),
            ("#G2Y", 120000, "#R2Y"),
            ("#V2Y", 110000, "#R2Y"),
            ("#L2Y", 90000, None),
        ):
            db.execute(
                "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES (1,?,'100','lazy',0,?,16)",
                (tag, tag),
            )
            db.execute(
                "INSERT INTO roster_entries(season_id,tag,manual_weight,assigned_clan_tag) VALUES (1,?,?,?)",
                (tag, weight, host),
            )
        marks.save(db, "#P2Y", True, 0, "staff")
        assert _auto_plan(db, 1)[0] == [{"tag": "#L2Y", "assigned_clan_tag": "#R2Y"}]
        plan, _ = balance_accounts(
            _roster_rows(db, 1), _rule_rows(db, 1), ["#L2Y"], ["#J2Y", "#R2Y"]
        )
        assert plan == [{"tag": "#L2Y", "assigned_clan_tag": "#R2Y"}]


def test_profile_scheduling_timing_stages_do_not_change_materialization(caplog):
    from utils.member_profile_runs import ProfileRuns

    async def run():
        parent = dict(
            _id="run",
            state="queued",
            cursor=0,
            next_at=0,
            items=[dict(revision=1)],
            user_id="staff",
            guild_id=1,
        )
        collection = S(
            find_one=AsyncMock(side_effect=[parent, None]), insert_one=AsyncMock()
        )
        store = ProfileRuns(S(bot_config=collection))
        store.prune_throttled = AsyncMock()
        with caplog.at_level(logging.INFO):
            await store.advance(now=100)
        collection.insert_one.assert_awaited_once()
        assert collection.insert_one.await_args.args[0]["created_at"] == 100
        assert all(
            f"stage={stage}" in caplog.text
            for stage in (
                "profile_parent",
                "profile_child_lookup",
                "profile_child_insert",
            )
        )
        assert "prune_ms=" in caplog.text and "next_in_ms=" in caplog.text

    asyncio.run(run())
