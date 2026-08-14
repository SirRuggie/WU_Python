"""Owner-only Discord phone lab for compact poll visuals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb

from utils.constants import BLUE_ACCENT, GOLD_ACCENT

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

GLYPH_PAIRS = {
    "parallelogram": ("▰", "▱"),
    "square": ("■", "□"),
    "vertical": ("▮", "▯"),
    "horizontal": ("▬", "▭"),
    "circle": ("●", "○"),
}
LAB_PERCENTAGES = (25, 50, 75)
LAB_WIDTHS = (10, 12, 14)


@dataclass(frozen=True, slots=True)
class PreviewVariant:
    code: str
    name: str
    pair: str
    width: int
    button_mode: str


FINALISTS = (
    PreviewVariant("A", "Reference", "parallelogram", 10, "number"),
    PreviewVariant("B", "Thicker squares", "square", 10, "emoji"),
    PreviewVariant("C", "Horizontal blocks", "horizontal", 10, "number"),
)


def _round_half_up(numerator: int, denominator: int) -> int:
    """Round a non-negative rational number to the nearest integer."""
    if denominator <= 0:
        return 0
    return (max(int(numerator), 0) + denominator // 2) // denominator


def _bar(pair: str, width: int, count: int, total: int) -> str:
    """Render one plain-Unicode preview bar with explicit half-up rounding."""
    if pair not in GLYPH_PAIRS:
        raise ValueError(f"Unknown poll bar glyph pair: {pair}")
    width = max(int(width), 1)
    filled_glyph, empty_glyph = GLYPH_PAIRS[pair]
    filled = min(_round_half_up(max(int(count), 0) * width, total), width)
    return filled_glyph * filled + empty_glyph * (width - filled)


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
        f"{_bar(variant.pair, variant.width, count, total)} "
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
    raise ValueError(f"Unknown poll visual-lab variant: {code}")


def _preview_button(
    *,
    preview: str,
    control: str,
    label: str | None = None,
    emoji: str | None = None,
    style: hikari.ButtonStyle = hikari.ButtonStyle.SECONDARY,
) -> Button:
    kwargs = {
        "style": style,
        "custom_id": f"poll_bar_preview_noop:{preview}|{control}",
        "is_disabled": True,
    }
    if emoji is not None:
        kwargs["emoji"] = emoji
    elif label is not None:
        kwargs["label"] = label
    else:
        raise ValueError("A preview button needs a label or emoji")
    return Button(**kwargs)


def _vote_row(preview: str, mode: str, option_count: int) -> ActionRow:
    buttons: list[Button] = []
    for number in range(1, int(option_count) + 1):
        display = f"{number}️⃣"
        buttons.append(_preview_button(
            preview=preview,
            control=f"{mode}-{option_count}-{number}",
            emoji=display if mode == "emoji" else None,
            label=str(number) if mode == "number" else None,
            style=hikari.ButtonStyle.PRIMARY,
        ))
    return ActionRow(components=buttons)


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
    """Build one complete, compact finalist poll for phone comparison."""
    variant = _variant_for(code)
    filled, empty = GLYPH_PAIRS[variant.pair]
    button_name = "[1] buttons" if variant.button_mode == "number" else "1️⃣ buttons"
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
        _vote_row(variant.code, variant.button_mode, len(POLL_OPTIONS)),
        _admin_row(variant.code),
        Text(content=(
            f"-# {POLL_TOTAL} votes · You can change your vote.\n"
            f"-# ⏱️ Closes <t:{_closes_at(observed_at)}:R> · <@{int(creator_id)}>\n"
            f"-# Preview {variant.code} · {variant.name} · "
            f"{variant.width}-cell {filled}/{empty} · {button_name}"
        )),
    ]
    return [Container(accent_color=GOLD_ACCENT, components=body)]


def _pair_matrix_text() -> str:
    lines = ["**10 cells · 25 / 50 / 75%**"]
    for pair, (filled, empty) in GLYPH_PAIRS.items():
        bars = " · ".join(
            _bar(pair, 10, percent, 100)
            for percent in LAB_PERCENTAGES
        )
        lines.append(f"**{filled}/{empty}** {bars}")
    return "\n".join(lines)


def _length_matrix_text() -> str:
    lines = ["**Strongest pairs · 50% at 10 / 12 / 14 cells**"]
    for pair in ("parallelogram", "square", "horizontal"):
        filled, empty = GLYPH_PAIRS[pair]
        bars = " · ".join(
            _bar(pair, width, 50, 100)
            for width in LAB_WIDTHS
        )
        lines.append(f"**{filled}/{empty}** {bars}")
    return "\n".join(lines)


def build_poll_visual_lab_components() -> list[Container]:
    """Build the compact glyph and two-/three-option button comparison."""
    body = [
        Text(content=(
            "## 🔬 Poll visual lab\n"
            "Plain Unicode bars and real Discord button construction."
        )),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content=_pair_matrix_text()),
        Separator(divider=False, spacing=hikari.SpacingType.SMALL),
        Text(content=_length_matrix_text()),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content="**Plain number labels**\n-# 2 options, then 3 options"),
        _vote_row("lab-number", "number", 2),
        _vote_row("lab-number", "number", 3),
        Text(content="**Emoji-only buttons**\n-# 2 options, then 3 options"),
        _vote_row("lab-emoji", "emoji", 2),
        _vote_row("lab-emoji", "emoji", 3),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content="-# Visual lab only · Controls are intentionally disabled."),
    ]
    return [Container(accent_color=BLUE_ACCENT, components=body)]


async def _send_poll_bar_previews(
    bot: hikari.GatewayBot,
    *,
    owner_id: int,
    observed_at: datetime | None = None,
) -> int:
    """DM three complete finalist polls and one compact comparison lab."""
    channel = await bot.rest.create_dm_channel(owner_id)
    views = [
        build_poll_bar_preview_components(
            variant.code,
            creator_id=owner_id,
            observed_at=observed_at,
        )
        for variant in FINALISTS
    ]
    views.append(build_poll_visual_lab_components())

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
    description="DM the owner a compact poll visual lab",
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
            f"Sent {sent} compact poll visual-lab previews to your DMs.",
            ephemeral=True,
        )
