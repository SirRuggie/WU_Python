# extensions/commands/setup/recruit_familyparticulars.py
"""
Warriors United Family Particulars command - displays clan rules, war information, and CWL details
"""

import hikari
import lightbulb
import uuid

from extensions.commands.setup import loader, setup
from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient
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
    """Render Family Particulars for publishing or dashboard previews."""
    if sections is not None and len(sections) != 28:
        raise ValueError("Family Particulars requires exactly twenty-eight text fields.")

    media = media or {}

    def image(slot, default):
        return media.get(slot, default)

    components = [
            # Image at the top
            Media(
                items=[
                    MediaItem(
                        media=image("welcome", "assets/recruit/static/WU_FamilyParticulars.gif")
                    )
                ]
            ),
            
            # Embed 1: Family Particulars
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Warriors United Family Particulars**"),
                    Separator(divider=True),
                    Text(content="### **GOLDEN RULE**\n"),
                    Text(content=(
                        "The main rule for any Group or Gathering is \"To treat and speak to others as you would expect to be "
                        "treated or spoken to.\" We understand that not every day is a good day. Just don't bring your bad day in here."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **FRIENDLY CHALLENGES**\n"),
                    Text(content=(
                        "Everytime you come into the game, put up a Friendly Challenge. No matter what Town Hall Level you are. "
                        "This gives anyone and everyone a chance to practice."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **CLAN GAMES**\n"),
                    Text(content=(
                        "Simple and easy achievement here...each member has to achieve at least 1000 point minimum as a goal for "
                        "Clan Games. Builder Base challenges will get you there in no time. Giving you a math figure, if 40 participate "
                        "and achieve 1,250 points that will equal out to the needed 50,000."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                ]
            ),
            
            # Embed 2: Family War Rules
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Family War Rules**"),
                    Separator(divider=True),
                    Text(content="### 🛡 **WAR ELIGIBILITY**\n"),
                    Text(content=(
                        "To be included in war you must have a GREEN ✅ 🛡️ (opt-in) as your War Status. FWA/No Stress is explained below\n\n"
                        "If for any personal reason, you cannot participate in war or you have Heroes upgrading in a Clan that requires "
                        "Heroes in War; RED ❌ 🛡️ (opt-out) should be your War Status.\n\n"
                        "Failure to communicate or change your war availability in any of the above scenarios will result in a strike "
                        "within the WU_Strike System.\n\n"
                        "If you are in one of our FWA Clans or one of our No Stress Clans, it's 50v50 Wars so no matter what your "
                        "base is upgrading you should be ✅ with your War Status."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **PREP DAY**\n"),
                    Text(content=(
                        "Everyone is expected to help fill Defensive CC. You are responsible for filling the member below you with "
                        "the Troops they desire. No need to let one person fill all when it can be a joint effort."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **BATTLE DAY**\n"),
                    Text(content=(
                        "Our Clan War General will provide a scripted War Plan detailing your war assignment. Don't always assume "
                        "you will be attacking your Mirror/Equal. Wait for the War Plan before attacking. If one is not provided "
                        "in a timely fashion ping your Clan's War General Role and ask. Don't just go rogue. 24hrs is plenty of "
                        "time to plan and attack. Always attack for stars, not for loot or hero status. (Unless given specific "
                        "direction by the War General)"
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                ]
            ),
            
            # Embed 3: Clan War League
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## <:warriorcat:947992348971905035> **Warriors United Clan War League**"),
                    Separator(divider=True),
                    Text(content=(
                        "CWL is our pinnacle team event. Your clan is expecting and counting on you to ensure the entire team has "
                        "the best shot at success. We split up into different clans for this event. Three factors determine the "
                        "League you'll be placed:\n"
                        "1) War activity\n"
                        "2) War performance\n"
                        "3) Account strength.\n\n"
                        "Participation is not mandatory but the completion of a simple Google \"CWL Form\" before the given deadline "
                        "is mandatory for participation. No exceptions to the deadline. The data compiled from this form allows Clan "
                        "Leaders and War General's to produce Clan Rosters. We have several Clans in the Family so everyone can have "
                        "a shot at some medals. If you have multiple accounts, only three are allotted to be in one Clan Roster.\n\n"
                        "No form, No Play...pretty simple."
                    )),
                    Text(content="\nᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Text(content="### 🛡 **Principles for every CWL Battle**\n"),
                    Text(content=(
                        "--Be available to attack and make sure you request offensive CC Troops.\n\n"
                        "--Have you heroes ready for battle.\n\n"
                        "--Have your defensive CC Troop Request laid out plainly. (e.g. Ice Golem/ Dragon or IG/Drag)\n\n"
                        "--Donate Defensive CC Troops to the player below you and/or at least one or more of your teammates, "
                        "making sure they are Max Troops.\n\n"
                        "--Make a plan of attack. You have 24hrs for one attack.\n\n"
                        "Make use of our Attack Trainer's in the \"Help-Me-Attack-This-Base\" Channels."
                    )),
                    Text(content="ᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖᨖ"),
                    Media(
                        items=[
                            MediaItem(
                                media=image("cwl", "assets/branding/banners/warriors_united_.gif")
                            )
                        ]
                    ),
                ]
            ),
            
            # Embed 4: Acknowledgment
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content="## 📜 **ACKNOWLEDGMENT**"),
                    Separator(divider=True),
                    Text(content=(
                        "Click **I understand - Continue** to confirm you have read and acknowledge our Family Particulars, then continue to Apply to open an application ticket.\n\nChoose only one application ticket option."
                    )),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SUCCESS,
                                custom_id=f"familyparticulars_acknowledge:{action_id}",
                                label="I understand - Continue",
                                emoji=hikari.Snowflake(ICONS["yes"])
                            )
                        ]
                    )
                ]
            ),
    ]
    if sections is not None:
        values = iter(sections)
        components = [
            Container(
                accent_color=component.accent_color,
                components=[
                    Text(content=next(values)) if isinstance(child, Text) else child
                    for child in component.components
                ],
            ) if isinstance(component, Container) else component
            for component in components
        ]
    if preview:
        components[-1].components[-1].components[0].set_is_disabled(True)
    return components


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
        saved = await mongo.bot_config.find_one({"_id": f"content:family-particulars:{ctx.guild_id}"})
        if saved:
            from extensions.commands.content import DOCUMENTS, render
            try:
                components = await render(
                    DOCUMENTS["family-particulars"], saved["sections"], media=saved.get("media"),
                    action_id=str(uuid.uuid4()),
                )
            except (KeyError, ValueError):
                saved = None
        if not saved:
            components = build_familyparticulars(action_id=str(uuid.uuid4()))
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await ctx.respond("Family Particulars posted.", ephemeral=True)


def _continue_components(guild_id: int):
    """Build the private V2 prompt that sends members to the application tickets."""
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content="## :shield: Continue to Apply"),
                Text(content="Open an application ticket to continue the Recruit Gauntlet."),
                ActionRow(components=[
                    LinkButton(
                        url=f"https://discord.com/channels/{guild_id}/{APPLY_HERE_CHANNEL_ID}",
                        label="Continue to Apply",
                        emoji=hikari.Snowflake(ICONS["open"]),
                    )
                ]),
            ],
        )
    ]


