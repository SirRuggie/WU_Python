"""Bounded, per-recruit Goblin challenges in settings.recruit_challenges."""

from datetime import datetime, timedelta, timezone
import logging
import uuid

from pymongo import ReturnDocument

_log = logging.getLogger(__name__)
KIND = "goblin_ping"
TTL = timedelta(hours=24)
LEASE = timedelta(minutes=2)


def utcnow():
    return datetime.now(timezone.utc)


def key(channel_id, user_id):
    return f"goblin_ping:{int(channel_id)}:{int(user_id)}"


def active_query(channel_id, user_id, now=None):
    return {
        "_id": key(channel_id, user_id),
        "type": KIND,
        "expires_at": {"$gt": now or utcnow()},
        "$or": [
            {"status": "pending"},
            {"status": "processing", "processing_until": {"$lte": now or utcnow()}},
        ],
    }


async def open_challenge(mongo, *, guild_id, channel_id, user_id, recruiter_id, source_message_id=None):
    now = utcnow()
    session = f"shield:{int(source_message_id)}" if source_message_id is not None else uuid.uuid4().hex
    if source_message_id is not None:
        current = await mongo.recruit_challenges.find_one({"_id": key(channel_id, user_id)})
        if current and current.get("session_id") == session:
            return session
        if current and current.get("source_message_id", 0) > int(source_message_id):
            raise ValueError("A newer Discord Basics prompt already exists")
    await mongo.recruit_challenges.update_one(
        {"_id": key(channel_id, user_id)},
        {
            "$set": {
                "type": KIND,
                "schema_version": 1,
                "session_id": session,
                "source_message_id": int(source_message_id) if source_message_id is not None else 0,
                "guild_id": int(guild_id),
                "channel_id": int(channel_id),
                "user_id": int(user_id),
                "recruiter_id": int(recruiter_id),
                "created_at": now,
                "expires_at": now + TTL,
                "status": "pending",
            },
            "$unset": {
                "claim_id": "",
                "processing_until": "",
                "completed_at": "",
                "success_message_id": "",
            },
        },
        upsert=True,
    )
    return session


async def claim(mongo, challenge):
    now = utcnow()
    claim_id = uuid.uuid4().hex
    row = await mongo.recruit_challenges.find_one_and_update(
        {
            **active_query(challenge["channel_id"], challenge["user_id"], now),
            "session_id": challenge["session_id"],
        },
        {
            "$set": {
                "status": "processing",
                "claim_id": claim_id,
                "processing_until": now + LEASE,
            }
        },
        return_document=ReturnDocument.BEFORE,
    )
    return claim_id if row else None


async def release(mongo, challenge, claim_id):
    await mongo.recruit_challenges.update_one(
        {
            "_id": challenge["_id"],
            "session_id": challenge["session_id"],
            "claim_id": claim_id,
        },
        {
            "$set": {"status": "pending"},
            "$unset": {"claim_id": "", "processing_until": ""},
        },
    )


async def complete(mongo, challenge, claim_id, message_id):
    await mongo.recruit_challenges.update_one(
        {
            "_id": challenge["_id"],
            "session_id": challenge["session_id"],
            "claim_id": claim_id,
        },
        {
            "$set": {
                "status": "completed",
                "completed_at": utcnow(),
                "success_message_id": int(message_id),
            },
            "$unset": {"claim_id": "", "processing_until": ""},
        },
    )


async def prepare_storage(mongo):
    # Share the existing family-code expiry index rather than create a duplicate.
    # Never remove legacy records if storage/index preparation fails.
    await mongo.recruit_challenges.create_index(
        "expires_at",
        expireAfterSeconds=0,
        name="family_code_expiry",
    )
    rows = []
    async for row in mongo.button_store.find({"challenge_type": KIND}):
        try:
            created = row["created_at"]
            if not isinstance(created, datetime) or row.get("status") != "pending":
                raise ValueError("invalid date/status")
            created = (
                created.replace(tzinfo=timezone.utc)
                if created.tzinfo is None
                else created.astimezone(timezone.utc)
            )
            for field in ("channel_id", "user_id", "recruiter_id"):
                if isinstance(row[field], bool) or int(row[field]) <= 0:
                    raise ValueError("invalid identifier")
            rows.append((created, row))
        except (KeyError, ValueError, TypeError):
            _log.warning(
                "Preserving malformed legacy Goblin challenge %s", row.get("_id")
            )
    # Most recent recruiter assignment wins when old delete/insert races left duplicates.
    rows.sort(key=lambda item: item[0], reverse=True)
    migrated = 0
    for created, row in rows:
        target = key(row["channel_id"], row["user_id"])
        document = {
            "type": KIND,
            "schema_version": 1,
            "session_id": f"legacy:{row['_id']}",
            "channel_id": int(row["channel_id"]),
            "user_id": int(row["user_id"]),
            "recruiter_id": int(row["recruiter_id"]),
            "status": "pending",
            "created_at": created,
            "expires_at": created + TTL,
        }
        if row.get("guild_id"):
            document["guild_id"] = int(row["guild_id"])
        # Existing new-system challenges always win. Retry is safe if the process
        # stops after the copy but before deleting the exact source document.
        await mongo.recruit_challenges.update_one(
            {"_id": target},
            {"$setOnInsert": document},
            upsert=True,
        )
        await mongo.button_store.delete_one(row)
        migrated += 1
    return migrated


async def claim_shield(mongo, *, message_id, channel_id, user_id, guild_id):
    """Keep a durable receipt per Shield message, independent of challenge TTL."""
    receipt_id = f"goblin_prompt:{int(message_id)}"
    now = utcnow()
    await mongo.recruit_challenges.update_one(
        {"_id": receipt_id},
        {
            "$setOnInsert": {
                "type": "goblin_prompt",
                "schema_version": 1,
                "guild_id": int(guild_id),
                "channel_id": int(channel_id),
                "user_id": int(user_id),
                "source_message_id": int(message_id),
                "created_at": now,
                "status": "ready",
            }
        },
        upsert=True,
    )
    token = uuid.uuid4().hex
    row = await mongo.recruit_challenges.find_one_and_update(
        {
            "_id": receipt_id,
            "type": "goblin_prompt",
            "guild_id": int(guild_id),
            "channel_id": int(channel_id),
            "user_id": int(user_id),
            "$or": [
                {"status": "ready"},
                {"status": "sending", "processing_until": {"$lte": now}},
            ],
        },
        {
            "$set": {
                "status": "sending",
                "claim_id": token,
                "processing_until": now + LEASE,
            }
        },
        return_document=ReturnDocument.BEFORE,
    )
    return (receipt_id, token) if row else None


async def release_shield(mongo, receipt):
    receipt_id, token = receipt
    await mongo.recruit_challenges.update_one(
        {"_id": receipt_id, "claim_id": token, "status": "sending"},
        {
            "$set": {"status": "ready"},
            "$unset": {"claim_id": "", "processing_until": ""},
        },
    )


async def complete_shield(mongo, receipt, prompt_id):
    receipt_id, token = receipt
    await mongo.recruit_challenges.update_one(
        {"_id": receipt_id, "claim_id": token, "status": "sending"},
        {
            "$set": {
                "status": "sent",
                "prompt_message_id": int(prompt_id),
                "sent_at": utcnow(),
            },
            "$unset": {"claim_id": "", "processing_until": ""},
        },
    )
