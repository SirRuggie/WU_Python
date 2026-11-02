"""Real isolated HTTP/SQLite receipts, then adversarial capture tampering."""

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import unittest
import test_cwl_web_roster as fixtures
from tools.release_sqlite_state import (
    compare_sqlite,
    capture_proof,
    trusted_staff_scopes,
)
from utils import roster_player_marks


class StaffWriteProof(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.RosterTests.asyncSetUp
    asyncTearDown = fixtures.RosterTests.asyncTearDown
    auth = fixtures.RosterTests.auth
    call = fixtures.RosterTests.call
    signup = fixtures.RosterTests.signup
    revision = fixtures.RosterTests.revision
    host = fixtures.RosterTests.host
    actor = "505227988229554179"

    def capture(self):
        names = (
            "roster_publications",
            "roster_player_marks",
            "roster_player_mark_audit",
            "signups",
        )
        proof_names = (
            "roster_audit",
            "publication_accounts",
            "roster_meta",
            "seasons",
            "grants",
        )
        with self.app["store"].tx() as db:
            rows = {
                name: [dict(row) for row in db.execute("SELECT * FROM " + name)]
                for name in names + proof_names
            }
        return (
            {name: rows[name] for name in names},
            {name: rows[name] for name in proof_names},
        )

    def compare(self, before, after, *, scopes=None, denied=()):
        return compare_sqlite(
            before[0],
            after[0],
            before[1],
            after[1],
            staff_scopes=(
                scopes
                if scopes is not None
                else {self.actor: {"cwl_publish", "cwl_roster"}}
            ),
            release_actors=denied,
            started=self.started,
            ended=datetime.now(timezone.utc),
        )

    async def publish(self, instructions=""):
        response = await self.call(
            "POST",
            f"/seasons/{self.sid}/publication",
            self.owner,
            json={
                "revision": await self.revision(),
                "acknowledge_unassigned": True,
                "joining_instructions": instructions,
            },
        )
        self.assertEqual(response.status, 201)

    async def setup_publication(self):
        await self.signup("main", "#P2Y")
        self.started = datetime.now(timezone.utc)
        before = self.capture()
        await self.publish()
        return before, self.capture()

    async def test_real_publication_is_reported_and_subsequent_publication_proves_prior(
        self,
    ):
        before, after = await self.setup_publication()
        reports = self.compare(before, after)
        self.assertEqual([r["kind"] for r in reports], ["staff_publication"])
        await self.publish("Updated joining instructions")
        self.assertEqual(len(self.compare(before, self.capture())), 2)
        self.assertEqual(len(self.compare(after, self.capture())), 1)

    async def test_actual_mark_toggle_chain_and_multiple_seasons(self):
        await self.signup("main", "#P2Y")
        response = await self.call(
            "POST",
            "/seasons",
            self.owner,
            json={"label": "Next month", "signup_open": True},
        )
        self.assertEqual(response.status, 201)
        self.started = datetime.now(timezone.utc)
        before = self.capture()
        with self.app["store"].tx() as db:
            roster_player_marks.save(db, "#P2Y", True, 0, self.actor)
            roster_player_marks.save(db, "#P2Y", False, 1, self.actor)
        after = self.capture()
        self.assertEqual(
            [r["kind"] for r in self.compare(before, after)],
            ["staff_mark", "staff_mark"],
        )
        broken = deepcopy(after)
        broken[0]["roster_player_mark_audit"].pop(0)
        with self.assertRaises(ValueError):
            self.compare(before, broken)

    async def test_mixed_publication_and_mark_exact_meta_increments(self):
        before, _ = await self.setup_publication()
        with self.app["store"].tx() as db:
            roster_player_marks.save(db, "#P2Y", True, 0, self.actor)
        await self.publish("After marking")
        after = self.capture()
        self.assertEqual(len(self.compare(before, after)), 3)
        after[1]["roster_meta"][0]["revision"] += 1
        with self.assertRaisesRegex(ValueError, "revision"):
            self.compare(before, after)

    async def test_same_capture_noop_and_no_permission_needed_for_unchanged_data(self):
        self.started = datetime.now(timezone.utc)
        before = self.capture()
        self.assertEqual(self.compare(before, before, scopes={}), [])

    async def test_publication_proof_rejects_tampering(self):
        before, after = await self.setup_publication()
        cases = {
            "missing audit": lambda a: a[1]["roster_audit"].pop(),
            "wrong actor": lambda a: a[1]["roster_audit"][-1].update(
                actor_id="untrusted"
            ),
            "wrong before": lambda a: a[1]["roster_audit"][-1].update(before_json="{}"),
            "wrong after": lambda a: a[1]["roster_audit"][-1].update(after_json="{}"),
            "wrong action": lambda a: a[1]["roster_audit"][-1].update(
                action="roster_unpublish"
            ),
            "old audit": lambda a: a[1]["roster_audit"][-1].update(
                created_at="2001-01-01"
            ),
            "missing snapshot": lambda a: a[1]["publication_accounts"].clear(),
            "changed count": lambda a: a[0]["roster_publications"][-1].update(
                assigned_count=2
            ),
            "withdrawn new": lambda a: a[0]["roster_publications"][-1].update(
                withdrawn_at="now"
            ),
            "changed signup": lambda a: a[0]["signups"][0].update(
                player_name="tampered"
            ),
            "duplicate audit": lambda a: a[1]["roster_audit"].append(
                a[1]["roster_audit"][-1]
            ),
            "unrelated audit": lambda a: a[1]["roster_audit"].append(
                dict(a[1]["roster_audit"][-1], id=999, action="bulk_assign")
            ),
        }
        for label, tamper in cases.items():
            with self.subTest(label=label):
                changed = deepcopy(after)
                tamper(changed)
                with self.assertRaises((ValueError, TypeError)):
                    self.compare(before, changed)
        for scopes, denied in (
            ({}, ()),
            ({self.actor: {"cwl_roster"}}, ()),
            ({self.actor: {"cwl_publish"}}, (self.actor,)),
        ):
            with self.assertRaisesRegex(ValueError, "actor"):
                self.compare(before, after, scopes=scopes, denied=denied)

    async def test_existing_publication_snapshot_audit_removal_or_change_rejected(self):
        _, baseline = await self.setup_publication()
        await self.publish("Second")
        after = self.capture()
        for table, location in (
            ("roster_publications", 0),
            ("publication_accounts", 1),
            ("roster_audit", 1),
        ):
            for removal in (True, False):
                with self.subTest(table=table, removal=removal):
                    changed = deepcopy(after)
                    if removal:
                        changed[location][table].pop(0)
                    else:
                        changed[location][table][0]["unexpected"] = "modified"
                    with self.assertRaises(ValueError):
                        self.compare(baseline, changed)

    async def test_mark_requires_exact_actor_revision_value_and_no_removals(self):
        self.started = datetime.now(timezone.utc)
        before = self.capture()
        with self.app["store"].tx() as db:
            roster_player_marks.save(db, "#P2Y", True, 0, self.actor)
        baseline = self.capture()
        with self.app["store"].tx() as db:
            roster_player_marks.save(db, "#P2Y", False, 1, self.actor)
        after = self.capture()
        cases = [
            lambda a: a[0]["roster_player_marks"].clear(),
            lambda a: a[0]["roster_player_mark_audit"].pop(),
            lambda a: a[0]["roster_player_marks"][0].update(updated_by="release"),
            lambda a: a[0]["roster_player_mark_audit"][-1].update(revision=7),
            lambda a: a[0]["roster_player_mark_audit"][-1].update(before_value=0),
            lambda a: a[0]["roster_player_mark_audit"][-1].update(after_value=1),
            lambda a: a[0]["roster_player_marks"][0].update(updated_at="2001-01-01"),
        ]
        for tamper in cases:
            changed = deepcopy(after)
            tamper(changed)
            with self.assertRaises(ValueError):
                self.compare(baseline, changed)
        with self.assertRaisesRegex(ValueError, "actor"):
            self.compare(before, baseline, denied=(self.actor,))

    async def test_invalid_or_missing_capture_and_time_fail_closed(self):
        before, after = await self.setup_publication()
        for proof in ({}, {"roster_audit": []}):
            with self.assertRaises(ValueError):
                compare_sqlite(
                    before[0],
                    after[0],
                    proof,
                    after[1],
                    staff_scopes={},
                    release_actors=(),
                    started=self.started,
                    ended=datetime.now(timezone.utc),
                )
        with self.assertRaisesRegex(ValueError, "Reversed"):
            compare_sqlite(
                before[0],
                after[0],
                before[1],
                after[1],
                staff_scopes={},
                release_actors=(),
                started=self.started + timedelta(days=1),
                ended=self.started,
            )

    async def test_actor_manifest_cannot_grant_authority_and_grant_changes_rejected(
        self,
    ):
        before, after = await self.setup_publication()
        forged = deepcopy(after)
        pub = forged[0]["roster_publications"][-1]
        audit = forged[1]["roster_audit"][-1]
        pub["published_by"] = audit["actor_id"] = "untrusted"
        import json

        meta = json.loads(audit["after_json"])
        meta["published_by"] = "untrusted"
        audit["after_json"] = json.dumps(meta)
        with self.assertRaisesRegex(ValueError, "actor"):
            self.compare(before, forged, scopes={"untrusted": {"cwl_publish"}})
        changed = deepcopy(after)
        changed[1]["grants"].append(
            {"user_id": "untrusted", "permissions": '["cwl_publish"]'}
        )
        with self.assertRaisesRegex(ValueError, "grants"):
            self.compare(before, changed)
        with self.app["store"].tx() as db:
            proof = capture_proof(db)
        self.assertEqual(proof, after[1])
        self.assertIn("cwl_publish", trusted_staff_scopes(proof)[self.actor])

    async def test_coordinator_capture_seam_is_read_only_and_checks_own_actor(self):
        import sqlite3
        from tools.release_sqlite_state import capture, compare_captures

        await self.signup("main", "#P2Y")

        def observed():
            # Actual query-only database connection, never Store.tx or a writer.
            path = self.app["store"].path
            with sqlite3.connect("file:" + str(path) + "?mode=ro", uri=True) as db:
                db.row_factory = sqlite3.Row
                db.execute("BEGIN")
                return capture(
                    db,
                    lambda c: {
                        name: [dict(row) for row in c.execute("SELECT * FROM " + name)]
                        for name in (
                            "roster_publications",
                            "roster_player_marks",
                            "roster_player_mark_audit",
                            "signups",
                        )
                    },
                )

        before = observed()
        await self.publish()
        after = observed()
        self.assertEqual(len(compare_captures(before, after, release_actors=())), 1)
        with self.assertRaisesRegex(ValueError, "actor"):
            compare_captures(before, after, release_actors=(self.actor,))
        with self.assertRaisesRegex(ValueError, "Independent"):
            compare_captures(before, before, release_actors=())
        with self.assertRaisesRegex(ValueError, "order"):
            compare_captures(after, before, release_actors=())
