import asyncio

import pytest

from tests.test_cwl_dashboard_integration import MemoryMongo
from utils import cwl_campaign, cwl_web_bridge


GUILD = 22
CYCLE = "2026-10"


def run(coro):
    return asyncio.run(coro)


def settings(loaded, pool="main"):
    return {
        "guild_id": GUILD,
        "cycle": CYCLE,
        "pool": pool,
        "publication_version": 1,
        "expected_generation": cwl_web_bridge.campaign_generation(loaded),
        "expected_channel_id": loaded["campaign"]["messages"]["roster"]["variants"][pool]["destination_channel_id"],
        "requested_by": 505227988229554179,
    }


def test_queue_native_send_and_manage_share_one_occurrence():
    async def scenario():
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        row = await cwl_web_bridge.queue_roster_send(mongo, **settings(loaded))
        assert row["status"] == "pending"
        sent = []

        async def sender(guild, cycle, message, variants, **kwargs):
            sent.append((guild, cycle, message, variants, kwargs))
            await cwl_campaign.record_delivery(mongo, guild, cycle, {
                "occurrence_id": cwl_campaign.occurrence_id(cycle, message, variants[0]),
                "message_key": message, "variant": variants[0], "status": "sent",
                "channel_id": row["channel_id"], "message_id": 123,
            })
            return True

        assert await cwl_web_bridge.process_pending_roster_requests(
            mongo, sender, guild_id=GUILD,
        ) == 1
        assert len(sent) == 1
        status = await cwl_web_bridge.get_roster_send_status(mongo, GUILD, CYCLE, "main")
        assert status["status"] == "sent"
        assert status["receipt"]["message_id"] == 123
        assert await cwl_web_bridge.process_pending_roster_requests(
            mongo, sender, guild_id=GUILD,
        ) == 0
        with pytest.raises(cwl_web_bridge.BridgeConflict, match="already sent"):
            await cwl_web_bridge.queue_roster_send(mongo, **settings(loaded))
    run(scenario())


def test_manage_send_before_worker_cancels_pending_web_post():
    async def scenario():
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        await cwl_web_bridge.queue_roster_send(mongo, **settings(loaded))
        await cwl_campaign.record_delivery(mongo, GUILD, CYCLE, {
            "occurrence_id": f"{CYCLE}|roster|main", "message_key": "roster",
            "variant": "main", "status": "sent", "message_id": 321,
        })

        async def forbidden(*args, **kwargs):
            raise AssertionError("The web bridge must not post after Manage")

        rows = await mongo.bot_config.find({"kind": cwl_web_bridge.REQUEST_KIND}).to_list(length=None)
        result = await cwl_web_bridge.process_roster_request(mongo, rows[0], forbidden)
        assert result["status"] == "sent"
        assert result["receipt"]["message_id"] == 321
    run(scenario())


def test_stale_generation_and_channel_fail_closed():
    async def scenario():
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        request = settings(loaded)
        with pytest.raises(cwl_web_bridge.BridgeConflict, match="channel changed"):
            await cwl_web_bridge.queue_roster_send(
                mongo, **{**request, "expected_channel_id": 99},
            )
        row = await cwl_web_bridge.queue_roster_send(mongo, **request)
        defaults = cwl_campaign.defaults_id(GUILD)
        await mongo.bot_config.update_one(
            {"_id": defaults},
            {"$set": {"revision": 1}},
            upsert=True,
        )

        async def forbidden(*args, **kwargs):
            raise AssertionError("Stale request must never post")

        result = await cwl_web_bridge.process_roster_request(mongo, row, forbidden)
        assert result["status"] == "stale"
        with pytest.raises(cwl_web_bridge.BridgeConflict, match="settings changed"):
            await cwl_web_bridge.queue_roster_send(
                mongo, **{**request, "pool": "lazy",
                          "expected_channel_id": loaded["campaign"]["messages"]["roster"]["variants"]["lazy"]["destination_channel_id"]},
            )
    run(scenario())


def test_unknown_sender_outcome_never_blindly_retries():
    async def scenario():
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        await cwl_web_bridge.queue_roster_send(mongo, **settings(loaded))
        calls = 0

        async def uncertain(*args, **kwargs):
            nonlocal calls
            calls += 1
            raise TimeoutError("Discord response missing")

        assert await cwl_web_bridge.process_pending_roster_requests(
            mongo, uncertain, guild_id=GUILD,
        ) == 1
        row = await mongo.bot_config.find_one({
            "_id": cwl_web_bridge.request_id(GUILD, CYCLE, "main"),
        })
        assert row["status"] == "uncertain"
        assert await cwl_web_bridge.process_pending_roster_requests(
            mongo, uncertain, guild_id=GUILD,
        ) == 0
        assert calls == 1
        assert await mongo.bot_config.find_one({
            "_id": cwl_web_bridge.worker_id(GUILD),
        }) is not None
    run(scenario())


