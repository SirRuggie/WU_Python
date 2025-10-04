# extensions/commands/help.py
"""
Comprehensive help command for Warriors United bot.
Lists all bot commands organized by categories with interactive UI.
"""

import hikari
import lightbulb

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT

loader = lightbulb.Loader()

# Help categories
HELP_CATEGORIES = {
    "fwa": {
        "name": "FWA Commands",
        "emoji": "⚔️",
        "description": "Farm War Alliance tools, bases, weights, and strategies"
    },
    "clan": {
        "name": "Clan Management",
        "emoji": "🏰",
        "description": "Commands to manage clans and view clan information"
    },
    "recruit": {
        "name": "Recruitment",
        "emoji": "👥",
        "description": "New member recruitment and onboarding system"
    },
    "ticket": {
        "name": "Ticket System",
        "emoji": "🎫",
        "description": "Recruitment ticket creation and management"
    },
    "cwl": {
        "name": "CWL Management",
        "emoji": "📅",
        "description": "CWL reminders, announcements, and bonus management"
    },
    "setup": {
        "name": "Server Setup",
        "emoji": "⚙️",
        "description": "Server configuration and information displays"
    },
    "utilities": {
        "name": "Utilities",
        "emoji": "🛠️",
        "description": "General purpose and fun commands"
    }
}

# Predefined command list organized by category
COMMAND_LIST = {
    "fwa": [
        ("/fwa bases", "Select and display FWA base layouts by Town Hall level - choose a user and TH level to view available bases"),
        ("/fwa chocolate", "Look up players or clans on the FWA Chocolate website for verification and war data"),
        ("/fwa lazycwl-snapshot", "Snapshot FWA clan players to track war participation during CWL season"),
        ("/fwa lazycwl-ping", "Ping players to return for FWA sync (Train⇨Join⇨Attack⇨Return 15-30min)"),
        ("/fwa lazycwl-status", "View active FWA LazyCWL snapshots for the current month"),
        ("/fwa lazycwl-roster", "Display complete player roster from any active snapshot - shows all players with TH levels, tags, and Discord link status"),
        ("/fwa lazycwl-reset", "Deactivate all FWA LazyCWL snapshots (use after wars complete)"),
        ("/fwa links", "Quick access to essential FWA links - verification forms and war weight entry"),
        ("/fwa upload-images", "Upload war and active base images for a specific Town Hall level"),
        ("/fwa war-plans", "Generate war strategy messages for different war outcomes (Win, Lose, Blacklisted, Mismatch)"),
        ("/fwa weight", "Calculate war weight from storage value (automatically multiplies by 5)"),
    ],
    "clan": [
        ("/clan dashboard", "Open the comprehensive Clan Management Dashboard with interactive buttons and clan data"),
        ("/clan info", "View detailed information about all clans in the Warriors United family"),
        ("/clan list", "Send clan assignment to a new recruit with welcome message and clan details"),
        ("/clan upload-images", "Upload logo and banner images for a specific clan"),
    ],
    "recruit": [
        ("/recruit questions", "Send comprehensive recruitment questionnaire to new recruits with primary questions dropdown"),
        ("/recruit dashboard", "Display the new member onboarding dashboard with role management and setup options"),
    ],
    "ticket": [
        ("/ticket setup", "Set up the ticket system embed with Main and FWA clan entry buttons (Admin only)"),
        ("/ticket config", "Configure ticket system settings including roles and categories (Admin only)"),
        ("/ticket change-category", "Change which category new tickets will be created in (Admin only)"),
        ("/ticket reset-counter", "Reset ticket counter for Main Clan, FWA Clan, or both types (Admin only)"),
        ("/ticket list", "List all currently open tickets with detailed information (Recruiter only)"),
        ("/ticket dashboard", "Quick ticket management dashboard with overview and actions (Recruiter only)"),
        ("/ticket deny", "Deny the ticket in current channel with denial options (Admin/Recruiter only)"),
        ("/ticket approve", "Approve the ticket in current channel and send congratulations (Admin/Recruiter only)"),
    ],
    "cwl": [
        ("/cwl-reminder schedule", "Schedule monthly CWL reminder notifications with custom timing"),
        ("/cwl-reminder status", "View current CWL reminder schedule status and upcoming reminders"),
        ("/cwl-reminder cancel", "Cancel all scheduled CWL reminder notifications"),
        ("/cwl-reminder test", "Send a test CWL reminder message to verify configuration"),
        ("/cwl-reminder list-jobs", "List all scheduled CWL reminder jobs with details"),
        ("/cwl-reminder followup", "Schedule CWL followup reminders for after signups close"),
        ("/cwl-announcement", "Send CWL announcement to main or lazy channels with custom messaging"),
        ("/lazycwl-bonuses", "Randomly select Lazy CWL bonus medal recipients from provided player list"),
        ("/lazyprep", "Send Lazy CWL preparation announcements (Declaration Complete, Closed, Open)"),
    ],
    "setup": [
        ("/setup recruit-aboutus", "Display Warriors United clan information and onboarding flow for new members"),
        ("/setup recruit-familyparticulars", "Display Warriors United family particulars, war rules, and expectations"),
        ("/setup recruit-strikesystem", "Display Warriors United strike system rules and enforcement policies"),
    ],
    "utilities": [
        ("/family-links", "Access the Family Clan Links panel to manage your roles and view clan information"),
        ("/slap", "Slap someone with a random GIF - select a user to target"),
        ("/say", "Send a message as the bot - useful for announcements"),
        ("/steal", "Steal a custom emoji into your bot application, replacing any with the same name"),
    ]
}


