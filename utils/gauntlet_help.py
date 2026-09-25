"""Durable settings and progression for the recruit Gauntlet help channel."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pymongo.errors import DuplicateKeyError

DEFAULT_REMINDER_MINUTES = 30
MIN_REMINDER_MINUTES = 1
MAX_REMINDER_MINUTES = 10080
STAGES = (1, 2, 3, 4)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def settings_id(guild_id: int) -> str:
    return f"gauntlet_help:{int(guild_id)}"


def progress_id(guild_id: int, user_id: int) -> str:
    return f"gauntlet_help_progress:{int(guild_id)}:{int(user_id)}"


async def get_settings(mongo, guild_id: int) -> dict:
    row = await mongo.bot_config.find_one({"_id": settings_id(guild_id)}) or {}
    value = row.get("reminder_minutes", DEFAULT_REMINDER_MINUTES)
    try:
        minutes = int(value)
    except (TypeError, ValueError):
        minutes = DEFAULT_REMINDER_MINUTES
    if not MIN_REMINDER_MINUTES <= minutes <= MAX_REMINDER_MINUTES:
        minutes = DEFAULT_REMINDER_MINUTES
    return {"reminder_minutes": minutes, "enabled": row.get("enabled", True) is True}


async def save_settings(mongo, guild_id: int, minutes: int, actor_id: int) -> None:
    if isinstance(minutes, bool) or not isinstance(minutes, int) or not MIN_REMINDER_MINUTES <= minutes <= MAX_REMINDER_MINUTES:
        raise ValueError("reminder_minutes must be an integer from 1 to 10080")
    await mongo.bot_config.update_one(
        {"_id": settings_id(guild_id)},
        {"$set": {"reminder_minutes": minutes, "updated_by": int(actor_id), "updated_at": utcnow()},
         "$setOnInsert": {"enabled": True, "guild_id": int(guild_id)}},
        upsert=True,
    )
    # Existing waiting recruits follow the new delay measured from their latest
    # advancement, so the dashboard value takes effect immediately.
    await mongo.bot_config.update_many(
        {"kind": "gauntlet_help_progress", "guild_id": int(guild_id),
         "status": "waiting"},
        [{"$set": {"due_at": {"$dateAdd": {"startDate": "$advanced_at",
                                            "unit": "minute", "amount": minutes}}}}],
    )
    await mongo.bot_config.update_many(
        {"kind": "gauntlet_help_progress", "guild_id": int(guild_id), "status": "checking"},
        [{"$set": {"status": "waiting", "due_at": {"$dateAdd": {
            "startDate": "$advanced_at", "unit": "minute", "amount": minutes}}}},
         {"$unset": ["claim_token", "lease_until"]}],
    )


async def record_progress(mongo, guild_id: int, user_id: int, stage: int) -> None:
    """Advance exactly once per stage; late older callbacks never reset a timer."""
    if isinstance(stage, bool) or stage not in STAGES:
        raise ValueError("stage must be 1, 2, 3, or 4")
    settings = await get_settings(mongo, guild_id)
    now = utcnow()
    fields = {
        "stage": stage, "advanced_at": now,
        "due_at": now + timedelta(minutes=settings["reminder_minutes"]),
        "status": "waiting", "guild_id": int(guild_id), "user_id": int(user_id),
        "kind": "gauntlet_help_progress", "updated_at": now,
    }
    key = progress_id(guild_id, user_id)
    result = await mongo.bot_config.update_one(
        {"_id": key, "stage": {"$lt": stage}, "status": {"$ne": "complete"}},
        {"$set": fields, "$unset": {"claim_token": "", "lease_until": "", "message_id": "", "delete_at": ""}},
    )
    if result.matched_count:
        return
    try:
        await mongo.bot_config.insert_one({"_id": key, **fields})
    except DuplicateKeyError:
        pass


async def complete_progress(mongo, guild_id: int, user_id: int) -> None:
    """Ticket creation closes the final stage, even when its callback races a sweep."""
    now = utcnow()
    await mongo.bot_config.update_one(
        {"_id": progress_id(guild_id, user_id)},
        {"$set": {"status": "complete", "completed_at": now, "updated_at": now}},
    )
