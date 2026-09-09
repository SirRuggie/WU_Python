"""Administrator controls for the thread-ticket pilot rollout."""

from __future__ import annotations

from collections.abc import Iterable

import hikari
import lightbulb

from extensions.commands import ticket_runtime
from extensions.commands.tickets import (
    perms,
    store,
    thread_intake_ready,
    thread_service,
    ticket,
)
from extensions.commands.tickets import surface
from utils.mongo import MongoClient


MIGRATION_PHASES = frozenset({
    ticket_runtime.PHASE_PILOT,
    ticket_runtime.PHASE_THREAD_DEFAULT,
    ticket_runtime.PHASE_THREAD_ONLY,
})


def _source_document(source: ticket_runtime.IntakeSource | None) -> dict[str, int]:
    if source is None:
        raise ticket_runtime.TicketRuntimeError("rollout intake sources are incomplete")
    return {
        "guild_id": int(source.guild_id),
        "channel_id": int(source.channel_id),
        "message_id": int(source.message_id),
    }


def _pilot_document(
    state: ticket_runtime.RolloutState,
    *,
    user_ids: Iterable[int] | None = None,
    role_ids: Iterable[int] | None = None,
    intake: ticket_runtime.IntakeSource | None = None,
) -> dict:
    source = intake or state.pilot_intake
    return {
        "intake": _source_document(source),
        "user_ids": sorted({
            int(value) for value in (
                state.pilot_user_ids if user_ids is None else user_ids
            ) if int(value) > 0
        }),
        "role_ids": sorted({
            int(value) for value in (
                state.pilot_role_ids if role_ids is None else role_ids
            ) if int(value) > 0
        }),
        "ticket_types": list(state.pilot_ticket_types),
    }


async def _require_admin(ctx, mongo: MongoClient) -> bool:
    if await perms.is_target_admin(getattr(ctx, "member", None), mongo):
        return True
    await ctx.respond(
        "❌ Administrator permission is required in the configured ticket server.",
        ephemeral=True,
    )
    return False


async def _rollout_for_guild(ctx, mongo: MongoClient) -> ticket_runtime.RolloutState | None:
    state = await ticket_runtime.get_rollout(mongo)
    if not state.valid:
        await ctx.respond(
            "🛑 Rollout is not configured. Run `/ticket-pilot setup` first.",
            ephemeral=True,
        )
        return None
    guild_id = store.as_int(getattr(ctx, "guild_id", 0))
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = store.as_int(config.get("ticket_target_guild_id"))
    legacy_guild_id = store.as_int(config.get("legacy_ticket_guild_id"))
    if (
        not guild_id
        or not target_guild_id
        or guild_id != target_guild_id
        or state.thread_intake is None
        or state.pilot_intake is None
        or state.legacy_intake is None
        or state.thread_intake.guild_id != target_guild_id
        or state.pilot_intake.guild_id != target_guild_id
        or not legacy_guild_id
        or state.legacy_intake.guild_id != legacy_guild_id
    ):
        await ctx.respond(
            "🛑 Rollout controls must run in the configured target server with "
            "matching cross-server bindings.",
            ephemeral=True,
        )
        return None
    return state


async def _configure_access(
    mongo: MongoClient,
    state: ticket_runtime.RolloutState,
    *,
    actor_id: int,
    user_ids: Iterable[int] | None = None,
    role_ids: Iterable[int] | None = None,
) -> ticket_runtime.RolloutState:
    return await ticket_runtime.configure_rollout(
        mongo,
        expected_revision=state.revision,
        actor_id=int(actor_id),
        legacy_intake=_source_document(state.legacy_intake),
        thread_intake=_source_document(state.thread_intake),
        pilot=_pilot_document(state, user_ids=user_ids, role_ids=role_ids),
    )


def _source_label(source: ticket_runtime.IntakeSource | None) -> str:
    if source is None:
        return "not configured"
    return f"<#{source.channel_id}> / `{source.message_id}`"


