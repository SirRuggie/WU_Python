"""Per-clan waiting and proof-based final capture; fake providers only."""

from datetime import datetime, timezone
from unittest.mock import patch
from cwl_web import participation_sync as sync
from cwl_web.providers import ProviderUnavailable
from test_participation_missing_season import CaptureTests, group
from test_participation_waiting import November


class EvidenceTests(CaptureTests):
    async def test_real_war_mixed_ended_waits_per_clan(self):
        await self.check_mixed_wait("ended")

    async def test_real_war_mixed_404_waits_per_clan(self):
        await self.check_mixed_wait("404")

    async def test_real_war_mixed_older_waits_per_clan(self):
        await self.check_mixed_wait("older")

    async def check_mixed_wait(self, kind):
        await self.prepare()
        self.set_group([["#Y2Y"]], state="PREPARATION", season=None)
        self.set_war("#Y2Y", state="PREPARATION")
        await self.signup("main", "#Q2Y")
        response = await self.call("POST", "/clans", self.owner, json={"tag": "#J2Y"})
        assert response.status == 201
        response = await self.call(
            "PATCH",
            f"/seasons/{self.sid}/roster/%23Q2Y",
            self.owner,
            json={
                "revision": await self.revision(),
                "assigned_clan_tag": "#J2Y",
                "kept": True,
            },
        )
        assert response.status == 200
        other = group("ENDED", None if kind == "ended" else "2026-10")
        other["clans"] = [{"tag": "#J2Y", "members": [{"tag": "#Q2Y"}]}]
        self.league.groups["#J2Y"] = other
        original = self.providers.league_group

        async def fetch(tag):
            if kind == "404" and tag == "#J2Y":
                error = ProviderUnavailable("fixture404")
                error.status_code = 404
                raise error
            return await original(tag)

        self.providers.league_group = fetch
        with self.app["store"].tx() as db:
            db.execute(
                "UPDATE participation_sync_settings SET last_success_at='2026-11-01T10:00:00+00:00' WHERE season_id=?",
                (self.sid,),
            )
        for _ in range(2):
            _, data = await self.result()
            row = next(r for r in data["accounts"] if r["tag"] == "#Q2Y")
            assert (
                data["sync"]["status"] == "partial" and data["sync"]["warning"] is None
            )
            assert row["source_status"] == "waiting" and row["source_attacks"] is None
            assert row["source_warning"] == "November CWL has not started in Clash yet"
            assert data["sync"]["last_success_at"] == data["sync"]["last_checked_at"]
            assert data["sync"]["last_success_at"] != "2026-11-01T10:00:00+00:00"
        with self.app["store"].tx() as db:
            db.execute(
                "INSERT INTO participation_group_observations VALUES(?,?,'#J2Y',?,'WAR','[[\"#Y2Q\"]]','[]','2026-11-01T00:00:00Z')",
                (self.sid, "2026-11", "2026-11"),
            )
        _, data = await self.result()
        row = next(r for r in data["accounts"] if r["tag"] == "#Q2Y")
        assert data["sync"]["warning"] and row["source_status"] != "waiting"

    async def test_exact_tags_allow_ended_missing_month_to_finish_and_qualify_for_bonus(
        self,
    ):
        await self.prepare()
        tags = [f"#Y2{x}" for x in "YQGJLPV"]
        self.set_group([[t] for t in tags], state="WAR", season="2026-11")
        for t in tags:
            self.set_war(t, state="ENDED")
        row, _ = await self.result()
        assert not row["source_complete"]
        self.set_group([[t] for t in tags], state="ENDED", season=None)
        row, data = await self.result()
        assert (
            row["source_attacks"] == 7
            and row["source_stars"] == 21
            and row["source_complete"]
        )
        # Existing immutable-war caching keeps its original freshness semantics.
        assert data["sync"]["status"] in {"complete", "stale"}
        from utils.cwl_bonus_raffle import eligibility

        assert (
            eligibility(dict(row, in_current_roster=True, roster_changed=False), 4)
            is None
        )

        class December(datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2026, 12, 1, tzinfo=timezone.utc)

        with patch.object(sync, "datetime", December):
            response = await self.sync()
            assert response.status == 200
            row, data = await self.account()
        assert row["source_complete"] and row["source_attacks"] == 7

    async def test_nonexact_overlap_does_not_finalize_stored_group(self):
        await self.prepare()
        self.set_group([["#Y2Y"], ["#Y2Q"]], state="WAR", season="2026-11")
        self.set_war("#Y2Y")
        self.set_war("#Y2Q")
        await self.result()
        self.set_group([["#Y2Y"]], state="ENDED", season=None)
        row, data = await self.result()
        assert not row["source_complete"] and data["sync"]["warning"]

    async def test_mismatching_war_does_not_store_inferred_group(self):
        await self.prepare()
        self.set_group([["#Y2Y"]], state="PREPARATION", season=None)
        self.set_war("#Y2Y")
        self.league.wars["#Y2Y"]["season"] = "2026-10"
        await self.result()
        with self.app["store"].tx() as db:
            assert (
                db.execute(
                    "SELECT count(*) FROM participation_group_observations WHERE season_id=? AND cycle=?",
                    (self.sid, "2026-11"),
                ).fetchone()[0]
                == 0
            )

    async def test_upcoming_missing_month_groups_wait_without_guessing(self):
        await self.prepare("2026-12")
        for state in ("PREPARATION", "WAR", "ENDED"):
            self.set_group([["#Y2Y"]], state=state, season=None)
            row, data = await self.result()
            assert data["sync"]["status"] == "waiting"
            assert row["source_attacks"] is None and row["source_status"] == "waiting"
            assert self.league.war_calls == []


def test_clan_evidence_is_keyed_by_season_cycle_and_clan():
    import sqlite3

    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    try:
        db.execute(
            "CREATE TABLE participation_group_observations(season_id,cycle,clan_tag,war_tags_json)"
        )
        db.executemany(
            "INSERT INTO participation_group_observations VALUES(?,?,?,?)",
            [
                (2, "2026-11", "#C2Y", '[["#Y2Y"]]'),
                (1, "2026-10", "#C2Y", '[["#Y2Y"]]'),
                (1, "2026-11", "#J2Y", '[["#Y2Y"]]'),
            ],
        )
        assert not sync._clan_month_evidence(db, 1, "2026-11", "#C2Y")
        db.execute(
            "INSERT INTO participation_group_observations VALUES(?,?,?,?)",
            (1, "2026-11", "#C2Y", '[["#Y2Q"]]'),
        )
        assert sync._clan_month_evidence(db, 1, "2026-11", "#C2Y")
    finally:
        db.close()
