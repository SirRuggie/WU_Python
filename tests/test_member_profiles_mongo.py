"""Opt-in dedicated local fixture; never uses the default Mongo endpoint."""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as S
from uuid import uuid4
from unittest.mock import AsyncMock
import pytest
from pymongo import AsyncMongoClient
from utils.member_profiles import MemberProfiles, ProfileConflict
from utils.member_profile_leases import editing, ProfileBusy

URI = os.environ.get("WU_ACTIVITY_TEST_MONGO_URI")
pytestmark = pytest.mark.skipif(
    not URI, reason="dedicated local profile Mongo fixture not provided"
)
USER = "123456789012345678"
ACTOR = "234567890123456789"
FIELDS = {"zone_id": "gmt-5", "country": "US", "name_source_tag": None}


def test_real_profile_lease_concurrency_failure_cas_and_ttl():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_profile_fixture_" + uuid4().hex]
        mongo = S(
            member_profiles=db.member_profiles,
            component_state=db.component_state,
            button_store=db.button_store,
        )
        store = MemberProfiles(mongo)
        try:
            await store.ensure_indexes()
            indexes = await db.member_profiles.index_information()
            assert (
                indexes["member_profile_left_90d"]["expireAfterSeconds"] == 90 * 86400
            )
            async with editing(mongo, USER):
                with pytest.raises(ProfileBusy):
                    await store.write(
                        USER,
                        FIELDS,
                        expected_revision=0,
                        updated_by=ACTOR,
                        source="staff",
                    )
            change = AsyncMock(side_effect=RuntimeError("Discord failed"))
            with pytest.raises(RuntimeError):
                await store.commit_after(
                    USER,
                    FIELDS,
                    change=change,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="warrior",
                )
            assert await store.get(USER) is None
            change.side_effect = None
            await store.commit_after(
                USER,
                FIELDS,
                change=change,
                expected_revision=0,
                updated_by=ACTOR,
                source="warrior",
            )
            current = await store.get(USER)
            assert current["revision"] == 1
            change.reset_mock()
            with pytest.raises(ProfileConflict):
                await store.commit_after(
                    USER,
                    FIELDS,
                    change=change,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="warrior",
                )
            change.assert_not_awaited()
            await store.membership(
                USER, left_at=datetime.now(timezone.utc) - timedelta(days=91)
            )
            for _ in range(60):
                if await store.get(USER) is None:
                    break
                await asyncio.sleep(0.2)
            assert await store.get(USER) is None
            assert await db.component_state.count_documents({}) == 1
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_consumed_preview_survives_restart_after_discord_success_storage_failure(
    monkeypatch,
):
    assert URI == "mongodb://127.0.0.1:27154"
    from extensions.warrior import nickname_setup as ui, core
    from extensions.commands import warrior
    from tests.test_warrior_setup import context

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_profile_receipt_fixture_" + uuid4().hex]
        mongo = S(
            member_profiles=db.member_profiles,
            component_state=db.component_state,
            button_store=db.button_store,
        )
        c = context()
        c["member"].id = int(USER)
        monkeypatch.setattr(ui, "GUILD_ID", 10)
        monkeypatch.setattr(core, "context", AsyncMock(return_value=c))
        monkeypatch.setattr(warrior, "home", AsyncMock(return_value=[]))
        monkeypatch.setattr(
            MemberProfiles,
            "_write",
            AsyncMock(side_effect=RuntimeError("storage acknowledgement unavailable")),
        )
        bot = S(rest=S(edit_member=AsyncMock()))
        ctx = S(user=S(id=int(ACTOR)), interaction=S(edit_initial_response=AsyncMock()))
        state = {
            "nonce": "preview",
            "step": "preview",
            "name": "Main",
            "zone_id": "gmt",
            "country": "GB",
            "profile_revision": 0,
        }
        await db.component_state.insert_one(
            {
                "_id": "wizard",
                "type": "warrior_setup",
                "guild_id": 10,
                "user_id": int(USER),
                "recruiter_id": int(ACTOR),
                "nickname_setup": dict(state),
            }
        )
        try:
            with pytest.raises(core.SetupError, match="profile save was not confirmed"):
                await ui.save(ctx, {"_id": "wizard"}, c, mongo, state, bot)
            assert await db.member_profiles.count_documents({}) == 0
            # A fresh wrapper represents a restarted worker reading the durable receipt.
            restarted = S(
                member_profiles=db.member_profiles,
                component_state=db.component_state,
                button_store=db.button_store,
            )
            with pytest.raises(core.SetupError, match="already used"):
                await ui.save(ctx, {"_id": "wizard"}, c, restarted, state, bot)
            bot.rest.edit_member.assert_awaited_once()
            receipt = await db.component_state.find_one({"_id": "wizard"})
            assert receipt["nickname_setup"]["step"] == "needs_attention"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_receipt_nonce_cas_preserves_newer_drafts(monkeypatch):
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_profile_nonce_fixture_" + uuid4().hex]
        mongo = S(
            member_profiles=db.member_profiles,
            component_state=db.component_state,
            button_store=db.button_store,
        )
        store = MemberProfiles(mongo)
        try:
            await db.component_state.insert_one(
                {
                    "_id": "wizard",
                    "type": "warrior_setup",
                    "guild_id": 10,
                    "user_id": int(USER),
                    "recruiter_id": int(ACTOR),
                    "nickname_setup": {"nonce": "old", "step": "preview"},
                }
            )
            assert await store.consume_preview(
                "wizard", "old", guild_id=10, discord_id=USER, actor_id=ACTOR
            )
            assert not await store.consume_preview(
                "wizard", "old", guild_id=10, discord_id=USER, actor_id=ACTOR
            )
            await db.component_state.update_one(
                {"_id": "wizard"},
                {"$set": {"nickname_setup": {"nonce": "new", "step": "country"}}},
            )
            assert not await store.finish_preview("wizard", "old", "saved")
            row = await db.component_state.find_one({"_id": "wizard"})
            assert row["nickname_setup"] == {"nonce": "new", "step": "country"}
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_real_standardize_selection_restart_pacing_and_bounded_receipts():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        from utils.member_profile_runs import ProfileRuns, KIND
        import time

        client = AsyncMongoClient(URI)
        db = client["wu_runs_fixture_" + uuid4().hex]
        mongo = S(bot_config=db.bot_config, component_state=db.component_state)
        runs = ProfileRuns(mongo)
        item = dict(
            discord_id=USER,
            old_nickname="Old",
            new_nickname="Name | GMT-5 🇺🇸",
            revision=1,
        )
        other = dict(item, discord_id=ACTOR)
        try:
            token = await runs.preview(actor_id=ACTOR, guild_id=1, rows=[item, other])
            parent = await runs.confirm(
                actor_id=ACTOR, guild_id=1, nonce=token, selected=[USER]
            )
            assert parent["items"] == [item]
            assert (
                await runs.confirm(
                    actor_id=ACTOR, guild_id=1, nonce=token, selected=[USER]
                )
            )["_id"] == parent["_id"]
            with pytest.raises(ValueError):
                await runs.confirm(
                    actor_id=ACTOR, guild_id=1, nonce=token, selected=[ACTOR]
                )
            await runs.advance()
            child = await db.bot_config.find_one({"parent_id": parent["_id"]})
            assert child["values"] == item
            assert (
                await db.bot_config.count_documents({"parent_id": parent["_id"]}) == 1
            )
            # An accepted-but-unconfirmed rename is never made pending again after restart.
            await db.bot_config.update_one(
                {"_id": child["_id"]}, {"$set": {"status": "uncertain"}}
            )
            restarted = ProfileRuns(mongo)
            await restarted.advance(now=time.time() + 4)
            assert (await db.bot_config.find_one({"_id": child["_id"]}))[
                "status"
            ] == "uncertain"
            await restarted.advance(now=time.time() + 8)
            assert (await db.bot_config.find_one({"_id": parent["_id"]}))[
                "state"
            ] == "done"
            assert (
                await db.bot_config.count_documents({"parent_id": parent["_id"]}) == 1
            )
            # Retention removes matching terminal children, never active children.
            for index in range(25):
                key = "old:" + str(index)
                await db.bot_config.insert_one(
                    dict(
                        _id=key,
                        kind=KIND,
                        state="done",
                        finished_at=time.time() - index,
                        created_at=time.time() - index,
                    )
                )
                await db.bot_config.insert_one(
                    dict(
                        _id=key + ":0",
                        kind="manage_web_request",
                        parent_id=key,
                        status="done",
                    )
                )
            await restarted.prune()
            assert (
                await db.bot_config.count_documents({"kind": KIND, "state": "done"})
                == 20
            )
            assert not await db.bot_config.find_one({"parent_id": "old:24"})
            replacement = await runs.preview(actor_id=ACTOR, guild_id=1, rows=[other])
            with pytest.raises(ValueError):
                await runs.confirm(
                    actor_id=ACTOR, guild_id=1, nonce=token, selected=[USER]
                )
            assert replacement != token
            # Pruning a completed/uncertain run must not make its old confirmation reusable.
            last = await runs.confirm(
                actor_id=ACTOR, guild_id=1, nonce=replacement, selected=[ACTOR]
            )
            await db.bot_config.delete_one({"_id": last["_id"]})
            with pytest.raises(ValueError, match="already used"):
                await runs.confirm(
                    actor_id=ACTOR, guild_id=1, nonce=replacement, selected=[ACTOR]
                )
            # Standalone save/import receipts are bounded without touching other sections.
            for index in range(25):
                await db.bot_config.insert_one(
                    dict(
                        _id="save:" + str(index),
                        kind="manage_web_request",
                        section="member_profiles",
                        status="done",
                        finished_at=time.time() - index,
                    )
                )
            await db.bot_config.insert_one(
                dict(
                    _id="other",
                    kind="manage_web_request",
                    section="clans",
                    status="done",
                    finished_at=0,
                )
            )
            await runs.prune()
            assert (
                await db.bot_config.count_documents(
                    {"section": "member_profiles", "parent_id": {"$exists": False}}
                )
                == 20
            )
            assert await db.bot_config.find_one({"_id": "other"})
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
