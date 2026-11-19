"""Warrior Desk: account and staff request types, routing, perms, copy, end states."""
import asyncio
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import hikari
import pytest

from extensions.commands import content, ticket_runtime as runtime
from extensions.commands.tickets import (
    inactivity,
    lifecycle,
    perms,
    resolve,
    schema,
    settings,
    setup,
    store,
    thread_service,
)
from tests.test_ticket_creation import _ticket as base_ticket
from tests.test_ticket_runtime import Collection, _cross_rollout, _mongo as runtime_mongo
from utils import manage_web_worker
from cwl_web import manage_tickets

GUILD = 10
ROLES = {"main": 100, "fwa": 101, "account": 102, "staff": 103}
CONFIG = {
    "_id": "config",
    "ticket_target_guild_id": GUILD,
    "main_candidate_parent": 20, "main_staff_parent": 21, "main_thread_recruiter_role": 100,
    "fwa_candidate_parent": 20, "fwa_staff_parent": 22, "fwa_thread_recruiter_role": 101,
    "desk_channel_id": 30, "desk_staff_parent": 21,
    "account_thread_recruiter_role": 102, "staff_thread_recruiter_role": 103,
}


def _texts(components):
    found = []

    def walk(component):
        content_value = getattr(component, "content", None)
        if content_value:
            found.append(content_value)
        for child in getattr(component, "components", ()) or ():
            walk(child)

    for component in components:
        walk(component)
    return found


def _ticket(kind):
    doc = base_ticket()
    doc["ticket_type"] = kind
    doc["recruiter_role_id"] = ROLES[kind]
    return doc


# --- 4a types -------------------------------------------------------------

def test_ticket_types_include_desk_and_validate():
    assert schema.TICKET_TYPES == {"main", "fwa", "account", "staff"}
    assert schema.DESK_TICKET_TYPES == {"account", "staff"}
    assert schema.RECRUIT_TICKET_TYPES == {"main", "fwa"}
    assert schema.ticket_type("Account") == "account"
    with pytest.raises(schema.TicketSchemaError):
        schema.ticket_type("support")
    assert runtime._VALID_TICKET_TYPES == schema.TICKET_TYPES
    assert runtime._DESK_TICKET_TYPES == schema.DESK_TICKET_TYPES
    assert runtime._slot_id(5, "staff") == "ticket-open:5:staff"


# --- 4c rollout and routing -----------------------------------------------

def _desk_rollout(phase, desk=True):
    doc = _cross_rollout(phase)
    if desk:
        doc["desk_intake"] = {"guild_id": 11, "channel_id": 23, "message_id": 33}
    return doc


def test_rollout_parse_with_and_without_desk_intake():
    assert runtime._parse_rollout(_cross_rollout()).desk_intake is None
    assert runtime._parse_rollout(_cross_rollout()).valid
    parsed = runtime._parse_rollout(_desk_rollout(runtime.PHASE_THREAD_DEFAULT))
    assert parsed.valid
    assert parsed.desk_intake == runtime.IntakeSource(11, 23, 33)
    bad = _desk_rollout(runtime.PHASE_THREAD_DEFAULT)
    bad["desk_intake"] = {"guild_id": 0}
    assert runtime._parse_rollout(bad).desk_intake is None


def _route(mongo, kind, channel, message):
    return asyncio.run(runtime.route_public_intake(
        mongo, requested_route=runtime.ROUTE_THREAD, guild_id=11, channel_id=channel,
        message_id=message, user_id=50, ticket_type=kind,
    ))


def test_desk_routing_only_from_desk_panel_in_live_phases():
    for phase in runtime.VALID_PHASES:
        mongo = runtime_mongo(rollout=[_desk_rollout(phase)])
        live = phase in {runtime.PHASE_THREAD_DEFAULT, runtime.PHASE_THREAD_ONLY}
        for kind in ("account", "staff"):
            assert _route(mongo, kind, 23, 33).allowed is live
            # The Apply panel and a copied message never open desk requests.
            assert not _route(mongo, kind, 21, 31).allowed
            assert not _route(mongo, kind, 23, 99).allowed
        # Main keeps the Apply panel and rejects the desk panel.
        assert _route(mongo, "main", 21, 31).allowed is live
        assert not _route(mongo, "main", 23, 33).allowed


