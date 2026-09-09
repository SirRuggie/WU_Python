"""Ticket panel interaction handlers.

New tickets are thread-only. Channel-based tickets are accepted solely as
read-only inputs by the explicit legacy migration command.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import re
from typing import Dict

import hikari
import lightbulb
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from extensions.commands.tickets import loader, thread_intake_ready, ticket
from extensions.commands.tickets import resolve
from extensions.commands.tickets import store
from extensions.commands.tickets import thread_service
from extensions.commands import ticket_runtime
from extensions.components import register_action
from utils.mongo import MongoClient


COOLDOWN_DURATION = 30
RATE_LIMIT_BACKOFF = 60
COOLDOWN_CLEANUP_INTERVAL = 300
TICKET_BOOTSTRAP_OWNER_ID = 505227988229554179

user_cooldowns: Dict[int, datetime] = {}
last_cleanup = datetime.now(timezone.utc)


def cleanup_expired_cooldowns() -> None:
    global last_cleanup
    now = datetime.now(timezone.utc)
    if (now - last_cleanup).total_seconds() < COOLDOWN_CLEANUP_INTERVAL:
        return
    expired = [
        user_id
        for user_id, started_at in user_cooldowns.items()
        if (now - started_at).total_seconds() > COOLDOWN_DURATION
    ]
    for user_id in expired:
        user_cooldowns.pop(user_id, None)
    last_cleanup = now


def _ticket_location(ticket: dict) -> int:
    location = ticket.get("location") or {}
    return int(location.get("id") or ticket.get("channel_id"))


async def _cancel_untouched_slot(
    mongo: MongoClient,
    claim: ticket_runtime.SlotClaim,
) -> bool:
    return await ticket_runtime.cancel_open_slot(
        mongo,
        slot_id=str(claim.slot["_id"]),
        owner_token=str(claim.owner_token),
        workflow_id=str(claim.slot["workflow_id"]),
    )


def _can_configure_thread_target(*, actor_id: int, guild_id: int, config: dict) -> bool:
    """Restrict the one-time global binding while retaining target-admin setup."""
    target_guild_id = store.as_int(config.get("ticket_target_guild_id"))
    if target_guild_id:
        return target_guild_id == int(guild_id)
    return int(actor_id) == TICKET_BOOTSTRAP_OWNER_ID


async def _recruiter_role_name(
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    *,
    guild_id: int,
    ticket_type: str,
) -> str | None:
    """Look up the configured recruiter role's display name, no mention."""
    try:
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    except Exception:
        return None
    role_id = store.as_int(config.get(f"{ticket_type}_thread_recruiter_role"))
    if not role_id:
        return None
    cache = getattr(bot, "cache", None)
    role = cache.get_role(role_id) if cache is not None else None
    if role is None:
        try:
            role = await bot.rest.fetch_role(int(guild_id), role_id)
        except Exception:
            return None
    name = getattr(role, "name", None)
    return str(name) if name else None


async def _release_slot_for_missing_thread(mongo: MongoClient, ticket_id) -> None:
    """Free a thread_missing ticket's open slot so the applicant can start fresh."""
    try:
        await ticket_runtime.mark_slot_release_pending_for_missing_thread(
            mongo, ticket_id=ticket_id,
        )
    except ticket_runtime.SlotConflict:
        return
    except Exception as error:
        print(
            "[Tickets] v2_thread_missing_slot_mark_failed "
            f"ticket={ticket_id} error={type(error).__name__}"
        )
        return
    try:
        await ticket_runtime.release_open_slot_for_missing_thread(
            mongo, ticket_id=ticket_id,
        )
    except Exception as error:
        print(
            "[Tickets] v2_thread_missing_slot_release_failed "
            f"ticket={ticket_id} error={type(error).__name__}"
        )


_PLAYER_TAG_RE = re.compile(r"(?<![A-Z0-9])#[A-Z0-9]{3,9}(?![A-Z0-9])", re.IGNORECASE)


