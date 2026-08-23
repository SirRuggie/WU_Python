import asyncio
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands import ticket_runtime
from extensions.commands.tickets import handlers, legacy_migration, rollout, setup, surface


def _component(custom_id=None, *children):
    return SimpleNamespace(custom_id=custom_id, components=list(children))


def _message(*custom_ids):
    return SimpleNamespace(
        components=[_component(None, *(_component(value) for value in custom_ids))]
    )


def _rollout_state(phase=ticket_runtime.PHASE_PILOT):
    public = ticket_runtime.IntakeSource(10, 20, 30)
    pilot = ticket_runtime.IntakeSource(10, 21, 31)
    return ticket_runtime.RolloutState(
        phase=phase,
        revision=4,
        valid=True,
        legacy_intake=public,
        thread_intake=public,
        pilot_intake=pilot,
        pilot_user_ids=(50,),
        pilot_role_ids=(),
        pilot_ticket_types=("main", "fwa"),
    )


def test_panel_action_validation_walks_nested_components_and_fails_closed():
    surface.require_panel_actions(
        _message(*surface.PILOT_PANEL_ACTIONS),
        surface.PILOT_PANEL_ACTIONS,
        label="pilot ticket panel",
    )
    with pytest.raises(ValueError, match="ticket_v2_create:pilot:fwa"):
        surface.require_panel_actions(
            _message("ticket_v2_create:pilot:main"),
            surface.PILOT_PANEL_ACTIONS,
            label="pilot ticket panel",
        )


@pytest.mark.parametrize(
    ("phase", "allowed"),
    [
        (ticket_runtime.PHASE_LEGACY_ONLY, True),
        (ticket_runtime.PHASE_PREPARED, True),
        (ticket_runtime.PHASE_PILOT, False),
        (ticket_runtime.PHASE_THREAD_DEFAULT, False),
        (ticket_runtime.PHASE_THREAD_ONLY, False),
        (ticket_runtime.PHASE_ROLLBACK_LEGACY, True),
    ],
)
def test_public_panel_rebinding_is_limited_to_safe_phases(phase, allowed):
    state = _rollout_state(phase)
    replacement = ticket_runtime.IntakeSource(10, 99, 100)

    assert setup.public_binding_change_allowed(state, replacement) is allowed
    assert setup.public_binding_change_allowed(state, state.legacy_intake) is True


@pytest.mark.parametrize(
    ("phase", "allowed"),
    [
        (ticket_runtime.PHASE_LEGACY_ONLY, False),
        (ticket_runtime.PHASE_PREPARED, False),
        (ticket_runtime.PHASE_ROLLBACK_LEGACY, False),
        (ticket_runtime.PHASE_PILOT, True),
        (ticket_runtime.PHASE_THREAD_DEFAULT, True),
        (ticket_runtime.PHASE_THREAD_ONLY, True),
    ],
)
def test_legacy_cloning_is_gated_by_rollout_phase(monkeypatch, phase, allowed):
    async def state(_mongo):
        return _rollout_state(phase)

    monkeypatch.setattr(legacy_migration.ticket_runtime, "get_rollout", state)

    actual, reason = asyncio.run(
        legacy_migration._migration_phase_allowed(SimpleNamespace())
    )

    assert actual is allowed
    assert bool(reason) is (not allowed)


