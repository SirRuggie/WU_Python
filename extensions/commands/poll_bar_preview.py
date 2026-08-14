"""Owner-only Discord phone preview for poll progress-bar candidates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import hikari
import lightbulb

from utils.constants import GOLD_ACCENT

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)


loader = lightbulb.Loader()

OWNER_ID = 505227988229554179
PREVIEW_STYLES = (
    ("A", "Current WU"),
    ("B", "Exact DWEEB · 10 cells"),
    ("C", "Geometric · 16 cells"),
    ("D", "Fractional block · 10 cells"),
)
PREVIEW_PERCENTAGES = (0, 10, 25, 32, 38, 50, 67, 75, 90, 100)
_FRACTIONAL_BLOCKS = ("", "▏", "▎", "▍", "▌", "▋", "▊", "▉")


def _round_half_up(numerator: int, denominator: int) -> int:
    """Round a non-negative rational number to the nearest integer."""
    if denominator <= 0:
        return 0
    return (max(int(numerator), 0) + denominator // 2) // denominator


def _preview_result_line(style: str, count: int, total: int = 100) -> str:
    """Render one preview-only tally without changing the production renderer."""
    style = str(style).upper()
    count = max(int(count), 0)
    total = max(int(total), 0)

    if style == "A":
        proportion = count / total if total else 0
        filled = min(max(round(proportion * 10), 0), 10)
        percent = round(proportion * 100)
        bar = "█" * filled + "░" * (10 - filled)
        rendered_bar = f"`{bar}`"
    elif style in {"B", "C"}:
        width = 10 if style == "B" else 16
        filled = min(_round_half_up(count * width, total), width)
        percent = _round_half_up(count * 100, total)
        rendered_bar = "▰" * filled + "▱" * (width - filled)
    elif style == "D":
        eighths = min(_round_half_up(count * 80, total), 80)
        full, remainder = divmod(eighths, 8)
        if remainder:
            rendered_bar = (
                "█" * full
                + _FRACTIONAL_BLOCKS[remainder]
                + "░" * (9 - full)
            )
        else:
            rendered_bar = "█" * full + "░" * (10 - full)
        percent = _round_half_up(count * 100, total)
    else:
        raise ValueError(f"Unknown poll bar preview style: {style}")

    votes = "vote" if count == 1 else "votes"
    return f"{rendered_bar} **{percent}%** · {count} {votes}"


def build_poll_bar_preview_components(
    style: str,
    *,
    creator_id: int,
    observed_at: datetime | None = None,
) -> list[Container]:
    """Build one production-shaped comparison card for a single bar style."""
    style = str(style).upper()
    names = dict(PREVIEW_STYLES)
    if style not in names:
        raise ValueError(f"Unknown poll bar preview style: {style}")

    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    closes_at = int((now.astimezone(timezone.utc) + timedelta(hours=1)).timestamp())

    body: list = [
        Text(content=f"# 📊 {style} · {names[style]}"),
        Text(content=(
            "Poll progress-bar phone preview\n"
            "Each result below is an independent poll sample."
        )),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
    ]

    for index, percent in enumerate(PREVIEW_PERCENTAGES, start=1):
        if index > 1:
            body.append(Separator(
                divider=False,
                spacing=hikari.SpacingType.SMALL,
            ))
        body.append(Text(content=(
            f"**{index}. Result at {percent}%**\n"
            f"{_preview_result_line(style, percent)}"
        )))

    body.extend([
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content="100 votes · You can change your vote."),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                label="Yes",
                custom_id=f"poll_bar_preview_noop:{style}|vote-1",
                is_disabled=True,
            ),
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                label="No",
                custom_id=f"poll_bar_preview_noop:{style}|vote-2",
                is_disabled=True,
            ),
        ]),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                label="Let me turn my hearing aid on",
                custom_id=f"poll_bar_preview_noop:{style}|vote-3",
                is_disabled=True,
            ),
        ]),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                label="View voters (Admin)",
                custom_id=f"poll_bar_preview_noop:{style}|voters",
                is_disabled=True,
            ),
            Button(
                style=hikari.ButtonStyle.DANGER,
                label="End poll (Admin)",
                custom_id=f"poll_bar_preview_noop:{style}|end",
                is_disabled=True,
            ),
        ]),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content=(
            f"-# ⏱️ Closes <t:{closes_at}:R> · <@{int(creator_id)}>"
        )),
    ])

    return [Container(accent_color=GOLD_ACCENT, components=body)]


async def _send_poll_bar_previews(
    bot: hikari.GatewayBot,
    *,
    owner_id: int,
    observed_at: datetime | None = None,
) -> int:
    """DM all four static comparison cards without persistence or poll actions."""
    channel = await bot.rest.create_dm_channel(owner_id)
    now = observed_at or datetime.now(timezone.utc)
    sent = 0
    for style, _name in PREVIEW_STYLES:
        await bot.rest.create_message(
            channel=channel,
            components=build_poll_bar_preview_components(
                style,
                creator_id=owner_id,
                observed_at=now,
            ),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
            mentions_reply=False,
        )
        sent += 1
    return sent


@loader.command
class PollBarPreview(
    lightbulb.SlashCommand,
    name="poll-bar-preview",
    description="DM the owner four poll progress-bar phone previews",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        if int(ctx.user.id) != OWNER_ID:
            await ctx.respond("This preview command is owner only.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        try:
            sent = await _send_poll_bar_previews(
                bot,
                owner_id=OWNER_ID,
            )
        except hikari.HikariError:
            await ctx.respond(
                "I could not send the poll previews. Check that your DMs are open.",
                ephemeral=True,
            )
            return

        await ctx.respond(
            f"Sent {sent} poll progress-bar previews to your DMs.",
            ephemeral=True,
        )
