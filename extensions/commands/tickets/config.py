# extensions/commands/tickets/config.py
"""
Ticket system configuration commands
"""

import hikari
import lightbulb
from datetime import datetime, timezone

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.mongo import MongoClient
from utils.constants import GREEN_ACCENT
from extensions.commands.tickets import loader, ticket

# Default configuration values (same as in handlers.py)
DEFAULT_MAIN_CATEGORY = 1395400463897202738
DEFAULT_FWA_CATEGORY = 1395653165470191667
DEFAULT_ADMIN_TO_NOTIFY = 505227988229554179


@ticket.register()
class Config(
    lightbulb.SlashCommand,
    name="config",
    description="Configure ticket system settings (Admin only)"
):
    main_role = lightbulb.string(
        "main_role",
        "Role ID for Main Clan recruiters",
        default=None
    )

    fwa_role = lightbulb.string(
        "fwa_role",
        "Role ID for FWA recruiters",
        default=None
    )

    admin_notify = lightbulb.string(
        "admin_id",
        "User ID to notify when categories are full",
        default=None
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        """Configure ticket system settings"""

        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True
            )
            return

        updates = []
        update_data = {}

        if self.main_role:  # Changed from ctx.options.main_role
            try:
                role_id = int(self.main_role)
                update_data["main_recruiter_role"] = role_id
                updates.append(f"Main Recruiter Role: <@&{role_id}>")
            except ValueError:
                await ctx.respond("Invalid Main Role ID!", ephemeral=True)
                return

        if self.fwa_role:  # Changed from ctx.options.fwa_role
            try:
                role_id = int(self.fwa_role)
                update_data["fwa_recruiter_role"] = role_id
                updates.append(f"FWA Recruiter Role: <@&{role_id}>")
            except ValueError:
                await ctx.respond("Invalid FWA Role ID!", ephemeral=True)
                return

        if self.admin_notify:  # Changed from ctx.options.admin_notify
            try:
                user_id = int(self.admin_notify)
                update_data["admin_to_notify"] = user_id
                updates.append(f"Admin to Notify: <@{user_id}>")
            except ValueError:
                await ctx.respond("Invalid Admin User ID!", ephemeral=True)
                return

        if updates:
            # Store in database for persistence
            update_data["updated_at"] = datetime.now(timezone.utc)
            await mongo.ticket_setup.update_one(
                {"_id": "config"},
                {"$set": update_data},
                upsert=True
            )

            print(f"[Tickets] Saved configuration to database: {update_data}")

            await ctx.respond(
                f"✅ **Ticket Configuration Updated:**\n" + "\n".join(updates),
                ephemeral=True
            )
        else:
            # Show current configuration
            config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
            config_text = (
                "**Current Ticket Configuration:**\n"
                f"Main Recruiter Role: {'<@&' + str(config.get('main_recruiter_role')) + '>' if config.get('main_recruiter_role') else 'Not set'}\n"
                f"FWA Recruiter Role: {'<@&' + str(config.get('fwa_recruiter_role')) + '>' if config.get('fwa_recruiter_role') else 'Not set'}\n"
                f"Admin to Notify: {'<@' + str(config.get('admin_to_notify', 505227988229554179)) + '>'}\n"
                f"Main Category: {config.get('main_category', 1395400463897202738)}\n"
                f"FWA Category: {config.get('fwa_category', 1395653165470191667)}\n\n"
                f"**Ticket Counters:**\n"
                f"Main Tickets: {config.get('main_ticket_counter', 0)}\n"
                f"FWA Tickets: {config.get('fwa_ticket_counter', 0)}"
            )
            await ctx.respond(config_text, ephemeral=True)


@ticket.register()
class ChangeCategory(
    lightbulb.SlashCommand,
    name="change-category",
    description="Change which category new tickets will be created in (Admin only)"
):
    ticket_type = lightbulb.string(
        "type",
        "Which ticket type to change",
        choices=[
            lightbulb.Choice(name="Main Clan", value="main"),
            lightbulb.Choice(name="FWA Clan", value="fwa")
        ]
    )

    new_category = lightbulb.string(
        "category_id",
        "New category ID for tickets"
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Change the category for ticket creation"""

        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True
            )
            return

        try:
            category_id = int(self.new_category)  # Changed from ctx.options.new_category

            # Verify the category exists and is accessible
            category = await bot.rest.fetch_channel(category_id)
            if category.type != hikari.ChannelType.GUILD_CATEGORY:
                await ctx.respond(
                    "❌ That's not a valid category channel!",
                    ephemeral=True
                )
                return

        except (ValueError, hikari.NotFoundError):
            await ctx.respond(
                "❌ Invalid category ID or category not found!",
                ephemeral=True
            )
            return

        # Update the configuration in database
        ticket_type = self.ticket_type  # Changed from ctx.options.ticket_type
        config_key = f"{ticket_type}_category"

        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {
                "$set": {
                    config_key: category_id,
                    f"{config_key}_name": category.name,
                    "updated_at": datetime.now(timezone.utc),
                    "updated_by": ctx.user.id
                }
            },
            upsert=True
        )

        await ctx.respond(
            components=[
                Container(
                    accent_color=GREEN_ACCENT,
                    components=[
                        Text(content="✅ **Category Updated Successfully**"),
                        Separator(divider=True),
                        Text(content=(
                            f"**Ticket Type:** {ticket_type.upper()}\n"
                            f"**New Category:** {category.name} (`{category_id}`)\n\n"
                            f"All new {ticket_type} tickets will now be created in this category."
                        )),
                        Media(items=[MediaItem(media="assets/Green_Footer.png")]),
                    ]
                )
            ],
            ephemeral=True
        )


@ticket.register()
class ResetCounter(
    lightbulb.SlashCommand,
    name="reset-counter",
    description="Reset ticket counter for a specific type (Admin only)"
):
    ticket_type = lightbulb.string(
        "type",
        "Which ticket counter to reset",
        choices=[
            lightbulb.Choice(name="Main Clan", value="main"),
            lightbulb.Choice(name="FWA Clan", value="fwa"),
            lightbulb.Choice(name="Both", value="both")
        ]
    )

    new_value = lightbulb.integer(
        "value",
        "New counter value (default: 0)",
        default=0,
        min_value=0
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        """Reset ticket counters"""

        # Check permissions
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond(
                "❌ You need Administrator permissions to use this command!",
                ephemeral=True
            )
            return

        ticket_type = self.ticket_type  # Changed from ctx.options.ticket_type
        new_value = self.new_value      # Changed from ctx.options.new_value

        update_data = {}
        updated = []

        if ticket_type in ["main", "both"]:
            update_data["main_ticket_counter"] = new_value
            updated.append(f"Main counter reset to {new_value}")

        if ticket_type in ["fwa", "both"]:
            update_data["fwa_ticket_counter"] = new_value
            updated.append(f"FWA counter reset to {new_value}")

        # Update database
        await mongo.ticket_setup.update_one(
            {"_id": "config"},
            {"$set": update_data},
            upsert=True
        )

        await ctx.respond(
            f"✅ **Ticket Counters Reset:**\n" + "\n".join(updated),
            ephemeral=True
        )