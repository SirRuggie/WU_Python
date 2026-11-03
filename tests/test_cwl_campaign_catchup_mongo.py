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
            sentinel = {"_id": "unrelated-fixture", "kind": "other", "value": [1, 2, 3]}
            await mongo.bot_config.insert_one(deepcopy(sentinel))
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
            assert await mongo.bot_config.find_one({"_id": sentinel["_id"]}) == sentinel
            explanation = await db.command({
                "explain": {"find": mongo.bot_config.name, "filter": {"_id": campaign.cycle_id(guild_id, CYCLE)}},
                "verbosity": "executionStats",
            })
            assert "_id_" in str(explanation["queryPlanner"]["winningPlan"])
            assert explanation["executionStats"]["totalDocsExamined"] <= 1
        finally:
            for collection in collections:
                await collection.drop()
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("boundary", ["fallback", "scheduled_cleanup", "recovery_cleanup", "different_receipt"])
def test_real_mongo_receipt_ownership_cas_preserves_replacements(boundary):
    async def run():
        client = AsyncMongoClient("mongodb://127.0.0.1:27171", serverSelectionTimeoutMS=2000, timeoutMS=5000)
        collection = client["catchup_144_test"]["owner_" + uuid4().hex]
        mongo = SimpleNamespace(cwl_pending_reminders=collection)
        job_id = "cwl_campaign:644963518025826319:2026-11:signup:main"
        old = {
            "_id": job_id, "kind": "campaign", "job_kind": "catchup",
            "status": "scheduled", "guild_id": 644963518025826319,
            "cycle": CYCLE, "message_id": "signup", "variants": ["main"],
            "generation": "old", "catchup": {"protocol": 1, "original_due_at": "2026-11-20T11:59:00-05:00"},
        }
        receipt = {"occurrence_id": campaign.occurrence_id(CYCLE, "signup", "main"),
                   "status": "sent", "late": True, "message_id": 123}
        pending = {**old, "status": "ledger_pending", "receipt": receipt}
        replacement = {**old, "job_kind": "manual", "generation": "new"}
        replacement.pop("catchup")
        if boundary == "scheduled_cleanup":
            replacement = deepcopy(pending)
        elif boundary == "different_receipt":
            replacement = {**pending, "receipt": {**receipt, "message_id": 124}}
        try:
            await collection.insert_one(deepcopy(replacement))
            if boundary == "fallback":
                with pytest.raises(RuntimeError, match="owner changed"):
                    await campaign.persist_catchup_receipt(mongo, old, receipt, "OSError")
            else:
                observed = old if boundary == "scheduled_cleanup" else pending
                await campaign.delete_catchup_job(mongo, observed)
            assert await collection.find_one({"_id": job_id}) == replacement
        finally:
            await collection.drop()
            await client.close()

    asyncio.run(run())


def test_real_mongo_preflight_release_preserves_a_later_worker_and_uncertainty():
    async def run():
        client = AsyncMongoClient("mongodb://127.0.0.1:27171", serverSelectionTimeoutMS=2000, timeoutMS=5000)
        collection = client["catchup_144_test"]["claim_" + uuid4().hex]
        mongo = SimpleNamespace(bot_config=collection)
        guild_id = 644963518025826319
        oid = campaign.occurrence_id(CYCLE, "signup", "main")
        old = {"at": "2026-11-20T16:00:00Z", "generation": "same"}
        later = {"at": "2026-11-20T16:16:00Z", "generation": "same"}
        document = {"_id": campaign.cycle_id(guild_id, CYCLE), "delivery_claims": {oid: later}, "uncertain_occurrences": [oid]}
        try:
            await collection.insert_one(deepcopy(document))
            assert not await campaign.release_catchup_preflight_claim(mongo, guild_id, CYCLE, oid, old)
            assert not await campaign.release_catchup_preflight_claim(mongo, guild_id, CYCLE, oid, later)
            assert await collection.find_one({"_id": document["_id"]}) == document
            await collection.update_one({"_id": document["_id"]}, {"$pull": {"uncertain_occurrences": oid}})
            assert not await campaign.release_catchup_preflight_claim(mongo, guild_id, CYCLE, oid, old)
            assert await campaign.release_catchup_preflight_claim(mongo, guild_id, CYCLE, oid, later)
            assert not (await collection.find_one({"_id": document["_id"]}))["delivery_claims"]
        finally:
            await collection.drop()
            await client.close()

    asyncio.run(run())


