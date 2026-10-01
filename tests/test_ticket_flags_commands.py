import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from extensions.commands.tickets import flag_store, flags


def test_automatic_prior_denial_uses_bot_actor_and_atomic_marker(monkeypatch):
    @asynccontextmanager
    async def guard(*_args, **_kwargs):
        yield

    class Cursor:
        def limit(self, _count):
            return self

        async def to_list(self, *, length):
            return []

    async def pair(*_args, **_kwargs):
        return ({"_id": "old", "user_id": 5, "player_tags": [],
                 "created_at": object()},
                {"_id": "new", "user_id": 5, "player_tags": [],
                 "created_at": object()})

    captured = {}

    async def set_unlocked(_mongo, **kwargs):
        captured.update(kwargs)
        return {"_id": "auto", "automatic_rule": kwargs.get("automatic_rule")}

    monkeypatch.setattr(flag_store, "identity_guard", guard)
    monkeypatch.setattr(flag_store.store, "denial_history_pair_for", pair)
    monkeypatch.setattr(flag_store, "_set_flag_unlocked", set_unlocked)
    mongo = SimpleNamespace(ticket_flags=SimpleNamespace(find=lambda _query: Cursor()))

    document, created = asyncio.run(flag_store.ensure_prior_denial_flag(
        mongo, {"_id": "new", "user_id": 5, "player_tags": []},
        actor_id=999, actor_name="WU Wizard",
    ))

    assert created and document["automatic_rule"] == "prior_denial"
    assert captured["added_by"] == 999
    assert captured["added_by_name"] == "WU Wizard"
    assert captured["automatic_rule"] == "prior_denial"


@pytest.mark.parametrize("active", [True, False])
def test_existing_prior_denial_flag_is_preserved_without_automation_write(monkeypatch, active):
    @asynccontextmanager
    async def guard(*_args, **_kwargs):
        yield

    existing = {"_id": "manual", "active": active, "source": "Recruiter", "reason": "Keep me"}

    class Cursor:
        def __init__(self, query):
            self.query = query

        def limit(self, _count):
            return self

        async def to_list(self, *, length):
            return [existing] if self.query.get("active") is active else []

    async def pair(*_args, **_kwargs):
        return ({"_id": "old", "user_id": 5, "player_tags": []},
                {"_id": "new", "user_id": 5, "player_tags": []})

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("existing recruiter state must not be rewritten")

    monkeypatch.setattr(flag_store, "identity_guard", guard)
    monkeypatch.setattr(flag_store.store, "denial_history_pair_for", pair)
    monkeypatch.setattr(flag_store, "_set_flag_unlocked", forbidden)
    mongo = SimpleNamespace(ticket_flags=SimpleNamespace(find=lambda query: Cursor(query)))

    document, created = asyncio.run(flag_store.ensure_prior_denial_flag(
        mongo, {"_id": "new", "user_id": 5, "player_tags": []},
        actor_id=999, actor_name="WU Wizard",
    ))
    assert document == existing
    assert not created


@pytest.mark.parametrize("active", [True, False])
def test_legacy_ghosted_flag_preserves_existing_recruiter_state(monkeypatch, active):
    @asynccontextmanager
    async def guard(*_args, **_kwargs):
        yield

    existing = {"_id": "manual", "active": active, "reason": "Keep me"}

    class Cursor:
        def limit(self, _count):
            return self

        async def to_list(self, *, length):
            return [existing]

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("existing recruiter state must not be rewritten")

    monkeypatch.setattr(flag_store, "identity_guard", guard)
    monkeypatch.setattr(flag_store, "_set_flag_unlocked", forbidden)
    mongo = SimpleNamespace(ticket_flags=SimpleNamespace(find=lambda _query: Cursor()))

    document, created = asyncio.run(flag_store.ensure_legacy_ghosted_flag(
        mongo, {"user_id": 5, "player_tags": ["#ABC123"]},
        source_channel_id=123, source_channel_name="👻 main-applicant",
        actor_id=999, actor_name="WU Wizard",
    ))

    assert document == existing
    assert not created


