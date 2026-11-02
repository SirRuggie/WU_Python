"""Late acknowledgements cannot overwrite recovered notification receipts."""

from copy import deepcopy
import sqlite3
import pytest
from utils.cwl_dashboard_state import (
    DashboardDurabilityError,
    MongoDashboardState,
    decode,
)
from test_cwl_dashboard_state import Collection


class RecoveryCollection(Collection):
    def find_one(self, query):
        return deepcopy(self.doc) if self.matches(query) else None


@pytest.fixture
def owner(tmp_path):
    path = tmp_path / "source.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript(
            "CREATE TABLE seasons(id INTEGER PRIMARY KEY); CREATE TABLE signups(id INTEGER); CREATE TABLE roster_entries(id INTEGER); CREATE TABLE deliveries(id INTEGER PRIMARY KEY,state TEXT); INSERT INTO deliveries VALUES(1,'sending');"
        )
    collection = RecoveryCollection()
    state = MongoDashboardState(collection)
    state.seed(path)
    state.acquire()
    return state, collection, path


def pending_save(state, path):
    with sqlite3.connect(path) as db:
        db.execute("UPDATE deliveries SET state='done'")
        state.publish(db)


@pytest.mark.parametrize("failure,expected", [("before", "sending"), ("after", "done")])
def test_recovery_uses_only_majority_known_receipt(owner, failure, expected):
    state, collection, path = owner
    collection.fail = failure
    with pytest.raises(DashboardDurabilityError):
        pending_save(state, path)
    collection.fail = None
    image = state.recovery_image()
    assert state.poisoned
    with decode(image) as recovered:
        assert (
            recovered.execute("SELECT state FROM deliveries").fetchone()[0] == expected
        )
    state.confirm_recovery(image)
    state.finish_recovery(image)
    assert not state.poisoned


def test_recovery_fences_original_write_that_arrives_late(owner):
    state, collection, path = owner
    original_update = collection.update_one
    delayed = []

    def delay(query, update):
        delayed.append((deepcopy(query), deepcopy(update)))
        raise TimeoutError("response budget elapsed before server processed CAS")

    collection.update_one = delay
    with pytest.raises(DashboardDurabilityError):
        pending_save(state, path)
    collection.update_one = original_update
    image = state.recovery_image()
    assert original_update(*delayed[0]).matched_count == 0
    assert collection.doc["revision"] == image["revision"]
    with decode(collection.doc) as db:
        assert db.execute("SELECT state FROM deliveries").fetchone()[0] == "sending"


def test_recovery_ack_lost_remains_fenced_then_recognizes_own_receipt(owner):
    state, collection, path = owner
    collection.fail = "before"
    with pytest.raises(DashboardDurabilityError):
        pending_save(state, path)
    collection.fail = "after"
    with pytest.raises(DashboardDurabilityError):
        state.recovery_image()
    assert state.poisoned
    confirmed_revision = collection.doc["revision"]
    collection.fail = None
    image = state.recovery_image()
    assert image["revision"] == confirmed_revision + 1
    state.confirm_recovery(image)
    state.finish_recovery(image)
    assert not state.poisoned


@pytest.mark.parametrize(
    "change", ["foreign_owner", "unknown_revision", "corrupt_image"]
)
def test_unrecognized_or_corrupt_head_never_overwritten(owner, change):
    state, collection, path = owner
    state.poisoned = True
    if change == "foreign_owner":
        collection.doc["owner"] = "another-process"
    elif change == "unknown_revision":
        collection.doc["revision"] += 8
    else:
        collection.doc["payload"] = b"corrupt"
    before = deepcopy(collection.doc)
    with pytest.raises(DashboardDurabilityError):
        state.recovery_image()
    assert collection.doc == before
    assert state.poisoned


