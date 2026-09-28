import asyncio
from datetime import timedelta
from types import SimpleNamespace as S
from unittest.mock import AsyncMock
import hikari
import pytest
from extensions.commands import warrior as ui
from extensions.warrior import core, walkthrough

P = hikari.Permissions


def run(coro):
    return asyncio.run(coro)


def role(rid, position=1, perms=P.NONE, managed=False):
    return S(
        id=rid,
        position=position,
        permissions=perms,
        is_managed=managed,
        name=f"Role {rid}",
    )


def member(uid, ids=()):
    return S(
        id=uid,
        guild_id=10,
        role_ids=list(ids),
        is_bot=False,
        display_name="Recruit",
        nickname=None,
        display_avatar_url="https://cdn.discordapp.com/embed/avatars/0.png",
    )


def context():
    roles = [
        role(10),
        role(40, 10),
        role(50, 20, P.MANAGE_ROLES | P.MANAGE_NICKNAMES),
        role(60, 5),
        role(61, 3),
        role(62, 30),
        role(63, 2, P.ADMINISTRATOR),
        role(64, 2, managed=True),
    ]
    return dict(
        guild=S(id=10, owner_id=99),
        roles=roles,
        actor=member(20, [40]),
        member=member(30, [61]),
        me=member(1, [50]),
        actor_permissions=P.NONE,
        bot_permissions=P.MANAGE_ROLES | P.MANAGE_NICKNAMES,
    )


def mongo():
    return S(
        ticket_setup=S(find_one=AsyncMock(return_value={})),
        recruit_onboarding=S(
            update_one=AsyncMock(), find_one=AsyncMock(return_value=None)
        ),
        component_state=S(find_one_and_update=AsyncMock(return_value=None)),
    )


class Cursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, **kw):
        return self.rows

    def limit(self, _):
        return self


def test_command_is_separate_and_legacy_remains():
    from extensions.commands.recruit.dashboard.dashboard import RecruitDashboard
    from extensions.components import registered_functions

    assert ui.Warrior._command_data.name == "warrior"
    assert RecruitDashboard._command_data.name == "dashboard"
    assert {
        "warrior",
        "warrior_form",
        "warrior_begin",
        "create_nickname",
        "execute_add_clans",
    }.issubset(registered_functions)


@pytest.mark.parametrize("rid", [62, 63, 64, 10, 999])
def test_role_mutation_refuses_hierarchy_privilege_managed_and_missing_roles(rid):
    c = context()
    bot = S(
        rest=S(
            fetch_member=AsyncMock(return_value=c["member"]),
            add_role_to_member=AsyncMock(),
        )
    )
    result = run(core.change_roles(bot, mongo(), c, add=[rid]))
    assert result["failed"]
    bot.rest.add_role_to_member.assert_not_awaited()


def test_role_updates_are_incremental_and_truthfully_report_failure():
    c = context()
    rest = S(
        fetch_member=AsyncMock(return_value=c["member"]),
        add_role_to_member=AsyncMock(),
        remove_role_from_member=AsyncMock(
            side_effect=hikari.ForbiddenError(url="x", headers={}, raw_body="denied")
        ),
    )
    result = run(core.change_roles(S(rest=rest), mongo(), c, add=[60], remove=[61]))
    rest.add_role_to_member.assert_awaited_once()
    assert result["added"] == ["Role 60"] and result["failed"] and not result["removed"]
    assert not hasattr(rest, "edit_member")


@pytest.mark.parametrize("target", [member(99), member(30, [62]), member(30, [40])])
def test_protected_targets_are_not_mutated(target):
    c = context()
    c["member"] = target
    with pytest.raises(core.SetupError):
        core.manageable_target(c)


@pytest.mark.parametrize(
    "ign,zone,country",
    [("x" * 25, "UTC+100", "US"), ("Name", "EST", "notflag"), ("a\nb", "EST", "US")],
)
def test_nickname_validates_combined_length_and_country(ign, zone, country):
    with pytest.raises(core.SetupError):
        core.nickname(ign, zone, country)


def test_nickname_country_conversion():
    assert core.nickname("Warrior", "est", "us") == "Warrior | EST 🇺🇸"


@pytest.mark.parametrize("rows", [[], [{"_id": "one"}, {"_id": "two"}]])
def test_walkthrough_requires_exactly_one_open_ticket(rows):
    m = S(tickets=S(find=lambda query: Cursor(rows)))
    with pytest.raises(core.SetupError):
        run(core.open_ticket(m, 10, 30))


def test_ticket_query_excludes_legacy_closed_and_other_servers():
    captured = []

    def find(query):
        captured.append(query)
        return Cursor([{"_id": "ticket_1"}])

    assert run(core.open_ticket(S(tickets=S(find=find)), 10, 30))["_id"] == "ticket_1"
    assert (
        captured[0]["status"] == "open"
        and captured[0]["venue"] == "thread"
        and captured[0]["guild_id"] == 10
    )


