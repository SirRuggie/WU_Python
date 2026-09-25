"""Best-effort reminder hooks; onboarding and ticket success must stay successful."""
import asyncio
import logging

_log = logging.getLogger(__name__)


async def track_progress(mongo, guild_id: int, user_id: int, stage: int) -> None:
    try:
        from utils.gauntlet_help import record_progress
        async with asyncio.timeout(5):
            await record_progress(mongo, int(guild_id), int(user_id), stage)
    except Exception:
        _log.exception("Could not record Gauntlet progress for guild %s user %s", guild_id, user_id)


async def ticket_opened(mongo, ticket: dict) -> None:
    if ticket.get("ticket_type") not in {"main", "fwa"} or int(ticket.get("guild_id") or 0) != 644963518025826315:
        return
    try:
        from utils.gauntlet_help import complete_progress
        async with asyncio.timeout(5):
            await complete_progress(mongo, int(ticket["guild_id"]), int(ticket["user_id"]))
    except Exception:
        _log.exception("Could not complete Gauntlet reminder for ticket %s", ticket.get("_id"))
