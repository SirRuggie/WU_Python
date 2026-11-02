"""Actual startup schema publication and lost-ack recovery on owned Mongo only."""

import json
import os
import sqlite3
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from local_mongo_fixture import fixture_uri
from cwl_web.store import Store
from utils.clan_weight_store import ClanWeightStore
from utils.cwl_dashboard_state import MongoDashboardState, DashboardDurabilityError
from test_last_war_weights import lineup

URI = fixture_uri(os.environ.get("WU_ACTIVITY_TEST_MONGO_URI"))
pytestmark = pytest.mark.skipif(not URI, reason="owned loopback Mongo not supplied")


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
            raise AutoReconnect("owned fixture lost schema/weight acknowledgement")
        return self.collection.update_one(selector, update, **kwargs)


@pytest.fixture
def owned(tmp_path):
    assert URI == "mongodb://127.0.0.1:27165"
    client = MongoClient(
        URI,
        serverSelectionTimeoutMS=2000,
        timeoutMS=10000,
        tz_aware=True,
        appName="wu-p131-owned-weights",
    )
    database = client["wu_p131_" + uuid4().hex]
    collection = LostAck(
        database.state.with_options(
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority", j=True),
        )
    )
    original = Store(tmp_path / "legacy.sqlite")
    with original.tx() as db:
        db.execute(
            "INSERT INTO clan_weight_war_lineups VALUES(?,?,?,?)",
            (
                "#R2Y",
                "2026-11-02T07:00:00+00:00",
                "2026-11-01T00:00:00Z",
                json.dumps(lineup()),
            ),
        )
        db.execute("DROP TABLE clan_weight_war_lineup_previous")
    owner = MongoDashboardState(collection)
    owner.seed(original.path)
    try:
        yield tmp_path, collection, owner
    finally:
        owner.close()
        client.drop_database(database.name)
        client.close()


def startup(owner, path):
    """Same order as cwl_web.__main__: restore, schema init, publish, then serve."""
    owner.restore(path)
    store = Store(path, durability=owner)
    with sqlite3.connect(path) as db:
        owner.publish(db)
    return store, ClanWeightStore(path, transaction_factory=store.tx)


@pytest.mark.parametrize("mode", ["before", "after"])
def test_first_schema_publication_is_before_serving_and_restart_keeps_legacy(
    owned, mode
):
    tmp_path, collection, owner = owned
    owner.restore(tmp_path / "working.sqlite")
    store = Store(tmp_path / "working.sqlite", durability=owner)
    collection.mode = mode
    with pytest.raises(DashboardDurabilityError):
        with sqlite3.connect(store.path) as db:
            owner.publish(db)
    # This is a startup failure, before web.run_app/worker startup, not a failed
    # accepted user write. Closing releases the lease just as __main__.finally.
    owner.close()
    restarted = MongoDashboardState(collection)
    try:
        store, weights = startup(restarted, tmp_path / "restart.sqlite")
        assert not restarted.poisoned
        assert len(weights.saved_lineups("#R2Y")) == 1
        assert weights.saved_lineup("#R2Y")["order"] == lineup()["order"]
        assert store.rows("SELECT * FROM clan_weight_war_lineup_previous") == []
        assert store.rows("SELECT * FROM clan_player_weights") == []
    finally:
        restarted.close()


@pytest.mark.parametrize("mode", ["before", "after"])
def test_first_rotating_capture_and_first_departed_save_recover_without_schema_poison(
    owned, mode
):
    tmp_path, collection, owner = owned
    store, weights = startup(owner, tmp_path / "working.sqlite")
    collection.mode = mode
    with pytest.raises(DashboardDurabilityError):
        weights.remember_lineup("#R2Y", lineup(3, ("#P2Y",)))
    assert owner.poisoned
    assert store.recover_durability()
    assert not owner.poisoned
    weights.remember_lineup("#R2Y", lineup(3, ("#P2Y",)))
    assert len(weights.saved_lineups("#R2Y")) == 2
    roster = {"tag": "#R2Y", "name": "Owned clan", "members": []}
    change = {"tag": "#G2Y", "weight": 150000, "storages": 5, "revision": 0}
    collection.mode = mode
    with pytest.raises(DashboardDurabilityError):
        weights.save(roster, [change], "fixture-owner", "Fixture owner")
    assert store.recover_durability()
    weights.save(roster, [change], "fixture-owner", "Fixture owner")
    assert len(store.rows("SELECT * FROM clan_player_weight_history")) == 1
    assert weights.for_members(["#G2Y"])["#G2Y"]["weight"] == 150000
    owner.close()
    restarted = MongoDashboardState(collection)
    try:
        recovered, weights = startup(restarted, tmp_path / "restored.sqlite")
        assert len(weights.saved_lineups("#R2Y")) == 2
        assert weights.for_members(["#G2Y"])["#G2Y"]["weight"] == 150000
        receipt = recovered.one("SELECT * FROM clan_player_weight_history")
        assert (
            receipt["actor_id"] == "fixture-owner"
            and receipt["source"] == "Clan weights"
        )
        with recovered.tx() as db:
            # Old artifact writes four columns in the latest table. New storage
            # deliberately retains that exact schema and the predecessor table.
            row = tuple(
                db.execute(
                    "SELECT * FROM clan_weight_war_lineups WHERE clan_tag='#R2Y'"
                ).fetchone()
            )
            db.execute(
                "INSERT OR REPLACE INTO clan_weight_war_lineups VALUES(?,?,?,?)", row
            )
        assert len(weights.saved_lineups("#R2Y")) == 2
    finally:
        restarted.close()