def test_desk_routing_rejected_without_desk_intake():
    mongo = runtime_mongo(rollout=[_desk_rollout(runtime.PHASE_THREAD_DEFAULT, desk=False)])
    decision = _route(mongo, "account", 23, 33)
    assert not decision.allowed and decision.reason == "wrong_desk_intake_source"
    assert _route(mongo, "main", 21, 31).allowed


def test_configure_rollout_keeps_or_sets_desk_intake():
    async def run():
        doc = _desk_rollout(runtime.PHASE_THREAD_DEFAULT)
        mongo = runtime_mongo(rollout=[doc])
        calls = []

        async def find_one_and_update(query, update, **_kwargs):
            calls.append(update)
            return {**doc, "revision": 5}

        mongo.ticket_rollout.find_one_and_update = find_one_and_update
        state = runtime._parse_rollout(doc)
        common = dict(
            expected_revision=4, actor_id=1, legacy_intake=state.legacy_intake,
            thread_intake=state.thread_intake,
            pilot={"intake": state.pilot_intake, "user_ids": [50], "role_ids": [], "ticket_types": ["main"]},
        )
        await runtime.configure_rollout(mongo, **common)
        assert "desk_intake" not in calls[0]["$set"]
        await runtime.configure_rollout(mongo, desk_intake=runtime.IntakeSource(11, 23, 77), **common)
        assert calls[1]["$set"]["desk_intake"] == {"guild_id": 11, "channel_id": 23, "message_id": 77}

    asyncio.run(run())


# --- 4b config ------------------------------------------------------------

def test_parents_from_config_desk_and_unknown_type():
    account = thread_service.parents_from_config(CONFIG, GUILD, "account")
    assert (account.candidate_parent_id, account.staff_parent_id, account.recruiter_role_id) == (30, 21, 102)
    # Main shares the staff parent, so each type sees the other roles on the thread.
    assert set(account.shared_staff_role_ids) == {100, 103}
    main = thread_service.parents_from_config(CONFIG, GUILD, "main")
    assert set(main.shared_staff_role_ids) == {102, 103}
    fwa = thread_service.parents_from_config(CONFIG, GUILD, "fwa")
    assert fwa.shared_staff_role_ids == ()
    with pytest.raises(thread_service.ThreadConfigurationError):
        thread_service.parents_from_config(CONFIG, GUILD, "bogus")
    fallback = {**CONFIG}
    del fallback["desk_staff_parent"]
    assert thread_service.parents_from_config(fallback, GUILD, "staff").staff_parent_id == 21
    missing = {k: v for k, v in CONFIG.items() if k != "staff_thread_recruiter_role"}
    with pytest.raises(thread_service.ThreadConfigurationError, match="staff_thread_recruiter_role"):
        thread_service.parents_from_config(missing, GUILD, "staff")


# --- 4d permissions -------------------------------------------------------

def _member(role=None, admin=False, guild=GUILD):
    return NS(
        id=7, guild_id=guild, role_ids=[role] if role else [],
        permissions=hikari.Permissions.ADMINISTRATOR if admin else hikari.Permissions.NONE,
    )


def _perm_mongo():
    return NS(ticket_setup=Collection([deepcopy(CONFIG)]))


@pytest.mark.parametrize("kind", ["main", "fwa", "account", "staff"])
def test_can_handle_matrix(kind):
    mongo = _perm_mongo()

    def can(member, ticket_type=kind):
        return asyncio.run(perms.can_handle(member, mongo, ticket_type))

    assert can(_member(admin=True))
    assert not can(_member(admin=True, guild=999))
    assert not can(_member())
    assert not can(None)
    assert can(_member(role=ROLES[kind]))
    for other, role in ROLES.items():
        if other == kind:
            continue
        # Recruit roles are interchangeable on recruit types, as before.
        both_recruit = kind in schema.RECRUIT_TICKET_TYPES and other in schema.RECRUIT_TICKET_TYPES
        assert can(_member(role=role)) is both_recruit, (kind, other)
    # is_recruiter keeps its original meaning; desk roles only pass is_ticket_staff.
    for other, role in ROLES.items():
        recruit = other in schema.RECRUIT_TICKET_TYPES
        assert asyncio.run(perms.is_recruiter(_member(role=role), mongo)) is recruit
        assert asyncio.run(perms.is_ticket_staff(_member(role=role), mongo))
    assert not asyncio.run(perms.is_recruiter(_member(), mongo))
    assert not asyncio.run(perms.is_ticket_staff(_member(), mongo))
    assert not asyncio.run(perms.is_ticket_staff(None, mongo))
    assert not asyncio.run(perms.is_ticket_staff(_member(role=ROLES["account"], guild=999), mongo))
    assert asyncio.run(perms.is_ticket_staff(_member(admin=True), mongo))
    assert not can(_member(role=100), "bogus")


