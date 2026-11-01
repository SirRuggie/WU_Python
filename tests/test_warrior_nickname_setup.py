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


def test_typed_name_modal_does_not_change_a_member_before_authorized_submission():
    ctx = S(respond_with_modal=AsyncMock(), interaction=S(values=[]))
    asyncio.run(ui.action(ctx, "1:n:type", mongo=object(), bot=object()))
    result = ctx.respond_with_modal.call_args.kwargs
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
