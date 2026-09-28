import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari
import pytest


@pytest.fixture(autouse=True)
def authoritative_lookup(monkeypatch):
    monkeypatch.setattr(
        staff.ticket_runtime, "_open_authoritative_tickets", AsyncMock(return_value=[])
    )


from extensions.commands.tickets import staff_creation as staff


def test_panel_searchable_picker_and_enabled_only_when_ready():
    blank = staff.panel({"_id": "x"})[0].build()[0]
    rows = blank["components"][1:]
    assert rows[0]["components"][0]["type"] == hikari.ComponentType.USER_SELECT_MENU
    assert rows[-1]["components"][0]["disabled"]
    complete = staff.panel({"_id": "x", "recruit_id": 123, "ticket_type": "fwa"})[
        0
    ].build()[0]
    assert not complete["components"][-1]["components"][0]["disabled"]


def test_private_state_requires_owner_guild_and_recruiter(monkeypatch):
    state = {"type": "staff_ticket_setup", "owner_id": 1, "guild_id": 2}
    monkeypatch.setattr(staff, "get_state", AsyncMock(return_value=state))
    recruiter = AsyncMock(return_value=True)
    monkeypatch.setattr(staff.perms, "is_recruiter", recruiter)
    ctx = SimpleNamespace(user=SimpleNamespace(id=9), guild_id=2, member=object())
    assert asyncio.run(staff.owned_state(ctx, object(), "x")) is None
    assert recruiter.await_count == 0
    ctx.user.id = 1
    assert asyncio.run(staff.owned_state(ctx, object(), "x")) is state
    recruiter.return_value = False
    assert asyncio.run(staff.owned_state(ctx, object(), "x")) is None


