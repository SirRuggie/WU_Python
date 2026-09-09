# extensions/events/channel/ticket_channel_monitor.py
"""Event listener for monitoring new channel creation for ticket channels"""

import asyncio
import re
import uuid
import hikari
import lightbulb
import coc
from datetime import datetime, timedelta, timezone
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError
from utils.mongo import MongoClient
from extensions.commands.tickets_legacy import store
from utils.constants import GOLDENROD_ACCENT

# Import Components V2
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    ThumbnailComponentBuilder as Thumbnail,
    SectionComponentBuilder as Section,
)

loader = lightbulb.Loader()

# Add debug print when module loads
print("[INFO] Loading ticket_channel_monitor extension...")

# Global variables to store instances
mongo_client = None
coc_client = None

# Define the patterns we're looking for
PATTERNS = {
    "MAIN": "main",
    "FWA": "fwa",
}

# Define which patterns are currently active
ACTIVE_PATTERNS = ["MAIN", "FWA"]

LEGACY_CHANNEL_NAME_RE = re.compile(
    r"^(?:🆕|✅|❌)?-?(main|fwa)-\d+-",
    re.IGNORECASE,
)

TICKET_LOOKUP_ATTEMPTS = 20
TICKET_LOOKUP_DELAY_SECONDS = 0.5
# The bot permits up to 120 seconds of REST rate-limit waiting and Hikari's
# request timeout adds up to 30 seconds. Keep ample ownership headroom around
# the single, non-retried POST.
DELIVERY_LEASE = timedelta(minutes=5)
DELIVERY_RETRY_BACKOFF = timedelta(seconds=5)
DELIVERY_BACKGROUND_RETRY_DELAYS_SECONDS = (5, 15, 30, 60, 300)
STAFF_LEADERSHIP_ROLE_ID = 1078723854316355595
DELIVERY_PLAN_VERSION = 1
DELIVERY_STEP_FIELDS = (
    "welcome_sent",
    "questionnaire_sent",
    "staff_privacy_sent",
    "staff_how_heard_sent",
    "staff_hook_sent",
    "staff_fwa_donation_sent",
)
_delivery_retry_tasks: dict[int, asyncio.Task] = {}
_delivery_retry_stopping = False


class DeliveryLeaseLost(RuntimeError):
    """A legacy delivery worker no longer owns its durable lease."""


class DeliveryPostUncertain(RuntimeError):
    """Discord may have accepted a message whose response was lost."""

    def __init__(self, step: str, error: Exception):
        super().__init__(f"legacy {step} delivery outcome is uncertain")
        self.step = step
        self.original_error = error


def delivery_now() -> datetime:
    """Read wall time separately before every fenced Discord side effect."""

    return datetime.now(timezone.utc)


async def wait_for_ticket_data(
        mongo: MongoClient,
        channel_id: int,
        *,
        attempts: int = TICKET_LOOKUP_ATTEMPTS,
        delay: float = TICKET_LOOKUP_DELAY_SECONDS,
):
    """Poll briefly for the ticket row created after the channel event fires."""
    lookup_id = f"ticket_{channel_id}"
    for attempt in range(max(1, attempts)):
        ticket_data = await store.find_one(mongo, {"_id": lookup_id})
        if ticket_data:
            return ticket_data
        if attempt + 1 < attempts:
            await asyncio.sleep(delay)
    return None


def build_automation_document(
    *,
    channel_id: int,
    thread_id: int | None,
    guild_id: int,
    user_id: int,
    ticket_type: str,
    now: datetime | None = None,
    initial_delivery: dict | None = None,
) -> dict:
    """Build the durable legacy automation row for event and startup recovery."""

    moment = now or delivery_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    normalized_type = str(ticket_type).strip().lower()
    return {
        "_id": str(channel_id),
        "kind": "legacy_initial_delivery",
        "route": "legacy",
        "runtime": "legacy_channel",
        "channel_id": int(channel_id),
        "thread_id": int(thread_id) if thread_id else None,
        "guild_id": int(guild_id),
        "user_id": int(user_id),
        "ticket_type": normalized_type,
        "created_at": moment,
        "updated_at": moment,
        **(
            {"initial_delivery": dict(initial_delivery)}
            if initial_delivery is not None
            else {}
        ),
        "automation_state": {
            "current_step": "initial",
            "halted": False,
            "halt_reason": None,
            "completed": False,
            "completed_at": None,
        },
        "ticket_info": {
            "user_id": int(user_id),
            "thread_id": int(thread_id) if thread_id else None,
            "player_tags": [],
            "user_tag": None,
            "clan_tags": [],
        },
        "step_data": {
            "account_collection": {
                "started": False,
                "completed": False,
                "accounts": [],
            },
            "questionnaire": {
                "started": False,
                "completed": False,
                "current_question": None,
                "responses": {},
            },
            "fwa": {
                "is_fwa_ticket": normalized_type == "fwa",
                "started": False,
                "completed": False,
            },
            "manual_review": {
                "required": False,
                "reviewed": False,
                "reviewer": None,
                "review_notes": None,
            },
            "final_placement": {
                "assigned_clan": None,
                "assigned_at": None,
                "approved_by": None,
            },
        },
        "messages": {"initial_prompt": str(channel_id)},
        "interaction_history": [
            {
                "timestamp": moment,
                "action": "ticket_created",
                "details": f"Ticket created for user {int(user_id)}",
            }
        ],
    }


async def claim_automation_delivery(
        mongo: MongoClient,
        automation_doc: dict,
        *,
        now: datetime | None = None,
):
    """Claim one channel's initial-message delivery across processes.

    A non-matching upsert races with the existing ``_id`` and raises
    ``DuplicateKeyError``. That is the expected "another worker owns it" result.
    """
    now = now or datetime.now(timezone.utc)
    owner_token = uuid.uuid4().hex
    channel_key = automation_doc["_id"]
    managed_delivery_fields = {
        "status",
        "lease_owner",
        "lease_until",
        "updated_at",
        "last_error",
        "retry_after",
    }
    insert_only = {
        key: value
        for key, value in automation_doc.items()
        if key not in {"kind", "route", "runtime", "initial_delivery"}
    }
    initial_delivery = automation_doc.get("initial_delivery")
    if isinstance(initial_delivery, dict):
        insert_only.update({
            f"initial_delivery.{key}": value
            for key, value in initial_delivery.items()
            if key not in managed_delivery_fields
        })
    query = {
        "_id": channel_key,
        "$or": [
            {"initial_delivery.status": {"$exists": False}},
            {
                "$and": [
                    {"initial_delivery.status": "retry"},
                    {"$or": [
                        {"initial_delivery.retry_after": {"$lte": now}},
                        {"initial_delivery.retry_after": {"$exists": False}},
                    ]},
                ]
            },
            {
                "initial_delivery.status": "processing",
                "initial_delivery.lease_until": {"$lte": now},
            },
        ],
    }
    update = {
        "$setOnInsert": insert_only,
        "$set": {
            "kind": "legacy_initial_delivery",
            "route": "legacy",
            "runtime": "legacy_channel",
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": owner_token,
            "initial_delivery.lease_until": now + DELIVERY_LEASE,
            "initial_delivery.updated_at": now,
        },
        "$unset": {
            "initial_delivery.last_error": "",
            "initial_delivery.retry_after": "",
        },
    }
    try:
        return await mongo.ticket_automation_state.find_one_and_update(
            query,
            update,
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        return None


async def assert_delivery_lease(
    mongo: MongoClient,
    channel_id: int | str,
    owner_token: str,
    *,
    now: datetime | None = None,
) -> dict:
    """Renew immediately before a Discord side effect or fail stale."""

    moment = now or delivery_now()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": str(channel_id),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": moment},
        },
        {"$set": {
            "initial_delivery.lease_until": moment + DELIVERY_LEASE,
            "initial_delivery.updated_at": moment,
        }},
    )
    if not getattr(result, "matched_count", 0):
        raise DeliveryLeaseLost("legacy delivery lease is no longer owned")
    document = await mongo.ticket_automation_state.find_one({
        "_id": str(channel_id),
        "initial_delivery.status": "processing",
        "initial_delivery.lease_owner": str(owner_token),
    })
    delivery = (document or {}).get("initial_delivery") or {}
    lease_until = delivery.get("lease_until")
    if isinstance(lease_until, datetime) and lease_until.tzinfo is None:
        # PyMongo decodes BSON datetimes as naive UTC unless tz_aware is set.
        lease_until = lease_until.replace(tzinfo=timezone.utc)
    if document is None or not isinstance(lease_until, datetime) or lease_until <= moment:
        raise DeliveryLeaseLost("legacy delivery lease is no longer owned")
    return document


