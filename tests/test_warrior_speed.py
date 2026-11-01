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
        with pytest.raises(core.SetupError):
            await core.change_roles(b, m, c, add=[60, 61])
        assert b.rest.add_role_to_member.await_count == 1

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
