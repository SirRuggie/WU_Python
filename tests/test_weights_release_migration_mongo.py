"""Run against the accepted candidate Store on owned loopback Mongo only."""

import os
import sqlite3
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from cwl_web.store import Store
from utils.cwl_dashboard_state import (
    MongoDashboardState,
    DashboardDurabilityError,
    decode,
)
from tools.weights_release_migration import capture, compare, previous_rows

URI = os.environ.get("WU_WEIGHTS_GUARD_MONGO_URI")
pytestmark = pytest.mark.skipif(not URI, reason="owned Mongo rehearsal not requested")


class LostAck:
    def __init__(self, collection):
        self.collection = collection
        self.mode = None

    def __getattr__(self, name):
        return getattr(self.collection, name)

    def update_one(self, selector, update, **kwargs):
        if self.mode and "payload" in update.get("$set", {}):
            mode, self.mode = self.mode, None
            if mode == "after":
                self.collection.update_one(selector, update, **kwargs)
            raise AutoReconnect("fictional schema publication acknowledgement lost")
        return self.collection.update_one(selector, update, **kwargs)


@pytest.mark.parametrize("lost_ack", [None, "before", "after"])
def test_public_restore_store_publish_decode_and_rollback_compatibility(
    tmp_path, lost_ack
):
    assert URI == "mongodb://127.0.0.1:27165"
    client = MongoClient(URI, serverSelectionTimeoutMS=2000, timeoutMS=10000)
    database = client["wu_weights_guard_" + uuid4().hex]
    collection = LostAck(
        database.state.with_options(
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority", j=True),
        )
    )
    owner = MongoDashboardState(collection)
    try:
        legacy = Store(tmp_path / "fictional-legacy.sqlite")
        with legacy.tx() as db:
            # The candidate must have the actual migration, rather than a test's DDL.
            assert previous_rows(db) == []
            assert db.execute(
                "SELECT name FROM sqlite_master WHERE name='clan_weight_war_lineup_previous'"
            ).fetchone()
            db.execute(
                "INSERT INTO clan_weight_war_lineups VALUES(?,?,?,?)",
                (
                    "#R2Y",
                    "2026-11-01T00:00:00Z",
                    "fictional-capture",
                    '{"order":["#P2Y"]}',
                ),
            )
            # Remove only the empty candidate table in this fictional old image.
            db.execute("DROP TABLE clan_weight_war_lineup_previous")
        owner.seed(legacy.path)
        working = tmp_path / "working.sqlite"
        owner.restore(working)
        with sqlite3.connect(working) as db:
            before = capture(db)
        candidate = Store(working, durability=owner)
        collection.mode = lost_ack
        if lost_ack:
            with pytest.raises(DashboardDurabilityError):
                with sqlite3.connect(working) as db:
                    owner.publish(db)
            owner.close()  # __main__.finally: failure never reaches serving/workers.
            owner = MongoDashboardState(collection)
            owner.restore(working)
            candidate = Store(working, durability=owner)
        with sqlite3.connect(candidate.path) as db:
            owner.publish(db)  # Actual public __main__ entrypoint before web.run_app.
        head = collection.find_one({"_id": "dashboard"})
        # Obtain the public canonical document without assuming its id constant.
        if not head:
            head = collection.find_one({"payload": {"$exists": True}})
        canonical = decode(head)
        try:
            proof = compare(before, capture(canonical))
            assert proof["created_empty_predecessor"] is True
            assert previous_rows(canonical) == []
        finally:
            canonical.close()
        owner.close()
        owner = MongoDashboardState(collection)
        restored = tmp_path / "restart.sqlite"
        owner.restore(restored)
        with sqlite3.connect(restored) as db:
            assert compare(before, capture(db))["created_empty_predecessor"]
            # Old artifact's positional write still has exactly four columns.
            old_row = tuple(
                db.execute("SELECT * FROM clan_weight_war_lineups").fetchone()
            )
            db.execute(
                "INSERT OR REPLACE INTO clan_weight_war_lineups VALUES(?,?,?,?)",
                old_row,
            )
            assert previous_rows(db) == []
            assert compare(before, capture(db))["created_empty_predecessor"]
    finally:
        owner.close()
        client.drop_database(database.name)
        client.close()
