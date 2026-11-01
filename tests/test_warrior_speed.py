"""Display cache and final-write authorization are deliberately separate lanes."""

import asyncio
import copy
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from extensions.warrior import core, nickname_setup as nick
from tests.test_warrior_setup import context, mongo


def fixture():
    c = context()
    m = mongo()
    m.ticket_setup.find_one.return_value = {"main_recruiter_role": 40}
    by_id = {x.id: x for x in [c["actor"], c["member"], c["me"]]}
    rest = S(
        fetch_guild=AsyncMock(return_value=c["guild"]),
        fetch_roles=AsyncMock(return_value=c["roles"]),
        fetch_member=AsyncMock(side_effect=lambda g, u: by_id[u]),
        add_role_to_member=AsyncMock(),
        remove_role_from_member=AsyncMock(),
    )
    cache = S(
        get_guild=lambda g: c["guild"],
        get_roles_view_for_guild=lambda g: {r.id: r for r in c["roles"]},
        get_member=lambda g, u: by_id[u],
    )
    return c, m, S(rest=rest, cache=cache, get_me=lambda: c["me"]), by_id


def test_display_cache_hit_and_fresh_reads():
    async def check():
        c, m, b, _ = fixture()
        assert (await core.context(b, m, 10, 20, 30, fresh=False))["member"] == c[
            "member"
        ]
        b.rest.fetch_guild.assert_not_awaited()
        b.rest.fetch_roles.assert_not_awaited()
        b.rest.fetch_member.assert_not_awaited()
        await core.context(b, m, 10, 20, 30)
        assert b.rest.fetch_member.await_count == 3
        b.rest.fetch_roles.assert_awaited_once()

    asyncio.run(check())


def test_cache_miss_and_partial_roles_fall_back_and_404_is_explained():
    async def check():
        import hikari

        c, m, b, _ = fixture()
        b.cache.get_member = lambda g, u: None
        b.cache.get_roles_view_for_guild = lambda g: {}
        await core.context(b, m, 10, 20, 30, fresh=False)
        assert b.rest.fetch_member.await_count == 3
        b.rest.fetch_roles.assert_awaited_once()
        b.rest.fetch_member.side_effect = hikari.NotFoundError(
            url="x", headers={}, raw_body="gone"
        )
        with pytest.raises(core.SetupError, match="no longer"):
            await core.context(b, m, 10, 20, 30, fresh=False)

    asyncio.run(check())


def test_stale_cached_staff_or_bot_role_never_authorizes_mutation():
    async def check():
        for who in ("actor", "me"):
            c, m, b, by_id = fixture()
            await core.context(b, m, 10, 20, 30, fresh=False)
            changed = copy.copy(c[who])
            changed.role_ids = []
            b.rest.fetch_member.side_effect = lambda g, u: (
                changed if u == changed.id else by_id[u]
            )
            with pytest.raises(core.SetupError):
                await core.change_roles(b, m, c, add=[60])
            b.rest.add_role_to_member.assert_not_awaited()

    asyncio.run(check())


def test_each_role_write_rechecks_authorization():
    async def check():
        c, m, b, by_id = fixture()

        async def added(*args, **kwargs):
            c["actor"].role_ids = []

        b.rest.add_role_to_member.side_effect = added
        result = await core.change_roles(b, m, c, add=[60, 61])
        assert result["added"] == ["Role 60"]
        assert result["failed"] and "Stopped" in result["failed"][0]
        assert b.rest.add_role_to_member.await_count == 1
        m.warrior_audit.update_one.assert_awaited_once()
        recorded = m.warrior_audit.update_one.call_args.args[1]["$push"]["events"][
            "$each"
        ][0]["result"]
        assert recorded == result

    asyncio.run(check())