async def mark_delivery_step(
    mongo: MongoClient,
    channel_id: int | str,
    owner_token: str,
    step: str,
) -> None:
    now = delivery_now()
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": str(channel_id),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": now},
        },
        {"$set": {
            f"initial_delivery.{step}": True,
            "initial_delivery.updated_at": now,
            "initial_delivery.lease_until": now + DELIVERY_LEASE,
        }},
    )
    if not getattr(result, "matched_count", 0):
        raise DeliveryLeaseLost("legacy delivery lease was lost before checkpoint")


async def finish_automation_delivery(
    mongo: MongoClient, channel_id: int | str, owner_token: str
) -> None:
    now = delivery_now()
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": str(channel_id),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": now},
        },
        {
            "$set": {
                "initial_delivery.status": "complete",
                "initial_delivery.completed_at": now,
                "initial_delivery.updated_at": now,
            },
            "$unset": {
                "initial_delivery.lease_owner": "",
                "initial_delivery.lease_until": "",
                "initial_delivery.last_error": "",
                "initial_delivery.retry_after": "",
                "initial_delivery.needs_history_inspection": "",
                "initial_delivery.ambiguous_step": "",
            },
        },
    )
    if not getattr(result, "matched_count", 0):
        raise DeliveryLeaseLost("legacy delivery lease was lost before completion")


async def release_automation_delivery(
        mongo: MongoClient,
        channel_id: int | str,
        owner_token: str,
        error: Exception | str,
) -> bool:
    now = delivery_now()
    uncertain_step = getattr(error, "step", None)
    retry_fields = {
        "initial_delivery.status": "retry",
        "initial_delivery.last_error": str(error)[:500],
        "initial_delivery.needs_history_inspection": True,
        "initial_delivery.retry_after": now + DELIVERY_RETRY_BACKOFF,
        "initial_delivery.updated_at": now,
    }
    if uncertain_step:
        retry_fields["initial_delivery.ambiguous_step"] = str(uncertain_step)
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": str(channel_id),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": now},
        },
        {
            "$set": retry_fields,
            "$unset": {
                "initial_delivery.lease_owner": "",
                "initial_delivery.lease_until": "",
            },
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def cancel_automation_delivery(
    mongo: MongoClient,
    channel_id: int | str,
    owner_token: str,
    reason: str,
) -> bool:
    """Converge an exact terminal ticket without replaying opening messages."""

    now = delivery_now()
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": str(channel_id),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": now},
        },
        {
            "$set": {
                "initial_delivery.status": "cancelled",
                "initial_delivery.cancel_reason": str(reason)[:240],
                "initial_delivery.cancelled_at": now,
                "initial_delivery.updated_at": now,
            },
            "$unset": {
                "initial_delivery.lease_until": "",
                "initial_delivery.lease_owner": "",
                "initial_delivery.last_error": "",
                "initial_delivery.retry_after": "",
                "initial_delivery.needs_history_inspection": "",
            },
        },
    )
    return bool(getattr(result, "matched_count", 0))


async def checkpoint_delivery_history(
    mongo: MongoClient,
    channel_id: int | str,
    owner_token: str,
    *,
    observed_steps: dict[str, bool],
) -> None:
    """Fence history-derived checkpoints before a recovery worker sends."""

    now = delivery_now()
    if set(observed_steps) != set(DELIVERY_STEP_FIELDS):
        raise ValueError("legacy delivery history checkpoint is incomplete")
    result = await mongo.ticket_automation_state.update_one(
        {
            "_id": str(channel_id),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": now},
        },
        {
            "$set": {
                **{
                    f"initial_delivery.{step}": bool(observed_steps[step])
                    for step in DELIVERY_STEP_FIELDS
                },
                "initial_delivery.history_inspected_at": now,
                "initial_delivery.updated_at": now,
                "initial_delivery.lease_until": now + DELIVERY_LEASE,
            },
            "$unset": {
                "initial_delivery.needs_history_inspection": "",
                "initial_delivery.ambiguous_step": "",
                "initial_delivery.last_error": "",
            },
        },
    )
    if not getattr(result, "matched_count", 0):
        raise DeliveryLeaseLost(
            "legacy delivery lease was lost during history inspection"
        )


async def send_with_retries(rest, **kwargs) -> None:
    """Attempt one POST; an exception has an ambiguous acceptance outcome."""

    await rest.create_message(**kwargs)


def _questionnaire_components(ticket_type: str, guild_icon_url: str | None):
    logo = guild_icon_url or "assets/branding/logo/WU_Logo.png"
    is_fwa = ticket_type == "fwa"
    heading = (
        "## **Warriors United FWA Clan Entry Ticket**"
        if is_fwa
        else "## **Warriors United Main Clan Entry Ticket**"
    )
    questions = [
        "1) In-game name & Player Tag",
        "2) Age & Timezone. Country name would be good too.",
        "3) Do you have multiple accounts?",
        "4) If yes to #3, please provide all Player Tags.",
        "5) What exactly are you looking for in a Clan?",
    ]
    if is_fwa:
        questions.append(
            "6) Are you familiar with LazyCWL and the day to day FWA Process?"
        )
    image = "assets/tickets/static/WU_FWA_Ticket.jpg" if is_fwa else logo
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=heading),
                        Text(content="\n".join(questions)),
                    ],
                    accessory=Thumbnail(media=logo),
                ),
                Media(items=[MediaItem(media=image)]),
                Text(content="-# Patience is key! A Recruiter will be with you soon."),
            ],
        )
    ]


def _delivery_message_plan(
    *,
    user_id: int,
    ticket_type: str,
    recruiter_role: int | str | None,
    guild_icon_url: str | None,
) -> dict:
    """Freeze every opening body so config changes cannot defeat reconciliation."""

    normalized_type = str(ticket_type).strip().lower()
    if normalized_type not in {"main", "fwa"}:
        raise ValueError("legacy delivery ticket type is invalid")
    role_id = int(recruiter_role) if recruiter_role else None
    label = "FWA" if normalized_type == "fwa" else "Main"
    welcome = f"<@{int(user_id)}> Welcome! Thank you for your interest! "
    welcome += f"<@&{role_id}> " if role_id else f"**@{label} Recruiter** "
    welcome += (
        "will be with you shortly, in the meanwhile, please answer the "
        "following questions..."
    )
    staff_privacy = (
        (
            f"<@&{role_id}> <@&{STAFF_LEADERSHIP_ROLE_ID}> "
            "this is a private thread for the candidate. They cannot see this "
            "thread, so DO NOT ping them, as it will add them.\n\n"
        )
        if role_id
        else (
            "⚠️ No recruiter role configured for this ticket type. "
            "Please configure roles using `/ticket config`"
        )
    )
    return {
        "version": DELIVERY_PLAN_VERSION,
        "recruiter_role": role_id,
        "guild_icon_url": str(guild_icon_url) if guild_icon_url else None,
        "welcome_content": welcome,
        "welcome_role_mentions": bool(role_id),
        "staff_privacy_content": staff_privacy,
        "staff_privacy_role_mentions": bool(role_id),
        "staff_how_heard_content": (
            "Hello there 👋🏻...how you hear about Warriors United?"
            if normalized_type == "main"
            else "Hello there 👋🏻...how you hear about our FWA Operation?"
        ),
        "staff_hook_content": (
            "What was the hook that reeled you in? The thing that said "
            '"yeah, I need to check these guys out!!!"'
        ),
        "staff_fwa_donation_content": (
            "Donations are better with the update allowing loot to be used "
            "but clan chats are and can be sporadic."
            if normalized_type == "fwa"
            else None
        ),
    }


def _validate_delivery_plan(plan: dict, *, ticket_type: str) -> dict:
    if not isinstance(plan, dict) or plan.get("version") != DELIVERY_PLAN_VERSION:
        raise RuntimeError("legacy delivery message plan is invalid")
    required_text = (
        "welcome_content",
        "staff_privacy_content",
        "staff_how_heard_content",
        "staff_hook_content",
    )
    if any(not isinstance(plan.get(field), str) for field in required_text):
        raise RuntimeError("legacy delivery message plan is incomplete")
    donation = plan.get("staff_fwa_donation_content")
    if ticket_type == "fwa" and not isinstance(donation, str):
        raise RuntimeError("legacy FWA delivery message plan is incomplete")
    if ticket_type == "main" and donation is not None:
        raise RuntimeError("legacy Main delivery message plan is invalid")
    return plan


