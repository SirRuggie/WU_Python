# extensions/commands/tickets/manage.py
"""
Ticket management commands - list, dashboard, etc.
"""

import hikari
import lightbulb
import re
from collections import Counter
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

# Discord rejects a Components V2 text display whose content is outside 1-4000
# characters, and BOTH bounds are reachable from a ticket list:
#   - upper: open tickets are only cleared by /ticket deny and /ticket approve, so
#     abandoned ones pile up forever and the joined list crosses 4000 at roughly 53
#     entries (~75 chars each). This is the bound that was actually crashing.
#   - lower: not reachable today via the if/else grouping below, but guarded anyway so
#     a future filter that returns nothing degrades to a message instead of a 400.
MAX_TEXT_CONTENT = 4000
TRUNCATION_HEADROOM = 120  # leaves room for the "N more" note


def safe_text_content(body: str, empty_fallback: str) -> str:
    """Clamp a text-display body into Discord's 1-4000 character window."""
    body = (body or "").strip()
    if not body:
        return empty_fallback
    if len(body) <= MAX_TEXT_CONTENT:
        return body

    lines = body.split("\n")
    kept, used = [], 0
    budget = MAX_TEXT_CONTENT - TRUNCATION_HEADROOM
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1

    hidden = len(lines) - len(kept)
    return "\n".join(kept) + f"\n\n-# …truncated, {hidden} more line(s) not shown."


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
                        Text(content=safe_text_content(
                            "\n".join(description_parts),
                            "No open tickets."
                        )),
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


# A ticket channel across every naming scheme this bot has used:
#   5be8ef8 created them as "✅main-1-user"  (✅ was the OPEN prefix originally)
#   b3015f6 changed creation to "🆕main-1-user"
#   close.py rewrites the leading emoji to ✅/❌ on approve/deny
# The optional hyphen covers names carrying a separator after the emoji.
TICKET_NAME_RE = re.compile(r"^[🆕✅❌]-?(main|fwa)-\d+-", re.IGNORECASE)
CLOSED_EMOJI = ("✅", "❌")
GUILD_CHANNEL_CAP = 500


def _as_int(value) -> int:
    """Channel/user ids have been stored as both int and str across schema versions."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@ticket.register()
class Diagnostics(
    lightbulb.SlashCommand,
    name="diagnostics",
    description="Ticket system health: channel counts, Mongo counts, orphans (Admin only)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Reconcile Discord channel state against Mongo ticket state."""

        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ You need Administrator permissions to use this command!",
                              ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        # Exactly two round trips regardless of ticket count. Deliberately NOT a
        # per-ticket fetch_channel loop - that is what got the startup orphan sweep
        # disabled in close.py for causing rate limits.
        guild_channels = await bot.rest.fetch_guild_channels(ctx.guild_id)
        docs = await mongo.button_store.find({"type": "ticket"}).to_list(length=None)

        live_ids = {_as_int(ch.id) for ch in guild_channels}
        live_names = {_as_int(ch.id): (ch.name or "") for ch in guild_channels}

        categories = {
            _as_int(ch.id): ch.name
            for ch in guild_channels
            if ch.type == hikari.ChannelType.GUILD_CATEGORY
        }
        per_category = Counter(
            _as_int(getattr(ch, "parent_id", None))
            for ch in guild_channels
            if getattr(ch, "parent_id", None)
        )

        by_status = Counter(d.get("status") or "(missing)" for d in docs)
        open_docs = [d for d in docs if d.get("status") == "open"]

        ghost_rows = [d for d in open_docs if _as_int(d.get("channel_id")) not in live_ids]
        live_open = [d for d in open_docs if _as_int(d.get("channel_id")) in live_ids]
        closed_name_open_status = [
            d for d in live_open
            if live_names.get(_as_int(d.get("channel_id")), "").startswith(CLOSED_EMOJI)
        ]

        tracked_ids = {_as_int(d.get("channel_id")) for d in docs}
        untracked = [
            ch for ch in guild_channels
            if TICKET_NAME_RE.match(ch.name or "") and _as_int(ch.id) not in tracked_ids
        ]

        total = len(guild_channels)
        lines = [
            "**Guild**",
            f"• Channels: **{total}/{GUILD_CHANNEL_CAP}** ({GUILD_CHANNEL_CAP - total} free)",
            f"• Categories: {len(categories)}",
            "",
            "**Fullest categories**",
        ]
        for cat_id, count in per_category.most_common(8):
            name = categories.get(cat_id, "(not a category / unknown)")
            flag = " ⚠️" if count >= 45 else ""
            lines.append(f"• {name} — {count}/50{flag}")

        lines += [
            "",
            "**Mongo `button_store` (type=ticket)**",
            f"• Documents: {len(docs)}",
            "• By status: " + ", ".join(f"`{k}`={v}" for k, v in sorted(by_status.items())),
            "",
            "**Open-ticket reconciliation**",
            f"• Marked open: **{len(open_docs)}**",
            f"• ├ channel still exists: {len(live_open)}",
            f"• ├ channel gone (ghost rows): **{len(ghost_rows)}**",
            f"• └ live but name shows ✅/❌ while status is open: **{len(closed_name_open_status)}**",
            "",
            f"**Ticket-like channels with no Mongo document:** {len(untracked)}",
        ]
        if untracked:
            for ch in untracked[:10]:
                lines.append(f"• {ch.name}")
            if len(untracked) > 10:
                lines.append(f"• …and {len(untracked) - 10} more")

        await ctx.respond(
            components=[
                Container(
                    accent_color=BLUE_ACCENT,
                    components=[
                        Text(content="🩺 **Ticket System Diagnostics**"),
                        Separator(divider=True),
                        Text(content=safe_text_content("\n".join(lines), "No data.")),
                        Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                    ]
                )
            ],
        )