def test_legacy_ghosted_flag_records_source_and_bot_actor(monkeypatch):
    @asynccontextmanager
    async def guard(*_args, **_kwargs):
        yield

    class Cursor:
        def limit(self, _count):
            return self

        async def to_list(self, *, length):
            return []

    captured = {}

    async def set_unlocked(_mongo, **kwargs):
        captured.update(kwargs)
        return {"_id": "auto", "automatic_rule": kwargs["automatic_rule"]}

    monkeypatch.setattr(flag_store, "identity_guard", guard)
    monkeypatch.setattr(flag_store, "_set_flag_unlocked", set_unlocked)
    mongo = SimpleNamespace(ticket_flags=SimpleNamespace(find=lambda _query: Cursor()))

    _document, created = asyncio.run(flag_store.ensure_legacy_ghosted_flag(
        mongo, {"user_id": 5, "player_tags": ["#ABC123"]},
        source_channel_id=123, source_channel_name="👻 main-applicant",
        actor_id=999, actor_name="WU Wizard",
    ))

    assert created
    assert captured["automatic_rule"] == "legacy_ghosted"
    assert captured["added_by"] == 999
    assert "#123" in captured["source"]
    assert "ghost marker" in captured["reason"]


def test_flag_command_normalizes_multiple_identities_without_duplicates():
    assert flags._discord_ids(
        "223456789012345678, 223456789012345678 323456789012345678"
    ) == ("223456789012345678", "323456789012345678")
    assert flags._tags("abc123, #ABC123 #other9") == ("#ABC123", "#OTHER9")


@pytest.mark.parametrize("value", ["123", "not-an-id", "123456789012345678901"])
def test_flag_command_rejects_non_snowflake_shaped_discord_ids(value):
    with pytest.raises(ValueError, match="17 to 20"):
        flags._discord_ids(value)


def test_flag_sources_preserve_the_decided_human_authority():
    assert flags.FLAG_SOURCES == {
        flag_store.FLAG_BLACKLISTED: "FWA Chocolate · FWA ban list",
        flag_store.FLAG_DENIED_BEFORE: "Warriors United ticket history",
        flag_store.FLAG_NOT_LOYAL: "Warriors United recruiter note",
        flag_store.FLAG_GHOSTED: "Warriors United recruiter ghosting report",
    }
    assert flag_store.normalize_kind("GHOSTED") == flag_store.FLAG_GHOSTED


def test_flag_reply_panel_reserves_text_budget_for_its_heading():
    view = flags._panel("Recruiter access required", "x" * 4000, accent=0)
    contents = [
        str(component.content)
        for component in view[0].components
        if getattr(component, "content", None) is not None
    ]
    assert sum(map(len, contents)) == flags.DISCORD_MESSAGE_TEXT_LIMIT


def test_flag_commands_use_authorized_store_boundaries():
    source = Path(flags.__file__).read_text(encoding="utf-8")
    assert "flag_store.set_flag_authorized(" in source
    assert "flag_store.deactivate_flag_authorized(" in source
    assert "flag_store.set_flag(" not in source
    assert "flag_store.deactivate_flag(" not in source


def test_flag_search_defers_before_permission_or_database_work(monkeypatch):
    events = []

    class Context:
        member = object()

        class Interaction:
            async def edit_initial_response(self, **kwargs):
                events.append(("respond", kwargs))

        interaction = Interaction()

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def denied(_member, _mongo):
        events.append(("permission", {}))
        return False

    from extensions.commands.tickets import perms

    monkeypatch.setattr(perms, "is_recruiter", denied)
    asyncio.run(flags.FlagsCommand.invoke._func(
        SimpleNamespace(identity="223456789012345678"), Context(), mongo=object(),
    ))

    assert [event[0] for event in events] == ["defer", "permission", "respond"]
    assert "Recruiter access required" in str(
        events[-1][1]["components"][0].build()
    )