def test_original_cas_winning_between_read_and_fence_is_not_lost(owner):
    state, collection, path = owner
    original_update = collection.update_one
    delayed = []

    def delay(query, update):
        delayed.append((deepcopy(query), deepcopy(update)))
        raise TimeoutError("late CAS")

    collection.update_one = delay
    with pytest.raises(DashboardDurabilityError):
        pending_save(state, path)
    raced = False

    def race(query, update):
        nonlocal raced
        if not raced:
            raced = True
            assert original_update(*delayed[0]).matched_count == 1
        return original_update(query, update)

    collection.update_one = race
    with pytest.raises(DashboardDurabilityError):
        state.recovery_image()
    image = state.recovery_image()
    with decode(image) as db:
        assert db.execute("SELECT state FROM deliveries").fetchone()[0] == "done"


from test_cwl_dashboard_state import setup as durable_setup


@pytest.mark.parametrize("failure,expected", [("before", 149000), ("after", 152000)])
def test_running_store_recovers_without_restart_or_repeating_delivery(
    durable_setup, failure, expected
):
    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    with store.tx() as db:
        db.execute(
            "INSERT INTO announcement_deliveries(season_id,publication_version,pool,channel_id,nonce,content,status,requested_by,requested_at) VALUES(1,1,'main','channel','nonce','hello','sending','staff','2026-11-01')"
        )
    collection.fail = failure
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as db:
            db.execute("UPDATE roster_entries SET manual_weight=152000")
            db.execute(
                "UPDATE announcement_deliveries SET status='sent',message_id='accepted'"
            )
    collection.fail = None
    assert store.recover_durability()
    assert not state.poisoned
    assert (
        store.one("SELECT manual_weight FROM roster_entries")["manual_weight"]
        == expected
    )
    receipt = store.one("SELECT status,message_id FROM announcement_deliveries")
    assert receipt == (
        {"status": "sending", "message_id": None}
        if failure == "before"
        else {"status": "sent", "message_id": "accepted"}
    )
    assert not store.recover_durability()
    with store.tx() as db:
        db.execute("UPDATE roster_entries SET manual_weight=153000")
    assert (
        store.one("SELECT manual_weight FROM roster_entries")["manual_weight"] == 153000
    )


def test_failed_local_commit_remains_fenced_then_retries_authoritative_image(
    durable_setup, monkeypatch
):
    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    collection.fail = "after"
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as db:
            db.execute("UPDATE roster_entries SET manual_weight=154000")
    collection.fail = None
    connect = sqlite3.connect

    class FailedCommit(sqlite3.Connection):
        def commit(self):
            raise sqlite3.OperationalError("simulated disk commit failure")

    def fail_local(database, *args, **kwargs):
        if str(database) == str(path):
            kwargs["factory"] = FailedCommit
        return connect(database, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", fail_local)
        with pytest.raises(DashboardDurabilityError):
            store.recover_durability()
    assert state.poisoned
    with connect(path) as db:
        assert (
            db.execute("SELECT manual_weight FROM roster_entries").fetchone()[0]
            == 149000
        )
    assert store.recover_durability()
    assert (
        store.one("SELECT manual_weight FROM roster_entries")["manual_weight"] == 154000
    )


def test_local_confirmed_role_receipts_survive_core_reconciliation(durable_setup):
    from test_cwl_pool_roles import save

    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    with store.tx() as db:
        db.execute("UPDATE member_season SET season_id=1 WHERE id=1")
        db.execute("UPDATE signups SET user_id='111111111111111111'")
    save(store, pool="lazy")
    with store.role_tx() as db:
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0] > 0
        db.execute(
            "UPDATE cwl_pool_role_jobs SET state='done',message='confirmed receipt'"
        )
    with sqlite3.connect(path) as db:
        rows_before = db.execute(
            "SELECT id,state,message FROM cwl_pool_role_jobs ORDER BY id"
        ).fetchall()
        triggers_before = db.execute(
            "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
        ).fetchall()
    state.poisoned = True
    assert store.recover_durability()
    assert store.role_dirty  # Recovered local terminal receipts still need backup.
    with sqlite3.connect(path) as db:
        assert (
            db.execute(
                "SELECT id,state,message FROM cwl_pool_role_jobs ORDER BY id"
            ).fetchall()
            == rows_before
        )
        assert (
            db.execute(
                "SELECT name,sql FROM sqlite_master WHERE type='trigger' ORDER BY name"
            ).fetchall()
            == triggers_before
        )
    assert (
        store.one(
            "SELECT COUNT(*) n FROM cwl_pool_role_jobs WHERE state IN ('pending','leased')"
        )["n"]
        == 0
    )


