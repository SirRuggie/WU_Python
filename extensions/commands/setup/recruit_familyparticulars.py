# extensions/commands/setup/recruit_familyparticulars.py
"""
Warriors United Family Particulars command - displays clan rules, war information, and CWL details
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.constants import WU_GOLD, WU_GREEN
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
CLAN_RULES_READ_ROLE_ID = 1553110621711634502
APPLY_HERE_CHANNEL_ID = 1547242779711766528
FAMILY_PARTICULARS_GUILD_ID = 644963518025826315


def build_familyparticulars(sections=None, *, media=None, action_id="preview", preview=False):
    """Keep saved field meanings and one topic per public box."""
    from utils.gauntlet_content import logical_sections, subtopic
    fields = logical_sections("family-particulars", sections)
    media = media or {}
    return [
        Media(items=[MediaItem(media=media.get("welcome", "assets/recruit/static/WU_FamilyParticulars.gif"))]),
        Container(accent_color=WU_GOLD, components=[Text(content=fields[28]), Text(content=fields[29])]),
        Container(accent_color=WU_GREEN, components=[Text(content=fields[30]),
            Text(content=subtopic("Friendly Challenges", fields[5])),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL), Text(content=subtopic("Clan Games", fields[8]))]),
        Container(accent_color=WU_GREEN, components=[Text(content=fields[31]),
            Text(content=subtopic("War Status", fields[12])),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL), Text(content=subtopic("Prep Day", fields[15])),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL), Text(content=subtopic("Battle Day", fields[18]))]),
        Media(items=[MediaItem(media=media.get("cwl", "assets/branding/banners/warriors_united_.gif"))]),
        Container(accent_color=WU_GREEN, components=[Text(content=fields[32]), Text(content=fields[21]),
            Separator(divider=True, spacing=hikari.SpacingType.SMALL), Text(content=subtopic("Every CWL Battle", fields[24]))]),
        Container(accent_color=WU_GOLD, components=[Text(content=fields[33]), Text(content=fields[27]),
            ActionRow(components=[Button(style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"familyparticulars_acknowledge:{action_id}", label="I understand - Continue",
                emoji=hikari.Snowflake(ICONS["yes"]), is_disabled=preview)]),
        ]),
    ]


class RecruitFamilyParticulars(
    lightbulb.SlashCommand,
    name="recruit-familyparticulars",
    description="Display Warriors United family particulars and war rules"
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
            ctx, bot, role_id=CLAN_RULES_READ_ROLE_ID, next_channel_id=APPLY_HERE_CHANNEL_ID
        ):
            return
        from extensions.commands.content import DOCUMENTS, render, template_for
        try:
            sections, media, _revision = await template_for(mongo, DOCUMENTS["family-particulars"], int(ctx.guild_id))
            components = await render(DOCUMENTS["family-particulars"], sections, media=media,
                                      action_id=str(uuid.uuid4()), mongo=mongo, guild_id=int(ctx.guild_id))
        except ValueError as error:
            await ctx.respond(str(error), ephemeral=True)
            return
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await ctx.respond("Family Particulars posted.", ephemeral=True)


def _continue_components(guild_id: int, *, url: str | None = None):
    """Build the private V2 prompt that sends members to the application tickets."""
    return [
        Container(
            accent_color=WU_GOLD,
            components=[
                Text(content="## :shield: Continue to Apply"),
                Text(content="Open an application ticket to continue the Recruit Gauntlet."),
                ActionRow(components=[
                    LinkButton(
                        url=url or f"https://discord.com/channels/{guild_id}/{route_for('family-particulars', guild_id)[1]}",
                        label="Continue to Apply",
                        emoji=hikari.Snowflake(ICONS["open"]),
                    )
                ]),
            ],
        )
    ]


async def _private_continue(ctx, guild_id: int, bot) -> None:
    """Respond privately without altering the published onboarding panel."""
    await observed("reply", ctx.interaction.execute,
        components=_continue_components(guild_id, url=await observed("destination_lookup", start_url, bot.rest, "family-particulars", guild_id)),
        flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
    )


async def _private_error(ctx, message: str) -> None:
    """Send an actionable private error without exposing internal failures."""
    gauntlet_event("rejected", reason=message)
    message = await notify_recruit_error(ctx, message)
    await observed("reply", ctx.interaction.execute, content=message, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("familyparticulars_acknowledge", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_familyparticulars_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
):
    """Grant application-ticket access and privately offer the Apply link."""
    del action_id
    ctx = kwargs["ctx"]
    interaction_guild_id = getattr(ctx.interaction, "guild_id", None)
    user_id = int(ctx.user.id)
    route = route_for("family-particulars", interaction_guild_id)
    if route is None:
        await _private_error(ctx, "This panel can only be used in a configured Warriors United server.")
        return
    role_id, next_channel_id = route

    try:
        target_channel = await observed("channel_check", bot.rest.fetch_channel, next_channel_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not open the application channel right now. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not verify the application channel right now. Please try again shortly.")
        return

    target_guild_id = getattr(target_channel, "guild_id", None)
    if (
        interaction_guild_id is None
        or target_guild_id is None
        or int(interaction_guild_id) != int(target_guild_id)
    ):
        await _private_error(ctx, "This Family Particulars panel can only be used in the Warriors United server.")
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
    if role_id not in {int(role_id) for role_id in getattr(member, "role_ids", ())}:
        try:
            await observed("role_assignment", bot.rest.add_role_to_member,
                guild=guild_id, user=user_id, role=role_id,
            )
        except hikari.HTTPError:
            await _private_error(ctx, "I could not grant application-ticket access right now. Please try again shortly.")
            return
        except Exception:
            await _private_error(ctx, "I could not grant application-ticket access right now. Please try again shortly.")
            return

    if guild_id == NEW_GUILD_ID:
        await observed("reminder_tracking", track_progress, mongo, guild_id, user_id, 4)
    await _private_continue(ctx, guild_id, bot)


loader.command(setup)