@pytest.mark.parametrize(
    "late,failed,manual",
    [
        (False, False, False),
        (True, False, False),
        (False, True, False),
        (False, False, True),
    ],
)
def test_background_lookup_immediate_and_nonce_safe(monkeypatch, late, failed, manual):
    async def check():
        from extensions.commands import warrior

        c, m, b, _ = fixture()
        m.member_profiles = S()
        monkeypatch.setattr(nick, "GUILD_ID", 10)
        monkeypatch.setattr(nick.MemberProfiles, "get", AsyncMock(return_value=None))
        data = {"_id": "speed", "type": "warrior_setup"}
        db = {}
        release = asyncio.Event()

        async def persist(m, data, state, **kw):
            db.update(nickname_setup=dict(state, nonce="n"))
            return copy.deepcopy(db["nickname_setup"])

        async def update(m, query, change):
            saved = db.get("nickname_setup") or {}
            if saved.get("nonce") != query.get(
                "nickname_setup.nonce", saved.get("nonce")
            ) or saved.get("step") != query.get(
                "nickname_setup.step", saved.get("step")
            ):
                return S(matched_count=0)
            db.update(copy.deepcopy(change["$set"]))
            return S(matched_count=1)

        async def choices(*args):
            await release.wait()
            if failed:
                raise RuntimeError("fixture")
            return {
                "accounts": [{"tag": "#PYY", "name": "Account", "townHallLevel": 18}],
                "suggested": {"name": "Account", "tag": "#PYY"},
                "unavailable": False,
            }

        monkeypatch.setattr(nick, "persist", persist)
        monkeypatch.setattr(nick, "update_state", update)
        monkeypatch.setattr(
            nick, "get_state", AsyncMock(side_effect=lambda *a: copy.deepcopy(db))
        )
        monkeypatch.setattr(nick, "name_choices", choices)
        show = AsyncMock()
        monkeypatch.setattr(warrior, "show", show)
        await nick.begin(S(), data, c, m, None)
        assert show.await_count == 1
        assert db["nickname_setup"]["loading"]
        assert "Checking linked accounts" in repr(show.call_args)
        assert "Type a name" in repr(show.call_args)
        if late:
            db["nickname_setup"].update(nonce="new", step="preview", name="Typed")
        if manual:
            db["nickname_setup"]["manual_name"] = True
        tasks = tuple(nick._tasks)
        release.set()
        await asyncio.gather(*tasks)
        if late:
            assert show.await_count == 1 and db["nickname_setup"]["name"] == "Typed"
        else:
            assert show.await_count == 2 and not db["nickname_setup"]["loading"]
            assert db["nickname_setup"]["step"] == (
                "name" if failed or manual else "country"
            )
            if failed:
                assert db["nickname_setup"]["unavailable"]

    asyncio.run(check())


def test_timing_contains_ids_and_operations_without_names(caplog):
    async def check():
        _, m, b, _ = fixture()
        await core.context(b, m, 10, 20, 30)

    import logging

    with caplog.at_level(logging.INFO, logger="extensions.warrior.timing"):
        asyncio.run(check())
    assert "rest.guild" in caplog.text and "mongo.ticket_setup" in caplog.text
    assert "actor_id" in caplog.text and "elapsed_ms" in caplog.text
    assert "Recruit" not in caplog.text and "Role 40" not in caplog.text


def test_abandon_removes_only_current_nickname_state(monkeypatch):
    update = AsyncMock(return_value=S(matched_count=1))
    monkeypatch.setattr(nick, "update_state", update)
    asyncio.run(nick.abandon(object(), {"_id": "1", "nickname_setup": {"nonce": "n"}}))
    assert update.call_args.args[1] == {"_id": "1", "nickname_setup.nonce": "n"}
    assert update.call_args.args[2] == {"$unset": {"nickname_setup": ""}}


def test_nickname_commit_rejects_demoted_actor_despite_stale_display_cache(monkeypatch):
    async def check():
        c, m, b, by_id = fixture()
        b.rest.edit_member = AsyncMock()
        lost = copy.copy(c["actor"])
        lost.role_ids = []
        b.rest.fetch_member.side_effect = lambda g, u: lost if u == 20 else by_id[u]

        async def commit(*args, change, **kwargs):
            await change()

        store = S(
            consume_preview=AsyncMock(return_value=True),
            preview_current=AsyncMock(return_value=True),
            finish_preview=AsyncMock(return_value=True),
            commit_after=commit,
        )
        monkeypatch.setattr(nick, "GUILD_ID", 10)
        monkeypatch.setattr(nick, "MemberProfiles", lambda m: store)
        ctx = S(
            user=S(id=20),
            respond=AsyncMock(),
            interaction=S(edit_initial_response=AsyncMock()),
        )
        state = dict(
            nonce="n",
            step="preview",
            name="Fixture",
            zone_id="gmt-5",
            country="US",
            profile_revision=0,
        )
        with pytest.raises(core.SetupError, match="Recruitment Team"):
            await nick.save(ctx, {"_id": "s"}, c, m, state, b)
        b.rest.edit_member.assert_not_awaited()

    asyncio.run(check())


