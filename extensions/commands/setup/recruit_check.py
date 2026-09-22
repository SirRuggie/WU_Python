"""Private, read-only diagnostics for the three recruit setup posts."""

from __future__ import annotations

import asyncio

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands.setup import setup
from extensions.commands.setup import (
    recruit_aboutus,
    recruit_familyparticulars,
    recruit_strikesystem,
)
from utils.media_store import MediaStore
from utils.recruit_setup_checks import inspect_recruit_setup, require_manage_server


_STEPS = (
    ("About Us", recruit_aboutus.ABOUT_US_ROLE_ID, recruit_aboutus.STRIKE_SYSTEM_CHANNEL_ID),
    ("WU Strike System", recruit_strikesystem.STRIKE_SYSTEM_ROLE_ID,
     recruit_strikesystem.FAMILY_PARTICULARS_CHANNEL_ID),
    ("Family Particulars", recruit_familyparticulars.CLAN_RULES_READ_ROLE_ID,
     recruit_familyparticulars.APPLY_HERE_CHANNEL_ID),
)


def check_panel(checks, *, media_configured: bool) -> list:
    """Build a Components V2-only private diagnostic response."""
    rows = [Text(content="## Recruit setup check")]
    for (label, _role_id, _channel_id), check in zip(_STEPS, checks, strict=True):
        if check.ready:
            rows.append(Text(content=f"✅ **{label}:** ready"))
        else:
            rows.append(Text(content=f"❌ **{label}:** " + "; ".join(check.issues)))
    rows.append(Text(content=(
        "✅ **Recruit content image storage:** configured"
        if media_configured
        else "❌ **Recruit content image storage:** R2 is not configured; image uploads are unavailable."
    )))
    rows.append(Text(content=(
        "This check confirms bot prerequisites only; it does not inspect member channel overwrites."
    )))
    return [Container(accent_color=0xEEEEAA, components=rows)]


@setup.register()
class RecruitCheck(
    lightbulb.SlashCommand,
    name="recruit-check",
    description="Check recruit post setup requirements (Manage Server)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        media: MediaStore = lightbulb.di.INJECTED,
    ) -> None:
        if not await require_manage_server(ctx):
            return
        await ctx.defer(ephemeral=True)
        checks = await asyncio.gather(*(
            inspect_recruit_setup(ctx, bot, role_id=role_id, next_channel_id=channel_id)
            for _label, role_id, channel_id in _STEPS
        ))
        await ctx.respond(
            components=check_panel(checks, media_configured=media.configured),
            ephemeral=True,
        )
