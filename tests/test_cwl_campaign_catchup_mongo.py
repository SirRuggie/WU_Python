"""Opt-in native Mongo protocol checks against the exclusively owned fixture."""

import asyncio
import os
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pymongo import AsyncMongoClient

from test_cwl_campaign_catchup import CYCLE, GUILD, runtime
from extensions.tasks import cwl_reminder as native
from utils import cwl_campaign as campaign

pytestmark = pytest.mark.skipif(
    os.environ.get("WU_CATCHUP_144_MONGO") != "27171",
    reason="Requires explicitly owned localhost27171 fixture",
)


@pytest.mark.parametrize("mode", ["normal", "crash", "race"])
def test_native_snowflake_restart_and_crash_use_real_mongo(runtime, monkeypatch, mode):
    async def run():
        client = AsyncMongoClient(
            "mongodb://127.0.0.1:27171", serverSelectionTimeoutMS=2000, timeoutMS=5000
        )
        db = client["catchup_144_test"]
        prefix = "native_" + uuid4().hex
        collections = [db[prefix + suffix] for suffix in ("_config", "_pending", "_legacy")]
        mongo = SimpleNamespace(
            bot_config=collections[0], cwl_pending_reminders=collections[1],
            cwl_reminder=collections[2],
        )
        try:
            await client.admin.command("ping")
            guild_id = 644963518025826319  # Fictional, not a production destination.
            document = deepcopy(runtime.mongo.bot_config.documents[campaign.defaults_id(GUILD)])
            document.update(_id=campaign.defaults_id(guild_id), guild_id=guild_id)
            document["campaign"]["messages"]["signup"]["schedule"] = {
                "mode": "monthly", "day": 20, "hour": 11, "minute": 59,
            }
            await mongo.bot_config.insert_one(document)
            monkeypatch.setattr(native, "mongo_client", mongo)
            runtime.rest.guild_id = guild_id
            loaded = await campaign.load_campaign(mongo, guild_id, CYCLE)
            job_id = native._campaign_job_id(guild_id, CYCLE, "signup", "main")
            await native._persist_campaign_job(
                job_id, runtime.clock[0].subtract(minutes=1), guild_id, CYCLE,
                "signup", ["main"], native._campaign_generation(loaded),
            )
            row = await mongo.cwl_pending_reminders.find_one({"_id": job_id})
            assert isinstance(row["guild_id"], int) and type(row["guild_id"]) is not int
            if mode == "crash":
                original = runtime.rest.create_message
                async def accepted_then_crash(*args, **kwargs):
                    await original(*args, **kwargs)
                    raise asyncio.CancelledError("Fixture crash after accepted POST")
                runtime.rest.create_message = accepted_then_crash
            await native._reconcile_cwl_startup()
            job = runtime.scheduler.get_job(job_id)
            assert job is not None
            if mode == "crash":
                with pytest.raises(asyncio.CancelledError):
                    await job.function(*job.args, **(getattr(job, "kwargs", None) or {}))
            elif mode == "race":
                args = job.args
                due_at = job.kwargs["catchup_due_at"]
                await asyncio.gather(
                    native._deliver_catchup_message(*args, due_at),
                    native._deliver_catchup_message(*args, due_at),
                )
            else:
                await job.function(*job.args, **(getattr(job, "kwargs", None) or {}))
            runtime.clock[0] = runtime.clock[0].add(minutes=16)
            runtime.scheduler.jobs.clear()
            await native._reconcile_cwl_startup()
            assert len(runtime.rest.sent) == 1
            final = await campaign.load_campaign(mongo, guild_id, CYCLE)
            assert len(final["deliveries"]) == 1
            assert final["deliveries"][0]["status"] == ("uncertain" if mode == "crash" else "sent")
            assert await mongo.cwl_pending_reminders.find_one({"_id": job_id}) is None
        finally:
            for collection in collections:
                await collection.drop()
            await client.close()

    asyncio.run(run())