def test_flag_remove_reports_identity_lock_contention_after_defer(monkeypatch):
    events = []

    class Context:
        member = object()
        user = SimpleNamespace(username="Recruiter")

        class Interaction:
            async def edit_initial_response(self, **kwargs):
                events.append(("respond", kwargs))

        interaction = Interaction()

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def busy(*_args, **_kwargs):
        raise flag_store.IdentityLockBusy("applicant identity is being updated; try again")

    monkeypatch.setattr(flag_store, "deactivate_flag_authorized", busy)
    asyncio.run(flags.FlagRemoveCommand.invoke._func(
        SimpleNamespace(flag_id="flag_123", reason="No longer applies"),
        Context(),
        mongo=object(),
        bot=object(),
    ))

    assert [event[0] for event in events] == ["defer", "respond"]
    assert "Flag not changed" in str(events[1][1]["components"][0].build())
    assert "try again" in str(events[1][1]["components"][0].build())


def test_flag_add_stays_successful_when_context_propagation_is_deferred(monkeypatch):
    events = []
    document = {
        "_id": "flag_123",
        "kind": flag_store.FLAG_NOT_LOYAL,
        "discord_ids": [223456789012345678],
        "player_tags": ["#ABC123"],
        "reason": "Recruiter note",
    }

    class Context:
        member = SimpleNamespace(id=7)
        user = SimpleNamespace(username="Recruiter")

        class Interaction:
            async def edit_initial_response(self, **kwargs):
                events.append(("respond", kwargs))

        interaction = Interaction()

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def save(*_args, **_kwargs):
        events.append(("saved", {}))
        return flag_store.FlagMutation("won", document)

    async def deferred(*_args, **_kwargs):
        events.append(("context-pending", {}))
        return False

    async def hub(*_args, **_kwargs):
        events.append(("hub", {}))
        return False

    monkeypatch.setattr(flag_store, "set_flag_authorized", save)
    monkeypatch.setattr(
        flags, "refresh_open_staff_contexts_for_flag_best_effort", deferred
    )
    monkeypatch.setattr(flags, "request_hub_refresh_best_effort", hub)
    asyncio.run(flags.FlagAddCommand.invoke._func(
        SimpleNamespace(
            kind=flag_store.FLAG_NOT_LOYAL,
            reason="Recruiter note",
            discord_ids="223456789012345678",
            player_tags="#ABC123",
        ),
        Context(),
        mongo=object(),
        bot=object(),
    ))

    assert [event[0] for event in events] == [
        "defer", "saved", "context-pending", "hub", "respond",
    ]
    assert "Flag saved" in str(events[-1][1]["components"][0].build())


def test_flag_remove_stays_successful_when_context_propagation_is_deferred(monkeypatch):
    events = []
    document = {
        "_id": "flag_123",
        "kind": flag_store.FLAG_NOT_LOYAL,
        "discord_ids": [223456789012345678],
        "player_tags": ["#ABC123"],
        "active": False,
    }

    class Context:
        member = SimpleNamespace(id=7)
        user = SimpleNamespace(username="Recruiter")

        class Interaction:
            async def edit_initial_response(self, **kwargs):
                events.append(("respond", kwargs))

        interaction = Interaction()

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def remove(*_args, **_kwargs):
        events.append(("removed", {}))
        return flag_store.FlagMutation("won", document)

    async def deferred(*_args, **_kwargs):
        events.append(("context-pending", {}))
        return False

    async def hub(*_args, **_kwargs):
        events.append(("hub", {}))
        return False

    monkeypatch.setattr(flag_store, "deactivate_flag_authorized", remove)
    monkeypatch.setattr(
        flags, "refresh_open_staff_contexts_for_flag_best_effort", deferred
    )
    monkeypatch.setattr(flags, "request_hub_refresh_best_effort", hub)
    asyncio.run(flags.FlagRemoveCommand.invoke._func(
        SimpleNamespace(flag_id="flag_123", reason="No longer applies"),
        Context(),
        mongo=object(),
        bot=object(),
    ))

    assert [event[0] for event in events] == [
        "defer", "removed", "context-pending", "hub", "respond",
    ]
    assert "Flag removed" in str(events[-1][1]["components"][0].build())


