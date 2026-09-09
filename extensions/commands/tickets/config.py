"""Read-only operator view of the thread ticket configuration."""

from __future__ import annotations

from collections.abc import Mapping

import lightbulb

from extensions.commands import ticket_runtime
from extensions.commands.tickets import perms, ticket
from utils.mongo import MongoClient


def _channel(value) -> str:
    return f"<#{int(value)}>" if value else "Not set"


def _role(value) -> str:
    return f"<@&{int(value)}>" if value else "Not set"


def _identifier(value) -> str:
    return f"`{int(value)}`" if value else "Not set"


def _source(source: ticket_runtime.IntakeSource | None) -> str:
    if source is None:
        return "Not bound"
    link = (
        "https://discord.com/channels/"
        f"{source.guild_id}/{source.channel_id}/{source.message_id}"
    )
    return (
        f"[message]({link}) — guild `{source.guild_id}`, "
        f"channel `{source.channel_id}`, message `{source.message_id}`"
    )


def configuration_summary(
    config: Mapping,
    rollout: ticket_runtime.RolloutState | None = None,
) -> str:
    """Render only settings that affect the thread v2 runtime."""
    legacy_guild_id = config.get("legacy_ticket_guild_id")
    target_guild_id = config.get("ticket_target_guild_id")
    if rollout is not None:
        if not legacy_guild_id and rollout.legacy_intake is not None:
            legacy_guild_id = rollout.legacy_intake.guild_id
        if not target_guild_id and rollout.thread_intake is not None:
            target_guild_id = rollout.thread_intake.guild_id
    rows = [
        "## Thread ticket configuration",
        "**Runtime:** Thread v2",
        f"**Legacy guild:** {_identifier(legacy_guild_id)}",
        f"**Target guild:** {_identifier(target_guild_id)}",
    ]
    if rollout is not None:
        phase = rollout.phase if rollout.valid else "invalid (legacy-safe)"
        rows.extend([
            f"**Rollout phase:** `{phase}`",
            f"**Legacy source:** {_source(rollout.legacy_intake)}",
            f"**Target public-v2 source:** {_source(rollout.thread_intake)}",
            f"**Target pilot source:** {_source(rollout.pilot_intake)}",
        ])
    for kind, label in (("main", "Main"), ("fwa", "FWA")):
        rows.extend([
            "",
            f"**{label}**",
            f"Candidate parent: {_channel(config.get(f'{kind}_candidate_parent'))}",
            f"Staff parent: {_channel(config.get(f'{kind}_staff_parent'))}",
            f"Target thread recruiter role: "
            f"{_role(config.get(f'{kind}_thread_recruiter_role'))}",
            f"Last allocated ticket: `{int(config.get(f'{kind}_ticket_counter') or 0)}`",
        ])

    console_channel = config.get("ticket_console_channel_id")
    rows.extend([
        "",
        "**Shared console**",
        f"Channel: {_channel(console_channel)}",
        "",
        "Use `/tickets configure-threads` to validate and save a thread pair.",
        "Use `/tickets console` in the private recruiter channel to post or repair the hub.",
    ])
    return "\n".join(rows)


@ticket.register()
class Config(
    lightbulb.SlashCommand,
    name="config",
    description="Inspect thread ticket settings (Admin only)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await perms.is_target_admin(ctx.member, mongo):
            await ctx.interaction.edit_initial_response(
                "Administrator permission is required in the target ticket guild.",
            )
            return
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        console = await mongo.ticket_setup.find_one({"_id": "ticket_console_hub"}) or {}
        rollout = await ticket_runtime.get_rollout(mongo)
        view = dict(config)
        view["ticket_console_channel_id"] = console.get("channel_id")
        await ctx.interaction.edit_initial_response(
            configuration_summary(view, rollout),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
