"""Read-only prerequisites for the recruit setup posting commands.

These checks deliberately stop before inspecting channel overwrites.  Discord
will still enforce those when a post is sent; this helper only establishes
that the bot can manage the configured acknowledgement role and can retrieve
the next ordinary guild channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import hikari


_CURRENT_CHANNEL_PERMISSIONS = (
    hikari.Permissions.VIEW_CHANNEL
    | hikari.Permissions.SEND_MESSAGES
    | hikari.Permissions.ATTACH_FILES
)
_TEXT_CHANNEL_TYPES = frozenset((
    hikari.ChannelType.GUILD_TEXT,
    hikari.ChannelType.GUILD_NEWS,
))
_THREAD_CHANNEL_TYPES = frozenset((
    hikari.ChannelType.GUILD_NEWS_THREAD,
    hikari.ChannelType.GUILD_PUBLIC_THREAD,
    hikari.ChannelType.GUILD_PRIVATE_THREAD,
))


@dataclass(frozen=True, slots=True)
class RecruitSetupCheck:
    """The safe-to-display result of checking one recruit post transition."""

    role_id: int
    next_channel_id: int
    issues: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return not self.issues

    def message(self, label: str | None = None) -> str:
        prefix = f"{label}: " if label else ""
        if self.ready:
            return f"{prefix}ready"
        return f"{prefix}" + "; ".join(self.issues)


def _as_int(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def can_manage_server(ctx: Any) -> bool:
    """Whether the invoking member may publish or inspect recruit setup."""
    interaction = getattr(ctx, "interaction", None)
    member = getattr(interaction, "member", None)
    permissions = hikari.Permissions(getattr(member, "permissions", hikari.Permissions.NONE))
    return bool(
        getattr(interaction, "guild_id", None)
        and permissions & (hikari.Permissions.MANAGE_GUILD | hikari.Permissions.ADMINISTRATOR)
    )


async def require_manage_server(ctx: Any) -> bool:
    """Respond privately before any recruit setup read or write by an unauthorized caller."""
    if can_manage_server(ctx):
        return True
    await ctx.respond("You need Manage Server permission to use recruit setup.", ephemeral=True)
    return False


def _current_channel_required_permissions(ctx: Any) -> hikari.Permissions:
    """Require thread-specific sending only when the interaction identifies one."""
    channel = getattr(getattr(ctx, "interaction", None), "channel", None)
    if getattr(channel, "type", None) in _THREAD_CHANNEL_TYPES:
        return (
            hikari.Permissions.VIEW_CHANNEL
            | hikari.Permissions.SEND_MESSAGES_IN_THREADS
            | hikari.Permissions.ATTACH_FILES
        )
    return _CURRENT_CHANNEL_PERMISSIONS


def _permission_issue(ctx: Any) -> str | None:
    interaction = getattr(ctx, "interaction", None)
    app_permissions = getattr(interaction, "app_permissions", None)
    if app_permissions is None:
        return "I cannot verify my permissions in this channel."
    actual = hikari.Permissions(app_permissions)
    channel = getattr(interaction, "channel", None)
    channel_type = getattr(channel, "type", None)
    if channel_type is not None and (
        channel_type not in _TEXT_CHANNEL_TYPES
        and channel_type not in _THREAD_CHANNEL_TYPES
    ):
        return "Recruit posts can only be sent in a text, announcement, or thread channel."
    if actual & hikari.Permissions.ADMINISTRATOR:
        return None
    required = _current_channel_required_permissions(ctx)
    missing = required & ~actual
    if not missing:
        return None
    if missing & hikari.Permissions.VIEW_CHANNEL:
        return "I need View Channel permission here."
    if missing & hikari.Permissions.SEND_MESSAGES_IN_THREADS:
        return "I need Send Messages in Threads permission here."
    if missing & hikari.Permissions.ATTACH_FILES:
        return "I need Attach Files permission here."
    return "I need Send Messages permission here."


def _role_issues(
    *,
    guild_id: int,
    role_id: int,
    roles: tuple[Any, ...],
    bot_member: Any,
) -> tuple[str, ...]:
    target = next((role for role in roles if _as_int(getattr(role, "id", 0)) == role_id), None)
    if target is None:
        return ("The acknowledgement role is missing from this server.",)
    if role_id == guild_id:
        return ("The acknowledgement role cannot be @everyone.",)
    if bool(getattr(target, "is_managed", False)):
        return ("The acknowledgement role is managed by an integration and cannot be assigned.",)

    roles_by_id = {_as_int(getattr(role, "id", 0)): role for role in roles}
    bot_role_ids = {_as_int(value) for value in getattr(bot_member, "role_ids", ())}
    bot_role_ids.add(guild_id)  # Discord omits @everyone from member.role_ids.
    bot_permissions = hikari.Permissions.NONE
    positions = []
    for member_role_id in bot_role_ids:
        role = roles_by_id.get(member_role_id)
        if role is None:
            continue
        bot_permissions |= hikari.Permissions(getattr(role, "permissions", 0))
        positions.append(_as_int(getattr(role, "position", 0)))

    issues: list[str] = []
    if not bot_permissions & (hikari.Permissions.MANAGE_ROLES | hikari.Permissions.ADMINISTRATOR):
        issues.append("I need Manage Roles permission to assign the acknowledgement role.")
    # Administrator bypasses permission checks, never Discord's role hierarchy.
    if _as_int(getattr(target, "position", 0)) >= max(positions, default=0):
        issues.append("My highest role must be above the acknowledgement role.")
    return tuple(issues)


async def inspect_recruit_setup(
    ctx: Any,
    bot: Any,
    *,
    role_id: int,
    next_channel_id: int,
) -> RecruitSetupCheck:
    """Inspect one acknowledgement role and its next channel without mutation."""
    issues: list[str] = []
    current_issue = _permission_issue(ctx)
    if current_issue:
        issues.append(current_issue)

    guild_id = _as_int(getattr(getattr(ctx, "interaction", None), "guild_id", None))
    if not guild_id:
        issues.append("This command can only be used in a server.")
        return RecruitSetupCheck(role_id, next_channel_id, tuple(issues))

    try:
        roles = tuple(await bot.rest.fetch_roles(guild_id))
        bot_member = await bot.rest.fetch_my_member(guild_id)
    except hikari.HTTPError:
        issues.append("I could not read my server roles. Check my server access and try again.")
    except Exception:
        issues.append("I could not verify my server roles right now. Try again shortly.")
    else:
        issues.extend(_role_issues(
            guild_id=guild_id,
            role_id=int(role_id),
            roles=roles,
            bot_member=bot_member,
        ))

    try:
        next_channel = await bot.rest.fetch_channel(int(next_channel_id))
    except hikari.HTTPError:
        issues.append("I could not read the next onboarding channel. Check its server access and try again.")
    except Exception:
        issues.append("I could not verify the next onboarding channel right now. Try again shortly.")
    else:
        if _as_int(getattr(next_channel, "guild_id", 0)) != guild_id:
            issues.append("The next onboarding channel is not in this server.")
        elif getattr(next_channel, "type", None) not in _TEXT_CHANNEL_TYPES:
            issues.append("The next onboarding channel must be a text or announcement channel.")

    return RecruitSetupCheck(int(role_id), int(next_channel_id), tuple(issues))


async def require_ready(
    ctx: Any,
    bot: Any,
    *,
    role_id: int,
    next_channel_id: int,
) -> bool:
    """Respond safely after a deferred setup command if posting is unsafe."""
    check = await inspect_recruit_setup(
        ctx, bot, role_id=role_id, next_channel_id=next_channel_id,
    )
    if check.ready:
        return True
    await ctx.respond(
        "I did not post the recruit panel because setup needs attention:\n- "
        + "\n- ".join(check.issues),
        ephemeral=True,
    )
    return False