def test_real_mongo_combined_legacy_report_is_once_and_cleans_only_the_observed_row():
    async def run():
        client = AsyncMongoClient("mongodb://127.0.0.1:27171", serverSelectionTimeoutMS=2000, timeoutMS=5000)
        db = client["catchup_144_test"]
        prefix = "legacy_" + uuid4().hex
        config, pending = db[prefix + "_config"], db[prefix + "_pending"]
        mongo = SimpleNamespace(bot_config=config, cwl_pending_reminders=pending)
        guild_id = 644963518025826319
        row = {
            "_id": f"cwl_campaign:{guild_id}:{CYCLE}:signup", "kind": "campaign",
            "guild_id": guild_id, "cycle": CYCLE, "message_id": "signup",
            "variants": ["main", "lazy"], "run_time": "2026-11-20T11:59:00-05:00",
            "job_kind": "scheduled", "status": "scheduled", "generation": "old",
        }
        replacement = {**row, "variants": ["main"], "job_kind": "manual", "generation": "new"}
        try:
            await pending.insert_one(deepcopy(replacement))
            assert await campaign.record_legacy_catchup_skip(mongo, row, row["run_time"])
            assert await pending.find_one({"_id": row["_id"]}) == replacement
            await pending.replace_one({"_id": row["_id"]}, deepcopy(row))
            assert not await campaign.record_legacy_catchup_skip(mongo, row, row["run_time"])
            assert await pending.find_one({"_id": row["_id"]}) is None
            state = await config.find_one({"_id": campaign.cycle_id(guild_id, CYCLE)})
            assert len(state["deliveries"]) == 1
            assert "occurrence_id" not in state["deliveries"][0]
            assert not state.get("catchup_reported_occurrences") and not state.get("skipped")
        finally:
            await config.drop()
            await pending.drop()
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("mode", ["duplicate", "uncertain", "lost_ack", "already_sent", "newer_request"])
def test_real_mongo_staff_not_sent_is_one_owned_receipt_without_clearing_other_send(mode):
    async def run():
        client = AsyncMongoClient("mongodb://127.0.0.1:27171", serverSelectionTimeoutMS=2000, timeoutMS=5000)
        db = client["catchup_144_test"]
        prefix = "busy_" + uuid4().hex
        config, pending = db[prefix + "_config"], db[prefix + "_pending"]
        mongo = SimpleNamespace(bot_config=config, cwl_pending_reminders=pending)
        gid = 644963518025826319
        oid = campaign.occurrence_id(CYCLE, "signup", "main")
        row = {
            "_id": f"cwl_campaign:{gid}:{CYCLE}:signup:main", "kind": "campaign",
            "guild_id": gid, "cycle": CYCLE, "message_id": "signup", "variants": ["main"],
            "generation": "1:0", "job_kind": "manual", "status": "scheduled",
            "run_time": "2026-11-20T12:00:02-05:00", "failure_count": 0,
            "staff_request_id": "a" * 32,
        }
        core = {
            "_id": campaign.cycle_id(gid, CYCLE), "campaign": {"paused": False},
            "delivery_claims": {oid: {"at": "2026-11-20T17:00:00Z", "generation": "1:0"}},
            "uncertain_occurrences": [oid] if mode == "uncertain" else [],
        }
        if mode == "already_sent":
            core.update(sent_occurrences=[oid], deliveries=[{"occurrence_id": oid, "status": "sent"}])
        replacement = {**row, "staff_request_id": "b" * 32} if mode == "newer_request" else row
        try:
            await config.insert_one(deepcopy(core))
            await pending.insert_one(deepcopy(replacement))
            if mode == "lost_ack":
                class LostAck:
                    async def update_one(self, query, update, **kwargs):
                        result = await config.update_one(query, update, **kwargs)
                        if "staff_not_sent_requests" in query:
                            raise OSError("Fixture history write applied, acknowledgement lost")
                        return result
                    def __getattr__(self, name):
                        return getattr(config, name)
                with pytest.raises(OSError):
                    await campaign.record_staff_not_sent(SimpleNamespace(bot_config=LostAck(), cwl_pending_reminders=pending), row)
                terminal = await pending.find_one({"_id": row["_id"]})
                assert campaign.is_staff_not_sent_receipt(terminal)
                assert await campaign.record_staff_not_sent(mongo, terminal)
            elif mode == "duplicate":
                await asyncio.gather(
                    campaign.record_staff_not_sent(mongo, deepcopy(row)),
                    campaign.record_staff_not_sent(mongo, deepcopy(row)),
                )
            else:
                await campaign.record_staff_not_sent(mongo, row)
            current = await config.find_one({"_id": core["_id"]})
            assert current["campaign"] == core["campaign"]
            assert current["delivery_claims"] == core["delivery_claims"]
            assert current["uncertain_occurrences"] == core["uncertain_occurrences"]
            if mode == "newer_request":
                assert await pending.find_one({"_id": row["_id"]}) == replacement
                assert not current.get("deliveries")
            else:
                assert await pending.find_one({"_id": row["_id"]}) is None
                assert len(current["deliveries"]) == 1
                if mode == "already_sent":
                    assert current["deliveries"][0]["status"] == "sent"
                else:
                    receipt = current["deliveries"][0]
                    assert receipt["reason"] == "Not sent: another send was running. Send again."
                    assert receipt["delivery_attempted"] is False
        finally:
            await config.drop()
            await pending.drop()
            await client.close()

    asyncio.run(run())


def test_due_scoped_reports_are_atomic_on_real_mongo():
    from test_cwl_campaign_due_report_storage import check_atomic_due_reports
    async def run():
        client = AsyncMongoClient('mongodb://127.0.0.1:27171', serverSelectionTimeoutMS=2000, timeoutMS=5000)
        db = client['catchup_156_' + uuid4().hex]
        mongo = SimpleNamespace(bot_config=db.config)
        try:
            await check_atomic_due_reports(mongo)
        finally:
            await client.drop_database(db.name)
            await client.close()
    asyncio.run(run())
