import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from extensions.commands.tickets import flag_store, flags


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
    }


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
