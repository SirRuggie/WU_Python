# extensions/commands/tickets/manage.py
"""
Ticket management commands - list, dashboard, etc.
"""

import hikari
import lightbulb
from typing import List
from datetime import datetime, timezone

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SelectMenuBuilder as SelectMenu,
    SelectOptionBuilder as SelectOption,
)

from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT
from extensions.components import register_action
from extensions.commands.tickets import loader, ticket


@ticket.register()
class ListTickets(
    lightbulb.SlashCommand,
    name="list",
    description="List all open tickets (Recruiter only)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        """List all open tickets"""

        # Get config to check roles
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
        main_role = config.get("main_recruiter_role")
        fwa_role = config.get("fwa_recruiter_role")

        # Check if user is a recruiter
        user_roles = ctx.member.role_ids
        is_recruiter = (
                (main_role and main_role in user_roles) or
                (fwa_role and fwa_role in user_roles) or
                ctx.member.permissions & hikari.Permissions.ADMINISTRATOR
        )

        if not is_recruiter:
            await ctx.respond(
                "❌ You must be a recruiter to use this command!",
                ephemeral=True
            )
            return

        # Fetch all open tickets
        tickets_list = await mongo.button_store.find({
            "type": "ticket",
            "status": "open"
        }).to_list(length=None)

        if not tickets_list:
            await ctx.respond(
                components=[
                    Container(
                        accent_color=BLUE_ACCENT,
                        components=[
                            Text(content="📋 **No Open Tickets**"),
                            Separator(divider=True),
                            Text(content="There are currently no open tickets."),
                            Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                        ]
                    )
                ],
                ephemeral=True
            )
            return

        # Group tickets by type
        main_tickets = []
        fwa_tickets = []

        for ticket in tickets_list:
            ticket_info = (
                f"• <@{ticket['user_id']}> - <#{ticket['channel_id']}> "
                f"(Created <t:{int(ticket['created_at'].timestamp())}:R>)"
            )

            if ticket['ticket_type'] == 'main':
                main_tickets.append(ticket_info)
            else:
                fwa_tickets.append(ticket_info)

        # Build response
        description_parts = []

        if main_tickets:
            description_parts.append(
                f"**Main Clan Tickets ({len(main_tickets)}):**\n" +
                "\n".join(main_tickets)
            )

        if fwa_tickets:
            if description_parts:
                description_parts.append("")  # Add spacing
            description_parts.append(
                f"**FWA Clan Tickets ({len(fwa_tickets)}):**\n" +
                "\n".join(fwa_tickets)
            )

        await ctx.respond(
            components=[
                Container(
                    accent_color=BLUE_ACCENT,
                    components=[
                        Text(content=f"📋 **Open Tickets ({len(tickets_list)} total)**"),
                        Separator(divider=True),
                        Text(content="\n".join(description_parts)),
                        Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                    ]
                )
            ],
            ephemeral=True
        )


@ticket.register()
class Dashboard(
    lightbulb.SlashCommand,
    name="dashboard",
    description="Quick ticket management dashboard (Recruiter only)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        """Show ticket management dashboard"""

        # Store action data
        action_id = str(ctx.interaction.id)
        await mongo.button_store.insert_one({
            "_id": action_id,
            "user_id": ctx.user.id
        })

        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="🎫 **Ticket Management Dashboard**"),
                    Separator(divider=True),
                    Text(content="Select an action from the menu below:"),

                    # Action menu
                    ActionRow(
                        components=[
                            SelectMenu(
                                custom_id=f"ticket_dashboard_action:{action_id}",
                                placeholder="Choose an action...",
                                options=[
                                    SelectOption(
                                        label="View Open Tickets",
                                        value="view_open",
                                        description="List all currently open tickets",
                                        emoji="📋"
                                    ),
                                    SelectOption(
                                        label="My Assigned Tickets",
                                        value="my_tickets",
                                        description="View tickets you're handling",
                                        emoji="👤"
                                    ),
                                    SelectOption(
                                        label="Ticket Statistics",
                                        value="stats",
                                        description="View system statistics",
                                        emoji="📊"
                                    ),
                                    SelectOption(
                                        label="Recent Activity",
                                        value="recent",
                                        description="See recent ticket activity",
                                        emoji="🕐"
                                    ),
                                ]
                            )
                        ]
                    ),

                    Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                ]
            )
        ]

        await ctx.respond(components=components, ephemeral=True)


@register_action("ticket_dashboard_action", opens_modal=False)
async def handle_dashboard_action(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
) -> List[Container]:
    """Handle dashboard action selection"""

    selected_action = ctx.interaction.values[0]

    # For now, return a placeholder
    return [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"**Selected:** {selected_action}"),
                Text(content="This feature is coming soon!"),
                Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
            ]
        )
    ]