def test_existing_other_type_returns_ticket_without_claim(monkeypatch):
    ticket = {
        "_id": "ticket_1",
        "status": "open",
        "guild_id": 2,
        "location": {"id": 10, "staff_space_id": 11},
    }
    mongo = SimpleNamespace(
        ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={}))
    )
    bot = SimpleNamespace(
        rest=SimpleNamespace(
            fetch_member=AsyncMock(return_value=SimpleNamespace(is_bot=False))
        )
    )
    monkeypatch.setattr(staff, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(
        staff.store, "find_open_for_applicant", AsyncMock(return_value=ticket)
    )
    claim = AsyncMock()
    monkeypatch.setattr(staff.ticket_runtime, "claim_open_slot", claim)
    result = asyncio.run(
        staff._create_for_recruit(
            bot,
            mongo,
            {"guild_id": 2, "recruit_id": 3, "ticket_type": "fwa", "mode": "live"},
            SimpleNamespace(id=4),
            AsyncMock(),
        )
    )
    assert result is ticket
    assert claim.await_count == 0
    assert "/2/10" in staff.ticket_links(ticket)
    assert "/2/11" in staff.ticket_links(ticket)


def test_bot_recruit_rejected_before_lookup(monkeypatch):
    bot = SimpleNamespace(
        rest=SimpleNamespace(
            fetch_member=AsyncMock(return_value=SimpleNamespace(is_bot=True))
        )
    )
    lookup = AsyncMock()
    monkeypatch.setattr(staff.store, "find_open_for_applicant", lookup)
    try:
        asyncio.run(
            staff._create_for_recruit(
                bot,
                object(),
                {"guild_id": 2, "recruit_id": 3, "ticket_type": "main"},
                SimpleNamespace(id=4),
                AsyncMock(),
            )
        )
    except ValueError as error:
        assert "human" in str(error)
    else:
        raise AssertionError("bot recruit accepted")
    assert lookup.await_count == 0


def test_live_creation_uses_applicant_for_route_and_opener_for_attribution(monkeypatch):
    member = SimpleNamespace(
        id=3, is_bot=False, username="recruit", display_name="Recruit", role_ids=[99]
    )
    bot = SimpleNamespace(
        rest=SimpleNamespace(fetch_member=AsyncMock(return_value=member))
    )
    mongo = SimpleNamespace(
        ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={}))
    )
    monkeypatch.setattr(staff, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(
        staff.store, "find_open_for_applicant", AsyncMock(return_value=None)
    )
    source = SimpleNamespace(guild_id=2, channel_id=10, message_id=11)
    monkeypatch.setattr(
        staff.ticket_runtime,
        "get_rollout",
        AsyncMock(
            return_value=SimpleNamespace(phase="thread_default", thread_intake=source)
        ),
    )
    route = AsyncMock(
        return_value=SimpleNamespace(
            allowed=True, route=staff.ticket_runtime.ROUTE_THREAD, revision=8
        )
    )
    monkeypatch.setattr(staff.ticket_runtime, "route_public_intake", route)
    claim = SimpleNamespace(won=True)
    monkeypatch.setattr(
        staff.ticket_runtime, "claim_open_slot", AsyncMock(return_value=claim)
    )
    create = AsyncMock(return_value=SimpleNamespace(ticket={"_id": "created"}))
    monkeypatch.setattr(staff.thread_service, "create_live_thread_ticket", create)
    result = asyncio.run(
        staff._create_for_recruit(
            bot,
            mongo,
            {"guild_id": 2, "recruit_id": 3, "ticket_type": "fwa", "mode": "live"},
            SimpleNamespace(id=4),
            AsyncMock(),
        )
    )
    assert result["_id"] == "created"
    assert route.call_args.kwargs["user_id"] == 3
    assert route.call_args.kwargs["member_role_ids"] == [99]
    assert create.call_args.kwargs["user_id"] == 3
    assert create.call_args.kwargs["opened_by"] == 4
    assert create.call_args.kwargs["open_slot_claim"] is claim


def test_isolated_creation_checks_both_users_and_enters_scoped_dependencies(
    monkeypatch,
):
    from contextlib import asynccontextmanager

    member = SimpleNamespace(
        id=3, is_bot=False, username="recruit", display_name="Recruit", role_ids=[99]
    )
    bot = SimpleNamespace(
        rest=SimpleNamespace(fetch_member=AsyncMock(return_value=member))
    )
    live = SimpleNamespace(
        ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={}))
    )
    scoped = SimpleNamespace(
        is_ticket_test_scope=True,
        ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={"test": True})),
    )
    monkeypatch.setattr(staff.testing_service, "test_mongo", lambda value: scoped)
    monkeypatch.setattr(
        staff.testing_service,
        "active_window",
        AsyncMock(return_value={"generation": "g"}),
    )
    access = AsyncMock()
    monkeypatch.setattr(staff, "require_test_access", access)
    monkeypatch.setattr(staff.testing_service, "test_bot", lambda bot, mongo: bot)
    monkeypatch.setattr(
        staff.store, "find_open_for_applicant", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        staff.testing_service,
        "claim_test_slot",
        AsyncMock(return_value=SimpleNamespace(won=True)),
    )
    guarded = object()
    entered = []

    @asynccontextmanager
    async def dependencies(mongo, incoming_bot):
        entered.append((mongo, incoming_bot))
        yield None, guarded

    monkeypatch.setattr(staff, "test_dependencies", dependencies)
    create = AsyncMock(return_value=SimpleNamespace(ticket={"_id": "test"}))
    monkeypatch.setattr(staff.thread_service, "create_live_thread_ticket", create)
    route = AsyncMock()
    monkeypatch.setattr(staff.ticket_runtime, "route_public_intake", route)
    asyncio.run(
        staff._create_for_recruit(
            bot,
            live,
            {"guild_id": 2, "recruit_id": 3, "ticket_type": "fwa", "mode": "test"},
            SimpleNamespace(id=4),
            AsyncMock(),
        )
    )
    assert [call.args[0].user.id for call in access.call_args_list] == [4, 3]
    assert entered == [(scoped, bot)]
    assert create.call_args.kwargs["mongo"] is scoped
    assert create.call_args.kwargs["bot"] is guarded
    assert create.call_args.kwargs["config"] == {"test": True}
    assert route.await_count == 0


