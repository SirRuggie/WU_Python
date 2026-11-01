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
                indexes["member_profile_left_90d"]["expireAfterSeconds"]
                == 90 * 86400
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

            fake_bot = S(
                rest=S(fetch_members=present), get_me=lambda: S(id=int(USER))
            )
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
            AsyncMock(
                side_effect=RuntimeError("storage acknowledgement unavailable")
            ),
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
                assert not await store.consume_preview(
                    "wizard", "old", **wrong
                )
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
                {
                    "$set": {
                        "nickname_setup": {"nonce": "new", "step": "country"}
                    }
                },
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
            token = await runs.preview(
                actor_id=ACTOR, guild_id=1, rows=[item, other]
            )
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
                await db.bot_config.count_documents(
                    {"parent_id": parent["_id"]}
                )
                == 1
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
                await db.bot_config.count_documents(
                    {"parent_id": parent["_id"]}
                )
                == 1
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
                await db.bot_config.count_documents(
                    {"kind": KIND, "state": "done"}
                )
                == 20
            )
            assert not await db.bot_config.find_one({"parent_id": "old:24"})
            replacement = await runs.preview(
                actor_id=ACTOR, guild_id=1, rows=[other]
            )
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
                    actor_id=ACTOR,
                    guild_id=1,
                    nonce=replacement,
                    selected=[ACTOR],
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
                    {
                        "section": "member_profiles",
                        "parent_id": {"$exists": False},
                    }
                )
                == 20
            )
            assert await db.bot_config.find_one({"_id": "other"})
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_uncertain_receipt_missing_completion_is_retained_for_its_full_lifetime(
    monkeypatch,
):
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        from utils import member_profile_runs as module

        clock = [1_800_000_000.0]
        monkeypatch.setattr(module.time, "time", lambda: clock[0])
        client = AsyncMongoClient(URI)
        db = client["wu_receipt_fixture_" + uuid4().hex]
        try:
            await db.bot_config.insert_many(
                [
                    {
                        "_id": "uncertain",
                        "kind": "manage_web_request",
                        "section": "member_profiles",
                        "status": "uncertain",
                        "created_at": clock[0] - 600,
                    },
                    {
                        "_id": "other",
                        "kind": "manage_web_request",
                        "section": "unrelated",
                        "status": "uncertain",
                    },
                    {
                        "_id": "active",
                        "kind": "manage_web_request",
                        "section": "member_profiles",
                        "status": "running",
                    },
                ]
            )
            store = module.ProfileRuns(S(bot_config=db.bot_config))
            await store.prune()
            row = await db.bot_config.find_one({"_id": "uncertain"})
            assert row["finished_at"] == clock[0]
            finish = row["finished_at"]
            clock[0] += 100
            await store.prune()
            assert (await db.bot_config.find_one({"_id": "uncertain"}))[
                "finished_at"
            ] == finish
            clock[0] = finish + 30 * 86400 - 1
            await store.prune()
            assert await db.bot_config.find_one({"_id": "uncertain"})
            clock[0] = finish + 30 * 86400 + 1
            await store.prune()
            assert not await db.bot_config.find_one({"_id": "uncertain"})
            assert await db.bot_config.find_one({"_id": "other"})
            assert await db.bot_config.find_one({"_id": "active"})
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_real_standardize_stop_retains_inflight_and_never_resumes(monkeypatch):
    assert URI == "mongodb://127.0.0.1:27154"

    async def check():
        import time

        at = time.time()
        from utils.member_profile_runs import (
            ProfileRuns,
            KIND,
            ProfileRunStopped,
        )
        from extensions.warrior import profile_dashboard as actions
        from unittest.mock import AsyncMock

        client = AsyncMongoClient(URI)
        db = client["wu_stop_fixture_" + uuid4().hex]
        m = S(
            bot_config=db.bot_config,
            component_state=db.component_state,
            member_profiles=db.member_profiles,
        )
        runs = ProfileRuns(m)
        item = dict(
            discord_id=USER,
            name="Fixture member",
            old_nickname="Old",
            new_nickname="Name | GMT-5 🇺🇸",
            revision=1,
        )
        other = dict(
            item,
            discord_id=ACTOR,
            name="Skipped fixture",
            skip_reason="Above bot",
        )
        try:
            await MemberProfiles(m).write(
                USER,
                FIELDS,
                expected_revision=0,
                updated_by=ACTOR,
                source="staff",
            )
            token = await runs.preview(
                actor_id=ACTOR, guild_id=actions.GUILD_ID, rows=[item, other]
            )
            parent = await runs.confirm(
                actor_id=ACTOR,
                guild_id=actions.GUILD_ID,
                nonce=token,
                selected=[USER],
            )
            assert "skipped" not in parent
            await runs.advance(now=at)
            child = await db.bot_config.find_one({"parent_id": parent["_id"]})
            await db.bot_config.update_one(
                {"_id": child["_id"]}, {"$set": {"status": "running"}}
            )
            stopped = await runs.stop(
                parent["_id"], actor_id=ACTOR, guild_id=actions.GUILD_ID
            )
            assert stopped["state"] == "queued" and stopped["stop_requested"]
            monkeypatch.setattr(
                actions,
                "target_context",
                AsyncMock(
                    return_value={
                        "member": S(nickname="Old"),
                        "bot_permissions": __import__(
                            "hikari"
                        ).Permissions.MANAGE_NICKNAMES,
                    }
                ),
            )
            bot = S(rest=S(edit_member=AsyncMock()))
            with pytest.raises(ProfileRunStopped):
                await actions.apply(bot, m, child)
            bot.rest.edit_member.assert_not_awaited()
            await db.bot_config.update_one(
                {"_id": child["_id"]},
                {"$set": {"status": "done", "finished_at": at + 1}},
            )
            await runs.advance(now=at + 2)
            assert (await db.bot_config.find_one({"_id": parent["_id"]}))[
                "state"
            ] == "stopped"
            replay = await runs.confirm(
                actor_id=ACTOR,
                guild_id=actions.GUILD_ID,
                nonce=token,
                selected=[USER],
            )
            assert replay["state"] == "stopped"
            await runs.advance(now=at + 9999)
            assert (
                await db.bot_config.count_documents(
                    {"parent_id": parent["_id"]}
                )
                == 1
            )
            assert (
                await runs.stop(
                    parent["_id"], actor_id=USER, guild_id=actions.GUILD_ID
                )
            )["state"] == "stopped"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(check())


