import lightbulb
import hikari
import asyncio
from datetime import datetime, timezone

loader = lightbulb.Loader()

DELETE_LOG_CHANNEL = 1392083438781337650
EDIT_LOG_CHANNEL = 1392083438781337650
MODERATION_LOG_CHANNEL = 1392083463431262349
MEMBER_JOIN_LEAVE_CHANNEL = 1392083485073604628


# -------------------- Message Deleted --------------------
@loader.listener(hikari.MessageDeleteEvent)
async def on_message_delete(event: hikari.MessageDeleteEvent) -> None:
    if not event.old_message or not event.guild_id:
        return

    msg = event.old_message
    channel_mention = f"<#{event.channel_id}>"
    author_mention = f"{msg.author.mention} (`{msg.author.username}`)"
    created_at = msg.created_at

    embed = hikari.Embed(
        title="🗑️ Message deleted",
        color=0xFF5555
    )
    embed.add_field(name="Channel", value=channel_mention, inline=False)
    embed.add_field(name="Message ID", value=str(msg.id), inline=False)
    embed.add_field(name="Message author", value=author_mention, inline=False)
    embed.add_field(
        name="Message created",
        value=created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else "Unknown",
        inline=False
    )
    embed.add_field(name="Message", value=msg.content or "*No content*", inline=False)
    embed.timestamp = created_at if created_at else datetime.now(timezone.utc)

    await event.app.rest.create_message(DELETE_LOG_CHANNEL, embed=embed)


# -------------------- Message Edited --------------------
@loader.listener(hikari.MessageUpdateEvent)
async def on_message_edit(event: hikari.MessageUpdateEvent) -> None:
    if not event.old_message or not event.message:
        return

    old = event.old_message
    new = event.message

    if old.content == new.content:
        return

    channel_mention = f"<#{event.channel_id}>"
    author_mention = f"{new.author.mention} (`{new.author.username}`)"
    created_at = old.created_at

    embed = hikari.Embed(
        title="✏️ Message edited",
        color=0xFFFF55
    )
    embed.add_field(name="Channel", value=channel_mention, inline=False)
    embed.add_field(name="Message ID", value=str(old.id), inline=False)
    embed.add_field(name="Message author", value=author_mention, inline=False)
    embed.add_field(
        name="Message created",
        value=created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if created_at else "Unknown",
        inline=False
    )
    embed.add_field(name="Before", value=old.content or "*Empty*", inline=False)
    embed.add_field(name="After", value=new.content or "*Empty*", inline=False)
    edited_at = new.edited_timestamp
    embed.timestamp = edited_at if edited_at else datetime.now(timezone.utc)

    await event.app.rest.create_message(EDIT_LOG_CHANNEL, embed=embed)


# -------------------- Member Joined --------------------
@loader.listener(hikari.MemberCreateEvent)
async def on_member_join(event: hikari.MemberCreateEvent) -> None:
    user = event.member
    now = datetime.now(timezone.utc)
    created_at = user.created_at
    created_str = created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Calculate if account is new (less than 7 days old)
    account_age_seconds = (now.replace(tzinfo=None) - created_at.replace(tzinfo=None)).total_seconds()
    is_new = account_age_seconds < 7 * 24 * 60 * 60
    new_account_flag = "⚠️ **New Account**" if is_new else ""

    embed = hikari.Embed(
        title="📥 Member Joined",
        description=f"{user.mention} just joined the server.\n{new_account_flag}",
        color=0x00FF7F
    )

    avatar_url = user.make_avatar_url() or user.default_avatar_url
    if avatar_url:
        embed.set_thumbnail(avatar_url)

    embed.add_field(name="Account Created", value=created_str)
    embed.set_footer(text=f"User ID: {user.id}")
    embed.timestamp = now

    await event.app.rest.create_message(MEMBER_JOIN_LEAVE_CHANNEL, embed=embed)