def test_entry_requires_shared_actions_binding_before_state_write(monkeypatch):
    ctx = SimpleNamespace(
        user=SimpleNamespace(id=4),
        guild_id=2,
        member=object(),
        defer=AsyncMock(),
        interaction=SimpleNamespace(
            message=SimpleNamespace(id=99, channel_id=10),
            edit_initial_response=AsyncMock(),
        ),
    )
    monkeypatch.setattr(
        staff.console,
        "_hub_state",
        AsyncMock(
            return_value={"guild_id": 2, "channel_id": 10, "actions_message_id": 11}
        ),
    )
    monkeypatch.setattr(staff.perms, "is_recruiter", AsyncMock(return_value=True))
    write = AsyncMock()
    monkeypatch.setattr(staff, "insert_state", write)
    asyncio.run(staff.open_setup(ctx, "hub", mongo=object()))
    assert write.await_count == 0
    assert ctx.defer.call_args.kwargs == {"ephemeral": True}
    ctx.interaction.message.id = 11
    asyncio.run(staff.open_setup(ctx, "hub", mongo=object()))
    assert write.await_count == 1
    state = write.call_args.args[1]
    assert state["owner_id"] == 4 and state["guild_id"] == 2
    assert "flags" not in ctx.interaction.edit_initial_response.call_args.kwargs
    payload = ctx.interaction.edit_initial_response.call_args.kwargs["components"][
        0
    ].build()[0]
    assert payload["type"] == hikari.ComponentType.CONTAINER


def test_actions_own_ack_and_never_route_as_modal_submissions():
    from extensions import components

    for name in (
        "ticket_v2_staff_create",
        "ticket_v2_staff_pick",
        "ticket_v2_staff_submit",
        "ticket_v2_staff_cancel",
    ):
        action = components.registered_functions[name]
        assert action.opens_modal and not action.is_modal
        assert action.no_return and not action.preload_state


def test_staff_lease_collision_never_enters_creation(monkeypatch):
    from pymongo.errors import DuplicateKeyError

    collection = SimpleNamespace(
        find_one_and_update=AsyncMock(side_effect=DuplicateKeyError("busy")),
        delete_one=AsyncMock(),
    )
    mongo = SimpleNamespace(ticket_automation_state=collection)
    create = AsyncMock()
    monkeypatch.setattr(staff, "_create_for_recruit", create)
    with pytest.raises(ValueError, match="already creating"):
        asyncio.run(
            staff.create_for_recruit(
                object(),
                mongo,
                {"recruit_id": 3, "mode": "live"},
                object(),
                AsyncMock(),
            )
        )
    assert create.await_count == 0
    assert collection.delete_one.await_count == 0


def test_closed_private_setup_cannot_be_reused(monkeypatch):
    state = {"type": "staff_ticket_setup", "owner_id": 1, "guild_id": 2, "closed": True}
    monkeypatch.setattr(staff, "get_state", AsyncMock(return_value=state))
    ctx = SimpleNamespace(user=SimpleNamespace(id=1), guild_id=2)
    assert asyncio.run(staff.owned_state(ctx, object(), "x")) is None


def test_legacy_other_kind_reused_before_claim(monkeypatch):
    legacy = {
        "guild_id": 2,
        "ticket_type": "main",
        "location": {"id": 90},
        "status": "open",
    }
    monkeypatch.setattr(
        staff.ticket_runtime,
        "_open_authoritative_tickets",
        AsyncMock(return_value=[(staff.ticket_runtime.ROUTE_LEGACY, legacy)]),
    )
    monkeypatch.setattr(
        staff.store, "find_open_for_applicant", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(staff, "thread_intake_ready", lambda: True)
    mongo = SimpleNamespace(
        ticket_setup=SimpleNamespace(find_one=AsyncMock(return_value={}))
    )
    bot = SimpleNamespace(
        rest=SimpleNamespace(
            fetch_member=AsyncMock(return_value=SimpleNamespace(is_bot=False))
        )
    )
    claim = AsyncMock()
    monkeypatch.setattr(staff.ticket_runtime, "claim_open_slot", claim)
    result = asyncio.run(
        staff._create_for_recruit(
            bot,
            mongo,
            {"guild_id": 2, "recruit_id": 3, "ticket_type": "fwa", "mode": "live"},
            SimpleNamespace(id=4),
            AsyncMock(),
        )
    )
    assert result == legacy
    assert claim.await_count == 0
