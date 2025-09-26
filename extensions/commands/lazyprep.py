# extensions/commands/lazyprep.py
"""
Lazy CWL preparation announcements command
"""

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.constants import GOLDENROD_ACCENT

loader = lightbulb.Loader()

# Configuration
LAZY_CWL_CHANNEL = 947166650321494067
LAZY_CWL_ROLE = 1080521665584308286
FWA_FAMILY_ROLE = 772313841090297886  # For Declaration Complete ping


def create_declaration_complete_message():
    """Create declaration complete announcement message"""
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=f"<@&{FWA_FAMILY_ROLE}>"),
                Separator(divider=True),
                Text(content="## ⚔️CWL League Declaration is Complete!!!!⚔️"),
                Separator(divider=True),
                Text(content=(
                    "Make sure we're leaving FWA Bases as active and Request CC Troops in FWA.\n\n"
                    "**Train ⇨ Join ⇨ Attack ⇨ Return...15-30min tops**"
                )),
                Separator(),
                Text(content=(
                    "```The War Plan in Lazy 84, 83, 82 81 is Mirror Attacks!!(Mirror = same base # as you),\n"
                    "The other clans have a little wiggle room at the bottom, you have two choices...\n\n"
                    "1) Hit your mirror\n\n"
                    "2) Drop down to a TH 3/2 Filler and hit it's mirror. Note I said drop down not up!!\n\n"
                    "Don't abuse this feature...if you have done your 8 Stars...hit your Mirror...don't get greedy.\n"
                    "Another option is if someone lower (or higher) has goose egged (goose egged = zero star)...it's available.```"
                )),
                Text(content="**AGAIN...If your in Lazy 84, 83, 82, 81.... MIRROR ATTACKS!!!**"),
                Separator(),
                Text(content=(
                    "```We will be continuing the system from last month\n"
                    "TLDR: Non-compliance with our LazyCWL rules = loss of Bonus Medal Spin this month, risk of being placed in a lower league next month```"
                )),
                Text(content="**The 3 main rules for Lazy CWL**"),
                Text(content=(
                    "1. Always keep your FWA base as your active War Base.\n"
                    "2. Always attack your Mirror (same number in War Lineup) in CWL. Exceptions….a) agree with someone else to swap bases.  b) Hitting a base that was already hit with a zero star result. c) TH8 or lower in the lineup are fillers. These are available to anyone.\n"
                    "3. Do not linger or stay in the CWL clan longer than needed. Join, attack, then leave. Simple."
                )),
                Separator(),
                Text(content=(
                    "We will leave FWA Clans set to \"Anyone Can Join\". This has proved to work really well with not a lot of outsiders attempting to join. If someone that your not familiar with does join, greet them and find out if they understand what FWA is. From there Leadership will decide if they stay or not.\n\n"
                    "Lazy Clans will still close in between FWA wars. The best way to not miss FWA Wars is to remember this....\n"
                    "`If we're not currently in a War...DON'T MOVE...STAY PUT...another one will start soon.`"
                )),
                Text(content=f"Any questions about the process haller at a FWA Rep in <#872692009066958879>"),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
            ]
        )
    ]


def create_closed_message():
    """Create closed announcement message"""
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=f"<@&{LAZY_CWL_ROLE}>"),
                Separator(divider=True),
                Text(content=(
                    "CWL Clans are closed in order to prepare for next FWA War.\n\n"
                    "The closing of CWL Clans is to ensure all are available for next FWA War search. They will reopen during FWA Prep Day. Everyone stay put please...👍🏻"
                )),
                Separator(),
                Text(content="**Don't be \"that guy\"**"),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
            ]
        )
    ]


def create_open_message():
    """Create open announcement message"""
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=f"<@&{LAZY_CWL_ROLE}>"),
                Separator(divider=True),
                Text(content=(
                    "CWL clans are back open. Request in your Home Clan for higher levels, go attack and return back to FWA ASAP. Invites will be sent for easy return back to FWA. Check war times in Discord..."
                )),
                Separator(),
                Text(content=(
                    "**Train ⇨ Join ⇨ Attack ⇨ Return**\n"
                    "__**15-30min tops**__"
                )),
                Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
            ]
        )
    ]


@loader.command()
class LazyPrep(
    lightbulb.SlashCommand,
    name="lazyprep",
    description="Send Lazy CWL preparation announcements"
):
    type = lightbulb.string(
        "type",
        "Type of announcement to send",
        choices=[
            lightbulb.Choice("Declaration Complete", "declaration"),
            lightbulb.Choice("Closed", "closed"),
            lightbulb.Choice("Open", "open")
        ]
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True
            )
            return

        await ctx.defer(ephemeral=True)

        if self.type == "declaration":
            # Declaration Complete message
            components = create_declaration_complete_message()
            role_to_ping = FWA_FAMILY_ROLE

        elif self.type == "closed":
            # Closed message
            components = create_closed_message()
            role_to_ping = LAZY_CWL_ROLE

        else:  # open
            # Open message
            components = create_open_message()
            role_to_ping = LAZY_CWL_ROLE

        # Send to Lazy CWL channel
        try:
            await bot.rest.create_message(
                channel=LAZY_CWL_CHANNEL,
                components=components,
                role_mentions=[role_to_ping]
            )

            await ctx.respond(
                f"✅ Lazy CWL {self.type} announcement sent to <#{LAZY_CWL_CHANNEL}>!",
                ephemeral=True
            )

        except Exception as e:
            await ctx.respond(
                f"❌ Failed to send announcement: {str(e)}",
                ephemeral=True
            )


# Register the command with the loader
loader.command(LazyPrep)