def test_retry_requires_definite_failed_state():
    async def scenario():
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        request = settings(loaded)
        row = await cwl_web_bridge.queue_roster_send(mongo, **request)
        with pytest.raises(cwl_web_bridge.BridgeConflict, match="already exists"):
            await cwl_web_bridge.queue_roster_send(
                mongo, **{**request, "retry_failed": True},
            )
        await mongo.bot_config.update_one(
            {"_id": row["_id"], "status": "pending"},
            {"$set": {"status": "failed", "error": "definitive rejection"}},
        )
        retried = await cwl_web_bridge.queue_roster_send(
            mongo, **{**request, "retry_failed": True},
        )
        assert retried["status"] == "pending"
        assert "error" not in retried
    run(scenario())



def test_native_manage_unknown_roster_outcome_blocks_both_senders(monkeypatch):
    from tests.test_cwl_dashboard_integration import (
        StrictCampaignRest, applied_campaign, install_runtime,
    )
    from extensions.tasks import cwl_reminder

    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        rest = StrictCampaignRest()
        install_runtime(monkeypatch, mongo, rest=rest)
        channel = loaded["campaign"]["messages"]["roster"]["variants"]["main"]["destination_channel_id"]
        rest.failing_channels.add(channel)

        generation = cwl_web_bridge.campaign_generation(loaded)
        assert await cwl_reminder.send_campaign_message(
            GUILD, CYCLE, "roster", ["main"], generation, manual=True,
        ) is False
        current = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        assert f"{CYCLE}|roster|main" in current["uncertain_occurrences"]
        assert current["deliveries"][-1]["status"] == "uncertain"
        rest.failing_channels.clear()
        assert await cwl_reminder.send_campaign_message(
            GUILD, CYCLE, "roster", ["main"], generation, manual=True,
        ) is False
        assert rest.sent == []
        status = await cwl_web_bridge.get_roster_send_status(mongo, GUILD, CYCLE, "main")
        assert status["status"] == "uncertain"
    run(scenario())


def test_web_unknown_roster_outcome_blocks_manage_retry(monkeypatch):
    from tests.test_cwl_dashboard_integration import (
        StrictCampaignRest, applied_campaign, install_runtime,
    )
    from extensions.tasks import cwl_reminder

    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        rest = StrictCampaignRest()
        install_runtime(monkeypatch, mongo, rest=rest)
        request = settings(loaded)
        row = await cwl_web_bridge.queue_roster_send(mongo, **request)
        rest.failing_channels.add(request["expected_channel_id"])
        result = await cwl_web_bridge.process_roster_request(
            mongo, row, cwl_reminder.send_campaign_message,
        )
        assert result["status"] == "uncertain"
        rest.failing_channels.clear()
        assert await cwl_reminder.send_campaign_message(
            GUILD, CYCLE, "roster", ["main"], request["expected_generation"], manual=True,
        ) is False
        assert rest.sent == []
    run(scenario())


def test_stale_request_can_be_explicitly_requeued_after_review():
    async def scenario():
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        request = settings(loaded)
        row = await cwl_web_bridge.queue_roster_send(mongo, **request)
        await mongo.bot_config.update_one(
            {"_id": row["_id"]}, {"$set": {"status": "stale"}},
        )
        await mongo.bot_config.update_one(
            {"_id": cwl_campaign.defaults_id(GUILD)},
            {"$set": {"revision": 1}}, upsert=True,
        )
        refreshed = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        with pytest.raises(cwl_web_bridge.BridgeConflict, match="settings changed"):
            await cwl_web_bridge.queue_roster_send(
                mongo, **{**request, "retry_failed": True},
            )
        retried = await cwl_web_bridge.queue_roster_send(
            mongo, **{**settings(refreshed), "retry_failed": True},
        )
        assert retried["status"] == "pending"
        assert retried["generation"] == cwl_web_bridge.campaign_generation(refreshed)
    run(scenario())


def test_native_ledger_pending_is_reported_sent_without_repost():
    async def scenario():
        mongo = MemoryMongo()
        job_id = f"cwl_campaign:{GUILD}:{CYCLE}:roster:main"
        await mongo.cwl_pending_reminders.update_one(
            {"_id": job_id},
            {"$set": {"status": "ledger_pending", "receipt": {
                "occurrence_id": f"{CYCLE}|roster|main", "status": "sent",
                "message_id": 555,
            }}},
            upsert=True,
        )
        status = await cwl_web_bridge.get_roster_send_status(mongo, GUILD, CYCLE, "main")
        assert status["status"] == "sent"
        assert status["receipt"]["message_id"] == 555
    run(scenario())



