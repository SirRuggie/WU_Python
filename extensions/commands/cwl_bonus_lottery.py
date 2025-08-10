# extensions/commands/cwl_bonus_lottery.py
"""
Lazy CWL Bonuses command for randomly selecting bonus medal recipients
"""

import hikari
import lightbulb
import random
from datetime import datetime, timezone
from dateutil.relativedelta import relativedelta

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.constants import GOLDENROD_ACCENT

loader = lightbulb.Loader()

# Configuration - Easy to change
LAZY_CWL_CHANNEL = 947166650321494067


def get_last_three_months():
    """Get the last 3 months as choices for the command"""
    now = datetime.now(timezone.utc)
    months = []
    
    for i in range(3):
        month_date = now - relativedelta(months=i)
        month_name = month_date.strftime("%B %Y")
        months.append(lightbulb.Choice(month_name, month_name))
    
    return months


@loader.command()
class LazyBonusLottery(
    lightbulb.SlashCommand,
    name="lazycwl-bonuses",
    description="Randomly select Lazy CWL bonus medal recipients"
):
    bonuses = lightbulb.integer(
        "bonuses",
        "Number of bonuses to give out",
        min_value=1,
        max_value=50
    )
    
    month = lightbulb.string(
        "month",
        "Month for the bonuses",
        choices=get_last_three_months()
    )
    
    clan_name = lightbulb.string(
        "clan_name", 
        "Name of the Lazy CWL clan",
        max_length=100
    )
    
    players = lightbulb.string(
        "players",
        "Comma-separated list of players (repeat names for higher chances)",
        max_length=4000  # Discord's max for option values
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

        # Parse players list
        player_list = [p.strip() for p in self.players.split(",") if p.strip()]
        
        if not player_list:
            await ctx.respond(
                "❌ No players provided! Please enter a comma-separated list of players.",
                ephemeral=True
            )
            return
        
        # Get unique players for display
        unique_players = list(set(player_list))
        unique_players.sort()  # Sort alphabetically
        
        # Check if we have enough players
        if len(player_list) < self.bonuses:
            await ctx.respond(
                f"❌ Not enough player entries ({len(player_list)}) for {self.bonuses} bonuses!\n"
                f"Add more players or add some players multiple times for higher chances.",
                ephemeral=True
            )
            return
        
        # Randomly select winners
        try:
            winners = random.sample(player_list, self.bonuses)
        except ValueError:
            await ctx.respond(
                "❌ Error selecting winners. Make sure you have enough player entries.",
                ephemeral=True
            )
            return
        
        # Create the announcement components
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"## {self.clan_name} Lazy CWL Bonus Medal recipients for {self.month}"),
                    Separator(divider=True),
                    Text(content=f"**All eligible players ({len(unique_players)} players) with {self.bonuses} bonuses to give:**"),
                    Text(content="\n".join([f"• {player}" for player in unique_players])),
                    Separator(divider=True),
                    Text(content="## 🎉 **Randomly selected winners:**"),
                    Text(content="\n".join([f"**{i+1}.** {winner}" for i, winner in enumerate(winners)])),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
                    Separator(divider=True),
                    Text(content=f"-# 🎲 Lottery drawn by {ctx.member.mention}")
                ]
            )
        ]
        
        # Send to the Lazy CWL channel
        try:
            await bot.rest.create_message(
                channel=LAZY_CWL_CHANNEL,
                components=components
            )
            
            # Confirm to the user
            await ctx.respond(
                f"✅ Lottery results posted to <#{LAZY_CWL_CHANNEL}>!\n\n"
                f"**Winners selected:** {', '.join(winners)}",
                ephemeral=True
            )
            
        except Exception as e:
            await ctx.respond(
                f"❌ Failed to send lottery results: {str(e)}",
                ephemeral=True
            )