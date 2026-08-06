"""
Background task to automatically remove New Recruit role after 2 hours
"""

import lightbulb
import hikari
import asyncio
from datetime import datetime, timedelta, timezone
from utils.mongo import MongoClient
import time
from pymongo import ReturnDocument

loader = lightbulb.Loader()

# Configuration
NEW_RECRUIT_ROLE_ID = 779277305671319572
CHECK_INTERVAL_MINUTES = 30  # Check every 30 minutes (reduced from 5 to avoid rate limits)
ROLE_REMOVAL_HOURS = 2  # Remove role after 2 hours
MAX_BATCH_SIZE = 20  # Maximum number of roles to remove in one batch to avoid rate limits
LEASE_DURATION = timedelta(minutes=10)
RETRY_DELAYS = (
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
    timedelta(hours=12),
    timedelta(hours=24),
)
MAX_CLEANUP_FAILURES = 6
PERMANENT_DISCORD_ERRORS = (
    hikari.BadRequestError,
    hikari.UnauthorizedError,
    hikari.ForbiddenError,
    hikari.NotFoundError,
)

# Global variables
cleanup_task = None
bot_instance = None
mongo_client = None


def _error_detail(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]


def _retry_delay(failure_count: int) -> timedelta:
    index = min(max(failure_count - 1, 0), len(RETRY_DELAYS) - 1)
    return RETRY_DELAYS[index]


