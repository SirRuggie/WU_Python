"""Owned real Mongo recovery copies; Discord transport remains detached and fake."""

import asyncio, os, json, time
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from pathlib import Path
import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from utils.cwl_dashboard_state import MongoDashboardState, decode
from cwl_web.store import Store
from utils import cwl_pool_roles as roles
from extensions.tasks import cwl_pool_roles as worker
from test_cwl_pool_roles import USER, OTHER, signup, save, bot_fixture, send_for, claim

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="dedicated owned Mongo fixture not provided"
)


def seed(tmp_path, db):
    initial = Store(str(tmp_path / "seed.sqlite"))
    with initial.tx() as sql:
        sql.execute("INSERT INTO seasons(id,label) VALUES(1,'Current')")
        sql.execute("UPDATE member_season SET season_id=1 WHERE id=1")
    state = MongoDashboardState(db.state)
    state.seed(initial.path)
    path = tmp_path / "working.sqlite"
    state.restore(path)
    return state, Store(str(path), durability=state)


@pytest.mark.parametrize("lost_receipt", [False, True])
def test_local_role_progress_survives_restart_without_full_publish_per_job(
    tmp_path, lost_receipt
):
    assert URI == "mongodb://127.0.0.1:27154"
    client = MongoClient(URI, tz_aware=True)
    db = client["wu_roles_recovery_" + uuid4().hex]
    state = second = None
    try:
        state, store = seed(tmp_path, db)
        save(store)
        signup(store)
        baseline = state.revision
        job = claim(store)
        bot, _, _, _ = bot_fixture()
        real = send_for(store)

        async def send(action, **body):
            if action == "finish" and lost_receipt:
                raise worker.BridgeUnavailable()
            return await real(action, **body)

        asyncio.run(worker.process_job(bot, job, send=send))
        bot.rest.add_role_to_member.assert_awaited_once()
        assert state.revision == baseline
        image = decode(db.state.find_one({"_id": state.key}))
        try:
            assert (
                image.execute("SELECT state FROM cwl_pool_role_jobs").fetchone()[0]
                == "pending"
            )
        finally:
            image.close()
        path = store.path
        state.close()
        state = None
        second = MongoDashboardState(db.state)
        second.restore(path)
        recovered = Store(path, durability=second)
        assert recovered.role_recovery_error is None
        if lost_receipt:
            with recovered.role_tx() as sql:
                sql.execute("UPDATE cwl_pool_role_jobs SET lease_until=0")
            retry = claim(recovered)
            asyncio.run(worker.process_job(bot, retry, send=send_for(recovered)))
        else:
            assert claim(recovered) is None
        bot.rest.add_role_to_member.assert_awaited_once()
        assert recovered.one("SELECT state FROM cwl_pool_role_jobs")["state"] == "done"
        assert recovered.flush_role_progress()["published"]
        checkpoint = roles.decode_progress(second.load_role_progress())
        jobs = checkpoint["cwl_pool_role_jobs"]
        assert dict(zip(jobs["columns"], jobs["rows"][0]))["state"] == "done"
        assert second.revision == baseline
    finally:
        if state:
            state.close()
        if second:
            second.close()
        client.drop_database(db.name)
        client.close()


@pytest.mark.parametrize("accepted", [False, True])
def test_role_backup_failure_or_lost_ack_never_poisons_the_signup_writer(
    tmp_path, accepted
):
    assert URI == "mongodb://127.0.0.1:27154"
    client = MongoClient(URI, tz_aware=True)
    db = client["wu_roles_ack_" + uuid4().hex]
    state = None
    try:
        state, store = seed(tmp_path, db)
        save(store)
        signup(store)
        job = claim(store)
        bot, _, _, _ = bot_fixture()
        asyncio.run(worker.process_job(bot, job, send=send_for(store)))
        base = state.revision
        collection = state.collection

        class BackupFailure:
            armed = True
            calls = 0

            def __getattr__(self, name):
                return getattr(collection, name)

            def update_one(self, query, *args, **kwargs):
                if query.get("_id") == state.key + ":pool-roles-progress":
                    self.calls += 1
                    if self.armed:
                        self.armed = False
                        if accepted:
                            collection.update_one(query, *args, **kwargs)
                        raise AutoReconnect("owned fixture role backup failed")
                return collection.update_one(query, *args, **kwargs)

        failure = BackupFailure()
        state.collection = failure
        assert store.flush_role_progress()["published"] is False
        assert not state.poisoned and state.revision == base
        signup(store, "NEW", uid=OTHER)
        assert state.revision == base + 1 and not state.poisoned
        assert store.one("SELECT COUNT(*) AS n FROM signups")["n"] == 2
        assert store.flush_role_progress(now=time.time() + 10)["attempted"] is False
        assert store.flush_role_progress(now=time.time() + 61)["published"]
        assert failure.calls == 2
        bot.rest.add_role_to_member.assert_awaited_once()
    finally:
        if state:
            state.close()
        client.drop_database(db.name)
        client.close()


