"""Daily complete-directory retention repair after missed/offline member events."""

import asyncio
import logging
from datetime import datetime, timezone
from utils.constants import WARRIORS_UNITED_GUILD_ID
from utils.member_profiles import MemberProfiles

log = logging.getLogger(__name__)
_task = None


async def reconcile(bot, mongo):
    observed = datetime.now(timezone.utc)
    store = MemberProfiles(mongo)
    profiles = await store.membership_rows()
    if not profiles:
        return {"profiles": 0, "present": 0, "absent": 0}
    members = set()
    # No absence write happens until the entire upstream directory has completed.
    async with asyncio.timeout(60):
        async for member in bot.rest.fetch_members(WARRIORS_UNITED_GUILD_ID):
            members.add(str(member.id))
            if len(members) > 10000:
                raise ValueError(
                    "Member directory limit exceeded; no absence marks applied."
                )
    if str(bot.get_me().id) not in members:
        raise ValueError(
            "Member directory did not include the bot; no absence marks applied."
        )
    present = 0
    for row in profiles:
        is_present = row["_id"] in members
        present += is_present
        # Preserve the first confirmed departure; do not slide its90day lifetime.
        left = None if is_present else row.get("left_at") or observed
        await store.membership(row["_id"], left_at=left, observed_at=observed)
    return {
        "profiles": len(profiles),
        "present": present,
        "absent": len(profiles) - present,
    }


async def loop(bot, mongo):
    while True:
        try:
            result = await reconcile(bot, mongo)
            log.info(
                "Member profile retention scan complete profiles=%s present=%s absent=%s",
                result["profiles"],
                result["present"],
                result["absent"],
            )
            delay = 86400
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning(
                "Member profile retention scan unavailable (%s); no incomplete directory used",
                type(error).__name__,
            )
            delay = 3600
        await asyncio.sleep(delay)


def start(bot, mongo):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(loop(bot, mongo), name="member-profile-retention")


async def stop():
    global _task
    if _task is not None:
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        _task = None
