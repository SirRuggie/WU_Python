"""Explicit owned-loopback database only; all external delivery is absent."""

from copy import deepcopy
import os
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

from cwl_web.store import Store
from utils.cwl_dashboard_state import MongoDashboardState, DashboardDurabilityError

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(not URI, reason="owned real Mongo fixture not provided")


class UncertainCollection:
    def __init__(self, collection):
        self.collection = collection
        self.mode = None
        self.delayed = None

    def __getattr__(self, name):
        return getattr(self.collection, name)

    def update_one(self, selector, update, **kwargs):
        if (
            self.mode == "recovery_after"
            and "write_token" in update.get("$set", {})
            and "payload" not in update.get("$set", {})
        ):
            self.mode = None
            self.collection.update_one(selector, update, **kwargs)
            raise AutoReconnect(
                "injected lost recovery acknowledgement on owned fixture"
            )
        if self.mode and "payload" in update.get("$set", {}):
            mode, self.mode = self.mode, None
            if mode == "late":
                self.delayed = (deepcopy(selector), deepcopy(update))
            elif mode == "after":
                self.collection.update_one(selector, update, **kwargs)
            raise AutoReconnect("injected uncertain response on owned fixture")
        return self.collection.update_one(selector, update, **kwargs)


@pytest.fixture
def real_store(tmp_path):
    assert URI == "mongodb://127.0.0.1:27154"
    client = MongoClient(
        URI,
        tz_aware=True,
        serverSelectionTimeoutMS=2000,
        timeoutMS=10000,
        appName="wu-p97-owned-recovery",
        maxPoolSize=10,
    )
    db = client["wu_p97_recovery_" + uuid4().hex]
    initial = Store(tmp_path / "seed.sqlite")
    with initial.tx() as sql:
        sql.execute("INSERT INTO seasons(id,label) VALUES(1,'Owned fixture')")
    collection = UncertainCollection(
        db.state.with_options(
            read_concern=ReadConcern("majority"),
            write_concern=WriteConcern(w="majority", j=True),
        )
    )
    state = MongoDashboardState(collection)
    try:
        state.seed(initial.path)
        state.restore(tmp_path / "working.sqlite")
        store = Store(tmp_path / "working.sqlite", durability=state)
        yield state, store, collection
    finally:
        state.close()
        client.drop_database(db.name)
        client.close()


@pytest.mark.parametrize("mode", ["before", "after", "late"])
def test_real_majority_recovery_without_restart_or_replay(real_store, mode):
    state, store, collection = real_store
    with store.tx() as sql:
        sql.execute(
            "INSERT INTO announcement_deliveries(season_id,publication_version,pool,channel_id,nonce,content,status,requested_by,requested_at) VALUES(1,1,'main','fake-channel','fake-nonce','fixture','sending','fixture','2026-11-01')"
        )
    collection.mode = mode
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as sql:
            sql.execute(
                "UPDATE announcement_deliveries SET status='sent',message_id='fixture-accepted'"
            )
    assert state.poisoned
    assert store.recover_durability()
    expected = "sent" if mode == "after" else "sending"
    assert store.one("SELECT status FROM announcement_deliveries")["status"] == expected
    if collection.delayed:
        assert collection.collection.update_one(*collection.delayed).matched_count == 0
    assert store.one("SELECT COUNT(*) n FROM announcement_deliveries")["n"] == 1
    with store.tx() as sql:
        sql.execute("UPDATE seasons SET label='Recovered safely'")
    assert store.one("SELECT label FROM seasons")["label"] == "Recovered safely"


@pytest.mark.parametrize("change", ["owner", "revision"])
def test_real_newer_or_foreign_head_never_overwritten(real_store, change):
    state, store, collection = real_store
    state.poisoned = True
    update = (
        {"$set": {"owner": "different-owned-fixture-writer"}}
        if change == "owner"
        else {"$inc": {"revision": 1}}
    )
    collection.collection.update_one({"_id": state.key}, update)
    before = collection.find_one({"_id": state.key})
    with pytest.raises(DashboardDurabilityError):
        store.recover_durability()
    assert collection.find_one({"_id": state.key}) == before
    assert state.poisoned


@pytest.mark.parametrize("original", ["before", "after"])
def test_real_recovery_acknowledgement_lost_then_checked_without_restart(
    real_store, original
):
    state, store, collection = real_store
    collection.mode = original
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as sql:
            sql.execute("UPDATE seasons SET label='Accepted uncertain save'")
    collection.mode = "recovery_after"
    with pytest.raises(DashboardDurabilityError):
        store.recover_durability()
    assert state.poisoned
    assert store.recover_durability()
    expected = "Accepted uncertain save" if original == "after" else "Owned fixture"
    assert store.one("SELECT label FROM seasons")["label"] == expected