def _candidate_message_snapshot(message: hikari.Message) -> str:
    content = (message.content or "").strip()
    attachments = [str(getattr(item, "filename", "attachment")) for item in message.attachments]
    if attachments:
        note = "Attachments: " + ", ".join(attachments)
        content = f"{content}\n{note}".strip()
    return content


@loader.listener(hikari.GuildMessageCreateEvent)
@lightbulb.di.with_di
async def capture_candidate_thread_activity(
    event: hikari.GuildMessageCreateEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Durably capture applicant answers and any `#TAG`-shaped tokens they type.

    Typed tags are unverified — anyone can type any tag — so they are stored
    as ``mentioned_tags``, a search/display hint only. They never join the
    verified ``player_tags`` identity used for flag and blacklist matching.
    """
    if not event.is_human:
        return
    ticket = await store.find_by_location(mongo, int(event.channel_id))
    if ticket is None or ticket.get("status") != "open":
        return
    if _ticket_location(ticket) != int(event.channel_id):
        return
    if int(ticket.get("user_id") or 0) != int(event.author_id):
        return
    snapshot = _candidate_message_snapshot(event.message)
    if not snapshot:
        return
    tags = sorted({match.upper() for match in _PLAYER_TAG_RE.findall(snapshot)})
    result = await store.append_candidate_activity(
        mongo,
        ticket["_id"],
        message_id=int(event.message_id),
        author_id=int(event.author_id),
        content=snapshot,
        mentioned_tags=tags,
        occurred_at=event.message.timestamp,
    )
    if result.won and result.reason != "already recorded" and result.doc is not None:
        # A candidate's own message never moves the console's chart counts
        # or the open-ticket set, so it must not force a full hub redraw --
        # see console._chart_signature.
        await thread_service.notify_console_after_change(
            bot, mongo, result.doc, reason="candidate activity", force=False,
        )


@loader.listener(hikari.GuildThreadDeleteEvent)
@lightbulb.di.with_di
async def handle_ticket_thread_deleted(
    event: hikari.GuildThreadDeleteEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Record a deleted candidate/staff thread on its ticket.

    `thread_missing` is a field, not a status: the ticket's `status` still
    reflects the recruiter's decision (or "open"). This only records that
    one Discord thread of the pair is gone, so re-click/My ticket can free
    the applicant's slot instead of pointing at a dead thread forever, and
    resolution effects that need that thread skip instead of retrying.
    """
    ticket = await store.find_by_location(mongo, int(event.thread_id))
    if ticket is None:
        return
    location = ticket.get("location") or {}
    candidate_id = store.as_int(location.get("id") or ticket.get("channel_id"))
    role = "candidate" if candidate_id == int(event.thread_id) else "staff"
    try:
        await store.mark_thread_missing(mongo, ticket["_id"], thread_role=role)
    except Exception as error:
        print(
            "[Tickets] v2_thread_deleted_mark_failed "
            f"ticket={ticket.get('_id')} thread={event.thread_id} "
            f"error={type(error).__name__}"
        )
        return
    if role == "candidate" and ticket.get("status") == "open":
        await _release_slot_for_missing_thread(mongo, ticket["_id"])
    await thread_service.notify_console_after_change(
        bot, mongo, ticket, reason="ticket thread removed"
    )


@register_action(
    "ticket_v2_create", opens_modal=True, no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def handle_create_ticket(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    """Create or safely resume a private candidate/public staff thread pair."""
    await ctx.defer(ephemeral=True)

    if not thread_intake_ready():
        await ctx.interaction.edit_initial_response(
            content=(
                "❌ Thread ticketing is still completing its safety checks. "
                "Nothing was created; try again shortly."
            )
        )
        return

    intake_surface, separator, ticket_type = action_id.partition(":")
    if separator != ":" or intake_surface not in {"pilot", "public"}:
        await ctx.interaction.edit_initial_response(
            content="❌ This ticket panel is unavailable. Ask staff for the current panel."
        )
        return
    if ticket_type not in {"main", "fwa"}:
        await ctx.interaction.edit_initial_response(
            content="❌ That ticket type is not available."
        )
        return

    interaction_message = getattr(ctx.interaction, "message", None)
    message_id = store.as_int(getattr(interaction_message, "id", 0))
    member_roles = tuple(
        int(role_id)
        for role_id in (getattr(getattr(ctx, "member", None), "role_ids", ()) or ())
    )
    try:
        route = await ticket_runtime.route_public_intake(
            mongo,
            requested_route=ticket_runtime.ROUTE_THREAD,
            guild_id=store.as_int(ctx.guild_id),
            channel_id=store.as_int(ctx.channel_id),
            message_id=message_id,
            user_id=int(ctx.user.id),
            member_role_ids=member_roles,
            ticket_type=ticket_type,
        )
    except Exception as error:
        print(
            "[Tickets] v2_intake_gate_failed "
            f"guild={ctx.guild_id} channel={ctx.channel_id} "
            f"message={message_id} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Thread ticketing is temporarily unavailable. Nothing was created."
        )
        return
    if not route.allowed or route.route != ticket_runtime.ROUTE_THREAD:
        message = (
            "❌ This pilot panel is not active for you here. "
            "Use the current public ticket panel or contact a recruiter."
            if intake_surface == "pilot"
            else "❌ This public ticket panel is not active. Use the current panel or contact a recruiter."
        )
        await ctx.interaction.edit_initial_response(content=message)
        return

    cleanup_expired_cooldowns()

    now = datetime.now(timezone.utc)
    user_id = int(ctx.user.id)
    previous = user_cooldowns.get(user_id)
    if previous is not None:
        elapsed = (now - previous).total_seconds()
        if elapsed < COOLDOWN_DURATION:
            await ctx.interaction.edit_initial_response(
                content=f"⏳ Please wait {int(COOLDOWN_DURATION - elapsed)} seconds before trying again."
            )
            return
    await ctx.interaction.edit_initial_response(content="🎫 Creating your ticket…")
    workflow_id = f"thread:{user_id}:{ticket_type}"
    try:
        slot_claim = await ticket_runtime.claim_open_slot(
            mongo,
            user_id=user_id,
            ticket_type=ticket_type,
            route=ticket_runtime.ROUTE_THREAD,
            guild_id=int(ctx.guild_id),
            workflow_id=workflow_id,
            rollout_revision=int(route.revision),
            now=now,
            lease_seconds=600,
        )
        if (
            not slot_claim.won
            and slot_claim.slot.get("state") == ticket_runtime.SLOT_RESERVED
            and slot_claim.slot.get("route") == ticket_runtime.ROUTE_THREAD
            and store.as_int(slot_claim.slot.get("guild_id")) == int(ctx.guild_id)
            and str(slot_claim.slot.get("workflow_id") or "") == workflow_id
        ):
            slot_claim = await ticket_runtime.resume_open_slot(
                mongo,
                slot_id=str(slot_claim.slot["_id"]),
                workflow_id=workflow_id,
                route=ticket_runtime.ROUTE_THREAD,
                guild_id=int(ctx.guild_id),
                now=now,
                lease_seconds=600,
            )
    except Exception as error:
        print(
            "[Tickets] v2_slot_claim_failed "
            f"guild={ctx.guild_id} user={user_id} type={ticket_type} "
            f"error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Thread ticketing is temporarily unavailable. Nothing was created."
        )
        return
    if not slot_claim.won:
        location_id = store.as_int(slot_claim.slot.get("location_id"))
        if slot_claim.slot.get("state") == ticket_runtime.SLOT_CLEANUP_REQUIRED:
            sentences = ["⚠️ A recruiter still needs to finish your earlier ticket."]
            if location_id:
                sentences.append(f"Jump to it here: <#{location_id}>.")
            role_name = await _recruiter_role_name(
                bot, mongo, guild_id=store.as_int(ctx.guild_id), ticket_type=ticket_type
            )
            sentences.append(
                f"Ask the {role_name} role if you need an update."
                if role_name else
                "Ask a recruiter if you need an update."
            )
            message = " ".join(sentences)
        elif location_id:
            existing_ticket = await store.find_by_location(mongo, location_id)
            if existing_ticket is not None and (
                existing_ticket.get("thread_missing") or {}
            ).get("thread_role") == "candidate":
                await _release_slot_for_missing_thread(mongo, existing_ticket["_id"])
                message = (
                    "⚠️ Your earlier ticket's thread was removed. "
                    "Press the button again to start a new one."
                )
            else:
                if existing_ticket is not None:
                    try:
                        await thread_service.ensure_candidate_thread_access(
                            bot.rest, existing_ticket, user_id=user_id,
                        )
                    except Exception as error:
                        print(
                            "[Tickets] v2_reclick_reaccess_failed "
                            f"guild={ctx.guild_id} user={user_id} type={ticket_type} "
                            f"error={type(error).__name__}"
                        )
                message = f"✅ You already have an open {ticket_type.upper()} ticket: <#{location_id}>"
        else:
            message = "⏳ Your ticket is already being created. Please try again shortly."
        await ctx.interaction.edit_initial_response(content=message)
        return
    user_cooldowns[user_id] = now
    try:
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    except Exception as error:
        user_cooldowns.pop(user_id, None)
        try:
            await _cancel_untouched_slot(mongo, slot_claim)
        except Exception:
            print(
                "[Tickets] pilot_slot_cancel_failed "
                f"guild={ctx.guild_id} user={user_id} type={ticket_type}"
            )
        print(
            "[Tickets] pilot_config_read_failed "
            f"guild={ctx.guild_id} user={user_id} type={ticket_type} "
            f"error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content="❌ Pilot ticketing is temporarily unavailable. Nothing was created."
        )
        return
    display_name = getattr(ctx.member, "display_name", None) if getattr(ctx, "member", None) else None
    try:
        result = await thread_service.create_live_thread_ticket(
            bot=bot,
            mongo=mongo,
            guild_id=int(ctx.guild_id),
            user_id=user_id,
            username=ctx.user.username,
            display_name=display_name,
            ticket_type=ticket_type,
            config=config,
            open_slot_claim=slot_claim,
        )
    except thread_service.ThreadCreationBusy:
        user_cooldowns.pop(user_id, None)
        await ctx.interaction.edit_initial_response(
            content="⏳ Your ticket is already being created. Please try again in a moment."
        )
        return
    except thread_service.ThreadConfigurationError as error:
        user_cooldowns.pop(user_id, None)
        await ctx.interaction.edit_initial_response(
            content=f"❌ Thread ticketing is not ready: {error}. Please contact an administrator."
        )
        return
    except hikari.RateLimitTooLongError:
        user_cooldowns[user_id] = now + timedelta(seconds=RATE_LIMIT_BACKOFF)
        await ctx.interaction.edit_initial_response(
            content="⏰ Discord is rate-limiting ticket creation. Please try again in a few minutes."
        )
        return
    except Exception as error:
        print(
            "[Tickets] thread_creation_failed "
            f"guild={ctx.guild_id} user={user_id} type={ticket_type} error={type(error).__name__}"
        )
        await ctx.interaction.edit_initial_response(
            content=(
                "❌ Your ticket could not be completed safely. The attempt was saved and can resume "
                "without creating duplicates. Please try again or contact an administrator."
            )
        )
        return

    location_id = _ticket_location(result.ticket)
    wording = "already open" if result.resumed else "created"
    delivery_note = (
        " Setup messages are retrying automatically."
        if result.delivery_pending
        else ""
    )
    await ctx.interaction.edit_initial_response(
        content=(
            f"✅ Your {ticket_type.upper()} ticket is {wording}: <#{location_id}>"
            f"{delivery_note}"
        )
    )


MAX_MY_TICKET_HISTORY = 5


def _my_ticket_history_line(prior: dict) -> str:
    """One "My ticket" history row. Applicant-facing only: no flags or notes."""
    kind = "FWA" if str(prior.get("ticket_type") or "").casefold() == "fwa" else "Main"
    try:
        number = int(prior.get("ticket_number"))
    except (TypeError, ValueError):
        number = "?"
    status = str(prior.get("status") or "unknown").replace("_", " ").title()
    at = (
        prior.get("approved_at")
        or prior.get("denied_at")
        or prior.get("updated_at")
        or prior.get("created_at")
    )
    line = f"{kind} #{number} · {status} · {resolve.ts(at)}"
    guild_id = store.as_int(prior.get("guild_id"))
    location_id = _ticket_location(prior)
    if guild_id and location_id:
        line += f" · https://discord.com/channels/{guild_id}/{location_id}"
    return line


@register_action(
    "ticket_v2_my_ticket", no_return=True, preload_state=False,
)
@lightbulb.di.with_di
async def handle_my_ticket(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    """Ephemeral pointer back to the applicant's own ticket.

    Never shows recruiter-only content (no flags, no staff notes) -- this is
    the applicant's own read of `store`'s applicant-facing fields only.
    """
    await ctx.defer(ephemeral=True)
    user_id = int(ctx.user.id)

    open_ticket = None
    for kind in ("main", "fwa"):
        open_ticket = await store.find_open_for_applicant(
            mongo, user_id=user_id, ticket_type=kind,
        )
        if open_ticket is not None:
            break

    if open_ticket is not None and (
        open_ticket.get("thread_missing") or {}
    ).get("thread_role") == "candidate":
        await _release_slot_for_missing_thread(mongo, open_ticket["_id"])
        await ctx.interaction.edit_initial_response(
            content=(
                "⚠️ Your earlier ticket's thread was removed. "
                "Press Main or FWA to start a new one."
            )
        )
        return

    if open_ticket is not None:
        location_id = _ticket_location(open_ticket)
        try:
            await thread_service.ensure_candidate_thread_access(
                bot.rest, open_ticket, user_id=user_id,
            )
        except Exception as error:
            print(
                "[Tickets] v2_my_ticket_reaccess_failed "
                f"user={user_id} error={type(error).__name__}"
            )
        await ctx.interaction.edit_initial_response(
            content=f"🎟️ Your open ticket: <#{location_id}>"
        )
        return

    history = await store.history_for(
        mongo, user_id=user_id, limit=MAX_MY_TICKET_HISTORY,
    )
    if not history:
        await ctx.interaction.edit_initial_response(
            content="You have no ticket yet. Press Main or FWA to start one."
        )
        return

    lines = "\n".join(_my_ticket_history_line(prior) for prior in history)
    await ctx.interaction.edit_initial_response(
        content=f"🎟️ You have no open ticket. Earlier tickets:\n{lines}"
    )


@ticket.register()
class ConfigureThreadParents(
    lightbulb.SlashCommand,
    name="configure-threads",
    description="Configure validated candidate and recruiter thread parents (Admin only)",
):
    ticket_type = lightbulb.string(
        "type",
        "Ticket type",
        choices=[
            lightbulb.Choice(name="Main", value="main"),
            lightbulb.Choice(name="FWA", value="fwa"),
        ],
    )
    candidate_parent = lightbulb.channel(
        "candidate-parent",
        "Text channel that owns private candidate threads",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )
    staff_parent = lightbulb.channel(
        "staff-parent",
        "Recruiter-only text channel that owns staff threads",
        channel_types=[hikari.ChannelType.GUILD_TEXT],
    )
    recruiter_role = lightbulb.role("recruiter-role", "Role allowed into staff threads")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not ctx.member or not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ Administrator permission is required.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        if not _can_configure_thread_target(
            actor_id=int(ctx.user.id),
            guild_id=int(ctx.guild_id),
            config=config,
        ):
            target_guild_id = store.as_int(config.get("ticket_target_guild_id"))
            message = (
                "🛑 Ticketing is already bound to a different guild; nothing was saved."
                if target_guild_id
                else "🛑 Only the bot owner can establish the ticket guild; nothing was saved."
            )
            await ctx.respond(message, ephemeral=True)
            return
        rollout_state = await ticket_runtime.get_rollout(mongo)
        if (
            rollout_state.valid
            and rollout_state.thread_intake is not None
            and (
                rollout_state.thread_intake.guild_id != int(ctx.guild_id)
                or rollout_state.thread_intake.channel_id
                != int(self.candidate_parent.id)
            )
        ):
            await ctx.respond(
                "🛑 Candidate threads must use the bound target public-v2 channel; "
                "nothing was saved.",
                ephemeral=True,
            )
            return
        parents = thread_service.ThreadParents(
            guild_id=int(ctx.guild_id),
            candidate_parent_id=int(self.candidate_parent.id),
            staff_parent_id=int(self.staff_parent.id),
            recruiter_role_id=int(self.recruiter_role.id),
        )
        me = bot.get_me()
        if me is None:
            await ctx.respond("❌ Bot identity is unavailable; nothing was saved.", ephemeral=True)
            return
        try:
            await thread_service.validate_thread_parents(
                bot.rest, parents, bot_user_id=int(me.id)
            )
        except thread_service.ThreadConfigurationError as error:
            await ctx.respond(f"❌ Nothing was saved: {error}.", ephemeral=True)
            return
        prefix = self.ticket_type
        try:
            saved = await mongo.ticket_setup.find_one_and_update(
                {
                    "_id": "config",
                    "$or": [
                        {"ticket_target_guild_id": {"$exists": False}},
                        {"ticket_target_guild_id": int(ctx.guild_id)},
                    ],
                },
                {"$set": {
                    "ticket_target_guild_id": int(ctx.guild_id),
                    f"{prefix}_candidate_parent": parents.candidate_parent_id,
                    f"{prefix}_staff_parent": parents.staff_parent_id,
                    f"{prefix}_thread_recruiter_role": parents.recruiter_role_id,
                }},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            saved = None
        if saved is None:
            await ctx.respond(
                "🛑 Ticketing is already bound to a different guild; nothing was saved.",
                ephemeral=True,
            )
            return
        await ctx.respond(
            f"✅ {prefix.upper()} thread parents validated and saved.", ephemeral=True
        )


@ticket.register()
class InspectThreadConfiguration(
    lightbulb.SlashCommand,
    name="thread-config",
    description="Inspect and revalidate thread ticket configuration (Admin only)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not ctx.member or not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ Administrator permission is required.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        if int(config.get("ticket_target_guild_id") or 0) != int(ctx.guild_id):
            await ctx.respond(
                "🛑 Thread configuration is private to the configured ticket guild.",
                ephemeral=True,
            )
            return
        me = bot.get_me()
        if me is None:
            await ctx.respond("❌ Bot identity is unavailable.", ephemeral=True)
            return
        rows = []
        for ticket_type in ("main", "fwa"):
            try:
                parents = thread_service.parents_from_config(
                    config, int(ctx.guild_id), ticket_type
                )
                await thread_service.validate_thread_parents(
                    bot.rest, parents, bot_user_id=int(me.id)
                )
                rows.append(
                    f"✅ **{ticket_type.upper()}** — candidate <#{parents.candidate_parent_id}>, "
                    f"staff <#{parents.staff_parent_id}>, recruiter <@&{parents.recruiter_role_id}>"
                )
            except thread_service.ThreadConfigurationError as error:
                rows.append(f"❌ **{ticket_type.upper()}** — {error}")
        await ctx.respond("\n".join(rows), ephemeral=True)
