# extensions/commands/recruit/dashboard/dashboard.py
"""
Main recruit dashboard display - shows the dashboard interface with all action buttons
"""

import lightbulb
import hikari

from extensions.commands.recruit import recruit
from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT
from utils.emoji import emojis

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)


@recruit.register()
class RecruitDashboard(
    lightbulb.SlashCommand,
    name="dashboard",
    description="Display the new member onboarding dashboard"
):
    user = lightbulb.user(
        "discord-user",
        "Select the new recruit to display dashboard for"
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Generate unique action ID for this interaction
        action_id = str(ctx.interaction.id)

        # Store the interaction data in MongoDB
        data = {
            "_id": action_id,
            "user_id": self.user.id,
            "recruiter_id": ctx.user.id,
            "guild_id": ctx.guild_id,
            "channel_id": ctx.channel_id
        }
        await mongo.button_store.insert_one(data)

        # Get the recruit's display information
        guild = bot.cache.get_guild(ctx.guild_id)
        member = guild.get_member(self.user.id) if guild else None

        # Build the dashboard components
        components = await create_dashboard_page(
            action_id=action_id,
            user=self.user,
            member=member,
            recruiter=ctx.member,
            bot=bot,
            mongo=mongo,
            **data
        )

        await ctx.respond(components=components, ephemeral=True)


async def create_dashboard_page(
        action_id: str,
        user: hikari.User,
        member: hikari.Member,
        recruiter: hikari.Member,
        bot: hikari.GatewayBot = None,
        mongo: MongoClient = None,
        **kwargs
) -> list:
    """Create the main dashboard page components"""

    # Get member's display name with their timezone/country if in nickname
    display_name = member.display_name if member else user.username

    # Collect current roles
    role_sections = []

    if member and mongo:
        # Import TH_LEVELS from set_townhall
        from .set_townhall import TH_LEVELS

        # Check TH roles
        th_roles = []
        for th_config in TH_LEVELS:
            if th_config["role_id"] in member.role_ids:
                th_roles.append(f"{th_config['emoji']} TH{th_config['level']}")

        # Check clan roles
        clan_roles = []
        clan_data = await mongo.clans.find().to_list(length=None)
        for clan in clan_data:
            if clan.get("role_id") in member.role_ids:
                clan_emoji = clan.get("emoji", "⚔️")
                clan_roles.append(f"{clan_emoji} {clan.get('name')}")

        # Check standard roles (from manage_roles.py)
        standard_roles = []
        try:
            from .manage_roles import STANDARD_ROLES
            for role_key, role_info in STANDARD_ROLES.items():
                if role_info["id"] in member.role_ids:
                    standard_roles.append(f"{role_info['emoji']} {role_info['name']}")
        except ImportError:
            pass

        # Build role display section
        if th_roles or clan_roles or standard_roles:
            role_sections.extend([
                Separator(divider=True),
                Text(content="### 📋 **Current Roles**"),
            ])

            if th_roles:
                role_sections.append(
                    Text(content=f"**Townhall:** {', '.join(th_roles)}")
                )
            else:
                role_sections.append(
                    Text(content="**Townhall:** _Not set_")
                )

            if clan_roles:
                role_sections.append(
                    Text(content=f"**Clan Roles:** {', '.join(clan_roles)}")
                )
            else:
                role_sections.append(
                    Text(content="**Clan Roles:** _Not assigned_")
                )

            if standard_roles:
                role_sections.append(
                    Text(content=f"**Other Roles:** {', '.join(standard_roles)}")
                )

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                # Header
                Text(content="## 🎯 **New Member Dashboard**"),
                Text(content=(
                    f"Welcome to the New Member Onboarding Dashboard! This tool is "
                    f"designed to simplify and automate the onboarding process for new "
                    f"recruits in the clan. Follow the steps below to assign roles, share "
                    f"important clan information, and notify key channels. Make sure you "
                    f"have the following information ready to streamline the setup:"
                )),

                # Required Information Section
                Separator(divider=True, spacing=hikari.SpacingType.LARGE),
                Text(content="### 📋 **Required Information:**"),
                Text(content=(
                    f"• **In-Game Name (IGN):** The recruit's in-game name.\n"
                    f"• **Time Zone:** The recruit's time zone.\n"
                    f"• **Country Flag:** The flag emoji representing their country.\n"
                    f"• **Number of Accounts:** The total number of accounts the recruit is bringing."
                )),

                # Nickname Display
                Separator(divider=True, spacing=hikari.SpacingType.LARGE),
                Text(content=f"**Nickname:** {display_name}"),

                # Add role sections here
                *role_sections,  # This unpacks the role display sections

                # Action Buttons
                Separator(divider=True, spacing=hikari.SpacingType.LARGE),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"create_nickname:{action_id}",
                            label="1-Create Server Nickname",
                            emoji="✏️"
                        ),
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"manage_roles:{action_id}",
                            label="2-Add/Remove Needed Roles",
                            emoji="👤"
                        ),
                    ]
                ),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"set_townhall:{action_id}",
                            label="3-Set Townhall Role(s)",
                            emoji="🏰"
                        ),
                        Button(
                            style=hikari.ButtonStyle.PRIMARY,
                            custom_id=f"add_clan_roles:{action_id}",
                            label="4-Add ALL Clan Roles to Recruit",
                            emoji="⚔️"
                        ),
                    ]
                ),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            custom_id=f"server_walkthrough:{action_id}",
                            label="5-Server walk thru (only 1 Clan)",
                            emoji="🎯"
                        ),
                    ]
                ),

                # Footer
                Media(
                    items=[
                        MediaItem(media="assets/Blue_Footer.png")
                    ]
                ),
                Text(content=f"-# Dashboard requested by {recruiter.mention}")
            ]
        )
    ]

    return components


# Register the main dashboard refresh action
@register_action("refresh_dashboard")
@lightbulb.di.with_di
async def refresh_dashboard(
        action_id: str,
        user_id: int = None,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        ctx: lightbulb.components.MenuContext = None,
        **kwargs
) -> list:
    """Refresh the dashboard display"""

    # Get the cached data
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        print(f"[Dashboard] No data found for action_id: {action_id}")
        return []

    # Use data from MongoDB if not provided
    user_id = user_id or data.get("user_id")
    guild_id = kwargs.get('guild_id') or data.get("guild_id")

    guild = bot.cache.get_guild(guild_id) if guild_id else None
    user = bot.cache.get_user(user_id)
    member = guild.get_member(user_id) if guild else None
    recruiter_id = kwargs.get('recruiter_id') or data.get("recruiter_id")
    recruiter = guild.get_member(recruiter_id) if guild and recruiter_id else None

    return await create_dashboard_page(
        action_id=action_id,
        user=user,
        member=member,
        recruiter=recruiter,
        bot=bot,
        mongo=mongo,
        **kwargs
    )