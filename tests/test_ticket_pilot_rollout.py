import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace

import hikari
import pytest
from pymongo.errors import DuplicateKeyError

from extensions.commands import ticket_runtime
from extensions.commands.tickets import (
    handlers,
    legacy_migration,
    perms,
    rollout,
    setup,
    surface,
)


def _component(custom_id=None, *children):
    return SimpleNamespace(custom_id=custom_id, components=list(children))


def _message(*custom_ids):
    return SimpleNamespace(
        author=SimpleNamespace(id=7),
        components=[_component(None, *(_component(value) for value in custom_ids))]
    )


def _rollout_state(phase=ticket_runtime.PHASE_PILOT):
    legacy = ticket_runtime.IntakeSource(10, 20, 30)
    public = ticket_runtime.IntakeSource(11, 21, 31)
    pilot = ticket_runtime.IntakeSource(11, 22, 32)
    return ticket_runtime.RolloutState(
        phase=phase,
        revision=4,
        valid=True,
        legacy_intake=legacy,
        thread_intake=public,
        pilot_intake=pilot,
        pilot_user_ids=(50,),
        pilot_role_ids=(),
        pilot_ticket_types=("main", "fwa"),
    )


def test_panel_action_validation_walks_nested_components_and_fails_closed():
    surface.require_panel_actions(
        _message(*surface.THREAD_PUBLIC_PANEL_ACTIONS),
        surface.THREAD_PUBLIC_PANEL_ACTIONS,
        label="target public v2 panel",
    )
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


def test_v2_permissions_read_only_namespaced_thread_roles():
    config = SimpleNamespace(find_one=lambda *_args, **_kwargs: _async_result({
        "main_recruiter_role": 101,
        "fwa_recruiter_role": 102,
        "main_thread_recruiter_role": 201,
        "fwa_thread_recruiter_role": 202,
    }))
    assert asyncio.run(perms.recruiter_role_ids(
        SimpleNamespace(ticket_setup=config)
    )) == (201, 202)


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
    assert setup.public_binding_change_allowed(state, state.thread_intake) is True


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
            if (channel_id, message_id) == (21, 31):
                return _message(*surface.THREAD_PUBLIC_PANEL_ACTIONS)
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
            find_one=lambda *_args, **_kwargs: _async_result({
                "legacy_ticket_guild_id": 10,
                "ticket_target_guild_id": 11,
                "main_candidate_parent": 21,
                "fwa_candidate_parent": 21,
            })
        )
    )
    bot = SimpleNamespace(rest=Rest(), get_me=lambda: SimpleNamespace(id=7))

    asyncio.run(rollout._validate_rollout_readiness(bot, mongo, state))

    assert fetched == [(20, 30), (21, 31), (22, 32)]
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
                else (
                    surface.THREAD_PUBLIC_PANEL_ACTIONS
                    if identity == (21, 31)
                    else surface.PILOT_PANEL_ACTIONS
                )
            )
            return _message(*expected)

    monkeypatch.setattr(rollout, "thread_intake_ready", lambda: True)
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(
        find_one=lambda *_args, **_kwargs: _async_result({
            "legacy_ticket_guild_id": 10,
            "ticket_target_guild_id": 11,
            "main_candidate_parent": 21,
            "fwa_candidate_parent": 21,
        })
    ))
    for identity in ((20, 30), (21, 31), (22, 32)):
        bot = SimpleNamespace(rest=Rest(identity), get_me=lambda: SimpleNamespace(id=7))
        with pytest.raises(ValueError, match="missing expected controls"):
            asyncio.run(rollout._validate_rollout_readiness(bot, mongo, state))


def test_rollout_readiness_requires_public_v2_as_shared_candidate_parent(monkeypatch):
    monkeypatch.setattr(rollout, "thread_intake_ready", lambda: True)
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(
        find_one=lambda *_args, **_kwargs: _async_result({
            "legacy_ticket_guild_id": 10,
            "ticket_target_guild_id": 11,
            "main_candidate_parent": 21,
            "fwa_candidate_parent": 99,
        })
    ))
    with pytest.raises(ticket_runtime.TicketRuntimeError, match="shared Main/FWA"):
        asyncio.run(rollout._validate_rollout_readiness(
            SimpleNamespace(rest=SimpleNamespace(), get_me=lambda: SimpleNamespace(id=7)),
            mongo,
            _rollout_state(),
        ))


def test_rollout_controls_run_only_in_bound_target_guild(monkeypatch):
    state = _rollout_state()

    async def get_rollout(_mongo):
        return state

    monkeypatch.setattr(rollout.ticket_runtime, "get_rollout", get_rollout)
    mongo = SimpleNamespace(ticket_setup=SimpleNamespace(
        find_one=lambda *_args, **_kwargs: _async_result({
            "legacy_ticket_guild_id": 10,
            "ticket_target_guild_id": 11,
        })
    ))

    async def respond(*_args, **_kwargs):
        return None

    old_ctx = SimpleNamespace(guild_id=10, respond=respond)
    target_ctx = SimpleNamespace(guild_id=11, respond=respond)
    assert asyncio.run(rollout._rollout_for_guild(old_ctx, mongo)) is None
    assert asyncio.run(rollout._rollout_for_guild(target_ctx, mongo)) == state


def _async_result(value):
    async def result():
        return value

    return result()