# -------------------- Member Left --------------------
@loader.listener(hikari.MemberDeleteEvent)
async def on_member_leave(event: hikari.MemberDeleteEvent) -> None:
    user = event.user
    member = event.old_member
    now = datetime.now(timezone.utc)
    created_at = user.created_at
    created_str = created_at.strftime("%Y-%m-%d %H:%M:%S UTC")

    # Calculate if account is new (less than 7 days old)
    account_age_seconds = (now.replace(tzinfo=None) - created_at.replace(tzinfo=None)).total_seconds()
    is_new = account_age_seconds < 7 * 24 * 60 * 60
    new_account_flag = "⚠️ **New Account**" if is_new else ""

    embed = hikari.Embed(
        title="📤 Member Left",
        description=f"{user.mention} has left the server.",
        color=0xFF4500
    )

    avatar_url = user.make_avatar_url() or user.default_avatar_url
    if avatar_url:
        embed.set_thumbnail(avatar_url)

    embed.add_field(name="Account Created", value=created_str)

    if member:
        if member.joined_at:
            joined_str = member.joined_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            embed.add_field(name="Joined Server", value=joined_str)
        role_mentions = [
            f"<@&{role_id}>" for role_id in member.role_ids if role_id != event.guild_id
        ]
        roles_value = ", ".join(role_mentions) if role_mentions else "*No roles*"
        embed.add_field(name="Roles", value=roles_value, inline=False)
    else:
        embed.add_field(name="Info", value="Could not fetch roles or join date (not cached).", inline=False)

    embed.set_footer(text=f"User ID: {user.id}")
    embed.timestamp = now

    # Check if this was a kick by looking at audit logs
    try:
        audit_log = await event.app.rest.fetch_audit_log(
            event.guild_id,
            event_type=hikari.AuditLogEventType.MEMBER_KICK
        )

        # Check recent kick entries
        for entry_id, entry in audit_log.entries.items():
            if entry.target_id == user.id:
                # Check if this entry is recent (within 5 seconds)
                entry_age = (now.replace(tzinfo=None) - entry.created_at.replace(tzinfo=None)).total_seconds()
                if entry_age < 5:
                    # This was a kick, log it separately
                    await log_kick(event, user, entry, member)
                    return
    except Exception:
        pass  # If we can't fetch audit log, just log as normal leave

    await event.app.rest.create_message(MEMBER_JOIN_LEAVE_CHANNEL, embed=embed)


async def log_kick(event: hikari.MemberDeleteEvent, user: hikari.User, audit_entry, member):
    """Log a kick event separately"""
    now = datetime.now(timezone.utc)
    bot_user = await event.app.rest.fetch_my_user()

    embed = hikari.Embed(
        title="👢 User Kicked",
        color=0xFF4444,
        timestamp=now
    )
    embed.add_field(name="User", value=f"{user.username}#{user.discriminator} ({user.mention})", inline=False)
    embed.add_field(name="ID", value=str(user.id), inline=False)
    embed.add_field(name="Kicked by", value=f"{audit_entry.user.mention}", inline=False)
    embed.add_field(name="Reason", value=audit_entry.reason or "No reason provided.", inline=False)

    avatar_url = user.make_avatar_url() or user.default_avatar_url
    if avatar_url:
        embed.set_thumbnail(avatar_url)

    embed.set_footer(text=f"{bot_user.username} • {now.strftime('%m/%d/%Y %I:%M %p')}")

    await event.app.rest.create_message(MODERATION_LOG_CHANNEL, embed=embed)


# -------------------- Timeout Logging --------------------
@loader.listener(hikari.MemberUpdateEvent)
async def on_member_update(event: hikari.MemberUpdateEvent) -> None:
    old = event.old_member
    new = event.member

    if not old or not new:
        return

    # IMPORTANT: communication_disabled_until is a METHOD, not an attribute
    old_timeout = old.communication_disabled_until()
    new_timeout = new.communication_disabled_until()

    # Check for timeout changes
    if old_timeout != new_timeout:
        await handle_timeout_change(event, old, new, old_timeout, new_timeout)

    # Check for nickname changes
    elif old.nickname != new.nickname:
        await handle_nickname_change(event, old, new)


