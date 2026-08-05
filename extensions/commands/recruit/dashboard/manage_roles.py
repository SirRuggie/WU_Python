# extensions/commands/recruit/dashboard/manage_roles.py
"""
Handle the Add/Remove Needed Roles action from the recruit dashboard
"""

import lightbulb
import hikari
import asyncio
import logging

from extensions.components import register_action
from extensions.commands.recruit import perms
from utils.component_state import get_state, update_state
from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT, RED_ACCENT, BLUE_ACCENT, GOLD_ACCENT

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SelectMenuBuilder as SelectMenu,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
)

# Define standard roles that should be managed for recruits
STANDARD_ROLES = {
    "family": {
        "name": "Family",
        "id": 1003749467863924806,
        "emoji": "👨‍👩‍👧‍👦",
        "description": "Part of the Warrior family"
    },
    "recruit": {
        "name": "New Recruit",
        "id": 779277305671319572,
        "emoji": "🆕",
        "description": "New member being onboarded"
    },
    "strike_accepted": {
        "name": "Strike System Accepted",
        "id": 1003797283348946944,
        "emoji": "✅",
        "description": "Has accepted the strike system rules"
    }
}

# Role to remove during quick setup
VISITOR_ROLE_ID = 1003796476750745751

_log = logging.getLogger(__name__)


def bot_top_role_position(guild: hikari.Guild, bot: hikari.GatewayBot) -> int | None:
    """Return the bot member's highest cached role position."""
    me = bot.get_me()
    bot_member = guild.get_member(me.id) if me else None
    if bot_member is None:
        return None

    positions = [
        role.position
        for role_id in bot_member.role_ids
        if (role := guild.get_role(role_id)) is not None
    ]
    return max(positions, default=0)


def role_is_manageable(
        guild: hikari.Guild,
        bot: hikari.GatewayBot,
        role: hikari.Role | None,
) -> bool:
    """Whether Discord will allow this bot to add or remove ``role``.

    A native role select cannot be filtered by the application, so this must be
    checked after every selection as well as when the removal menu is built.
    """
    if role is None or role.id == guild.id or role.is_managed:
        return False

    me = bot.get_me()
    bot_member = guild.get_member(me.id) if me else None
    if bot_member is None:
        return False

    has_permission = bool(
        perms.guild_permissions(bot_member, guild)
        & (hikari.Permissions.MANAGE_ROLES | hikari.Permissions.ADMINISTRATOR)
    )
    top_position = bot_top_role_position(guild, bot)
    return (
        has_permission
        and top_position is not None
        and role.position < top_position
    )


def manageable_member_roles(
        guild: hikari.Guild,
        bot: hikari.GatewayBot,
        member: hikari.Member,
        actor: hikari.Member | hikari.InteractionMember | None,
) -> list[hikari.Role]:
    """Return the member's removable roles, highest first."""
    roles = [guild.get_role(role_id) for role_id in member.role_ids]
    return sorted(
        [
            role
            for role in roles
            if role_is_manageable(guild, bot, role)
            and perms.actor_can_manage_role(actor, guild, role)
        ],
        key=lambda role: role.position,
        reverse=True,
    )


async def _authorized(
        ctx: lightbulb.components.MenuContext,
        guild: hikari.Guild | None,
        mongo: MongoClient,
) -> bool:
    clicker = getattr(ctx.interaction, "member", None)
    if clicker is None and guild is not None:
        clicker = guild.get_member(ctx.user.id)
    return await perms.is_recruiter(clicker, mongo, guild)


def _clicking_member(
        ctx: lightbulb.components.MenuContext,
        guild: hikari.Guild | None,
) -> hikari.Member | hikari.InteractionMember | None:
    member = getattr(ctx.interaction, "member", None)
    if member is None and guild is not None:
        member = guild.get_member(ctx.user.id)
    return member


async def _resolve_member(
        guild: hikari.Guild | None,
        user_id: int,
        bot: hikari.GatewayBot,
) -> hikari.Member | None:
    if guild is None:
        return None

    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await bot.rest.fetch_member(guild.id, user_id)
    except (hikari.NotFoundError, hikari.ForbiddenError):
        return None


def _permission_response() -> list:
    return [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ❌ Recruiter Access Required"),
                Text(content=(
                    "Only configured recruiters, the Recruitment Team, and "
                    "administrators can manage another member's roles."
                )),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ],
        )
    ]