def test_stopped_run_never_starts_the_next_member(monkeypatch):
    assert URI == "mongodb://127.0.0.1:27154"

    async def check():
        import time, hikari
        from utils.member_profile_runs import ProfileRuns
        from extensions.warrior import profile_dashboard as actions

        client = AsyncMongoClient(URI)
        db = client["wu_stop_next_" + uuid4().hex]
        m = S(
            bot_config=db.bot_config,
            component_state=db.component_state,
            member_profiles=db.member_profiles,
        )
        uid2 = "345678901234567890"
        at = time.time()
        runs = ProfileRuns(m)
        try:
            for uid in [USER, uid2]:
                await MemberProfiles(m).write(
                    uid,
                    FIELDS,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="staff",
                )
            rows = [
                dict(
                    discord_id=uid,
                    name="Fixture " + uid[-2:],
                    old_nickname="Old",
                    new_nickname="Name | GMT-5 🇺🇸",
                    revision=1,
                )
                for uid in [USER, uid2]
            ]
            token = await runs.preview(
                actor_id=ACTOR, guild_id=actions.GUILD_ID, rows=rows
            )
            parent = await runs.confirm(
                actor_id=ACTOR,
                guild_id=actions.GUILD_ID,
                nonce=token,
                selected=[USER, uid2],
            )
            await runs.advance(now=at)
            first = await db.bot_config.find_one({"parent_id": parent["_id"]})
            await db.bot_config.update_one(
                {"_id": first["_id"]}, {"$set": {"status": "running"}}
            )
            await runs.stop(
                parent["_id"], actor_id=ACTOR, guild_id=actions.GUILD_ID
            )
            await db.bot_config.update_one(
                {"_id": first["_id"]},
                {"$set": {"status": "done", "finished_at": at + 1}},
            )
            await runs.advance(now=at + 2)
            await runs.advance(now=at + 20)
            next_child = await db.bot_config.find_one(
                {"_id": parent["_id"] + ":1"}
            )
            bot = S(rest=S(edit_member=AsyncMock()))
            monkeypatch.setattr(
                actions,
                "target_context",
                AsyncMock(
                    return_value={
                        "member": S(nickname="Old"),
                        "bot_permissions": hikari.Permissions.MANAGE_NICKNAMES,
                    }
                ),
            )
            if next_child:
                await actions.apply(bot, m, next_child)
            bot.rest.edit_member.assert_not_awaited()
            assert next_child is None
            assert (await db.bot_config.find_one({"_id": parent["_id"]}))[
                "state"
            ] == "stopped"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(check())