def test_accepted_new_role_intent_without_local_proof_is_paused(durable_setup):
    from test_cwl_pool_roles import save
    from utils import cwl_pool_roles as roles

    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    with store.tx() as db:
        db.execute("UPDATE member_season SET season_id=1 WHERE id=1")
        db.execute("UPDATE signups SET user_id='111111111111111111'")
    collection.fail = "after"
    with pytest.raises(DashboardDurabilityError):
        save(store, pool="lazy")
    collection.fail = None
    assert store.recover_durability()
    with sqlite3.connect(path) as db:
        db.row_factory = sqlite3.Row
        assert roles.recovery_paused(db)
        assert db.execute(
            "SELECT role_id FROM cwl_pool_role_settings WHERE pool='lazy'"
        ).fetchone()[0]
    assert store.role_recovery_error


def test_owner_changed_after_fence_cannot_complete_local_recovery(owner):
    state, collection, path = owner
    state.poisoned = True
    image = state.recovery_image()
    collection.doc["owner"] = "new-writer"
    with pytest.raises(DashboardDurabilityError):
        state.confirm_recovery(image)
    assert state.poisoned


def test_lifecycle_retries_recovery_and_keeps_heartbeat_alive(monkeypatch, caplog):
    import asyncio

    async def scenario():
        import asyncio
        import logging
        from types import SimpleNamespace
        from cwl_web import durability

        real_sleep = asyncio.sleep
        finished = asyncio.Event()
        sleeps = 0
        owner = SimpleNamespace(poisoned=True, heartbeats=0)

        def heartbeat():
            owner.heartbeats += 1

        owner.heartbeat = heartbeat
        attempts = []

        def recover():
            attempts.append(True)
            if len(attempts) == 1:
                raise DashboardDurabilityError("offline")
            owner.poisoned = False
            return True

        async def tick(seconds):
            nonlocal sleeps
            sleeps += 1
            if sleeps >= 4:
                finished.set()
                await asyncio.Future()
            await real_sleep(0)

        monkeypatch.setattr(
            durability,
            "asyncio",
            SimpleNamespace(
                sleep=tick,
                to_thread=asyncio.to_thread,
                create_task=asyncio.create_task,
                CancelledError=asyncio.CancelledError,
            ),
        )
        context = durability.lifecycle(
            {"store": SimpleNamespace(durability=owner, recover_durability=recover)}
        )
        with caplog.at_level(logging.INFO):
            await context.__anext__()
            await asyncio.wait_for(finished.wait(), 3)
            await context.aclose()
        assert len(attempts) == 2
        assert owner.heartbeats == 1
        assert (
            sum(
                "temporarily unavailable" in record.message for record in caplog.records
            )
            == 1
        )
        assert (
            sum(
                "saved receipts reconciled" in record.message
                for record in caplog.records
            )
            == 1
        )

    asyncio.run(scenario())


def test_repeated_lost_recovery_acknowledgements_keep_bounded_receipts(owner):
    state, collection, path = owner
    state.poisoned = True
    collection.fail = "after"
    for _ in range(80):
        with pytest.raises(DashboardDurabilityError):
            state.recovery_image()
        assert len(state._receipts) <= 3
    collection.fail = None
    image = state.recovery_image()
    state.confirm_recovery(image)
    state.finish_recovery(image)
    assert not state.poisoned


def test_majority_observed_newer_revision_cannot_regress_to_an_old_known_head(owner):
    state, collection, path = owner
    original = deepcopy(collection.doc)
    state.poisoned = True
    collection.fail = "after"
    for _ in range(2):
        with pytest.raises(DashboardDurabilityError):
            state.recovery_image()
    collection.fail = None
    collection.doc = original
    with pytest.raises(DashboardDurabilityError):
        state.recovery_image()
    assert collection.doc == original


