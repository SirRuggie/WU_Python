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
            routes.standardize_stop,
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
        async def commit(*args, change, **kwargs):
            if kwargs.get("prepare") is not None:
                await kwargs["prepare"]()
            await change()

        store = S(commit_after=AsyncMock(side_effect=commit), write=AsyncMock())
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
        store.commit_after.assert_awaited_once()
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


def test_already_matching_nickname_is_not_sent_again(monkeypatch):
    async def run():
        async def commit(*args, change, **kwargs):
            if kwargs.get("prepare") is not None:
                await kwargs["prepare"]()
            await change()

        store = S(commit_after=AsyncMock(side_effect=commit), write=AsyncMock())
        monkeypatch.setattr(actions, "MemberProfiles", lambda db: store)
        monkeypatch.setattr(
            actions,
            "target_context",
            AsyncMock(return_value=dict(member=S(nickname="Name | GMT-5 🇺🇸"))),
        )
        bot = S(rest=S(edit_member=AsyncMock()))
        row = dict(
            guild_id=actions.GUILD_ID,
            action="save",
            user_id=ACTOR,
            revision=0,
            values=dict(
                discord_id=UID,
                fields=FIELDS,
                rename=True,
                name="Name",
                old_nickname="Name | GMT-5 🇺🇸",
            ),
        )
        await actions.apply(bot, None, row)
        bot.rest.edit_member.assert_not_awaited()
        store.commit_after.assert_awaited_once()
        store.write.assert_not_awaited()

    asyncio.run(run())


def test_roles_are_rechecked_inside_edit_and_split_outcome_is_explicit(monkeypatch):
    async def run():
        from utils.member_profiles import ProfileOutcomeUncertain

        initial = dict(
            member=S(nickname="Old"),
            bot_permissions=hikari.Permissions.MANAGE_NICKNAMES,
        )
        stale = dict(member=S(nickname="Old"), bot_permissions=0)
        lookup = AsyncMock(side_effect=[stale])
        monkeypatch.setattr(actions, "target_context", lookup)

        async def commit(*args, change, **kwargs):
            if kwargs.get("prepare") is not None:
                await kwargs["prepare"]()
            await change()
            raise RuntimeError("Mongo down after Discord")

        monkeypatch.setattr(
            actions, "MemberProfiles", lambda db: S(commit_after=commit)
        )
        bot = S(rest=S(edit_member=AsyncMock()))
        row = dict(
            guild_id=actions.GUILD_ID,
            action="save",
            user_id=ACTOR,
            revision=0,
            values=dict(
                discord_id=UID,
                fields=FIELDS,
                rename=True,
                name="Name",
                old_nickname="Old",
            ),
        )
        with pytest.raises(ValueError, match="Manage Nicknames"):
            await actions.apply(bot, None, row)
        bot.rest.edit_member.assert_not_awaited()
        lookup.side_effect = [dict(initial, member=S(nickname="Manual change"))]
        with pytest.raises(ValueError, match="Nickname changed"):
            await actions.apply(bot, None, row)
        bot.rest.edit_member.assert_not_awaited()
        lookup.side_effect = [initial]
        with pytest.raises(
            ProfileOutcomeUncertain,
            match="Nickname changed in Discord; profile save was not confirmed",
        ):
            await actions.apply(bot, None, row)
        bot.rest.edit_member.assert_awaited_once()

    asyncio.run(run())


def test_partial_import_reports_no_renames_and_safe_rerun(monkeypatch):
    async def run():
        from utils.member_profiles import ProfileOutcomeUncertain

        monkeypatch.setattr(actions, "MemberProfiles", lambda db: S())
        monkeypatch.setattr(
            actions,
            "directory",
            AsyncMock(
                return_value=[S(id=int(UID), nickname="Name | GMT", is_bot=False)]
            ),
        )
        monkeypatch.setattr(
            actions,
            "import_nicknames",
            AsyncMock(
                side_effect=RuntimeError("Mongo unavailable after partial progress")
            ),
        )
        bot = S(rest=S(edit_member=AsyncMock()))
        row = dict(guild_id=actions.GUILD_ID, action="import", user_id=ACTOR, values={})
        with pytest.raises(ProfileOutcomeUncertain, match="No nicknames changed"):
            await actions.apply(bot, None, row)
        bot.rest.edit_member.assert_not_awaited()

    asyncio.run(run())