async def ensure_delivery_message_plan(
    mongo: MongoClient,
    automation_doc: dict,
    *,
    owner_token: str,
    guild_icon_url: str | None,
) -> dict:
    """Persist the immutable bodies under the active delivery lease."""

    ticket_type = str(automation_doc.get("ticket_type") or "").strip().lower()
    existing = (automation_doc.get("initial_delivery") or {}).get("message_plan")
    if existing is not None:
        _validate_delivery_plan(existing, ticket_type=ticket_type)
        return automation_doc
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    plan = _delivery_message_plan(
        user_id=int(automation_doc["user_id"]),
        ticket_type=ticket_type,
        recruiter_role=config.get(f"{ticket_type}_recruiter_role"),
        guild_icon_url=guild_icon_url,
    )
    now = delivery_now()
    updated = await mongo.ticket_automation_state.find_one_and_update(
        {
            "_id": str(automation_doc["channel_id"]),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
            "initial_delivery.lease_until": {"$gt": now},
            "initial_delivery.message_plan": {"$exists": False},
        },
        {
            "$set": {
                "initial_delivery.message_plan": plan,
                "initial_delivery.updated_at": now,
                "initial_delivery.lease_until": now + DELIVERY_LEASE,
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        updated = await mongo.ticket_automation_state.find_one({
            "_id": str(automation_doc["channel_id"]),
            "initial_delivery.status": "processing",
            "initial_delivery.lease_owner": str(owner_token),
        })
    if updated is None:
        raise DeliveryLeaseLost("legacy delivery lease was lost before plan freeze")
    _validate_delivery_plan(
        ((updated.get("initial_delivery") or {}).get("message_plan")),
        ticket_type=ticket_type,
    )
    return updated


def _expected_step_target(automation_doc: dict, step: str) -> int:
    if step in {"welcome_sent", "questionnaire_sent"}:
        return int(automation_doc["channel_id"])
    if step in DELIVERY_STEP_FIELDS:
        return int(automation_doc.get("thread_id") or 0)
    raise RuntimeError("legacy delivery step is invalid")


def _assert_ticket_matches_automation(ticket: dict, automation_doc: dict) -> str:
    """Validate the immutable ticket identity and return its normalized status."""

    channel_id = int(automation_doc["channel_id"])
    identity = _ticket_delivery_identity(ticket)
    expected = (
        channel_id,
        int(automation_doc.get("guild_id") or 0),
        int(automation_doc["user_id"]),
        str(automation_doc.get("ticket_type") or "").strip().lower(),
    )
    if identity != expected or int(ticket.get("thread_id") or 0) != int(
        automation_doc.get("thread_id") or 0
    ):
        raise RuntimeError("legacy ticket identity changed during opening delivery")
    return str(ticket.get("status") or "").strip().lower()


async def _acquire_ticket_post_intent(
    mongo: MongoClient,
    automation_doc: dict,
    *,
    owner_token: str,
    step: str,
    target_id: int,
) -> str | None:
    """Linearize one Discord POST against terminal resolution on its ticket."""

    channel_id = int(automation_doc["channel_id"])
    await assert_delivery_lease(
        mongo,
        channel_id,
        owner_token,
        now=delivery_now(),
    )
    intent_token = uuid.uuid4().hex
    acquired = await store.acquire_opening_post_intent(
        mongo,
        f"ticket_{channel_id}",
        channel_id=channel_id,
        thread_id=int(automation_doc.get("thread_id") or 0),
        guild_id=int(automation_doc.get("guild_id") or 0),
        user_id=int(automation_doc["user_id"]),
        ticket_type=str(automation_doc.get("ticket_type") or "").strip().lower(),
        token=intent_token,
        step=step,
        target_id=int(target_id),
    )
    if acquired is not None:
        return intent_token

    ticket = await store.find_one(mongo, {"_id": f"ticket_{channel_id}"})
    if ticket is None:
        raise RuntimeError("authoritative legacy ticket is unavailable before POST")
    status = _assert_ticket_matches_automation(ticket, automation_doc)
    if status in {"approved", "denied"}:
        if not await cancel_automation_delivery(
            mongo,
            channel_id,
            owner_token,
            f"authoritative ticket is terminal ({status})",
        ):
            raise DeliveryLeaseLost(
                "legacy delivery lease was lost before terminal cancellation"
            )
        return None
    if status != "open":
        raise RuntimeError("authoritative legacy ticket status is ambiguous before POST")
    if ticket.get("opening_post_intent"):
        raise RuntimeError(
            "legacy opening POST intent requires exact history reconciliation"
        )
    raise RuntimeError("legacy opening POST intent could not be acquired")


async def _settle_opening_post_intent_after_history(
    mongo: MongoClient,
    automation_doc: dict,
) -> None:
    """Clear an ambiguous intent only after both exact histories were read."""

    channel_id = int(automation_doc["channel_id"])
    ticket = await store.find_one(mongo, {"_id": f"ticket_{channel_id}"})
    if ticket is None:
        raise RuntimeError("authoritative legacy ticket is unavailable after history")
    status = _assert_ticket_matches_automation(ticket, automation_doc)
    intent = ticket.get("opening_post_intent")
    if not intent:
        return
    if status != "open":
        raise RuntimeError("terminal legacy ticket retained an opening POST intent")
    step = str(intent.get("step") or "")
    token = str(intent.get("token") or "")
    target_id = int(intent.get("target_id") or 0)
    if (
        not token
        or step not in DELIVERY_STEP_FIELDS
        or target_id != _expected_step_target(automation_doc, step)
    ):
        raise RuntimeError("legacy opening POST intent identity is invalid")
    cleared = await store.clear_opening_post_intent(
        mongo,
        f"ticket_{channel_id}",
        token=token,
        step=step,
    )
    if not cleared:
        raise RuntimeError("legacy opening POST intent changed during settlement")


async def deliver_claimed_automation(
    rest,
    mongo: MongoClient,
    automation_doc: dict,
    *,
    guild_icon_url: str | None = None,
) -> bool:
    """Resume a claimed legacy opening from its durable step checkpoints."""

    channel_id = int(automation_doc["channel_id"])
    thread_id = int(automation_doc.get("thread_id") or 0)
    ticket_type = str(automation_doc.get("ticket_type") or "").strip().lower()
    if ticket_type not in {"main", "fwa"}:
        raise ValueError("legacy delivery ticket type is invalid")
    delivery_state = automation_doc.get("initial_delivery") or {}
    owner_token = str(delivery_state.get("lease_owner") or "")
    if not owner_token:
        raise DeliveryLeaseLost("legacy delivery claim has no lease owner")
    if thread_id <= 0:
        raise RuntimeError("legacy delivery staff thread is invalid")
    plan = _validate_delivery_plan(
        delivery_state.get("message_plan"), ticket_type=ticket_type
    )

    async def post_step(step: str, *, target: int, **kwargs) -> bool:
        if delivery_state.get(step):
            return True
        intent_token = await _acquire_ticket_post_intent(
            mongo,
            automation_doc,
            owner_token=owner_token,
            step=step,
            target_id=target,
        )
        if intent_token is None:
            return False
        try:
            await send_with_retries(rest, channel=target, **kwargs)
        except Exception as error:
            raise DeliveryPostUncertain(step.removesuffix("_sent"), error) from error
        await mark_delivery_step(mongo, channel_id, owner_token, step)
        if not await store.clear_opening_post_intent(
            mongo,
            f"ticket_{channel_id}",
            token=intent_token,
            step=step,
        ):
            raise RuntimeError(
                "legacy opening POST intent could not be cleared after checkpoint"
            )
        delivery_state[step] = True
        return True

    if not await post_step(
        "welcome_sent",
        target=channel_id,
        content=plan["welcome_content"],
        user_mentions=True,
        role_mentions=bool(plan["welcome_role_mentions"]),
    ):
        return False
    if delivery_state.get("welcome_sent") and not delivery_state.get(
        "questionnaire_sent"
    ):
        await asyncio.sleep(1)
    if not await post_step(
        "questionnaire_sent",
        target=channel_id,
        components=_questionnaire_components(
            ticket_type, plan.get("guild_icon_url") or guild_icon_url
        ),
        user_mentions=True,
    ):
        return False
    if not delivery_state.get("staff_privacy_sent"):
        await asyncio.sleep(0.5)
    if not await post_step(
        "staff_privacy_sent",
        target=thread_id,
        content=plan["staff_privacy_content"],
        role_mentions=bool(plan["staff_privacy_role_mentions"]),
    ):
        return False
    if not await post_step(
        "staff_how_heard_sent",
        target=thread_id,
        content=plan["staff_how_heard_content"],
    ):
        return False
    if not await post_step(
        "staff_hook_sent",
        target=thread_id,
        content=plan["staff_hook_content"],
    ):
        return False
    if ticket_type == "fwa" and not await post_step(
        "staff_fwa_donation_sent",
        target=thread_id,
        content=plan["staff_fwa_donation_content"],
    ):
        return False
    if ticket_type == "main":
        delivery_state["staff_fwa_donation_sent"] = True
    ticket = await store.find_one(mongo, {"_id": f"ticket_{channel_id}"})
    if ticket is None:
        raise RuntimeError("authoritative legacy ticket vanished before completion")
    status = _assert_ticket_matches_automation(ticket, automation_doc)
    if status in {"approved", "denied"}:
        if not await cancel_automation_delivery(
            mongo,
            channel_id,
            owner_token,
            f"authoritative ticket is terminal ({status})",
        ):
            raise DeliveryLeaseLost(
                "legacy delivery lease was lost before terminal cancellation"
            )
        return False
    if status != "open":
        raise RuntimeError("authoritative legacy ticket status is ambiguous")
    await assert_delivery_lease(mongo, channel_id, owner_token, now=delivery_now())
    await finish_automation_delivery(mongo, channel_id, owner_token)
    return True


async def _message_history(rest, channel_id: int) -> list:
    iterator = rest.fetch_messages(channel_id)
    collect = getattr(iterator, "collect", None)
    if callable(collect):
        return list(await collect(list))
    to_list = getattr(iterator, "to_list", None)
    if callable(to_list):
        return list(await to_list())
    return list(await iterator)


def _component_signature(components) -> tuple:
    """Build a stable, ordered semantic signature for the questionnaire."""

    def scalar(value):
        if value is hikari.UNDEFINED:
            return None
        if value is None or isinstance(value, (str, int, bool, float)):
            return value
        raw = getattr(value, "url", None)
        if raw is not None:
            return str(raw)
        return str(value)

    def one(component) -> tuple:
        media = getattr(component, "media", None)
        accessory = getattr(component, "accessory", None)
        spoiler = getattr(component, "is_spoiler", hikari.UNDEFINED)
        if spoiler is hikari.UNDEFINED:
            spoiler = getattr(component, "spoiler", False)
        if spoiler is hikari.UNDEFINED:
            spoiler = False
        children = tuple(
            one(child) for child in (getattr(component, "components", ()) or ())
        )
        return (
            scalar(getattr(component, "type", None)),
            str(getattr(component, "content", "") or ""),
            scalar(getattr(component, "accent_color", None)),
            bool(spoiler),
            scalar(media),
            scalar(getattr(component, "description", None)),
            one(accessory) if accessory is not None else None,
            children,
            tuple(
                one(item) for item in (getattr(component, "items", ()) or ())
            ),
        )

    return tuple(one(component) for component in (components or ()))


async def _existing_delivery_steps(
    bot,
    *,
    automation_doc: dict,
    message_plan: dict,
) -> dict[str, bool]:
    me = bot.get_me()
    if me is None:
        raise RuntimeError("bot identity is unavailable for delivery inspection")
    channel_id = int(automation_doc["channel_id"])
    thread_id = int(automation_doc.get("thread_id") or 0)
    ticket_type = str(automation_doc.get("ticket_type") or "").strip().lower()
    plan = _validate_delivery_plan(message_plan, ticket_type=ticket_type)
    expected_questionnaire = _component_signature(
        _questionnaire_components(ticket_type, plan.get("guild_icon_url"))
    )
    observed = {step: False for step in DELIVERY_STEP_FIELDS}
    if ticket_type == "main":
        observed["staff_fwa_donation_sent"] = True
    for message in await _message_history(bot.rest, channel_id):
        if int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        content = str(getattr(message, "content", "") or "")
        observed["welcome_sent"] = observed["welcome_sent"] or (
            content == plan["welcome_content"]
        )
        components = tuple(getattr(message, "components", ()) or ())
        observed["questionnaire_sent"] = observed["questionnaire_sent"] or (
            _component_signature(components) == expected_questionnaire
        )
        if observed["welcome_sent"] and observed["questionnaire_sent"]:
            break
    for message in await _message_history(bot.rest, thread_id):
        if int(getattr(getattr(message, "author", None), "id", 0)) != int(me.id):
            continue
        content = str(getattr(message, "content", "") or "")
        observed["staff_privacy_sent"] = observed["staff_privacy_sent"] or (
            content == plan["staff_privacy_content"]
        )
        observed["staff_how_heard_sent"] = observed["staff_how_heard_sent"] or (
            content == plan["staff_how_heard_content"]
        )
        observed["staff_hook_sent"] = observed["staff_hook_sent"] or (
            content == plan["staff_hook_content"]
        )
        donation = plan.get("staff_fwa_donation_content")
        if donation is not None:
            observed["staff_fwa_donation_sent"] = (
                observed["staff_fwa_donation_sent"] or content == donation
            )
        if all(observed.values()):
            break
    return observed


def _ticket_delivery_identity(ticket_data: dict) -> tuple[int, int, int, str]:
    channel_id = int(ticket_data.get("channel_id", 0))
    guild_id = int(ticket_data.get("guild_id", 0))
    user_id = int(ticket_data.get("user_id", 0))
    ticket_type = str(ticket_data.get("ticket_type") or "").strip().lower()
    if (
        channel_id <= 0
        or guild_id <= 0
        or user_id <= 0
        or ticket_type not in {"main", "fwa"}
        or str(ticket_data.get("_id")) != f"ticket_{channel_id}"
    ):
        raise RuntimeError("legacy ticket delivery identity is invalid")
    return channel_id, guild_id, user_id, ticket_type


def _assert_automation_identity(
    automation_doc: dict,
    *,
    channel_id: int,
    thread_id: int,
    guild_id: int,
    user_id: int,
    ticket_type: str,
) -> None:
    """Refuse to reuse a colliding automation row for another ticket."""

    if (
        str(automation_doc.get("_id")) != str(channel_id)
        or int(automation_doc.get("channel_id", 0)) != int(channel_id)
        or int(automation_doc.get("thread_id", 0)) != int(thread_id)
        or int(automation_doc.get("guild_id", 0)) != int(guild_id)
        or int(automation_doc.get("user_id", 0)) != int(user_id)
        or str(automation_doc.get("ticket_type") or "").strip().lower()
        != ticket_type
        or automation_doc.get("kind") != "legacy_initial_delivery"
        or automation_doc.get("route") != "legacy"
        or automation_doc.get("runtime") != "legacy_channel"
    ):
        raise RuntimeError("legacy automation identity collision")


async def _upgrade_legacy_automation_identity(
    mongo: MongoClient,
    automation_doc: dict,
    ticket_data: dict,
) -> dict:
    """Fence and upgrade a markerless pre-coexistence monitor row in place."""

    channel_id, guild_id, user_id, ticket_type = _ticket_delivery_identity(
        ticket_data
    )
    thread_id = int(ticket_data.get("thread_id") or 0)
    if thread_id <= 0 or str(automation_doc.get("_id")) != str(channel_id):
        raise RuntimeError("legacy automation upgrade identity is invalid")

    if (
        automation_doc.get("kind") == "legacy_initial_delivery"
        and automation_doc.get("route") == "legacy"
        and automation_doc.get("runtime") == "legacy_channel"
    ):
        _assert_automation_identity(
            automation_doc,
            channel_id=channel_id,
            thread_id=thread_id,
            guild_id=guild_id,
            user_id=user_id,
            ticket_type=ticket_type,
        )
        return automation_doc

    nested = automation_doc.get("ticket_info")
    if not isinstance(nested, dict):
        raise RuntimeError("legacy automation upgrade evidence is incomplete")
    evidence = {
        "channel_id": (automation_doc.get("channel_id"), channel_id),
        "user_id": (automation_doc.get("user_id"), user_id),
        "thread_id": (automation_doc.get("thread_id"), thread_id),
        "ticket_info.user_id": (nested.get("user_id"), user_id),
        "ticket_info.thread_id": (nested.get("thread_id"), thread_id),
    }
    if int(automation_doc.get("channel_id") or 0) != channel_id:
        raise RuntimeError("legacy automation upgrade channel evidence conflicts")
    for label, (observed, expected) in evidence.items():
        if observed not in {None, ""} and int(observed) != expected:
            raise RuntimeError(f"legacy automation upgrade {label} conflicts")
    if not any(
        int(value or 0) == user_id
        for value in (automation_doc.get("user_id"), nested.get("user_id"))
    ):
        raise RuntimeError("legacy automation upgrade user evidence is incomplete")
    if not any(
        int(value or 0) == thread_id
        for value in (automation_doc.get("thread_id"), nested.get("thread_id"))
    ):
        raise RuntimeError("legacy automation upgrade thread evidence is incomplete")
    observed_type = str(automation_doc.get("ticket_type") or "").strip().lower()
    if observed_type != ticket_type:
        raise RuntimeError("legacy automation upgrade ticket type conflicts")

    canonical = {
        "kind": "legacy_initial_delivery",
        "route": "legacy",
        "runtime": "legacy_channel",
        "guild_id": guild_id,
        "channel_id": channel_id,
        "thread_id": thread_id,
        "user_id": user_id,
        "ticket_type": ticket_type,
    }
    query: dict = {"_id": str(channel_id)}
    updates: dict = {}
    for field, expected in canonical.items():
        if field not in automation_doc:
            query[field] = {"$exists": False}
            updates[field] = expected
            continue
        observed = automation_doc.get(field)
        if field in {"guild_id", "channel_id", "thread_id", "user_id"}:
            if observed in {None, ""}:
                query[field] = observed
                updates[field] = expected
            elif int(observed) != int(expected):
                raise RuntimeError(
                    f"legacy automation upgrade {field} conflicts"
                )
            else:
                query[field] = observed
        elif observed != expected:
            raise RuntimeError(f"legacy automation upgrade {field} conflicts")
        else:
            query[field] = observed
    for field in ("user_id", "thread_id"):
        path = f"ticket_info.{field}"
        if field not in nested:
            query[path] = {"$exists": False}
            updates[path] = canonical[field]
        elif nested.get(field) in {None, ""}:
            query[path] = nested.get(field)
            updates[path] = canonical[field]
        else:
            query[path] = nested[field]

    if updates:
        upgraded = await mongo.ticket_automation_state.find_one_and_update(
            query,
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )
        if upgraded is None:
            upgraded = await mongo.ticket_automation_state.find_one(
                {"_id": str(channel_id)}
            )
        if upgraded is None:
            raise RuntimeError("legacy automation upgrade lost its row")
    else:
        upgraded = automation_doc
    _assert_automation_identity(
        upgraded,
        channel_id=channel_id,
        thread_id=thread_id,
        guild_id=guild_id,
        user_id=user_id,
        ticket_type=ticket_type,
    )
    return upgraded


async def ensure_ticket_automation_delivery(
    mongo: MongoClient,
    ticket_data: dict,
    *,
    now: datetime | None = None,
) -> dict:
    """Materialize one committed open legacy ticket's delivery obligation."""

    channel_id, guild_id, user_id, ticket_type = _ticket_delivery_identity(
        ticket_data
    )
    thread_id = int(ticket_data.get("thread_id", 0))
    if thread_id <= 0:
        raise RuntimeError("legacy delivery staff thread identity is invalid")
    if str(ticket_data.get("status") or "").strip().lower() != "open":
        raise RuntimeError("legacy delivery can only be queued for an open ticket")
    moment = now or delivery_now()
    document = build_automation_document(
        channel_id=channel_id,
        thread_id=thread_id,
        guild_id=guild_id,
        user_id=user_id,
        ticket_type=ticket_type,
        now=moment,
        initial_delivery={
            "status": "retry",
            "needs_history_inspection": True,
            "updated_at": moment,
        },
    )
    try:
        await mongo.ticket_automation_state.insert_one(document)
        existing = document
    except DuplicateKeyError:
        existing = await mongo.ticket_automation_state.find_one(
            {"_id": str(channel_id)}
        )
        if existing is None:
            raise RuntimeError(
                "legacy automation collision could not be read"
            ) from None
    _assert_automation_identity(
        existing,
        channel_id=channel_id,
        thread_id=thread_id,
        guild_id=guild_id,
        user_id=user_id,
        ticket_type=ticket_type,
    )
    return existing


async def _synthesize_missing_automation_rows(
    mongo: MongoClient,
    *,
    limit: int,
    now: datetime,
) -> int:
    """Durably expose open tickets whose channel event died before its row."""

    created = 0
    open_tickets = sorted(
        await store.find(mongo, {"status": "open"}),
        key=lambda ticket: str(ticket.get("_id")),
    )
    for ticket_data in open_tickets:
        if created >= limit:
            break
        channel_id, guild_id, user_id, ticket_type = _ticket_delivery_identity(
            ticket_data
        )
        thread_id = int(ticket_data.get("thread_id", 0))
        if thread_id <= 0:
            raise RuntimeError("legacy delivery staff thread identity is invalid")
        existing = await mongo.ticket_automation_state.find_one(
            {"_id": str(channel_id)}
        )
        if existing is not None:
            continue
        document = build_automation_document(
            channel_id=channel_id,
            thread_id=thread_id,
            guild_id=guild_id,
            user_id=user_id,
            ticket_type=ticket_type,
            now=now,
            initial_delivery={
                "status": "retry",
                "needs_history_inspection": True,
                "last_error": "startup recovered a missing delivery checkpoint",
                "updated_at": now,
            },
        )
        try:
            await mongo.ticket_automation_state.insert_one(document)
        except DuplicateKeyError:
            continue
        created += 1
    return created


async def recover_pending_automation_deliveries(
    *,
    bot,
    mongo: MongoClient,
    limit: int = 25,
    now: datetime | None = None,
    only_channel_id: int | None = None,
) -> dict[str, int]:
    """Retry eligible legacy opening deliveries without replaying sent steps."""

    from extensions.commands import ticket_runtime

    moment = now or datetime.now(timezone.utc)
    bounded = max(1, int(limit))
    synthesized = (
        await _synthesize_missing_automation_rows(
            mongo, limit=bounded, now=moment
        )
        if only_channel_id is None
        else 0
    )
    recovery_query = ticket_runtime.legacy_recoverable_delivery_query(now=moment)
    if only_channel_id is not None:
        recovery_query = {
            "$and": [
                recovery_query,
                {"_id": str(int(only_channel_id))},
            ]
        }
    cursor = mongo.ticket_automation_state.find(recovery_query)
    rows = await cursor.sort([("_id", 1)]).limit(bounded).to_list(length=bounded)
    completed = 0
    cancelled = 0
    failed = 0
    for automation_doc in rows:
        channel_key = automation_doc.get("channel_id", automation_doc.get("_id"))
        claimed = None
        owner_token = ""
        try:
            channel_id = int(channel_key)
            ticket_data = await store.find_one(
                mongo, {"_id": f"ticket_{channel_id}"}
            )
            if ticket_data is None:
                raise RuntimeError("authoritative legacy ticket is unavailable")
            bound_channel, guild_id, bound_user, bound_type = (
                _ticket_delivery_identity(ticket_data)
            )
            automation_doc = await _upgrade_legacy_automation_identity(
                mongo,
                automation_doc,
                ticket_data,
            )
            user_id = int(automation_doc["user_id"])
            ticket_type = str(
                automation_doc.get("ticket_type") or ""
            ).strip().lower()
            if (
                bound_channel != channel_id
                or bound_user != user_id
                or bound_type != ticket_type
            ):
                raise RuntimeError("legacy automation identity does not match ticket")
            thread_id = int(ticket_data.get("thread_id") or 0)
            _assert_automation_identity(
                automation_doc,
                channel_id=channel_id,
                thread_id=thread_id,
                guild_id=guild_id,
                user_id=user_id,
                ticket_type=ticket_type,
            )
            status = str(ticket_data.get("status") or "").strip().lower()
            if status in {"approved", "denied"}:
                if ticket_data.get("opening_post_intent"):
                    raise RuntimeError(
                        "terminal legacy ticket retained an opening POST intent"
                    )
                claim_moment = delivery_now()
                claimed = await claim_automation_delivery(
                    mongo, automation_doc, now=claim_moment
                )
                if claimed is None:
                    continue
                owner_token = str(
                    (claimed.get("initial_delivery") or {}).get("lease_owner") or ""
                )
                _assert_automation_identity(
                    claimed,
                    channel_id=channel_id,
                    thread_id=thread_id,
                    guild_id=guild_id,
                    user_id=user_id,
                    ticket_type=ticket_type,
                )
                if not owner_token or not await cancel_automation_delivery(
                    mongo,
                    channel_key,
                    owner_token,
                    f"authoritative ticket is terminal ({status})",
                ):
                    raise DeliveryLeaseLost(
                        "legacy delivery lease was lost before cancellation"
                    )
                cancelled += 1
                continue
            if status != "open":
                raise RuntimeError("authoritative legacy ticket status is ambiguous")
            channel = await bot.rest.fetch_channel(channel_id)
            if getattr(channel, "type", None) != hikari.ChannelType.GUILD_TEXT:
                raise RuntimeError("legacy delivery target is not a guild text channel")
            channel_match = LEGACY_CHANNEL_NAME_RE.match(
                str(getattr(channel, "name", "") or "")
            )
            if channel_match is None or channel_match.group(1).lower() != ticket_type:
                raise RuntimeError("legacy delivery target name does not match ticket")
            if int(getattr(channel, "guild_id", 0)) != guild_id:
                raise RuntimeError("legacy delivery guild binding does not match")
            thread = await bot.rest.fetch_channel(thread_id)
            if getattr(thread, "type", None) != hikari.ChannelType.GUILD_PRIVATE_THREAD:
                raise RuntimeError(
                    "legacy delivery staff target is not a private thread"
                )
            if int(getattr(thread, "guild_id", 0)) != guild_id:
                raise RuntimeError("legacy delivery staff thread guild does not match")
            if int(getattr(thread, "parent_id", 0)) != channel_id:
                raise RuntimeError("legacy delivery staff thread parent does not match")
            claim_moment = delivery_now()
            claimed = await claim_automation_delivery(
                mongo, automation_doc, now=claim_moment
            )
            if claimed is None:
                continue
            owner_token = str(
                (claimed.get("initial_delivery") or {}).get("lease_owner") or ""
            )
            _assert_automation_identity(
                claimed,
                channel_id=channel_id,
                thread_id=thread_id,
                guild_id=guild_id,
                user_id=user_id,
                ticket_type=ticket_type,
            )
            current_ticket = await store.find_one(
                mongo, {"_id": f"ticket_{channel_id}"}
            )
            if current_ticket is None:
                raise RuntimeError(
                    "authoritative legacy ticket vanished after delivery claim"
                )
            current_identity = _ticket_delivery_identity(current_ticket)
            if current_identity != (channel_id, guild_id, user_id, ticket_type):
                raise RuntimeError(
                    "legacy ticket identity changed after delivery claim"
                )
            if int(current_ticket.get("thread_id") or 0) != thread_id:
                raise RuntimeError(
                    "legacy ticket staff thread changed after delivery claim"
                )
            current_status = str(
                current_ticket.get("status") or ""
            ).strip().lower()
            if current_status in {"approved", "denied"}:
                if not await cancel_automation_delivery(
                    mongo,
                    channel_id,
                    owner_token,
                    f"authoritative ticket is terminal ({current_status})",
                ):
                    raise DeliveryLeaseLost(
                        "legacy delivery lease was lost before cancellation"
                    )
                cancelled += 1
                continue
            if current_status != "open":
                raise RuntimeError(
                    "authoritative legacy ticket status changed ambiguously"
                )
            cache = getattr(bot, "cache", None)
            guild = cache.get_guild(guild_id) if cache is not None else None
            icon = guild.make_icon_url() if guild is not None else None
            claimed = await ensure_delivery_message_plan(
                mongo,
                claimed,
                owner_token=owner_token,
                guild_icon_url=icon,
            )
            delivery_state = claimed.get("initial_delivery") or {}
            plan = _validate_delivery_plan(
                delivery_state.get("message_plan"), ticket_type=ticket_type
            )
            observed = await _existing_delivery_steps(
                bot,
                automation_doc=claimed,
                message_plan=plan,
            )
            merged_steps = {
                step: bool(delivery_state.get(step) or observed[step])
                for step in DELIVERY_STEP_FIELDS
            }
            await checkpoint_delivery_history(
                mongo,
                channel_id,
                owner_token,
                observed_steps=merged_steps,
            )
            claimed_delivery = claimed.setdefault("initial_delivery", {})
            claimed_delivery.update(merged_steps)
            claimed_delivery.pop("needs_history_inspection", None)
            claimed_delivery.pop("last_error", None)
            await _settle_opening_post_intent_after_history(mongo, claimed)
            delivered = await deliver_claimed_automation(
                bot.rest, mongo, claimed, guild_icon_url=icon
            )
            if delivered:
                completed += 1
            else:
                cancelled += 1
        except Exception as error:  # noqa: BLE001 - durable retry records the cause
            if claimed is None:
                claim_moment = delivery_now()
                claimed = await claim_automation_delivery(
                    mongo, automation_doc, now=claim_moment
                )
                owner_token = str(
                    (claimed or {}).get("initial_delivery", {}).get(
                        "lease_owner", ""
                    )
                )
            if claimed is not None and owner_token:
                await release_automation_delivery(
                    mongo, channel_key, owner_token, error
                )
            failed += 1
    pending = await mongo.ticket_automation_state.count_documents(
        ticket_runtime.legacy_pending_delivery_query()
    )
    return {
        "processed": len(rows),
        "completed": completed,
        "cancelled": cancelled,
        "failed": failed,
        "pending": int(pending),
        "synthesized": synthesized,
    }


async def ensure_and_deliver_ticket_automation(
    *,
    bot,
    mongo: MongoClient,
    ticket_data: dict,
    now: datetime | None = None,
) -> dict[str, int]:
    """Queue and best-effort drive one exact committed legacy ticket."""

    channel_id, _guild_id, _user_id, _ticket_type = _ticket_delivery_identity(
        ticket_data
    )
    await ensure_ticket_automation_delivery(mongo, ticket_data, now=now)
    result = await recover_pending_automation_deliveries(
        bot=bot,
        mongo=mongo,
        limit=1,
        now=now,
        only_channel_id=channel_id,
    )
    if result.get("failed"):
        raise RuntimeError("legacy initial delivery remains retryable")
    current = await mongo.ticket_automation_state.find_one(
        {"_id": str(channel_id)}
    )
    status = str(
        ((current or {}).get("initial_delivery") or {}).get("status") or ""
    )
    if status not in {"complete", "cancelled"}:
        raise RuntimeError(
            f"legacy initial delivery is still pending ({status or 'missing'})"
        )
    return result


async def _retry_ticket_automation_delivery(
    *,
    bot,
    mongo: MongoClient,
    ticket_id: str,
) -> None:
    """Retry one committed ticket online until delivery durably settles."""

    attempt = 0
    while True:
        try:
            ticket_data = await store.find_one(mongo, {"_id": ticket_id})
            if ticket_data is None:
                raise RuntimeError("authoritative legacy ticket is unavailable")
            channel_id, _guild_id, _user_id, _ticket_type = (
                _ticket_delivery_identity(ticket_data)
            )
            status = str(ticket_data.get("status") or "").strip().lower()
            if status == "open":
                await ensure_and_deliver_ticket_automation(
                    bot=bot,
                    mongo=mongo,
                    ticket_data=ticket_data,
                )
                return
            if status in {"approved", "denied"}:
                existing = await mongo.ticket_automation_state.find_one(
                    {"_id": str(channel_id)}
                )
                if existing is None:
                    return
                result = await recover_pending_automation_deliveries(
                    bot=bot,
                    mongo=mongo,
                    limit=1,
                    only_channel_id=channel_id,
                )
                current = await mongo.ticket_automation_state.find_one(
                    {"_id": str(channel_id)}
                )
                delivery_status = str(
                    ((current or {}).get("initial_delivery") or {}).get("status")
                    or ""
                )
                if result.get("failed") or delivery_status not in {
                    "complete",
                    "cancelled",
                }:
                    raise RuntimeError(
                        "terminal legacy initial delivery remains pending"
                    )
                return
            raise RuntimeError("authoritative legacy ticket status is ambiguous")
        except asyncio.CancelledError:
            raise
        except Exception as error:
            attempt += 1
            delays = DELIVERY_BACKGROUND_RETRY_DELAYS_SECONDS
            delay = delays[min(attempt - 1, len(delays) - 1)]
            if attempt <= len(delays) or (attempt - len(delays)) % 12 == 0:
                print(
                    "[Tickets:Legacy] initial_delivery_retry "
                    f"ticket_id={ticket_id} attempt={attempt} "
                    f"delay_seconds={delay} error={type(error).__name__}"
                )
            await asyncio.sleep(delay)


def schedule_ticket_automation_delivery_retry(
    *,
    bot,
    mongo: MongoClient,
    ticket_data: dict,
) -> asyncio.Task:
    """Track one shutdown-safe online retry worker per committed ticket."""

    if _delivery_retry_stopping:
        raise RuntimeError("legacy delivery retry scheduling is stopping")
    channel_id, _guild_id, _user_id, _ticket_type = _ticket_delivery_identity(
        ticket_data
    )
    ticket_id = str(ticket_data["_id"])
    current = _delivery_retry_tasks.get(channel_id)
    if current is not None and not current.done():
        return current
    task = asyncio.create_task(
        _retry_ticket_automation_delivery(
            bot=bot,
            mongo=mongo,
            ticket_id=ticket_id,
        ),
        name=f"legacy-initial-delivery:{channel_id}",
    )
    _delivery_retry_tasks[channel_id] = task

    def discard(done: asyncio.Task) -> None:
        if _delivery_retry_tasks.get(channel_id) is done:
            _delivery_retry_tasks.pop(channel_id, None)
        if not done.cancelled():
            error = done.exception()
            if error is not None:
                print(
                    "[Tickets:Legacy] initial_delivery_worker_failed "
                    f"ticket_id={ticket_id} error={type(error).__name__}"
                )

    task.add_done_callback(discard)
    return task


async def stop_ticket_automation_delivery_retries() -> None:
    """Cancel and await every monitor-owned online retry worker."""

    global _delivery_retry_stopping
    _delivery_retry_stopping = True
    tasks = list(_delivery_retry_tasks.values())
    for task in tasks:
        if not task.done():
            task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _delivery_retry_tasks.clear()


async def start_ticket_automation_delivery_retries() -> None:
    """Drain a prior lifecycle before reopening the scheduling gate."""

    global _delivery_retry_stopping
    await stop_ticket_automation_delivery_retries()
    _delivery_retry_stopping = False


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED,
        coc_api: coc.Client = lightbulb.di.INJECTED
) -> None:
    """Store instances when bot starts"""
    global mongo_client, coc_client
    # A hot restart cannot inherit tasks tied to the previous REST/Mongo
    # lifecycle. Fence, drain, then reopen scheduling for this lifecycle.
    await start_ticket_automation_delivery_retries()
    mongo_client = mongo
    coc_client = coc_api
    print("[INFO] Ticket channel monitor ready with MongoDB and CoC connections")


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(_: hikari.StoppingEvent) -> None:
    """Stop monitor-owned delivery retry tasks before REST/Mongo shutdown."""

    await stop_ticket_automation_delivery_retries()


@loader.listener(hikari.GuildChannelCreateEvent)
async def on_channel_create(event: hikari.GuildChannelCreateEvent) -> None:
    """Handle channel creation events"""

    # Thread creation and unrelated guild-channel events belong to other
    # runtimes.  The legacy monitor owns only top-level guild text channels.
    if getattr(event.channel, "type", None) != hikari.ChannelType.GUILD_TEXT:
        return

    # Get the channel name
    channel_name = event.channel.name

    # Debug logging
    print(f"[DEBUG] New channel created: {channel_name} (ID: {event.channel.id})")

    match = LEGACY_CHANNEL_NAME_RE.match(channel_name or "")
    if not match:
        print(f"[DEBUG] Channel {channel_name} does not match any active patterns")
        return
    matched_pattern = match.group(1).upper()
    if matched_pattern not in ACTIVE_PATTERNS:
        return
    print(f"[DEBUG] Channel matches legacy pattern: {matched_pattern}")

    # Get the channel ID
    channel_id = event.channel.id

    # Try to find the ticket data from MongoDB - it's stored immediately by ticket creation
    ticket_data = None

    if mongo_client:
        try:
            print(f"[DEBUG] Waiting for ticket with _id: ticket_{channel_id}")
            ticket_data = await wait_for_ticket_data(mongo_client, channel_id)
            if ticket_data:
                print(
                    "[DEBUG] Found ticket data: "
                    f"user_id={ticket_data.get('user_id')}, "
                    f"thread_id={ticket_data.get('thread_id')}, "
                    f"ticket_type={ticket_data.get('ticket_type')}"
                )
            else:
                print(
                    f"[ERROR] No ticket data found for channel {channel_id} after "
                    f"{TICKET_LOOKUP_ATTEMPTS} attempts"
                )
                return
        except Exception as e:
            print(f"[ERROR] Failed to fetch ticket data from MongoDB: {e}")
            return

    # Gateway delivery uses the same authoritative executor as post-commit,
    # online retry, and startup recovery. The tracked worker covers any
    # transient failure after this event returns.
    if ticket_data is not None:
        try:
            schedule_ticket_automation_delivery_retry(
                bot=event.app,
                mongo=mongo_client,
                ticket_data=ticket_data,
            )
            await ensure_and_deliver_ticket_automation(
                bot=event.app,
                mongo=mongo_client,
                ticket_data=ticket_data,
            )
        except Exception as error:
            print(
                "[Tickets:Legacy] gateway_initial_delivery_deferred "
                f"ticket_id={ticket_data.get('_id')} "
                f"error={type(error).__name__}"
            )
        return