async def _private_continue(ctx, guild_id: int) -> None:
    """Respond privately without altering the published onboarding panel."""
    await ctx.interaction.execute(
        components=_continue_components(guild_id),
        flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
    )


async def _private_error(ctx, message: str) -> None:
    """Send an actionable private error without exposing internal failures."""
    await ctx.interaction.execute(content=message, flags=hikari.MessageFlag.EPHEMERAL)


@register_action("familyparticulars_acknowledge", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_familyparticulars_acknowledge(
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs,
):
    """Grant application-ticket access and privately offer the Apply link."""
    del action_id
    ctx = kwargs["ctx"]
    interaction_guild_id = getattr(ctx.interaction, "guild_id", None)
    user_id = int(ctx.user.id)

    try:
        target_channel = await bot.rest.fetch_channel(APPLY_HERE_CHANNEL_ID)
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
        or int(target_guild_id) != FAMILY_PARTICULARS_GUILD_ID
    ):
        await _private_error(ctx, "This Family Particulars panel can only be used in the Warriors United server.")
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

    if CLAN_RULES_READ_ROLE_ID not in {int(role_id) for role_id in getattr(member, "role_ids", ())}:
        try:
            await bot.rest.add_role_to_member(
                guild=guild_id, user=user_id, role=CLAN_RULES_READ_ROLE_ID,
            )
        except hikari.HTTPError:
            await _private_error(ctx, "I could not grant application-ticket access right now. Please try again shortly.")
            return
        except Exception:
            await _private_error(ctx, "I could not grant application-ticket access right now. Please try again shortly.")
            return

    await _private_continue(ctx, guild_id)


loader.command(setup)
