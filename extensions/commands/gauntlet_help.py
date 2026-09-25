"""Private settings panel for Recruit Gauntlet help and reminder timing."""

from __future__ import annotations

from typing import Any

import hikari
import lightbulb

from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT
from utils.manage_ui import breadcrumb, button_emoji
from utils.mongo import MongoClient


loader = lightbulb.Loader()
GUILD_ID = 644963518025826315
HELP_CHANNEL_ID = 1553128653645160479
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}


def _identity(ctx: Any) -> tuple[int | None, int | None]:
    user = getattr(ctx, "user", None)
    guild_id = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    try:
        return int(user.id), int(guild_id)
    except (AttributeError, TypeError, ValueError):
        return None, None


async def _content_state(ctx: Any, mongo: MongoClient, sid: str) -> tuple[dict | None, str | None]:
    """Validate the short-lived Recruit Gauntlet panel which opened this screen."""
    from extensions.commands import content

    state, problem = await content.load(ctx, mongo, sid)
    if problem:
        return None, problem
    if int(state.get("guild_id", 0)) != GUILD_ID:
        return None, "Recruit Gauntlet help settings are available in Warriors United only."
    return state, None


async def _settings(mongo: MongoClient) -> dict:
    from utils.gauntlet_help import get_settings
    return await get_settings(mongo, GUILD_ID)


def panel(state: dict, settings: dict, notice: str | None = None) -> list:
    sid = state["_id"]
    minutes = int(settings["reminder_minutes"])
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", "Help & reminders")),
        hikari.impl.TextDisplayComponentBuilder(content="## Help & reminders"),
        hikari.impl.TextDisplayComponentBuilder(
            content=(
                f"Recruit help is posted in <#{HELP_CHANNEL_ID}>. When a recruit stops progressing, "
                f"the bot sends one reminder after **{minutes} minutes** of inactivity."
            )
        ),
        hikari.impl.TextDisplayComponentBuilder(
            content=(
                "The reminder deletes after 10 minutes. Completing the next Gauntlet step resets "
                "its timer, and opening an application ticket ends reminders."
            )
        ),
        hikari.impl.TextDisplayComponentBuilder(
            content="The help sticky returns to the bottom of the channel after 30 minutes of quiet."
        ),
        hikari.impl.TextDisplayComponentBuilder(content=f"Reminder delay: **{minutes} minutes**"),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    controls = hikari.impl.MessageActionRowBuilder()
    controls.add_interactive_button(
        hikari.ButtonStyle.PRIMARY, f"gauntlet_help_edit:{sid}",
        label="Edit delay", emoji=button_emoji("Edit"),
    )
    footer = hikari.impl.MessageActionRowBuilder()
    footer.add_interactive_button(
        hikari.ButtonStyle.SECONDARY, f"content_back_root:{sid}",
        label="Back to Recruit Gauntlet", emoji=button_emoji("Back to Recruit Gauntlet"),
    )
    if token := state.get("manage_token"):
        footer.add_interactive_button(
            hikari.ButtonStyle.SECONDARY, f"manage_home:{token}",
            label="Management Home", emoji=button_emoji("Management Home"),
        )
    rows.extend((controls, footer))
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=rows)]


def error_panel(message: str) -> list:
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLDENROD_ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content=breadcrumb("Recruit Gauntlet", "Help & reminders")),
        hikari.impl.TextDisplayComponentBuilder(content="## Help & reminders"),
        hikari.impl.TextDisplayComponentBuilder(content=message),
    ])]


async def _ack_modal(ctx: Any) -> None:
    interaction = ctx.interaction
    if getattr(interaction, "message", None) is not None:
        await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)


async def _modal_edit(ctx: Any, components: list) -> None:
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


def _modal_value(ctx: Any, field: str) -> str:
    return next(
        (str(item.value or "") for row in getattr(ctx.interaction, "components", ()) for item in row
         if getattr(item, "custom_id", None) == field),
        "",
    )


@register_action("gauntlet_help", preload_state=False)
@lightbulb.di.with_di
async def open_settings(ctx: Any, action_id: str,
                        mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _content_state(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    return panel(state, await _settings(mongo))


@register_action("gauntlet_help_edit", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_delay(ctx: Any, action_id: str,
                     mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _content_state(ctx, mongo, action_id)
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    settings = await _settings(mongo)
    await ctx.respond_with_modal(
        title="Edit reminder delay",
        custom_id=f"gauntlet_help_save:{state['_id']}",
        components=[hikari.impl.ModalActionRowBuilder().add_text_input(
            "reminder_minutes", "Reminder delay in minutes",
            value=str(settings["reminder_minutes"]), required=True,
            min_length=1, max_length=5, placeholder="30 (1 to 10080)",
            style=hikari.TextInputStyle.SHORT,
        )],
    )


@register_action("gauntlet_help_save", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def save_delay(ctx: Any, action_id: str,
                     mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _ack_modal(ctx)
    state, problem = await _content_state(ctx, mongo, action_id)
    if problem:
        await _modal_edit(ctx, error_panel(problem))
        return
    raw = _modal_value(ctx, "reminder_minutes").strip()
    try:
        minutes = int(raw)
    except ValueError:
        minutes = 0
    if raw != str(minutes) or not 1 <= minutes <= 10080:
        await _modal_edit(ctx, panel(
            state, await _settings(mongo),
            "Enter a whole number from 1 to 10,080 minutes.",
        ))
        return
    from utils.gauntlet_help import save_settings

    actor_id, _guild_id = _identity(ctx)
    if actor_id is None:
        await _modal_edit(ctx, error_panel("Your account could not be identified. Reopen /manage."))
        return
    await save_settings(mongo, GUILD_ID, minutes, actor_id)
    await _modal_edit(ctx, panel(
        state, await _settings(mongo), f"Reminder delay saved: {minutes} minutes.",
    ))
