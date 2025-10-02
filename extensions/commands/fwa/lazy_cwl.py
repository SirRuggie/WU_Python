# extensions/commands/fwa/lazy_cwl.py
"""
LazyCWL Player Tracking System for WU-Python
Tracks FWA clan players during CWL to ensure they return for sync wars.
Train ⇨ Join ⇨ Attack ⇨ Return (15-30min tops)
"""

import uuid
import aiohttp
import hikari
import lightbulb
import coc
from datetime import datetime, timezone
from typing import Dict, List, Optional

from extensions.commands.fwa import loader, fwa
from extensions.components import register_action
from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GOLD_ACCENT, BLUE_ACCENT, GREEN_ACCENT
from utils.emoji import emojis
from utils.classes import Clan

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    LinkButtonBuilder as LinkButton,
)


async def get_discord_ids(player_tags: List[str]) -> Dict[str, Optional[str]]:
    """
    Call ClashKing API to get Discord IDs for player tags.

    Args:
        player_tags: List of player tags WITH # prefix

    Returns:
        Dict mapping player tags (with #) to Discord IDs or None
    """
    if not player_tags:
        return {}

    # Remove # prefix for API call
    clean_tags = [tag.lstrip('#') for tag in player_tags]

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.clashk.ing/discord_links",
                json=clean_tags,
                headers={'Content-Type': 'application/json'}
            ) as response:
                if response.status == 200:
                    result = await response.json()
                    # API returns with # prefix
                    return result
                else:
                    print(f"ClashKing API error {response.status}: {await response.text()}")
                    return {}
    except Exception as e:
        print(f"ClashKing API request failed: {e}")
        return {}


async def create_clan_selector_components(fwa_clans: List[Dict], action_prefix: str, action_id: str) -> List[Container]:
    """Create clan selector dropdown components."""
    if not fwa_clans:
        return [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ No FWA Clans Found"),
                    Text(content="No FWA clans are configured in the database."),
                ]
            )
        ]

    options = []
    for clan in fwa_clans:
        # Use Clan class to properly handle emoji
        c = Clan(data=clan)

        kwargs = {
            "label": c.name,
            "value": c.tag,
            "description": c.tag  # Just show the tag, not member count
        }

        # Add emoji if available
        if getattr(c, "partial_emoji", None):
            kwargs["emoji"] = c.partial_emoji

        options.append(SelectOption(**kwargs))

    return [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content=f"## 📊 Select FWA Clan"),
                Text(content="Choose the FWA clan to snapshot for CWL tracking:"),
                Separator(),
                ActionRow(
                    components=[
                        TextSelectMenu(
                            custom_id=f"{action_prefix}:{action_id}",
                            placeholder="Select an FWA clan...",
                            max_values=1,
                            options=options
                        )
                    ]
                )
            ]
        )
    ]


@fwa.register()
class LazyCwlSnapshot(
    lightbulb.SlashCommand,
    name="lazycwl-snapshot",
    description="Snapshot FWA clan players to track war participation during CWL"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get FWA clans from database
        fwa_clans = await mongo.clans.find({"type": "FWA"}).to_list(length=None)

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "snapshot",
            "user_id": ctx.member.id
        }
        await mongo.button_store.insert_one(data)

        components = await create_clan_selector_components(fwa_clans, "lazycwl_snapshot_select", action_id)
        await ctx.respond(components=components, ephemeral=True)