async def handle_timeout_change(event, old, new, old_timeout, new_timeout):
    """Handle timeout/mute changes"""
    now = datetime.now(timezone.utc)
    bot_user = await event.app.rest.fetch_my_user()

    if new_timeout and (not old_timeout or new_timeout > old_timeout):
        # Timeout was added or extended
        action = f"🔇 Mute `{new.username}`"
        desc = f"{new.mention} was **timed out** until `{new_timeout.strftime('%Y-%m-%d %H:%M:%S UTC')}`"

        # Calculate duration
        duration_seconds = (new_timeout.replace(tzinfo=None) - now.replace(tzinfo=None)).total_seconds()
        hours, remainder = divmod(int(duration_seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        duration_parts = []
        if hours > 0:
            duration_parts.append(f"{hours}h")
        if minutes > 0:
            duration_parts.append(f"{minutes}m")
        if seconds > 0 or not duration_parts:
            duration_parts.append(f"{seconds}s")
        duration = " ".join(duration_parts)

        # Try to fetch the moderator and reason from audit log
        reason = "No reason provided."
        moderator = None
        try:
            # Small delay to ensure audit log is updated
            await asyncio.sleep(2.0)

            print(f"[DEBUG] Fetching audit log for timeout change...")

            # Fetch audit log - it returns a list of AuditLog objects
            audit_result = await event.app.rest.fetch_audit_log(
                event.guild_id,
                event_type=hikari.AuditLogEventType.MEMBER_UPDATE
            )

            if isinstance(audit_result, list):
                # Process each AuditLog object in the list
                for audit_log in audit_result:
                    if hasattr(audit_log, 'entries'):
                        for entry_id, entry in audit_log.entries.items():
                            if entry.target_id == new.id:
                                entry_age = (now.replace(tzinfo=None) - entry.created_at.replace(
                                    tzinfo=None)).total_seconds()

                                if entry_age < 30 and entry_age > -10:  # Within reasonable time window
                                    print(f"[DEBUG] Found matching timeout entry")
                                    print(f"[DEBUG] Entry reason: '{entry.reason}'")
                                    print(f"[DEBUG] Entry user_id: {entry.user_id}")

                                    # Get the reason
                                    reason = entry.reason if entry.reason else "No reason provided."

                                    # Get the moderator from the users in the audit log
                                    if hasattr(audit_log, 'users') and entry.user_id in audit_log.users:
                                        moderator = audit_log.users[entry.user_id]
                                        print(f"[DEBUG] Found moderator: {moderator.username}")

                                    print(f"[DEBUG] USING THIS ENTRY - Reason: '{reason}'")
                                    break

                        # If we found what we needed, break outer loop
                        if moderator or reason != "No reason provided.":
                            break

        except Exception as e:
            print(f"[DEBUG] Error fetching audit log: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()

        embed = hikari.Embed(
            title=action,
            description=desc,
            color=0xFFAA00,
            timestamp=now
        )
        embed.add_field(name="User", value=f"{new.mention} ({new.display_name})", inline=False)
        if moderator:
            embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Duration", value=duration, inline=False)
        embed.add_field(name="ID", value=str(new.id), inline=False)

    else:
        # Timeout was removed
        action = "🔊 Timeout Removed"
        desc = f"{new.mention}'s timeout was **removed**."

        embed = hikari.Embed(
            title=action,
            description=desc,
            color=0x00FF00,
            timestamp=now
        )
        embed.add_field(name="User", value=f"{new.mention} ({new.display_name})", inline=False)
        embed.add_field(name="ID", value=str(new.id), inline=False)

    avatar_url = new.make_avatar_url() or new.default_avatar_url
    if avatar_url:
        embed.set_thumbnail(avatar_url)
    embed.set_footer(text=f"{bot_user.username} • {now.strftime('%m/%d/%Y %I:%M %p')}")

    await event.app.rest.create_message(MODERATION_LOG_CHANNEL, embed=embed)


async def handle_nickname_change(event, old, new):
    """Handle nickname changes"""
    embed = hikari.Embed(
        title="✏️ Nickname Changed",
        description=f"{new.mention} changed their nickname.",
        color=0x55AAFF,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Before", value=old.nickname or "*None*", inline=True)
    embed.add_field(name="After", value=new.nickname or "*None*", inline=True)
    embed.set_footer(text=f"User ID: {new.id}")

    await event.app.rest.create_message(MODERATION_LOG_CHANNEL, embed=embed)


# -------------------- Ban Logging --------------------
@loader.listener(hikari.BanCreateEvent)
async def on_member_banned(event: hikari.BanCreateEvent) -> None:
    user = event.user
    now = datetime.now(timezone.utc)
    bot_user = await event.app.rest.fetch_my_user()

    # Try to fetch ban info_hub from audit log
    reason = "No reason provided."
    banned_by = None
    try:
        audit_log = await event.app.rest.fetch_audit_log(
            event.guild_id,
            event_type=hikari.AuditLogEventType.MEMBER_BAN_ADD
        )
        for entry_id, entry in audit_log.entries.items():
            if entry.target_id == user.id:
                entry_age = (now.replace(tzinfo=None) - entry.created_at.replace(tzinfo=None)).total_seconds()
                if entry_age < 5:
                    reason = entry.reason or reason
                    banned_by = entry.user
                    break
    except Exception:
        pass

    embed = hikari.Embed(
        title="🔨 Member Banned",
        description=f"{user.mention} was banned from the server.",
        color=0xFF0000,
        timestamp=now
    )
    embed.add_field(name="User", value=f"{user.username}#{user.discriminator} ({user.mention})", inline=False)
    if banned_by:
        embed.add_field(name="Banned by", value=f"{banned_by.mention}", inline=False)
    embed.add_field(name="Reason", value=reason, inline=False)
    embed.add_field(name="ID", value=str(user.id), inline=False)

    avatar_url = user.make_avatar_url() or user.default_avatar_url
    if avatar_url:
        embed.set_thumbnail(avatar_url)
    embed.set_footer(text=f"{bot_user.username} • {now.strftime('%m/%d/%Y %I:%M %p')}")

    await event.app.rest.create_message(MODERATION_LOG_CHANNEL, embed=embed)


# -------------------- Unban Logging --------------------
@loader.listener(hikari.BanDeleteEvent)
async def on_member_unbanned(event: hikari.BanDeleteEvent) -> None:
    user = event.user
    now = datetime.now(timezone.utc)
    bot_user = await event.app.rest.fetch_my_user()

    # Try to fetch unban info_hub from audit log
    unbanned_by = None
    try:
        audit_log = await event.app.rest.fetch_audit_log(
            event.guild_id,
            event_type=hikari.AuditLogEventType.MEMBER_BAN_REMOVE
        )
        for entry_id, entry in audit_log.entries.items():
            if entry.target_id == user.id:
                entry_age = (now.replace(tzinfo=None) - entry.created_at.replace(tzinfo=None)).total_seconds()
                if entry_age < 5:
                    unbanned_by = entry.user
                    break
    except Exception:
        pass

    embed = hikari.Embed(
        title="🔓 Member Unbanned",
        description=f"{user.mention} was unbanned from the server.",
        color=0x00FF00,
        timestamp=now
    )
    embed.add_field(name="User", value=f"{user.username}#{user.discriminator} ({user.mention})", inline=False)
    if unbanned_by:
        embed.add_field(name="Unbanned by", value=f"{unbanned_by.mention}", inline=False)
    embed.add_field(name="ID", value=str(user.id), inline=False)

    avatar_url = user.make_avatar_url() or user.default_avatar_url
    if avatar_url:
        embed.set_thumbnail(avatar_url)
    embed.set_footer(text=f"{bot_user.username} • {now.strftime('%m/%d/%Y %I:%M %p')}")

    await event.app.rest.create_message(MODERATION_LOG_CHANNEL, embed=embed)