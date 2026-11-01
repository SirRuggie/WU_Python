import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import pytest
from extensions.warrior import nickname_setup as ui, core
from tests.test_warrior_setup import context


@pytest.fixture(autouse=True)
def fixture_guild(monkeypatch):
    monkeypatch.setattr(ui, "GUILD_ID", 10)


def options(rendered):
    def walk(value):
        if isinstance(value, dict):
            if "options" in value:
                yield value["options"]
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    result = []
    for component in rendered:
        result.extend(walk(component.build()[0]))
    return result


def test_tied_accounts_paginate_without_silently_choosing_and_menus_fit():
    data = {"_id": "1"}
    state = {
        "nonce": "n",
        "step": "name",
        "accounts": [
            {"name": f"Player{i}", "tag": "#PYY", "townHallLevel": 18}
            for i in range(30)
        ],
    }
    first = options(ui.render(data, state))
    second = options(ui.render(data, state, page=1))
    assert len(first[0]) == 25 and first[0][-1]["label"] == "Type a name"
    assert len(second[0]) == 7 and second[0][0]["value"] == "24"
    state["step"] = "country"
    assert len(options(ui.render(data, state))[0]) == 25
    state["step"] = "zone"
    assert len(options(ui.render(data, state))[0]) == 19


def test_preview_bounds_offer_shortening_without_a_save_button():
    state = {
        "nonce": "n",
        "step": "preview",
        "name": "x" * 32,
        "zone_id": "gmt-5",
        "country": "US",
    }
    text = repr(ui.render({"_id": "1"}, state))
    assert "shorten" in text.lower() and "Set nickname" not in text


def test_typed_name_modal_does_not_change_a_member_before_authorized_submission(
    monkeypatch,
):
    from utils import component_state

    monkeypatch.setattr(
        component_state,
        "get_state",
        AsyncMock(
            return_value={
                "type": "warrior_setup",
                "guild_id": 10,
                "recruiter_id": 20,
                "nickname_setup": {
                    "nonce": "n",
                    "step": "preview",
                    "name": "Current name",
                },
            }
        ),
    )
    ctx = S(
        respond_with_modal=AsyncMock(),
        interaction=S(values=[]),
        guild_id=10,
        user=S(id=20),
    )
    asyncio.run(ui.action(ctx, "1:n:type", mongo=object(), bot=object()))
    result = ctx.respond_with_modal.call_args.kwargs
    assert (
        result["components"][0].build()[0]["components"][0]["value"] == "Current name"
    )
    assert (
        len(result["components"]) == 1
        and result["custom_id"] == "warrior_nick_form:1:n:name"
    )


def test_duplicate_preview_is_refused_before_the_discord_change(monkeypatch):
    async def run():
        c = context()
        bot = S(rest=S(edit_member=AsyncMock()))
        state = {
            "nonce": "n",
            "step": "preview",
            "name": "Main",
            "zone_id": "gmt",
            "country": "GB",
        }
        m = S(component_state=S(find_one_and_update=AsyncMock(return_value=None)))
        monkeypatch.setattr(
            ui,
            "MemberProfiles",
            lambda db: S(
                consume_preview=AsyncMock(return_value=False),
                preview_current=AsyncMock(return_value=True),
            ),
        )
        with pytest.raises(core.SetupError, match="already used"):
            await ui.save(S(user=S(id=20)), {"_id": "1"}, c, m, state, bot)
        bot.rest.edit_member.assert_not_awaited()

    asyncio.run(run())


def test_other_guild_cannot_change_family_profile():
    c = context()
    c["guild"].id = 999
    with pytest.raises(core.SetupError, match="Warriors United"):
        ui.authorize(c)


def test_successful_save_is_not_reported_as_failure_when_summary_read_fails(
    monkeypatch,
):
    async def run():
        c = context()
        bot = S(rest=S(edit_member=AsyncMock()))
        state = {
            "nonce": "n",
            "step": "preview",
            "name": "Main",
            "zone_id": "gmt",
            "country": "GB",
            "profile_revision": 0,
        }
        m = S(
            component_state=S(find_one_and_update=AsyncMock(return_value={"_id": "1"}))
        )

        async def commit(*args, change, **kwargs):
            await change()
            return {"revision": 1}

        monkeypatch.setattr(
            ui,
            "MemberProfiles",
            lambda db: S(
                commit_after=commit,
                consume_preview=AsyncMock(return_value=True),
                finish_preview=AsyncMock(return_value=True),
                preview_current=AsyncMock(return_value=True),
            ),
        )
        monkeypatch.setattr(ui, "update_state", AsyncMock())
        monkeypatch.setattr(
            core,
            "context",
            AsyncMock(side_effect=[c, RuntimeError("summary unavailable")]),
        )
        ctx = S(user=S(id=20), interaction=S(edit_initial_response=AsyncMock()))
        await ui.save(ctx, {"_id": "1"}, c, m, state, bot)
        bot.rest.edit_member.assert_awaited_once()
        assert "Nickname and member profile saved" in repr(
            ctx.interaction.edit_initial_response.call_args
        )

    asyncio.run(run())


