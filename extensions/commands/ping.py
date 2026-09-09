"""Fast, dependency-free Discord connection check."""

import math
import time

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)

from utils.constants import GREEN_ACCENT


loader = lightbulb.Loader()

# Root command extensions load during process startup. This timestamp therefore
# describes the current bot session without depending on Mongo or another
# service that /ping is meant to help diagnose.
SESSION_STARTED_AT = int(time.time())


def gateway_latency_ms(latency_seconds: object) -> int | None:
    """Convert Hikari's heartbeat latency to display-safe milliseconds."""
    try:
        latency = float(latency_seconds)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latency) or latency < 0:
        return None
    return round(latency * 1000)


def build_ping_view(
    *, latency_ms: int | None, session_started_at: int
) -> list[Container]:
    """Build the compact public health card."""
    latency = f"{latency_ms} ms" if latency_ms is not None else "Measuring…"
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[Text(content=(
            "## ✅ WU Wizard is online\n"
            "The bot is connected to Discord and responding to commands.\n\n"
            f"**Gateway latency:** `{latency}`\n"
            f"**Session started:** <t:{int(session_started_at)}:R>\n"
            "-# Gateway latency is Discord heartbeat time."
        ))],
    )]


@loader.command
class PingCommand(
    lightbulb.SlashCommand,
    name="ping",
    description="Check whether the bot is online and responding",
):
    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.respond(components=build_ping_view(
            latency_ms=gateway_latency_ms(bot.heartbeat_latency),
            session_started_at=SESSION_STARTED_AT,
        ))