@pytest.mark.parametrize("verb", ["apply:restart:token", "retry"])
def test_demotion_blocks_restart_and_retry_writes(monkeypatch, verb):
    async def check():
        from extensions.commands import warrior

        c, m, b, by_id = fixture()
        lost = copy.copy(c["actor"])
        lost.role_ids = []
        b.rest.fetch_member.side_effect = lambda g, u: lost if u == 20 else by_id[u]
        m.warrior_walkthroughs.find_one = AsyncMock(
            return_value={"ticket_id": "ticket", "state": "paused", "token": "old"}
        )
        m.warrior_walkthroughs.delete_one = AsyncMock()
        m.warrior_history = S(replace_one=AsyncMock())
        monkeypatch.setattr(core, "session", AsyncMock(return_value=({"_id": "s"}, c)))
        monkeypatch.setattr(
            core, "open_ticket", AsyncMock(return_value={"_id": "ticket"})
        )
        ctx = S(
            guild_id=10,
            user=S(id=20),
            defer=AsyncMock(),
            interaction=S(values=[], edit_initial_response=AsyncMock()),
        )
        await warrior.action(ctx, "s:" + verb, mongo=m, bot=b, coc_client=None)
        m.warrior_walkthroughs.delete_one.assert_not_awaited()
        m.warrior_walkthroughs.update_one.assert_not_awaited()
        m.warrior_history.replace_one.assert_not_awaited()
        assert b.rest.fetch_member.await_count == 3

    asyncio.run(check())


def test_prepare_does_not_grant_thread_access_or_queue_for_demoted_actor(monkeypatch):
    async def check():
        from extensions.warrior import walkthrough

        c, m, b, by_id = fixture()
        lost = copy.copy(c["actor"])
        lost.role_ids = []
        b.rest.fetch_member.side_effect = lambda g, u: lost if u == 20 else by_id[u]
        m.warrior_walkthroughs.insert_one = AsyncMock()
        access = AsyncMock()
        monkeypatch.setattr(
            walkthrough.thread_service, "ensure_candidate_thread_access", access
        )
        monkeypatch.setattr(
            core,
            "open_ticket",
            AsyncMock(return_value={"_id": "ticket", "location": {"id": 123}}),
        )
        with pytest.raises(core.SetupError, match="Recruitment Team"):
            await walkthrough.prepare(b, m, c, {}, {})
        access.assert_not_awaited()
        m.warrior_walkthroughs.insert_one.assert_not_awaited()

    asyncio.run(check())


def test_settings_submission_does_not_trust_cached_administrator(monkeypatch):
    async def check():
        from extensions.commands import warrior

        c, m, b, by_id = fixture()
        c["actor"].role_ids.append(63)
        c["actor_permissions"] = __import__("hikari").Permissions.ADMINISTRATOR
        fresh = copy.copy(c["actor"])
        fresh.role_ids = [40]
        b.rest.fetch_member.side_effect = lambda g, u: fresh if u == 20 else by_id[u]
        m.warrior_settings.update_one = AsyncMock()
        monkeypatch.setattr(core, "session", AsyncMock(return_value=({"_id": "s"}, c)))
        monkeypatch.setattr(core, "clans", AsyncMock(return_value=[]))
        monkeypatch.setattr(warrior, "modal_value", lambda *a: "60")
        ctx = S(
            guild_id=10,
            user=S(id=20),
            interaction=S(
                create_initial_response=AsyncMock(), edit_initial_response=AsyncMock()
            ),
        )
        await warrior.form(ctx, "s:setting:roles:family", mongo=m, bot=b)
        m.warrior_settings.update_one.assert_not_awaited()
        assert "Administrator" in repr(ctx.interaction.edit_initial_response.call_args)

    asyncio.run(check())


def test_second_click_acknowledges_before_waiting_for_the_panel_lock():
    async def check():
        entered = asyncio.Event()
        release = asyncio.Event()
        running = 0
        maximum = 0

        @nick.serialized()
        async def handler(ctx, action_id):
            nonlocal running, maximum
            running += 1
            maximum = max(maximum, running)
            entered.set()
            await release.wait()
            running -= 1

        first = S(defer=AsyncMock())
        second = S(defer=AsyncMock())
        one = asyncio.create_task(handler(first, "sid:one"))
        await entered.wait()
        two = asyncio.create_task(handler(second, "sid:two"))
        await asyncio.sleep(0)
        second.defer.assert_awaited_once_with(edit=True)
        release.set()
        await asyncio.gather(one, two)
        assert maximum == 1

    asyncio.run(check())


def test_background_message_update_is_serialized_with_a_newer_step(monkeypatch):
    async def check():
        from extensions.commands import warrior

        shown = []
        paused = asyncio.Event()
        release = asyncio.Event()
        db = {"nonce": "n", "step": "name", "accounts": []}

        async def show(ctx, rendered):
            if rendered == "name":
                paused.set()
                await release.wait()
            shown.append(rendered)

        monkeypatch.setattr(warrior, "show", show)
        monkeypatch.setattr(nick, "render", lambda d, s: s["step"])
        monkeypatch.setattr(
            nick,
            "get_state",
            AsyncMock(side_effect=lambda *a: {"nickname_setup": dict(db)}),
        )
        monkeypatch.setattr(
            nick, "update_state", AsyncMock(return_value=S(matched_count=1))
        )
        monkeypatch.setattr(
            nick,
            "name_choices",
            AsyncMock(
                return_value={"accounts": [], "suggested": None, "unavailable": False}
            ),
        )
        ctx = S(defer=AsyncMock())

        @nick.serialized()
        async def next_step(ctx, action_id):
            db.update(nonce="new", step="preview")
            await show(ctx, "preview")

        loader = asyncio.create_task(
            nick.load_names(ctx, {"_id": "sid"}, object(), None, dict(db), 30)
        )
        await paused.wait()
        newer = asyncio.create_task(next_step(ctx, "sid:new"))
        await asyncio.sleep(0)
        before = db["step"]
        release.set()
        await asyncio.gather(loader, newer)
        assert before == "name" and shown == ["name", "preview"]

    asyncio.run(check())


def test_shutdown_cancels_and_awaits_pending_name_lookup():
    async def check():
        began = asyncio.Event()

        async def pending():
            began.set()
            await asyncio.Event().wait()

        task = asyncio.create_task(pending())
        nick._tasks.add(task)
        task.add_done_callback(nick._tasks.discard)
        try:
            await began.wait()
            await nick.stop()
            assert task.done() and task.cancelled()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(check())


def test_empty_role_batch_still_checks_member_hierarchy(monkeypatch):
    async def check():
        c, m, b, _ = fixture()
        c["member"].id = 99
        monkeypatch.setattr(core, "context", AsyncMock(return_value=c))
        with pytest.raises(core.SetupError, match="server owner"):
            await core.change_roles(b, m, c)
        m.warrior_audit.update_one.assert_awaited_once()

    asyncio.run(check())


def test_confirmed_role_changes_are_reported_when_audit_storage_is_unavailable():
    async def check():
        c, m, b, _ = fixture()
        m.warrior_audit.update_one.side_effect = RuntimeError(
            "fixture storage unavailable"
        )
        result = await core.change_roles(b, m, c, add=[60])
        assert result["added"] == ["Role 60"]
        assert "audit save not confirmed" in result["failed"][0]

    asyncio.run(check())


def test_cancelled_role_batch_attempts_audit_with_confirmed_partial_results():
    async def check():
        import hikari

        c, m, b, _ = fixture()
        c["roles"].append(
            S(
                id=65,
                position=5,
                permissions=hikari.Permissions.NONE,
                is_managed=False,
                name="Role 65",
            )
        )
        second = asyncio.Event()

        async def added(g, u, r, **kwargs):
            if r == 65:
                second.set()
                await asyncio.Event().wait()

        b.rest.add_role_to_member.side_effect = added
        task = asyncio.create_task(core.change_roles(b, m, c, add=[60, 65]))
        await second.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        saved = m.warrior_audit.update_one.call_args.args[1]["$push"]["events"][
            "$each"
        ][0]["result"]
        assert saved["added"] == ["Role 60"] and "interrupted" in saved["failed"][0]

    asyncio.run(check())


def test_large_partial_batch_never_truncates_its_interruption_notice():
    value = core.result_text(
        {
            "added": ["Role " + str(i) + "x" * 90 for i in range(100)],
            "removed": [],
            "unchanged": [],
            "failed": ["Stopped after authorization changed."],
        }
    )
    assert value.startswith("**Failed:** Stopped after authorization changed.")
    assert "**Added:**" in value and len(value) <= 2800 and value.endswith("…")
