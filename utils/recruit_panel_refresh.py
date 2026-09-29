"""Durable ten-minute refresh jobs for private Recruit Questions panels.

Interaction tokens are short-lived credentials: never log rows or exception URLs.
They are removed on completion/failure/expiry. All jobs have a one-day TTL.
"""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import uuid

import hikari
from pymongo import ReturnDocument

_log = logging.getLogger(__name__)
DELAY_SECONDS = 600
TOKEN_LIFETIME = timedelta(minutes=15)
LEASE = timedelta(minutes=2)
_worker = None


def utcnow():
    return datetime.now(timezone.utc)


def aware(value):
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


def collection(mongo):
    # Follow the configured component-state database without mixing job data
    # with panel sessions, challenges, or legacy button_store records.
    return mongo.component_state.database.get_collection("recruit_panel_refreshes")


async def prepare(mongo):
    jobs = collection(mongo)
    await jobs.create_index(
        "expires_at", expireAfterSeconds=0, name="recruit_panel_refresh_expiry"
    )
    await jobs.create_index(
        [("status", 1), ("next_at", 1)], name="recruit_panel_refresh_due"
    )


async def schedule(mongo, ctx, user_id):
    interaction = ctx.interaction
    created = aware(interaction.created_at)
    now = utcnow()
    row = {
        "schema_version": 1,
        "source_message_id": int(interaction.message.id),
        "application_id": int(interaction.application_id),
        "interaction_token": interaction.token,
        "guild_id": int(ctx.guild_id),
        "channel_id": int(ctx.channel_id),
        "recruiter_id": int(ctx.user.id),
        "user_id": int(user_id),
        "action_id": interaction.custom_id.split(":", 1)[1],
        "created_at": created,
        "due_at": created + timedelta(seconds=DELAY_SECONDS),
        "next_at": created + timedelta(seconds=DELAY_SECONDS),
        "token_expires_at": created + TOKEN_LIFETIME - timedelta(seconds=5),
        "expires_at": now + timedelta(days=1),
        "status": "pending",
    }
    jobs = collection(mongo)
    key = str(interaction.message.id)
    await jobs.update_one({"_id": key}, {"$setOnInsert": row}, upsert=True)
    # A later pick does not slide a live countdown. A failed/expired refresh can
    # be scheduled again using that new pick's fresh interaction credential.
    await jobs.update_one(
        {
            "_id": key,
            "$or": [
                {"status": {"$in": ["failed", "expired"]}},
                {"status": "pending", "token_expires_at": {"$lte": now}},
            ],
        },
        {
            "$set": row,
            "$unset": {
                "claim_id": "",
                "lease_until": "",
                "replacement_id": "",
                "failure": "",
            },
        },
    )


async def finish(jobs, job, status, failure=None):
    fields = {"status": status, "finished_at": utcnow()}
    if failure:
        fields["failure"] = failure
    await jobs.update_one(
        {"_id": job["_id"], "claim_id": job["claim_id"]},
        {
            "$set": fields,
            "$unset": {"interaction_token": "", "claim_id": "", "lease_until": ""},
        },
    )


async def cleanup(jobs, rest, job):
    # A known replacement must still exist before removing the source panel.
    try:
        await rest.fetch_webhook_message(
            job["application_id"], job["interaction_token"], job["replacement_id"]
        )
    except hikari.NotFoundError:
        await finish(jobs, job, "failed", "replacement_missing")
        return
    try:
        await rest.delete_interaction_response(
            job["application_id"], job["interaction_token"]
        )
    except hikari.NotFoundError:
        pass  # Source is already gone; the replacement remains usable.
    await finish(jobs, job, "done")