class _SetupConfig:
    def __init__(self, document):
        self.document = deepcopy(document)
        self.write_calls = 0

    async def find_one(self, _query):
        return deepcopy(self.document)

    async def find_one_and_update(self, _query, update, **_kwargs):
        self.write_calls += 1
        self.document.update(update.get("$set", {}))
        for key in update.get("$unset", {}):
            self.document.pop(key, None)
        return deepcopy(self.document)


class _CrossServerSetupRest:
    def __init__(self):
        self.created = []
        self.deleted = []

    async def fetch_channel(self, channel_id):
        guild_id = 10 if int(channel_id) == 20 else 11
        return SimpleNamespace(
            id=int(channel_id), guild_id=guild_id, type=hikari.ChannelType.GUILD_TEXT
        )

    async def fetch_message(self, channel_id, message_id):
        assert (int(channel_id), int(message_id)) == (20, 30)
        return _message(*surface.LEGACY_PANEL_ACTIONS)

    async def fetch_guild(self, guild_id):
        return SimpleNamespace(id=int(guild_id), owner_id=999999)

    async def fetch_roles(self, guild_id):
        # @everyone with no permissions -- the pilot channel is not visible
        # to @everyone by default, so no warning is expected.
        return [SimpleNamespace(id=int(guild_id), permissions=0, is_managed=False)]

    async def create_message(self, *, channel, components, **_kwargs):
        message_id = 31 if int(channel) == 21 else 32
        self.created.append((int(channel), message_id, components))
        return SimpleNamespace(id=message_id)

    async def delete_message(self, channel_id, message_id):
        self.deleted.append((int(channel_id), int(message_id)))


def _setup_context():
    responses = []

    async def defer(**_kwargs):
        return None

    async def respond(content, **_kwargs):
        responses.append(content)

    return SimpleNamespace(
        guild_id=11,
        channel_id=22,
        user=SimpleNamespace(id=7),
        member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR),
        defer=defer,
        respond=respond,
        responses=responses,
    )


def _setup_command():
    command = setup.Setup()
    command.legacy_panel = "10/20/30"
    command.public_channel = SimpleNamespace(id=21, guild_id=11)
    command.tester = SimpleNamespace(id=50)
    command.tester_role = None
    command.replace = False
    return command


def test_cross_server_setup_verifies_both_admins_and_binds_two_owned_panels(monkeypatch):
    state = ticket_runtime.RolloutState(
        ticket_runtime.PHASE_LEGACY_ONLY, 0, False
    )
    admin_checks = []
    seeded = []

    async def get_rollout(_mongo):
        return state

    async def old_admin(_rest, guild_id, user_id):
        admin_checks.append((guild_id, user_id))
        return True

    async def seed(_mongo, **kwargs):
        seeded.append(kwargs)
        pilot_source = ticket_runtime.IntakeSource(**kwargs["pilot"]["intake"])
        return ticket_runtime.RolloutState(
            phase=ticket_runtime.PHASE_LEGACY_ONLY,
            revision=1,
            valid=True,
            legacy_intake=kwargs["legacy_intake"],
            thread_intake=kwargs["thread_intake"],
            pilot_intake=pilot_source,
            pilot_user_ids=(50,),
        )

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup.ticket_runtime, "seed_rollout", seed)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = _CrossServerSetupRest()
    config = _SetupConfig({
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_recruiter_role": 900,
    })
    ctx = _setup_context()

    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert admin_checks == [(10, 7)]
    assert config.document["legacy_ticket_guild_id"] == 10
    assert config.document["ticket_target_guild_id"] == 11
    assert config.document["main_recruiter_role"] == 900
    assert seeded[0]["legacy_intake"] == ticket_runtime.IntakeSource(10, 20, 30)
    assert seeded[0]["thread_intake"] == ticket_runtime.IntakeSource(11, 21, 31)
    assert surface.message_action_ids(SimpleNamespace(components=rest.created[0][2])) >= (
        surface.THREAD_PUBLIC_PANEL_ACTIONS
    )
    assert surface.message_action_ids(SimpleNamespace(components=rest.created[1][2])) >= (
        surface.PILOT_PANEL_ACTIONS
    )
    assert rest.deleted == []
    assert ctx.responses[-1].startswith("✅ Cross-server intake bound")


def test_setup_refuses_a_pilot_channel_that_is_not_a_guild_text_channel(monkeypatch):
    """The pilot panel used to post straight to `ctx.channel_id` with no
    fetch or type check. A thread, forum, or voice channel must be refused,
    with nothing posted."""
    state = ticket_runtime.RolloutState(ticket_runtime.PHASE_LEGACY_ONLY, 0, False)

    async def get_rollout(_mongo):
        return state

    async def old_admin(*_args):
        return True

    class Rest(_CrossServerSetupRest):
        async def fetch_channel(self, channel_id):
            channel = await super().fetch_channel(channel_id)
            if int(channel_id) == 22:
                channel.type = hikari.ChannelType.GUILD_PUBLIC_THREAD
            return channel

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = Rest()
    ctx = _setup_context()
    config = _SetupConfig({"_id": "config", "ticket_target_guild_id": 10})

    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert rest.created == []
    assert "not a thread, forum, or voice channel" in ctx.responses[-1]