def test_finished_old_save_does_not_replace_a_newer_wizard(monkeypatch):
    async def run():
        c = context()
        ctx = S(user=S(id=20), interaction=S(edit_initial_response=AsyncMock()))
        store = S(
            consume_preview=AsyncMock(return_value=True),
            commit_after=AsyncMock(),
            finish_preview=AsyncMock(return_value=False),
            preview_current=AsyncMock(return_value=True),
        )
        monkeypatch.setattr(ui, "MemberProfiles", lambda db: store)
        monkeypatch.setattr(core, "context", AsyncMock(return_value=c))
        from extensions.commands import warrior

        monkeypatch.setattr(warrior, "home", AsyncMock(return_value=[]))
        state = {
            "nonce": "old",
            "name": "Main",
            "zone_id": "gmt",
            "country": "GB",
            "profile_revision": 0,
        }
        await ui.save(ctx, {"_id": "1"}, c, object(), state, object())
        ctx.interaction.edit_initial_response.assert_not_awaited()

    asyncio.run(run())


def test_old_consume_race_does_not_replace_newer_controls(monkeypatch):
    async def run():
        c = context()
        ctx = S(user=S(id=20), interaction=S(edit_initial_response=AsyncMock()))
        store = S(
            consume_preview=AsyncMock(return_value=False),
            preview_current=AsyncMock(return_value=False),
        )
        monkeypatch.setattr(ui, "MemberProfiles", lambda db: store)
        state = {
            "nonce": "old",
            "name": "Main",
            "zone_id": "gmt",
            "country": "GB",
            "profile_revision": 0,
        }
        await ui.save(ctx, {"_id": "1"}, c, object(), state, object())
        ctx.interaction.edit_initial_response.assert_not_awaited()

    asyncio.run(run())


def save_fixture(
    monkeypatch, *, edit_error=None, storage_error=None, receipt_error=None, fresh=None
):
    c = context()
    state = dict(
        nonce="n",
        step="preview",
        name="Main",
        zone_id="gmt",
        country="GB",
        profile_revision=0,
    )
    bot = S(rest=S(edit_member=AsyncMock(side_effect=edit_error)))

    async def commit(*args, change, **kwargs):
        await change()
        if storage_error:
            raise storage_error

    store = S(
        commit_after=commit,
        consume_preview=AsyncMock(return_value=True),
        finish_preview=AsyncMock(return_value=True, side_effect=receipt_error),
        preview_current=AsyncMock(return_value=True),
    )
    monkeypatch.setattr(ui, "MemberProfiles", lambda db: store)
    monkeypatch.setattr(core, "context", AsyncMock(return_value=fresh or c))
    ctx = S(
        user=S(id=20),
        respond=AsyncMock(),
        interaction=S(edit_initial_response=AsyncMock()),
    )
    return ctx, c, state, bot, store


@pytest.mark.parametrize(
    "kind,message",
    [
        ("ForbiddenError", "Missing permission"),
        ("BadRequestError", "Invalid nickname"),
        ("NotFoundError", "Unknown Member"),
    ],
)
def test_definite_discord_refusal_survives_receipt_storage_failure(
    monkeypatch, kind, message
):
    import hikari

    async def run():
        error = getattr(hikari, kind)(
            url="https://discord.com/api", headers={}, raw_body="", message=message
        )
        ctx, c, state, bot, store = save_fixture(
            monkeypatch, edit_error=error, receipt_error=RuntimeError("Mongo down")
        )
        with pytest.raises(core.SetupError, match=message):
            await ui.save(ctx, {"_id": "1"}, c, object(), state, bot)
        ctx.respond.assert_not_awaited()
        bot.rest.edit_member.assert_awaited_once()

    asyncio.run(run())


def test_confirmed_discord_success_survives_both_storage_failures(monkeypatch):
    async def run():
        ctx, c, state, bot, store = save_fixture(
            monkeypatch,
            storage_error=RuntimeError("profile write failed"),
            receipt_error=RuntimeError("receipt write failed"),
        )
        await ui.save(ctx, {"_id": "1"}, c, object(), state, bot)
        assert ctx.respond.await_args.args[0].startswith(
            "Nickname changed in Discord; profile save not confirmed"
        )
        assert ctx.respond.await_args.kwargs["ephemeral"]
        bot.rest.edit_member.assert_awaited_once()

    asyncio.run(run())