@pytest.mark.parametrize(
    "invalid",
    [
        dict(tag="#WRONG", name="Wrong cached account", town_hall=19),
        dict(tag="#PQQ", name="Missing TH", town_hall=None),
    ],
)
def test_public_account_lookup_never_suggests_malformed_or_wrong_tag(
    monkeypatch, invalid
):
    async def run():
        import json

        monkeypatch.setattr(routes, "require_manage", AsyncMock(return_value={}))
        monkeypatch.setattr(
            routes, "discord", AsyncMock(return_value={"user": {"id": UID}})
        )
        provider = S(
            linked_tags=AsyncMock(return_value=["#PYY", "#PQQ"]),
            player=AsyncMock(
                side_effect=[dict(tag="#PYY", name="Known", town_hall=18), invalid]
            ),
        )
        request = S(app={"providers": provider}, match_info={"member_id": UID})
        response = await routes.choices(request)
        body = json.loads(response.text)
        assert body["complete"] is False and body["suggested"] is None
        assert body["accounts"] == [dict(tag="#PYY", name="Known", townHallLevel=18)]

    asyncio.run(run())


def test_real_discord_form_error_preserves_dashboard_nickname_reason(monkeypatch):
    async def run():
        initial = dict(
            member=S(nickname="Old"),
            bot_permissions=hikari.Permissions.MANAGE_NICKNAMES,
        )
        monkeypatch.setattr(actions, "target_context", AsyncMock(return_value=initial))
        committed = []

        async def commit(*args, change, **kwargs):
            if kwargs.get("prepare") is not None:
                await kwargs["prepare"]()
            await change()
            committed.append(True)

        monkeypatch.setattr(
            actions, "MemberProfiles", lambda db: S(commit_after=commit)
        )
        error = hikari.BadRequestError(
            url="https://discord.com/api",
            headers={},
            raw_body="",
            message="Invalid Form Body",
            code=50035,
            errors={
                "nick": {"_errors": [{"message": "Must be 32 or fewer in length"}]}
            },
        )
        bot = S(rest=S(edit_member=AsyncMock(side_effect=error)))
        row = dict(
            guild_id=actions.GUILD_ID,
            action="save",
            user_id=ACTOR,
            revision=0,
            values=dict(
                discord_id=UID,
                fields=FIELDS,
                rename=True,
                name="Name",
                old_nickname="Old",
            ),
        )
        with pytest.raises(
            ValueError,
            match="nick: Must be 32 or fewer in length. No profile was saved",
        ):
            await actions.apply(bot, None, row)
        assert not committed
        bot.rest.edit_member.assert_awaited_once()

    asyncio.run(run())


