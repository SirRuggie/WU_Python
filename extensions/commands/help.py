"""Trustworthy, navigable Components V2 command guide."""

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SelectOptionBuilder as SelectOption,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
    TextSelectMenuBuilder as TextSelectMenu,
)

from extensions.commands.help_catalog import HELP_CATEGORIES
from extensions.components import register_action
from utils.constants import BLUE_ACCENT
from utils.startup import tickets_guild_id


loader = lightbulb.Loader()


def _visible_categories(guild_id: int | None) -> dict:
    """``HELP_CATEGORIES`` filtered to what this guild can actually run.

    ``tickets_v2`` documents the `/tickets` thread-ticket pilot, a group
    lightbulb only registers in the configured pilot guild (see
    ``utils.startup.tickets_guild_id``). ``/help`` is global, so every other
    guild must not list commands Discord never offers them.
    """
    if guild_id == tickets_guild_id():
        return HELP_CATEGORIES
    return {
        category_id: category
        for category_id, category in HELP_CATEGORIES.items()
        if category_id != "tickets_v2"
    }


def _category_select(
        categories: dict, selected_category: str | None = None
) -> ActionRow:
    options = [
        SelectOption(
            label=f"{category['name']} ({len(category['commands'])})",
            value=category_id,
            description=category["description"],
            emoji=category["emoji"],
            is_default=category_id == selected_category,
        )
        for category_id, category in categories.items()
    ]
    return ActionRow(
        components=[
            TextSelectMenu(
                custom_id="help_category_select:menu",
                placeholder="Choose a command category...",
                max_values=1,
                options=options,
            )
        ]
    )


async def create_help_view(guild_id: int | None = None) -> list:
    categories = _visible_categories(guild_id)
    total_commands = sum(
        len(category["commands"])
        for category in categories.values()
    )
    category_lines = "\n".join(
        f"{category['emoji']} **{category['name']}** — {category['description']}"
        for category in categories.values()
    )

    return [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="# 🧭 Warriors United Command Guide"),
                Text(content=(
                    f"Browse **{total_commands} slash commands** by what you want to do. "
                    "Choose a category below; Discord will show each command's required "
                    "options when you select it."
                )),
                Separator(divider=True),
                Text(content=category_lines),
                Separator(divider=True),
                _category_select(categories),
                Text(content=(
                    "-# Fast starts: `/role` for member roles • `/recruit` for onboarding "
                    "• `/ticket` for tickets • `/fwa` for FWA tools "
                    "• `/accounts` for your players • `/todo` for outstanding work"
                )),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
            ],
        )
    ]


async def create_category_view(category_id: str, guild_id: int | None = None) -> list:
    categories = _visible_categories(guild_id)
    category = categories.get(category_id)
    if category is None:
        return await create_help_view(guild_id)

    command_text = "\n\n".join(
        f"**{command}**\n{description}"
        for command, description in category["commands"]
    )
    components = [
        Text(content=f"# {category['emoji']} {category['name']}"),
        Text(content=category["description"]),
        Separator(divider=True),
        Text(content=command_text),
    ]

    notes = category.get("notes", [])
    if notes:
        components.extend([
            Separator(divider=True),
            Text(content="\n".join(f"• {note}" for note in notes)),
        ])

    components.extend([
        Separator(divider=True),
        _category_select(categories, category_id),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="help_back:main",
                    label="All Categories",
                    emoji="⬅️",
                )
            ]
        ),
        Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
    ])
    return [Container(accent_color=BLUE_ACCENT, components=components)]


@loader.command
class HelpCommand(
    lightbulb.SlashCommand,
    name="help",
    description="Browse every bot command by category",
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond(components=await create_help_view(ctx.guild_id), ephemeral=True)


@register_action("help_category_select", ephemeral=True)
async def on_category_select(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs,
):
    """Switch directly to the selected help category."""
    return await create_category_view(ctx.interaction.values[0], ctx.interaction.guild_id)


@register_action("help_back", ephemeral=True)
async def on_help_back(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs,
):
    """Return to the category overview."""
    return await create_help_view(ctx.interaction.guild_id)


@register_action("help_refresh", ephemeral=True)
async def on_legacy_help_refresh(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        **kwargs,
):
    """Keep Refresh buttons on already-rendered help panels working."""
    return await create_help_view(ctx.interaction.guild_id)
