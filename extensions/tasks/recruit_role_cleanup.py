"""
Background task to automatically remove New Recruit role after 2 hours
"""

import lightbulb
import hikari
import asyncio
from datetime import datetime, timedelta, timezone
from utils.mongo import MongoClient

loader = lightbulb.Loader()

# Configuration
NEW_RECRUIT_ROLE_ID = 779277305671319572
CHECK_INTERVAL_MINUTES = 5  # Check every 5 minutes
ROLE_REMOVAL_HOURS = 2  # Remove role after 2 hours

# Global variables
cleanup_task = None
bot_instance = None
mongo_client = None


async def remove_expired_recruit_roles():
    """Check for expired new recruit roles and remove them"""
    if not bot_instance or not mongo_client:
        print("[Recruit Role Cleanup] Bot or MongoDB not initialized")
        return
    
    try:
        # Calculate the cutoff time (2 hours ago)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=ROLE_REMOVAL_HOURS)
        
        # Find all walkthroughs that started more than 2 hours ago and haven't had role removed
        expired_walkthroughs = await mongo_client.recruit_onboarding.find({
            "walkthrough_started_at": {"$lt": cutoff_time},
            "new_recruit_role_removed": False
        }).to_list(length=None)
        
        print(f"[Recruit Role Cleanup] Found {len(expired_walkthroughs)} expired walkthroughs")
        
        for walkthrough in expired_walkthroughs:
            user_id = walkthrough.get("user_id")
            guild_id = walkthrough.get("guild_id")
            
            if not user_id or not guild_id:
                continue
            
            # Get guild and member
            guild = bot_instance.cache.get_guild(guild_id)
            if not guild:
                print(f"[Recruit Role Cleanup] Guild {guild_id} not found in cache")
                continue
            
            member = guild.get_member(user_id)
            if not member:
                print(f"[Recruit Role Cleanup] Member {user_id} not found in guild {guild_id}")
                # Still mark as processed to avoid repeated checks
                await mongo_client.recruit_onboarding.update_one(
                    {"_id": walkthrough["_id"]},
                    {"$set": {"new_recruit_role_removed": True}}
                )
                continue
            
            # Check if member has the New Recruit role
            if NEW_RECRUIT_ROLE_ID in member.role_ids:
                try:
                    # Remove the role
                    await member.remove_role(NEW_RECRUIT_ROLE_ID, reason="Auto-removal after 2 hours from walkthrough start")
                    print(f"[Recruit Role Cleanup] Removed New Recruit role from {member.display_name} ({user_id})")
                    
                    # Log the removal in a channel if desired (optional)
                    # You can add notification logic here if needed
                    
                except Exception as e:
                    print(f"[Recruit Role Cleanup] Failed to remove role from {user_id}: {e}")
                    continue
            
            # Mark as processed in database
            await mongo_client.recruit_onboarding.update_one(
                {"_id": walkthrough["_id"]},
                {"$set": {"new_recruit_role_removed": True}}
            )
            
    except Exception as e:
        print(f"[Recruit Role Cleanup] Error during cleanup: {e}")


async def cleanup_loop():
    """Main loop for the cleanup task"""
    while True:
        try:
            await remove_expired_recruit_roles()
        except Exception as e:
            print(f"[Recruit Role Cleanup] Loop error: {e}")
        
        # Wait for the next check
        await asyncio.sleep(CHECK_INTERVAL_MINUTES * 60)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED
) -> None:
    """Initialize the cleanup task when the bot starts"""
    global bot_instance, mongo_client, cleanup_task
    
    bot_instance = bot
    mongo_client = mongo
    
    # Start the cleanup task automatically
    cleanup_task = asyncio.create_task(cleanup_loop())
    print("[Recruit Role Cleanup] Task started")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    """Stop the cleanup task when the bot stops"""
    global cleanup_task
    
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        print("[Recruit Role Cleanup] Task stopped")