def test_setup_warns_but_still_posts_when_everyone_can_view_the_pilot_channel(
    monkeypatch,
):
    """The docs allow a temporary restricted channel to share visibility as
    long as every tester already has recruiter/owner/Administrator access --
    so a pilot channel visible to @everyone is a warning, not a refusal."""
    state = ticket_runtime.RolloutState(ticket_runtime.PHASE_LEGACY_ONLY, 0, False)

    async def get_rollout(_mongo):
        return state

    async def old_admin(*_args):
        return True

    async def seed(_mongo, **kwargs):
        pilot_source = ticket_runtime.IntakeSource(**kwargs["pilot"]["intake"])
        return ticket_runtime.RolloutState(
            phase=ticket_runtime.PHASE_LEGACY_ONLY,
            revision=1,
            valid=True,
            legacy_intake=kwargs["legacy_intake"],
            thread_intake=kwargs["thread_intake"],
            pilot_intake=pilot_source,
            pilot_user_ids=(50,),
        )

    class Rest(_CrossServerSetupRest):
        async def fetch_roles(self, guild_id):
            return [SimpleNamespace(
                id=int(guild_id),
                permissions=int(hikari.Permissions.VIEW_CHANNEL),
                is_managed=False,
            )]

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup.ticket_runtime, "seed_rollout", seed)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = Rest()
    config = _SetupConfig({
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_recruiter_role": 900,
    })
    ctx = _setup_context()

    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert len(rest.created) == 2
    assert ctx.responses[-1].startswith("✅ Cross-server intake bound")
    assert "@everyone can view the pilot panel channel" in ctx.responses[-1]


def test_safe_phase_target_panel_relocation_precedes_parent_reconfiguration(
    monkeypatch,
):
    state = _rollout_state(ticket_runtime.PHASE_PREPARED)
    configured = []

    async def get_rollout(_mongo):
        return state

    async def old_admin(*_args):
        return True

    async def configure(_mongo, **kwargs):
        configured.append(kwargs)
        return ticket_runtime.RolloutState(
            phase=state.phase,
            revision=state.revision + 1,
            valid=True,
            legacy_intake=state.legacy_intake,
            thread_intake=kwargs["thread_intake"],
            pilot_intake=ticket_runtime.IntakeSource(**kwargs["pilot"]["intake"]),
            pilot_user_ids=state.pilot_user_ids,
            pilot_role_ids=state.pilot_role_ids,
            pilot_ticket_types=state.pilot_ticket_types,
        )

    class Rest(_CrossServerSetupRest):
        async def create_message(self, *, channel, components, **_kwargs):
            message_id = 51 if int(channel) == 41 else 52
            self.created.append((int(channel), message_id, components))
            return SimpleNamespace(id=message_id)

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup.ticket_runtime, "configure_rollout", configure)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = Rest()
    config = _SetupConfig({
        "_id": "config",
        "legacy_ticket_guild_id": 10,
        "ticket_target_guild_id": 11,
        "main_candidate_parent": 21,
        "fwa_candidate_parent": 21,
    })
    ctx = _setup_context()
    command = _setup_command()
    command.public_channel = SimpleNamespace(id=41, guild_id=11)
    command.replace = True

    asyncio.run(command.invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert configured[0]["thread_intake"] == ticket_runtime.IntakeSource(11, 41, 51)
    assert config.document["main_candidate_parent"] == 21
    assert config.document["fwa_candidate_parent"] == 21
    assert ctx.responses[-1].startswith("✅ Cross-server intake bound")

    relocated = ticket_runtime.RolloutState(
        phase=state.phase,
        revision=state.revision + 1,
        valid=True,
        legacy_intake=state.legacy_intake,
        thread_intake=ticket_runtime.IntakeSource(11, 41, 51),
        pilot_intake=ticket_runtime.IntakeSource(11, 22, 52),
        pilot_user_ids=state.pilot_user_ids,
        pilot_role_ids=state.pilot_role_ids,
        pilot_ticket_types=state.pilot_ticket_types,
    )
    monkeypatch.setattr(rollout, "thread_intake_ready", lambda: True)
    with pytest.raises(ticket_runtime.TicketRuntimeError, match="shared Main/FWA"):
        asyncio.run(rollout._validate_rollout_readiness(
            SimpleNamespace(rest=SimpleNamespace(), get_me=lambda: SimpleNamespace(id=7)),
            SimpleNamespace(ticket_setup=config),
            relocated,
        ))


def test_target_panel_relocation_rejects_unsafe_phase_before_post_or_write(
    monkeypatch,
):
    state = _rollout_state(ticket_runtime.PHASE_PILOT)

    async def get_rollout(_mongo):
        return state

    async def old_admin(*_args):
        raise AssertionError("unsafe relocation must stop before cross-guild auth")

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = _CrossServerSetupRest()
    config = _SetupConfig({
        "_id": "config",
        "legacy_ticket_guild_id": 10,
        "ticket_target_guild_id": 11,
        "main_candidate_parent": 21,
        "fwa_candidate_parent": 21,
    })
    ctx = _setup_context()
    command = _setup_command()
    command.public_channel = SimpleNamespace(id=41, guild_id=11)
    command.replace = True

    asyncio.run(command.invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert rest.created == []
    assert config.write_calls == 0
    assert "blocked during `pilot`" in ctx.responses[-1]


def test_cross_server_setup_restores_config_and_compensates_when_rollout_fails(
    monkeypatch,
):
    state = ticket_runtime.RolloutState(
        ticket_runtime.PHASE_LEGACY_ONLY, 0, False
    )

    async def get_rollout(_mongo):
        return state

    async def old_admin(*_args):
        return True

    async def seed(*_args, **_kwargs):
        raise ticket_runtime.RolloutConflict("seed failed")

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup.ticket_runtime, "seed_rollout", seed)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = _CrossServerSetupRest()
    original = {
        "_id": "config",
        "ticket_target_guild_id": 10,
        "main_recruiter_role": 900,
    }
    config = _SetupConfig(original)
    ctx = _setup_context()

    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert config.document == original
    assert rest.deleted == [(22, 32), (21, 31)]
    assert "prior guild binding was restored" in ctx.responses[-1]


def test_cross_server_setup_requires_old_server_admin_before_any_post(monkeypatch):
    async def get_rollout(_mongo):
        return ticket_runtime.RolloutState(
            ticket_runtime.PHASE_LEGACY_ONLY, 0, False
        )

    async def old_admin(*_args):
        return False

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = _CrossServerSetupRest()
    config = _SetupConfig({"_id": "config", "ticket_target_guild_id": 10})
    ctx = _setup_context()

    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert rest.created == []
    assert config.document == {"_id": "config", "ticket_target_guild_id": 10}
    assert "both the old and target servers" in ctx.responses[-1]


def test_cross_server_setup_rejects_legacy_guild_before_post_or_config_write(
    monkeypatch,
):
    async def get_rollout(_mongo):
        return ticket_runtime.RolloutState(
            ticket_runtime.PHASE_LEGACY_ONLY, 0, False
        )

    async def old_admin(*_args):
        raise AssertionError("same-guild setup must stop before cross-guild auth")

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = _CrossServerSetupRest()
    config = _SetupConfig({
        "_id": "config",
        "main_recruiter_role": 900,
    })
    ctx = _setup_context()
    ctx.guild_id = 10

    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=config),
    ))

    assert rest.created == []
    assert config.write_calls == 0
    assert config.document == {"_id": "config", "main_recruiter_role": 900}
    assert "different server" in ctx.responses[-1]


