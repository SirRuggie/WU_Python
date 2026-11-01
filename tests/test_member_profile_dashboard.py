import asyncio
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import hikari
import pytest
from aiohttp import web
from extensions.warrior import profile_dashboard as actions
from cwl_web import member_timezones as routes
from utils import dashboard_access

UID = "123456789012345678"
ACTOR = "234567890123456789"
FIELDS = dict(zone_id="gmt-5", country="US")


def test_every_profile_route_checks_existing_member_roles_access(monkeypatch):
    async def run():
        gate = AsyncMock(side_effect=web.HTTPForbidden())
        monkeypatch.setattr(routes, "require_manage", gate)
        request = S(json=AsyncMock(), match_info={})
        directory = AsyncMock()
        monkeypatch.setattr(routes, "directory", directory)
        for handler in (
            routes.overview,
            routes.choices,
            routes.save,
            routes.import_current,
            routes.standardize_preview,
            routes.standardize_confirm,
            routes.standardize_status,
            routes.standardize_runs,
        ):
            with pytest.raises(web.HTTPForbidden):
                await handler(request)
        directory.assert_not_awaited()
        request.json.assert_not_awaited()
        assert all(call.args[1] == "member_profiles" for call in gate.await_args_list)
        assert dashboard_access.SECTION_SCOPE["member_profiles"] == "member_roles"

    asyncio.run(run())


def test_changed_nickname_never_reaches_discord_or_storage(monkeypatch):
    async def run():
        store = S(commit_after=AsyncMock(), write=AsyncMock())
        monkeypatch.setattr(actions, "MemberProfiles", lambda db: store)
        monkeypatch.setattr(
            actions,
            "target_context",
            AsyncMock(
                return_value=dict(
                    member=S(nickname="Manually changed"),
                    bot_permissions=hikari.Permissions.MANAGE_NICKNAMES,
                )
            ),
        )
        bot = S(rest=S(edit_member=AsyncMock()))
        row = dict(
            guild_id=actions.GUILD_ID,
            section="member_profiles",
            action="save",
            user_id=ACTOR,
            revision=1,
            values=dict(
                discord_id=UID,
                fields=FIELDS,
                rename=True,
                name="Name",
                old_nickname="Reviewed old",
            ),
        )
        with pytest.raises(ValueError, match="Nickname changed"):
            await actions.apply(bot, None, row)
        store.commit_after.assert_not_awaited()
        store.write.assert_not_awaited()
        bot.rest.edit_member.assert_not_awaited()

    asyncio.run(run())


def test_profile_only_save_never_calls_discord_edit(monkeypatch):
    async def run():
        store = S(commit_after=AsyncMock(), write=AsyncMock())
        monkeypatch.setattr(actions, "MemberProfiles", lambda db: store)
        monkeypatch.setattr(actions, "target_context", AsyncMock(return_value={}))
        bot = S(rest=S(edit_member=AsyncMock()))
        row = dict(
            guild_id=actions.GUILD_ID,
            action="save",
            user_id=ACTOR,
            revision=0,
            values=dict(discord_id=UID, fields=FIELDS, rename=False),
        )
        result = await actions.apply(bot, None, row)
        assert "Nickname unchanged" in result["message"]
        assert store.write.await_args.kwargs["source"] == "staff"
        bot.rest.edit_member.assert_not_awaited()
        store.commit_after.assert_not_awaited()

    asyncio.run(run())


def test_forged_or_unticked_child_cannot_rename(monkeypatch):
    async def run():
        monkeypatch.setattr(actions, "MemberProfiles", lambda db: S())
        monkeypatch.setattr(actions, "target_context", AsyncMock(return_value={}))
        bot = S(rest=S(edit_member=AsyncMock()))
        row = dict(
            _id="run:0",
            parent_id="run",
            guild_id=actions.GUILD_ID,
            action="standardize_one",
            user_id=ACTOR,
            revision=1,
            values=dict(
                discord_id=UID,
                revision=1,
                old_nickname="Old",
                new_nickname="New | GMT-5 🇺🇸",
            ),
        )
        parent = dict(
            _id="run",
            state="queued",
            cursor=0,
            items=[dict(row["values"], discord_id="345678901234567890")],
        )
        mongo = S(bot_config=S(find_one=AsyncMock(return_value=parent)))
        with pytest.raises(ValueError, match="reviewed selection"):
            await actions.apply(bot, mongo, row)
        bot.rest.edit_member.assert_not_awaited()

    asyncio.run(run())


def test_partial_member_directory_refuses_import(monkeypatch):
    async def run():
        async def listing(guild):
            yield S(id=int(UID))

        bot = S(get_me=lambda: S(id=987654321012345678), rest=S(fetch_members=listing))
        with pytest.raises(ValueError, match="incomplete directory"):
            await actions.directory(bot)

    asyncio.run(run())