async def _validate_rollout_readiness(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    state: ticket_runtime.RolloutState,
) -> None:
    if not thread_intake_ready():
        raise ticket_runtime.TicketRuntimeError(
            "thread runtime startup recovery has not completed"
        )
    if not state.pilot_user_ids and not state.pilot_role_ids:
        raise ticket_runtime.TicketRuntimeError("pilot allowlist is empty")
    if state.legacy_intake is None or state.thread_intake is None:
        raise ticket_runtime.TicketRuntimeError("the public intake source is missing")
    if state.pilot_intake is None:
        raise ticket_runtime.TicketRuntimeError("the pilot intake source is missing")
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = store.as_int(config.get("ticket_target_guild_id"))
    legacy_guild_id = store.as_int(config.get("legacy_ticket_guild_id"))
    if (
        not target_guild_id
        or not legacy_guild_id
        or state.thread_intake.guild_id != target_guild_id
        or state.pilot_intake.guild_id != target_guild_id
        or state.legacy_intake.guild_id != legacy_guild_id
        or state.thread_intake == state.pilot_intake
    ):
        raise ticket_runtime.TicketRuntimeError(
            "cross-server intake bindings do not match ticket configuration"
        )
    candidate_parent_ids = {
        store.as_int(config.get("main_candidate_parent")),
        store.as_int(config.get("fwa_candidate_parent")),
    }
    if candidate_parent_ids != {state.thread_intake.channel_id}:
        raise ticket_runtime.TicketRuntimeError(
            "target public v2 panel must use the shared Main/FWA candidate-thread parent"
        )
    me = bot.get_me()
    if me is None:
        raise ticket_runtime.TicketRuntimeError("bot identity is unavailable")
    panel_checks = (
        (state.legacy_intake, surface.LEGACY_PANEL_ACTIONS, "legacy ticket panel"),
        (
            state.thread_intake,
            surface.THREAD_PUBLIC_PANEL_ACTIONS,
            "target public v2 panel",
        ),
        (state.pilot_intake, surface.PILOT_PANEL_ACTIONS, "pilot ticket panel"),
    )
    for source, actions, label in panel_checks:
        message = await bot.rest.fetch_message(source.channel_id, source.message_id)
        if int(getattr(getattr(message, "author", None), "id", 0) or 0) != int(me.id):
            raise ticket_runtime.TicketRuntimeError(f"{label} is not bot-authored")
        surface.require_panel_actions(message, actions, label=label)
    for ticket_type in ("main", "fwa"):
        parents = thread_service.parents_from_config(
            config, target_guild_id, ticket_type
        )
        await thread_service.validate_thread_parents(
            bot.rest, parents, bot_user_id=int(me.id)
        )
    await ticket_runtime.ensure_indexes(mongo)


async def _validate_legacy_intake(
    bot: hikari.GatewayBot,
    state: ticket_runtime.RolloutState,
) -> None:
    source = state.legacy_intake
    me = bot.get_me()
    if source is None or me is None:
        raise ticket_runtime.TicketRuntimeError("legacy intake identity is unavailable")
    message = await bot.rest.fetch_message(source.channel_id, source.message_id)
    if int(getattr(getattr(message, "author", None), "id", 0) or 0) != int(me.id):
        raise ticket_runtime.TicketRuntimeError("legacy ticket panel is not bot-authored")
    surface.require_panel_actions(
        message, surface.LEGACY_PANEL_ACTIONS, label="legacy ticket panel"
    )


async def migration_allowed(mongo: MongoClient) -> tuple[bool, str]:
    """Return the fail-closed migration gate used by both migration commands."""
    state = await ticket_runtime.get_rollout(mongo)
    if not state.valid:
        return False, "ticket rollout is not configured"
    if state.phase not in MIGRATION_PHASES:
        return False, f"legacy cloning is disabled during `{state.phase}`"
    return True, ""