def test_cross_server_setup_rejects_non_bot_old_panel_before_post(monkeypatch):
    async def get_rollout(_mongo):
        return ticket_runtime.RolloutState(
            ticket_runtime.PHASE_LEGACY_ONLY, 0, False
        )

    async def old_admin(*_args):
        return True

    class Rest(_CrossServerSetupRest):
        async def fetch_message(self, channel_id, message_id):
            message = await super().fetch_message(channel_id, message_id)
            message.author.id = 999
            return message

    monkeypatch.setattr(setup.ticket_runtime, "get_rollout", get_rollout)
    monkeypatch.setattr(setup, "_guild_administrator", old_admin)
    rest = Rest()
    ctx = _setup_context()
    asyncio.run(_setup_command().invoke(
        ctx,
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=SimpleNamespace(ticket_setup=_SetupConfig({
            "_id": "config", "ticket_target_guild_id": 10,
        })),
    ))

    assert rest.created == []
    assert "not authored by this bot" in ctx.responses[-1]


def _rollout_command_context():
    responses = []

    async def defer(**_kwargs):
        return None

    async def respond(content, **_kwargs):
        responses.append(content)

    return SimpleNamespace(
        guild_id=11,
        user=SimpleNamespace(id=7),
        member=SimpleNamespace(permissions=hikari.Permissions.ADMINISTRATOR),
        defer=defer,
        respond=respond,
        responses=responses,
    )


def test_cross_server_promotion_is_one_phase_cas(monkeypatch):
    state = _rollout_state(ticket_runtime.PHASE_PILOT)
    calls = []

    async def allowed(*_args):
        return True

    async def rollout_state(*_args):
        return state

    async def ready(*_args):
        return None

    async def transition(_mongo, **kwargs):
        calls.append(kwargs)
        return ticket_runtime.RolloutState(
            **{
                **{field: getattr(state, field) for field in (
                    "revision", "valid", "legacy_intake", "thread_intake",
                    "pilot_intake", "pilot_user_ids", "pilot_role_ids",
                    "pilot_ticket_types",
                )},
                "phase": ticket_runtime.PHASE_THREAD_DEFAULT,
            }
        )

    monkeypatch.setattr(rollout, "_require_admin", allowed)
    monkeypatch.setattr(rollout, "_rollout_for_guild", rollout_state)
    monkeypatch.setattr(rollout, "_validate_rollout_readiness", ready)
    monkeypatch.setattr(rollout.ticket_runtime, "transition_rollout", transition)
    command = rollout.RolloutPromote()
    command.confirm = True
    ctx = _rollout_command_context()
    asyncio.run(command.invoke(
        ctx, bot=SimpleNamespace(), mongo=SimpleNamespace()
    ))

    assert len(calls) == 1
    assert calls[0]["expected_phase"] == ticket_runtime.PHASE_PILOT
    assert calls[0]["expected_revision"] == state.revision
    assert calls[0]["to_phase"] == ticket_runtime.PHASE_THREAD_DEFAULT


