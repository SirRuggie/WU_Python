"""Self-service removal of this bot's old messages from one private DM."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time
import uuid

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from extensions.commands import todo
from utils.component_state import insert_state, update_state
from utils.constants import RED_ACCENT
from utils.mongo import MongoClient

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)

STATE_TYPE = "clear_my_dms"
STATE_TTL = timedelta(minutes=10)
RECEIPT_SECONDS = 15
# Discord's delete-message bucket is dynamic. Keep this intentionally below a
# request per second, while Hikari still honours any stricter server Retry-After.
DELETE_INTERVAL_SECONDS = 1.1


class _PurgeFailure(RuntimeError):
    def __init__(self, deleted: int, cause: Exception) -> None:
        super().__init__(str(cause))
        self.deleted = deleted
        self.cause = cause


def _as_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _monotonic() -> float:
    """Local seam for deterministic pacing tests without altering asyncio's clock."""
    return time.monotonic()


async def _requester_dm(ctx, bot, *, user_id: int, channel_id: int) -> bool:
    """Verify the interaction is still the requester's one-to-one DM."""
    if getattr(ctx, "guild_id", None) is not None:
        return False
    interaction = getattr(ctx, "interaction", None)
    actual_channel_id = _as_int(getattr(interaction, "channel_id", None))
    if actual_channel_id is not None and actual_channel_id != channel_id:
        return False
    try:
        channel = await bot.rest.fetch_channel(channel_id)
    except (hikari.ForbiddenError, hikari.NotFoundError):
        return False
    return (
        getattr(channel, "type", None) == hikari.ChannelType.DM
        and _as_int(getattr(getattr(channel, "recipient", None), "id", None))
        == user_id
    )


async def _claim(
    mongo: MongoClient, *, action_id: str, user_id: int, channel_id: int
) -> dict | None:
    """Atomically make one confirmation click the sole purge worker."""
    return await mongo.component_state.find_one_and_update(
        {
            "_id": action_id,
            "type": STATE_TYPE,
            "status": "pending",
            "user_id": user_id,
            "channel_id": channel_id,
            "expires_at": {"$gt": datetime.now(timezone.utc)},
            "cutoff_id": {"$gt": 0},
        },
        {"$set": {"status": "running", "started_at": datetime.now(timezone.utc)}},
    )


async def _cancel(
    mongo: MongoClient, *, action_id: str, user_id: int, channel_id: int
) -> bool:
    """Consume a still-pending request so confirm and cancel have one winner."""
    result = await mongo.component_state.delete_one({
        "_id": action_id,
        "type": STATE_TYPE,
        "status": "pending",
        "user_id": user_id,
        "channel_id": channel_id,
        "expires_at": {"$gt": datetime.now(timezone.utc)},
    })
    return bool(getattr(result, "deleted_count", 0))


def _confirmation(action_id: str) -> list:
    return [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## Delete WUBOT messages from this DM?"),
                Text(content=(
                    "This permanently deletes **all messages authored by WUBOT** "
                    "in this private DM, including the oldest messages and this "
                    "confirmation. Your messages are preserved.\n\n"
                    "The active automatic `/todo` panel will be stopped first. "
                    "Future reminders and a future `/todo` command remain enabled. "
                    "This can take time for a long history and cannot be undone. "
                    "A temporary completion receipt follows after the sweep."
                )),
                Separator(divider=True),
                ActionRow(components=[
                    Button(
                        style=hikari.ButtonStyle.DANGER,
                        label="Delete WUBOT messages",
                        custom_id=f"clear_my_dms_confirm:{action_id}",
                    ),
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        label="Cancel",
                        custom_id=f"clear_my_dms_cancel:{action_id}",
                    ),
                ]),
            ],
        )
    ]


async def _delete_through_cutoff(bot, *, channel_id: int, cutoff_id: int) -> int:
    """Stream and remove this application's messages up to one fixed snowflake."""
    deleted = 0
    last_delete_finished_at: float | None = None
    # ``before`` is exclusive.  The next numeric snowflake includes the visible
    # confirmation itself while the fixed cutoff excludes later notifications.
    try:
        me = bot.get_me()
        bot_id = _as_int(getattr(me, "id", None))
        if bot_id is None:
            raise RuntimeError("bot identity is unavailable")
        async for message in bot.rest.fetch_messages(channel_id, before=cutoff_id + 1):
            message_id = _as_int(getattr(message, "id", None))
            if message_id is None or message_id > cutoff_id:
                continue
            author_id = _as_int(getattr(getattr(message, "author", None), "id", None))
            if author_id != bot_id:
                continue
            # A cooperative delay after each completed eligible request keeps
            # the next deletion at least 1.1s away. It is deliberately not a
            # 429 retry: Hikari owns Discord's bucket and Retry-After handling,
            # including a longer wait when the server requires one.
            if last_delete_finished_at is not None:
                delay = DELETE_INTERVAL_SECONDS - (
                    _monotonic() - last_delete_finished_at
                )
                if delay > 0:
                    await asyncio.sleep(delay)
            try:
                await bot.rest.delete_message(channel_id, message.id)
            except hikari.NotFoundError:
                # Another client may already have removed it; it is no longer
                # part of the requested history, so continue the complete scan.
                continue
            finally:
                # Anchor the next pacing interval to the completed REST call,
                # including a Hikari-managed 429 retry or a NotFound response.
                last_delete_finished_at = _monotonic()
            deleted += 1
    except Exception as exc:  # preserve accurate partial progress for the receipt
        raise _PurgeFailure(deleted, exc) from exc
    return deleted