@fwa.register()
class LazyCwlPing(
    lightbulb.SlashCommand,
    name="lazycwl-ping",
    description="Ping players to return for FWA sync (Train⇨Join⇨Attack⇨Return 15-30min)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get active snapshots
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True
        }).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No Active Snapshots"),
                        Text(content="No active CWL snapshots found."),
                        Text(content="Use `/fwa lazycwl-snapshot` first to create snapshots."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "ping",
            "user_id": ctx.member.id
        }
        await mongo.button_store.insert_one(data)

        options = [
            SelectOption(
                label="🌍 ALL FWA CLANS",
                value="ALL",
                description=f"Ping all {len(snapshots)} active FWA clan snapshots",
                emoji="🌍"
            )
        ]

        for snapshot in snapshots:
            player_count = len(snapshot.get("players", []))
            options.append(
                SelectOption(
                    label=snapshot["clan_name"],
                    value=snapshot["_id"],
                    description=f"{snapshot['clan_tag']} • {player_count} players • {snapshot['snapshot_date'].strftime('%m/%d/%Y')}",
                    emoji=emojis.FWA.partial_emoji
                )
            )

        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## 📢 Select Snapshot to Ping"),
                    Text(content="Choose which clan snapshot to check for missing players:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_ping_select:{action_id}",
                                placeholder="Select a clan snapshot...",
                                max_values=1,
                                options=options
                            )
                        ]
                    )
                ]
            )
        ]

        await ctx.respond(components=components, ephemeral=True)


@fwa.register()
class LazyCwlStatus(
    lightbulb.SlashCommand,
    name="lazycwl-status",
    description="View active FWA LazyCWL snapshots for the current month"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True
        }).sort("snapshot_date", -1).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## 📊 No Active Snapshots"),
                        Text(content="No active FWA LazyCWL snapshots found."),
                        Text(content="Use `/fwa lazycwl-snapshot` to create your first snapshot."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        # Build status display
        components = [
            Text(content="## 📊 Active FWA LazyCWL Snapshots"),
            Separator(),
        ]

        total_players = 0
        for i, snapshot in enumerate(snapshots, 1):
            player_count = len(snapshot.get("players", []))
            total_players += player_count

            discord_ids = sum(1 for player in snapshot.get("players", []) if player.get("discord_id"))
            coverage = f"{discord_ids}/{player_count}" if player_count > 0 else "0/0"

            components.extend([
                Text(content=(
                    f"**{i}. {snapshot['clan_name']}** `{snapshot['clan_tag']}`\n"
                    f"• **Date:** {snapshot['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC')}\n"
                    f"• **Players:** {player_count}\n"
                    f"• **Discord Coverage:** {coverage}\n"
                    f"• **Created by:** <@{snapshot['created_by']}>"
                )),
                Separator(divider=False, spacing=hikari.SpacingType.SMALL),
            ])

        components.extend([
            Separator(),
            Text(content=f"**Total Active Snapshots:** {len(snapshots)}")
        ])

        if total_players > 0:
            components.append(Text(content=f"**Total Players Tracked:** {total_players}"))

        final_components = [Container(accent_color=BLUE_ACCENT, components=components)]
        await ctx.respond(components=final_components, ephemeral=True)


@fwa.register()
class LazyCwlReset(
    lightbulb.SlashCommand,
    name="lazycwl-reset",
    description="Deactivate all FWA LazyCWL snapshots (use after wars complete)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        active_count = await mongo.lazy_cwl_snapshots.count_documents({
            "active": True
        })

        if active_count == 0:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ℹ️ No Active Snapshots"),
                        Text(content="No active snapshots found to reset."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "reset",
            "user_id": ctx.member.id
        }
        await mongo.button_store.insert_one(data)

        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ⚠️ Confirm Reset"),
                    Text(content=f"This will deactivate **{active_count}** active LazyCWL snapshot(s)."),
                    Text(content="**This action cannot be undone.**"),
                    Separator(),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.DANGER,
                                custom_id=f"lazycwl_confirm_reset:{action_id}",
                                label="Confirm Reset",
                                emoji="🗑️"
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"lazycwl_cancel_reset:{action_id}",
                                label="Cancel",
                                emoji="❌"
                            ),
                        ]
                    )
                ]
            )
        ]

        await ctx.respond(components=components, ephemeral=True)


# ======================== COMPONENT HANDLERS ========================

