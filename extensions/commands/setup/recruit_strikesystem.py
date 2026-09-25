# extensions/commands/setup/recruit_strikesystem.py
"""
Warriors United Strike System command - displays clan rules and strike system information
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient
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
    """Render the Strike System post for publishing or dashboard previews."""
    if sections is not None and len(sections) != 12:
        raise ValueError("Strike System requires exactly twelve editable text fields.")
    values = iter(sections) if sections is not None else None
    media = media or {}

    def text(default):
        return Text(content=next(values) if values is not None else default)

    def image(slot, default):
        return media.get(slot, default)

    components = [
            # Image at the top
            Media(
                items=[
                    MediaItem(
                        media=image("rules", "assets/recruit/strikes/WU_Strikes.gif")
                    )
                ]
            ),
            
            # Embed 1: Basic Rules
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    text("## 📜 **Warriors United Basic Rules** 📜"),
                    Separator(divider=True),
                    text((
                        "🛡️**WARRIORS UNITED**🛡️ is an adult community with good morals and ethics. A little banter and cutting up "
                        "is acceptable however, there are some things that just won't be tolerated...\n\n"
                        "**1.** No form of sexism, racism, religious discrimination, gender discrimination will be tolerated. "
                        "A permanent ban will be issued without a warning if this is seen anywhere on this server.\n\n"
                        "**2.** While cussing is allowed, do not cuss excessively or at someone. All such instances will be recorded. "
                        "A warning will be issued to you on each instance.\n\n"
                        "**3.** Don't post advertisements for free nitro. We don't check if they are actually legit and will ban "
                        "without a warning.\n\n"
                        "**4.** Respect other members and their privacy. If you DM someone repeatedly even after them telling you "
                        "not to do so, a warning will be issued against you.\n\n"
                        "**5.** While posting a message / image / gif / sticker, you should always follow discord ToS. "
                        "It can be found at https://discord.com/terms. Not following Discord ToS will lead to a one day mute, "
                        "and a second instance will lead to ban from the server.\n\n"
                        "On two warnings - A one day timeout will be issued to you.\n"
                        "On three warnings - A one week timeout will be issued to you.\n"
                        "On four warnings - A permanent ban from the server, along with a kick from the family in CoC will be issued."
                    )),
                ]
            ),
            
            # Embed 2: Strike System Overview
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    text("## ❌ **Warrior's United Strike System** ❌"),
                    Separator(divider=True),
                    text((
                        "Our Strike System is a penalty system in which strikes are given to members who violate the rules and "
                        "principles implemented within the Warrior's United Clan Family.\n\n"
                        "Violations have different set strikes that go along with them. It's not the amount violations you develop "
                        "but rather the amount of strikes. For example, missing both attacks in War is one violation that results "
                        "in two strikes. Members have a total of 4 strikes before disciplinary action is taken place. Once maximum "
                        "strikes are received, you will have 12hrs to open up a Ticket and discuss your situation. Failure to comply "
                        "will result in a kick from the Clan and a ban from any other Clan within the Family for a week. After one "
                        "week with no reply, your Clan Roles are stripped back to as if you just joined the Server.\n\n"
                        "All strikes are given per individual account, with the exception of civil behavior offenses. If multiple "
                        "strikes are broken within a single action, only the strike count of the more severe offense is counted; "
                        "both strikes are still noted.\n\n"
                        "Strike data is compiled and executed by the WU Strike Bot. Depending on the strike it will have a time "
                        "limit to reset. Generally speaking, it's a 60-day reset.\n\n"
                        "Below are charts of offenses and how much value each offense holds."
                    )),
                ]
            ),
            
            # Embed 3: Main Clan Strike System
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    text("## ❌ **MAIN CLAN STRIKE SYSTEM** ❌"),
                    Separator(divider=True),
                    text("Check below for the main clan strike system rules."),
                    Media(
                        items=[
                            MediaItem(
                                media=image("main-strikes", "assets/recruit/strikes/WU_Main_Strikes.jpg")
                            )
                        ]
                    ),
                ]
            ),
            
            # Embed 4: FWA Strike System
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    text("## ❌ **FWA STRIKE SYSTEM** ❌"),
                    Separator(divider=True),
                    text("Check below for fwa clan strike system rules."),
                    Media(
                        items=[
                            MediaItem(
                                media=image("fwa-strikes", "assets/recruit/strikes/WU_FWA_Strikes.jpg")
                            )
                        ]
                    ),
                ]
            ),
            
            # Embed 5: Terms and Conditions
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    text("## ❌ **Terms and conditions** ❌"),
                    Separator(divider=True),
                    text((
                        "• All offenses except those that reside in the Red Zone can have warnings issued before strikes are given. "
                        "Issuing warnings is up to the leadership team, and warnings will be logged.\n\n"
                        "• Strikes can be withdrawn by leadership majority.\n\n"
                        "• Leadership has the right to make changes and amendments to this system at any time in-between seasons.\n\n"
                        "• A kicked person may be reinvited to the Family after a unanimous vote by Leadership."
                    )),
                ]
            ),
            
            # Embed 6: Acknowledgment
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    text("## 📜 **ACKNOWLEDGMENT**"),
                    Separator(divider=True),
                    text((
                        "Choose **I understand - Continue** to confirm you have read and agree to follow the Warriors United Strike System, "
                        "then continue to Family Particulars for the next Recruit Gauntlet step."
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"strikesystem_acknowledge:{action_id}",
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
        saved = await mongo.bot_config.find_one({"_id": f"content:strike-system:{ctx.guild_id}"})
        if saved:
            from extensions.commands.content import DOCUMENTS, render
            try:
                components = await render(
                    DOCUMENTS["strike-system"], saved["sections"], media=saved.get("media"),
                    action_id=str(uuid.uuid4()),
                )
            except (KeyError, ValueError):
                saved = None
        if not saved:
            components = build_strikesystem(action_id=str(uuid.uuid4()))
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await ctx.respond("WU Strike System posted.", ephemeral=True)


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
                        url=f"https://discord.com/channels/{guild_id}/{FAMILY_PARTICULARS_CHANNEL_ID}",
                        label="Continue to Family Particulars",
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

    try:
        target_channel = await bot.rest.fetch_channel(FAMILY_PARTICULARS_CHANNEL_ID)
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
        or int(target_guild_id) != STRIKE_SYSTEM_GUILD_ID
    ):
        await _private_error(ctx, "This Strike System panel can only be used in the Warriors United server.")
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

    if STRIKE_SYSTEM_ROLE_ID in {int(role_id) for role_id in getattr(member, "role_ids", ())}:
        await track_progress(mongo, guild_id, user_id, 3)
        await _private_continue(ctx, guild_id, "You already have access to Family Particulars. Continue to Family Particulars for the next Recruit Gauntlet step.")
        return

    try:
        await bot.rest.add_role_to_member(guild=guild_id, user=user_id, role=STRIKE_SYSTEM_ROLE_ID)
    except hikari.HTTPError:
        await _private_error(ctx, "I could not grant access to Family Particulars right now. Please try again shortly.")
        return
    except Exception:
        await _private_error(ctx, "I could not grant access to Family Particulars right now. Please try again shortly.")
        return

    await track_progress(mongo, guild_id, user_id, 3)
    await _private_continue(ctx, guild_id, "Continue to Family Particulars for the next Recruit Gauntlet step.")


loader.command(setup)