async def _temporary_receipt(bot, channel_id: int, content: str) -> None:
    """Post the only new visible result, then remove it without a stray task."""
    message = await bot.rest.create_message(channel_id, content)
    await asyncio.sleep(RECEIPT_SECONDS)
    try:
        await bot.rest.delete_message(channel_id, message.id)
    except (hikari.ForbiddenError, hikari.NotFoundError):
        pass


@loader.command
class ClearMyDms(
    lightbulb.SlashCommand,
    name="clear-my-dms",
    description="Delete this bot's past messages from this private DM",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        user_id = _as_int(ctx.user.id)
        channel_id = _as_int(ctx.channel_id)
        if (
            user_id is None or channel_id is None
            or not await _requester_dm(ctx, bot, user_id=user_id, channel_id=channel_id)
        ):
            await ctx.respond(
                "Use `/clear-my-dms` only in your one-to-one DM with WUBOT.",
                flags=hikari.MessageFlag.EPHEMERAL,
            )
            return

        action_id = uuid.uuid4().hex
        await insert_state(mongo, {
            "_id": action_id,
            "type": STATE_TYPE,
            "status": "pending",
            "user_id": user_id,
            "channel_id": channel_id,
            "cutoff_id": 0,
        }, ttl=STATE_TTL)
        await ctx.respond(components=_confirmation(action_id))
        confirmation = await ctx.interaction.fetch_initial_response()
        await update_state(
            mongo,
            {"_id": action_id, "type": STATE_TYPE, "status": "pending"},
            {"$set": {"cutoff_id": int(confirmation.id)}},
        )


@register_action("clear_my_dms_confirm", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def clear_my_dms_confirm(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    user_id = _as_int(ctx.user.id)
    channel_id = _as_int(ctx.channel_id)
    if (
        user_id is None or channel_id is None
        or not await _requester_dm(ctx, bot, user_id=user_id, channel_id=channel_id)
    ):
        await ctx.respond("This confirmation is only valid in its original private DM.", ephemeral=True)
        return
    claimed = await _claim(
        mongo, action_id=action_id, user_id=user_id, channel_id=channel_id
    )
    if claimed is None:
        await ctx.respond("This clear request was cancelled, expired, or is already running.", ephemeral=True)
        return

    cutoff_id = _as_int(claimed.get("cutoff_id"))
    if cutoff_id is None:
        await ctx.respond("The confirmation was not ready. Run `/clear-my-dms` again.", ephemeral=True)
        return
    audit_id = action_id[:8]
    _log.info("clear-my-dms purge started action=%s", audit_id)
    try:
        stopped, outcome = await todo.clear_dm_history_through(
            mongo,
            user_id=user_id,
            channel_id=channel_id,
            cutoff_id=cutoff_id,
            purge=lambda: _delete_through_cutoff(
                bot, channel_id=channel_id, cutoff_id=cutoff_id
            ),
        )
    except _PurgeFailure as exc:
        _log.warning(
            "clear-my-dms purge failed action=%s deleted=%s error=%s",
            audit_id, exc.deleted, type(exc.cause).__name__,
        )
        await mongo.component_state.update_one(
            {"_id": action_id, "status": "running"},
            {"$set": {
                "status": "failed",
                "error": type(exc).__name__,
                "deleted_count": exc.deleted,
            }},
        )
        await _temporary_receipt(
            bot, channel_id,
            f"The clear stopped after deleting {exc.deleted} WUBOT-authored message{'s' if exc.deleted != 1 else ''}. Run `/clear-my-dms` again to finish the remaining history.",
        )
        return
    if not stopped:
        _log.warning("clear-my-dms purge stopped before deletion action=%s", audit_id)
        await mongo.component_state.update_one(
            {"_id": action_id, "status": "running"},
            {"$set": {"status": "failed"}},
        )
        await _temporary_receipt(
            bot, channel_id,
            "I could not safely stop the active `/todo` panel, so no messages were deleted.",
        )
        return
    deleted = outcome
    _log.info("clear-my-dms purge completed action=%s deleted=%s", audit_id, deleted)
    await mongo.component_state.update_one(
        {"_id": action_id, "status": "running"},
        {"$set": {"status": "complete", "deleted_count": deleted}},
    )
    await _temporary_receipt(
        bot,
        channel_id,
        f"Deleted {deleted} WUBOT-authored message{'s' if deleted != 1 else ''} from this DM. Your messages were kept.",
    )


@register_action("clear_my_dms_cancel", no_return=True, preload_state=False)
@lightbulb.di.with_di
async def clear_my_dms_cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    user_id = _as_int(ctx.user.id)
    channel_id = _as_int(ctx.channel_id)
    if (
        user_id is None or channel_id is None
        or not await _requester_dm(ctx, bot, user_id=user_id, channel_id=channel_id)
    ):
        await ctx.respond("This confirmation is only valid in its original private DM.", ephemeral=True)
        return
    if await _cancel(mongo, action_id=action_id, user_id=user_id, channel_id=channel_id):
        await ctx.respond("No messages were deleted.", ephemeral=True)
    else:
        await ctx.respond("This clear request was already cancelled, expired, or is running.", ephemeral=True)