def test_native_roster_post_then_lost_response_is_never_resent(monkeypatch):
    from tests.test_cwl_dashboard_integration import (
        StrictCampaignRest, applied_campaign, install_runtime,
    )
    from extensions.tasks import cwl_reminder

    class LostResponseRest(StrictCampaignRest):
        async def create_message(self, channel, **kwargs):
            self.sent.append({"channel": channel, **kwargs})
            raise TimeoutError("response lost after Discord accepted the post")

    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        rest = LostResponseRest()
        install_runtime(monkeypatch, mongo, rest=rest)
        generation = cwl_web_bridge.campaign_generation(loaded)

        assert await cwl_reminder.send_campaign_message(
            GUILD, CYCLE, "roster", ["main"], generation, manual=True,
        ) is False
        assert len(rest.sent) == 1
        assert await cwl_reminder.send_campaign_message(
            GUILD, CYCLE, "roster", ["main"], generation, manual=True,
        ) is False
        assert len(rest.sent) == 1
        current = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        assert f"{CYCLE}|roster|main" in current["uncertain_occurrences"]
    run(scenario())


def test_definitive_native_rejection_clears_uncertainty_and_reports_failed(monkeypatch):
    from tests.test_cwl_dashboard_integration import (
        StrictCampaignRest, applied_campaign, install_runtime,
    )
    from extensions.tasks import cwl_reminder

    class RejectedRest(StrictCampaignRest):
        async def create_message(self, channel, **kwargs):
            raise ValueError("Channel configuration rejected")

    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        install_runtime(monkeypatch, mongo, rest=RejectedRest())
        generation = cwl_web_bridge.campaign_generation(loaded)

        assert await cwl_reminder.send_campaign_message(
            GUILD, CYCLE, "roster", ["main"], generation, manual=True,
        ) is False
        current = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        assert f"{CYCLE}|roster|main" not in current["uncertain_occurrences"]
        assert current["deliveries"][-1]["status"] == "failed"
        status = await cwl_web_bridge.get_roster_send_status(mongo, GUILD, CYCLE, "main")
        assert status["status"] == "failed"
    run(scenario())



def test_concurrent_manage_and_web_share_atomic_roster_claim(monkeypatch):
    from tests.test_cwl_dashboard_integration import (
        StrictCampaignRest, applied_campaign, install_runtime,
    )
    from extensions.tasks import cwl_reminder

    async def scenario():
        mongo = MemoryMongo()
        loaded = await applied_campaign(mongo, monkeypatch)
        rest = StrictCampaignRest()
        install_runtime(monkeypatch, mongo, rest=rest)
        request = settings(loaded)
        row = await cwl_web_bridge.queue_roster_send(mongo, **request)
        await asyncio.gather(
            cwl_reminder.send_campaign_message(
                GUILD, CYCLE, "roster", ["main"],
                request["expected_generation"], manual=True,
            ),
            cwl_web_bridge.process_roster_request(
                mongo, row, cwl_reminder.send_campaign_message,
            ),
        )
        assert len(rest.sent) == 1
        status = await cwl_web_bridge.get_roster_send_status(
            mongo, GUILD, CYCLE, "main",
        )
        assert status["status"] == "sent"
    run(scenario())



def test_old_native_failure_does_not_hide_new_pending_request():
    async def scenario():
        mongo = MemoryMongo()
        await cwl_campaign.record_delivery(mongo, GUILD, CYCLE, {
            "occurrence_id": f"{CYCLE}|roster|main", "message_key": "roster",
            "variant": "main", "status": "failed",
            "error_type": "ForbiddenError",
        })
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        await cwl_web_bridge.queue_roster_send(mongo, **settings(loaded))
        status = await cwl_web_bridge.get_roster_send_status(
            mongo, GUILD, CYCLE, "main",
        )
        assert status["status"] == "pending"
    run(scenario())


def test_revoked_roster_sender_never_reaches_discord():
    async def scenario():
        from unittest.mock import AsyncMock
        mongo = MemoryMongo()
        loaded = await cwl_campaign.load_campaign(mongo, GUILD, CYCLE)
        row = await cwl_web_bridge.queue_roster_send(mongo, **settings(loaded))
        sender = AsyncMock()
        result = await cwl_web_bridge.process_roster_request(mongo, row, sender, authorize=AsyncMock(return_value=False))
        assert result['status'] == 'failed'
        sender.assert_not_awaited()
    run(scenario())
