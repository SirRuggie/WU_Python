# extensions/commands/recruit/codes.py
import lightbulb
import asyncio
import hikari
from typing import Optional, Dict
from datetime import datetime, timezone

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.commands.recruit import loader, recruit
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient
from utils.emoji import emojis

# Valid emoji codes for keeping it in the family
VALID_EMOJI_CODES = [
    "⚔️⚔️⚔️",
    "⚔️🍻⚔️",
    "⚔️☠️⚔️"
]

# Store active listeners
active_listeners: Dict[int, Dict] = {}


@recruit.register()
class RecruitCodes(
    lightbulb.SlashCommand,
    name="codes",
    description="Send 'Keeping it in the Family' codes to a new recruit"
):
    user = lightbulb.user(
        "user",
        "Select the recruit to send codes to"
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Create the embed
        components = [
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=[
                    Text(content=f"<@{self.user.id}>"),
                    Separator(divider=True),
                    Text(content="## Keeping it in the Family"),
                    Text(content=(
                        "Warriors United family members may move around the family for "
                        "donations, a Friendly Challenge with an available member, helping "
                        "with Clan Games, or participation in a Family Event. When sending "
                        "a Clan Request use one of these three emoji combos as your "
                        "request message...."
                    )),
                    Text(content="\n**⚔️⚔️⚔️**\n**⚔️🍻⚔️**\n**⚔️☠️⚔️**\n"),
                    Text(content=(
                        f"**DO NOT** use the default join message... I'd like to join your clan.\n\n"
                        f"Acknowledge you understand this by sending one of the above "
                        f"three codes down below in chat. Just as you would if you were "
                        f"going to request to join!"
                    )),
                    Separator(divider=True),
                    Text(content=f"-# Command triggered by {ctx.member.display_name}"),
                ]
            )
        ]

        # Send the message without content parameter
        message = await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components,
            user_mentions=[self.user.id]
        )

        # Store listener info in MongoDB
        listener_data = {
            "_id": f"codes_{message.id}",
            "message_id": message.id,
            "channel_id": ctx.channel_id,
            "user_id": self.user.id,
            "moderator_id": ctx.user.id,
            "created_at": datetime.now(timezone.utc),
            "completed": False
        }
        await mongo.recruit_onboarding.insert_one(listener_data)

        # Store in active listeners
        active_listeners[message.id] = {
            "user_id": self.user.id,
            "channel_id": ctx.channel_id,
            "moderator_id": ctx.user.id
        }

        await ctx.respond(
            f"✅ Sent 'Keeping it in the Family' codes to {self.user.mention}. "
            f"Waiting for their response...",
            ephemeral=True
        )


@loader.listener(hikari.GuildMessageCreateEvent)
@lightbulb.di.with_di
async def on_code_response(
        event: hikari.GuildMessageCreateEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED
):
    """Listen for emoji code responses"""

    # Ignore bot messages
    if event.is_bot:
        return

    # Check if this user has an active listener
    for message_id, listener_info in list(active_listeners.items()):
        if (event.author_id == listener_info["user_id"] and
                event.channel_id == listener_info["channel_id"]):

            # Check if message contains valid code
            message_content = event.content.strip()
            if message_content in VALID_EMOJI_CODES:
                # Valid code received!
                # Update MongoDB
                await mongo.recruit_onboarding.update_one(
                    {"_id": f"codes_{message_id}"},
                    {
                        "$set": {
                            "completed": True,
                            "completed_at": datetime.now(timezone.utc),
                            "code_used": message_content
                        }
                    }
                )

                # Get moderator info for footer
                try:
                    moderator = await event.app.rest.fetch_member(event.guild_id, listener_info["moderator_id"])
                    moderator_name = moderator.display_name
                except:
                    moderator_name = "Unknown"

                # Send success message
                success_components = [
                    Container(
                        accent_color=GOLDENROD_ACCENT,
                        components=[
                            Text(content="## ✅ Code Confirmed!"),
                            Separator(divider=True),
                            Text(content=(
                                f"{event.author.mention} **Thank you for acknowledging!**\n\n"
                                f"We encourage and allow temporary movement within the family but if you desire a permanent move to another clan we need to discuss it further with Leadership. So from here forward, the Clan you are assigned to is your **\"Home Clan\"**. Always come back home...👍🏼\n\n"
                                f"The **{message_content}**; or any of the code combinations; will get you in to any clan within the Family.... remember that...💪🏼.\n\n"
                            )),
                            Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
                            Text(content=f"-# Confirmation triggered by {moderator_name}"),
                        ]
                    )
                ]

                await event.app.rest.create_message(
                    channel=event.channel_id,
                    components=success_components,
                    user_mentions=[event.author_id, listener_info["moderator_id"]]
                )

                # Remove from active listeners
                del active_listeners[message_id]
                break


# Clean up old listeners periodically
@loader.listener(hikari.StartingEvent)
@lightbulb.di.with_di
async def setup_cleanup_task(
        event: hikari.StartingEvent,
        mongo: MongoClient = lightbulb.di.INJECTED
):
    """Set up periodic cleanup of old listeners"""

    async def cleanup_old_listeners():
        while True:
            await asyncio.sleep(3600)  # Check every hour

            # Find and remove listeners older than 24 hours
            cutoff_time = datetime.now(timezone.utc).timestamp() - 86400

            for message_id in list(active_listeners.keys()):
                if message_id < hikari.Snowflake.from_datetime(
                        datetime.fromtimestamp(cutoff_time, timezone.utc)
                ):
                    del active_listeners[message_id]

    asyncio.create_task(cleanup_old_listeners())