# extensions/commands/setup/recruit_strikesystem.py
"""
Warriors United Strike System command - displays clan rules and strike system information
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.constants import WU_GOLD, WU_GREEN, WU_RED
from utils.mongo import MongoClient
from utils.recruit_error_reporting import notify as notify_recruit_error
from utils.gauntlet_diagnostics import observed, event as gauntlet_event
from utils.gauntlet_routes import start_url
from utils.gauntlet_routes import route_for, NEW_GUILD_ID
from utils.gauntlet_tracking import track_progress
from utils.manage_ui import ICONS
from utils.recruit_setup_checks import require_manage_server, require_ready

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    LinkButtonBuilder as LinkButton,
)

# Configuration
STRIKE_SYSTEM_ROLE_ID = 1553110508746448956
FAMILY_PARTICULARS_CHANNEL_ID = 1547242699873325116
STRIKE_SYSTEM_GUILD_ID = 644963518025826315


def build_strikesystem(sections=None, *, media=None, action_id="preview", preview=False):
    """Compose the five approved topic boxes without changing transport."""
    from utils.gauntlet_content import sections_for, subtopic
    fields = sections_for("strike-system", sections)
    media = media or {}
    return [
        Media(items=[MediaItem(media=media.get("rules", "assets/recruit/strikes/WU_Strikes.gif"))]),
        Container(accent_color=WU_RED, components=[Text(content=fields[14]), Text(content=fields[12])]),
        Container(accent_color=WU_GREEN, components=[Text(content=fields[15]), Text(content=fields[13])]),
        Container(accent_color=WU_RED, components=[Text(content=fields[16]), Text(content=fields[3])]),
        Container(accent_color=None, components=[
            Text(content=fields[17]), Text(content=subtopic("Main", fields[5])),
            Media(items=[MediaItem(media=media.get("main-strikes", "assets/recruit/strikes/WU_Main_Strikes.jpg"))]),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL),
            Text(content=subtopic("FWA", fields[7])),
            Media(items=[MediaItem(media=media.get("fwa-strikes", "assets/recruit/strikes/WU_FWA_Strikes.jpg"))]),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL), Text(content=subtopic("Terms", fields[9])),
        ]),
        Container(accent_color=WU_GOLD, components=[Text(content=fields[18]), Text(content=fields[11]),
            ActionRow(components=[Button(style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"strikesystem_acknowledge:{action_id}", label="I understand - Continue",
                emoji=hikari.Snowflake(ICONS["yes"]), is_disabled=preview)]),
        ]),
    ]


class RecruitStrikeSystem(
    lightbulb.SlashCommand,
    name="recruit-strikesystem",
    description="Display Warriors United strike system and rules"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not await require_manage_server(ctx):
            return
        await ctx.defer(ephemeral=True)
        if not await require_ready(
            ctx, bot, role_id=STRIKE_SYSTEM_ROLE_ID,
            next_channel_id=FAMILY_PARTICULARS_CHANNEL_ID,
        ):
            return
        from extensions.commands.content import DOCUMENTS, render, template_for
        try:
            sections, media, _revision = await template_for(mongo, DOCUMENTS["strike-system"], int(ctx.guild_id))
            components = await render(DOCUMENTS["strike-system"], sections, media=media,
                                      action_id=str(uuid.uuid4()), mongo=mongo, guild_id=int(ctx.guild_id))
        except ValueError as error:
            await ctx.respond(str(error), ephemeral=True)
            return
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await ctx.respond("WU Strike System posted.", ephemeral=True)


def _continue_components(guild_id: int, message: str, *, url: str | None = None):
    """Build the private V2 prompt that sends members to the next step."""
    return [
        Container(
            accent_color=WU_GOLD,
            components=[
                Text(content="## :shield: Next step unlocked"),
                Text(content=message),
                ActionRow(components=[
                    LinkButton(
                        url=url or f"https://discord.com/channels/{guild_id}/{route_for('strike-system', guild_id)[1]}",
                        label="Continue to Family Particulars",
                        emoji=hikari.Snowflake(ICONS["open"]),
                    )
                ]),
            ],
        )
    ]


async def _private_continue(ctx, guild_id: int, message: str, *, bot) -> None:
    """Respond privately without altering the published onboarding panel."""
    await observed("reply", ctx.interaction.execute,
        components=_continue_components(guild_id, message, url=await observed("destination_lookup", start_url, bot.rest, "strike-system", guild_id)),
        flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
    )


async def _private_error(ctx, message: str) -> None:
    """Send an actionable private error without exposing internal failures."""
    gauntlet_event("rejected", reason=message)
    message = await notify_recruit_error(ctx, message)
    await observed("reply", ctx.interaction.execute, content=message, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("strikesystem_acknowledge", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_strikesystem_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> None:
    """Grant Family Particulars access and privately offer the Family Particulars link."""
    del action_id
    ctx = kwargs["ctx"]
    interaction_guild_id = getattr(ctx.interaction, "guild_id", None)
    user_id = int(ctx.user.id)
    route = route_for("strike-system", interaction_guild_id)
    if route is None:
        await _private_error(ctx, "This panel can only be used in a configured Warriors United server.")
        return
    role_id, next_channel_id = route

    try:
        target_channel = await observed("channel_check", bot.rest.fetch_channel, next_channel_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not open the next onboarding channel. Try again in a few minutes.")
        return
    except Exception:
        await _private_error(ctx, "I could not verify the next onboarding channel right now. Please try again shortly.")
        return

    target_guild_id = getattr(target_channel, "guild_id", None)
    if (
        interaction_guild_id is None
        or target_guild_id is None
        or int(interaction_guild_id) != int(target_guild_id)
    ):
        await _private_error(ctx, "This Strike System panel can only be used in the Warriors United server.")
        return

    guild_id = int(target_guild_id)
    try:
        member = await observed("member_check", bot.rest.fetch_member, guild_id, user_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not find your member profile in this server. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not check your member profile. Try again in a few minutes.")
        return

    if role_id in {int(role_id) for role_id in getattr(member, "role_ids", ())}:
        gauntlet_event("role_already_present")
        if guild_id == NEW_GUILD_ID:
            await observed("reminder_tracking", track_progress, mongo, guild_id, user_id, 3)
        await _private_continue(ctx, guild_id, "You already have access to Family Particulars. Continue to Family Particulars for the next Recruit Gauntlet step.", bot=bot)
        return

    try:
        await observed("role_assignment", bot.rest.add_role_to_member, guild=guild_id, user=user_id, role=role_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not grant access to Family Particulars right now. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not grant access to Family Particulars right now. Please try again shortly.")
        return

    if guild_id == NEW_GUILD_ID:
        await observed("reminder_tracking", track_progress, mongo, guild_id, user_id, 3)
    await _private_continue(ctx, guild_id, "Continue to Family Particulars for the next Recruit Gauntlet step.", bot=bot)


loader.command(setup)
