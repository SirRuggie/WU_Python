"""Real isolated Mongo recovery checkpoints, with fake Discord only."""

import asyncio
import os
from uuid import uuid4

import pytest
from pymongo import MongoClient
from pymongo.errors import AutoReconnect
from utils.cwl_dashboard_state import (
    MongoDashboardState,
    DashboardDurabilityError,
    decode,
)
from cwl_web.store import Store
from utils import cwl_pool_roles as roles
from extensions.tasks import cwl_pool_roles as worker
from test_cwl_pool_roles import signup, save, bot_fixture, send_for

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="dedicated owned Mongo fixture not provided"
)


@pytest.mark.parametrize("lost_ack", [False, True])
def test_role_receipt_or_lease_recovers_without_duplicate_discord_change(
    tmp_path, lost_ack
):
    assert URI == "mongodb://127.0.0.1:27154"
    client = MongoClient(URI, tz_aware=True)
    db = client["wu_pool_roles_fixture_" + uuid4().hex]
    state = second = None
    try:
        seed = Store(str(tmp_path / "seed.sqlite"))
        with seed.tx() as sql:
            sql.execute("INSERT INTO seasons(id,label) VALUES(1,'Current')")
        state = MongoDashboardState(db.state)
        state.seed(seed.path)
        state.restore(str(tmp_path / "first.sqlite"))
        store = Store(str(tmp_path / "first.sqlite"), durability=state)
        save(store)
        signup(store)
        with store.tx() as sql:
            job = roles.claim(sql)
        bot, _, _, _ = bot_fixture()
        real = send_for(store)

        async def missing_receipt(action, **body):
            if action == "finish":
                raise worker.BridgeUnavailable()
            return await real(action, **body)

        if lost_ack:
            collection = state.collection

            class AcceptedThenLost:
                armed = True

                def __getattr__(self, name):
                    return getattr(collection, name)

                def update_one(self, *args, **kwargs):
                    result = collection.update_one(*args, **kwargs)
                    if self.armed:
                        self.armed = False
                        raise AutoReconnect(
                            "simulated lost acknowledgement after accepted checkpoint"
                        )
                    return result

            state.collection = AcceptedThenLost()
            with pytest.raises(DashboardDurabilityError):
                asyncio.run(worker.process_job(bot, job, send=real))
            assert state.poisoned
        else:
            asyncio.run(worker.process_job(bot, job, send=missing_receipt))
        bot.rest.add_role_to_member.assert_awaited_once()
        state.close()
        state = None
        second = MongoDashboardState(db.state)
        second.restore(str(tmp_path / "recovered.sqlite"))
        recovered = Store(str(tmp_path / "recovered.sqlite"), durability=second)
        with recovered.tx() as sql:
            assert (
                sql.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0]
                == 1
            )
            if not lost_ack:
                sql.execute("UPDATE cwl_pool_role_jobs SET lease_until=0")
                sql.execute("UPDATE cwl_pool_role_clock SET next_at=0")
            next_job = roles.claim(sql)
        if next_job:
            asyncio.run(worker.process_job(bot, next_job, send=send_for(recovered)))
        bot.rest.add_role_to_member.assert_awaited_once()
        image = decode(db.state.find_one({"_id": second.key}))
        try:
            assert (
                image.execute("SELECT state FROM cwl_pool_role_jobs").fetchone()[0]
                == "done"
            )
            assert image.execute("SELECT COUNT(*) FROM signups").fetchone()[0] == 1
        finally:
            image.close()
    finally:
        if state:
            state.close()
        if second:
            second.close()
        client.drop_database(db.name)
        client.close()
