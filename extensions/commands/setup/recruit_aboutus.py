# extensions/commands/setup/recruit_aboutus.py
"""
Warriors United About Us command - displays clan information and onboarding flow
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.constants import WU_GOLD
from utils.manage_ui import ICONS
from utils.mongo import MongoClient
from utils.recruit_error_reporting import notify as notify_recruit_error
from utils.gauntlet_diagnostics import observed, event as gauntlet_event
from utils.gauntlet_routes import start_url
from utils.gauntlet_routes import route_for, NEW_GUILD_ID
from utils.gauntlet_tracking import track_progress
from utils.recruit_setup_checks import require_manage_server, require_ready

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    LinkButtonBuilder as LinkButton,
    MediaGalleryItemBuilder as MediaItem,
)

# Configuration
ABOUT_US_ROLE_ID = 1553110276251979937
STRIKE_SYSTEM_CHANNEL_ID = 1547242610819604560
ABOUT_US_GUILD_ID = 644963518025826315


def build_aboutus(sections=None, *, media=None, action_id="preview", preview=False,
                  family_rules=None, clans=None, include_family_rules=True):
    """Build the public shape; registry I/O belongs to the shared async renderer."""
    from utils.info_channel_content import (
        about_us_defaults, about_us_sections, family_rules_sections, validate_fields,
    )
    fields = about_us_defaults() if sections is None else list(sections)
    validate_fields(fields, 12, "About Us")
    if clans is not None:
        fields = about_us_sections(fields, clans)
    media = media or {}
    components = [
        Media(items=[MediaItem(media=media.get("welcome", "assets/branding/banners/Warriors_United.gif"))]),
        Container(accent_color=WU_GOLD, components=[
            Text(content=fields[0]), Separator(divider=True), Text(content=fields[1]),
            Separator(divider=True), Text(content=fields[2]), Text(content=fields[3]),
        ]),
        Container(accent_color=WU_GOLD, components=[Text(content=fields[4]), Text(content=fields[5])]),
        Container(accent_color=WU_GOLD, components=[
            Text(content=fields[6]), Text(content=fields[7]), Separator(divider=True),
            Text(content=fields[8]), Text(content=fields[9]),
        ]),
    ]
    if include_family_rules:
        rules = family_rules_sections(family_rules)
        components.append(Container(accent_color=WU_GOLD, components=[Text(content=rules[0]), Text(content=rules[1])]))
    components.append(Container(accent_color=WU_GOLD, components=[
        Text(content=fields[10]), Text(content=fields[11]),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SUCCESS,
            custom_id=f"aboutus_acknowledge:{action_id}",
            label="I understand - Continue", emoji=hikari.Snowflake(ICONS["yes"]),
            is_disabled=preview,
        )]),
    ]))
    return components


def default_sections():
    from utils.info_channel_content import about_us_defaults
    return about_us_defaults()


def configured_sections(document):
    """Return a valid per-server template or the unchanged built-in copy."""
    sections = document.get("sections") if document else None
    if (
        not isinstance(sections, list)
        or len(sections) != 12
        or any(not isinstance(section, str) or not section.strip() for section in sections)
    ):
        return default_sections()
    return list(sections)


class RecruitAboutUs(
    lightbulb.SlashCommand,
    name="recruit-aboutus",
    description="Display Warriors United clan information and onboarding flow"
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
            ctx, bot, role_id=ABOUT_US_ROLE_ID, next_channel_id=STRIKE_SYSTEM_CHANNEL_ID
        ):
            return
        from extensions.commands.content import DOCUMENTS, render, template_for
        sections, media, _revision = await template_for(mongo, DOCUMENTS["about-us"], int(ctx.guild_id))
        try:
            components = await render(
                DOCUMENTS["about-us"], sections, media=media,
                action_id=str(uuid.uuid4()), mongo=mongo, guild_id=int(ctx.guild_id),
            )
        except ValueError as error:
            await ctx.respond(str(error), ephemeral=True)
            return
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await ctx.respond("About Us posted.", ephemeral=True)


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
                        url=url or f"https://discord.com/channels/{guild_id}/{route_for('about-us', guild_id)[1]}",
                        label="Continue to WU Strike System",
                        emoji=hikari.Snowflake(ICONS["open"]),
                    )
                ]),
            ],
        )
    ]


async def _private_continue(ctx, guild_id: int, message: str, *, bot) -> None:
    """Respond privately without altering the published onboarding panel."""
    await observed("reply", ctx.interaction.execute,
        components=_continue_components(guild_id, message, url=await observed("destination_lookup", start_url, bot.rest, "about-us", guild_id)),
        flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
    )


async def _private_error(ctx, message: str) -> None:
    """Send an actionable private error without exposing internal failures."""
    gauntlet_event("rejected", reason=message)
    message = await notify_recruit_error(ctx, message)
    await observed("reply", ctx.interaction.execute, content=message, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("aboutus_acknowledge", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_aboutus_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> None:
    """Grant Strike System access and offer the WU Strike System link privately."""
    del action_id
    ctx = kwargs["ctx"]
    interaction_guild_id = getattr(ctx.interaction, "guild_id", None)
    user_id = int(ctx.user.id)
    route = route_for("about-us", interaction_guild_id)
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
        await _private_error(ctx, "This About Us panel can only be used in the Warriors United server.")
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
            await observed("reminder_tracking", track_progress, mongo, guild_id, user_id, 2)
        await _private_continue(ctx, guild_id, "You already have access to WU Strike System. Go to WU Strike System and do the required Recruit Gauntlet steps.", bot=bot)
        return

    try:
        await observed("role_assignment", bot.rest.add_role_to_member, guild=guild_id, user=user_id, role=role_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not give you access to WU Strike System. Try again in a few minutes.")
        return
    except Exception:
        await _private_error(ctx, "I could not give you access to WU Strike System. Try again in a few minutes.")
        return

    if guild_id == NEW_GUILD_ID:
        await observed("reminder_tracking", track_progress, mongo, guild_id, user_id, 2)
    await _private_continue(ctx, guild_id, "Go to WU Strike System and do the required Recruit Gauntlet steps.", bot=bot)

loader.command(setup)
