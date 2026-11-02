"""Actual publishing service through the queue worker, with fake Discord only."""

import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest

from test_cwl_dashboard_integration import MemoryMongo
from test_cwl_post_update_store import Collection
from utils import cwl_campaign as campaign, cwl_web_bridge as bridge
from utils.cwl_post_updates import create_review, PostUpdateWorker

GUILD, USER, CYCLE = 100, 200, "2026-11"
COPY = {
    "title": "New roster title",
    "body": "New body @everyone <@&999>",
    "buttons": [
        {
            "label": "My tasks",
            "url": "https://dash.warriorsunited.cc/tasks",
            "emoji": "✅",
        }
    ],
}


def fixture():
    mongo = MemoryMongo()
    mongo.bot_config = Collection()
    template = campaign.default_campaign()
    template["messages"]["roster"]["variants"]["main"].update(
        role_ids=[999], media_url="https://static.example/template-different.png"
    )
    mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] = {
        "_id": campaign.cycle_id(GUILD, CYCLE),
        "kind": "cwl_campaign_cycle",
        "guild_id": GUILD,
        "cycle": CYCLE,
        "activated": True,
        "revision": 4,
        "campaign": template,
        "updated_at": "2026-11-01T00:00:00+00:00",
        "deliveries": [
            {
                "status": "sent",
                "occurrence_id": CYCLE + "|roster|main",
                "channel_id": 300,
                "message_id": 400,
            }
        ],
        "sent_occurrences": [CYCLE + "|roster|main"],
    }
    message = NS(
        author=NS(id=500),
        content="Existing outer text",
        attachments=[
            NS(id=600, filename="observed.png", url="https://cdn.example/observed.png")
        ],
        components=[
            hikari.impl.ContainerComponentBuilder(
                components=[
                    hikari.impl.TextDisplayComponentBuilder(content="<@&888>"),
                    hikari.impl.SeparatorComponentBuilder(divider=True),
                    hikari.impl.TextDisplayComponentBuilder(
                        content="## Original live title"
                    ),
                    hikari.impl.SeparatorComponentBuilder(divider=True),
                    hikari.impl.TextDisplayComponentBuilder(
                        content="Original live text"
                    ),
                    hikari.impl.MediaGalleryComponentBuilder(
                        items=[
                            hikari.impl.MediaGalleryItemBuilder(
                                media="attachment://observed.png",
                                description="Observed image",
                                spoiler=True,
                            )
                        ]
                    ),
                    hikari.impl.MessageActionRowBuilder().add_link_button(
                        "https://example.com", label="Old link"
                    ),
                ]
            )
        ],
    )
    rest = NS(
        fetch_roles=AsyncMock(
            return_value=[NS(id=888, name="Roster staff"), NS(id=999, name="Main team")]
        ),
        fetch_channel=AsyncMock(
            return_value=NS(guild_id=GUILD, name="roster-announcements")
        ),
        fetch_message=AsyncMock(return_value=message),
        edit_message=AsyncMock(),
        create_message=AsyncMock(side_effect=AssertionError("Never create a post")),
        delete_message=AsyncMock(side_effect=AssertionError("Never delete a post")),
    )
    bot = NS(get_me=lambda: NS(id=500), rest=rest)
    return mongo, bot, message


async def review(mongo, *, nonce="a" * 32):
    loaded = await campaign.load_campaign(mongo, GUILD, CYCLE)
    return await create_review(
        mongo,
        guild_id=GUILD,
        user_id=USER,
        season_id=42,
        cycle=CYCLE,
        pool="main",
        nonce=nonce,
        generation=bridge.campaign_generation(loaded),
        candidate=deepcopy(COPY),
    )


