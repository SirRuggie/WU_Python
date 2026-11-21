"""Reconcile explicit private staff-thread invites after role changes/restarts.

No historical public pair is converted. The existing maintenance task pages
through marked private pairs, including closed history, so role loss while the
bot was offline does not permanently retain an old invite.
"""
import logging

import hikari

from . import perms, store, testing_service, thread_service

_log = logging.getLogger(__name__)
_after = ""


async def sweep(bot, mongo):
    global _after
    if testing_service.is_test_scope(mongo):
        return
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    guild_id = int(config.get("ticket_target_guild_id") or 0)
    me = bot.get_me()
    if not guild_id or me is None:
        return
    rows = await store.private_staff_tickets(mongo, guild_id=guild_id, after=_after, limit=5)
    members = await thread_service.staff_member_snapshot(bot.rest, guild_id) if rows else []
    for row in rows[:5]:
        try:
            thread_id = int((row.get("location") or {}).get("staff_space_id") or 0)
            if not thread_id:
                continue
            channel = await bot.rest.fetch_channel(thread_id)
            if (int(channel.guild_id) != guild_id
                    or channel.type != hikari.ChannelType.GUILD_PRIVATE_THREAD):
                continue
            # Recheck canonical ownership immediately before transport calls.
            current = await store.find_one(mongo, {
                **store.RUNTIME_FILTER, "_id": row["_id"], "guild_id": guild_id,
                "staff_thread_private": True, "location.staff_space_id": thread_id,
            })
            if current is None:
                continue
            for channel_id, preserved in (
                (thread_id, ()),
                (int((current.get("location") or {}).get("id") or 0), (current["user_id"],)),
            ):
                if not channel_id:
                    continue
                target = await bot.rest.fetch_channel(channel_id)
                if (target.type != hikari.ChannelType.GUILD_PRIVATE_THREAD or int(target.guild_id) != guild_id
                        or int(getattr(target, "owner_id", 0)) != int(me.id)):
                    continue
                await thread_service.sync_private_staff_members(
                    bot.rest, guild_id=guild_id, thread_id=channel_id,
                    role_ids=perms.ticket_type_role_ids(config, current["ticket_type"]),
                    bot_user_id=int(me.id), preserve_member_ids=preserved, members=members,
                )
        except hikari.NotFoundError:
            # Deleted threads have no membership to reconcile.
            continue
        except Exception:
            _log.exception("Private staff membership reconciliation failed ticket=%s", row["_id"])
    _after = str(rows[4]["_id"]) if len(rows) > 5 else ""


async def member_changed(bot, mongo, member):
    """Prompt role-event reconciliation; bounded maintenance covers missed events."""
    if testing_service.is_test_scope(mongo):
        return
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    guild_id = int(config.get("ticket_target_guild_id") or 0)
    me = bot.get_me()
    if not guild_id or int(member.guild_id) != guild_id or me is None or int(member.id) == int(me.id):
        return
    rows = await store.private_staff_tickets(mongo, guild_id=guild_id, limit=50)
    for row in rows[:50]:
        current = await store.find_one(mongo, {**store.RUNTIME_FILTER, "_id":row["_id"],
            "guild_id":guild_id, "staff_thread_private":True})
        if current is None:
            continue
        for field in ("staff_space_id", "id"):
            channel_id = int((current.get("location") or {}).get(field) or 0)
            if not channel_id:
                continue
            try:
                channel = await bot.rest.fetch_channel(channel_id)
                if (channel.type != hikari.ChannelType.GUILD_PRIVATE_THREAD
                        or int(channel.guild_id) != guild_id
                        or int(getattr(channel, "owner_id", 0)) != int(me.id)):
                    continue
                fresh = await bot.rest.fetch_member(guild_id, member.id)
                allowed_roles = perms.ticket_type_role_ids(config, current["ticket_type"])
                allowed = bool(allowed_roles.intersection(map(int,fresh.role_ids)))
                if field == "id" and int(member.id) == int(current["user_id"]):
                    allowed = True
                try:
                    await bot.rest.fetch_thread_member(channel_id,member.id)
                    invited = True
                except hikari.NotFoundError:
                    invited = False
                if invited and not allowed:
                    await bot.rest.remove_thread_member(channel_id,member.id)
                elif allowed and not invited:
                    # Fetch again immediately before granting a new invitation.
                    fresh = await bot.rest.fetch_member(guild_id,member.id)
                    if (allowed_roles.intersection(map(int,fresh.role_ids))
                            or (field == "id" and int(member.id) == int(current["user_id"]))):
                        await bot.rest.add_thread_member(channel_id,member.id)
            except hikari.NotFoundError:
                continue
            except Exception:
                _log.exception("Role-event private thread reconciliation failed ticket=%s", row["_id"])
