# extensions/commands/tickets/setup.py
"""
Ticket system setup command - posts the ticket creation embed
"""

import hikari
import lightbulb
from typing import List

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
)

from utils.constants import RED_ACCENT
from extensions.commands import ticket_runtime
from extensions.commands.tickets import perms, ticket
from extensions.commands.tickets import surface
from utils.mongo import MongoClient


SAFE_PUBLIC_REBIND_PHASES = frozenset({
    ticket_runtime.PHASE_LEGACY_ONLY,
    ticket_runtime.PHASE_PREPARED,
    ticket_runtime.PHASE_ROLLBACK_LEGACY,
})


def public_binding_change_allowed(
    state: ticket_runtime.RolloutState,
    source: ticket_runtime.IntakeSource,
) -> bool:
    if not state.valid:
        return True
    changes = any(
        current is None or current != source
        for current in (state.legacy_intake, state.thread_intake)
    )
    return not changes or state.phase in SAFE_PUBLIC_REBIND_PHASES


def create_ticket_embed() -> List[Container]:
    """Create the Warriors United Clan Entry embed"""
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## Warriors United Ticket Pilot"),
                Separator(divider=True),
                Text(content=(
                    "Approved testers can create a live entry ticket from one of the "
                    "categories below. The public ticket panel remains unchanged.\n\n"
                    "Once you have created one, please wait patiently for one of our "
                    "Recruiters to respond.\n\n"
                    "We want you to have the best experience possible here within "
                    "the Warriors United Family!"
                )),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
                # Buttons row
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="ticket_v2_create:pilot:main",
                            label="Main Clan Interest",
                            emoji="🏆",  # Trophy emoji
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="ticket_v2_create:pilot:fwa",
                            label="FWA Clan Interest",
                            emoji="💎",  # Diamond emoji
                        ),
                    ]
                ),
            ]
        )
    ]

    return components


def inactive_pilot_embed() -> List[Container]:
    """A fail-closed replacement when the new panel could not be bound."""
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="## Ticket Pilot Inactive"),
            Separator(divider=True),
            Text(content="This panel was not activated. Ask an administrator to run setup again."),
        ],
    )]