def test_missing_local_progress_pauses_ambiguous_work_but_not_new_signups(tmp_path):
    assert URI == "mongodb://127.0.0.1:27154"
    client = MongoClient(URI, tz_aware=True)
    db = client["wu_roles_missing_" + uuid4().hex]
    state = second = None
    try:
        state, store = seed(tmp_path, db)
        save(store)
        signup(store)
        job = claim(store)
        bot, _, _, _ = bot_fixture()
        asyncio.run(worker.process_job(bot, job, send=send_for(store)))
        state.close()
        state = None
        second = MongoDashboardState(db.state)
        path = tmp_path / "different-host.sqlite"
        second.restore(path)
        recovered = Store(str(path), durability=second)
        assert recovered.role_recovery_error
        signup(recovered, "NEW", uid=OTHER)
        assert recovered.one("SELECT COUNT(*) AS n FROM signups")["n"] == 2
        bot.rest.add_role_to_member.assert_awaited_once()
    finally:
        if state:
            state.close()
        if second:
            second.close()
        client.drop_database(db.name)
        client.close()


def test_real_mongo_ninety_one_job_copy_cost_is_coalesced(tmp_path):
    assert URI == "mongodb://127.0.0.1:27154"
    client = MongoClient(URI, tz_aware=True)
    db = client["wu_roles_cost_" + uuid4().hex]
    state = None
    try:
        state, store = seed(tmp_path, db)
        with store.tx() as sql:
            for index in range(91):
                sql.execute(
                    "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(1,?,?,'main',0,'Fixture',16)",
                    (str(index), str(int(USER) + index)),
                )
        save(store)
        base = state.revision
        start = datetime.now(timezone.utc)
        wall = time.perf_counter()
        snapshots = []
        for index in range(91):
            now = start + timedelta(seconds=index * 3)
            with store.role_tx() as sql:
                job = roles.claim(sql, now=now)
            assert job
            with store.role_tx() as sql:
                assert roles.finish(
                    sql, job["id"], job["lease_token"], job["generation"]
                )["accepted"]
            outcome = store.flush_role_progress(now=now.timestamp())
            if outcome.get("published"):
                snapshots.append(outcome)
        seconds = time.perf_counter() - wall
        assert state.revision == base and len(snapshots) == 5
        assert store.flush_role_progress(
            now=(start + timedelta(seconds=300)).timestamp()
        )["published"]
        head = state.load_role_progress()
        assert head["raw_bytes"] < 100000
        evidence = dict(
            jobs=91,
            local_transactions=182,
            full_dashboard_publishes=state.revision - base,
            role_backups_during_270_virtual_seconds=len(snapshots),
            final_backup_at_virtual_seconds=300,
            actual_local_mongo_protocol_seconds=round(seconds, 6),
            compressed_bytes=len(head["payload"]),
            raw_bytes=head["raw_bytes"],
            discord_delivery="not measured; protocol fixture only",
        )
        if os.environ.get("WU_POOL_ROLE_MONGO_COST_EVIDENCE"):
            Path(os.environ["WU_POOL_ROLE_MONGO_COST_EVIDENCE"]).write_text(
                json.dumps(evidence, indent=2)
            )
    finally:
        if state:
            state.close()
        client.drop_database(db.name)
        client.close()