def test_rollout_readiness_checks_runtime_and_exact_discord_controls(monkeypatch):
    state = _rollout_state()
    fetched = []
    validated = []

    class Rest:
        async def fetch_message(self, channel_id, message_id):
            fetched.append((channel_id, message_id))
            if (channel_id, message_id) == (20, 30):
                return _message(*surface.LEGACY_PANEL_ACTIONS)
            return _message(*surface.PILOT_PANEL_ACTIONS)

    async def validate(_rest, parents, *, bot_user_id):
        validated.append((parents, bot_user_id))

    async def indexes(_mongo):
        return None

    monkeypatch.setattr(rollout, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(
        rollout.thread_service,
        "parents_from_config",
        lambda _config, _guild_id, ticket_type: ticket_type,
    )
    monkeypatch.setattr(rollout.thread_service, "validate_thread_parents", validate)
    monkeypatch.setattr(rollout.ticket_runtime, "ensure_indexes", indexes)
    mongo = SimpleNamespace(
        ticket_setup=SimpleNamespace(
            find_one=lambda *_args, **_kwargs: _async_result({"configured": True})
        )
    )
    bot = SimpleNamespace(rest=Rest(), get_me=lambda: SimpleNamespace(id=7))

    asyncio.run(rollout._validate_rollout_readiness(bot, mongo, state))

    assert fetched == [(20, 30), (21, 31)]
    assert validated == [("main", 7), ("fwa", 7)]

    monkeypatch.setattr(rollout, "thread_intake_ready", lambda: False)
    with pytest.raises(ticket_runtime.TicketRuntimeError, match="startup recovery"):
        asyncio.run(rollout._validate_rollout_readiness(bot, mongo, state))


def test_rollout_readiness_rejects_wrong_public_or_pilot_controls(monkeypatch):
    state = _rollout_state()

    class Rest:
        def __init__(self, wrong_identity):
            self.wrong_identity = wrong_identity

        async def fetch_message(self, channel_id, message_id):
            identity = (channel_id, message_id)
            if identity == self.wrong_identity:
                return _message("unrelated")
            expected = (
                surface.LEGACY_PANEL_ACTIONS
                if identity == (20, 30)
                else surface.PILOT_PANEL_ACTIONS
            )
            return _message(*expected)

    monkeypatch.setattr(rollout, "thread_intake_ready", lambda: True)
    mongo = SimpleNamespace()
    for identity in ((20, 30), (21, 31)):
        bot = SimpleNamespace(rest=Rest(identity), get_me=lambda: SimpleNamespace(id=7))
        with pytest.raises(ValueError, match="missing expected controls"):
            asyncio.run(rollout._validate_rollout_readiness(bot, mongo, state))


def _async_result(value):
    async def result():
        return value

    return result()


def _pilot_context(edits):
    async def defer(**_kwargs):
        return None

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    return SimpleNamespace(
        guild_id=10,
        channel_id=21,
        user=SimpleNamespace(id=50, username="Tester"),
        member=SimpleNamespace(role_ids=(), display_name="Tester"),
        defer=defer,
        interaction=SimpleNamespace(
            message=SimpleNamespace(id=31),
            edit_initial_response=edit_initial_response,
        ),
    )


def test_copied_or_stale_pilot_panel_fails_before_slot_claim(monkeypatch):
    edits = []
    calls = []

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_REJECT,
            False,
            ticket_runtime.PHASE_PILOT,
            4,
            "pilot_denied",
        )

    async def claim(*_args, **_kwargs):
        calls.append("claim")
        raise AssertionError("a rejected panel must not claim a slot")

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    handlers.user_cooldowns.clear()

    asyncio.run(
        handlers.handle_create_ticket(
            _pilot_context(edits),
            "pilot:main",
            bot=SimpleNamespace(),
            mongo=SimpleNamespace(),
        )
    )

    assert calls == []
    assert "not active for you here" in edits[-1]["content"]
    assert handlers.user_cooldowns == {}


def test_config_read_failure_exactly_cancels_untouched_slot(monkeypatch):
    edits = []
    cancelled = []
    slot = {
        "_id": "ticket-open:50:main",
        "state": ticket_runtime.SLOT_RESERVED,
        "route": ticket_runtime.ROUTE_THREAD,
        "workflow_id": "thread:50:main",
    }

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_PILOT,
            12,
            "pilot_allowed",
        )

    async def claim(*_args, **kwargs):
        assert kwargs["rollout_revision"] == 12
        return ticket_runtime.SlotClaim(True, "owner-token", slot)

    async def cancel(_mongo, **kwargs):
        cancelled.append(kwargs)
        return True

    async def create(*_args, **_kwargs):
        raise AssertionError("Discord creation must not start after config-read failure")

    class Setup:
        async def find_one(self, *_args, **_kwargs):
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    monkeypatch.setattr(handlers.ticket_runtime, "cancel_open_slot", cancel)
    monkeypatch.setattr(handlers.thread_service, "create_live_thread_ticket", create)
    handlers.user_cooldowns.clear()

    asyncio.run(
        handlers.handle_create_ticket(
            _pilot_context(edits),
            "pilot:main",
            bot=SimpleNamespace(),
            mongo=SimpleNamespace(ticket_setup=Setup()),
        )
    )

    assert cancelled == [{
        "slot_id": "ticket-open:50:main",
        "owner_token": "owner-token",
        "workflow_id": "thread:50:main",
    }]
    assert handlers.user_cooldowns == {}
    assert edits[-1]["content"].endswith("Nothing was created.")


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)

    def limit(self, _amount):
        return self

    async def to_list(self, **_kwargs):
        return deepcopy(self.rows)


class _ReadCollection:
    def __init__(self, rows=()):
        self.rows = list(rows)

    def find(self, query):
        def value_at(row, path):
            value = row
            for part in path.split("."):
                if not isinstance(value, dict) or part not in value:
                    return None
                value = value[part]
            return value

        def matches(row, condition):
            for key, expected in condition.items():
                if key == "$or":
                    if not any(matches(row, item) for item in expected):
                        return False
                    continue
                actual = value_at(row, key)
                if isinstance(expected, dict) and "$in" in expected:
                    if actual not in expected["$in"]:
                        return False
                elif actual != expected:
                    return False
            return True

        return _Cursor(row for row in self.rows if matches(row, query))