def _target_permission_response() -> list:
    return [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ❌ Member Cannot Be Managed"),
                Text(content=(
                    "You can only change roles for members below your highest role. "
                    "Administrators can manage any eligible member."
                )),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ],
        )
    ]


@register_action("manage_roles", requires_state=True)
@lightbulb.di.with_di
async def manage_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        user_id: int,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Display role management interface"""

    guild_id = kwargs.get("guild_id")
    guild = bot.cache.get_guild(guild_id)
    member = await _resolve_member(guild, user_id, bot)

    if not await _authorized(ctx, guild, mongo):
        return _permission_response()

    # Get feedback messages from kwargs
    added_roles = kwargs.get("added_roles", [])
    removed_roles = kwargs.get("removed_roles", [])
    skipped_roles = kwargs.get("skipped_roles", [])
    failed_roles = kwargs.get("failed_roles", [])

    if not member:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ **Member Not Found**"),
                    Text(content="Could not find the member in this server."),
                    Media(items=[MediaItem(media="assets/Red_Footer.png")])
                ]
            )
        ]

    actor = _clicking_member(ctx, guild)
    if not perms.actor_can_manage_member(actor, member, guild):
        return _target_permission_response()

    # Get member's current roles
    member_role_ids = set(member.role_ids)

    # Build role lists for display
    current_roles = []
    available_roles = []

    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        role = guild.get_role(role_id) if guild else None

        if role:
            if role_id in member_role_ids:
                current_roles.append(f"{role_info['emoji']} {role_info['name']}")
            else:
                available_roles.append(f"{role_info['emoji']} {role_info['name']}")

    # Build components list
    removable_roles = manageable_member_roles(guild, bot, member, actor)
    server_role_count = len(member_role_ids)

    container_components = [
        Text(content=f"## 👤 Member Roles — {member.display_name}"),
        Text(content=(
            f"{member.mention} currently has **{server_role_count}** server role(s). "
            "Use the controls below for bulk changes."
        )),
    ]
    
    # Add feedback messages if any
    if added_roles or removed_roles or skipped_roles or failed_roles:
        feedback_parts = []
        if added_roles:
            feedback_parts.append(f"**✅ Added:** {', '.join(added_roles)}")
        if removed_roles:
            feedback_parts.append(f"**➖ Removed:** {', '.join(removed_roles)}")
        if skipped_roles:
            feedback_parts.append(f"**⏭️ No change needed:** {', '.join(skipped_roles)}")
        if failed_roles:
            feedback_parts.append(f"**⚠️ Could not change:** {', '.join(failed_roles)}")

        container_components.extend([
            Separator(divider=True),
            Text(content="\n".join(feedback_parts)),
        ])
    
    container_components.extend([
        Separator(divider=True),

        # Current roles display
        Text(content="### ✅ Recruit Role Set Assigned"),
        Text(content="\n".join(current_roles) if current_roles else "_No standard roles assigned_"),

        Separator(divider=True),

        # Available roles display
        Text(content="### 📋 Recruit Role Set Not Assigned"),
        Text(content="\n".join(available_roles) if available_roles else "_All standard roles assigned_"),

        Separator(divider=True),

        # Action buttons
        Text(content="**Choose an action:**"),
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SUCCESS,
                    custom_id=f"add_roles:{action_id}",
                    label="Add Roles",
                    emoji="➕"
                ),
                Button(
                    style=hikari.ButtonStyle.DANGER,
                    custom_id=f"remove_roles:{action_id}",
                    label="Remove Roles",
                    emoji="➖",
                    is_disabled=not removable_roles
                ),
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id=f"quick_setup:{action_id}",
                    label="Apply Recruit Setup",
                    emoji="⚡"
                ),
            ]
        ),
    ])

    if kwargs.get("origin") != "role_command":
        container_components.append(
            ActionRow(
                components=[
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"refresh_dashboard:{action_id}",
                        label="Back to Recruit Dashboard",
                        emoji="↩️"
                    )
                ]
            )
        )

    container_components.append(
        Media(items=[MediaItem(media="assets/Blue_Footer.png")])
    )
    
    # Build the interface
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=container_components
        )
    ]

    return components


@register_action("add_roles", requires_state=True)
@lightbulb.di.with_di
async def add_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Show role addition interface with native role select menu"""

    # Get stored data
    data = await get_state(mongo, action_id)
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = await _resolve_member(guild, user_id, bot)

    if not await _authorized(ctx, guild, mongo):
        return _permission_response()

    if not member:
        return [error_response("Member not found", action_id)]

    if not perms.actor_can_manage_member(_clicking_member(ctx, guild), member, guild):
        return _target_permission_response()

    return [
        Container(
            accent_color=GREEN_ACCENT,
            components=[
                Text(content="## ➕ **Add Roles**"),
                Text(content=f"Select roles to add to **{member.display_name}**:"),
                Text(content=(
                    "-# Search by role name. Discord shows every server role; "
                    "roles outside your or the bot's hierarchy will be safely refused."
                )),
                ActionRow(
                    components=[
                        SelectMenu(
                            type=hikari.ComponentType.ROLE_SELECT_MENU,
                            custom_id=f"execute_add_roles:{action_id}",
                            placeholder="Select roles to add...",
                            min_values=1,
                            max_values=25,  # Discord's maximum
                        )
                    ]
                ),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            custom_id=f"manage_roles:{action_id}",
                            label="Cancel",
                            emoji="❌"
                        )
                    ]
                ),
                Media(items=[MediaItem(media="assets/Green_Footer.png")])
            ]
        )
    ]


