import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from utils import cwl_campaign, cwl_publishing as posts


def fixtures(monkeypatch):
    draft = {"_id": "draft", "guild_id": 100, "user_id": 200, "cycle": "2026-09", "updated_at": "today", "campaign": cwl_campaign.default_campaign()}
    message = SimpleNamespace(author=SimpleNamespace(id=500), content=None, attachments=[], components=[
        hikari.impl.ContainerComponentBuilder(components=[hikari.impl.TextDisplayComponentBuilder(content="Original")])
    ])
    bot = SimpleNamespace(get_me=lambda: SimpleNamespace(id=500), rest=SimpleNamespace(
        fetch_channel=AsyncMock(return_value=SimpleNamespace(guild_id=100)),
        fetch_message=AsyncMock(return_value=message), edit_message=AsyncMock(),
    ))
    mongo = SimpleNamespace(bot_config=SimpleNamespace(update_one=AsyncMock(), delete_one=AsyncMock()))
    monkeypatch.setattr(cwl_campaign, "load_draft", AsyncMock(return_value=draft))
    monkeypatch.setattr(cwl_campaign, "load_campaign", AsyncMock(return_value={"deliveries": [{
        "occurrence_id": "2026-09|signup|main", "status": "sent", "channel_id": 300, "message_id": 400,
    }]}))
    monkeypatch.setattr(cwl_campaign, "record_delivery", AsyncMock())
    kwargs = {"guild_id": 100, "cycle": "2026-09", "occurrence_id": "2026-09|signup|main", "user_id": 200, "draft_id": "draft"}
    return draft, message, mongo, bot, kwargs


def test_reviewed_update_renders_draft_without_pinging_or_rescheduling(monkeypatch):
    async def run():
        draft, _, mongo, bot, kwargs = fixtures(monkeypatch)
        draft["campaign"]["messages"]["signup"]["variants"]["main"]["body"] = "Edited text {signup_deadline}"
        target = await posts.prepare_post_update(mongo, bot, **kwargs)
        url = await posts.update_published_post(mongo, bot, **kwargs, target=target)
        assert url == "https://discord.com/channels/100/300/400"
        args = bot.rest.edit_message.call_args
        assert args.args == (300, 400)
        assert all(args.kwargs[name] is False for name in posts.NO_MENTIONS)
        text = " ".join(getattr(node, "content", "") for node in args.kwargs["components"][0].components)
        assert "Edited text <t:" in text
        assert "{signup_deadline}" not in text
        assert args.kwargs["attachments"] == []
        cwl_campaign.record_delivery.assert_awaited_once()
        mongo.bot_config.delete_one.assert_awaited_once()
    asyncio.run(run())


@pytest.mark.parametrize("change", ["post", "draft", "owner", "guild", "author"])
def test_edit_rejects_stale_or_foreign_targets(monkeypatch, change):
    async def run():
        draft, message, mongo, bot, kwargs = fixtures(monkeypatch)
        target = await posts.prepare_post_update(mongo, bot, **kwargs)
        if change == "post":
            message.components = [hikari.impl.TextDisplayComponentBuilder(content="Someone else edited")]
        elif change == "draft":
            draft["updated_at"] = "later"
        elif change == "owner":
            kwargs["user_id"] = 201
        elif change == "guild":
            bot.rest.fetch_channel.return_value.guild_id = 101
        else:
            message.author.id = 501
        with pytest.raises(ValueError):
            await posts.update_published_post(mongo, bot, **kwargs, target=target)
        bot.rest.edit_message.assert_not_awaited()
    asyncio.run(run())


def test_busy_post_lease_never_edits_or_releases_other_editors_lease(monkeypatch):
    async def run():
        _, _, mongo, bot, kwargs = fixtures(monkeypatch)
        target = await posts.prepare_post_update(mongo, bot, **kwargs)
        mongo.bot_config.update_one.side_effect = DuplicateKeyError("busy")
        with pytest.raises(ValueError, match="Another editor"):
            await posts.update_published_post(mongo, bot, **kwargs, target=target)
        bot.rest.edit_message.assert_not_awaited()
        mongo.bot_config.delete_one.assert_not_awaited()
    asyncio.run(run())


def test_discord_failure_releases_lease_without_recording_success(monkeypatch):
    async def run():
        _, _, mongo, bot, kwargs = fixtures(monkeypatch)
        target = await posts.prepare_post_update(mongo, bot, **kwargs)
        bot.rest.edit_message.side_effect = RuntimeError("offline")
        with pytest.raises(RuntimeError, match="offline"):
            await posts.update_published_post(mongo, bot, **kwargs, target=target)
        cwl_campaign.record_delivery.assert_not_awaited()
        mongo.bot_config.delete_one.assert_awaited_once()
    asyncio.run(run())


def test_audit_and_lease_cleanup_outage_do_not_misreport_successful_discord_edit(monkeypatch):
    async def run():
        _, _, mongo, bot, kwargs = fixtures(monkeypatch)
        target = await posts.prepare_post_update(mongo, bot, **kwargs)
        cwl_campaign.record_delivery.side_effect = RuntimeError("Mongo offline")
        mongo.bot_config.delete_one.side_effect = RuntimeError("Mongo offline")
        assert await posts.update_published_post(mongo, bot, **kwargs, target=target) == "https://discord.com/channels/100/300/400"
        bot.rest.edit_message.assert_awaited_once()
    asyncio.run(run())
