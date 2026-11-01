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
                cursor=1, next_at=503
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