def test_desk_only_role_has_no_recruit_actions_by_id(monkeypatch):
    from extensions.commands.tickets import console, flag_store, staff_creation
    mongo = _perm_mongo()
    desk = _member(role=102)
    assert not asyncio.run(perms.is_recruiter(desk, mongo))
    flagged = asyncio.run(flag_store.set_flag_authorized(
        mongo, member=desk, actor_name="x", kind=flag_store.FLAG_GHOSTED,
        discord_ids=5, source="test",
    ))
    assert flagged.outcome == store.UNAUTHORIZED
    sent = []

    async def notice(_ctx, text):
        sent.append(text)

    async def hub_state(_mongo):
        return {"guild_id": GUILD}

    monkeypatch.setattr(staff_creation, "notice", notice)
    monkeypatch.setattr(console, "_hub_state", hub_state)
    monkeypatch.setattr(console, "_is_shared_actions_source", lambda *_: True)
    ctx = NS(member=desk, guild_id=GUILD, user=NS(id=7), defer=AsyncMock())
    asyncio.run(staff_creation.open_setup(ctx, "hub", mongo=mongo))
    assert sent and "recruiter" in sent[0]


def test_main_role_acts_on_fwa_and_fwa_role_on_main():
    mongo = _perm_mongo()
    assert asyncio.run(perms.can_handle(_member(role=100), mongo, "fwa"))
    assert asyncio.run(perms.can_handle(_member(role=101), mongo, "main"))
    assert not asyncio.run(perms.can_handle(_member(role=100), mongo, "account"))
    assert not asyncio.run(perms.can_handle(_member(role=100), mongo, "staff"))
    assert not asyncio.run(perms.can_handle(_member(role=102), mongo, "main"))
    assert not asyncio.run(perms.can_handle(_member(role=102), mongo, "fwa"))
    assert asyncio.run(perms.can_handle(_member(admin=True), mongo, "account"))


def test_desk_role_opens_console_and_selects_desk_ticket():
    from extensions.commands.tickets import console
    mongo = _perm_mongo()
    doc = {**_ticket("account"), "type": "ticket", "status": "open"}
    mongo.tickets = Collection([doc])
    state = {"guild_id": GUILD}
    ctx = NS(member=_member(role=102), guild_id=GUILD, channel_id=1)

    async def run(role):
        ctx.member = _member(role=role)
        return await console._require_recruiter(
            NS(member=ctx.member, respond=AsyncMock()), mongo)

    assert asyncio.run(run(102)) is True
    assert asyncio.run(run(100)) is True
    assert asyncio.run(run(None)) is False


def test_desk_role_cannot_approve_recruit_and_main_role_cannot_act_on_desk():
    async def run():
        for ticket_type, role in (("main", 102), ("account", 100), ("staff", 100)):
            doc = _ticket(ticket_type)
            mongo = NS(ticket_setup=Collection([deepcopy(CONFIG)]), tickets=Collection([doc]))
            doc_runtime = {**doc, **store.RUNTIME_FILTER}
            monkey = AsyncMock(return_value=doc_runtime)
            real = store.find_one
            store.find_one = monkey
            try:
                result = await resolve.approve_ticket(
                    NS(), mongo, ticket_id=doc["_id"], member=_member(role=role), actor_name="x",
                    coc_client=NS(),
                )
                closed = await lifecycle.change(
                    NS(), mongo, ticket_id=doc["_id"], member=_member(role=role),
                    actor_name="x", kind="close", reason="Staff checked it.",
                )
            finally:
                store.find_one = real
            assert result.outcome in {store.UNAUTHORIZED, store.BLOCKED}, ticket_type
            assert closed.outcome == store.UNAUTHORIZED, ticket_type

    asyncio.run(run())


