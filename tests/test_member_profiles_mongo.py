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
            from extensions.warrior import profile_membership

            async def present(guild):
                yield S(id=int(USER))

            fake_bot = S(rest=S(fetch_members=present), get_me=lambda: S(id=int(USER)))
            await profile_membership.reconcile(fake_bot, mongo)
            await profile_membership.reconcile(fake_bot, mongo)
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
        ctx = S(
            user=S(id=int(ACTOR)),
            respond=AsyncMock(),
            interaction=S(edit_initial_response=AsyncMock()),
        )
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
            await ui.save(ctx, {"_id": "wizard"}, c, mongo, state, bot)
            assert ctx.respond.await_args.args[0].startswith(
                "Nickname changed in Discord; profile save not confirmed"
            )
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
            for wrong in (
                dict(guild_id=11, discord_id=USER, actor_id=ACTOR),
                dict(guild_id=10, discord_id=ACTOR, actor_id=ACTOR),
                dict(guild_id=10, discord_id=USER, actor_id=USER),
            ):
                assert not await store.consume_preview("wizard", "old", **wrong)
                assert (await db.component_state.find_one({"_id": "wizard"}))[
                    "nickname_setup"
                ]["step"] == "preview"
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