def test_final_authorization_revocation_prevents_rename(monkeypatch):
    async def run():
        fresh = context()
        fresh["bot_permissions"] = 0
        ctx, c, state, bot, store = save_fixture(monkeypatch, fresh=fresh)
        with pytest.raises(core.SetupError, match="Manage Nicknames"):
            await ui.save(ctx, {"_id": "1"}, c, object(), state, bot)
        bot.rest.edit_member.assert_not_awaited()

    asyncio.run(run())


def test_step_persist_cannot_replace_a_consumed_applying_receipt(monkeypatch):
    async def run():
        record = {"nonce": "n", "step": "applying"}

        async def update(mongo, query, change):
            condition = query.get("nickname_setup.step") or {}
            allowed = (
                record["step"] in condition.get("$in", [])
                if "$in" in condition
                else record["step"] != condition.get("$ne")
            )
            if allowed:
                record.update(change["$set"]["nickname_setup"])
            return S(matched_count=int(allowed))

        monkeypatch.setattr(ui, "update_state", update)
        with pytest.raises(core.SetupError):
            await ui.persist(
                object(), {"_id": "1"}, dict(step="country"), old_nonce="n"
            )
        assert record == {"nonce": "n", "step": "applying"}

    asyncio.run(run())


def test_real_discord_form_error_keeps_field_reason_and_sentence_boundary(monkeypatch):
    import hikari

    async def run():
        error = hikari.BadRequestError(
            url="https://discord.com/api",
            headers={},
            raw_body="",
            message="Invalid Form Body",
            code=50035,
            errors={
                "nick": {
                    "_errors": [
                        {
                            "code": "BASE_TYPE_MAX_LENGTH",
                            "message": "Must be 32 or fewer in length",
                        }
                    ]
                }
            },
        )
        ctx, c, state, bot, store = save_fixture(monkeypatch, edit_error=error)
        with pytest.raises(core.SetupError) as result:
            await ui.save(ctx, {"_id": "1"}, c, object(), state, bot)
        assert "nick: Must be 32 or fewer in length. Nothing changed" in str(
            result.value
        )
        bot.rest.edit_member.assert_awaited_once()

    asyncio.run(run())


def test_return_during_applying_does_not_silence_discord_refusal(monkeypatch):
    import hikari

    async def run():
        error = hikari.ForbiddenError(
            url="https://discord.com/api",
            headers={},
            raw_body="",
            message="Missing Permissions",
        )
        ctx, c, state, bot, store = save_fixture(monkeypatch, edit_error=error)
        # Return removed nickname_setup while the edit awaited Discord.
        store.finish_preview.return_value = False
        await ui.save(ctx, {"_id": "1"}, c, object(), state, bot)
        assert "Missing Permissions. Nothing changed" in ctx.respond.await_args.args[0]
        assert ctx.respond.await_args.kwargs["ephemeral"]
        bot.rest.edit_member.assert_awaited_once()

    asyncio.run(run())


@pytest.mark.parametrize(
    "step,nonce,old_nonce,allowed",
    [
        ("applying", "n", None, False),
        ("preview", "n", None, True),
        ("applying", "n", "n", False),
        ("saved", "n", "n", False),
        ("needs_attention", "n", "n", False),
        ("preview", "changed", "n", False),
        ("name", "n", "n", True),
        ("country", "n", "n", True),
        ("zone", "n", "n", True),
        ("preview", "n", "n", True),
    ],
)
def test_each_persist_guard_preserves_newer_or_consumed_state(
    monkeypatch, step, nonce, old_nonce, allowed
):
    async def run():
        record = {"step": step, "nonce": nonce}
        original = dict(record)

        async def update(mongo, query, change):
            match = True
            for key, expected in query.items():
                actual = "1" if key == "_id" else record.get(key.split(".")[-1])
                if isinstance(expected, dict):
                    match &= (
                        actual in expected["$in"]
                        if "$in" in expected
                        else actual != expected["$ne"]
                    )
                else:
                    match &= actual == expected
            if match:
                record.update(change["$set"]["nickname_setup"])
            return S(matched_count=int(match))

        monkeypatch.setattr(ui, "update_state", update)
        if allowed:
            await ui.persist(
                object(), {"_id": "1"}, {"step": "country"}, old_nonce=old_nonce
            )
            assert record["nonce"] != nonce
        else:
            with pytest.raises(core.SetupError):
                await ui.persist(
                    object(), {"_id": "1"}, {"step": "country"}, old_nonce=old_nonce
                )
            assert record == original

    asyncio.run(run())