@ticket.register()
class CleanupGhosts(
    lightbulb.SlashCommand,
    name="cleanup-ghosts",
    description="Close ticket rows whose Discord channel no longer exists (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm",
        "Actually write the changes. Omit or set false for a dry run.",
        default=False,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        """Reconcile open ticket rows against live channels; close the orphans."""

        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ You need Administrator permissions to use this command!",
                              ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        # Same two-round-trip reconciliation as /ticket diagnostics. Explicitly NOT a
        # per-ticket fetch_channel loop - that is what got the startup orphan sweep
        # disabled in close.py for causing rate limits.
        guild_channels = await bot.rest.fetch_guild_channels(ctx.guild_id)
        live_ids = {_as_int(ch.id) for ch in guild_channels}
        open_docs = await mongo.button_store.find(
            {"type": "ticket", "status": "open"}
        ).to_list(length=None)

        ghosts = [d for d in open_docs if _as_int(d.get("channel_id")) not in live_ids]

        if not ghosts:
            await ctx.respond(
                f"✅ Nothing to clean up — all {len(open_docs)} open ticket(s) still "
                f"have a live channel."
            )
            return

        header = f"👻 **{len(ghosts)} ghost row(s)** of {len(open_docs)} open tickets"
        sample = [
            f"• `{d.get('_id')}` — {d.get('ticket_type', '?')} #{d.get('ticket_number', '?')} "
            f"({d.get('username', 'unknown')})"
            for d in ghosts[:10]
        ]
        if len(ghosts) > 10:
            sample.append(f"• …and {len(ghosts) - 10} more")

        if not self.confirm:
            body = "\n".join([
                header,
                "",
                "**DRY RUN — nothing was written.**",
                "",
                *sample,
                "",
                "These rows point at channels that no longer exist in Discord. Re-run "
                "with `confirm: true` to mark them denied with reason "
                "`channel_deleted`. Documents are updated, never removed, so the audit "
                "trail survives. Snapshot the collection first.",
            ])
            await ctx.respond(
                components=[
                    Container(
                        accent_color=BLUE_ACCENT,
                        components=[
                            Text(content="🧹 **Ghost Row Cleanup**"),
                            Separator(divider=True),
                            Text(content=safe_text_content(body, "Nothing to report.")),
                            Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                        ]
                    )
                ],
            )
            return

        # Re-assert status == "open" in the filter so a row closed by a recruiter
        # between the read above and this write is not clobbered.
        result = await mongo.button_store.update_many(
            {"_id": {"$in": [d["_id"] for d in ghosts]}, "status": "open"},
            {"$set": {
                "status": "denied",
                "denied_at": datetime.now(timezone.utc),
                "denied_reason": "channel_deleted",
                "denied_by": ctx.user.id,
            }},
        )

        print(f"[Tickets] cleanup-ghosts by {ctx.user.username}: "
              f"{result.modified_count} row(s) closed as channel_deleted")

        body = "\n".join([
            header,
            "",
            f"✅ **Wrote {result.modified_count} row(s)** "
            f"(matched {result.matched_count}).",
            "",
            *sample,
            "",
            "Marked `denied` with reason `channel_deleted`. No Discord channels were "
            "touched. Run `/ticket diagnostics` to confirm the new counts.",
        ])
        await ctx.respond(
            components=[
                Container(
                    accent_color=BLUE_ACCENT,
                    components=[
                        Text(content="🧹 **Ghost Row Cleanup**"),
                        Separator(divider=True),
                        Text(content=safe_text_content(body, "Nothing to report.")),
                        Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                    ]
                )
            ],
        )


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