@register_action("lazycwl_snapshot_select", no_return=True)
@lightbulb.di.with_di
async def handle_snapshot_select(
    ctx,
    action_id: str,
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle clan selection for snapshot creation."""
    clan_tag = ctx.interaction.values[0]

    try:
        # Fetch clan from CoC API
        clan = await coc_client.get_clan(clan_tag)
        if not clan:
            raise Exception(f"Clan {clan_tag} not found")

        # Prepare player tags for ClashKing API
        player_tags = [member.tag for member in clan.members]

        # Get Discord IDs from ClashKing
        discord_mapping = await get_discord_ids(player_tags)

        # Check if snapshot already exists
        existing = await mongo.lazy_cwl_snapshots.find_one({
            "clan_tag": clan_tag,
            "active": True
        })

        if existing:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ⚠️ Snapshot Already Exists"),
                        Text(content=f"An active snapshot for **{clan.name}** `{clan_tag}` already exists."),
                        Text(content=f"Created: {existing['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC')}"),
                        Text(content="Use `/fwa lazycwl-reset` to clear existing snapshots first."),
                    ]
                )
            ]
        else:
            # Create player data
            players = []
            discord_coverage = 0

            for member in clan.members:
                discord_id = discord_mapping.get(member.tag)
                if discord_id:
                    discord_coverage += 1

                players.append({
                    "tag": member.tag,
                    "name": member.name,
                    "th_level": member.town_hall,
                    "discord_id": discord_id,
                    "in_home_clan": True
                })

            # Create snapshot document
            snapshot = {
                "_id": str(uuid.uuid4()),
                "clan_tag": clan_tag,
                "clan_name": clan.name,
                "snapshot_date": datetime.now(timezone.utc),
                "month": current_month,
                "players": players,
                "active": True,
                "created_by": str(user_id)
            }

            # Insert into database
            await mongo.lazy_cwl_snapshots.insert_one(snapshot)

            # Success response
            coverage_percent = (discord_coverage / len(players) * 100) if players else 0
            components = [
                Container(
                    accent_color=GREEN_ACCENT,
                    components=[
                        Text(content="## ✅ Snapshot Created Successfully"),
                        Separator(),
                        Text(content=(
                            f"**Clan:** {clan.name} `{clan_tag}`\n"
                            f"**Players Tracked:** {len(players)}\n"
                            f"**Discord Coverage:** {discord_coverage}/{len(players)} ({coverage_percent:.1f}%)\n"
                            f"**Month:** {current_month}\n"
                            f"**Created:** {snapshot['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC')}"
                        )),
                        Separator(),
                        Text(content="✅ Players tracked for FWA. Use `/fwa lazycwl-ping` to remind players to return for sync."),
                    ]
                )
            ]

    except Exception as e:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Snapshot Creation Failed"),
                    Text(content=f"Failed to create snapshot for {clan_tag}:"),
                    Text(content=f"```{str(e)}```"),
                    Text(content="Please try again or contact support if the issue persists."),
                ]
            )
        ]

    await ctx.interaction.edit_initial_response(components=components)


async def process_single_snapshot_ping(
    snapshot: dict,
    bot: hikari.GatewayBot,
    coc_client: coc.Client,
    mongo: MongoClient
) -> dict:
    """
    Process a single snapshot and send ping if needed.
    Returns dict with results: {
        'success': bool,
        'clan_name': str,
        'missing_count': int,
        'total_count': int,
        'error': str (if failed)
    }
    """
    try:
        # Fetch clan data to get announcement channel
        clan_data = await mongo.clans.find_one({"tag": snapshot["clan_tag"]})
        if not clan_data:
            return {
                'success': False,
                'clan_name': snapshot.get('clan_name', 'Unknown'),
                'error': f"Clan data not found for {snapshot['clan_tag']}"
            }

        # Get announcement channel ID
        announcement_channel = clan_data.get("announcement_id")
        if not announcement_channel:
            return {
                'success': False,
                'clan_name': snapshot['clan_name'],
                'error': f"No announcement channel set"
            }

        # Get clan role ID for mentions
        clan_role_id = clan_data.get("role_id")

        # Get current clan members
        clan = await coc_client.get_clan(snapshot["clan_tag"])
        if not clan:
            return {
                'success': False,
                'clan_name': snapshot['clan_name'],
                'error': f"Clan not found in CoC API"
            }

        current_member_tags = {member.tag.upper() for member in clan.members}
        snapshot_players = snapshot.get("players", [])

        # Find missing players
        missing_players = []
        for player in snapshot_players:
            player_tag = player.get("tag", "").upper()
            if player_tag and player_tag not in current_member_tags:
                missing_players.append(player)

        # If no missing players, return success without sending message
        if not missing_players:
            return {
                'success': True,
                'clan_name': snapshot['clan_name'],
                'missing_count': 0,
                'total_count': len(snapshot_players),
                'all_present': True
            }

        # Create ping message for missing players
        ping_components = [
            Text(content=f"## 📢 FWA Sync War - Return to {snapshot['clan_name']}"),
            Separator(),
            Text(content=f"⚔️ **FWA SYNC WAR TIME** ⚔️"),
            Text(content=f"Please return to **{snapshot['clan_name']}** `{snapshot['clan_tag']}` for sync war!"),
            Separator(),
            Text(content="**📋 Workflow: Train ⇨ Join ⇨ Attack ⇨ Return (15-30min tops)**"),
            Separator(),
            Text(content="**Players to return:**")
        ]

        # Add individual player details
        for player in missing_players:
            player_name = player.get('name', 'Unknown')
            player_tag = player.get('tag', 'Unknown')
            discord_id = player.get('discord_id')

            if discord_id:
                discord_mention = f"<@{discord_id}>"
            else:
                discord_mention = "No Discord linked"

            ping_components.append(
                Text(content=f"**{player_name}** - `{player_tag}` - {discord_mention}")
            )

        # Add total count and link
        ping_components.extend([
            Separator(),
            Text(content=f"**Total missing:** {len(missing_players)}/{len(snapshot_players)} players"),
            Separator(),
            ActionRow(
                components=[
                    LinkButton(
                        url=f"https://link.clashofclans.com/en?action=OpenClanProfile&tag={snapshot['clan_tag'].replace('#', '%23')}",
                        label=f"Open {snapshot['clan_name']} in-Game",
                        emoji="🔗"
                    )
                ]
            )
        ])

        # Send to clan's announcement channel with role ping
        role_mentions = [int(clan_role_id)] if clan_role_id else []
        await bot.rest.create_message(
            channel=announcement_channel,
            components=[Container(accent_color=GOLD_ACCENT, components=ping_components)],
            user_mentions=True,
            role_mentions=role_mentions
        )

        return {
            'success': True,
            'clan_name': snapshot['clan_name'],
            'missing_count': len(missing_players),
            'total_count': len(snapshot_players),
            'all_present': False
        }

    except Exception as e:
        return {
            'success': False,
            'clan_name': snapshot.get('clan_name', 'Unknown'),
            'error': str(e)
        }


@register_action("lazycwl_ping_select", no_return=True)
@lightbulb.di.with_di
async def handle_ping_select(
    ctx,
    action_id: str,
    user_id: int,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle snapshot selection for pinging missing players."""
    selection = ctx.interaction.values[0]

    try:
        if selection == "ALL":
            # Process all active snapshots
            snapshots = await mongo.lazy_cwl_snapshots.find({"active": True}).to_list(length=None)

            if not snapshots:
                components = [
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content="## ❌ No Active Snapshots"),
                            Text(content="No active snapshots found to ping."),
                        ]
                    )
                ]
                await ctx.interaction.edit_initial_response(components=components)
                return

            # Process each snapshot
            results = []
            for snapshot in snapshots:
                result = await process_single_snapshot_ping(snapshot, bot, coc_client, mongo)
                results.append(result)

            # Build summary response
            total_clans = len(results)
            successful = sum(1 for r in results if r['success'])
            failed = sum(1 for r in results if not r['success'])
            total_missing = sum(r.get('missing_count', 0) for r in results if r['success'])
            clans_all_present = sum(1 for r in results if r.get('all_present', False))

            summary_parts = [
                Text(content="## 📤 All Clans Ping Complete"),
                Separator(),
                Text(content=(
                    f"**Total Clans Processed:** {total_clans}\n"
                    f"**Successful:** {successful}\n"
                    f"**Failed:** {failed}\n"
                    f"**Clans with all players present:** {clans_all_present}\n"
                    f"**Total missing players:** {total_missing}"
                )),
                Separator(),
                Text(content="**Clan Details:**")
            ]

            for result in results:
                if result['success']:
                    if result.get('all_present'):
                        summary_parts.append(
                            Text(content=f"✅ **{result['clan_name']}**: All players present ({result['total_count']} players)")
                        )
                    else:
                        summary_parts.append(
                            Text(content=f"📢 **{result['clan_name']}**: {result['missing_count']}/{result['total_count']} missing - Ping sent")
                        )
                else:
                    summary_parts.append(
                        Text(content=f"❌ **{result['clan_name']}**: {result.get('error', 'Unknown error')}")
                    )

            components = [Container(accent_color=GOLD_ACCENT, components=summary_parts)]

        else:
            # Process single snapshot (existing logic)
            snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": selection})
            if not snapshot:
                raise Exception("Snapshot not found")

            result = await process_single_snapshot_ping(snapshot, bot, coc_client, mongo)

            if not result['success']:
                components = [
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content="## ❌ Ping Failed"),
                            Text(content=f"Failed to process **{result['clan_name']}**:"),
                            Text(content=f"```{result.get('error', 'Unknown error')}```"),
                        ]
                    )
                ]
            elif result.get('all_present'):
                components = [
                    Container(
                        accent_color=GREEN_ACCENT,
                        components=[
                            Text(content="## 🎉 All Players Are Ready!"),
                            Text(content=f"All **{result['total_count']}** players from **{result['clan_name']}** are in their FWA home clan."),
                            Text(content="✅ Ready for FWA sync!"),
                        ]
                    )
                ]
            else:
                components = [
                    Container(
                        accent_color=GOLD_ACCENT,
                        components=[
                            Text(content="## 📤 Ping Message Sent"),
                            Separator(),
                            Text(content=(
                                f"**Clan:** {result['clan_name']}\n"
                                f"**Missing Players:** {result['missing_count']}/{result['total_count']}"
                            )),
                            Separator(),
                            Text(content="✅ Public ping message has been sent to the clan's announcement channel."),
                        ]
                    )
                ]

    except Exception as e:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Ping Failed"),
                    Text(content=f"Failed to process ping request:"),
                    Text(content=f"```{str(e)}```"),
                ]
            )
        ]

    await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_confirm_reset", no_return=True)
