import asyncio
from copy import deepcopy

import hikari
import pytest

from extensions.commands import cwl_dashboard as ui
from tests.test_cwl_dashboard_integration import MemoryMongo, install_runtime, modal_context
from tests.test_cwl_navigation import nodes
from utils import cwl_campaign


async def setup(monkeypatch):
    mongo = MemoryMongo()
    install_runtime(monkeypatch, mongo)
    draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
    await cwl_campaign.apply_draft(mongo, draft["token"], 11, keep_draft=True)
    states = {}

    async def insert(_mongo, state, *, ttl):
        assert ttl.total_seconds() == 600
        states[state["_id"]] = deepcopy(state)

    async def get(_mongo, key):
        return states.get(key)

    monkeypatch.setattr(ui, "insert_state", insert)
    monkeypatch.setattr(ui, "get_state", get)
    draft = await cwl_campaign.load_draft(mongo, draft["token"])
    occurrence = cwl_campaign.occurrence_id("2030-10", "signup", "main")
    return mongo, draft, occurrence, states


def test_red_skip_requires_confirmation_and_cancel_does_not_skip(monkeypatch):
    async def scenario():
        mongo, draft, occurrence, states = await setup(monkeypatch)
        ctx = modal_context()
        overview = await ui.panel(draft, mongo=mongo)
        skip = next(node for node in nodes(overview) if node.get("label") == "Skip this message")
        assert skip["style"] == hikari.ButtonStyle.DANGER
        before = deepcopy(mongo.cwl_pending_reminders.documents)
        review = await ui.skip(ctx, draft["token"] + "|" + occurrence, mongo=mongo)
        assert "Main Clan" in str(review[0].build()[0])
        yes = next(node for node in nodes(review) if node.get("label") == "Yes, skip")
        assert yes["style"] == hikari.ButtonStyle.DANGER
        assert mongo.cwl_pending_reminders.documents == before
        assert not (await cwl_campaign.load_campaign(mongo, 22, "2030-10"))["skipped"]
        cancel = next(node for node in nodes(review) if node.get("label") == "Cancel")
        await ui.tab(ctx, cancel["custom_id"].split(":", 1)[1], mongo=mongo)
        assert not (await cwl_campaign.load_campaign(mongo, 22, "2030-10"))["skipped"]
        await ui.confirm_skip(ctx, next(iter(states)), mongo=mongo)
        live = await cwl_campaign.load_campaign(mongo, 22, "2030-10")
        assert live["skipped"] == [occurrence]
        assert len(mongo.cwl_pending_reminders.documents) == len(before) - 1
        # Duplicate confirmation cannot cancel the following post.
        await ui.confirm_skip(ctx, next(iter(states)), mongo=mongo)
        assert (await cwl_campaign.load_campaign(mongo, 22, "2030-10"))["skipped"] == [occurrence]
    asyncio.run(scenario())


@pytest.mark.parametrize("change", ["expired", "permission", "owner", "guild", "schedule", "sent"])
def test_skip_confirmation_rechecks_target_and_authorization(monkeypatch, change):
    async def scenario():
        mongo, draft, occurrence, states = await setup(monkeypatch)
        ctx = modal_context()
        await ui.skip(ctx, draft["token"] + "|" + occurrence, mongo=mongo)
        key = next(iter(states))
        if change == "expired":
            states.clear()
        elif change == "permission":
            ctx.interaction.member.permissions = hikari.Permissions.MANAGE_GUILD
        elif change == "owner":
            ctx.user.id = 99
        elif change == "guild":
            ctx.interaction.guild_id = 99
        elif change == "schedule":
            await cwl_campaign.set_paused(mongo, 22, True, cycle="2030-10")
        elif change == "sent":
            await cwl_campaign.record_delivery(mongo, 22, "2030-10", {"occurrence_id": occurrence, "status": "sent"})
        await ui.confirm_skip(ctx, key, mongo=mongo)
        assert not (await cwl_campaign.load_campaign(mongo, 22, "2030-10"))["skipped"]
    asyncio.run(scenario())