def test_cross_server_rollback_requires_live_exact_old_panel_before_cas(monkeypatch):
    state = _rollout_state(ticket_runtime.PHASE_THREAD_DEFAULT)
    transitions = []

    async def allowed(*_args):
        return True

    async def rollout_state(*_args):
        return state

    async def missing(*_args):
        raise ValueError("legacy controls missing")

    async def transition(*_args, **_kwargs):
        transitions.append(kwargs)

    monkeypatch.setattr(rollout, "_require_admin", allowed)
    monkeypatch.setattr(rollout, "_rollout_for_guild", rollout_state)
    monkeypatch.setattr(rollout, "_validate_legacy_intake", missing)
    monkeypatch.setattr(rollout.ticket_runtime, "transition_rollout", transition)
    command = rollout.RolloutRollback()
    command.confirm = True
    ctx = _rollout_command_context()
    asyncio.run(command.invoke(
        ctx, bot=SimpleNamespace(), mongo=SimpleNamespace()
    ))

    assert transitions == []
    assert "Rollback readiness failed" in ctx.responses[-1]
    assert "Nothing changed" in ctx.responses[-1]


def test_rollout_status_surfaces_a_stuck_console_refresh_error(monkeypatch):
    """`refresh_error`/`refresh_failures` were recorded on the shared-console
    hub state but never surfaced anywhere -- an operator had no way to see
    a permanently broken console short of reading logs. rollout-status must
    show it as a `console: <error>` line."""
    state = _rollout_state(ticket_runtime.PHASE_PILOT)
    drain = ticket_runtime.DrainStatus(
        legacy_open_tickets=0, legacy_slots=0, legacy_pending_workflows=0,
    )

    async def allowed(*_args):
        return True

    async def rollout_state(*_args):
        return state

    async def drain_status(*_args):
        return drain

    async def console_error(_mongo):
        return "ConsoleConfigurationError: console channel must deny View Channel to @everyone"

    async def count_documents(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(rollout, "_require_admin", allowed)
    monkeypatch.setattr(rollout.ticket_runtime, "get_rollout", rollout_state)
    monkeypatch.setattr(rollout.ticket_runtime, "legacy_drain_status", drain_status)
    monkeypatch.setattr(rollout.console, "refresh_status", console_error)

    mongo = SimpleNamespace(
        ticket_creation_state=SimpleNamespace(count_documents=count_documents),
    )
    ctx = _rollout_command_context()
    asyncio.run(rollout.RolloutStatus().invoke(ctx, mongo=mongo))

    lines = ctx.responses[-1].split("\n")
    assert (
        "console: ConsoleConfigurationError: console channel must deny "
        "View Channel to @everyone"
    ) in lines


def test_rollout_status_omits_console_line_when_healthy(monkeypatch):
    state = _rollout_state(ticket_runtime.PHASE_PILOT)
    drain = ticket_runtime.DrainStatus(
        legacy_open_tickets=0, legacy_slots=0, legacy_pending_workflows=0,
    )

    async def allowed(*_args):
        return True

    async def rollout_state(*_args):
        return state

    async def drain_status(*_args):
        return drain

    async def console_healthy(_mongo):
        return None

    async def count_documents(*_args, **_kwargs):
        return 0

    monkeypatch.setattr(rollout, "_require_admin", allowed)
    monkeypatch.setattr(rollout.ticket_runtime, "get_rollout", rollout_state)
    monkeypatch.setattr(rollout.ticket_runtime, "legacy_drain_status", drain_status)
    monkeypatch.setattr(rollout.console, "refresh_status", console_healthy)

    mongo = SimpleNamespace(
        ticket_creation_state=SimpleNamespace(count_documents=count_documents),
    )
    ctx = _rollout_command_context()
    asyncio.run(rollout.RolloutStatus().invoke(ctx, mongo=mongo))

    assert not any(line.startswith("console:") for line in ctx.responses[-1].split("\n"))


def _pilot_context(edits):
    async def defer(**_kwargs):
        return None

    async def edit_initial_response(**kwargs):
        edits.append(kwargs)

    return SimpleNamespace(
        guild_id=11,
        channel_id=22,
        user=SimpleNamespace(id=50, username="Tester"),
        member=SimpleNamespace(role_ids=(), display_name="Tester"),
        defer=defer,
        interaction=SimpleNamespace(
            message=SimpleNamespace(id=32),
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


def test_target_public_v2_surface_routes_and_claims_in_target_guild(monkeypatch):
    edits = []
    routed = []
    claimed = []

    async def route(*_args, **kwargs):
        routed.append(kwargs)
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_THREAD_DEFAULT,
            8,
            "thread_default",
        )

    async def claim(*_args, **kwargs):
        claimed.append(kwargs)
        return ticket_runtime.SlotClaim(False, None, {
            "_id": "ticket-open:50:main",
            "state": ticket_runtime.SLOT_CLEANUP_REQUIRED,
            "route": ticket_runtime.ROUTE_THREAD,
            "guild_id": 11,
            "workflow_id": "thread:50:main",
        })

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    handlers.user_cooldowns.clear()
    ctx = _pilot_context(edits)
    ctx.channel_id = 21
    ctx.interaction.message.id = 31

    asyncio.run(handlers.handle_create_ticket(
        ctx, "public:main", bot=SimpleNamespace(), mongo=SimpleNamespace()
    ))

    assert routed[0]["guild_id"] == 11
    assert routed[0]["channel_id"] == 21
    assert routed[0]["message_id"] == 31
    assert routed[0]["requested_route"] == ticket_runtime.ROUTE_THREAD
    assert claimed[0]["guild_id"] == 11
    assert handlers.user_cooldowns == {}


def test_cleanup_required_reply_names_the_recruiter_and_links_the_earlier_ticket(
    monkeypatch,
):
    edits = []

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_THREAD_DEFAULT,
            8,
            "thread_default",
        )

    async def claim(*_args, **_kwargs):
        return ticket_runtime.SlotClaim(False, None, {
            "_id": "ticket-open:50:main",
            "state": ticket_runtime.SLOT_CLEANUP_REQUIRED,
            "location_id": 999,
            "route": ticket_runtime.ROUTE_THREAD,
            "guild_id": 11,
            "workflow_id": "thread:50:main",
        })

    class TicketSetup:
        async def find_one(self, _query):
            return {"main_thread_recruiter_role": 555}

    class Cache:
        def get_role(self, role_id):
            assert role_id == 555
            return SimpleNamespace(name="Main Recruiter")

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    handlers.user_cooldowns.clear()
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_create_ticket(
        ctx,
        "public:main",
        bot=SimpleNamespace(cache=Cache()),
        mongo=SimpleNamespace(ticket_setup=TicketSetup()),
    ))

    message = edits[-1]["content"]
    assert "<#999>" in message
    assert "Main Recruiter" in message
    assert "quarantine" not in message.lower()
    assert "cleanup_required" not in message.lower()