@register_action("remove_roles", requires_state=True)
@lightbulb.di.with_di
async def remove_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Show role removal interface with paginated role list"""

    data = await get_state(mongo, action_id)
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")
    page = kwargs.get("page", 0)  # Get current page from kwargs

    guild = bot.cache.get_guild(guild_id)
    member = await _resolve_member(guild, user_id, bot)

    if not await _authorized(ctx, guild, mongo):
        return _permission_response()

    if not member:
        return [error_response("Member not found", action_id)]

    actor = _clicking_member(ctx, guild)
    if not perms.actor_can_manage_member(actor, member, guild):
        return _target_permission_response()

    removable_roles = manageable_member_roles(guild, bot, member, actor)

    if not removable_roles:
        return [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ℹ️ **No Roles to Remove**"),
                    Text(content="This member doesn't have any removable roles."),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"manage_roles:{action_id}",
                                label="Back to Role Management",
                                emoji="↩️"
                            )
                        ]
                    ),
                    Media(items=[MediaItem(media="assets/Gold_Footer.png")])
                ]
            )
        ]

    # Pagination logic
    roles_per_page = 25
    total_pages = (len(removable_roles) + roles_per_page - 1) // roles_per_page
    page = max(0, min(page, total_pages - 1))  # Ensure page is within bounds
    await update_state(
        mongo,
        action_id,
        {"$set": {"remove_roles_page": page}},
    )
    
    start_idx = page * roles_per_page
    end_idx = start_idx + roles_per_page
    page_roles = removable_roles[start_idx:end_idx]
    
    # Build options for the current page
    options = []
    for role in page_roles:
        options.append(
            SelectOption(
                label=role.name[:100],
                value=str(role.id),
                description=f"Position: {role.position}",
                emoji="🏷️"
            )
        )

    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ➖ **Remove Roles**"),
                Text(content=f"Select roles to remove from **{member.display_name}**:"),
                Text(content=f"-# Page {page + 1} of {total_pages} • Showing {len(page_roles)} of {len(removable_roles)} roles"),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"execute_remove_roles:{action_id}",
                            placeholder="Select roles to remove...",
                            min_values=1,
                            max_values=len(options),
                            options=options
                        )
                    ]
                ),
            ]
        )
    ]
    
    # Add navigation buttons if there are multiple pages
    nav_buttons = []
    
    if page > 0:
        nav_buttons.append(
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"remove_roles_prev:{action_id}",
                label="Previous",
                emoji="◀️"
            )
        )
    
    nav_buttons.append(
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"manage_roles:{action_id}",
            label="Cancel",
            emoji="❌"
        )
    )
    
    if page < total_pages - 1:
        nav_buttons.append(
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"remove_roles_next:{action_id}",
                label="Next",
                emoji="▶️"
            )
        )
    
    components[0].components.extend([
        ActionRow(components=nav_buttons),
        Media(items=[MediaItem(media="assets/Red_Footer.png")])
    ])

    return components


async def _change_remove_roles_page(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        direction: int,
        mongo: MongoClient,
        bot: hikari.GatewayBot,
) -> list:
    data = await get_state(mongo, action_id)
    if not data:
        return [error_response("Session expired", action_id)]

    current_page = int(data.get("remove_roles_page", 0))
    return await remove_roles_handler(
        ctx=ctx,
        action_id=action_id,
        mongo=mongo,
        bot=bot,
        page=max(0, current_page + direction),
        **data,
    )


@register_action("remove_roles_prev", requires_state=True)
@lightbulb.di.with_di
async def remove_roles_prev_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    """Show the previous page of removable roles."""
    return await _change_remove_roles_page(ctx, action_id, -1, mongo, bot)


@register_action("remove_roles_next", requires_state=True)
@lightbulb.di.with_di
async def remove_roles_next_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    """Show the next page of removable roles."""
    return await _change_remove_roles_page(ctx, action_id, 1, mongo, bot)


@register_action("quick_setup", requires_state=True)
@lightbulb.di.with_di
async def quick_setup_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Quick setup - adds standard recruit roles and removes visitor role"""

    data = await get_state(mongo, action_id)
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = await _resolve_member(guild, user_id, bot)

    if not await _authorized(ctx, guild, mongo):
        return _permission_response()

    if not member:
        return [error_response("Member not found", action_id)]

    if not perms.actor_can_manage_member(_clicking_member(ctx, guild), member, guild):
        return _target_permission_response()

    # Add all standard roles
    added_roles = []
    failed_roles = []
    removed_roles = []

    # Add standard roles
    actor = _clicking_member(ctx, guild)
    for role_key, role_info in STANDARD_ROLES.items():
        role_id = role_info["id"]
        role = guild.get_role(role_id)

        if role and role_id not in member.role_ids:
            if (
                    not role_is_manageable(guild, bot, role)
                    or not perms.actor_can_manage_role(actor, guild, role)
            ):
                failed_roles.append(f"{role_info['name']} (not permitted)")
                continue
            try:
                await member.add_role(
                    role,
                    reason=f"Recruit setup applied by {ctx.user.username} ({ctx.user.id})",
                )
                added_roles.append(role_info['name'])
            except Exception:
                _log.exception(
                    "recruit setup could not add role=%s member=%s actor=%s",
                    role_id, user_id, ctx.user.id,
                )
                failed_roles.append(role_info['name'])
    
    # Remove visitor role if they have it
    visitor_role = guild.get_role(VISITOR_ROLE_ID)
    if visitor_role and VISITOR_ROLE_ID in member.role_ids:
        if (
                not role_is_manageable(guild, bot, visitor_role)
                or not perms.actor_can_manage_role(actor, guild, visitor_role)
        ):
            failed_roles.append(f"{visitor_role.name} (not permitted)")
            visitor_role = None

    if visitor_role and VISITOR_ROLE_ID in member.role_ids:
        try:
            await member.remove_role(
                visitor_role,
                reason=f"Recruit setup applied by {ctx.user.username} ({ctx.user.id})",
            )
            removed_roles.append(visitor_role.name)
        except Exception:
            _log.exception(
                "recruit setup could not remove role=%s member=%s actor=%s",
                VISITOR_ROLE_ID, user_id, ctx.user.id,
            )
            failed_roles.append(visitor_role.name)
    
    # Wait a moment for Discord to update
    await asyncio.sleep(0.5)

    # Refresh the manage roles view to show updated roles
    return await manage_roles_handler(
        ctx=ctx,
        action_id=action_id,
        user_id=user_id,
        mongo=mongo,
        bot=bot,
        guild_id=guild_id,
        added_roles=added_roles,
        removed_roles=removed_roles,
        failed_roles=failed_roles,
        origin=data.get("origin"),
    )