def test_session_checks_owner_and_server(monkeypatch):
    monkeypatch.setattr(
        core,
        "get_state",
        AsyncMock(
            return_value={"type": "warrior_setup", "guild_id": 10, "recruiter_id": 20}
        ),
    )
    with pytest.raises(core.SetupError):
        run(core.session(S(guild_id=10, user=S(id=21)), object(), mongo(), "x"))


def test_stale_session_is_refused(monkeypatch):
    monkeypatch.setattr(core, "get_state", AsyncMock(return_value=None))
    with pytest.raises(core.SetupError):
        run(core.session(S(), object(), mongo(), "x"))


def record():
    return {
        "_id": "warrior:10:30",
        "token": "token",
        "guild_id": 10,
        "user_id": 30,
        "actor_id": 20,
        "ticket_id": "ticket_1",
        "ticket_channel": 100,
        "clan": {
            "name": "Warriors",
            "tag": "#ABC",
            "role_id": 60,
            "announcement_id": 200,
            "chat_channel_id": 201,
        },
        "settings": {"roles": core.STANDARD, "channels": core.CHANNELS},
        "started_at": core.now(),
        "next_step": 0,
        "state": "preparing",
    }


def test_walkthrough_preserves_destinations_except_first_ticket_messages():
    r = record()
    steps = walkthrough.plan(r)
    assert [s[0] for s in steps] == [
        100,
        100,
        200,
        201,
        1005916813378465832,
        671836698371424256,
        671836698371424256,
    ]
    assert all(s[0] != 1128966424082255872 for s in steps)
    assert len({walkthrough.marker(r, i) for i in range(7)}) == 7
    for i in range(7):
        assert walkthrough.components(r, i)[0].build()[0]["type"] == 17


def test_home_shows_missing_fields_and_fits_component_limits(monkeypatch):
    c = context()
    m = mongo()
    monkeypatch.setattr(core, "clans", AsyncMock(return_value=[]))
    built = run(ui.home({"_id": "1"}, c, m))[0].build()[0]
    assert built["accent_color"] == ui.GOLDENROD_ACCENT
    assert (
        "Not set" in repr(built)
        and "Not assigned" in repr(built)
        and "Missing" in repr(built)
    )

    def count(x):
        return (
            1
            + sum(count(k) for k in x.get("components", []))
            + (count(x["accessory"]) if "accessory" in x else 0)
        )

    assert count(built) <= 40


def test_clans_paginate_without_dropping_options(monkeypatch):
    c = context()
    rows = [dict(name=f"Clan {i}", tag=f"#{i}", role_id=i + 100) for i in range(30)]
    monkeypatch.setattr(core, "clans", AsyncMock(return_value=rows))
    a = run(ui.clan_menu({"_id": "1"}, c, mongo(), 0))[0].build()[0]
    b = run(ui.clan_menu({"_id": "1"}, c, mongo(), 1))[0].build()[0]
    assert len(a["components"][1]["components"][0]["options"]) == 25
    assert len(b["components"][1]["components"][0]["options"]) == 5


def test_modals_acknowledge_without_member_changes():
    ctx = S(respond_with_modal=AsyncMock())
    run(ui.action(ctx, "1:nick", mongo=object(), bot=object()))
    fields = ctx.respond_with_modal.call_args.kwargs["components"]
    assert len(fields) == 3 and all(x.build()[0]["type"] == 1 for x in fields)


def test_config_form_rechecks_authorization(monkeypatch):
    c = context()
    ctx = S(
        interaction=S(
            create_initial_response=AsyncMock(), edit_initial_response=AsyncMock()
        )
    )
    monkeypatch.setattr(core, "session", AsyncMock(return_value=({"_id": "1"}, c)))
    m = mongo()
    m.ticket_setup.update_one = AsyncMock()
    run(ui.form(ctx, "1:setting:roles:family", mongo=m, bot=object()))
    m.ticket_setup.update_one.assert_not_awaited()
    assert "Administrator" in repr(ctx.interaction.edit_initial_response.call_args)


def test_delivery_recovers_send_before_checkpoint_without_duplicate(monkeypatch):
    r = record()
    c = context()
    saved = S(id=555, author=S(id=1), components=[S(id=walkthrough.marker(r, 0))])

    async def history():
        yield saved

    rest = S(fetch_messages=lambda *a, **k: history(), create_message=AsyncMock())
    bot = S(rest=rest, get_me=lambda: S(id=1))
    m = mongo()
    monkeypatch.setattr(core, "context", AsyncMock(return_value=c))
    monkeypatch.setattr(
        core, "open_ticket", AsyncMock(return_value={"_id": "ticket_1"})
    )
    monkeypatch.setattr(walkthrough, "validate_destination", AsyncMock())
    run(walkthrough.deliver(bot, m, r, "owner"))
    rest.create_message.assert_not_awaited()
    saved = m.recruit_onboarding.update_one.call_args.args[1]["$set"]
    assert (
        saved["next_step"] == 1
        and saved["state"] == "awaiting"
        and saved["messages.0"] == 555
    )