async def create_help_view(selected_category: str = "fwa") -> list:
    """Create the main help view with category selection."""
    cat_info = HELP_CATEGORIES.get(selected_category, {"name": "Unknown", "emoji": "❓"})

    components = [
        Text(content=f"# {cat_info['emoji']} Warriors United Bot Help"),
        Text(content="Select a category below to view available commands and their descriptions."),
        Separator(),
    ]

    # Category selection dropdown
    select_options = []
    for cat_id, cat_info in HELP_CATEGORIES.items():
        select_options.append(
            SelectOption(
                label=cat_info["name"],
                value=cat_id,
                description=cat_info["description"],
                emoji=cat_info["emoji"],
                is_default=(cat_id == selected_category)
            )
        )

    components.extend([
        ActionRow(
            components=[
                TextSelectMenu(
                    custom_id="help_category_select:menu",
                    placeholder="Pick a category to see commands...",
                    options=select_options
                )
            ]
        ),
        Separator(),
    ])

    # Action buttons
    components.append(
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="help_refresh:main",
                    label="Refresh",
                    emoji="🔄"
                ),
            ]
        )
    )

    return [Container(accent_color=BLUE_ACCENT, components=components)]


async def create_category_view(category: str) -> list:
    """Create a view showing commands in a specific category."""
    cat_info = HELP_CATEGORIES.get(category, {"name": "Unknown", "emoji": "❓"})
    commands = COMMAND_LIST.get(category, [])

    components = [
        Text(content=f"# {cat_info['emoji']} {cat_info['name']}"),
        Text(content=cat_info.get('description', 'Commands in this category')),
        Separator(divider=True),
    ]

    if commands:
        for cmd, desc in commands:
            components.extend([
                Text(content=f"**{cmd}**"),
                Text(content=desc),
                Separator(),
            ])
    else:
        components.append(Text(content="No commands found in this category."))

    # Back and refresh buttons
    components.append(
        ActionRow(
            components=[
                Button(
                    style=hikari.ButtonStyle.PRIMARY,
                    custom_id="help_back:main",
                    label="Back to Categories",
                    emoji="⬅️"
                ),
                Button(
                    style=hikari.ButtonStyle.SECONDARY,
                    custom_id="help_refresh:main",
                    label="Refresh",
                    emoji="🔄"
                ),
            ]
        )
    )

    return [Container(accent_color=BLUE_ACCENT, components=components)]


@loader.command
class HelpCommand(
    lightbulb.SlashCommand,
    name="help",
    description="View all available bot commands organized by category"
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        """Show the help menu."""
        components = await create_help_view()
        await ctx.respond(components=components, ephemeral=True)


@register_action("help_category_select", no_return=True)
async def on_category_select(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **kwargs
):
    """Handle category selection from dropdown."""
    selected_category = ctx.interaction.values[0]
    components = await create_category_view(selected_category)
    await ctx.interaction.edit_initial_response(components=components)


@register_action("help_back", no_return=True)
async def on_help_back(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **kwargs
):
    """Handle back button to return to main help view."""
    components = await create_help_view()
    await ctx.interaction.edit_initial_response(components=components)


@register_action("help_refresh", no_return=True)
async def on_help_refresh(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    **kwargs
):
    """Handle refresh button to reload help view."""
    components = await create_help_view()
    await ctx.interaction.edit_initial_response(components=components)


loader.command(HelpCommand)