def test_staff_type_cannot_approve_or_deny_even_for_admin():
    async def run():
        doc = {**_ticket("staff"), **store.RUNTIME_FILTER}
        mongo = NS(ticket_setup=Collection([deepcopy(CONFIG)]))
        real = store.find_one
        store.find_one = AsyncMock(return_value=doc)
        try:
            for kind in (resolve.KIND_APPROVE, resolve.KIND_DENY_CUSTOM):
                result = await resolve._resolve_ticket(
                    NS(), mongo, ticket_id=doc["_id"], kind=kind, member=_member(admin=True),
                    actor_name="x", reason="Not a recruit.", coc_client=NS(),
                )
                assert result.outcome == store.BLOCKED
        finally:
            store.find_one = real

    asyncio.run(run())


def test_account_cannot_use_default_denial_bodies():
    async def run():
        doc = {**_ticket("account"), **store.RUNTIME_FILTER}
        mongo = NS(ticket_setup=Collection([deepcopy(CONFIG)]))
        real = store.find_one
        store.find_one = AsyncMock(return_value=doc)
        try:
            for kind in (resolve.KIND_DENY_FWA, resolve.KIND_DENY_MAIN):
                result = await resolve._resolve_ticket(
                    NS(), mongo, ticket_id=doc["_id"], kind=kind, member=_member(admin=True),
                    actor_name="x", coc_client=NS(),
                )
                assert result.outcome == store.BLOCKED
        finally:
            store.find_one = real

    asyncio.run(run())


# --- 4e creation copy -----------------------------------------------------

def test_welcome_and_opening_copy_for_desk_types():
    account = _texts(thread_service._candidate_welcome_components(_ticket("account")))
    assert account[0] == "## ➕ Add another account"
    assert account[1] == "<@30> Answer here. Staff check your accounts."
    staff = _texts(thread_service._candidate_welcome_components(_ticket("staff")))
    assert staff[0] == "## 💬 Contact staff"
    assert staff[1] == "<@30> Tell us what you need. Staff reply here."
    for kind in ("account", "staff"):
        opening = _texts(thread_service._staff_opening_components(_ticket(kind)))
        assert f"<@&{ROLES[kind]}> a member opened a request." in opening
        joined = "\n".join(opening).lower()
        assert "new applicant" not in joined and "ticket" not in joined
    main = _texts(thread_service._staff_opening_components(_ticket("main")))
    assert any("a new applicant is ready for review" in text for text in main)


def test_account_questionnaire_has_exactly_two_questions():
    assert thread_service.ACCOUNT_QUESTIONS == (
        "How many accounts do you want to add?",
        "Send the player tag of each account.",
    )
    texts = _texts(thread_service._questionnaire_components("account", None))
    assert "1. How many accounts do you want to add?\n2. Send the player tag of each account." in texts
    assert not any("Staff will reply as soon" in text for text in texts)
    assert not any("Town Hall" in text for text in texts)
    media = [c for c in thread_service._questionnaire_components("account", None)[0].components
             if isinstance(c, hikari.impl.MediaGalleryComponentBuilder)]
    assert media == []


class _Rest:
    def __init__(self):
        self.channels = {101: [], 102: []}
        self.creates = 0

    def fetch_messages(self, channel_id):
        messages = self.channels[channel_id]

        async def to_list():
            return list(messages)

        return NS(to_list=to_list)

    async def create_message(self, channel_id, **kwargs):
        self.creates += 1
        message = NS(
            id=1000 + self.creates, author=NS(id=7), content=kwargs.get("content", ""),
            components=kwargs.get("components", []),
        )
        self.channels[channel_id].append(message)
        return message

    async def fetch_my_user(self):
        return NS(id=7)

    async def fetch_guild(self, _guild_id):
        return NS(make_icon_url=lambda: None)