def test_cleanup_required_reply_falls_back_without_link_or_role(monkeypatch):
    edits = []

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_THREAD_DEFAULT,
            8,
            "thread_default",
        )

    async def claim(*_args, **_kwargs):
        return ticket_runtime.SlotClaim(False, None, {
            "_id": "ticket-open:50:main",
            "state": ticket_runtime.SLOT_CLEANUP_REQUIRED,
            "route": ticket_runtime.ROUTE_THREAD,
            "guild_id": 11,
            "workflow_id": "thread:50:main",
        })

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    handlers.user_cooldowns.clear()
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_create_ticket(
        ctx, "public:main", bot=SimpleNamespace(), mongo=SimpleNamespace()
    ))

    message = edits[-1]["content"]
    assert "<#" not in message
    assert "recruiter" in message.lower()
    assert "quarantine" not in message.lower()
    assert "cleanup_required" not in message.lower()


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


def test_require_legacy_source_unchanged_tolerates_a_lease_timestamp_write():
    """Fingerprinting the whole `button_store` row made any unrelated write
    to it -- a delivery lease timestamp, in particular -- look like the
    source ticket itself had changed, wedging every resume behind "source
    ... changed" forever. The narrow fingerprint (status, ticket_type,
    user_id, channel_id) must not react to that kind of drift."""
    source = {
        "_id": "ticket_2",
        "type": "ticket",
        "channel_id": 2,
        "ticket_type": "main",
        "user_id": 30,
        "status": "approved",
        "delivery_lease_until": "2026-01-01T00:00:00Z",
        "delivery_lease_owner": "worker-a",
    }
    present_state = {
        "source": {"guild_id": 1, "channel_id": 2},
        "metadata": {
            "source_ticket_id": source["_id"],
            "source_ticket_fingerprint": legacy_migration._source_ticket_fingerprint(source),
        },
    }
    leased = {
        **source,
        "delivery_lease_until": "2026-06-01T12:00:00Z",
        "delivery_lease_owner": "worker-b",
    }

    result = asyncio.run(
        legacy_migration._require_legacy_source_unchanged(
            _source_mongo([leased]), present_state
        )
    )

    assert result == leased


def test_legacy_source_allows_a_stale_best_effort_mirror():
    """The `tickets` mirror written by the retired store-copy command is a
    best-effort snapshot and drifts on fields outside a ticket's identity,
    location, or status (claim state, timestamps). That drift alone must
    not raise "conflicting divergent" and block a legitimate migration."""
    source = {
        "_id": "ticket_2",
        "type": "ticket",
        "channel_id": 2,
        "guild_id": 1,
        "user_id": 30,
        "ticket_type": "main",
        "status": "approved",
        "claimed_by": None,
        "updated_at": "2026-01-01T00:00:00Z",
    }
    mirror = {
        **source,
        "venue": "channel",
        "claimed_by": 999,
        "updated_at": "2026-06-01T00:00:00Z",
    }

    found = asyncio.run(
        legacy_migration._legacy_source_ticket(
            _source_mongo([source], [mirror]), 1, 2
        )
    )

    assert found == source


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


def test_reclick_with_open_ticket_reaccesses_candidate_thread(monkeypatch):
    edits = []

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_THREAD_DEFAULT,
            8,
            "thread_default",
        )

    async def claim(*_args, **_kwargs):
        return ticket_runtime.SlotClaim(False, None, {
            "_id": "ticket-open:50:main",
            "state": ticket_runtime.SLOT_OPEN,
            "location_id": 999,
            "route": ticket_runtime.ROUTE_THREAD,
            "guild_id": 11,
            "workflow_id": "thread:50:main",
        })

    ticket_doc = {
        "_id": "ticket_1",
        "location": {"id": 999, "staff_space_id": 1000},
        "guild_id": 11,
        "user_id": 50,
        "status": "open",
    }

    async def find_by_location(_mongo, location_id):
        assert location_id == 999
        return ticket_doc

    reaccess_calls = []

    async def ensure_access(_rest, ticket, *, user_id):
        reaccess_calls.append((ticket["_id"], user_id))
        return True

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    monkeypatch.setattr(handlers.store, "find_by_location", find_by_location)
    monkeypatch.setattr(
        handlers.thread_service, "ensure_candidate_thread_access", ensure_access
    )
    handlers.user_cooldowns.clear()
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_create_ticket(
        ctx,
        "public:main",
        bot=SimpleNamespace(rest=SimpleNamespace()),
        mongo=SimpleNamespace(),
    ))

    assert reaccess_calls == [("ticket_1", 50)]
    assert "<#999>" in edits[-1]["content"]


