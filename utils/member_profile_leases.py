"""Short-lived shared component-state leases; profile data stays in its owner."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4
import asyncio
from pymongo.errors import DuplicateKeyError
from utils.component_state import insert_state, update_state, get_state

DEFAULT_LEASE_SECONDS = 60


class ProfileBusy(ValueError):
    pass


@asynccontextmanager
async def editing(mongo, discord_id, *, lease_seconds=DEFAULT_LEASE_SECONDS):
    if type(lease_seconds) is not int or not 60 <= lease_seconds <= 200:
        raise ValueError("Invalid member edit lease duration.")
    lease = timedelta(seconds=lease_seconds)
    retention = lease + timedelta(seconds=60)
    key = "member_profile_edit:" + str(discord_id)
    owner = uuid4().hex
    now = datetime.now(timezone.utc)
    claim = {
        "_id": key,
        "type": "member_profile_edit",
        "owner": owner,
        "lease_until": now + lease,
    }
    try:
        await insert_state(mongo, claim, ttl=retention)
    except DuplicateKeyError:
        result = await update_state(
            mongo,
            {
                "_id": key,
                "type": "member_profile_edit",
                "lease_until": {"$lte": now},
            },
            {
                "$set": {
                    "owner": owner,
                    "lease_until": now + lease,
                    "expires_at": now + retention,
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
