"""
Background task to automatically remove New Recruit role after 2 hours
"""

import lightbulb
import hikari
import asyncio
from datetime import datetime, timedelta, timezone
from utils.mongo import MongoClient
import time

loader = lightbulb.Loader()

# Configuration
NEW_RECRUIT_ROLE_ID = 779277305671319572
CHECK_INTERVAL_MINUTES = 30  # Check every 30 minutes (reduced from 5 to avoid rate limits)
ROLE_REMOVAL_HOURS = 2  # Remove role after 2 hours
MAX_BATCH_SIZE = 20  # Maximum number of roles to remove in one batch to avoid rate limits

# Global variables
cleanup_task = None
bot_instance = None
mongo_client = None


async def remove_expired_recruit_roles():
    """Check for expired new recruit roles and remove them"""
    if not bot_instance or not mongo_client:
        print("[Recruit Role Cleanup] Bot or MongoDB not initialized")
        return
    
    start_time = time.time()
    print(f"[Recruit Role Cleanup] Starting cleanup check at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    
    try:
        # Calculate the cutoff time (2 hours ago)
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=ROLE_REMOVAL_HOURS)
        
        # Find all walkthroughs that started more than 2 hours ago and haven't had role removed
        expired_walkthroughs = await mongo_client.recruit_onboarding.find({
            "walkthrough_started_at": {"$lt": cutoff_time},
            "new_recruit_role_removed": False
        }).to_list(length=None)
        
        print(f"[Recruit Role Cleanup] Found {len(expired_walkthroughs)} expired walkthroughs")
        
        if len(expired_walkthroughs) == 0:
            print(f"[Recruit Role Cleanup] No expired walkthroughs to process. Check completed in {time.time() - start_time:.2f}s")
            return
        
        # Limit batch size to avoid rate limits
        if len(expired_walkthroughs) > MAX_BATCH_SIZE:
            print(f"[Recruit Role Cleanup] Limiting batch to {MAX_BATCH_SIZE} walkthroughs (from {len(expired_walkthroughs)})")
            expired_walkthroughs = expired_walkthroughs[:MAX_BATCH_SIZE]
        
        processed = 0
        api_calls = 0
        
        for i, walkthrough in enumerate(expired_walkthroughs):
            user_id = walkthrough.get("user_id")
            guild_id = walkthrough.get("guild_id")
            
            if not user_id or not guild_id:
                continue
            
            # Add delay between processing to avoid rate limits
            if i > 0 and i % 5 == 0:
                print(f"[Recruit Role Cleanup] Processed {i}/{len(expired_walkthroughs)}, adding 2s delay to avoid rate limits")
                await asyncio.sleep(2)
            
            # Get guild and member
            guild = bot_instance.cache.get_guild(guild_id)
            if not guild:
                print(f"[Recruit Role Cleanup] Guild {guild_id} not found in cache")
                continue
            
            api_calls += 1  # Getting member is an API call
            member = guild.get_member(user_id)
            if not member:
                print(f"[Recruit Role Cleanup] Member {user_id} not found in guild {guild_id}")
                # Still mark as processed to avoid repeated checks
                await mongo_client.recruit_onboarding.update_one(
                    {"_id": walkthrough["_id"]},
                    {"$set": {"new_recruit_role_removed": True}}
                )
                processed += 1
                continue
            
            # Check if member has the New Recruit role
            if NEW_RECRUIT_ROLE_ID in member.role_ids:
                try:
                    # Add a small delay before role removal to avoid rate limits
                    await asyncio.sleep(0.5)
                    
                    # Remove the role
                    api_calls += 1  # Role removal is an API call
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
            processed += 1
        
        # Print summary
        elapsed = time.time() - start_time
        print(f"[Recruit Role Cleanup] Cleanup completed: processed {processed}/{len(expired_walkthroughs)} walkthroughs, "
              f"made {api_calls} API calls in {elapsed:.2f}s")
            
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