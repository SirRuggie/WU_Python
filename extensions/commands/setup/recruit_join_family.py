"""The first Warriors United Recruit Gauntlet panel: Join the Family."""

from __future__ import annotations

import hikari
import lightbulb

from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT
from utils.manage_ui import ICONS
from utils.mongo import MongoClient
from utils.gauntlet_tracking import track_progress

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    LinkButtonBuilder as LinkButton,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)


# This panel is intentionally a content document rather than a slash command.
# The Recruit Gauntlet editor creates and publishes its messages.
JOIN_FAMILY_ROLE_ID = 1551011479577165844
ABOUT_US_CHANNEL_ID = 1547241886954168430
JOIN_FAMILY_GUILD_ID = 644963518025826315


def build_join_family(sections=None, *, media=None, action_id="preview", preview=False):
    """Render the Join the Family panel for publishing or editor previews."""
    if sections is not None and len(sections) != 3:
        raise ValueError("Join the Family requires exactly three editable text fields.")
    values = iter(sections) if sections is not None else None
    media = media or {}

    def text(default):
        return Text(content=next(values) if values is not None else default)

    components = [
        Media(items=[MediaItem(media=media.get("welcome", "assets/branding/banners/Warriors_United.gif"))]),
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                text(
                    "Welcome, Warrior. The Recruit Gauntlet begins here—your guide to the Warriors United "
                    "family, its clans, wars, and community."
                ),
                text(
                    "### **What happens next**\n"
                    "Tap the button below to unlock the family welcome area. From there, learn who we are, "
                    "read the required steps, and continue through recruitment. When you have completed the "
                    "Recruit Gauntlet, open an application ticket to apply."
                ),
                text(
                    "### **Ready to begin?**\n"
                    "Choose **Join the Family** to get access to the next step."
                ),
                ActionRow(components=[
                    Button(
                        style=hikari.ButtonStyle.SUCCESS,
                        custom_id=f"join_family_acknowledge:{action_id}",
                        label="Join the Family",
                        emoji=hikari.Snowflake(ICONS["yes"]),
                    )
                ]),
            ],
        ),
    ]
    if preview:
        components[-1].components[-1].components[0].set_is_disabled(True)
    return components


def _continue_components(guild_id: int, message: str):
    """A private, clickable next step. Discord cannot open a channel for a user."""
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content="## :shield: Gauntlet access unlocked"),
                Text(content=message),
                ActionRow(components=[
                    LinkButton(
                        url=f"https://discord.com/channels/{guild_id}/{ABOUT_US_CHANNEL_ID}",
                        label="Continue to About Us",
                        emoji=hikari.Snowflake(ICONS["open"]),
                    )
                ]),
            ],
        )
    ]


async def _private_continue(ctx, guild_id: int, message: str) -> None:
    """Send a private V2 followup, never edit the public panel that was clicked."""
    components = _continue_components(guild_id, message)
    await ctx.interaction.execute(
        components=components,
        flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
    )


async def _private_error(ctx, message: str) -> None:
    """Errors are private and never promise access that was not granted."""
    await ctx.interaction.execute(content=message, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("join_family_acknowledge", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_join_family_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> None:
    """Grant the join role and privately offer the About Us channel link."""
    del action_id
    ctx = kwargs["ctx"]
    interaction_guild_id = getattr(ctx.interaction, "guild_id", None)
    user_id = int(ctx.user.id)

    # The target channel is fetched every click: cached guild data can be stale
    # after a restart, and this prevents a panel copied into another server from
    # assigning the role there.
    try:
        target_channel = await bot.rest.fetch_channel(ABOUT_US_CHANNEL_ID)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not open the next onboarding channel right now. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not verify the next onboarding channel right now. Please try again shortly.")
        return

    target_guild_id = getattr(target_channel, "guild_id", None)
    if (
        interaction_guild_id is None
        or target_guild_id is None
        or int(interaction_guild_id) != int(target_guild_id)
        or int(target_guild_id) != JOIN_FAMILY_GUILD_ID
    ):
        await _private_error(ctx, "This Join the Family panel can only be used in the Warriors United server.")
        return

    guild_id = int(target_guild_id)
    # Use REST even when cache has a member: cached role_ids can lag a recent role change.
    try:
        member = await bot.rest.fetch_member(guild_id, user_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not find your member profile in this server. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not verify your member profile right now. Please try again shortly.")
        return

    if JOIN_FAMILY_ROLE_ID in {int(role_id) for role_id in getattr(member, "role_ids", ())}:
        await track_progress(mongo, guild_id, user_id, 1)
        await _private_continue(ctx, guild_id, "You already have access to the Recruit Gauntlet. Continue to About Us to work through the required steps.")
        return

    try:
        await bot.rest.add_role_to_member(guild=guild_id, user=user_id, role=JOIN_FAMILY_ROLE_ID)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not grant family access right now. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not grant family access right now. Please try again shortly.")
        return

    await track_progress(mongo, guild_id, user_id, 1)
    await _private_continue(ctx, guild_id, "Continue to About Us to begin the Recruit Gauntlet and work through the required steps.")