def _source_mongo(legacy=(), thread=()):
    return SimpleNamespace(
        button_store=_ReadCollection(legacy),
        tickets=_ReadCollection(thread),
    )


def test_legacy_source_allows_absence_and_exact_channel_mirror():
    assert asyncio.run(
        legacy_migration._legacy_source_ticket(_source_mongo(), 1, 2)
    ) is None

    source = {
        "_id": "ticket_2",
        "type": "ticket",
        "channel_id": "2",
        "guild_id": 1,
        "status": "approved",
    }
    mirror = {
        **source,
        "channel_id": 2,
        "schema_version": 2,
        "venue": "channel",
    }
    found = asyncio.run(
        legacy_migration._legacy_source_ticket(
            _source_mongo([source], [mirror]), 1, 2
        )
    )

    assert found == source


def test_no_record_source_stays_absent_after_distinct_destination_insert():
    destination = {
        "_id": "ticket_101",
        "type": "ticket",
        "venue": "thread",
        "runtime": ticket_runtime.THREAD_RUNTIME,
        "channel_id": 101,
        "location": {"id": 101},
        "source": {"guild_id": 1, "channel_id": 2},
    }

    assert asyncio.run(
        legacy_migration._legacy_source_ticket(
            _source_mongo(thread=[destination]), 1, 2
        )
    ) is None


@pytest.mark.parametrize(
    "mirror",
    [
        {
            "_id": "ticket_2",
            "type": "ticket",
            "channel_id": 2,
            "guild_id": 1,
            "status": "denied",
            "venue": "channel",
        },
        {
            "_id": "ticket_2",
            "type": "ticket",
            "channel_id": 2,
            "guild_id": 1,
            "status": "approved",
            "venue": "thread",
            "runtime": ticket_runtime.THREAD_RUNTIME,
        },
    ],
)
def test_legacy_source_rejects_divergent_or_thread_runtime_mirror(mirror):
    source = {
        "_id": "ticket_2",
        "type": "ticket",
        "channel_id": 2,
        "guild_id": 1,
        "status": "approved",
    }
    with pytest.raises(legacy_migration.LegacyMigrationError, match="divergent"):
        asyncio.run(
            legacy_migration._legacy_source_ticket(
                _source_mongo([source], [mirror]), 1, 2
            )
        )


def test_legacy_source_absence_and_present_record_are_revalidated():
    absent_state = {
        "source": {"guild_id": 1, "channel_id": 2},
        "metadata": {"source_ticket_id": None, "source_ticket_fingerprint": ""},
    }
    assert asyncio.run(
        legacy_migration._require_legacy_source_unchanged(
            _source_mongo(), absent_state
        )
    ) is None

    source = {
        "_id": "ticket_2",
        "type": "ticket",
        "channel_id": 2,
        "status": "approved",
    }
    present_state = {
        "source": {"guild_id": 1, "channel_id": 2},
        "metadata": {
            "source_ticket_id": source["_id"],
            "source_ticket_fingerprint": legacy_migration._source_ticket_fingerprint(source),
        },
    }
    assert asyncio.run(
        legacy_migration._require_legacy_source_unchanged(
            _source_mongo([source]), present_state
        )
    ) == source

    changed = {**source, "status": "denied"}
    with pytest.raises(legacy_migration.LegacyMigrationError, match="changed"):
        asyncio.run(
            legacy_migration._require_legacy_source_unchanged(
                _source_mongo([changed]), present_state
            )
        )


class _InsertCollection:
    def __init__(self, existing=None):
        self.existing = deepcopy(existing)
        self.inserted = []

    async def insert_one(self, document):
        self.inserted.append(deepcopy(document))
        if self.existing is not None:
            raise DuplicateKeyError("duplicate")

    async def find_one(self, _query):
        return deepcopy(self.existing)


def test_migrated_thread_insert_is_distinct_and_idempotent_in_tickets_only():
    canonical = {
        "_id": "ticket_101",
        "type": "ticket",
        "venue": "thread",
        "ticket_type": "main",
        "ticket_number": 8,
        "guild_id": 10,
        "channel_id": 101,
        "thread_id": 102,
        "category_id": 20,
        "user_id": 50,
        "status": "approved",
        "location": {"id": 101, "staff_space_id": 102},
        "source": {"guild_id": 1, "channel_id": 2},
    }
    expected = {**canonical, "runtime": ticket_runtime.THREAD_RUNTIME}
    collection = _InsertCollection(existing=expected)
    mongo = SimpleNamespace(tickets=collection)

    result = asyncio.run(legacy_migration._insert_migrated_ticket(mongo, canonical))

    assert result == expected
    assert collection.inserted == [expected]
