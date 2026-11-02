import asyncio
from copy import deepcopy
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from utils.member_profile_runs import ProfileRuns, selected_manifest

UID = "123456789012345678"
ACTOR = "234567890123456789"
ITEM = dict(
    discord_id=UID,
    old_nickname="Old | EST 🇺🇸",
    new_nickname="New | GMT-5 🇺🇸",
    revision=3,
)


def test_unticked_and_unmanageable_never_become_work():
    skipped = dict(ITEM, discord_id=ACTOR, skip_reason="Above bot")
    assert selected_manifest([ITEM, skipped], [UID]) == [ITEM]
    assert selected_manifest([ITEM, dict(ITEM, discord_id=ACTOR)], [UID]) == [ITEM]
    with pytest.raises(ValueError):
        selected_manifest([ITEM, skipped], [ACTOR])
    with pytest.raises(ValueError):
        selected_manifest([ITEM], [UID, UID])
    with pytest.raises(ValueError):
        selected_manifest([ITEM], ["345678901234567890"])


@pytest.mark.parametrize(
    "status", ["done", "failed", "uncertain", "running", "pending"]
)
def test_restart_never_recreates_or_resets_a_child(status):
    async def run():
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            state="queued",
            cursor=0,
            items=[ITEM],
            user_id=ACTOR,
            guild_id=1,
        )
        coll = S(
            find_one=AsyncMock(side_effect=[parent, dict(_id="run:0", status=status)]),
            update_one=AsyncMock(),
            insert_one=AsyncMock(),
        )
        await ProfileRuns(S(bot_config=coll)).advance(now=500)
        coll.insert_one.assert_not_awaited()
        if status in ("done", "failed", "uncertain"):
            assert coll.update_one.await_args.args[1]["$set"] == dict(
                cursor=1, next_at=503, state="done", finished_at=500
            )
        else:
            coll.update_one.assert_not_awaited()

    asyncio.run(run())


def test_late_materialization_has_fresh_expiry_and_exact_reviewed_payload():
    async def run():
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            state="queued",
            cursor=0,
            items=[deepcopy(ITEM)],
            user_id=ACTOR,
            guild_id=1,
            created_at=10,
        )
        coll = S(find_one=AsyncMock(side_effect=[parent, None]), insert_one=AsyncMock())
        await ProfileRuns(S(bot_config=coll)).advance(now=10000)
        child = coll.insert_one.await_args.args[0]
        assert child["created_at"] == 10000 and child["expires_at"] == 10900
        assert child["values"] == ITEM and child["status"] == "pending"

    asyncio.run(run())


def test_pace_does_not_release_next_member_early():
    async def run():
        coll = S(
            find_one=AsyncMock(return_value=dict(next_at=501)), insert_one=AsyncMock()
        )
        await ProfileRuns(S(bot_config=coll)).advance(now=500)
        assert coll.find_one.await_count == 1
        coll.insert_one.assert_not_awaited()

    asyncio.run(run())


@pytest.fixture(autouse=True)
def isolated_pruning(monkeypatch):
    # These cases exercise scheduling; retention is covered against real Mongo.
    monkeypatch.setattr(ProfileRuns, "prune", AsyncMock())


@pytest.mark.parametrize("running", [False, True])
def test_stop_barrier_prevents_materializing_another_child(running):
    async def check():
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            state="queued",
            stop_requested=True,
            cursor=0,
            items=[ITEM],
            next_at=9999,
        )
        coll = S(
            find_one=AsyncMock(
                side_effect=[parent, {"status": "running"} if running else None]
            ),
            update_many=AsyncMock(),
            update_one=AsyncMock(),
            insert_one=AsyncMock(),
        )
        await ProfileRuns(S(bot_config=coll)).advance(now=500)
        coll.insert_one.assert_not_awaited()
        assert coll.update_many.call_args.args[0]["status"] == "pending"
        if running:
            coll.update_one.assert_not_awaited()
        else:
            assert coll.update_one.call_args.args[1]["$set"]["state"] == "stopped"

    asyncio.run(check())


@pytest.mark.parametrize("run_type", ["profiles", "roles"])
def test_new_run_inherits_shared_lane_backoff(monkeypatch, run_type):
    from uuid import uuid4

    async def run():
        until = 12345678900.0
        coll = S(
            create_index=AsyncMock(),
            find_one=AsyncMock(side_effect=[None, None, {"retry_not_before": until}]),
            insert_one=AsyncMock(),
        )
        owner = ProfileRuns(S(bot_config=coll))
        monkeypatch.setattr(owner, "prune", AsyncMock())
        item = (
            ITEM
            if run_type == "profiles"
            else dict(
                discord_id=UID,
                role_id="345678901234567890",
                operation="add",
                expected_role_ids=[],
                bot=False,
                protected=False,
                revision=0,
            )
        )
        parent = await owner.create(
            actor_id=ACTOR,
            guild_id=1,
            request_id=str(uuid4()),
            preview=[item],
            selected=[UID],
            run_type=run_type,
        )
        assert parent["next_at"] == until
        assert coll.insert_one.await_args.args[0]["next_at"] == until
        query = coll.find_one.await_args.args[0]
        assert query["guild_id"] == 1 and query["section"] == {
            "$in": ["member_profiles", "roles"]
        }
        assert coll.find_one.await_args.kwargs["hint"] == "member_change_lane_backoff"

    asyncio.run(run())