@pytest.mark.parametrize("kind,public,staff", [("account", 2, 1), ("staff", 1, 1), ("main", 2, 3)])
def test_opening_delivery_per_type(kind, public, staff):
    rest = _Rest()
    doc = _ticket(kind)
    doc["recruiter_role_id"] = 0
    asyncio.run(thread_service._deliver_opening_messages(rest, doc))
    assert (len(rest.channels[101]), len(rest.channels[102])) == (public, staff)
    # A retry posts nothing new (questionnaire and cards are found by title).
    before = rest.creates
    asyncio.run(thread_service._deliver_opening_messages(rest, doc))
    assert rest.creates == before


# --- 4f end states --------------------------------------------------------

def test_decision_copy_for_account():
    doc = {**_ticket("account"), "ticket_number": 3, "handled_by": 7, "handled_at": None,
           "denial_reason": "Not yours."}
    approved = "\n".join(_texts(resolve._staff_decision_components(doc, resolve.KIND_APPROVE)))
    assert "ACCOUNT #3" in approved and "Approved" in approved
    assert "Staff approved the account." in approved
    denied = "\n".join(_texts(resolve._staff_decision_components(doc, resolve.KIND_DENY_CUSTOM)))
    assert "ACCOUNT #3" in denied and "Denied" in denied
    assert "Staff denied the account." in denied


def test_account_cards_to_member():
    sent = []

    class Rest:
        async def create_message(self, **kwargs):
            sent.append("\n".join(_texts(kwargs["components"])))

    doc = _ticket("account")
    doc["location"] = {"id": 101}
    bot = NS(rest=Rest())
    asyncio.run(resolve.apply_approval(bot, NS(), ticket=doc))
    asyncio.run(resolve.apply_denial(bot, NS(), kind=resolve.KIND_DENY_CUSTOM, ticket=doc, reason="No."))
    assert "Staff approved your new account." in sent[0]
    assert "Congratulations" not in sent[0]
    assert ", staff denied your new account." in sent[1]


def test_staff_done_copy_and_lifecycle_cards():
    doc = {**_ticket("staff"), "closure_reason": "Handled.", "handled_by": 7, "handled_at": None}
    card = "\n".join(_texts(lifecycle.components(doc, "close")))
    assert "Staff marked this request as done." in card
    assert "application" not in card and "ticket" not in card.lower()
    account = "\n".join(_texts(lifecycle.components({**doc, "ticket_type": "account"}, "close")))
    assert "Staff closed this request." in account
    main = "\n".join(_texts(lifecycle.components({**doc, "ticket_type": "main"}, "close")))
    assert "Staff closed this application." in main


def test_console_labels_and_done_status():
    from extensions.commands.tickets import console

    assert console._status_meta("closed", "staff")[0] == "Done"
    assert console._status_meta("closed", "account")[0] == console.STATUS_META["closed"][0]
    assert console._ticket_type({"ticket_type": "account"}) == "account"
    assert console._ticket_label({"ticket_type": "staff", "ticket_number": 4}) == "Staff #4"
    assert console._TICKET_TYPE_LABEL["account"] == "Account"
    assert "account" in console.schema.TICKET_TYPES


def test_inactivity_skips_staff_type_only():
    base = {**store.RUNTIME_FILTER, "status": "open", "ticket_type": "main"}
    assert inactivity.eligible(base)
    assert inactivity.eligible({**base, "ticket_type": "account"})
    assert not inactivity.eligible({**base, "ticket_type": "staff"})


# --- 4g panel -------------------------------------------------------------

