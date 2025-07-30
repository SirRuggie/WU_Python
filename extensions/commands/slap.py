import lightbulb
import hikari
import aiohttp
import random
from typing import Optional

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.constants import RED_ACCENT

loader = lightbulb.Loader()

# Kawaii API configuration
KAWAII_API_TOKEN = "505227988229554179.io8f0JgibCkCj8zD7aBt"
KAWAII_API_URL = "https://kawaii.red/api/gif/slap/token={token}"

async def fetch_slap_gif(session: aiohttp.ClientSession) -> Optional[str]:
    """Fetch a random slap GIF from Kawaii API."""
    try:
        url = KAWAII_API_URL.format(token=KAWAII_API_TOKEN)
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                # Kawaii API returns the GIF URL directly in the response
                return data.get("response")
            else:
                print(f"Kawaii API error: {response.status}")
                return None
    except Exception as e:
        print(f"Error fetching from Kawaii API: {e}")
        return None

@loader.command
class Slap(
    lightbulb.SlashCommand,
    name="slap",
    description="Slap someone with a random GIF"
):
    target = lightbulb.user(
        "user",
        "Who do you want to slap?"
    )
    
    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        # Validate target
        if self.target.id == ctx.user.id:
            await ctx.respond("❌ You can't slap yourself! That's just weird...", ephemeral=True)
            return
            
        if self.target.is_bot:
            await ctx.respond("❌ You can't slap a bot! They have feelings too... maybe.", ephemeral=True)
            return
        
        await ctx.defer()
        
        # Fetch GIF from Kawaii API
        gif_url = None
        async with aiohttp.ClientSession() as session:
            gif_url = await fetch_slap_gif(session)
        
        if not gif_url:
            await ctx.respond("❌ Failed to fetch a slap GIF. Please try again!", ephemeral=True)
            return
        
        # Fun flavor texts
        flavor_texts = [
            "Ouch! That's gotta hurt!",
            "Right in the kisser!",
            "POW! Take that!",
            "That's gonna leave a mark...",
            "Critical hit!",
            "K.O.!",
            "Slapped into next week!",
            "Someone call 911!",
            "RIP their dignity!",
            "Absolutely demolished!"
        ]
        
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content=f"## 👋 **{ctx.member.display_name} slaps {self.target.mention}!**"),
                    Separator(divider=True),
                    Text(content=f"_{random.choice(flavor_texts)}_"),
                    Media(
                        items=[
                            MediaItem(media=gif_url)
                        ]
                    ),
                ]
            )
        ]
        
        # Delete deferred response
        await ctx.interaction.delete_initial_response()
        
        # Send message to channel
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=[self.target.id]
        )