@ticket.register()
class PilotUser(
    lightbulb.SlashCommand,
    name="pilot-user",
    description="Add or remove one pilot tester (Admin only)",
):
    action = lightbulb.string(
        "action",
        "Allow or remove this tester",
        choices=[
            lightbulb.Choice(name="Allow", value="allow"),
            lightbulb.Choice(name="Remove", value="remove"),
        ],
    )
    member = lightbulb.user("member", "Pilot tester")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        users = set(state.pilot_user_ids)
        if self.action == "allow":
            users.add(int(self.member.id))
        else:
            users.discard(int(self.member.id))
        try:
            updated = await _configure_access(
                mongo, state, actor_id=int(ctx.user.id), user_ids=users
            )
        except (ValueError, ticket_runtime.TicketRuntimeError) as error:
            await ctx.respond(f"🛑 Nothing changed: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ Pilot user access updated. Users: **{len(updated.pilot_user_ids)}**; "
            f"roles: **{len(updated.pilot_role_ids)}**.",
            ephemeral=True,
        )


@ticket.register()
class PilotRole(
    lightbulb.SlashCommand,
    name="pilot-role",
    description="Add or remove one pilot tester role (Admin only)",
):
    action = lightbulb.string(
        "action",
        "Allow or remove this role",
        choices=[
            lightbulb.Choice(name="Allow", value="allow"),
            lightbulb.Choice(name="Remove", value="remove"),
        ],
    )
    role = lightbulb.role("role", "Pilot tester role")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        roles = set(state.pilot_role_ids)
        if self.action == "allow":
            roles.add(int(self.role.id))
        else:
            roles.discard(int(self.role.id))
        try:
            updated = await _configure_access(
                mongo, state, actor_id=int(ctx.user.id), role_ids=roles
            )
        except (ValueError, ticket_runtime.TicketRuntimeError) as error:
            await ctx.respond(f"🛑 Nothing changed: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ Pilot role access updated. Users: **{len(updated.pilot_user_ids)}**; "
            f"roles: **{len(updated.pilot_role_ids)}**.",
            ephemeral=True,
        )