def test_reclick_reply_survives_reaccess_failure(monkeypatch):
    """A vanished candidate thread must not stop the reply from going out."""
    edits = []

    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_THREAD_DEFAULT,
            8,
            "thread_default",
        )

    async def claim(*_args, **_kwargs):
        return ticket_runtime.SlotClaim(False, None, {
            "_id": "ticket-open:50:main",
            "state": ticket_runtime.SLOT_OPEN,
            "location_id": 999,
            "route": ticket_runtime.ROUTE_THREAD,
            "guild_id": 11,
            "workflow_id": "thread:50:main",
        })

    async def find_by_location(_mongo, _location_id):
        return {"_id": "ticket_1", "location": {"id": 999}, "guild_id": 11}

    async def ensure_access(*_args, **_kwargs):
        raise hikari.NotFoundError(
            url="", headers={}, raw_body=b"", code=10003, message="unknown channel"
        )

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    monkeypatch.setattr(handlers.store, "find_by_location", find_by_location)
    monkeypatch.setattr(
        handlers.thread_service, "ensure_candidate_thread_access", ensure_access
    )
    handlers.user_cooldowns.clear()
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_create_ticket(
        ctx,
        "public:main",
        bot=SimpleNamespace(rest=SimpleNamespace()),
        mongo=SimpleNamespace(),
    ))

    assert "<#999>" in edits[-1]["content"]


def test_my_ticket_button_shows_open_ticket_link_and_reaccesses(monkeypatch):
    edits = []
    ticket_doc = {
        "_id": "ticket_9",
        "location": {"id": 777, "staff_space_id": 778},
        "guild_id": 11,
        "user_id": 50,
        "status": "open",
        "ticket_type": "main",
    }

    async def find_open(_mongo, *, user_id, ticket_type):
        assert user_id == 50
        return ticket_doc if ticket_type == "main" else None

    reaccess_calls = []

    async def ensure_access(_rest, ticket, *, user_id):
        reaccess_calls.append((ticket["_id"], user_id))
        return True

    monkeypatch.setattr(handlers.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(
        handlers.thread_service, "ensure_candidate_thread_access", ensure_access
    )
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_my_ticket(
        ctx, "", bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
    ))

    assert reaccess_calls == [("ticket_9", 50)]
    assert "<#777>" in edits[-1]["content"]
    assert "flag" not in edits[-1]["content"].lower()


def test_my_ticket_button_shows_history_when_no_open_ticket(monkeypatch):
    edits = []

    async def find_open(_mongo, *, user_id, ticket_type):
        return None

    history = [{
        "ticket_type": "main",
        "ticket_number": 198,
        "status": "denied",
        "denied_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "guild_id": 11,
        "location": {"id": 555},
    }]

    async def history_for(_mongo, *, user_id, limit):
        assert user_id == 50
        assert limit == handlers.MAX_MY_TICKET_HISTORY
        return history

    monkeypatch.setattr(handlers.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(handlers.store, "history_for", history_for)
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_my_ticket(
        ctx, "", bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
    ))

    content = edits[-1]["content"]
    assert "Main #198" in content
    assert "Denied" in content
    assert "555" in content


def test_my_ticket_button_hints_when_nothing_found(monkeypatch):
    edits = []

    async def find_open(_mongo, *, user_id, ticket_type):
        return None

    async def history_for(_mongo, *, user_id, limit):
        return []

    monkeypatch.setattr(handlers.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(handlers.store, "history_for", history_for)
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_my_ticket(
        ctx, "", bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
    ))

    assert "no ticket yet" in edits[-1]["content"]


def test_thread_delete_event_marks_ticket_thread_missing_and_releases_slot(monkeypatch):
    ticket_doc = {
        "_id": "ticket_1",
        "location": {"id": 999, "staff_space_id": 1000},
        "guild_id": 11,
        "status": "open",
    }
    marked = []
    released = []

    async def find_by_location(_mongo, thread_id):
        assert thread_id == 999
        return ticket_doc

    async def mark_thread_missing(_mongo, ticket_id, *, thread_role):
        marked.append((ticket_id, thread_role))
        return SimpleNamespace(won=True, doc=ticket_doc)

    async def release(_mongo, ticket_id):
        released.append(ticket_id)

    async def notify(*_args, **_kwargs):
        return None

    monkeypatch.setattr(handlers.store, "find_by_location", find_by_location)
    monkeypatch.setattr(handlers.store, "mark_thread_missing", mark_thread_missing)
    monkeypatch.setattr(handlers, "_release_slot_for_missing_thread", release)
    monkeypatch.setattr(handlers.thread_service, "notify_console_after_change", notify)

    event = SimpleNamespace(thread_id=999, guild_id=11)
    asyncio.run(handlers.handle_ticket_thread_deleted(
        event, bot=SimpleNamespace(), mongo=SimpleNamespace(),
    ))

    assert marked == [("ticket_1", "candidate")]
    assert released == ["ticket_1"]