def test_desk_panel_components_and_registration():
    panel = setup.create_warrior_desk_embed()
    texts = _texts(panel)
    assert texts == [
        "## 🛡 Warrior Desk",
        "Already a Warrior? Select a button.\n\n"
        "**Add another account:** add a Clash account to the family.\n"
        "**Contact staff:** conflicts, strike appeals and other questions.",
    ]
    assert panel[0].accent_color == setup.WU_GOLD
    buttons = [b for row in panel[0].components if isinstance(row, hikari.impl.MessageActionRowBuilder)
               for b in row.components]
    assert [(b.custom_id, b.label, str(b.emoji)) for b in buttons] == [
        ("ticket_v2_create:public:account", "Add another account", "➕"),
        ("ticket_v2_create:public:staff", "Contact staff", "💬"),
    ]
    assert all(":" in b.custom_id and b.custom_id.count(":") == 2 for b in buttons)
    media = [c for c in panel[0].components if isinstance(c, hikari.impl.MediaGalleryComponentBuilder)]
    assert media[0].items[0].media == "assets/Gold_Footer.png"
    assert "warrior_desk" in content.DOCUMENTS
    assert content.document_renderer(content.DOCUMENTS["warrior_desk"]) is setup.create_warrior_desk_embed
    assert content.acknowledgement_id(panel, content.DOCUMENTS["warrior_desk"]) == "public:account"
    previewed = setup.create_warrior_desk_embed(preview=True)
    assert all(b.is_disabled for row in previewed[0].components
               if isinstance(row, hikari.impl.MessageActionRowBuilder) for b in row.components)
    for text in texts:
        assert "ticket" not in text.lower() and "support" not in text.lower()


def test_published_desk_panel_follows_desk_intake():
    async def run():
        mongo = runtime_mongo(rollout=[_desk_rollout(runtime.PHASE_THREAD_DEFAULT)])
        assert await content.published_for(mongo, 11, "warrior_desk") == {"channel_id": 23, "message_id": 33}
        mongo = runtime_mongo(rollout=[_desk_rollout(runtime.PHASE_THREAD_DEFAULT, desk=False)])
        assert await content.published_for(mongo, 11, "warrior_desk") is None

    asyncio.run(run())


# --- settings, web, worker ------------------------------------------------

DESK_KEYS = ("desk_channel_id", "desk_staff_parent", "account_thread_recruiter_role", "staff_thread_recruiter_role")


def test_settings_fields_and_web_validation_for_desk_keys():
    for key in DESK_KEYS:
        assert key in settings.FIELDS
        assert key in manage_tickets.FIELDS
    clean = manage_tickets.validated_settings({key: "1234567890123456" for key in DESK_KEYS})
    assert set(clean) == set(DESK_KEYS)
    with pytest.raises(ValueError):
        manage_tickets.validated_settings({"desk_channel_id": "12"})
    with pytest.raises(ValueError):
        manage_tickets.validated_settings({"unknown_key": "1234567890123456"})
    assert set(manage_tickets.history_values({}, "desk")) == set(DESK_KEYS)


def test_web_desk_part_and_tools_action():
    class Request(dict):
        match_info = {"part": "desk"}
        app = {}

    async def run():
        import cwl_web.manage_tickets as module
        cfg = deepcopy(CONFIG)

        class Db:
            ticket_setup = NS(find_one=AsyncMock(return_value=cfg))

        class Ctx:
            async def __aenter__(self):
                return Db()

            async def __aexit__(self, *_):
                return False

        real = (module.require_manage, module.mongo)
        module.require_manage = AsyncMock()
        module.mongo = lambda _request: Ctx()
        try:
            part = __import__("json").loads((await module.settings(Request())).text)
            Request.match_info = {}
            index = __import__("json").loads((await module.settings(Request())).text)
            Request.match_info = {"part": "tools"}
            tools = __import__("json").loads((await module.settings(Request())).text)
        finally:
            module.require_manage, module.mongo = real
        assert [f["key"] for f in part["fields"]] == list(DESK_KEYS)
        assert [f["label"] for f in part["fields"]] == [
            "Warrior Desk channel", "Staff thread channel", "Add account staff role", "Contact staff role",
        ]
        assert ("desk", "Warrior Desk") in [(d["id"], d["label"]) for d in index["documents"]]
        action = next(a for a in tools["actions"] if a["id"] == "restore_desk_entry")
        assert action["label"] == "Post Warrior Desk panel"
        assert action["confirm"] == "Post or repair the Warrior Desk panel in its channel?"

    asyncio.run(run())


def test_worker_allow_list_has_restore_desk_entry():
    assert ("ticket_settings", "restore_desk_entry") in manage_web_worker.ACTIONS
    assert ("ticket_settings", "restore_entry") in manage_web_worker.ACTIONS