def test_standardize_preview_preserves_pipe_names_and_marks_unknown_suffix_for_review(
    monkeypatch,
):
    from contextlib import asynccontextmanager
    import json
    from utils import member_profile_runs

    async def run():
        rows = [
            dict(
                discord_id=UID,
                name="Sir Ruggie",
                nickname="Sir | Ruggie | EST 🇺🇸",
                profile=dict(FIELDS, revision=1),
                skip_reason=None,
            ),
            dict(
                discord_id=ACTOR,
                name="Bob",
                nickname="Bob | Co-Leader",
                profile=dict(FIELDS, revision=1),
                skip_reason=None,
            ),
        ]
        rows.append(
            dict(
                discord_id="345678901234567890",
                name="Already",
                nickname="Already | GMT-5 🇺🇸",
                profile=dict(FIELDS, revision=1),
                skip_reason=None,
            )
        )
        monkeypatch.setattr(routes, "inventory", AsyncMock(return_value=rows))
        monkeypatch.setattr(
            routes, "require_manage", AsyncMock(return_value={"user_id": ACTOR})
        )
        store = S(preview=AsyncMock(return_value="token"))
        monkeypatch.setattr(member_profile_runs, "ProfileRuns", lambda db: store)

        @asynccontextmanager
        async def database(request):
            yield object()

        monkeypatch.setattr(routes, "mongo", database)
        response = await routes.standardize_preview(object())
        values = json.loads(response.text)["rows"]
        assert values[0]["new_nickname"] == "Sir | Ruggie | GMT-5 🇺🇸"
        assert not values[0]["needs_review"]
        assert values[1]["new_nickname"] == "Bob | Co-Leader | GMT-5 🇺🇸"
        assert values[1]["needs_review"]
        assert values[2]["skip_reason"] == "Already standardized"

    asyncio.run(run())


def test_staff_can_list_and_read_another_staff_members_run(monkeypatch):
    from contextlib import asynccontextmanager
    import json

    async def run():
        from cwl_web import member_timezones as routes

        creator = "345678901234567890"
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            guild_id=actions.GUILD_ID,
            user_id=creator,
            state="done",
            items=[],
            stopped_by=ACTOR,
        )
        queries = []

        class Cursor:
            def sort(self, *args):
                return self

            async def to_list(self, **kwargs):
                return [parent] if self.parent else []

        def find(query, projection=None):
            if projection is not None:
                assert "items" not in projection
            queries.append(query)
            cursor = Cursor()
            cursor.parent = "parent_id" not in query
            return cursor

        async def find_one(query):
            queries.append(query)
            return parent

        db = S(bot_config=S(find=find, find_one=find_one))

        @asynccontextmanager
        async def database(request):
            yield db

        monkeypatch.setattr(routes, "mongo", database)
        monkeypatch.setattr(
            routes, "require_manage", AsyncMock(return_value={"user_id": ACTOR})
        )
        request = S(match_info={"run_id": "run"}, query={})
        listed = json.loads((await routes.standardize_runs(request)).text)
        detail = json.loads((await routes.standardize_status(request)).text)
        assert listed["runs"][0]["started_by"] == creator
        assert detail["started_by"] == creator and detail["stopped_by"] == ACTOR
        assert all("user_id" not in query for query in queries)
        assert all(
            query.get("guild_id") == actions.GUILD_ID
            for query in queries
            if "parent_id" not in query
        )

    asyncio.run(run())


def test_run_status_never_lists_unselected_legacy_skips(monkeypatch):
    from contextlib import asynccontextmanager
    import json

    async def run():
        monkeypatch.setattr(
            routes, "require_manage", AsyncMock(return_value={"user_id": ACTOR})
        )
        items = [
            dict(
                discord_id=UID,
                name="Selected",
                old_nickname="Old",
                new_nickname="New",
                revision=1,
            )
        ]
        parent = dict(
            _id="run",
            kind="member_profile_standardize",
            guild_id=actions.GUILD_ID,
            user_id=ACTOR,
            state="queued",
            items=items,
            skipped=[
                dict(
                    discord_id="345678901234567890", name="Unselected", status="skipped"
                )
            ],
        )
        coll = S(
            find_one=AsyncMock(return_value=parent),
            find=lambda *a, **kw: S(to_list=AsyncMock(return_value=[])),
        )

        @asynccontextmanager
        async def mongo(_):
            yield S(bot_config=coll)

        monkeypatch.setattr(routes, "mongo", mongo)
        response = await routes.standardize_status(S(match_info={"run_id": "run"}))
        body = json.loads(response.text)
        assert len(body["rows"]) == 1 and body["rows"][0]["name"] == "Selected"
        assert "Unselected" not in response.text

    asyncio.run(run())