def test_thread_delete_event_ignores_a_thread_with_no_known_ticket(monkeypatch):
    async def find_by_location(_mongo, _thread_id):
        return None

    marked = []

    async def mark_thread_missing(*_args, **_kwargs):
        marked.append(True)

    monkeypatch.setattr(handlers.store, "find_by_location", find_by_location)
    monkeypatch.setattr(handlers.store, "mark_thread_missing", mark_thread_missing)

    event = SimpleNamespace(thread_id=555, guild_id=11)
    asyncio.run(handlers.handle_ticket_thread_deleted(
        event, bot=SimpleNamespace(), mongo=SimpleNamespace(),
    ))

    assert marked == []


def test_reclick_with_thread_missing_ticket_releases_slot_and_offers_a_new_one(
    monkeypatch,
):
    async def route(*_args, **_kwargs):
        return ticket_runtime.RouteDecision(
            ticket_runtime.ROUTE_THREAD,
            True,
            ticket_runtime.PHASE_THREAD_DEFAULT,
            8,
            "thread_default",
        )

    async def claim(*_args, **_kwargs):
        return ticket_runtime.SlotClaim(False, None, {
            "_id": "ticket-open:50:main",
            "state": ticket_runtime.SLOT_OPEN,
            "location_id": 999,
            "route": ticket_runtime.ROUTE_THREAD,
            "guild_id": 11,
            "workflow_id": "thread:50:main",
        })

    ticket_doc = {
        "_id": "ticket_1",
        "location": {"id": 999},
        "guild_id": 11,
        "thread_missing": {"thread_role": "candidate"},
    }

    async def find_by_location(_mongo, _location_id):
        return ticket_doc

    released = []

    async def release(_mongo, ticket_id):
        released.append(ticket_id)

    reaccess_calls = []

    async def ensure_access(*_args, **_kwargs):
        reaccess_calls.append(True)
        return True

    monkeypatch.setattr(handlers, "thread_intake_ready", lambda: True)
    monkeypatch.setattr(handlers.ticket_runtime, "route_public_intake", route)
    monkeypatch.setattr(handlers.ticket_runtime, "claim_open_slot", claim)
    monkeypatch.setattr(handlers.store, "find_by_location", find_by_location)
    monkeypatch.setattr(handlers, "_release_slot_for_missing_thread", release)
    monkeypatch.setattr(
        handlers.thread_service, "ensure_candidate_thread_access", ensure_access
    )
    handlers.user_cooldowns.clear()
    edits = []
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_create_ticket(
        ctx,
        "public:main",
        bot=SimpleNamespace(rest=SimpleNamespace()),
        mongo=SimpleNamespace(),
    ))

    assert released == ["ticket_1"]
    assert reaccess_calls == []
    assert "removed" in edits[-1]["content"]
    assert "<#999>" not in edits[-1]["content"]


def test_my_ticket_button_with_thread_missing_ticket_releases_slot(monkeypatch):
    edits = []
    ticket_doc = {
        "_id": "ticket_9",
        "location": {"id": 777},
        "guild_id": 11,
        "user_id": 50,
        "ticket_type": "main",
        "thread_missing": {"thread_role": "candidate"},
    }

    async def find_open(_mongo, *, user_id, ticket_type):
        return ticket_doc if ticket_type == "main" else None

    released = []

    async def release(_mongo, ticket_id):
        released.append(ticket_id)

    reaccess_calls = []

    async def ensure_access(*_args, **_kwargs):
        reaccess_calls.append(True)
        return True

    monkeypatch.setattr(handlers.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(handlers, "_release_slot_for_missing_thread", release)
    monkeypatch.setattr(
        handlers.thread_service, "ensure_candidate_thread_access", ensure_access
    )
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_my_ticket(
        ctx, "", bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
    ))

    assert released == ["ticket_9"]
    assert reaccess_calls == []
    assert "removed" in edits[-1]["content"]
    assert "<#777>" not in edits[-1]["content"]


def test_my_ticket_button_with_staff_thread_missing_keeps_the_candidate_link(
    monkeypatch,
):
    """A missing STAFF thread must not be treated like a missing candidate
    thread: the ticket stays open, the applicant's slot is kept, and My
    ticket still points at the (still alive) candidate thread."""
    edits = []
    ticket_doc = {
        "_id": "ticket_9",
        "location": {"id": 777},
        "guild_id": 11,
        "user_id": 50,
        "ticket_type": "main",
        "thread_missing": {"thread_role": "staff"},
    }

    async def find_open(_mongo, *, user_id, ticket_type):
        return ticket_doc if ticket_type == "main" else None

    released = []

    async def release(_mongo, ticket_id):
        released.append(ticket_id)

    reaccess_calls = []

    async def ensure_access(*_args, **_kwargs):
        reaccess_calls.append(True)
        return True

    monkeypatch.setattr(handlers.store, "find_open_for_applicant", find_open)
    monkeypatch.setattr(handlers, "_release_slot_for_missing_thread", release)
    monkeypatch.setattr(
        handlers.thread_service, "ensure_candidate_thread_access", ensure_access
    )
    ctx = _pilot_context(edits)

    asyncio.run(handlers.handle_my_ticket(
        ctx, "", bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
    ))

    assert released == []
    assert reaccess_calls == [True]
    assert "removed" not in edits[-1]["content"]
    assert "<#777>" in edits[-1]["content"]
