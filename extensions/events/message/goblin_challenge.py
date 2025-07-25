# extensions/events/message/goblin_challenge.py
"""
Handles the goblin ping challenge for recruit questions.
Monitors for users to say "goblin" and ping their recruiter.
"""

import hikari
import lightbulb
from typing import Optional
from datetime import datetime, timezone

from utils.mongo import MongoClient
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from utils.constants import GREEN_ACCENT

# Global instances
mongo_client: Optional[MongoClient] = None
bot_instance: Optional[hikari.GatewayBot] = None


def initialize(mongo: MongoClient, bot: hikari.GatewayBot):
    """Initialize the handler"""
    global mongo_client, bot_instance
    mongo_client = mongo
    bot_instance = bot
    print("[GoblinChallenge] Handler initialized")


async def check_goblin_challenge(event: hikari.GuildMessageCreateEvent) -> bool:
    """
    Check if a message completes a goblin challenge.
    Returns True if the message was handled by this system.
    """
    if not mongo_client:
        return False
    
    # Skip bot messages
    if event.is_bot:
        return False
    
    # Check if there's an active goblin challenge in this channel FIRST
    challenge = await mongo_client.button_store.find_one({
        "channel_id": event.channel_id,
        "challenge_type": "goblin_ping",
        "status": "pending"
    })
    
    if not challenge:
        # No active challenge in this channel, silently return
        return False
    
    # Only log if we found a relevant challenge
    print(f"[GoblinChallenge] Found active challenge ID {challenge.get('_id')} in channel {event.channel_id} for user {challenge.get('user_id')}")
    
    # Check if it's the right user
    if event.author_id != challenge.get("user_id"):
        return False
    
    # Check message content (case-insensitive)
    content_lower = event.content.lower()
    has_goblin = "goblin" in content_lower
    
    # Check if recruiter is mentioned
    recruiter_id = challenge.get("recruiter_id")
    has_recruiter_ping = recruiter_id in event.message.user_mentions_ids
    
    print(f"[GoblinChallenge] Checking message: has_goblin={has_goblin}, has_recruiter_ping={has_recruiter_ping}")
    
    if has_goblin and has_recruiter_ping:
        # Success! Delete the challenge to prevent further checks
        await mongo_client.button_store.delete_one({"_id": challenge["_id"]})
        print(f"[GoblinChallenge] Challenge ID {challenge.get('_id')} completed and deleted for user {event.author_id}")
        
        # Send success message
        await send_success_message(event.channel_id, event.author_id, recruiter_id)
        
        # Add reaction to the user's message
        try:
            await event.message.add_reaction("✅")
        except:
            pass
        
        return True
    
    elif has_goblin and not has_recruiter_ping:
        # They said goblin but didn't ping the recruiter
        try:
            await event.message.add_reaction("❓")
            await event.message.respond(
                f"<@{event.author_id}> Nice try! You said 'goblin' but you forgot to ping your recruiter <@{recruiter_id}>. Try again!",
                mentions_everyone=False,
                user_mentions=[event.author_id]
            )
        except:
            pass
        return True
    
    elif has_recruiter_ping and not has_goblin:
        # They pinged but didn't say goblin
        try:
            await event.message.add_reaction("❓")
            await event.message.respond(
                f"<@{event.author_id}> You pinged your recruiter, but you forgot to say the magic word! (Hint: it rhymes with 'boblin')",
                mentions_everyone=False,
                user_mentions=[event.author_id]
            )
        except:
            pass
        return True
    
    return False


async def send_success_message(channel_id: int, user_id: int, recruiter_id: int):
    """Send a success message when the goblin challenge is completed"""
    if not bot_instance:
        return
    
    try:
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content=f"## 🎉 **Excellent Work!** · <@{user_id}>"),
                    Separator(divider=True),
                    Text(
                        content=(
                            "You've successfully:\n"
                            "✅ Said the magic word 'Goblin'\n"
                            f"✅ Pinged your recruiter <@{recruiter_id}>\n\n"
                            "**You've now proven all three Discord communication skills!**\n"
                            "1️⃣ Sending messages ✓\n"
                            "2️⃣ Pinging users ✓\n"
                            "3️⃣ Reacting to messages ✓\n\n"
                            "Awesome!!\n" 
                            "You're officially 100% smarter than the average Discord user! 🧠✨\n\n"
                            "You'll be utilizing those three methods of discord communication very frequently while in the WU Server. "
                            "Be it a member or a Role, a ping; and/or a reaction to a message; can be worth a thousand words. "
                            "In some cases, it's the best way to get one's attention and all Leadership are cool with it...👍🏻\n\n"
                            "**Make sense?**"
                        )
                    ),
                    Media(
                        items=[
                            MediaItem(media="assets/Green_Footer.png")  # Use a valid image asset
                        ]
                    ),
                    Text(content=f"-# Challenge completed! Great job on mastering Discord basics."),
                ]
            )
        ]
        
        channel = await bot_instance.rest.fetch_channel(channel_id)
        await channel.send(
            components=components,
            user_mentions=[user_id, recruiter_id]
        )
        
    except Exception as e:
        print(f"[GoblinChallenge] Error sending success message: {e}")


async def cleanup_old_challenges():
    """Clean up challenges older than 24 hours"""
    if not mongo_client:
        return
    
    try:
        from datetime import timedelta
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        
        result = await mongo_client.button_store.delete_many({
            "challenge_type": "goblin_ping",
            "created_at": {"$lt": cutoff_time}
        })
        
        if result.deleted_count > 0:
            print(f"[GoblinChallenge] Cleaned up {result.deleted_count} old challenges")
            
    except Exception as e:
        print(f"[GoblinChallenge] Error cleaning up old challenges: {e}")