def test_role_work_after_recovery_unfences_cannot_lose_its_dirty_flag(durable_setup):
    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    state.poisoned = True
    finished = state.finish_recovery

    def writer_immediately_after_unfencing(image):
        finished(image)
        with store.role_tx() as db:
            db.execute("UPDATE cwl_pool_role_clock SET next_at=next_at+1 WHERE id=1")

    state.finish_recovery = writer_immediately_after_unfencing
    assert store.recover_durability()
    assert store.role_dirty


def test_local_database_open_failure_stays_retryable_and_fenced(
    durable_setup, monkeypatch
):
    _path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    state.poisoned = True
    with monkeypatch.context() as patch:
        patch.setattr(
            sqlite3,
            "connect",
            lambda *a, **kw: (_ for _ in ()).throw(
                sqlite3.OperationalError("owned open failure")
            ),
        )
        with pytest.raises(DashboardDurabilityError, match="temporarily unavailable"):
            store.recover_durability()
    assert state.poisoned
    assert store.recover_durability()


@pytest.mark.parametrize("damage", ["foreign", "corrupt"])
def test_permanent_recovery_fence_logs_once_and_never_downgrades(owner, caplog, damage):
    from utils.cwl_dashboard_state import DashboardDurabilityAttention

    state, collection, _path = owner
    state.poisoned = True
    if damage == "foreign":
        collection.doc["owner"] = "another-writer"
    else:
        collection.doc["payload"] = b"invalid-compressed-image"
    for _ in range(2):
        with pytest.raises(DashboardDurabilityAttention, match="needs attention"):
            state.recovery_image()
        with pytest.raises(DashboardDurabilityAttention):
            state.check()
    assert state.poisoned
    assert sum(record.levelname == "CRITICAL" for record in caplog.records) == 1


def test_recovery_stays_fenced_at_the_actual_local_commit(durable_setup, monkeypatch):
    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    state.poisoned = True
    connect = sqlite3.connect
    committed = []

    class ObservedCommit(sqlite3.Connection):
        def commit(self):
            assert state.poisoned, "Writer became available before local FULL commit"
            committed.append(True)
            return super().commit()

    def observed(database, *args, **kwargs):
        if str(database) == str(path):
            kwargs["factory"] = ObservedCommit
        return connect(database, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", observed)
        assert store.recover_durability()
    assert committed == [True]
    assert not state.poisoned


def test_store_rechecks_owner_before_committing_recovered_rows(durable_setup):
    path, store, state, collection = durable_setup
    collection.find_one = lambda query: (
        deepcopy(collection.doc) if collection.matches(query) else None
    )
    collection.fail = "after"
    with pytest.raises(DashboardDurabilityError):
        with store.tx() as db:
            db.execute("UPDATE roster_entries SET manual_weight=155000")
    collection.fail = None
    recover = state.recovery_image

    def changed_owner_after_image():
        image = recover()
        collection.doc["owner"] = "foreign-writer"
        return image

    state.recovery_image = changed_owner_after_image
    with pytest.raises(DashboardDurabilityError):
        store.recover_durability()
    assert state.poisoned
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT manual_weight FROM roster_entries").fetchone()[0]
            == 149000
        )


def test_known_foreign_lease_is_attention_immediately(owner, caplog):
    from utils.cwl_dashboard_state import DashboardDurabilityAttention
    state, collection, _path = owner
    collection.doc["owner"] = "foreign"
    with pytest.raises(DashboardDurabilityAttention):
        state.heartbeat()
    with pytest.raises(DashboardDurabilityAttention):
        state.check()
    assert state.poisoned
    assert sum(record.levelname == "CRITICAL" for record in caplog.records) == 1


def test_permanent_storage_response_carries_attention_header():
    import asyncio
    from cwl_web.app import errors
    from utils.cwl_dashboard_state import DashboardDurabilityAttention
    async def handler(_request):
        raise DashboardDurabilityAttention("Dashboard storage needs attention.")
    from types import SimpleNamespace
    response = asyncio.run(errors(SimpleNamespace(path="/api/cwl/fixture"), handler))
    assert response.status == 503
    assert response.headers["X-Dashboard-Storage-Degraded"] == "1"
    assert response.headers["X-Dashboard-Storage-Attention"] == "1"
