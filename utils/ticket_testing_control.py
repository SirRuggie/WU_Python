"""Administrator controls and explicit opt-in entry for ticket exercises."""
from __future__ import annotations

from datetime import datetime, timezone
import uuid
import asyncio
from functools import wraps

import hikari

from extensions.commands.tickets import perms, testing_service, thread_service
from utils.ticket_testing_context import test_dependencies

# One bot process owns these channels. Serialize setup and permission changes;
# durable topic markers let a restarted process recover an uncertain create.
WINDOW_LOCK = asyncio.Lock()


def serialized_window_change(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with WINDOW_LOCK:
            return await function(*args, **kwargs)
    return wrapped


PARENTS_ID = "test_parents"
TEST_ACCESS = (hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY |
               hikari.Permissions.SEND_MESSAGES | hikari.Permissions.SEND_MESSAGES_IN_THREADS)


def _member(ctx):
    return getattr(ctx, "member", None) or getattr(ctx.interaction, "member", None)


def _guild(ctx):
    return int(getattr(ctx, "guild_id", None) or getattr(ctx.interaction, "guild_id", 0) or 0)


async def _admin(ctx, mongo):
    if not await perms.is_target_admin(_member(ctx), mongo):
        raise ValueError("Administrator permission is required in the ticket server.")


async def _overwrites(bot, guild_id, window):
    me = bot.get_me() if callable(getattr(bot, "get_me", None)) else None
    if me is None:
        me = await bot.rest.fetch_my_user()
    result = [
        hikari.PermissionOverwrite(id=guild_id, type=hikari.PermissionOverwriteType.ROLE,
                                   deny=TEST_ACCESS),
        hikari.PermissionOverwrite(id=me.id, type=hikari.PermissionOverwriteType.MEMBER,
                                   allow=TEST_ACCESS | hikari.Permissions.MANAGE_THREADS |
                                   hikari.Permissions.CREATE_PUBLIC_THREADS | hikari.Permissions.CREATE_PRIVATE_THREADS |
                                   hikari.Permissions.MANAGE_MESSAGES),
    ]
    if window:
        for user_id in window.get("allowed_user_ids", ()):
            if int(user_id) != int(me.id):
                result.append(hikari.PermissionOverwrite(id=int(user_id), type=hikari.PermissionOverwriteType.MEMBER, allow=TEST_ACCESS))
        for role_id in window.get("allowed_role_ids", ()):
            if int(role_id) == guild_id:
                raise ValueError("Choose a specific tester role; @everyone cannot be allowlisted.")
            result.append(hikari.PermissionOverwrite(id=int(role_id), type=hikari.PermissionOverwriteType.ROLE, allow=TEST_ACCESS))
    return result


async def sync_parent_access(bot, scoped, window=None):
    """Only rewrite permission overwrites on durable, bot-owned test parents."""
    row = await scoped.ticket_automation_state.find_one({"_id": PARENTS_ID, "mode": "test"})
    if not row:
        return
    guild_id = int(row["guild_id"])
    overwrites = await _overwrites(bot, guild_id, window)
    for field in ("candidate_parent_id", "staff_parent_id"):
        if not row.get(field):
            continue
        channel = await bot.rest.fetch_channel(int(row[field]))
        if int(channel.guild_id) != guild_id or getattr(channel, "topic", None) != row["marker"]:
            raise ValueError("A testing channel changed ownership; an administrator must review it.")
        await bot.rest.edit_channel(channel.id, permission_overwrites=overwrites,
                                    reason="Update isolated ticket testing access")


async def _ensure_parents(bot, scoped, guild_id):
    collection = scoped.ticket_automation_state
    await collection.update_one({"_id": PARENTS_ID}, {"$setOnInsert": {
        "mode": "test", "guild_id": guild_id,
        "marker": "WU isolated ticket testing " + uuid.uuid4().hex,
    }}, upsert=True)
    row = await collection.find_one({"_id": PARENTS_ID})
    if row.get("mode") != "test" or int(row.get("guild_id", 0)) != guild_id:
        raise ValueError("Testing channels are bound to a different server.")
    for field, name in (("candidate_parent_id", "ticket-test-applicants"), ("staff_parent_id", "ticket-test-staff")):
        if row.get(field):
            channel = await bot.rest.fetch_channel(int(row[field]))
            if int(channel.guild_id) != guild_id or channel.topic != row["marker"]:
                raise ValueError("A testing channel changed ownership; an administrator must review it.")
            continue
        # Recover a Discord create whose response was lost, using our durable
        # marker rather than claiming a similarly named channel.
        channels = await bot.rest.fetch_guild_channels(guild_id)
        matches = [c for c in channels if getattr(c, "topic", None) == row["marker"] and c.name == name]
        if len(matches) > 1:
            raise ValueError("Duplicate testing channels need administrator review.")
        channel = matches[0] if matches else await bot.rest.create_guild_text_channel(
            guild_id, name, topic=row["marker"], permission_overwrites=await _overwrites(bot, guild_id, None),
            reason="Create an isolated ticket testing space",
        )
        row[field] = int(channel.id)
        await collection.update_one({"_id": PARENTS_ID, "marker": row["marker"]}, {"$set": {field: int(channel.id)}})
    await scoped.ticket_setup.update_one({"_id": "config"}, {"$set": {
        "mode": "test", "ticket_target_guild_id": guild_id,
        "main_candidate_parent": row["candidate_parent_id"], "fwa_candidate_parent": row["candidate_parent_id"],
        "main_staff_parent": row["staff_parent_id"], "fwa_staff_parent": row["staff_parent_id"],
    }}, upsert=True)
    return row


@serialized_window_change
async def start_window(bot, mongo, ctx, duration_minutes, cleanup_minutes):
    await _admin(ctx, mongo)
    if not 1 <= int(duration_minutes) <= 1440 or not 0 <= int(cleanup_minutes) <= 10080:
        raise ValueError("Use 1–1,440 minutes for the window and 0–10,080 minutes for cleanup.")
    scoped = testing_service.test_mongo(mongo)
    if await testing_service.active_window(scoped):
        raise ValueError("A test window is already open. End it before starting another.")
    await testing_service.snapshot_ticket_config(mongo, scoped)
    await _ensure_parents(bot, scoped, _guild(ctx))
    window = await testing_service.open_window(scoped, guild_id=_guild(ctx), actor_id=int(ctx.user.id),
        duration_minutes=int(duration_minutes), cleanup_minutes=int(cleanup_minutes),
        allowed_user_ids=[int(ctx.user.id)], allow_admins=True)
    try:
        await sync_parent_access(bot, scoped, window)
    except Exception:
        # A partially configured window must never authorize ticket creation.
        await scoped.ticket_automation_state.update_one(
            {"_id": testing_service.WINDOW_ID, "generation": window["generation"]},
            {"$set": {"expires_at": datetime.now(timezone.utc)}})
        raise
    return window


@serialized_window_change
async def update_access(bot, mongo, ctx, *, user_ids=None, role_ids=None, allow_admins=None, add_self=False):
    await _admin(ctx, mongo)
    scoped = testing_service.test_mongo(mongo)
    window = await testing_service.active_window(scoped)
    if not window or int(window["guild_id"]) != _guild(ctx):
        raise ValueError("Open a test window first.")
    fields = {}
    if user_ids is not None:
        ids = sorted({int(value) for value in user_ids})
        for uid in ids:
            await bot.rest.fetch_member(_guild(ctx), uid)
        fields["allowed_user_ids"] = ids
    if add_self:
        fields["allowed_user_ids"] = sorted(set(fields.get("allowed_user_ids", window.get("allowed_user_ids", []))) | {int(ctx.user.id)})
    if role_ids is not None:
        ids = sorted({int(value) for value in role_ids})
        available = {int(role.id) for role in await bot.rest.fetch_roles(_guild(ctx))}
        if _guild(ctx) in ids or not set(ids).issubset(available):
            raise ValueError("Select existing tester roles; @everyone is not permitted.")
        fields["allowed_role_ids"] = ids
    if allow_admins is not None:
        fields["allow_admins"] = bool(allow_admins)
    result = await scoped.ticket_automation_state.update_one(
        {"_id": testing_service.WINDOW_ID, "mode": "test", "opened_at": window["opened_at"]}, {"$set": fields})
    if not result.matched_count:
        raise ValueError("The test window changed. Reopen the testing panel.")
    window.update(fields)
    await sync_parent_access(bot, scoped, window)
    return window


@serialized_window_change
async def end_window(bot, mongo, ctx):
    await _admin(ctx, mongo)
    scoped = testing_service.test_mongo(mongo)
    now = datetime.now(timezone.utc)
    await scoped.ticket_automation_state.update_one(
        {"_id": testing_service.WINDOW_ID, "mode": "test", "guild_id": _guild(ctx)},
        {"$set": {"expires_at": now, "ended_by": int(ctx.user.id)}})
    await sync_parent_access(bot, scoped, None)
    return await scoped.ticket_automation_state.find_one({"_id": testing_service.WINDOW_ID})


async def require_test_access(ctx, mongo, bot):
    scoped = testing_service.test_mongo(mongo)
    window = await testing_service.active_window(scoped)
    if not window or int(window.get("guild_id", 0)) != _guild(ctx):
        raise ValueError("This test window has ended. Ask an administrator to open a new one.")
    member = await bot.rest.fetch_member(_guild(ctx), int(ctx.user.id))
    # Gateway interaction permissions include Administrator; REST members do
    # not. Resolve current role permissions so removed access fails closed.
    roles = await bot.rest.fetch_roles(_guild(ctx))
    held = {int(role) for role in member.role_ids} | {_guild(ctx)}
    permissions = hikari.Permissions.NONE
    for role in roles:
        if int(role.id) in held:
            permissions |= role.permissions
    allowed = testing_service.user_allowed(window, user_id=int(ctx.user.id), role_ids=member.role_ids,
        is_admin=bool(permissions & hikari.Permissions.ADMINISTRATOR))
    if not allowed:
        raise ValueError("You are not on this test window’s allowlist. Ask an administrator to add you.")
    return scoped, window


async def open_test_ticket(ctx, bot, mongo, ticket_type):
    await ctx.defer(ephemeral=True)
    if ticket_type not in {"main", "fwa"}:
        raise ValueError("Choose Main or FWA.")
    scoped, window = await require_test_access(ctx, mongo, bot)
    claim = await testing_service.claim_test_slot(scoped, guild_id=_guild(ctx),
        user_id=int(ctx.user.id), ticket_type=ticket_type)
    if not claim.won:
        location = int(claim.slot.get("location_id") or 0)
        text = (f"Your test ticket is already open: <#{location}>." if location else
                "Your test ticket is being prepared. Try again shortly.")
        await ctx.interaction.edit_initial_response(content=text, user_mentions=False, role_mentions=False)
        return
    config = await scoped.ticket_setup.find_one({"_id": "config"}) or {}
    async with test_dependencies(scoped, bot, ctx) as (test_ctx, test_bot):
        result = await thread_service.create_live_thread_ticket(
            bot=test_bot, mongo=scoped, guild_id=_guild(ctx), user_id=int(ctx.user.id),
            username=ctx.user.username, display_name=getattr(_member(ctx), "display_name", None),
            ticket_type=ticket_type, config=config, open_slot_claim=claim)
        location = result.ticket.get("location") or {}
        channel_id = int(location.get("id") or result.ticket["channel_id"])
        await test_ctx.interaction.edit_initial_response(
            content=f"**{testing_service.number_label(result.ticket['ticket_number'])}** is ready: <#{channel_id}>. This test does not affect live tickets.",
            user_mentions=False, role_mentions=False, mentions_everyone=False)