def test_cross_staff_stop_and_uncertain_receipt_survives_newer_history():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        from utils.member_profile_runs import ProfileRuns, KIND
        import time

        client = AsyncMongoClient(URI)
        db = client["wu_stop_retention_fixture_" + uuid4().hex]
        store = ProfileRuns(
            S(bot_config=db.bot_config, component_state=db.component_state)
        )
        now = time.time()
        try:
            await db.bot_config.insert_one(
                dict(
                    _id="run",
                    kind=KIND,
                    guild_id=1,
                    user_id=ACTOR,
                    state="queued",
                    items=[],
                    created_at=now,
                )
            )
            stopped = await store.stop("run", actor_id=USER, guild_id=1)
            assert (
                stopped["state"] == "stopped" and stopped["stopped_by"] == USER
            )
            stamp = stopped["finished_at"]
            await store.stop("run", actor_id=ACTOR, guild_id=1)
            unchanged = await db.bot_config.find_one({"_id": "run"})
            assert (
                unchanged["finished_at"] == stamp
                and unchanged["stopped_by"] == USER
            )
            with pytest.raises(ValueError):
                await store.stop("run", actor_id=USER, guild_id=2)
            for i in range(25):
                await db.bot_config.insert_one(
                    dict(
                        _id=f"save:{i}",
                        kind="manage_web_request",
                        section="member_profiles",
                        status="done",
                        finished_at=now - i,
                    )
                )
            await db.bot_config.insert_one(
                dict(
                    _id="uncertain",
                    kind="manage_web_request",
                    section="member_profiles",
                    status="uncertain",
                    finished_at=now - 3600,
                )
            )
            await store.prune()
            assert await db.bot_config.find_one({"_id": "uncertain"})
            await db.bot_config.update_one(
                {"_id": "uncertain"},
                {"$set": {"finished_at": now - 31 * 86400}},
            )
            await store.prune()
            assert not await db.bot_config.find_one({"_id": "uncertain"})
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_real_import_batch_preserves_saved_imported_and_concurrent_cas():
    from utils.member_timezone_import import import_nicknames

    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_import_fixture_" + uuid4().hex]
        store = MemberProfiles(
            S(
                member_profiles=db.member_profiles,
                component_state=db.component_state,
                button_store=db.button_store,
            )
        )
        ids = [str(123456789012340000 + i) for i in range(48)]
        try:
            saved = await store.write(
                ids[0],
                FIELDS,
                expected_revision=0,
                updated_by=ACTOR,
                source="staff",
            )
            imported = await store.write(
                ids[1],
                FIELDS,
                expected_revision=0,
                updated_by=ACTOR,
                source="nickname_import",
            )
            saved = await store.get(ids[0])
            imported = await store.get(ids[1])
            rows = [
                dict(discord_id=uid, nickname="N | GMT+5:45 🇳🇵") for uid in ids
            ]
            counts = await import_nicknames(store, rows, actor_id=ACTOR)
            assert counts["imported"] == 46 and counts["preserved"] == 2
            assert (
                await store.get(ids[0]) == saved
                and await store.get(ids[1]) == imported
            )
            snapshot = await store.for_members(ids)
            again = await import_nicknames(store, rows, actor_id=ACTOR)
            assert again["imported"] == 0 and again["preserved"] == 48
            assert await store.for_members(ids) == snapshot
            with pytest.raises(ProfileConflict):
                await store.write(
                    ids[2],
                    FIELDS,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="nickname_import",
                )
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_fast_tick_fallback_and_independent_claimers_execute_once(monkeypatch):
    from utils import (
        manage_web_worker as worker,
        manage_operations_runtime,
        return_bulk,
    )

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_claim_fixture_" + uuid4().hex]
        mongo = S(bot_config=db.bot_config)

        async def dispatched(*args):
            await asyncio.sleep(0.03)
            return {"message": "Fixture only"}

        calls = AsyncMock(side_effect=dispatched)
        monkeypatch.setattr(worker, "context", AsyncMock(return_value={}))
        monkeypatch.setattr(worker, "dispatch", calls)
        monkeypatch.setattr(
            manage_operations_runtime, "refresh_base_image_cache", AsyncMock()
        )
        monkeypatch.setattr(
            manage_operations_runtime, "runtime_snapshot", lambda _: {}
        )
        monkeypatch.setattr(return_bulk, "activate", AsyncMock())
        row = dict(
            _id="first",
            kind="manage_web_request",
            guild_id=worker.GUILD_ID,
            section="fwa_points",
            action="enable",
            user_id=ACTOR,
            values={},
            revision="x",
            created_at=__import__("time").time(),
            status="pending",
        )
        try:
            await db.bot_config.insert_one(row)
            await asyncio.gather(
                worker.fast_poll(None, mongo), worker.poll(None, mongo)
            )
            assert calls.await_count == 1
            await db.bot_config.insert_one(dict(row, _id="second"))
            await asyncio.gather(
                worker._process_requests(None, mongo),
                worker._process_requests(None, mongo),
            )
            assert calls.await_count == 2
            assert (await db.bot_config.find_one({"_id": "second"}))[
                "status"
            ] == "done"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_fast_run_stop_between_members_and_restart_never_replays_uncertain(
    monkeypatch,
):
    from utils import manage_web_worker as worker
    from utils.member_profile_runs import ProfileRuns
    import time

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_paced_fixture_" + uuid4().hex]
        mongo = S(bot_config=db.bot_config)
        monkeypatch.setattr(worker, "context", AsyncMock(return_value={}))
        calls = AsyncMock(return_value={"message": "Fixture only"})
        monkeypatch.setattr(worker, "dispatch", calls)
        try:
            service = ProfileRuns(mongo)
            items = [
                dict(
                    discord_id=str(123456789012340000 + i),
                    revision=1,
                    old_nickname="Old",
                    new_nickname="New",
                )
                for i in range(2)
            ]
            parent = await service.create(
                actor_id=ACTOR,
                guild_id=worker.GUILD_ID,
                request_id=str(uuid4()),
                preview=items,
                selected=[r["discord_id"] for r in items],
            )
            task = asyncio.create_task(worker.fast_poll(None, mongo))
            for _ in range(100):
                if await db.bot_config.find_one(
                    {"parent_id": parent["_id"], "status": "done"}
                ):
                    break
                await asyncio.sleep(0.01)
            else:
                raise AssertionError("First child did not finish")
            await service.stop(
                parent["_id"], actor_id=ACTOR, guild_id=worker.GUILD_ID
            )
            await task
            assert calls.await_count == 1
            assert (await db.bot_config.find_one({"_id": parent["_id"]}))[
                "state"
            ] == "stopped"
            calls.reset_mock()
            parent = await service.create(
                actor_id=ACTOR,
                guild_id=worker.GUILD_ID,
                request_id=str(uuid4()),
                preview=items,
                selected=[r["discord_id"] for r in items],
            )
            await service.advance()
            await db.bot_config.update_one(
                {"parent_id": parent["_id"]},
                {
                    "$set": {
                        "status": "running",
                        "started_at": time.time() - 301,
                    }
                },
            )
            async with asyncio.timeout(6):
                await worker.fast_poll(None, mongo)
            assert calls.await_count == 1
            assert (
                await db.bot_config.find_one({"_id": parent["_id"] + ":0"})
            )["status"] == "uncertain"
            assert (
                await db.bot_config.find_one({"_id": parent["_id"] + ":1"})
            )["status"] == "done"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_expired_lease_after_slow_preparation_never_edits():
    assert URI == "mongodb://127.0.0.1:27154"

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_profile_prepare_fixture_" + uuid4().hex]
        mongo = S(
            member_profiles=db.member_profiles,
            component_state=db.component_state,
        )
        store = MemberProfiles(mongo)
        change = AsyncMock()

        async def prepare():
            await db.component_state.update_one(
                {"_id": "member_profile_edit:" + USER},
                {
                    "$set": {
                        "lease_until": datetime.now(timezone.utc)
                        - timedelta(seconds=1)
                    }
                },
            )

        try:
            with pytest.raises(ProfileBusy, match="expired"):
                await store.commit_after(
                    USER,
                    FIELDS,
                    change=change,
                    prepare=prepare,
                    expected_revision=0,
                    updated_by=ACTOR,
                    source="staff",
                )
            change.assert_not_awaited()
            assert await store.get(USER) is None
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