def test_begin_checks_current_ticket_and_is_idempotent(monkeypatch):
    r = record()
    m = mongo()
    m.recruit_onboarding.find_one_and_update = AsyncMock(side_effect=[r, None])
    monkeypatch.setattr(core, "context", AsyncMock(return_value=context()))
    monkeypatch.setattr(
        core, "open_ticket", AsyncMock(return_value={"_id": "ticket_1"})
    )
    assert run(walkthrough.begin(object(), m, r, 20, 100))
    assert not run(walkthrough.begin(object(), m, r, 20, 100))
    assert (
        m.recruit_onboarding.find_one_and_update.call_args.args[0]["state"]
        == "awaiting"
    )
    with pytest.raises(core.SetupError):
        run(walkthrough.begin(object(), m, r, 20, 999))


def test_begin_refuses_resolved_or_replaced_ticket(monkeypatch):
    monkeypatch.setattr(core, "context", AsyncMock(return_value=context()))
    monkeypatch.setattr(
        core, "open_ticket", AsyncMock(return_value={"_id": "different"})
    )
    with pytest.raises(core.SetupError):
        run(walkthrough.begin(object(), mongo(), record(), 20, 100))


def test_walkthrough_pause_keeps_completed_checkpoint(monkeypatch):
    r = record()
    r.update(next_step=3, state="running")
    collection = S(
        find=lambda query: Cursor([r] if "due_at" in query else []),
        find_one_and_update=AsyncMock(return_value=r),
        update_one=AsyncMock(),
    )
    monkeypatch.setattr(
        walkthrough,
        "deliver",
        AsyncMock(side_effect=core.SetupError("Missing channel access")),
    )
    run(walkthrough.sweep(object(), S(recruit_onboarding=collection)))
    update = collection.update_one.call_args.args[1]
    assert update["$set"]["state"] == "paused"
    assert "next_step" not in update["$set"]
    assert "lease_until" in update["$unset"]


def test_core_authorization_rejects_nonrecruiter_even_if_command_visible():
    c = context()
    rest = S(
        fetch_guild=AsyncMock(return_value=c["guild"]),
        fetch_roles=AsyncMock(return_value=c["roles"]),
        fetch_member=AsyncMock(side_effect=[c["actor"], c["member"], c["me"]]),
    )
    bot = S(rest=rest, get_me=lambda: S(id=1))
    with pytest.raises(core.SetupError, match="Recruitment Team"):
        run(core.context(bot, mongo(), 10, 20, 30))


def test_core_authorization_accepts_configured_thread_recruiter_role():
    c = context()
    rest = S(
        fetch_guild=AsyncMock(return_value=c["guild"]),
        fetch_roles=AsyncMock(return_value=c["roles"]),
        fetch_member=AsyncMock(side_effect=[c["actor"], c["member"], c["me"]]),
    )
    m = mongo()
    m.ticket_setup.find_one.return_value = {"main_thread_recruiter_role": "40"}
    resolved = run(core.context(S(rest=rest, get_me=lambda: S(id=1)), m, 10, 20, 30))
    assert resolved["member"].id == 30


def test_stale_bulk_confirmation_does_not_change_roles(monkeypatch):
    c = context()
    m = mongo()
    monkeypatch.setattr(core, "session", AsyncMock(return_value=({"_id": "1"}, c)))
    changes = AsyncMock()
    monkeypatch.setattr(core, "change_roles", changes)
    ctx = S(defer=AsyncMock(), interaction=S(edit_initial_response=AsyncMock()))
    run(ui.action(ctx, "1:apply:all_clans:stale", mongo=m, bot=object()))
    changes.assert_not_awaited()
    assert "already used" in repr(ctx.interaction.edit_initial_response.call_args)


def test_quick_setup_retains_visitor_if_standard_roles_fail(monkeypatch):
    c = context()
    m = mongo()
    ctx = S(
        defer=AsyncMock(),
        user=S(id=20),
        interaction=S(edit_initial_response=AsyncMock()),
    )
    monkeypatch.setattr(core, "session", AsyncMock(return_value=({"_id": "1"}, c)))
    monkeypatch.setattr(core, "context", AsyncMock(return_value=c))
    monkeypatch.setattr(core, "clans", AsyncMock(return_value=[]))
    changes = AsyncMock(
        return_value={"added": [], "removed": [], "unchanged": [], "failed": ["Family"]}
    )
    monkeypatch.setattr(core, "change_roles", changes)
    run(ui.action(ctx, "1:quick", mongo=m, bot=object()))
    assert changes.await_count == 1 and "remove" not in changes.call_args.kwargs


def test_no_open_ticket_means_no_welcome_or_saved_walkthrough(monkeypatch):
    c = context()
    m = mongo()
    monkeypatch.setattr(
        core, "open_ticket", AsyncMock(side_effect=core.SetupError("No open ticket"))
    )
    with pytest.raises(core.SetupError):
        run(walkthrough.prepare(object(), m, c, {}, {}))
    m.recruit_onboarding.update_one.assert_not_awaited()
