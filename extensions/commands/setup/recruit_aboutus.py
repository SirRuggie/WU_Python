# extensions/commands/setup/recruit_aboutus.py
"""
Warriors United About Us command - displays clan information and onboarding flow
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT
from utils.manage_ui import ICONS
from utils.mongo import MongoClient
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


def build_aboutus(sections=None, *, media=None, action_id="preview", preview=False):
    """Single renderer for published messages and private editor previews."""
    if sections is not None and len(sections) != 12:
        raise ValueError("About Us requires exactly twelve editable text fields.")
    values = iter(sections) if sections is not None else None
    media = media or {}

    def text(default):
        # TextDisplayComponentBuilder has no set_content method in hikari 2.6.
        # Construct each display with its draft value so the pinned SDK can
        # render both editor previews and saved posts.
        return Text(content=next(values) if values is not None else default)

    def image(slot, default):
        return media.get(slot, default)

    # Create all embeds
    components = [
        # Image at the top
        Media(
            items=[
                MediaItem(
                    media=image("welcome", "assets/branding/banners/Warriors_United.gif")
                )
            ]
        ),

        # Embed 1: Welcome and Overview
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                text("## :shield: **Welcome to Warriors United!!** :shield:"),
                Separator(divider=True),
                text((
                    "We're an English-speaking Clan Family based in the USA but have Clasher's from all over the Globe. "
                    "We've developed system of game play that allows you to war no matter what the upgrade status of your base is.\n\n"
                    "**Note of mention** None of our clans are Family Friendly Clans. So if you know your account(s) will require "
                    "this; need to look elsewhere...👍🏼\n\n"
                    "Here's what we will provide:\n"
                    ":shield: 2 High Level Tactical Clans\n"
                    ":shield: 3 Flexible Fun War Clans\n"
                    ":shield: 5 Official FWA Clans for Farmers\n"
                    ":shield: CWL chances for everyone\n"
                    ":shield: An Experienced Base Building Team\n"
                    ":shield: Experienced Attack Trainers"
                )),
                Separator(divider=True),
                text("## ☠️ **High Level Tactical Clans** ☠️"),
                text((
                    "**Funnies (#2Q9RLRCG)**\n"
                    "**WeAreBrother (#YQPYJCQ2)**\n\n"
                    "Our High Level Tactical Clans are TH13+ full maxed previous TH Level and always strive to obtain 3 ⭐'s in war. "
                    "Not to worry if you fail; they can't all be perfect; but we expect our members to follow the War Format set in place "
                    "and are committed to winning every war as part of an overall team effort.\n\n"
                    "Wars are always full strength, meaning no Heroes upgrading."
                )),
            ]
        ),

        # Embed 2: Flexible Fun War Clans
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                text("## 🪖 **Flexible Fun War Clans** 🪖"),
                text((
                    "**Warriors United (#2YRVY8YCP)**\n"
                    "**Noahs Ark (#8VPQCR2R)**\n"
                    "**Morning Woods! (#8VQP9VQ9)**\n\n"
                    "Our \"Flexible Fun\" Clans are relaxed Farm/War Clans that do 50v50 wars or highest amount possible. "
                    "You will be held accountable to make your first attack here but we won't hold you liable for performance. "
                    "No Heroes necessary!!\n\n"
                    "These clans are designed for lower level/more chill players. If your in a Tactical Clan and drop a Hero; "
                    "or more; upgrading and still want some war loot. Slide over to a Flexible Fun Clan and move back to Tactical "
                    "when upgrades are done.\n\n"
                    "Don't mistake these to be Camping Clans and not competitive. Like anyone we strive to win!!\n\n"
                    "No War Activity = No Clan Membership EzPz"
                )),
            ]
        ),

        # Embed 3: FWA Clans
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                text("## 💰 **FWA Clans** 💰"),
                text((
                    "**Clash of Thrones (#Q889GPL)**\n"
                    "**CoT Wildlings (#2YJVQUCYJ)**\n"
                    "**Four and Twenty (#8CV0GPPR)**\n"
                    "**The Horde (#2RRCJCI0)**\n"
                    "**PlaneClashers (#9UGQ0GL)**\n\n"
                    "FWA (Farm War Alliance) is an alliance of clans who have back to back organized wars for loot. "
                    "The war outcome is predetermined and simple War Plans are posted regarding the needed outcome. "
                    "Also a place with no Heroes necessary.\n\n"
                    "Minimum requirements: TH12 and above with war weight equal to or greater than 115 with all buildings "
                    "built for your current TH Level."
                )),
                Separator(divider=True),
                text("### **Disclaimer**"),
                text((
                    "Each new recruit is viewed on a case by case scenario and more details on each Clan Category will be "
                    "provided in your interview. The above requirements are a benchmark and are subject to Leadership's discretion."
                )),
            ]
        ),

        # Embed 4: Next Steps
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                text("## ⏩ **NEXT STEP**"),
                text((
                    "Choose **I understand - Continue** to unlock WU Strike System, then read its rules "
                    "and follow the next step of the Recruit Gauntlet."
                )),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            custom_id=f"aboutus_acknowledge:{action_id}",
                            label="I understand - Continue",
                            emoji=hikari.Snowflake(ICONS["yes"])
                        )
                    ]
                )
            ]
        ),
    ]

    if preview:
        components[-1].components[-1].components[0].set_is_disabled(True)
    return components


def default_sections():
    return [child.content for item in build_aboutus() if isinstance(item, Container)
            for child in item.components if isinstance(child, Text)]


def configured_sections(document):
    """Return a valid per-server template or the unchanged built-in copy."""
    sections = document.get("sections") if document else None
    if (
        not isinstance(sections, list)
        or len(sections) != 12
        or any(not isinstance(section, str) or not section.strip() for section in sections)
        or sum(map(len, sections)) > 4000
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
        document = await mongo.bot_config.find_one({"_id": f"content:about-us:{ctx.guild_id}"})
        if document:
            from extensions.commands.content import DOCUMENTS, render
            try:
                components = await render(
                    DOCUMENTS["about-us"], document["sections"], media=document.get("media"),
                    action_id=str(uuid.uuid4()),
                )
            except (KeyError, ValueError):
                document = None
        if not document:
            legacy = await mongo.bot_config.find_one({"_id": f"recruit_aboutus:{ctx.guild_id}"})
            components = build_aboutus(configured_sections(legacy), action_id=str(uuid.uuid4()))
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await ctx.respond("About Us posted.", ephemeral=True)


def _continue_components(guild_id: int, message: str):
    """Build the private V2 prompt that sends members to the next step."""
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content="## :shield: Next step unlocked"),
                Text(content=message),
                ActionRow(components=[
                    LinkButton(
                        url=f"https://discord.com/channels/{guild_id}/{STRIKE_SYSTEM_CHANNEL_ID}",
                        label="Continue to WU Strike System",
                        emoji=hikari.Snowflake(ICONS["open"]),
                    )
                ]),
            ],
        )
    ]


async def _private_continue(ctx, guild_id: int, message: str) -> None:
    """Respond privately without altering the published onboarding panel."""
    await ctx.interaction.execute(
        components=_continue_components(guild_id, message),
        flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
    )


async def _private_error(ctx, message: str) -> None:
    """Send an actionable private error without exposing internal failures."""
    await ctx.interaction.execute(content=message, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("aboutus_acknowledge", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_aboutus_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs,
) -> None:
    """Grant Strike System access and offer the WU Strike System link privately."""
    del action_id
    ctx = kwargs["ctx"]
    interaction_guild_id = getattr(ctx.interaction, "guild_id", None)
    user_id = int(ctx.user.id)

    try:
        target_channel = await bot.rest.fetch_channel(STRIKE_SYSTEM_CHANNEL_ID)
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
        or int(target_guild_id) != ABOUT_US_GUILD_ID
    ):
        await _private_error(ctx, "This About Us panel can only be used in the Warriors United server.")
        return

    guild_id = int(target_guild_id)
    try:
        member = await bot.rest.fetch_member(guild_id, user_id)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not find your member profile in this server. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not verify your member profile right now. Please try again shortly.")
        return

    if ABOUT_US_ROLE_ID in {int(role_id) for role_id in getattr(member, "role_ids", ())}:
        await _private_continue(ctx, guild_id, "You already have access to WU Strike System. Continue to the WU Strike System and work through the required Recruit Gauntlet steps.")
        return

    try:
        await bot.rest.add_role_to_member(guild=guild_id, user=user_id, role=ABOUT_US_ROLE_ID)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not grant access to WU Strike System right now. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not grant access to WU Strike System right now. Please try again shortly.")
        return

    await _private_continue(ctx, guild_id, "Continue to the WU Strike System and work through the required Recruit Gauntlet steps.")

loader.command(setup)