@ticket.register()
class Setup(
    lightbulb.SlashCommand,
    name="setup",
    description="Post and bind the restricted thread-ticket pilot panel (Admin only)"
):
    public_channel = lightbulb.channel(
        "public-channel",
        "Channel containing the existing legacy public ticket panel (first setup only)",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
        default=None,
    )
    public_message_id = lightbulb.string(
        "public-message-id",
        "Message ID of the existing legacy public ticket panel (first setup only)",
        default=None,
    )
    tester = lightbulb.user(
        "tester",
        "Initial pilot tester; optional when an allowlist already exists",
        default=None,
    )
    tester_role = lightbulb.role(
        "tester-role",
        "Initial pilot tester role; optional when an allowlist already exists",
        default=None,
    )
    replace = lightbulb.boolean(
        "replace",
        "Replace the configured pilot panel binding if it was deleted or moved",
        default=False,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        """Send the ticket creation embed"""

        # Defer the response immediately to avoid timeout
        await ctx.defer(ephemeral=True)

        # Check permissions
        if not await perms.is_target_admin(ctx.member, mongo):
            await ctx.respond(
                "❌ Administrator permission is required in the configured ticket guild."
            )
            return

        state = await ticket_runtime.get_rollout(mongo)
        guild_id = int(ctx.guild_id or 0)
        if not guild_id:
            await ctx.respond("❌ Run this command in the ticket server.", ephemeral=True)
            return
        if state.valid and any(
            source is not None and source.guild_id != guild_id
            for source in (state.legacy_intake, state.thread_intake, state.pilot_intake)
        ):
            await ctx.respond(
                "🛑 Rollout is bound to another server. Nothing was posted.",
                ephemeral=True,
            )
            return
        if state.valid and state.pilot_intake is not None and not self.replace:
            await ctx.respond(
                "🛑 A pilot panel is already bound at "
                f"<#{state.pilot_intake.channel_id}> / `{state.pilot_intake.message_id}`. "
                "Use `replace: true` only if it was deleted or must move.",
                ephemeral=True,
            )
            return

        existing_users = set(state.pilot_user_ids if state.valid else ())
        existing_roles = set(state.pilot_role_ids if state.valid else ())
        if self.tester is not None:
            existing_users.add(int(self.tester.id))
        if self.tester_role is not None:
            existing_roles.add(int(self.tester_role.id))
        if not existing_users and not existing_roles:
            await ctx.respond(
                "🛑 Supply `tester` or `tester-role` for the initial allowlist. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return

        supplied_public = self.public_channel is not None or bool(self.public_message_id)
        if supplied_public and (
            self.public_channel is None or not self.public_message_id
        ):
            await ctx.respond(
                "🛑 Supply both `public-channel` and `public-message-id`. Nothing was posted.",
                ephemeral=True,
            )
            return
        if supplied_public:
            public_guild_id = int(getattr(self.public_channel, "guild_id", 0) or 0)
            if public_guild_id != guild_id:
                await ctx.respond(
                    "🛑 The public panel must be in this server. Nothing was posted.",
                    ephemeral=True,
                )
                return
            try:
                public_message_id = int(str(self.public_message_id).strip())
            except (TypeError, ValueError):
                await ctx.respond(
                    "🛑 `public-message-id` must be a Discord message ID. Nothing was posted.",
                    ephemeral=True,
                )
                return
            public_source = ticket_runtime.IntakeSource(
                guild_id,
                int(self.public_channel.id),
                public_message_id,
            )
        else:
            public_source = state.legacy_intake if state.valid else None
        if public_source is None:
            await ctx.respond(
                "🛑 First setup requires the existing public panel channel and message ID.",
                ephemeral=True,
            )
            return
        if state.valid:
            if not public_binding_change_allowed(state, public_source):
                await ctx.respond(
                    f"🛑 Public-panel rebinding is blocked during `{state.phase}`. "
                    "Rollback and prepare first. Nothing was posted.",
                    ephemeral=True,
                )
                return
        if public_source.channel_id == int(ctx.channel_id):
            await ctx.respond(
                "🛑 The pilot panel must use a separate restricted channel. Nothing was posted.",
                ephemeral=True,
            )
            return

        try:
            public_message = await bot.rest.fetch_message(
                public_source.channel_id, public_source.message_id
            )
            surface.require_panel_actions(
                public_message,
                surface.LEGACY_PANEL_ACTIONS,
                label="public ticket panel",
            )
        except Exception:
            await ctx.respond(
                "🛑 The existing public panel message could not be verified. Nothing was posted.",
                ephemeral=True,
            )
            return

        posted = None
        try:
            posted = await bot.rest.create_message(
                channel=ctx.channel_id,
                components=create_ticket_embed(),
                mentions_everyone=False,
                user_mentions=False,
                role_mentions=False,
            )
            pilot_source = ticket_runtime.IntakeSource(
                guild_id,
                int(ctx.channel_id),
                int(posted.id),
            )
            pilot = {
                "intake": {
                    "guild_id": pilot_source.guild_id,
                    "channel_id": pilot_source.channel_id,
                    "message_id": pilot_source.message_id,
                },
                "user_ids": sorted(existing_users),
                "role_ids": sorted(existing_roles),
                "ticket_types": list(
                    state.pilot_ticket_types if state.valid else ("main", "fwa")
                ),
            }
            if state.valid:
                updated = await ticket_runtime.configure_rollout(
                    mongo,
                    expected_revision=state.revision,
                    actor_id=int(ctx.user.id),
                    legacy_intake=public_source,
                    thread_intake=public_source,
                    pilot=pilot,
                )
            else:
                updated = await ticket_runtime.seed_rollout(
                    mongo,
                    actor_id=int(ctx.user.id),
                    legacy_intake=public_source,
                    thread_intake=public_source,
                    pilot=pilot,
                )
                if updated.pilot_intake != pilot_source:
                    if any(
                        source is not None and source.guild_id != guild_id
                        for source in (
                            updated.legacy_intake,
                            updated.thread_intake,
                            updated.pilot_intake,
                        )
                    ):
                        raise ticket_runtime.RolloutConflict(
                            "rollout was concurrently bound to another server"
                        )
                    if not public_binding_change_allowed(updated, public_source):
                        raise ticket_runtime.RolloutConflict(
                            "public-panel rebinding became unsafe during setup"
                        )
                    updated = await ticket_runtime.configure_rollout(
                        mongo,
                        expected_revision=updated.revision,
                        actor_id=int(ctx.user.id),
                        legacy_intake=public_source,
                        thread_intake=public_source,
                        pilot=pilot,
                    )
            success_message = (
                "✅ Pilot panel posted and bound exactly to "
                f"<#{pilot_source.channel_id}> / `{pilot_source.message_id}` at "
                f"revision `{updated.revision}`. Run `/ticket-pilot rollout-prepare` "
                "when the tester allowlist is ready, then explicitly enable the pilot."
            )

        except Exception as e:
            if posted is not None:
                try:
                    await bot.rest.delete_message(ctx.channel_id, int(posted.id))
                except Exception:
                    try:
                        await bot.rest.edit_message(
                            ctx.channel_id,
                            int(posted.id),
                            components=inactive_pilot_embed(),
                        )
                    except Exception:
                        pass
            await ctx.respond(
                "❌ Pilot setup did not complete safely. Any unbound panel is inactive. "
                f"Error: {type(e).__name__}."
            )
            return

        # An acknowledgement failure must not delete a panel whose exact source
        # binding has already committed successfully.
        await ctx.respond(success_message)
