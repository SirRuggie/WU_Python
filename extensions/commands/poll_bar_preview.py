"""Owner-only Discord phone preview for WU poll bar lengths."""

from __future__ import annotations

from dataclasses import dataclass
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
POLL_QUESTION = "What should we play tonight?"
POLL_DETAILS = "Pick one for game night."
POLL_OPTIONS = (
    (1, "Minecraft", 12),
    (2, "Jackbox Party Pack", 7),
    (3, "Gartic Phone with custom prompts", 3),
)
POLL_TOTAL = sum(count for _option_id, _label, count in POLL_OPTIONS)


@dataclass(frozen=True, slots=True)
class PreviewVariant:
    code: str
    width: int


FINALISTS = (
    PreviewVariant("A", 16),
    PreviewVariant("B", 20),
)


def _round_half_up(numerator: int, denominator: int) -> int:
    """Round a non-negative rational number to the nearest integer."""
    if denominator <= 0:
        return 0
    return (max(int(numerator), 0) + denominator // 2) // denominator


def _bar(width: int, count: int, total: int) -> str:
    """Render one plain-text WU bar with explicit half-up rounding."""
    width = max(int(width), 1)
    filled = min(_round_half_up(max(int(count), 0) * width, total), width)
    return "█" * filled + "░" * (width - filled)


def _percent(count: int, total: int) -> int:
    return _round_half_up(max(int(count), 0) * 100, total)


def _result_line(
    variant: PreviewVariant,
    *,
    option_id: int,
    label: str,
    count: int,
    total: int = POLL_TOTAL,
) -> str:
    result = (
        f"{_bar(variant.width, count, total)} "
        f"**{_percent(count, total)}% · {count}**"
    )
    option = f"**{int(option_id)}. {label}**"
    if len(label) > 24:
        return f"{option}\n{result}"
    return f"{option} {result}"


def _variant_for(code: str) -> PreviewVariant:
    normalized = str(code).upper()
    for variant in FINALISTS:
        if variant.code == normalized:
            return variant
    raise ValueError(f"Unknown poll bar-length variant: {code}")


def _preview_button(
    *,
    preview: str,
    control: str,
    label: str,
    style: hikari.ButtonStyle = hikari.ButtonStyle.SECONDARY,
) -> Button:
    return Button(
        style=style,
        custom_id=f"poll_bar_preview_noop:{preview}|{control}",
        label=label,
        is_disabled=True,
    )


def _vote_row(preview: str, option_count: int) -> ActionRow:
    return ActionRow(components=[
        _preview_button(
            preview=preview,
            control=f"vote-{number}",
            label=str(number),
            style=hikari.ButtonStyle.PRIMARY,
        )
        for number in range(1, int(option_count) + 1)
    ])


def _admin_row(preview: str) -> ActionRow:
    return ActionRow(components=[
        _preview_button(
            preview=preview,
            control="view-voters",
            label="View voters",
        ),
        _preview_button(
            preview=preview,
            control="end-poll",
            label="End poll",
        ),
    ])


def _closes_at(observed_at: datetime | None) -> int:
    now = observed_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return int((now.astimezone(timezone.utc) + timedelta(hours=1)).timestamp())


def build_poll_bar_preview_components(
    code: str,
    *,
    creator_id: int,
    observed_at: datetime | None = None,
) -> list[Container]:
    """Build one complete compact poll for the 16/20-cell phone comparison."""
    variant = _variant_for(code)
    results = "\n".join(
        _result_line(
            variant,
            option_id=option_id,
            label=label,
            count=count,
        )
        for option_id, label, count in POLL_OPTIONS
    )

    body = [
        Text(content=f"# 📊 {POLL_QUESTION}\n{POLL_DETAILS}"),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content=results),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        _vote_row(variant.code, len(POLL_OPTIONS)),
        _admin_row(variant.code),
        Text(content=(
            f"-# {POLL_TOTAL} votes · You can change your vote.\n"
            f"-# ⏱️ Closes <t:{_closes_at(observed_at)}:R> · <@{int(creator_id)}>\n"
            f"-# Preview {variant.code} · WU bar · {variant.width} cells"
        )),
    ]
    return [Container(accent_color=GOLD_ACCENT, components=body)]


async def _send_poll_bar_previews(
    bot: hikari.GatewayBot,
    *,
    owner_id: int,
    observed_at: datetime | None = None,
) -> int:
    """DM the owner the complete 16- and 20-cell poll previews."""
    channel = await bot.rest.create_dm_channel(owner_id)
    views = [
        build_poll_bar_preview_components(
            variant.code,
            creator_id=owner_id,
            observed_at=observed_at,
        )
        for variant in FINALISTS
    ]

    for components in views:
        await bot.rest.create_message(
            channel=channel,
            components=components,
            flags=hikari.MessageFlag.IS_COMPONENTS_V2,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
            mentions_reply=False,
        )
    return len(views)


@loader.command
class PollBarPreview(
    lightbulb.SlashCommand,
    name="poll-bar-preview",
    description="DM the owner the 16- and 20-cell WU poll previews",
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
            f"Sent {sent} WU poll bar-length previews to your DMs.",
            ephemeral=True,
        )