def test_validate_reports_desk_not_set_or_passed(monkeypatch):
    async def run(cfg):
        calls = []

        async def validate_parents(_rest, parents, **_kwargs):
            calls.append(parents.candidate_parent_id)

        monkeypatch.setattr(thread_service, "validate_thread_parents", validate_parents)
        rest = NS(fetch_my_user=AsyncMock(return_value=NS(id=1)))
        mongo = runtime_mongo(rollout=[_cross_rollout(runtime.PHASE_THREAD_DEFAULT)])
        cfg = {**cfg, "main_candidate_parent": 21, "fwa_candidate_parent": 21}
        return await settings.validate(mongo, rest, cfg, 11), calls

    bare = {k: v for k, v in CONFIG.items() if k not in DESK_KEYS}
    bare["ticket_target_guild_id"] = 11
    result, calls = asyncio.run(run(bare))
    assert result == "Warrior Desk not set." and calls == [21, 21]
    full = {**CONFIG, "ticket_target_guild_id": 11}
    result, calls = asyncio.run(run(full))
    assert result == "Warrior Desk passed." and calls[-2:] == [30, 30]


# --- review rework --------------------------------------------------------

def _creation_state(kind, shared):
    return {
        "guild_id": GUILD, "ticket_type": kind,
        "candidate_parent_id": 30 if kind in schema.DESK_TICKET_TYPES else 20,
        "staff_parent_id": 21, "recruiter_role_id": ROLES[kind],
        "shared_staff_role_ids": list(shared), "staff_viewer_role_ids": [],
    }


def test_creation_recovery_config_for_desk_types():
    for kind, shared in (("account", (100, 103)), ("staff", (100, 102))):
        state = _creation_state(kind, shared)
        config = thread_service._recovery_config(state, kind, GUILD)
        parents = thread_service.parents_from_config(config, GUILD, kind)
        assert (parents.candidate_parent_id, parents.staff_parent_id) == (30, 21)
        assert parents.recruiter_role_id == ROLES[kind]
        assert set(parents.shared_staff_role_ids) == set(shared)


def test_creation_recovery_config_keeps_all_shared_roles_for_main():
    state = _creation_state("main", (102, 103))
    config = thread_service._recovery_config(state, "main", GUILD)
    parents = thread_service.parents_from_config(config, GUILD, "main")
    assert (parents.candidate_parent_id, parents.staff_parent_id, parents.recruiter_role_id) == (20, 21, 100)
    assert set(parents.shared_staff_role_ids) == {102, 103}


def test_account_decision_cards_are_recognised_for_crash_recovery():
    sent = []

    class Rest:
        async def create_message(self, **kwargs):
            sent.append(NS(content="", components=kwargs["components"]))

    doc = _ticket("account")
    doc["location"] = {"id": 101}
    bot = NS(rest=Rest())
    asyncio.run(resolve.apply_approval(bot, NS(), ticket=doc))
    asyncio.run(resolve.apply_denial(bot, NS(), kind=resolve.KIND_DENY_CUSTOM, ticket=doc, reason="No."))
    assert resolve._is_notification_card(sent[0], resolve.KIND_APPROVE)
    assert resolve._is_notification_card(sent[1], resolve.KIND_DENY_CUSTOM)
    assert not resolve._is_notification_card(sent[0], resolve.KIND_DENY_CUSTOM)


def test_desk_thread_names_recover_with_status_prefix():
    for kind in ("account", "staff"):
        base, staff_base = thread_service.thread_names(kind, 4, "Some Name", status="")
        closed, staff_closed = thread_service.thread_names(kind, 4, "Some Name", status="denied")
        assert closed != base
        assert closed in thread_service._name_variants(base)
        assert base in thread_service._name_variants(closed)
        assert staff_closed in thread_service._name_variants(staff_base)


def test_desk_creation_replies_say_request_not_ticket():
    from extensions.commands.tickets import handlers

    sent = []

    async def edit_error(_ctx, *, rest, content):
        sent.append(content)

    async def run(action_id, ready):
        ctx = NS(defer=AsyncMock())
        handlers_ready = handlers.thread_intake_ready
        handlers.thread_intake_ready = lambda: ready
        original = handlers.edit_error
        handlers.edit_error = edit_error
        try:
            await handlers.handle_create_ticket(
                ctx, action_id, bot=NS(rest=None), mongo=NS(), _source_message_id=1)
        finally:
            handlers.thread_intake_ready = handlers_ready
            handlers.edit_error = original

    asyncio.run(run("public:account", False))
    asyncio.run(run("bogus:account", True))
    asyncio.run(run("public:main", False))
    assert "ticket" not in sent[0].lower() and "request" in sent[0]
    assert "ticket" not in sent[1].lower()
    assert "ticket" in sent[2]


