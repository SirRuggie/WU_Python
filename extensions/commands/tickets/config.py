"""Read-only operator view of the thread ticket configuration."""

from __future__ import annotations

from collections.abc import Mapping

import lightbulb

from extensions.commands.tickets import perms, ticket
from utils.mongo import MongoClient


def _channel(value) -> str:
    return f"<#{int(value)}>" if value else "Not set"


def _role(value) -> str:
    return f"<@&{int(value)}>" if value else "Not set"


def configuration_summary(config: Mapping) -> str:
    """Render only settings that affect the thread-only runtime."""
    rows = ["## Thread ticket configuration", "**Runtime:** Thread-only"]
    for kind, label in (("main", "Main"), ("fwa", "FWA")):
        rows.extend([
            "",
            f"**{label}**",
            f"Candidate parent: {_channel(config.get(f'{kind}_candidate_parent'))}",
            f"Staff parent: {_channel(config.get(f'{kind}_staff_parent'))}",
            f"Recruiter role: {_role(config.get(f'{kind}_recruiter_role'))}",
            f"Last allocated ticket: `{int(config.get(f'{kind}_ticket_counter') or 0)}`",
        ])

    console_channel = config.get("ticket_console_channel_id")
    rows.extend([
        "",
        "**Shared console**",
        f"Channel: {_channel(console_channel)}",
        "",
        "Use `/ticket configure-threads` to validate and save a thread pair.",
        "Use `/ticket console` in the private recruiter channel to post or repair the hub.",
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
                "Administrator permission is required in the configured ticket guild.",
            )
            return
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        console = await mongo.ticket_setup.find_one({"_id": "ticket_console_hub"}) or {}
        view = dict(config)
        view["ticket_console_channel_id"] = console.get("channel_id")
        await ctx.interaction.edit_initial_response(
            configuration_summary(view),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )
