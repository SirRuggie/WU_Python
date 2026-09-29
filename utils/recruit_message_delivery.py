"""Durable delivery receipts for recruitment challenge messages.

See docs/recruit-message-delivery.md. No message bodies or tokens are stored.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import uuid

import hikari
from pymongo import ReturnDocument

_log = logging.getLogger(__name__)
SHORT_RETRY = timedelta(seconds=60)
LEASE = timedelta(minutes=2)
RETENTION = timedelta(days=30)
HISTORY_LIMIT = 500


class DeliveryUncertain(RuntimeError):
    """Delivery needs reconciliation; callers must not send a replacement."""


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def collection(mongo):
    return mongo.recruit_challenges.database.get_collection(
        "recruit_message_deliveries"
    )


def identity(kind, channel_id, user_id, session_id):
    key = f"{kind}:{int(channel_id)}:{int(user_id)}:{session_id}"
    # Discord limits nonce strings to 25 characters; the full readable ID is
    # retained as Mongo's natural key and included in diagnostic logs.
    return key, hashlib.sha256(key.encode()).hexdigest()[:24]


async def prepare(mongo):
    receipts = collection(mongo)
    await receipts.create_index(
        "expires_at", expireAfterSeconds=0, name="recruit_delivery_retention"
    )
    await receipts.create_index(
        [("status", 1), ("updated_at", -1)], name="recruit_delivery_status"
    )
    await receipts.create_index(
        [("user_id", 1), ("channel_id", 1), ("created_at", -1)],
        name="recruit_delivery_lookup",
    )


async def record_sent(receipts, row, message_id, *, recovered=False):
    result = await receipts.update_one(
        {"_id": row["_id"], "claim_id": row["claim_id"]},
        {
            "$set": {
                "status": "sent",
                "discord_message_id": int(message_id),
                "updated_at": utcnow(),
                "recovered_from_history": recovered,
            },
            "$unset": {"claim_id": "", "lease_until": "", "last_error": ""},
        },
    )
    if not result.matched_count:
        raise DeliveryUncertain(
            f"Delivery claim changed before checkpoint: {row['_id']}"
        )
    _log.info(
        "recruit_delivery_sent delivery_id=%s message_id=%s recovered=%s",
        row["_id"],
        message_id,
        recovered,
    )
    return SimpleNamespace(id=int(message_id))


async def reconcile(rest, row):
    """Only exact nonces from this bot are evidence of prior delivery."""
    me = await rest.fetch_my_user()
    after = hikari.Snowflake.from_datetime(
        aware(row["first_attempt_at"]) - timedelta(seconds=1)
    )
    async for message in rest.fetch_messages(row["channel_id"], after=after).limit(
        HISTORY_LIMIT
    ):
        if (
            int(message.author.id) == int(me.id)
            and str(getattr(message, "nonce", None)) == row["discord_nonce"]
        ):
            return message.id
    # Missing nonce, deleted message, long history, or no match are all ambiguous.
    return None


async def deliver(
    mongo,
    rest,
    *,
    kind,
    session_id,
    guild_id,
    channel_id,
    user_id,
    components,
    user_mentions,
    role_mentions=False,
):
    if kind not in {"goblin_prompt", "goblin_confirmation", "family_code_confirmation"}:
        raise ValueError("Unsupported recruitment delivery type")
    now = utcnow()
    delivery_id, nonce = identity(kind, channel_id, user_id, session_id)
    receipts = collection(mongo)
    await receipts.update_one(
        {"_id": delivery_id},
        {
            "$setOnInsert": {
                "schema_version": 1,
                "kind": kind,
                "session_id": str(session_id),
                "guild_id": int(guild_id) if guild_id is not None else None,
                "channel_id": int(channel_id),
                "user_id": int(user_id),
                "discord_nonce": nonce,
                "status": "prepared",
                "attempts": 0,
                "created_at": now,
                "updated_at": now,
                "expires_at": now + RETENTION,
            }
        },
        upsert=True,
    )
    row = await receipts.find_one({"_id": delivery_id})
    if row["status"] == "sent":
        return SimpleNamespace(id=int(row["discord_message_id"]))
    token = uuid.uuid4().hex
    claimed = await receipts.find_one_and_update(
        {
            "_id": delivery_id,
            "status": {"$in": ["prepared", "sending", "retryable", "needs_review"]},
            "$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
            ],
        },
        {
            "$set": {
                "status": "sending",
                "claim_id": token,
                "lease_until": now + LEASE,
                "updated_at": now,
            }
        },
        return_document=ReturnDocument.BEFORE,
    )
    if claimed is None:
        raise DeliveryUncertain(
            f"Recruitment delivery is already processing: {delivery_id}"
        )
    row = {**claimed, "claim_id": token}
    # The short window is anchored to the FIRST send, never extended by retries.
    if (
        row.get("first_attempt_at")
        and now - aware(row["first_attempt_at"]) > SHORT_RETRY
    ):
        try:
            found = await reconcile(rest, row)
        except Exception as exc:
            found = None
            _log.warning(
                "recruit_delivery_reconcile_failed delivery_id=%s error=%s",
                delivery_id,
                type(exc).__name__,
            )
        if found is not None:
            return await record_sent(receipts, row, found, recovered=True)
        await receipts.update_one(
            {"_id": delivery_id, "claim_id": token},
            {
                "$set": {
                    "status": "needs_review",
                    "updated_at": utcnow(),
                    "last_error": "prior_delivery_unconfirmed",
                },
                "$unset": {"claim_id": "", "lease_until": ""},
            },
        )
        _log.warning(
            "recruit_delivery_needs_review delivery_id=%s channel=%s user=%s",
            delivery_id,
            channel_id,
            user_id,
        )
        raise DeliveryUncertain(f"Prior delivery could not be confirmed: {delivery_id}")
    fields = {"updated_at": now, "last_attempt_at": now}
    if not row.get("first_attempt_at"):
        fields["first_attempt_at"] = now
    await receipts.update_one(
        {"_id": delivery_id, "claim_id": token},
        {"$set": fields, "$inc": {"attempts": 1}},
    )
    try:
        message = await rest.create_message(
            channel=channel_id,
            components=components,
            user_mentions=user_mentions,
            role_mentions=role_mentions,
            mentions_everyone=False,
            nonce=nonce,
        )
    except (Exception, asyncio.CancelledError) as exc:
        # Hikari emits enforce_nonce=True for a non-empty nonce. Ambiguous
        # failures retain first_attempt_at so a long retry must reconcile.
        update = {
            "$set": {
                "status": "retryable",
                "updated_at": utcnow(),
                "last_error": type(exc).__name__,
            },
            "$unset": {"claim_id": "", "lease_until": ""},
        }
        if isinstance(
            exc,
            (
                hikari.BadRequestError,
                hikari.ForbiddenError,
                hikari.UnauthorizedError,
                hikari.NotFoundError,
            ),
        ) and not row.get("first_attempt_at"):
            update["$unset"]["first_attempt_at"] = ""  # Known rejected initial request.
        await receipts.update_one({"_id": delivery_id, "claim_id": token}, update)
        raise
    return await record_sent(receipts, row, message.id)
