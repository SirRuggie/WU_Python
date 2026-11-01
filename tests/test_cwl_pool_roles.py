"""Durable role work uses fake Discord only; signup transactions remain independent."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from cwl_web.store import Store
from utils import cwl_pool_roles as roles
from extensions.tasks import cwl_pool_roles as worker

USER = "111111111111111111"
OTHER = "222222222222222222"
ROLE = "333333333333333333"
BOT = 888888888888888888
TOP = 999999999999999999


@pytest.fixture
def store(tmp_path):
    value = Store(str(tmp_path / "roles.sqlite"))
    with value.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES (1,'Current')")
        db.execute("UPDATE member_season SET season_id=1 WHERE id=1")
    return value


def signup(store, tag="P", uid=USER, pool="main"):
    with store.tx() as db:
        db.execute(
            "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) "
            "VALUES (1,?,?,?,0,'Member',16)",
            (tag, uid, pool),
        )


def save(store, pool="main", role=ROLE, now=None):
    with store.tx() as db:
        current = next(r for r in roles.snapshot(db)["pools"] if r["pool"] == pool)
        return roles.save(
            db,
            pool,
            role,
            current["revision"],
            current["member_basis"],
            "staff",
            now=now,
        )


def claim(store, now=None):
    with store.role_tx() as db:
        db.execute("UPDATE cwl_pool_role_clock SET next_at=0")
        return roles.claim(db, now=now)


def send_for(store):
    async def send(action, **body):
        with store.role_tx() as db:
            if action == "claim":
                return {"job": roles.claim(db)}
            args = (db, body.pop("id"), body.pop("lease_token"), body.pop("generation"))
            return (
                roles.validate(*args) | {"role_allowed": True}
                if action == "validate"
                else roles.finish(*args, **body)
            )

    return send


def bot_fixture():
    role = NS(id=int(ROLE), position=1, permissions=0, is_managed=False)
    top = NS(id=TOP, position=100, permissions=1 << 28, is_managed=False)
    everyone = NS(id=roles.GUILD_ID, position=0, permissions=0, is_managed=False)
    members = {
        USER: NS(id=int(USER), role_ids=[]),
        OTHER: NS(id=int(OTHER), role_ids=[]),
    }
    own = NS(id=BOT, role_ids=[TOP])

    async def member(guild, uid):
        assert guild == roles.GUILD_ID
        return own if int(uid) == BOT else members[str(uid)]

    async def add(guild, uid, rid, **kw):
        assert guild == roles.GUILD_ID
        members[str(uid)].role_ids.append(rid)

    async def remove(guild, uid, rid, **kw):
        assert guild == roles.GUILD_ID
        members[str(uid)].role_ids.remove(rid)

    rest = NS(
        fetch_roles=AsyncMock(return_value=[everyone, top, role]),
        fetch_member=AsyncMock(side_effect=member),
        add_role_to_member=AsyncMock(side_effect=add),
        remove_role_from_member=AsyncMock(side_effect=remove),
    )
    return NS(rest=rest, get_me=lambda: NS(id=BOT)), members, role, top


def test_blank_on_signup_cancel_staff_update_startup_and_expiry_is_quiet(store):
    signup(store)
    with store.tx() as db:
        db.execute("UPDATE signups SET pool='lazy' WHERE tag='P'")
        db.execute("DELETE FROM signups")
        assert roles.claim(db, now=datetime(2030, 1, 16, tzinfo=timezone.utc)) is None
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_audit").fetchone()[0] == 0

    async def run():
        bot, _, _, _ = bot_fixture()
        await worker.poll_once(bot, send=send_for(store))
        bot.rest.fetch_roles.assert_not_awaited()
        bot.rest.add_role_to_member.assert_not_awaited()
        bot.rest.remove_role_from_member.assert_not_awaited()

    asyncio.run(run())


def test_save_membership_basis_and_revision_are_atomic(store):
    signup(store)
    with store.tx() as db:
        old = next(r for r in roles.snapshot(db)["pools"] if r["pool"] == "main")
    signup(store, "Q", OTHER)
    with store.tx() as db:
        with pytest.raises(roles.Conflict):
            roles.save(db, "main", ROLE, old["revision"], old["member_basis"], "staff")
        assert roles.snapshot(db)["pools"][1]["role_id"] is None
    save(store)
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0] == 2
        with pytest.raises(roles.Conflict):
            roles.save(db, "main", ROLE, 0, roles.member_basis(db, "main"), "staff")


def test_last_account_cancel_resignup_and_pool_independence(store):
    save(store)
    save(store, "lazy", "444444444444444444")
    signup(store)
    signup(store, "Q")

    async def run():
        bot, members, _, _ = bot_fixture()
        await worker.process_job(bot, claim(store), send=send_for(store))
        bot.rest.add_role_to_member.assert_awaited_once()
        with store.tx() as db:
            db.execute("DELETE FROM signups WHERE tag='P'")
        assert claim(store) is None
        bot.rest.remove_role_from_member.assert_not_awaited()
        with store.tx() as db:
            db.execute("DELETE FROM signups WHERE tag='Q'")
        await worker.process_job(bot, claim(store), send=send_for(store))
        bot.rest.remove_role_from_member.assert_awaited_once()
        signup(store)
        await worker.process_job(bot, claim(store), send=send_for(store))
        assert bot.rest.add_role_to_member.await_count == 2
        assert int(ROLE) in members[USER].role_ids
        with store.tx() as db:
            assert (
                next(r for r in roles.snapshot(db)["pools"] if r["pool"] == "lazy")[
                    "role_id"
                ]
                == "444444444444444444"
            )

    asyncio.run(run())


def test_failure_never_reverts_signup_and_is_visible(store):
    save(store)
    signup(store)

    async def run():
        bot, _, role, _ = bot_fixture()
        role.permissions = 8
        await worker.process_job(bot, claim(store), send=send_for(store))
        bot.rest.add_role_to_member.assert_not_awaited()
        with store.tx() as db:
            assert db.execute("SELECT COUNT(*) FROM signups").fetchone()[0] == 1
            assert any(r["failure"] for r in roles.snapshot(db)["pools"])

    asyncio.run(run())


def test_restart_after_discord_accepted_reconciles_instead_of_replaying(store):
    save(store)
    signup(store)

    async def run():
        bot, _, _, _ = bot_fixture()
        real = send_for(store)

        async def lost_receipt(action, **body):
            if action == "finish":
                raise worker.BridgeUnavailable()
            return await real(action, **body)

        await worker.process_job(bot, claim(store), send=lost_receipt)
        with store.tx() as db:
            db.execute("UPDATE cwl_pool_role_jobs SET lease_until=0")
        await worker.process_job(bot, claim(store), send=real)
        bot.rest.add_role_to_member.assert_awaited_once()
        with store.tx() as db:
            assert (
                db.execute("SELECT state FROM cwl_pool_role_jobs").fetchone()[0]
                == "done"
            )

    asyncio.run(run())


def test_role_change_or_clear_cancels_old_work_without_removing_old_role(store):
    save(store)
    signup(store)
    old = claim(store)
    save(store, role=None)

    async def run():
        bot, members, _, _ = bot_fixture()
        members[USER].role_ids = [int(ROLE)]
        await worker.process_job(bot, old, send=send_for(store))
        bot.rest.add_role_to_member.assert_not_awaited()
        bot.rest.remove_role_from_member.assert_not_awaited()
        assert members[USER].role_ids == [int(ROLE)]
        bot.rest.fetch_roles.assert_not_awaited()

    asyncio.run(run())


def test_expiry_catchup_once_persists_cursor_and_includes_every_holder(store):
    save(store, now=datetime(2026, 12, 20, tzinfo=timezone.utc))
    now = datetime(2027, 1, 16, tzinfo=timezone.utc)
    scan = claim(store, now)
    assert scan["kind"] == "scan"
    with store.tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[OTHER],
            cursor=OTHER,
        )
    resumed = claim(store, now)
    assert resumed["id"] == scan["id"] and resumed["cursor"] == OTHER
    with store.tx() as db:
        roles.finish(
            db,
            resumed["id"],
            resumed["lease_token"],
            resumed["generation"],
            page=[],
            cursor=OTHER,
        )
    removal = claim(store, now)
    assert removal["kind"] == "remove" and removal["user_id"] == OTHER
    with store.tx() as db:
        roles.finish(db, removal["id"], removal["lease_token"], removal["generation"])
    assert claim(store, now) is None
    with store.tx() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM cwl_pool_role_jobs WHERE kind='scan'"
            ).fetchone()[0]
            == 1
        )
        assert next(r for r in roles.snapshot(db)["pools"] if r["pool"] == "main")[
            "next_expiry"
        ].startswith("2027-02-16")


def test_durable_pacing_and_stale_tokens(store):
    save(store)
    signup(store)
    signup(store, "Q", OTHER)
    with store.tx() as db:
        job = roles.claim(db)
        assert roles.claim(db) is None
        assert not roles.finish(db, job["id"], "wrong", job["generation"])["accepted"]
        db.execute(
            "UPDATE cwl_pool_role_jobs SET lease_until=0 WHERE id=?", (job["id"],)
        )
    replacement = claim(store)
    with store.tx() as db:
        assert not roles.finish(db, job["id"], job["lease_token"], job["generation"])[
            "accepted"
        ]
    assert replacement["lease_token"] != job["lease_token"]


@pytest.mark.parametrize(
    "failure", ["network", "missing_member", "missing_permission", "deleted_role"]
)
def test_discord_failure_matrix_keeps_signup_and_records_outcome(store, failure):
    import hikari

    save(store)
    signup(store)

    async def run():
        bot, _, role, top = bot_fixture()
        if failure == "network":
            bot.rest.fetch_roles.side_effect = TimeoutError()
        elif failure == "missing_member":
            original = bot.rest.fetch_member.side_effect

            async def read(guild, uid):
                if int(uid) == int(USER):
                    raise hikari.NotFoundError(
                        "http://fixture", {}, b"", "Unknown Member", 10007
                    )
                return await original(guild, uid)

            bot.rest.fetch_member.side_effect = read
        elif failure == "missing_permission":
            top.permissions = 0
        else:
            bot.rest.fetch_roles.return_value = [top]
        await worker.process_job(bot, claim(store), send=send_for(store))
        bot.rest.add_role_to_member.assert_not_awaited()
        with store.tx() as db:
            assert db.execute("SELECT COUNT(*) FROM signups").fetchone()[0] == 1
            row = db.execute("SELECT * FROM cwl_pool_role_jobs").fetchone()
            assert row["state"] == (
                "pending" if failure in ("network", "missing_permission") else "failed"
            )
            assert any(r["failure"] for r in roles.snapshot(db)["pools"])

    asyncio.run(run())


def test_expiry_supersedes_old_signup_jobs_but_preserves_new_signup_intent(store):
    save(store, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    signup(store)
    now = datetime(2026, 12, 16, tzinfo=timezone.utc)
    scan = claim(store, now)
    with store.tx() as db:
        assert (
            db.execute(
                "SELECT state FROM cwl_pool_role_jobs WHERE kind='sync'"
            ).fetchone()[0]
            == "superseded"
        )
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[USER],
            cursor=USER,
        )
    # A later signup is represented by its durable post-cutoff request time.
    signup(store, "Q", OTHER)
    with store.tx() as db:
        db.execute(
            "UPDATE cwl_pool_role_jobs SET requested_at=? WHERE user_id=? AND kind='sync'",
            (now.timestamp() + 1, OTHER),
        )
    scan = claim(store, now)
    with store.tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[],
            cursor=USER,
        )
    removal = claim(store, now)
    assert removal["kind"] == "remove"
    with store.tx() as db:
        roles.finish(db, removal["id"], removal["lease_token"], removal["generation"])
    newer = claim(store, now)
    assert newer["kind"] == "sync" and newer["user_id"] == OTHER and newer["desired"]
    with store.tx() as db:
        roles.finish(db, newer["id"], newer["lease_token"], newer["generation"])
    assert claim(store, now) is None


def test_same_role_save_does_not_skip_overdue_expiry_and_multi_month_catchup_is_once(
    store,
):
    save(store, now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    save(store, now=datetime(2027, 2, 20, tzinfo=timezone.utc))
    now = datetime(2027, 2, 20, tzinfo=timezone.utc)
    scan = claim(store, now)
    assert scan["kind"] == "scan" and "2027-02-16" in scan["job_key"]
    with store.tx() as db:
        roles.finish(
            db, scan["id"], scan["lease_token"], scan["generation"], page=[], cursor="0"
        )
        assert next(r for r in roles.snapshot(db)["pools"] if r["pool"] == "main")[
            "next_expiry"
        ].startswith("2027-03-16")
    assert claim(store, now) is None


def test_expired_lease_and_forged_pagination_are_refused(store):
    save(store)
    signup(store)
    job = claim(store)
    with store.tx() as db:
        db.execute("UPDATE cwl_pool_role_jobs SET lease_until=0")
        assert not roles.validate(db, job["id"], job["lease_token"], job["generation"])[
            "valid"
        ]
    scan = claim(store, datetime(2027, 1, 16, tzinfo=timezone.utc))
    with store.tx() as db:
        with pytest.raises(ValueError):
            roles.finish(
                db,
                scan["id"],
                scan["lease_token"],
                scan["generation"],
                page=[USER],
                cursor="0",
            )


def test_blank_slow_bridge_never_holds_management_lane(store):
    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow(action, **body):
            assert action == "claim"
            entered.set()
            await release.wait()
            return {"job": None}

        bot, _, _, _ = bot_fixture()
        task = asyncio.create_task(worker.poll_once(bot, send=slow))
        await entered.wait()
        assert not worker.queue_lock().locked()
        async with worker.queue_lock():
            pass
        release.set()
        await task
        bot.rest.fetch_roles.assert_not_awaited()

    asyncio.run(run())


def test_actual_role_write_uses_shared_lane(store):
    save(store)
    signup(store)

    async def run():
        bot, _, _, _ = bot_fixture()
        real = bot.rest.add_role_to_member.side_effect

        async def add(*args, **kwargs):
            assert worker.queue_lock().locked()
            return await real(*args, **kwargs)

        bot.rest.add_role_to_member.side_effect = add
        await worker.poll_once(bot, send=send_for(store))
        bot.rest.add_role_to_member.assert_awaited_once()

    asyncio.run(run())


def test_progress_excludes_internal_scan_and_superseded_old_signup_work(store):
    save(store, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    signup(store)
    now = datetime(2026, 12, 16, tzinfo=timezone.utc)
    scan = claim(store, now)
    with store.tx() as db:
        row = next(r for r in roles.snapshot(db)["pools"] if r["pool"] == "main")
        assert row["scanning"] and row["progress"] == {}
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[USER],
            cursor=USER,
        )
    scan = claim(store, now)
    with store.tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[],
            cursor=USER,
        )
        row = next(r for r in roles.snapshot(db)["pools"] if r["pool"] == "main")
        assert not row["scanning"] and row["progress"] == {"pending": 1}


def test_same_physical_role_is_retained_while_either_pool_has_signup(store):
    save(store)
    save(store, "lazy", ROLE)
    signup(store)
    signup(store, "Q", pool="lazy")
    with store.tx() as db:
        db.execute("DELETE FROM signups WHERE tag='P'")
        for job in db.execute("SELECT * FROM cwl_pool_role_jobs"):
            assert roles.desired(db, job)


def test_unlinked_and_invalid_legacy_owners_never_create_role_targets(store):
    save(store)
    for i, uid in enumerate(["", "100", "000000000000000000"]):
        signup(store, str(i), uid=uid)
    with store.tx() as db:
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0] == 0


def test_shutdown_is_quiet_when_bridge_is_unconfigured(store, caplog, monkeypatch):
    import logging

    monkeypatch.setenv("CWL_DISCORD_BRIDGE_SECRET", "")

    async def run():
        bot, _, _, _ = bot_fixture()
        with patch_sleep_cancel():
            with pytest.raises(asyncio.CancelledError):
                await worker.run(bot)
        bot.rest.fetch_roles.assert_not_awaited()

    from unittest.mock import patch

    def patch_sleep_cancel():
        return patch.object(
            worker.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
        )

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert not caplog.records


def test_role_job_and_receipt_retention_does_not_delete_settings_audit_or_pending(
    store,
):
    save(store)
    signup(store)
    job = claim(store)
    with store.tx() as db:
        roles.finish(db, job["id"], job["lease_token"], job["generation"])
        db.execute("UPDATE cwl_pool_role_jobs SET created_at=0")
        db.execute("UPDATE cwl_pool_role_audit SET created_at='2000-01-01'")
        db.execute("UPDATE cwl_pool_role_clock SET last_prune=0,next_at=0")
        roles.claim(db)
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0] == 0
        assert (
            db.execute("SELECT action FROM cwl_pool_role_audit").fetchall()[0][0]
            == "setting_saved"
        )


def test_every_holder_expiry_includes_unlinked_and_bot_members_once_and_resumes_after_remove(
    store,
):
    from unittest.mock import Mock

    save(store, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    signup(store)
    now = datetime(2026, 12, 16, tzinfo=timezone.utc)

    async def run():
        bot, members, _, _ = bot_fixture()
        third = "444444444444444444"
        members[third] = NS(id=int(third), role_ids=[int(ROLE)], is_bot=True)
        members[USER].role_ids = [int(ROLE)]
        members[OTHER].role_ids = [int(ROLE)]

        class Page:
            def __init__(self, rows):
                self.rows = rows

            def limit(self, n):
                self.rows = self.rows[:n]
                return self

            async def __aiter__(self):
                for row in self.rows:
                    yield row

        bot.rest.fetch_members = Mock(
            side_effect=lambda guild, *, start_at: Page(
                sorted(
                    [m for m in members.values() if m.id > start_at], key=lambda m: m.id
                )
            )
        )
        real = send_for(store)
        await worker.process_job(bot, claim(store, now), send=real)
        await worker.process_job(bot, claim(store, now), send=real)
        first = claim(store, now)
        assert first["kind"] == "remove"

        async def lost(action, **body):
            if action == "finish":
                raise worker.BridgeUnavailable()
            return await real(action, **body)

        await worker.process_job(bot, first, send=lost)
        with store.tx() as db:
            db.execute(
                "UPDATE cwl_pool_role_jobs SET lease_until=0 WHERE id=?", (first["id"],)
            )
        resumed = claim(store, now)
        assert resumed["id"] == first["id"]
        await worker.process_job(bot, resumed, send=real)
        while (job := claim(store, now)) is not None:
            await worker.process_job(bot, job, send=real)
        assert bot.rest.remove_role_from_member.await_count == 3
        bot.rest.add_role_to_member.assert_not_awaited()
        assert all(int(ROLE) not in m.role_ids for m in members.values())
        # A manual grant after the finished cycle stays until the next cycle.
        members[OTHER].role_ids.append(int(ROLE))
        assert claim(store, now) is None
        assert bot.rest.remove_role_from_member.await_count == 3

    asyncio.run(run())


def test_cancel_after_expiry_never_adds_while_another_account_remains(store):
    save(store)
    signup(store)
    signup(store, "Q")

    async def run():
        bot, members, _, _ = bot_fixture()
        await worker.process_job(bot, claim(store), send=send_for(store))
        members[USER].role_ids.clear()  # The monthly cleanup already removed it.
        with store.tx() as db:
            db.execute("DELETE FROM signups WHERE tag='P'")
        pending = claim(store)
        if pending is not None:
            await worker.process_job(bot, pending, send=send_for(store))
        assert members[USER].role_ids == []
        assert bot.rest.add_role_to_member.await_count == 1
        bot.rest.remove_role_from_member.assert_not_awaited()

    asyncio.run(run())


def test_same_role_save_keeps_an_expiry_and_cancel_receipt_in_flight(store):
    save(store, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    signup(store)
    now = datetime(2026, 12, 16, tzinfo=timezone.utc)
    scan = claim(store, now)
    with store.role_tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[USER],
            cursor=USER,
        )
    save(store)
    with store.tx() as db:
        assert (
            db.execute(
                "SELECT state FROM cwl_pool_role_jobs WHERE kind='scan'"
            ).fetchone()[0]
            == "pending"
        )
        assert (
            db.execute(
                "SELECT state FROM cwl_pool_role_jobs WHERE kind='remove'"
            ).fetchone()[0]
            == "pending"
        )
    with store.tx() as db:
        db.execute("DELETE FROM signups WHERE tag='P'")
    before = claim(store, now)
    save(store)
    with store.tx() as db:
        assert (
            roles.owned(db, before["id"], before["lease_token"], before["generation"])
            is not None
        )


def test_fresh_signup_supersedes_a_delayed_expiry_remove_even_after_retry(store):
    save(store, now=datetime(2026, 12, 1, tzinfo=timezone.utc))
    now = datetime(2026, 12, 16, tzinfo=timezone.utc)
    scan = claim(store, now)
    with store.role_tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[USER],
            cursor=USER,
        )
    scan = claim(store, now)
    with store.role_tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[],
            cursor=USER,
        )
    removal = claim(store, now)
    with store.role_tx() as db:
        roles.finish(
            db,
            removal["id"],
            removal["lease_token"],
            removal["generation"],
            retry=True,
            message="Retry later",
        )
    signup(store)
    with store.tx() as db:
        assert (
            db.execute(
                "SELECT state FROM cwl_pool_role_jobs WHERE id=?", (removal["id"],)
            ).fetchone()[0]
            == "superseded"
        )
        assert (
            roles.owned(
                db, removal["id"], removal["lease_token"], removal["generation"]
            )
            is None
        )


def test_only_member_facing_season_counts_and_metadata_edits_do_not_readd(store):
    save(store)
    signup(store)
    with store.tx() as db:
        db.execute("INSERT INTO seasons(id,label) VALUES (2,'Historical draft')")
        db.execute(
            "INSERT INTO signups(season_id,tag,user_id,pool,prefer_crystal_1_or_lower,player_name,town_hall) VALUES(2,'OLD',?,'main',0,'Old',16)",
            (OTHER,),
        )
        assert roles.members(db, "main") == [USER]
        assert db.execute("SELECT COUNT(*) FROM cwl_pool_role_jobs").fetchone()[0] == 1
        prior = dict(db.execute("SELECT * FROM cwl_pool_role_jobs").fetchone())
        db.execute("UPDATE signups SET player_name='New name' WHERE tag='P'")
        assert dict(db.execute("SELECT * FROM cwl_pool_role_jobs").fetchone()) == prior
        db.execute("UPDATE member_season SET season_id=2 WHERE id=1")
        assert roles.members(db, "main") == [OTHER]
        jobs = list(db.execute("SELECT * FROM cwl_pool_role_jobs WHERE season_id=2"))
        assert len(jobs) == 1
        assert jobs[0]["user_id"] == OTHER
        assert jobs[0]["intent"] == "add"
        generation = jobs[0]["generation"]
        db.execute("UPDATE member_season SET season_id=2 WHERE id=1")
        assert (
            db.execute(
                "SELECT generation FROM cwl_pool_role_jobs WHERE id=?", (jobs[0]["id"],)
            ).fetchone()[0]
            == generation
        )
        assert roles.owned(db, prior["id"], "invalid", prior["generation"]) is None


@pytest.mark.parametrize("denied_at", [1, 2])
def test_dashboard_grant_rechecked_before_any_bot_role_write(store, denied_at):
    signup(store)
    save(store)
    job = claim(store)
    bot, _, _, _ = bot_fixture()
    original = send_for(store)
    validations = 0

    async def send(action, **body):
        nonlocal validations
        result = await original(action, **body)
        if action == "validate":
            validations += 1
            result["role_allowed"] = validations < denied_at
        return result

    asyncio.run(worker.process_job(bot, job, send=send))
    bot.rest.add_role_to_member.assert_not_awaited()
    bot.rest.remove_role_from_member.assert_not_awaited()
    assert validations == denied_at
    assert (
        store.one("SELECT state FROM cwl_pool_role_jobs WHERE id=?", (job["id"],))[
            "state"
        ]
        == "failed"
    )


def test_positive_but_expired_lease_cannot_validate_or_finish(store):
    import time

    signup(store)
    save(store)
    job = claim(store)
    with store.role_tx() as db:
        db.execute(
            "UPDATE cwl_pool_role_jobs SET lease_until=? WHERE id=?",
            (time.time() - 1, job["id"]),
        )
        assert not roles.validate(db, job["id"], job["lease_token"], job["generation"])[
            "valid"
        ]
        assert not roles.finish(db, job["id"], job["lease_token"], job["generation"])[
            "accepted"
        ]


@pytest.mark.parametrize("backfill", [True, False])
def test_cancel_one_of_two_accounts_does_not_erase_a_pending_add(store, backfill):
    if not backfill:
        save(store)
    signup(store, "A")
    signup(store, "B")
    if backfill:
        save(store)
    before = store.one("SELECT * FROM cwl_pool_role_jobs WHERE kind='sync'")
    assert before["intent"] == "add" and before["state"] == "pending"
    with store.tx() as db:
        db.execute("DELETE FROM signups WHERE tag='A'")
    after = store.one("SELECT * FROM cwl_pool_role_jobs WHERE id=?", (before["id"],))
    assert after["intent"] == "add" and after["generation"] == before["generation"]

    async def run():
        bot, people, _, _ = bot_fixture()
        await worker.process_job(bot, claim(store), send=send_for(store))
        assert people[USER].role_ids == [int(ROLE)]
        bot.rest.add_role_to_member.assert_awaited_once()
        bot.rest.remove_role_from_member.assert_not_awaited()

    asyncio.run(run())


def test_post_cutoff_signup_then_cancel_other_account_keeps_the_role(store):
    from datetime import timedelta

    signup(store, "A")
    save(store)
    cutoff = datetime.fromisoformat(
        store.one("SELECT next_expiry FROM cwl_pool_role_settings WHERE pool='main'")[
            "next_expiry"
        ]
    )
    signup(store, "B")
    with store.tx() as db:
        db.execute(
            "UPDATE cwl_pool_role_jobs SET requested_at=? WHERE kind='sync'",
            ((cutoff + timedelta(seconds=1)).timestamp(),),
        )
        db.execute("DELETE FROM signups WHERE tag='A'")
    now = cutoff + timedelta(seconds=2)
    scan = claim(store, now=now)
    assert scan["kind"] == "scan"
    with store.role_tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[USER],
            cursor=USER,
        )
    # A complete second scan page advances the scan receipt to terminal.
    scan = claim(store, now=now + timedelta(seconds=4))
    assert scan["kind"] == "scan"
    with store.role_tx() as db:
        roles.finish(
            db,
            scan["id"],
            scan["lease_token"],
            scan["generation"],
            page=[],
            cursor=USER,
        )

    async def run():
        bot, people, _, _ = bot_fixture()
        people[USER].role_ids = [int(ROLE)]
        for step in range(3):
            job = claim(store, now=now + timedelta(seconds=8 + step * 4))
            if job:
                await worker.process_job(bot, job, send=send_for(store))
        assert people[USER].role_ids == [int(ROLE)]
        bot.rest.remove_role_from_member.assert_not_awaited()

    asyncio.run(run())


def test_post_cutoff_cancel_is_not_a_reason_to_skip_expiry_removal(store):
    import time

    signup(store, "A")
    save(store)
    cutoff = time.time() - 1
    with store.tx() as db:
        db.execute("DELETE FROM signups WHERE tag='A'")
        db.execute("UPDATE cwl_pool_role_jobs SET requested_at=?", (cutoff + 1,))
        assert (
            db.execute("SELECT intent FROM cwl_pool_role_jobs").fetchone()[0]
            == "cancel"
        )
        assert not roles.skip_change(
            db,
            {
                "kind": "remove",
                "user_id": USER,
                "role_id": ROLE,
                "cycle_cutoff": cutoff,
            },
        )


def test_lease_with_wrong_setting_revision_cannot_validate_or_finish(store):
    signup(store)
    save(store)
    job = claim(store)
    with store.role_tx() as db:
        db.execute(
            "UPDATE cwl_pool_role_jobs SET setting_revision=setting_revision+100 WHERE id=?",
            (job["id"],),
        )
        assert not roles.validate(db, job["id"], job["lease_token"], job["generation"])[
            "valid"
        ]
        assert not roles.finish(db, job["id"], job["lease_token"], job["generation"])[
            "accepted"
        ]