def test_real_service_edit_preserves_observed_images_buttons_and_no_mentions():
    async def run():
        mongo, bot, message = fixture()
        raw = deepcopy(mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)])
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        allowed = AsyncMock(return_value=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        assert ready["status"] == "ready"
        assert mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)] == raw
        assert ready["target"]["channel_name"] == "roster-announcements"
        assert (
            ready["draft_preview"][-1]["children"][-1]["children"][0]["emoji"] == "✅"
        )
        assert ready["live_preview"][0]["text"] == "Existing outer text"
        assert ready["draft_preview"][0]["text"] == "Existing outer text"
        queued = await worker.store.request_update(ready, future_months=False)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        done = await worker.store.collection.find_one({"_id": row["_id"]})
        assert done["status"] == "done"
        bot.rest.edit_message.assert_awaited_once()
        kwargs = bot.rest.edit_message.call_args.kwargs
        assert all(
            kwargs[key] is False
            for key in ("user_mentions", "role_mentions", "mentions_everyone")
        )
        assert kwargs["attachments"] == message.attachments
        assert kwargs["components"][0].components[0].content == "<@&888>"
        from extensions.commands.content import media_galleries, media_url

        galleries = media_galleries(kwargs["components"])
        assert media_url(galleries[0].items[0]) == "attachment://observed.png"
        assert galleries[0].items[0].is_spoiler
        assert "template-different" not in str(kwargs["components"])
        buttons = [
            child
            for child in kwargs["components"][0].components
            if int(child.type) == 1
        ][0].components
        assert [(b.label, b.url) for b in buttons] == [
            ("My tasks", COPY["buttons"][0]["url"])
        ]
        saved = await campaign.load_campaign(mongo, GUILD, CYCLE)
        assert (
            saved["campaign"]["messages"]["roster"]["variants"]["main"]["body"]
            == COPY["body"]
        )
        assert done["campaign_saved"] is True and done["recurring_saved"] is False
        assert saved["sent_occurrences"] == raw["sent_occurrences"]
        assert [
            item for item in saved["deliveries"] if item["status"] == "sent"
        ] == raw["deliveries"]
        assert (
            sum(item["status"] == "post_updated" for item in saved["deliveries"]) == 1
        )
        assert await campaign.load_draft(mongo, row["draft_id"]) is None
        await worker.store.request_update(done, future_months=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        bot.rest.edit_message.assert_awaited_once()
        bot.rest.create_message.assert_not_awaited()
        bot.rest.delete_message.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize("reason", ["stale", "deleted", "permission"])
def test_stale_deleted_or_removed_permission_never_edits_or_creates(reason):
    async def run():
        mongo, bot, message = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        allowed = AsyncMock(return_value=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        await worker.store.request_update(ready)
        if reason == "stale":
            message.components = [
                hikari.impl.TextDisplayComponentBuilder(
                    content="A different editor changed this"
                )
            ]
        elif reason == "deleted":
            bot.rest.fetch_message.side_effect = hikari.NotFoundError(
                "url", {}, b"", "gone"
            )
        else:
            allowed.return_value = False
        await worker.poll(guild_id=GUILD, authorize=allowed)
        result = await worker.store.collection.find_one({"_id": row["_id"]})
        assert result["status"] == "failed"
        if reason == "stale":
            assert result["error"] == "Post changed. Preview again."
        if reason == "deleted":
            assert "deleted" in result["error"]
            assert result["error_code"] == "deleted"
        bot.rest.edit_message.assert_not_awaited()
        bot.rest.create_message.assert_not_awaited()
        bot.rest.delete_message.assert_not_awaited()

    asyncio.run(run())


def test_worker_restart_after_unconfirmed_edit_never_replays():
    async def run():
        mongo, bot, _ = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        allowed = AsyncMock(return_value=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        await worker.store.request_update(ready)
        bot.rest.edit_message.side_effect = asyncio.CancelledError
        with pytest.raises(asyncio.CancelledError):
            await worker.poll(guild_id=GUILD, authorize=allowed)
        after = await worker.store.collection.find_one({"_id": row["_id"]})
        assert after["status"] == "updating"
        replacement = PostUpdateWorker(mongo, bot, runtime_id="process-b")
        assert await replacement.poll(guild_id=GUILD, authorize=allowed) == 0
        after = await worker.store.collection.find_one({"_id": row["_id"]})
        assert after["status"] == "uncertain"
        bot.rest.edit_message.assert_awaited_once()
        bot.rest.create_message.assert_not_awaited()

    asyncio.run(run())


def test_private_preview_draft_expires_without_affecting_normal_manage_draft():
    from datetime import datetime, timedelta, timezone

    async def run():
        mongo, _, _ = fixture()
        row = await review(mongo)
        private = await campaign.load_draft(mongo, row["draft_id"])
        assert private["purpose"] == "post_update"
        assert isinstance(private["expires_at"], datetime)
        normal = await campaign.new_draft(mongo, GUILD, USER, CYCLE)
        assert "purpose" not in normal and "expires_at" not in normal
        assert (await campaign.find_draft(mongo, GUILD, USER, CYCLE))["_id"] == normal[
            "_id"
        ]
        mongo.bot_config.documents[row["draft_id"]]["expires_at"] = datetime.now(
            timezone.utc
        ) - timedelta(seconds=1)
        assert await campaign.load_draft(mongo, row["draft_id"]) is None
        assert await campaign.load_draft(mongo, normal["_id"]) is not None
        ttl = next(
            options
            for _, options in mongo.bot_config.indexes
            if options["name"] == "cwl_post_update_scratch_expiry"
        )
        assert ttl["partialFilterExpression"] == {
            "kind": "cwl_campaign_draft",
            "purpose": "post_update",
        }

    asyncio.run(run())


def test_native_stop_invalidates_cached_worker_even_when_same_bot_starts_again(
    monkeypatch,
):
    from extensions.tasks import cwl_reminder as native

    mongo, bot, _ = fixture()
    monkeypatch.setattr(native, "mongo_client", mongo)
    monkeypatch.setattr(native, "bot_instance", bot)
    monkeypatch.setattr(native, "_post_update_worker", None)
    monkeypatch.setattr(native, "_management_stopping", False)
    monkeypatch.setattr(native, "_management_driver", None)
    monkeypatch.setattr(native, "_roster_driver", None)
    monkeypatch.setattr(native, "startup_reconciler", None)
    monkeypatch.setattr(native, "scheduler", NS(running=False))

    async def run():
        first = native._post_update_worker_for_runtime()
        assert native._post_update_worker_for_runtime() is first
        await native.on_bot_stopping(NS(app=bot))
        second = native._post_update_worker_for_runtime()
        assert second is not first and second.runtime_id != first.runtime_id

    asyncio.run(run())


def test_access_removed_during_post_fetch_is_rechecked_at_actual_edit_boundary():
    async def run():
        mongo, bot, _ = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        allowed = AsyncMock(side_effect=[True, True, False])
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        await worker.store.request_update(ready)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        result = await worker.store.collection.find_one({"_id": row["_id"]})
        assert result["status"] == "failed"
        assert allowed.await_count == 3
        bot.rest.edit_message.assert_not_awaited()
        bot.rest.create_message.assert_not_awaited()

    asyncio.run(run())


def test_post_changed_during_final_scope_check_is_not_overwritten():
    async def run():
        mongo, bot, message = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        count = 0

        async def allowed(_):
            nonlocal count
            count += 1
            if count == 3:
                message.components = [
                    hikari.impl.TextDisplayComponentBuilder(
                        content="Changed during backend scope check"
                    )
                ]
            return True

        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        await worker.store.request_update(ready)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        result = await worker.store.collection.find_one({"_id": row["_id"]})
        assert (
            result["status"] == "failed"
            and result["error"] == "Post changed. Preview again."
        )
        bot.rest.edit_message.assert_not_awaited()

    asyncio.run(run())


def test_confirmed_edit_with_concurrent_saved_copy_change_reports_warning_not_retry():
    async def run():
        mongo, bot, _ = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        allowed = AsyncMock(return_value=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        await worker.store.request_update(ready)

        async def edit_accepted(*_args, **_kwargs):
            live = mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]
            live["revision"] += 1
            live["campaign"]["messages"]["roster"]["variants"]["main"][
                "body"
            ] = "A newer saved choice"

        bot.rest.edit_message.side_effect = edit_accepted
        await worker.poll(guild_id=GUILD, authorize=allowed)
        done = await worker.store.collection.find_one({"_id": row["_id"]})
        assert done["status"] == "done" and done["campaign_saved"] is False
        assert "post was updated" in done["save_warning"]
        assert done["message_url"] == "https://discord.com/channels/100/300/400"
        assert (
            mongo.bot_config.documents[campaign.cycle_id(GUILD, CYCLE)]["campaign"][
                "messages"
            ]["roster"]["variants"]["main"]["body"]
            == "A newer saved choice"
        )
        await worker.poll(guild_id=GUILD, authorize=allowed)
        bot.rest.edit_message.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["added", "filename", "description"])
def test_attachment_only_change_during_final_scope_check_is_not_overwritten(change):
    async def run():
        mongo, bot, message = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="process-a")
        count = 0

        async def allowed(_):
            nonlocal count
            count += 1
            if count == 3:
                if change == "added":
                    message.attachments.append(
                        NS(
                            id=601,
                            filename="later.png",
                            url="https://cdn.example/later.png",
                        )
                    )
                elif change == "filename":
                    message.attachments[0].filename = "renamed.png"
                else:
                    message.attachments[0].description = (
                        "Changed attachment description"
                    )
            return True

        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        await worker.store.request_update(ready)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        result = await worker.store.collection.find_one({"_id": row["_id"]})
        assert result["status"] == "failed"
        assert result["error"] == "Post changed. Preview again."
        bot.rest.edit_message.assert_not_awaited()
        bot.rest.create_message.assert_not_awaited()

    asyncio.run(run())


def test_attachment_fingerprint_ignores_only_rotating_discord_signatures():
    from utils.cwl_publishing import _fingerprint

    _, _, message = fixture()
    attachment = message.attachments[0]
    attachment.url = "https://cdn.discordapp.com/attachments/100/600/observed.png?ex=old&is=old&hm=old&width=600"
    before = _fingerprint(message)
    attachment.url = "https://cdn.discordapp.com/attachments/100/600/observed.png?ex=new&is=new&hm=new&width=600"
    assert _fingerprint(message) == before
    attachment.url = "https://cdn.discordapp.com/attachments/100/600/observed.png?ex=new&is=new&hm=new&width=800"
    assert _fingerprint(message) != before


@pytest.mark.parametrize("stage", ["authorization", "load", "fetch", "edit"])
def test_only_an_attempted_discord_edit_may_have_an_uncertain_outcome(
    monkeypatch, stage
):
    async def run():
        mongo, bot, message = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="one")
        allowed = AsyncMock(return_value=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        assert ready["status"] == "ready"
        await worker.store.request_update(ready)
        if stage == "authorization":
            allowed.side_effect = RuntimeError("before any edit")
        elif stage == "load":
            monkeypatch.setattr(
                campaign,
                "load_campaign",
                AsyncMock(side_effect=RuntimeError("before any edit")),
            )
        elif stage == "fetch":
            bot.rest.fetch_message.side_effect = RuntimeError("before any edit")
        else:
            bot.rest.edit_message.side_effect = RuntimeError("could be accepted")
        await worker.poll(guild_id=GUILD, authorize=allowed)
        done = await worker.store.collection.find_one({"_id": row["_id"]})
        assert done["status"] == ("uncertain" if stage == "edit" else "failed")
        assert done["error"] == (
            "Not sure it updated. Check the post."
            if stage == "edit"
            else "Not updated. Preview again."
        )
        assert bot.rest.edit_message.await_count == int(stage == "edit")

    asyncio.run(run())


def test_real_preview_resolves_role_names_and_never_displays_role_ids():
    async def run():
        import json

        mongo, bot, _ = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="one")
        await worker.poll(guild_id=GUILD, authorize=AsyncMock(return_value=True))
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        visible = json.dumps([ready["live_preview"], ready["draft_preview"]])
        assert "@Roster staff" in visible and "@Main team" in visible
        assert "888" not in visible and "999" not in visible
        assert ready["has_changes"] is True

    asyncio.run(run())