async def _record_cleanup_failure(collection, walkthrough, stage, exc, now):
    """Persist a bounded retry or terminal state for one claimed walkthrough."""
    try:
        failure_count = int(walkthrough.get("cleanup_attempts") or 0) + 1
    except (TypeError, ValueError):
        failure_count = 1
    permanent = isinstance(exc, PERMANENT_DISCORD_ERRORS)
    terminal_reason = None
    if permanent:
        terminal_reason = "permanent_discord_error"
    elif failure_count >= MAX_CLEANUP_FAILURES:
        terminal_reason = "failure_limit"

    fields = {
        "cleanup_attempts": failure_count,
        "cleanup_first_failed_at": (
            walkthrough.get("cleanup_first_failed_at") or now
        ),
        "cleanup_last_failed_at": now,
        "cleanup_last_error_type": type(exc).__name__,
        "cleanup_last_error_detail": _error_detail(exc),
    }
    if terminal_reason:
        fields.update({
            "cleanup_status": f"abandoned_{stage}",
            "cleanup_terminal": True,
            "cleanup_terminal_reason": terminal_reason,
            "cleanup_terminal_at": now,
        })
        update = {
            "$set": fields,
            "$unset": {
                "cleanup_lease_until": "",
                "cleanup_next_attempt_at": "",
            },
        }
    else:
        delay = _retry_delay(failure_count)
        fields.update({
            "cleanup_status": f"retry_{stage}",
            "cleanup_next_attempt_at": now + delay,
        })
        update = {
            "$set": fields,
            "$unset": {"cleanup_lease_until": ""},
        }

    await collection.update_one({"_id": walkthrough["_id"]}, update)
    if terminal_reason:
        print(f"[Recruit Role Cleanup] ALERT cleanup_abandoned "
              f"stage={stage} user={walkthrough.get('user_id')} "
              f"guild={walkthrough.get('guild_id')} failures={failure_count} "
              f"reason={terminal_reason} error={type(exc).__name__} "
              f"detail={_error_detail(exc)}")
    else:
        print(f"[Recruit Role Cleanup] cleanup_retry_scheduled "
              f"stage={stage} user={walkthrough.get('user_id')} "
              f"guild={walkthrough.get('guild_id')} failures={failure_count} "
              f"retry_at={fields['cleanup_next_attempt_at'].isoformat()} "
              f"error={type(exc).__name__} detail={_error_detail(exc)}")
    return terminal_reason is not None


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
        
        now = datetime.now(timezone.utc)
        # Failed rows are deferred before the next scan, so a poison row cannot
        # permanently occupy one of the first 20 slots and starve later recruits.
        query = {
            "walkthrough_started_at": {"$lt": cutoff_time},
            "new_recruit_role_removed": False,
            "cleanup_terminal": {"$ne": True},
            "$and": [
                {"$or": [
                    {"cleanup_next_attempt_at": {"$exists": False}},
                    {"cleanup_next_attempt_at": {"$lte": now}},
                ]},
                {"$or": [
                    {"cleanup_lease_until": {"$exists": False}},
                    {"cleanup_lease_until": {"$lte": now}},
                ]},
            ],
        }
        cursor = mongo_client.recruit_onboarding.find(query).sort(
            "walkthrough_started_at", 1
        ).limit(MAX_BATCH_SIZE)
        expired_walkthroughs = await cursor.to_list(length=MAX_BATCH_SIZE)
        
        print(f"[Recruit Role Cleanup] Found {len(expired_walkthroughs)} expired walkthroughs")
        
        if len(expired_walkthroughs) == 0:
            print(f"[Recruit Role Cleanup] No expired walkthroughs to process. Check completed in {time.time() - start_time:.2f}s")
            return
        
        processed = 0
        api_calls = 0
        
        for i, walkthrough in enumerate(expired_walkthroughs):
            user_id = walkthrough.get("user_id")
            guild_id = walkthrough.get("guild_id")
            
            if not user_id or not guild_id:
                await mongo_client.recruit_onboarding.update_one(
                    {"_id": walkthrough["_id"]},
                    {"$set": {
                        "new_recruit_role_removed": True,
                        "cleanup_status": "invalid_record",
                        "cleanup_completed_at": now,
                    }},
                )
                processed += 1
                continue

            claimed = await mongo_client.recruit_onboarding.find_one_and_update(
                {
                    "_id": walkthrough["_id"],
                    "new_recruit_role_removed": False,
                    "cleanup_terminal": {"$ne": True},
                    "$and": [
                        {"$or": [
                            {"cleanup_next_attempt_at": {"$exists": False}},
                            {"cleanup_next_attempt_at": {"$lte": now}},
                        ]},
                        {"$or": [
                            {"cleanup_lease_until": {"$exists": False}},
                            {"cleanup_lease_until": {"$lte": now}},
                        ]},
                    ],
                },
                {"$set": {"cleanup_lease_until": now + LEASE_DURATION}},
                return_document=ReturnDocument.AFTER,
            )
            if not claimed:
                continue
            
            # Add delay between processing to avoid rate limits
            if i > 0 and i % 5 == 0:
                print(f"[Recruit Role Cleanup] Processed {i}/{len(expired_walkthroughs)}, adding 2s delay to avoid rate limits")
                await asyncio.sleep(2)
            
            # Get guild and member
            guild = bot_instance.cache.get_guild(guild_id)
            member = guild.get_member(user_id) if guild else None
            if not member:
                try:
                    api_calls += 1
                    member = await bot_instance.rest.fetch_member(guild_id, user_id)
                except hikari.NotFoundError:
                    await mongo_client.recruit_onboarding.update_one(
                        {"_id": walkthrough["_id"]},
                        {"$set": {
                            "new_recruit_role_removed": True,
                            "cleanup_status": "member_left_guild",
                            "cleanup_completed_at": now,
                        }, "$unset": {"cleanup_lease_until": ""}},
                    )
                    processed += 1
                    continue
                except Exception as e:
                    await _record_cleanup_failure(
                        mongo_client.recruit_onboarding,
                        claimed,
                        "member_fetch",
                        e,
                        now,
                    )
                    continue
            
            # Check if member has the New Recruit role
            if NEW_RECRUIT_ROLE_ID in member.role_ids:
                try:
                    # Add a small delay before role removal to avoid rate limits
                    await asyncio.sleep(0.5)
                    
                    # Remove the role
                    api_calls += 1  # Role removal is an API call
                    await bot_instance.rest.remove_role_from_member(
                        guild_id,
                        user_id,
                        NEW_RECRUIT_ROLE_ID,
                        reason="Auto-removal after 2 hours from walkthrough start",
                    )
                    print(f"[Recruit Role Cleanup] Removed New Recruit role from {member.display_name} ({user_id})")
                    
                    # Log the removal in a channel if desired (optional)
                    # You can add notification logic here if needed
                    
                except Exception as e:
                    await _record_cleanup_failure(
                        mongo_client.recruit_onboarding,
                        claimed,
                        "role_removal",
                        e,
                        now,
                    )
                    continue
            
            # Mark as processed in database
            await mongo_client.recruit_onboarding.update_one(
                {"_id": walkthrough["_id"]},
                {
                    "$set": {
                        "new_recruit_role_removed": True,
                        "cleanup_status": "complete",
                        "cleanup_completed_at": now,
                    },
                    "$unset": {
                        "cleanup_lease_until": "",
                        "cleanup_next_attempt_at": "",
                    },
                }
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
    
    try:
        await mongo.recruit_onboarding.create_index(
            [
                ("new_recruit_role_removed", 1),
                ("cleanup_terminal", 1),
                ("cleanup_next_attempt_at", 1),
                ("walkthrough_started_at", 1),
            ],
            name="recruit_role_cleanup_due",
        )
    except Exception as e:
        print(f"[Recruit Role Cleanup] WARNING: due-work index unavailable: {e}")

    # Start the cleanup task automatically, once.
    if cleanup_task and not cleanup_task.done():
        print("[Recruit Role Cleanup] Task already running; start skipped")
        return
    cleanup_task = asyncio.create_task(
        cleanup_loop(), name="recruit-role-cleanup"
    )
    print("[Recruit Role Cleanup] Task started")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    """Stop the cleanup task when the bot stops"""
    global cleanup_task
    
    if cleanup_task and not cleanup_task.done():
        cleanup_task.cancel()
        try:
            await cleanup_task
        except asyncio.CancelledError:
            pass
        print("[Recruit Role Cleanup] Task stopped")
