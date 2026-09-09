# extensions/commands/tickets/setup.py
"""
Ticket system setup command - posts the ticket creation embed
"""

import asyncio
import re
from typing import List

import hikari
import lightbulb
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

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
from extensions.commands.tickets import ticket
from extensions.commands.tickets import surface
from utils.mongo import MongoClient


SAFE_PUBLIC_REBIND_PHASES = frozenset({
    ticket_runtime.PHASE_LEGACY_ONLY,
    ticket_runtime.PHASE_PREPARED,
    ticket_runtime.PHASE_ROLLBACK_LEGACY,
})


def _as_positive_int(value) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def parse_legacy_panel_reference(value: str | None) -> ticket_runtime.IntakeSource | None:
    """Parse a Discord message link or ``guild/channel/message`` identity."""
    if value is None:
        return None
    numbers = re.findall(r"\d+", str(value).strip().strip("<>"))
    if len(numbers) != 3:
        raise ValueError(
            "legacy-panel must be a Discord message link or guild/channel/message IDs"
        )
    guild_id, channel_id, message_id = (int(item) for item in numbers)
    if not guild_id or not channel_id or not message_id:
        raise ValueError("legacy-panel IDs must be positive")
    return ticket_runtime.IntakeSource(guild_id, channel_id, message_id)


async def _guild_administrator(
    rest: hikari.api.RESTClient,
    guild_id: int,
    user_id: int,
) -> bool:
    """Verify owner/Administrator from authoritative REST guild data."""
    try:
        guild, member, roles = await asyncio.gather(
            rest.fetch_guild(int(guild_id)),
            rest.fetch_member(int(guild_id), int(user_id)),
            rest.fetch_roles(int(guild_id)),
        )
    except (hikari.NotFoundError, hikari.ForbiddenError):
        return False
    if _as_positive_int(getattr(guild, "owner_id", 0)) == int(user_id):
        return True
    role_ids = {
        _as_positive_int(value) for value in (getattr(member, "role_ids", ()) or ())
    }
    role_ids.add(int(guild_id))
    permissions = hikari.Permissions.NONE
    for role in roles:
        if _as_positive_int(getattr(role, "id", 0)) in role_ids:
            permissions |= hikari.Permissions(getattr(role, "permissions", 0))
    return bool(permissions & hikari.Permissions.ADMINISTRATOR)


def public_binding_change_allowed(
    state: ticket_runtime.RolloutState,
    source: ticket_runtime.IntakeSource,
) -> bool:
    if not state.valid:
        return True
    changes = state.thread_intake is None or state.thread_intake != source
    return not changes or state.phase in SAFE_PUBLIC_REBIND_PHASES