@register_action("execute_add_roles", requires_state=True)
@lightbulb.di.with_di
async def execute_add_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Execute the role addition and refresh the manage roles view"""
    
    data = await get_state(mongo, action_id)
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = await _resolve_member(guild, user_id, bot)

    if not await _authorized(ctx, guild, mongo):
        return _permission_response()

    if not member:
        return [error_response("Member not found", action_id)]

    if not perms.actor_can_manage_member(_clicking_member(ctx, guild), member, guild):
        return _target_permission_response()

    # Get selected role IDs from the interaction
    selected_values = ctx.interaction.values
    added_roles = []
    skipped_roles = []
    failed_roles = []
    actor = _clicking_member(ctx, guild)

    for selected_role_id in selected_values:
        role_id = int(selected_role_id)
        role = guild.get_role(role_id)

        if role is None:
            failed_roles.append(f"Unknown role `{role_id}`")
        elif role_id in member.role_ids:
            skipped_roles.append(role.name)
        elif (
                not role_is_manageable(guild, bot, role)
                or not perms.actor_can_manage_role(actor, guild, role)
        ):
            failed_roles.append(f"{role.name} (not permitted)")
        else:
            try:
                await member.add_role(
                    role,
                    reason=f"Added by {ctx.user.username} ({ctx.user.id}) via role manager",
                )
                added_roles.append(role.name)
            except Exception:
                _log.exception(
                    "bulk role add failed role=%s member=%s actor=%s",
                    role_id, user_id, ctx.user.id,
                )
                failed_roles.append(role.name)

    # Wait a moment for Discord to update
    await asyncio.sleep(0.5)
    
    # Refresh the manage roles view
    return await manage_roles_handler(
        ctx=ctx,
        action_id=action_id,
        user_id=user_id,
        mongo=mongo,
        bot=bot,
        guild_id=guild_id,
        added_roles=added_roles,
        skipped_roles=skipped_roles,
        failed_roles=failed_roles,
        origin=data.get("origin"),
    )


@register_action("execute_remove_roles", requires_state=True)
@lightbulb.di.with_di
async def execute_remove_roles_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Execute the role removal and refresh the manage roles view"""
    
    data = await get_state(mongo, action_id)
    if not data:
        return [error_response("Session expired", action_id)]

    user_id = data.get("user_id")
    guild_id = data.get("guild_id")

    guild = bot.cache.get_guild(guild_id)
    member = await _resolve_member(guild, user_id, bot)

    if not await _authorized(ctx, guild, mongo):
        return _permission_response()

    if not member:
        return [error_response("Member not found", action_id)]

    if not perms.actor_can_manage_member(_clicking_member(ctx, guild), member, guild):
        return _target_permission_response()

    # Get selected role IDs from the interaction
    selected_values = ctx.interaction.values
    removed_roles = []
    skipped_roles = []
    failed_roles = []
    actor = _clicking_member(ctx, guild)

    for role_id_str in selected_values:
        # TextSelectMenu provides role IDs as strings
        role_id = int(role_id_str)
        role = guild.get_role(role_id)

        if role is None:
            failed_roles.append(f"Unknown role `{role_id}`")
        elif role_id not in member.role_ids:
            skipped_roles.append(role.name)
        elif (
                not role_is_manageable(guild, bot, role)
                or not perms.actor_can_manage_role(actor, guild, role)
        ):
            failed_roles.append(f"{role.name} (not permitted)")
        else:
            try:
                await member.remove_role(
                    role,
                    reason=f"Removed by {ctx.user.username} ({ctx.user.id}) via role manager",
                )
                removed_roles.append(role.name)
            except Exception:
                _log.exception(
                    "bulk role remove failed role=%s member=%s actor=%s",
                    role_id, user_id, ctx.user.id,
                )
                failed_roles.append(role.name)

    # Wait a moment for Discord to update
    await asyncio.sleep(0.5)
    
    # Refresh the manage roles view
    return await manage_roles_handler(
        ctx=ctx,
        action_id=action_id,
        user_id=user_id,
        mongo=mongo,
        bot=bot,
        guild_id=guild_id,
        removed_roles=removed_roles,
        skipped_roles=skipped_roles,
        failed_roles=failed_roles,
        origin=data.get("origin"),
    )


# Legacy buttons encode ``original_action_id:page`` in the dispatcher's action-id
# segment. Let the handler unpack that compound id before checking the original
# state; a dispatcher-level lookup would search for the unsaved compound value.
@register_action("remove_roles_page")
@lightbulb.di.with_di
async def remove_roles_page_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs
) -> list:
    """Keep old, already-rendered pagination buttons usable."""
    parts = ctx.interaction.custom_id.split(":")
    if len(parts) != 3:
        return [error_response("Invalid role page", action_id)]

    original_action_id = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        return [error_response("Invalid role page", original_action_id)]

    data = await get_state(mongo, original_action_id)
    if not data:
        return [error_response("Session expired", original_action_id)]

    return await remove_roles_handler(
        ctx=ctx,
        action_id=original_action_id,
        mongo=mongo,
        bot=bot,
        page=page,
        **data,
    )


# Helper function for error responses
def error_response(message: str, action_id: str) -> Container:
    return Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"## ❌ **Error: {message}**"),
            Media(items=[MediaItem(media="assets/Red_Footer.png")])
        ]
    )