@lightbulb.di.with_di
async def handle_confirm_reset(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle confirmation of snapshot reset."""

    try:
        # Deactivate all active snapshots
        result = await mongo.lazy_cwl_snapshots.update_many(
            {"active": True},
            {"$set": {"active": False}}
        )

        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ Reset Complete"),
                    Separator(),
                    Text(content=(
                        f"**Snapshots Deactivated:** {result.modified_count}\n"
                        f"**Status:** All FWA LazyCWL snapshots have been reset."
                    )),
                    Separator(),
                    Text(content="✅ You can now create new snapshots for the next LazyCWL season."),
                ]
            )
        ]

    except Exception as e:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Reset Failed"),
                    Text(content=f"Failed to reset snapshots:"),
                    Text(content=f"```{str(e)}```"),
                    Text(content="Please try again or contact support if the issue persists."),
                ]
            )
        ]

    await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_cancel_reset", no_return=True)
async def handle_cancel_reset(ctx, action_id: str, **kwargs) -> None:
    """Handle cancellation of snapshot reset."""

    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## ❌ Reset Cancelled"),
                Text(content="Snapshot reset has been cancelled. No changes were made."),
            ]
        )
    ]

    await ctx.interaction.edit_initial_response(components=components)


# Register the commands with the loader
loader.command(fwa)