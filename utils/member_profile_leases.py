"""Short-lived shared component-state leases; profile data stays in its owner."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import asyncio
from pymongo.errors import DuplicateKeyError
from utils.component_state import insert_state, update_state, get_state

LEASE = timedelta(seconds=60)


class ProfileBusy(ValueError):
    pass


@asynccontextmanager
async def editing(mongo, discord_id):
    key = "member_profile_edit:" + str(discord_id)
    owner = uuid4().hex
    now = datetime.now(timezone.utc)
    claim = {
        "_id": key,
        "type": "member_profile_edit",
        "owner": owner,
        "lease_until": now + LEASE,
    }
    try:
        await insert_state(mongo, claim, ttl=timedelta(minutes=2))
    except DuplicateKeyError:
        result = await update_state(
            mongo,
            {"_id": key, "type": "member_profile_edit", "lease_until": {"$lte": now}},
            {
                "$set": {
                    "owner": owner,
                    "lease_until": now + LEASE,
                    "expires_at": now + timedelta(minutes=2),
                }
            },
        )
        if not result.matched_count:
            raise ProfileBusy(
                "This member is being edited. Wait a moment, then refresh."
            )
    try:
        yield claim
    finally:
        # Cancellation must not strand the lease; no Discord call is retried.
        task = asyncio.create_task(
            update_state(
                mongo,
                {"_id": key, "owner": owner},
                {"$set": {"lease_until": datetime.now(timezone.utc)}},
            )
        )
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await task
            raise


async def verify(mongo, claim):
    row = await get_state(mongo, claim["_id"])
    until = (row or {}).get("lease_until")
    if until is not None and until.tzinfo is None:
        until = until.replace(tzinfo=timezone.utc)
    if (
        not row
        or row.get("owner") != claim["owner"]
        or until is None
        or until <= datetime.now(timezone.utc)
    ):
        raise ProfileBusy("Member edit expired. Refresh before saving.")