def test_gallery_before_title_keeps_its_exact_original_position():
    async def run():
        mongo, bot, message = fixture()
        children = list(message.components[0].components)
        gallery = children.pop(5)
        children.insert(2, gallery)
        message.components = [
            hikari.impl.ContainerComponentBuilder(components=children)
        ]
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="one")
        allowed = AsyncMock(return_value=True)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        assert ready["status"] == "ready"
        await worker.store.request_update(ready)
        await worker.poll(guild_id=GUILD, authorize=allowed)
        rendered = bot.rest.edit_message.call_args.kwargs["components"][0].components
        assert [int(node.type) for node in rendered] == [
            int(node.type) for node in children
        ]
        assert int(rendered[2].type) == 12
        assert rendered[2].items[0].media == gallery.items[0].media

    asyncio.run(run())


def test_identical_proposal_has_no_changes_and_cannot_queue_an_edit():
    from utils.cwl_post_update_store import PostUpdateConflict

    async def run():
        mongo, bot, _ = fixture()
        loaded = await campaign.load_campaign(mongo, GUILD, CYCLE)
        row = await create_review(
            mongo,
            guild_id=GUILD,
            user_id=USER,
            season_id="42",
            cycle=CYCLE,
            pool="main",
            nonce="a" * 32,
            generation=bridge.campaign_generation(loaded),
            candidate={
                "title": "Original live title",
                "body": "Original live text",
                "buttons": [{"label": "Old link", "url": "https://example.com"}],
            },
        )
        worker = PostUpdateWorker(mongo, bot, runtime_id="one")
        await worker.poll(guild_id=GUILD, authorize=AsyncMock(return_value=True))
        ready = await worker.store.collection.find_one({"_id": row["_id"]})
        assert ready["status"] == "ready" and ready["has_changes"] is False
        with pytest.raises(PostUpdateConflict, match="No changes"):
            await worker.store.request_update(ready)
        bot.rest.edit_message.assert_not_awaited()

    asyncio.run(run())


def test_authorization_member_404_is_access_changed_not_deleted_post():
    async def run():
        mongo, bot, _ = fixture()
        row = await review(mongo)
        worker = PostUpdateWorker(mongo, bot, runtime_id="one")
        error = hikari.NotFoundError(
            url="https://discord.invalid/member",
            headers={},
            raw_body=b"",
            message="missing member",
        )
        await worker.poll(guild_id=GUILD, authorize=AsyncMock(side_effect=error))
        failed = await worker.store.collection.find_one({"_id": row["_id"]})
        assert failed["status"] == "failed"
        assert "access" in failed["error"] and "deleted" not in failed["error"]
        bot.rest.edit_message.assert_not_awaited()

    asyncio.run(run())