def test_ready_work_partial_index_avoids_archived_manifest_scan():
    assert URI == "mongodb://127.0.0.1:27154"
    from utils.member_profile_runs import ProfileRuns

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_ready_index_fixture_" + uuid4().hex]
        store = ProfileRuns(S(bot_config=db.bot_config))
        try:
            await db.bot_config.insert_many(
                [
                    dict(_id=str(i), kind="archive", payload="x" * 100)
                    for i in range(20000)
                ]
            )
            await store.ensure_work_index()
            assert await store.ready_work() is None
            query = {
                "$or": [
                    {"kind": "manage_web_request", "status": "pending"},
                    {"kind": "member_profile_standardize", "state": "queued"},
                ]
            }
            plan = await db.command(
                "explain",
                {
                    "find": "bot_config",
                    "filter": query,
                    "hint": "management_ready_work",
                },
                verbosity="executionStats",
            )
            assert plan["executionStats"]["totalDocsExamined"] == 0
            await db.bot_config.insert_one(
                dict(
                    _id="pending", kind="manage_web_request", status="pending"
                )
            )
            assert (await store.ready_work())["_id"] == "pending"
        finally:
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())


@pytest.mark.parametrize("stop", [False, True])
def test_real_hikari_seventy_second_429_finishes_four_members_without_uncertainty(
    monkeypatch, stop
):
    """Actual Hikari bucket wait, loopback HTTP, owned Mongo; never Discord."""
    assert URI == "mongodb://127.0.0.1:27154"
    import time
    import hikari
    from aiohttp import web
    from tests.fixtures.nickname_speed import Rest, Mongo, ACTOR as STAFF, BOT
    from utils import manage_web_worker as worker, dashboard_access
    from utils.member_profile_runs import ProfileRuns

    async def run():
        client = AsyncMongoClient(URI)
        db = client["wu_real_429_fixture_" + uuid4().hex]
        mongo = Mongo(db)
        calls = []
        accepted = []
        limited_until = [None]
        first_request = asyncio.Event()

        async def edit(request):
            now = time.monotonic()
            uid = request.match_info["uid"]
            body = await request.json()
            calls.append((uid, now))
            first_request.set()
            if limited_until[0] is None:
                limited_until[0] = now + (2 if stop else 70)
            remaining = limited_until[0] - now
            if remaining > 0:
                return web.json_response(
                    {
                        "message": "Fixture rate limit",
                        "retry_after": remaining,
                        "global": False,
                    },
                    status=429,
                    headers={
                        "X-RateLimit-Bucket": "fixture-nickname",
                        "X-RateLimit-Limit": "1",
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset-After": str(remaining),
                    },
                )
            accepted.append(uid)
            return web.json_response(
                dict(
                    user=dict(
                        id=uid,
                        username="Fixture",
                        discriminator="0000",
                        avatar=None,
                    ),
                    roles=[],
                    joined_at="2020-01-01T00:00:00+00:00",
                    deaf=False,
                    mute=False,
                    flags=0,
                    nick=body["nick"],
                ),
                headers={
                    "X-RateLimit-Bucket": "fixture-nickname",
                    "X-RateLimit-Limit": "100",
                    "X-RateLimit-Remaining": "99",
                    "X-RateLimit-Reset-After": "1",
                },
            )

        app = web.Application()
        app.router.add_patch("/guilds/{guild}/members/{uid}", edit)
        server = web.AppRunner(app)
        await server.setup()
        site = web.TCPSite(server, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        rest_app = hikari.impl.RESTApp(
            url=f"http://127.0.0.1:{port}", max_rate_limit=120.0
        )
        await rest_app.start()
        fake = Rest(4)
        monkeypatch.setattr(
            dashboard_access, "dashboard_allowed", AsyncMock(return_value=True)
        )
        errors = []
        original_dispatch = worker.dispatch

        async def traced_dispatch(*args, **kwargs):
            try:
                return await original_dispatch(*args, **kwargs)
            except Exception as error:
                errors.append((type(error).__name__, str(error)))
                raise

        monkeypatch.setattr(worker, "dispatch", traced_dispatch)
        try:
            async with rest_app.acquire(
                "fixture.fake.token", hikari.TokenType.BOT
            ) as real:
                fake.edit_member = real.edit_member
                bot = S(rest=fake, get_me=lambda: S(id=BOT))
                rows = []
                store = MemberProfiles(mongo)
                for i in range(4):
                    uid = str(123456789012340000 + i)
                    await store.write(
                        uid,
                        FIELDS,
                        expected_revision=0,
                        updated_by=str(STAFF),
                        source="staff",
                    )
                    rows.append(
                        dict(
                            discord_id=uid,
                            old_nickname=f"Member {i} | EST 🇺🇸",
                            new_nickname=f"Member {i} | GMT-5 🇺🇸",
                            revision=1,
                        )
                    )
                parent = await ProfileRuns(mongo).create(
                    actor_id=str(STAFF),
                    guild_id=worker.GUILD_ID,
                    request_id=str(uuid4()),
                    preview=rows,
                    selected=[r["discord_id"] for r in rows],
                )
                started = time.monotonic()
                task = asyncio.create_task(worker.fast_poll(bot, mongo))
                if stop:
                    await asyncio.wait_for(first_request.wait(), 5)
                    await ProfileRuns(mongo).stop(
                        parent["_id"],
                        actor_id=str(STAFF),
                        guild_id=worker.GUILD_ID,
                    )
                await asyncio.wait_for(task, timeout=115)
                elapsed = time.monotonic() - started
                current = await db.bot_config.find_one({"_id": parent["_id"]})
                children = await db.bot_config.find(
                    {"parent_id": parent["_id"]}
                ).to_list(length=10)
                expected = 1 if stop else 4
                assert current["state"] == ("stopped" if stop else "done")
                assert [r["status"] for r in children] == [
                    "done"
                ] * expected, errors
                assert (
                    len(calls) == expected + 1
                    and len(set(accepted)) == expected
                    and len(accepted) == expected
                )
                assert (2 if stop else 70) <= elapsed < 110
                assert calls[1][1] - calls[0][1] >= (1.9 if stop else 69)
                assert [
                    (await store.get(r["discord_id"]))["revision"]
                    for r in rows
                ] == ([2, 1, 1, 1] if stop else [2] * 4)
                print(
                    f"REAL_HIKARI_429 elapsed={elapsed:.3f}s requests={len(calls)} confirmed={len(accepted)} uncertain=0"
                )
        finally:
            await rest_app.close()
            await server.cleanup()
            await client.drop_database(db.name)
            await client.close()

    asyncio.run(run())
