"""Role bulk manifests reuse the existing durable member-run owner and lane."""

import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from utils.member_profile_runs import ProfileRuns, ProfileRunStopped, role_manifest

USER = "123456789012345678"
ACTOR = "234567890123456789"
ROLE = "345678901234567890"
ITEM = dict(
    discord_id=USER,
    role_id=ROLE,
    operation="add",
    expected_role_ids=[],
    bot=False,
    protected=False,
    revision=0,
)


@pytest.fixture(autouse=True)
def isolate_retention(monkeypatch):
    # Scheduling is covered here; retention and restart persistence use owned Mongo.
    monkeypatch.setattr(ProfileRuns, "prune", AsyncMock())


def test_exact_reviewed_selection_has_the_count_of_sent_ids():
    assert role_manifest([ITEM], [USER]) == [ITEM]
    for selected in ([USER, USER], [], [ACTOR]):
        with pytest.raises(ValueError):
            role_manifest([ITEM], selected)


@pytest.mark.parametrize(
    "patch",
    [
        {"bot": True},
        {"operation": "send"},
        {"role_id": "bad"},
        {"expected_role_ids": [ROLE, ROLE]},
    ],
)
def test_invalid_or_bot_review_never_becomes_work(patch):
    with pytest.raises(ValueError):
        role_manifest([dict(ITEM, **patch)], [USER])


def test_mixed_role_or_action_is_not_one_confirmation():
    with pytest.raises(ValueError):
        role_manifest(
            [ITEM, dict(ITEM, discord_id=ACTOR, operation="remove")], [USER, ACTOR]
        )


def test_role_child_materialization_reuses_one_fresh_durable_request():
    async def run():
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            run_type="roles",
            state="queued",
            cursor=0,
            items=[ITEM],
            user_id=ACTOR,
            guild_id=1,
            created_at=10,
        )
        coll = S(find_one=AsyncMock(side_effect=[parent, None]), insert_one=AsyncMock())
        await ProfileRuns(S(bot_config=coll)).advance(now=10000)
        child = coll.insert_one.await_args.args[0]
        assert (child["section"], child["action"], child["values"]) == (
            "roles",
            "bulk_one",
            ITEM,
        )
        assert child["created_at"] == 10000 and child["expires_at"] == 10900

    asyncio.run(run())


@pytest.mark.parametrize(
    "status", ["done", "failed", "uncertain", "running", "pending"]
)
def test_role_child_is_never_replayed_after_restart(status):
    async def run():
        parent = dict(
            _id="run",
            run_type="roles",
            state="queued",
            cursor=0,
            items=[ITEM],
            user_id=ACTOR,
            guild_id=1,
        )
        coll = S(
            find_one=AsyncMock(side_effect=[parent, dict(_id="run:0", status=status)]),
            insert_one=AsyncMock(),
            update_one=AsyncMock(),
        )
        await ProfileRuns(S(bot_config=coll)).advance(now=500)
        coll.insert_one.assert_not_awaited()
        if status in ("done", "failed", "uncertain"):
            assert coll.update_one.await_args.args[1]["$set"]["next_at"] == 503
        else:
            coll.update_one.assert_not_awaited()

    asyncio.run(run())


def test_stop_before_later_role_write_is_checked_without_loading_all_receipts():
    async def run():
        parent = dict(
            _id="run",
            run_type="roles",
            state="queued",
            stop_requested=True,
            cursor=0,
            items=[ITEM],
            user_id=ACTOR,
            guild_id=1,
        )
        coll = S(find_one=AsyncMock(return_value=parent))
        with pytest.raises(ProfileRunStopped):
            await ProfileRuns(S(bot_config=coll)).reviewed_child(
                dict(
                    _id="run:0", parent_id="run", values=ITEM, user_id=ACTOR, guild_id=1
                ),
                run_type="roles",
            )
        assert coll.find_one.await_count == 1

    asyncio.run(run())


def test_wrong_preview_type_is_not_consumed_by_nickname_endpoint():
    async def run():
        coll = S(
            find_one=AsyncMock(return_value=dict(run_type="roles")),
            update_one=AsyncMock(),
        )
        with pytest.raises(ValueError):
            await ProfileRuns(S(bot_config=S(), component_state=coll)).confirm(
                actor_id=ACTOR, guild_id=1, nonce="token", selected=[USER]
            )
        coll.update_one.assert_not_awaited()

    asyncio.run(run())


def test_protected_role_cannot_be_created_without_confirmation():
    from uuid import uuid4

    async def run():
        service = ProfileRuns(S(bot_config=S()))
        with pytest.raises(ValueError, match="Confirm this protected role"):
            await service.create(
                actor_id=ACTOR,
                guild_id=1,
                request_id=str(uuid4()),
                preview=[dict(ITEM, protected=True)],
                selected=[USER],
                run_type="roles",
            )

    asyncio.run(run())


def test_role_and_nickname_status_scopes_cannot_cross():
    async def run():
        coll = S(find_one=AsyncMock(return_value=None))
        owner = ProfileRuns(S(bot_config=coll))
        with pytest.raises(ValueError):
            await owner.get("role-run", guild_id=1)
        assert coll.find_one.await_args.args[0]["run_type"] == {"$ne": "roles"}
        with pytest.raises(ValueError):
            await owner.get("role-run", guild_id=1, run_type="roles")
        assert coll.find_one.await_args.args[0]["run_type"] == "roles"

    asyncio.run(run())