@pytest.mark.parametrize('channel',[101,102])
def test_flag_identity_infers_candidate_in_both_threads(monkeypatch,channel):
    from tests.test_ticket_storage_foundation import _mongo,_ticket
    ticket=_ticket();ticket['mentioned_tags']=['#FOREIGN']
    async def allowed(*a): return True
    monkeypatch.setattr(flags.perms,'is_recruiter',allowed)
    ctx=SimpleNamespace(channel_id=channel,guild_id=10,member=object())
    ids,tags=asyncio.run(flags.flag_identity_from_context(ctx,_mongo(ticket),(),()))
    assert ids==(str(ticket['user_id']),)
    assert tags==tuple(ticket['player_tags'])
    assert '#FOREIGN' not in tags


@pytest.mark.parametrize('ids,tags',[(('123',),()),((),('#PYY',))])
def test_explicit_flag_target_does_not_mix_in_ticket_identity(monkeypatch,ids,tags):
    async def forbidden(*a): raise AssertionError('No contextual lookup for an explicit target')
    monkeypatch.setattr(flags.store,'find_by_location',forbidden)
    assert asyncio.run(flags.flag_identity_from_context(None,None,ids,tags))==(ids,tags)


def test_flag_inference_does_not_read_before_authorization(monkeypatch):
    async def denied(*a): return False
    async def forbidden(*a): raise AssertionError('Unauthorized lookup')
    monkeypatch.setattr(flags.perms,'is_recruiter',denied)
    monkeypatch.setattr(flags.store,'find_by_location',forbidden)
    assert asyncio.run(flags.flag_identity_from_context(SimpleNamespace(member=None),None,(),()))==((),())


@pytest.mark.parametrize('guild,channel',[(11,101),(10,999)])
def test_flag_inference_rejects_foreign_guild_and_non_ticket(monkeypatch,guild,channel):
    from tests.test_ticket_storage_foundation import _mongo,_ticket
    async def allowed(*a): return True
    monkeypatch.setattr(flags.perms,'is_recruiter',allowed)
    with pytest.raises(ValueError,match='ticket or staff thread'):
        asyncio.run(flags.flag_identity_from_context(SimpleNamespace(member=object(),guild_id=guild,channel_id=channel),_mongo(_ticket()),(),()))


def test_flag_add_command_passes_inferred_identity_to_authorized_writer(monkeypatch):
    from tests.test_ticket_storage_foundation import _mongo,_ticket
    from extensions.commands.tickets import store
    ticket=_ticket();captured={}
    async def allowed(*a): return True
    async def write(*a,**kw):
        captured.update(kw)
        return SimpleNamespace(outcome=store.WON,doc={'discord_ids':list(kw['discord_ids']),'player_tags':list(kw['player_tags']),'reason':kw['reason']})
    async def nothing(*a,**kw): pass
    monkeypatch.setattr(flags.perms,'is_recruiter',allowed)
    monkeypatch.setattr(flags.flag_store,'set_flag_authorized',write)
    for name in ('_reconcile_ghost_names_best_effort','refresh_open_staff_contexts_for_flag_best_effort','request_hub_refresh_best_effort','_reply'):
        monkeypatch.setattr(flags,name,nothing)
    ctx=SimpleNamespace(defer=nothing,member=object(),guild_id=10,channel_id=102,user=SimpleNamespace(username='Recruiter'))
    command=SimpleNamespace(discord_ids=None,player_tags=None,kind=flags.flag_store.FLAG_GHOSTED,reason='Stopped responding')
    asyncio.run(flags.FlagAddCommand.invoke(command,ctx,mongo=_mongo(ticket),bot=object()))
    assert captured['discord_ids']==(str(ticket['user_id']),)
    assert captured['player_tags']==tuple(ticket['player_tags'])