async def process(jobs, rest, job, render):
    if job["status"] == "cleanup":
        await cleanup(jobs, rest, job)
        return
    source = await rest.fetch_interaction_response(
        job["application_id"], job["interaction_token"]
    )
    if int(source.id) != job["source_message_id"]:
        await finish(jobs, job, "failed", "source_mismatch")
        return
    components = await render(action_id=job["action_id"], user_id=job["user_id"])
    replacement = await rest.execute_webhook(
        job["application_id"],
        job["interaction_token"],
        components=components,
        flags=hikari.MessageFlag.EPHEMERAL | hikari.MessageFlag.IS_COMPONENTS_V2,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )
    # Checkpoint BEFORE deletion. A retry/restart in cleanup never sends again.
    saved = await jobs.update_one(
        {"_id": job["_id"], "claim_id": job["claim_id"]},
        {"$set": {"status": "cleanup", "replacement_id": int(replacement.id)}},
    )
    if not saved.matched_count:
        return
    job.update(status="cleanup", replacement_id=int(replacement.id))
    await cleanup(jobs, rest, job)


async def run_due(mongo, rest, render):
    jobs = collection(mongo)
    now = utcnow()
    await jobs.update_many(
        {
            "status": {"$in": ["pending", "sending", "cleanup"]},
            "token_expires_at": {"$lte": now},
        },
        {
            "$set": {"status": "expired"},
            "$unset": {"interaction_token": "", "claim_id": "", "lease_until": ""},
        },
    )
    async for row in jobs.find(
        {
            "status": {"$in": ["pending", "sending", "cleanup"]},
            "next_at": {"$lte": now},
            "token_expires_at": {"$gt": now},
            "$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
            ],
        }
    ):
        claim_id = uuid.uuid4().hex
        claimed = await jobs.find_one_and_update(
            {
                "_id": row["_id"],
                "status": row["status"],
                "created_at": row["created_at"],
                "next_at": {"$lte": now},
                "token_expires_at": {"$gt": now},
                "$or": [
                    {"lease_until": {"$exists": False}},
                    {"lease_until": {"$lte": now}},
                ],
            },
            {
                "$set": {
                    "claim_id": claim_id,
                    "lease_until": now + LEASE,
                    "status": (
                        "sending" if row["status"] == "pending" else row["status"]
                    ),
                }
            },
            return_document=ReturnDocument.BEFORE,
        )
        if claimed is None:
            continue
        job = {**claimed, "claim_id": claim_id}
        # A crashed send has no reliable replacement ID. Do not blindly resend
        # or delete the old panel. The next selection can start a fresh job.
        if job["status"] == "sending":
            await finish(jobs, job, "failed", "delivery_unknown_after_restart")
            continue
        try:
            async with asyncio.timeout(45):
                await process(jobs, rest, job, render)
        except Exception as exc:
            # Do not include exception text/tracebacks: webhook URLs contain tokens.
            _log.warning(
                "Recruit panel refresh %s failed (%s), phase=%s",
                job["_id"],
                type(exc).__name__,
                job["status"],
            )
            if job["status"] == "cleanup":
                await jobs.update_one(
                    {"_id": job["_id"], "claim_id": claim_id},
                    {
                        "$set": {"next_at": utcnow() + timedelta(seconds=15)},
                        "$unset": {"lease_until": "", "claim_id": ""},
                    },
                )
            else:
                await finish(jobs, job, "failed", type(exc).__name__)


async def loop(mongo, rest, render):
    while True:
        try:
            await prepare(mongo)
            break
        except Exception as exc:
            _log.warning(
                "Recruit panel refresh storage unavailable (%s)", type(exc).__name__
            )
            await asyncio.sleep(15)
    _log.info("Recruit panel refresh worker ready")
    while True:
        try:
            await run_due(mongo, rest, render)
        except Exception as exc:
            _log.warning("Recruit panel refresh scan failed (%s)", type(exc).__name__)
        await asyncio.sleep(5)


def start(mongo, rest, render):
    global _worker
    if _worker is None or _worker.done():
        _worker = asyncio.create_task(loop(mongo, rest, render))


async def stop():
    global _worker
    if _worker is not None:
        _worker.cancel()
        await asyncio.gather(_worker, return_exceptions=True)
        _worker = None