def create_public_ticket_embed() -> List[Container]:
    """Create the target-guild public v2 intake panel."""
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content="## Warriors United Clan Entry"),
            Separator(divider=True),
            Text(content=(
                "Create an entry ticket from one of the categories below.\n\n"
                "Once you have created one, please wait patiently for one of our "
                "Recruiters to respond."
            )),
            Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ActionRow(components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="ticket_v2_create:public:main",
                    label="Main Clan Interest",
                    emoji="🏆",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="ticket_v2_create:public:fwa",
                    label="FWA Clan Interest",
                    emoji="💎",
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="ticket_v2_my_ticket",
                    label="My ticket",
                    emoji="🎟️",
                ),
            ]),
        ],
    )]


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
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id="ticket_v2_my_ticket",
                            label="My ticket",
                            emoji="🎟️",  # Ticket emoji
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
    description="Bind old intake and post target public/pilot v2 panels (Admin only)"
):
    legacy_panel = lightbulb.string(
        "legacy-panel",
        "Old panel message link or guild/channel/message IDs (first setup only)",
        default=None,
    )
    public_channel = lightbulb.channel(
        "public-channel",
        "Target-server channel for the public v2 panel (first setup only)",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
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
        "Replace both target public and pilot panel bindings",
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
        """Validate the cross-server topology and bind both target v2 panels."""
        await ctx.defer(ephemeral=True)
        member = getattr(ctx, "member", None)
        if member is None or not member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ Administrator permission is required in the target ticket server.",
                ephemeral=True,
            )
            return
        guild_id = int(ctx.guild_id or 0)
        if not guild_id:
            await ctx.respond("❌ Run this command in the ticket server.", ephemeral=True)
            return
        legacy_panel_value = self.legacy_panel if isinstance(self.legacy_panel, str) else None
        public_channel_option = (
            self.public_channel if hasattr(self.public_channel, "id") else None
        )
        tester_option = self.tester if hasattr(self.tester, "id") else None
        tester_role_option = (
            self.tester_role if hasattr(self.tester_role, "id") else None
        )
        replace_requested = self.replace is True

        try:
            state = await ticket_runtime.get_rollout(mongo)
            config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
            supplied_legacy = parse_legacy_panel_reference(legacy_panel_value)
        except (ValueError, ticket_runtime.TicketRuntimeError) as error:
            await ctx.respond(f"🛑 Setup stopped: {error}. Nothing was posted.", ephemeral=True)
            return
        except Exception:
            await ctx.respond(
                "🛑 Ticket configuration could not be loaded. Nothing was posted.",
                ephemeral=True,
            )
            return

        legacy_source = supplied_legacy or (state.legacy_intake if state.valid else None)
        if legacy_source is None:
            await ctx.respond(
                "🛑 First setup requires `legacy-panel`. Nothing was posted.",
                ephemeral=True,
            )
            return
        if state.valid and supplied_legacy is not None and supplied_legacy != state.legacy_intake:
            await ctx.respond(
                "🛑 Rebind the old panel with `/ticket setup`; target setup cannot move it. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return
        if legacy_source.guild_id == guild_id:
            await ctx.respond(
                "🛑 The v2 target must be a different server from legacy ticketing. "
                "Nothing was posted or changed.",
                ephemeral=True,
            )
            return

        target_already_bound = bool(
            state.valid
            and state.thread_intake is not None
            and state.pilot_intake is not None
            and state.thread_intake.guild_id == guild_id
            and state.pilot_intake.guild_id == guild_id
        )
        if target_already_bound and not replace_requested:
            await ctx.respond(
                "🛑 Target public and pilot panels are already bound. Use `replace: true` "
                "only if either panel was deleted or must move.",
                ephemeral=True,
            )
            return
        if state.valid and not target_already_bound and state.phase not in SAFE_PUBLIC_REBIND_PHASES:
            await ctx.respond(
                f"🛑 Cross-server binding is blocked during `{state.phase}`. "
                "Roll back first. Nothing was posted.",
                ephemeral=True,
            )
            return
        if state.valid and target_already_bound and replace_requested and (
            state.phase not in SAFE_PUBLIC_REBIND_PHASES
        ):
            await ctx.respond(
                f"🛑 Target-panel replacement is blocked during `{state.phase}`. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return

        bound_legacy_guild = _as_positive_int(config.get("legacy_ticket_guild_id"))
        if bound_legacy_guild and bound_legacy_guild != legacy_source.guild_id:
            await ctx.respond(
                "🛑 Legacy ticketing is bound to a different server. Nothing was posted.",
                ephemeral=True,
            )
            return
        bound_target_guild = _as_positive_int(config.get("ticket_target_guild_id"))
        old_single_guild_binding = (
            not bound_legacy_guild and bound_target_guild == legacy_source.guild_id
        )
        if bound_target_guild not in {None, guild_id} and not old_single_guild_binding:
            await ctx.respond(
                "🛑 Thread ticketing is bound to a different target server. Nothing was posted.",
                ephemeral=True,
            )
            return
        try:
            old_guild_admin = await _guild_administrator(
                bot.rest, legacy_source.guild_id, int(ctx.user.id)
            )
        except Exception:
            old_guild_admin = False
        if not old_guild_admin:
            await ctx.respond(
                "🛑 You must own or administer both the old and target servers. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return

        existing_users = set(state.pilot_user_ids if state.valid else ())
        existing_roles = set(state.pilot_role_ids if state.valid else ())
        if tester_option is not None:
            existing_users.add(int(tester_option.id))
        if tester_role_option is not None:
            existing_roles.add(int(tester_role_option.id))
        if not existing_users and not existing_roles:
            await ctx.respond(
                "🛑 Supply `tester` or `tester-role` for the initial allowlist. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return

        if public_channel_option is not None:
            public_channel_id = int(public_channel_option.id)
            public_channel_guild = int(
                getattr(public_channel_option, "guild_id", 0) or 0
            )
            if public_channel_guild != guild_id:
                await ctx.respond(
                    "🛑 The public v2 channel must be in the target server. Nothing was posted.",
                    ephemeral=True,
                )
                return
        elif target_already_bound and state.thread_intake is not None:
            public_channel_id = state.thread_intake.channel_id
        else:
            await ctx.respond(
                "🛑 First target setup requires `public-channel`. Nothing was posted.",
                ephemeral=True,
            )
            return
        if public_channel_id == int(ctx.channel_id):
            await ctx.respond(
                "🛑 Public v2 and private pilot panels must use separate channels. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return
        configured_candidate_parents = {
            value
            for key in ("main_candidate_parent", "fwa_candidate_parent")
            if (value := _as_positive_int(config.get(key))) is not None
        }
        relocating_public_panel = bool(
            state.valid
            and target_already_bound
            and replace_requested
            and state.phase in SAFE_PUBLIC_REBIND_PHASES
            and state.thread_intake is not None
            and state.thread_intake.channel_id != public_channel_id
        )
        if (
            configured_candidate_parents
            and configured_candidate_parents != {public_channel_id}
            and not relocating_public_panel
        ):
            await ctx.respond(
                "🛑 The public v2 channel must be the shared configured candidate-thread "
                "parent. Nothing was posted.",
                ephemeral=True,
            )
            return

        me = bot.get_me()
        if me is None:
            await ctx.respond("🛑 Bot identity is unavailable. Nothing was posted.", ephemeral=True)
            return
        try:
            legacy_channel, legacy_message, target_public_channel = await asyncio.gather(
                bot.rest.fetch_channel(legacy_source.channel_id),
                bot.rest.fetch_message(legacy_source.channel_id, legacy_source.message_id),
                bot.rest.fetch_channel(public_channel_id),
            )
            if (
                int(getattr(legacy_channel, "guild_id", 0) or 0) != legacy_source.guild_id
                or getattr(legacy_channel, "type", None) != hikari.ChannelType.GUILD_TEXT
            ):
                raise ValueError("legacy panel channel identity does not match its server")
            if (
                int(getattr(target_public_channel, "guild_id", 0) or 0) != guild_id
                or getattr(target_public_channel, "type", None) != hikari.ChannelType.GUILD_TEXT
            ):
                raise ValueError("public v2 channel is not a target-server text channel")
            if int(getattr(getattr(legacy_message, "author", None), "id", 0) or 0) != int(me.id):
                raise ValueError("legacy panel was not authored by this bot")
            surface.require_panel_actions(
                legacy_message,
                surface.LEGACY_PANEL_ACTIONS,
                label="legacy ticket panel",
            )
        except Exception as error:
            await ctx.respond(
                f"🛑 The old or target panel location could not be verified: {error}. "
                "Nothing was posted.",
                ephemeral=True,
            )
            return

        posted: list[tuple[int, int]] = []
        config_binding_committed = False
        config_binding_uncertain = False
        rollout_binding_committed = False
        public_source: ticket_runtime.IntakeSource | None = None
        pilot_source: ticket_runtime.IntakeSource | None = None
        try:
            public_message = await bot.rest.create_message(
                channel=public_channel_id,
                components=create_public_ticket_embed(),
                mentions_everyone=False,
                user_mentions=False,
                role_mentions=False,
            )
            posted.append((public_channel_id, int(public_message.id)))
            pilot_message = await bot.rest.create_message(
                channel=ctx.channel_id,
                components=create_ticket_embed(),
                mentions_everyone=False,
                user_mentions=False,
                role_mentions=False,
            )
            posted.append((int(ctx.channel_id), int(pilot_message.id)))
            public_source = ticket_runtime.IntakeSource(
                guild_id, public_channel_id, int(public_message.id)
            )
            pilot_source = ticket_runtime.IntakeSource(
                guild_id,
                int(ctx.channel_id),
                int(pilot_message.id),
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

            target_filter = (
                {"ticket_target_guild_id": bound_target_guild}
                if bound_target_guild is not None
                else {"ticket_target_guild_id": {"$exists": False}}
            )
            legacy_filter = (
                {"legacy_ticket_guild_id": bound_legacy_guild}
                if bound_legacy_guild is not None
                else {"legacy_ticket_guild_id": {"$exists": False}}
            )
            try:
                saved = await mongo.ticket_setup.find_one_and_update(
                    {"_id": "config", "$and": [target_filter, legacy_filter]},
                    {"$set": {
                        "legacy_ticket_guild_id": legacy_source.guild_id,
                        "ticket_target_guild_id": guild_id,
                    }},
                    upsert=True,
                    return_document=ReturnDocument.AFTER,
                )
            except DuplicateKeyError:
                saved = None
            except Exception:
                try:
                    observed_config = await mongo.ticket_setup.find_one(
                        {"_id": "config"}
                    ) or {}
                except Exception:
                    config_binding_uncertain = True
                    raise
                saved = (
                    observed_config
                    if _as_positive_int(
                        observed_config.get("legacy_ticket_guild_id")
                    ) == legacy_source.guild_id
                    and _as_positive_int(
                        observed_config.get("ticket_target_guild_id")
                    ) == guild_id
                    else None
                )
            if saved is None:
                raise ticket_runtime.RolloutConflict(
                    "ticket guild bindings changed during setup"
                )
            config_binding_committed = True

            if state.valid:
                updated = await ticket_runtime.configure_rollout(
                    mongo,
                    expected_revision=state.revision,
                    actor_id=int(ctx.user.id),
                    legacy_intake=legacy_source,
                    thread_intake=public_source,
                    pilot=pilot,
                )
            else:
                updated = await ticket_runtime.seed_rollout(
                    mongo,
                    actor_id=int(ctx.user.id),
                    legacy_intake=legacy_source,
                    thread_intake=public_source,
                    pilot=pilot,
                )
            if (
                updated.legacy_intake != legacy_source
                or updated.thread_intake != public_source
                or updated.pilot_intake != pilot_source
            ):
                raise ticket_runtime.RolloutConflict(
                    "rollout was concurrently bound to different panels"
                )
            rollout_binding_committed = True
            success_message = (
                "✅ Cross-server intake bound: old legacy "
                f"`{legacy_source.guild_id}/{legacy_source.channel_id}/{legacy_source.message_id}`, "
                f"target public <#{public_source.channel_id}> / `{public_source.message_id}`, "
                f"pilot <#{pilot_source.channel_id}> / `{pilot_source.message_id}` at "
                f"revision `{updated.revision}`. Run `/ticket-pilot rollout-prepare` "
                "when the tester allowlist is ready, then explicitly enable the pilot."
            )

        except Exception as e:
            restore_failed = False
            rollout_binding_uncertain = False
            if (
                config_binding_committed
                and not rollout_binding_committed
                and public_source is not None
                and pilot_source is not None
            ):
                try:
                    observed = await ticket_runtime.get_rollout(mongo)
                except Exception:
                    observed = None
                    restore_failed = True
                    rollout_binding_uncertain = True
                if (
                    observed is not None
                    and observed.valid
                    and observed.legacy_intake == legacy_source
                    and observed.thread_intake == public_source
                    and observed.pilot_intake == pilot_source
                ):
                    rollout_binding_committed = True
                elif observed is not None:
                    restore_update: dict[str, dict] = {}
                    restore_set = {
                        key: config[key]
                        for key in (
                            "legacy_ticket_guild_id",
                            "ticket_target_guild_id",
                        )
                        if key in config
                    }
                    restore_unset = {
                        key: ""
                        for key in (
                            "legacy_ticket_guild_id",
                            "ticket_target_guild_id",
                        )
                        if key not in config
                    }
                    if restore_set:
                        restore_update["$set"] = restore_set
                    if restore_unset:
                        restore_update["$unset"] = restore_unset
                    try:
                        restored = await mongo.ticket_setup.find_one_and_update(
                            {
                                "_id": "config",
                                "legacy_ticket_guild_id": legacy_source.guild_id,
                                "ticket_target_guild_id": guild_id,
                            },
                            restore_update,
                            return_document=ReturnDocument.AFTER,
                        )
                        restore_failed = restored is None
                    except Exception:
                        restore_failed = True

            if rollout_binding_committed:
                await ctx.respond(
                    "✅ Cross-server intake binding was confirmed after a response error. "
                    "The bound panels were preserved.",
                    ephemeral=True,
                )
                return
            if rollout_binding_uncertain:
                await ctx.respond(
                    "❌ Cross-server setup outcome is uncertain because rollout state could "
                    "not be reread. The posted panels and guild binding were preserved; "
                    "check rollout status before retrying.",
                    ephemeral=True,
                )
                return
            for channel_id, message_id in reversed(posted):
                try:
                    await bot.rest.delete_message(channel_id, message_id)
                except Exception:
                    try:
                        await bot.rest.edit_message(
                            channel_id,
                            message_id,
                            components=inactive_pilot_embed(),
                        )
                    except Exception:
                        pass
            await ctx.respond(
                "❌ Cross-server setup did not complete. Any proven-unbound panels are inactive. "
                + (
                    "The guild binding could not be verified or restored automatically; "
                    "retry only after "
                    "checking rollout status. "
                    if restore_failed or config_binding_uncertain
                    else "The prior guild binding was restored. "
                )
                + f"Error: {type(e).__name__}."
            )
            return

        # An acknowledgement failure must not delete a panel whose exact source
        # binding has already committed successfully.
        await ctx.respond(success_message)