def _repair_harness(monkeypatch, *, cas_fails, delete_fails):
    calls = {"deleted": [], "created": []}
    state = NS(revision=3, desk_intake=None, legacy_intake=None, thread_intake=None,
               pilot_intake=NS(guild_id=1, channel_id=2, message_id=3),
               pilot_user_ids=(), pilot_role_ids=(), pilot_ticket_types=())

    async def get_rollout(_mongo):
        return state

    async def configure_rollout(*_a, **_k):
        if cas_fails:
            raise RuntimeError("cas")

    async def validate(*_a, **_k):
        return "ok"

    async def embed(*_a, **_k):
        return []

    async def create_message(channel, **_k):
        calls["created"].append(channel)
        return NS(id=555)

    async def delete_message(channel, message):
        calls["deleted"].append((channel, message))
        if delete_fails:
            raise RuntimeError("delete")

    monkeypatch.setattr(settings.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(settings.ticket_runtime, "configure_rollout", configure_rollout)
    monkeypatch.setattr(settings, "validate", validate)
    monkeypatch.setattr(settings.setup, "saved_warrior_desk_embed", embed)
    rest = NS(fetch_my_user=AsyncMock(return_value=NS(id=1)), create_message=create_message,
              delete_message=delete_message)
    ctx = NS(guild_id=GUILD, user=NS(id=7))
    mongo = NS(ticket_setup=Collection([deepcopy(CONFIG)]))
    return calls, ctx, mongo, NS(rest=rest)


def test_repair_desk_entry_happy_path(monkeypatch):
    calls, ctx, mongo, bot = _repair_harness(monkeypatch, cas_fails=False, delete_fails=False)
    result = asyncio.run(settings.repair_desk_entry(ctx, mongo, bot))
    assert result == "Warrior Desk panel posted and bound."
    assert calls["created"] == [30] and calls["deleted"] == []


def test_repair_desk_entry_cas_failure_removes_new_post(monkeypatch):
    calls, ctx, mongo, bot = _repair_harness(monkeypatch, cas_fails=True, delete_fails=False)
    with pytest.raises(RuntimeError, match="cas"):
        asyncio.run(settings.repair_desk_entry(ctx, mongo, bot))
    assert calls["deleted"] == [(30, 555)]


def test_repair_desk_entry_reports_failed_cleanup(monkeypatch, capsys):
    calls, ctx, mongo, bot = _repair_harness(monkeypatch, cas_fails=True, delete_fails=True)
    with pytest.raises(ValueError, match="could not be removed"):
        asyncio.run(settings.repair_desk_entry(ctx, mongo, bot))
    assert "desk_panel_cleanup_failed" in capsys.readouterr().out


def test_warrior_desk_has_no_generic_posting_channel_record():
    from cwl_web import manage_content

    ids = {item["id"] for item in manage_content.catalog()}
    assert "gauntlet--warrior_desk" in ids
    assert "destination--warrior_desk" not in ids
    assert "destination--apply" not in ids


def test_generic_publish_cannot_send_a_new_warrior_desk_post():
    from cwl_web import manage_delivery

    row = {"_id": "r1", "action": "send", "user_id": "1", "values": {
        "document": "warrior_desk", "template_revision": 1,
        "template": manage_delivery.fingerprint({"sections": ["x"], "media": {}}),
        "destination": 456, "target": None, "post": None}}
    bot = NS(rest=NS(create_message=AsyncMock()))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(content, "template_for", AsyncMock(return_value=(["x"], {}, 1)))
        patch.setattr(content, "destination_for", AsyncMock(return_value=456))
        patch.setattr(content, "published_for", AsyncMock(return_value=None))
        with pytest.raises(ValueError, match="Warrior Desk posts are created in Ticket settings"):
            asyncio.run(manage_delivery.publish(bot, NS(), row, NS()))
    bot.rest.create_message.assert_not_awaited()