@ticket.register()
class RolloutStatus(
    lightbulb.SlashCommand,
    name="rollout-status",
    description="Show thread-ticket rollout bindings and drain safety (Admin only)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await ticket_runtime.get_rollout(mongo)
        drain = await ticket_runtime.legacy_drain_status(mongo)
        validity = "valid" if state.valid else "invalid / safe legacy default"
        pending_ids = ", ".join(drain.pending_delivery_ids) or "none"
        conflict_ids = ", ".join(drain.conflict_slot_ids) or "none"
        degraded_creations = await mongo.ticket_creation_state.count_documents({
            "kind": "thread_ticket_creation",
            "recovery_note": {"$exists": True},
        })
        await ctx.respond(
            "\n".join([
                f"**Phase:** `{state.phase}` ({validity}, revision `{state.revision}`)",
                f"**Old legacy panel:** {_source_label(state.legacy_intake)}",
                f"**Target public v2 panel:** {_source_label(state.thread_intake)}",
                f"**Pilot panel:** {_source_label(state.pilot_intake)}",
                f"**Pilot access:** {len(state.pilot_user_ids)} user(s), "
                f"{len(state.pilot_role_ids)} role(s)",
                "**Store conversion:** intentionally unavailable while both runtimes coexist",
                f"**Legacy drain:** {drain.legacy_open_tickets} open, "
                f"{drain.legacy_slots} slot(s), "
                f"{drain.legacy_pending_workflows} pending workflow(s)",
                f"**Pending legacy deliveries:** {drain.legacy_pending_deliveries} "
                f"(`{pending_ids}`)",
                f"**Unresolved open-ticket conflicts:** "
                f"{drain.unresolved_conflicts} (`{conflict_ids}`)",
                f"**Degraded ticket creations:** {degraded_creations}",
            ]),
            ephemeral=True,
        )


@ticket.register()
class RolloutPrepare(
    lightbulb.SlashCommand,
    name="rollout-prepare",
    description="Validate bindings and stage the restricted pilot (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm", "Move rollout to prepared after validation", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        try:
            await _validate_rollout_readiness(bot, mongo, state)
        except Exception as error:
            await ctx.respond(
                f"🛑 Pilot readiness failed: {error}. Nothing changed.", ephemeral=True
            )
            return
        if not self.confirm:
            await ctx.respond(
                "✅ Pilot readiness passed. Re-run with `confirm: true` to stage it.",
                ephemeral=True,
            )
            return
        try:
            if state.phase in {
                ticket_runtime.PHASE_LEGACY_ONLY,
                ticket_runtime.PHASE_ROLLBACK_LEGACY,
            }:
                state = await ticket_runtime.transition_rollout(
                    mongo,
                    expected_phase=state.phase,
                    expected_revision=state.revision,
                    to_phase=ticket_runtime.PHASE_PREPARED,
                    actor_id=int(ctx.user.id),
                )
            elif state.phase != ticket_runtime.PHASE_PREPARED:
                raise ticket_runtime.InvalidRolloutTransition(
                    f"cannot prepare from {state.phase!r}"
                )
        except ticket_runtime.TicketRuntimeError as error:
            await ctx.respond(f"🛑 Pilot was not prepared: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ Pilot staged at revision `{state.revision}`. Intake is still legacy-only. "
            "Run `/ticket-pilot rollout-pilot confirm: true` to enable testers.",
            ephemeral=True,
        )


@ticket.register()
class RolloutPilot(
    lightbulb.SlashCommand,
    name="rollout-pilot",
    description="Enable the prepared allowlisted pilot panel (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm", "Enable live pilot intake for allowlisted testers", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        if state.phase != ticket_runtime.PHASE_PREPARED:
            await ctx.respond(
                f"🛑 Pilot enablement requires `prepared`; current phase is `{state.phase}`.",
                ephemeral=True,
            )
            return
        try:
            await _validate_rollout_readiness(bot, mongo, state)
        except Exception as error:
            await ctx.respond(
                f"🛑 Pilot readiness failed: {error}. Nothing changed.", ephemeral=True
            )
            return
        if not self.confirm:
            await ctx.respond(
                "✅ Pilot is prepared. Re-run with `confirm: true` to enable tester clicks.",
                ephemeral=True,
            )
            return
        try:
            state = await ticket_runtime.transition_rollout(
                mongo,
                expected_phase=state.phase,
                expected_revision=state.revision,
                to_phase=ticket_runtime.PHASE_PILOT,
                actor_id=int(ctx.user.id),
            )
        except ticket_runtime.TicketRuntimeError as error:
            await ctx.respond(f"🛑 Pilot enablement failed safely: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ Restricted pilot enabled at revision `{state.revision}`. "
            "The public legacy panel remains unchanged.",
            ephemeral=True,
        )


@ticket.register()
class RolloutPromote(
    lightbulb.SlashCommand,
    name="rollout-promote",
    description="Make thread tickets the public intake default (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm", "Retire old intake and enable the target public v2 panel", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        try:
            await _validate_rollout_readiness(bot, mongo, state)
        except Exception as error:
            await ctx.respond(
                f"🛑 Promotion readiness failed: {error}. Nothing changed.",
                ephemeral=True,
            )
            return
        if state.phase != ticket_runtime.PHASE_PILOT:
            await ctx.respond(
                f"🛑 Promotion requires `pilot`; current phase is `{state.phase}`.",
                ephemeral=True,
            )
            return
        if not self.confirm:
            await ctx.respond(
                "✅ Promotion readiness passed. Re-run with `confirm: true` to switch intake.",
                ephemeral=True,
            )
            return
        try:
            state = await ticket_runtime.transition_rollout(
                mongo,
                expected_phase=state.phase,
                expected_revision=state.revision,
                to_phase=ticket_runtime.PHASE_THREAD_DEFAULT,
                actor_id=int(ctx.user.id),
            )
        except ticket_runtime.TicketRuntimeError as error:
            await ctx.respond(f"🛑 Promotion failed safely: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ Target-server thread intake is now public at revision `{state.revision}`. "
            "Existing legacy tickets remain active.",
            ephemeral=True,
        )


@ticket.register()
class RolloutRollback(
    lightbulb.SlashCommand,
    name="rollout-rollback",
    description="Return new public intake to the legacy runtime (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm", "Return new intake to legacy without closing tickets", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        if not self.confirm:
            await ctx.respond(
                "🛑 Nothing changed. Re-run with `confirm: true` to return intake to legacy.",
                ephemeral=True,
            )
            return
        if state.phase in {
            ticket_runtime.PHASE_LEGACY_ONLY,
            ticket_runtime.PHASE_ROLLBACK_LEGACY,
        }:
            await ctx.respond("✅ Legacy intake is already active.", ephemeral=True)
            return
        target = (
            ticket_runtime.PHASE_LEGACY_ONLY
            if state.phase == ticket_runtime.PHASE_PREPARED
            else ticket_runtime.PHASE_ROLLBACK_LEGACY
        )
        try:
            await _validate_legacy_intake(bot, state)
        except Exception as error:
            await ctx.respond(
                f"🛑 Rollback readiness failed: {error}. Nothing changed.",
                ephemeral=True,
            )
            return
        try:
            state = await ticket_runtime.transition_rollout(
                mongo,
                expected_phase=state.phase,
                expected_revision=state.revision,
                to_phase=target,
                actor_id=int(ctx.user.id),
            )
        except ticket_runtime.TicketRuntimeError as error:
            await ctx.respond(f"🛑 Rollback failed safely: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ New intake returned to legacy at revision `{state.revision}`. "
            "Existing thread tickets remain manageable.",
            ephemeral=True,
        )


@ticket.register()
class RolloutDrain(
    lightbulb.SlashCommand,
    name="rollout-drain",
    description="Verify legacy drain and optionally enter thread-only mode (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm", "Enter thread-only only when every legacy blocker is zero", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await _require_admin(ctx, mongo):
            return
        state = await _rollout_for_guild(ctx, mongo)
        if state is None:
            return
        drain = await ticket_runtime.legacy_drain_status(mongo)
        summary = (
            f"{drain.legacy_open_tickets} open legacy ticket(s), "
            f"{drain.legacy_slots} active legacy slot(s), "
            f"{drain.legacy_pending_workflows} pending legacy workflow(s), "
            f"{drain.legacy_pending_deliveries} pending delivery(s), "
            f"{drain.unresolved_conflicts} unresolved conflict(s)"
        )
        if drain.pending_delivery_ids:
            summary += "; delivery IDs: " + ", ".join(drain.pending_delivery_ids)
        if drain.conflict_slot_ids:
            summary += "; conflict slots: " + ", ".join(drain.conflict_slot_ids)
        if not self.confirm:
            await ctx.respond(
                f"**Legacy drain:** {summary}. Nothing changed.", ephemeral=True
            )
            return
        if state.phase != ticket_runtime.PHASE_THREAD_DEFAULT:
            await ctx.respond(
                f"🛑 Drain requires `thread_default`; current phase is `{state.phase}`.",
                ephemeral=True,
            )
            return
        if not drain.drained:
            await ctx.respond(f"🛑 Drain blocked: {summary}.", ephemeral=True)
            return
        try:
            state = await ticket_runtime.transition_rollout(
                mongo,
                expected_phase=state.phase,
                expected_revision=state.revision,
                to_phase=ticket_runtime.PHASE_THREAD_ONLY,
                actor_id=int(ctx.user.id),
            )
        except ticket_runtime.TicketRuntimeError as error:
            await ctx.respond(f"🛑 Drain failed safely: {error}.", ephemeral=True)
            return
        await ctx.respond(
            f"✅ Legacy runtime drained; thread-only phase is active at revision "
            f"`{state.revision}`.",
            ephemeral=True,
        )


__all__ = ["MIGRATION_PHASES", "migration_allowed"]
