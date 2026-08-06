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
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from pymongo.errors import DuplicateKeyError

from extensions.commands.fwa import loader, fwa
from extensions.components import register_action
from utils.component_state import insert_state
from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler
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

# Global variables for auto-ping system
scheduler: Optional[AsyncIOScheduler] = None
bot_instance: Optional[hikari.GatewayBot] = None
coc_client: Optional[coc.Client] = None
mongo_client: Optional[MongoClient] = None
startup_reconciler: Optional[StartupReconciler] = None

AUTOPING_JOB_DEFAULTS = {
    "coalesce": True,
    "max_instances": 1,
    "misfire_grace_time": 300,
}
ACTIVE_SNAPSHOT_INDEX = "one_active_lazy_cwl_snapshot_per_clan"


def _as_utc(value: Optional[datetime]) -> Optional[datetime]:
    """Return a timezone-aware UTC datetime without changing the instant."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def calculate_next_autoping_run(
    snapshot: dict,
    now: Optional[datetime] = None,
) -> datetime:
    """Find the next future run while preserving the persisted cadence.

    Missed intervals are skipped rather than replayed after a reboot. The next
    run remains aligned to the most recent successful check (or the original
    start time for a job that has never run).
    """
    now = _as_utc(now) or datetime.now(timezone.utc)
    interval_minutes = max(1, int(snapshot.get("auto_ping_interval_minutes", 60)))
    interval = timedelta(minutes=interval_minutes)
    anchor = (
        _as_utc(snapshot.get("last_auto_ping_at"))
        or _as_utc(snapshot.get("auto_ping_started_at"))
        or now
    )

    next_run = anchor + interval
    if next_run <= now:
        missed_intervals = ((now - anchor) // interval) + 1
        next_run = anchor + (interval * missed_intervals)

    return next_run


async def rollback_failed_autoping_start(mongo: MongoClient, snapshot_id) -> None:
    """Keep Mongo from advertising an auto-ping whose job was never created."""
    await mongo.lazy_cwl_snapshots.update_one(
        {"_id": snapshot_id},
        {
            "$set": {"auto_ping_enabled": False},
            "$unset": {"auto_ping_job_id": ""},
        },
    )


async def ensure_snapshot_invariants(mongo: MongoClient) -> None:
    """Repair legacy state and enforce one active snapshot per clan.

    Older data can contain inactive snapshots with auto-ping still enabled and
    more than one active snapshot for the same clan. Keep the newest active
    snapshot deterministically, deactivate the rest, then let MongoDB enforce
    the invariant for concurrent command invocations.
    """
    await mongo.lazy_cwl_snapshots.update_many(
        {"active": {"$ne": True}, "auto_ping_enabled": True},
        {"$set": {"auto_ping_enabled": False}},
    )

    active_snapshots = await mongo.lazy_cwl_snapshots.find(
        {"active": True, "clan_tag": {"$type": "string"}}
    ).to_list(length=None)

    by_clan: Dict[str, List[dict]] = {}
    for snapshot in active_snapshots:
        by_clan.setdefault(snapshot["clan_tag"].upper(), []).append(snapshot)

    for clan_snapshots in by_clan.values():
        def snapshot_order(snapshot: dict) -> tuple[datetime, str]:
            created = _as_utc(snapshot.get("snapshot_date")) or datetime.min.replace(
                tzinfo=timezone.utc
            )
            return created, str(snapshot.get("_id", ""))

        clan_snapshots.sort(key=snapshot_order, reverse=True)
        for duplicate in clan_snapshots[1:]:
            await mongo.lazy_cwl_snapshots.update_one(
                {"_id": duplicate["_id"]},
                {"$set": {"active": False, "auto_ping_enabled": False}},
            )

        winner = clan_snapshots[0]
        normalized_tag = winner["clan_tag"].upper()
        if winner["clan_tag"] != normalized_tag:
            await mongo.lazy_cwl_snapshots.update_one(
                {"_id": winner["_id"]},
                {"$set": {"clan_tag": normalized_tag}},
            )

    await mongo.lazy_cwl_snapshots.create_index(
        [("clan_tag", 1)],
        name=ACTIVE_SNAPSHOT_INDEX,
        unique=True,
        partialFilterExpression={
            "active": True,
            "clan_tag": {"$type": "string"},
        },
    )


async def get_discord_ids(player_tags: List[str]) -> Optional[Dict[str, Optional[str]]]:
    """
    Call ClashKing API to get Discord IDs for player tags.

    Args:
        player_tags: List of player tags WITH # prefix

    Returns:
        Dict mapping player tags (with #) to Discord IDs or None,
        or **None if the lookup itself failed**.

    A FAILED LOOKUP AND AN EMPTY RESULT ARE DIFFERENT THINGS AND CALLERS MUST
    TELL THEM APART. This previously returned {} for both, and the caller could
    not distinguish "ClashKing is down" from "nobody in this clan has linked".
    The snapshot was written either way, with discord_id None on every player,
    and every downstream auto-ping then silently pinged nobody. Nothing raised
    and nothing warned; the bad snapshot persisted until deleted by hand.

        None  -> the call failed. The answer is unknown. Do not persist.
        {}    -> the call succeeded and nobody is linked. A real answer.
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
                    return None
    except Exception as e:
        print(f"ClashKing API request failed: {e}")
        return None


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

        if not fwa_clans:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No FWA Clans Found"),
                        Text(content="No FWA clans are configured in the database."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "snapshot",
            "user_id": ctx.member.id
        }
        await insert_state(mongo, data)

        # Build dropdown options with ALL option first
        options = [
            SelectOption(
                label="🌍 ALL FWA CLANS",
                value="ALL",
                description=f"Create snapshots for all {len(fwa_clans)} FWA clans",
                emoji="🌍"
            )
        ]

        # Add individual clan options
        for clan in fwa_clans:
            # Use Clan class to properly handle emoji
            c = Clan(data=clan)

            kwargs = {
                "label": c.name,
                "value": c.tag,
                "description": c.tag
            }

            # Add emoji if available
            if getattr(c, "partial_emoji", None):
                kwargs["emoji"] = c.partial_emoji

            options.append(SelectOption(**kwargs))

        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"## 📊 Select FWA Clan"),
                    Text(content="Choose the FWA clan to snapshot for CWL tracking:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_snapshot_select:{action_id}",
                                placeholder="Select an FWA clan...",
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
        await insert_state(mongo, data)

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
class LazyCwlRoster(
    lightbulb.SlashCommand,
    name="lazycwl-roster",
    description="View all players in a LazyCWL snapshot roster"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get all active snapshots
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True
        }).sort("snapshot_date", -1).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No Active Snapshots"),
                        Text(content="No active LazyCWL snapshots found."),
                        Text(content="Use `/fwa lazycwl-snapshot` to create your first snapshot."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "roster",
            "user_id": ctx.member.id
        }
        await insert_state(mongo, data)

        # Build dropdown options
        options = []
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
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## 📋 Select Snapshot to View Roster"),
                    Text(content="Choose which clan snapshot roster to display:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_roster_select:{action_id}",
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

        # Get all active snapshots
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True
        }).sort("snapshot_date", -1).to_list(length=None)

        if not snapshots:
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
        await insert_state(mongo, data)

        # Build dropdown options with ALL option first
        options = [
            SelectOption(
                label="🌍 ALL SNAPSHOTS",
                value="ALL",
                description=f"Reset all {len(snapshots)} active snapshots",
                emoji="🗑️"
            )
        ]

        # Add individual snapshot options
        for snapshot in snapshots:
            player_count = len(snapshot.get("players", []))
            auto_ping_indicator = " 🔔" if snapshot.get("auto_ping_enabled") else ""

            options.append(
                SelectOption(
                    label=f"{snapshot['clan_name']}{auto_ping_indicator}",
                    value=snapshot["_id"],
                    description=f"{snapshot['clan_tag']} • {player_count} players • {snapshot['snapshot_date'].strftime('%m/%d/%Y')}",
                    emoji=emojis.FWA.partial_emoji
                )
            )

        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## 🗑️ Select Snapshot to Reset"),
                    Text(content="Choose which snapshot(s) to deactivate:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_reset_select:{action_id}",
                                placeholder="Select a snapshot to reset...",
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
class LazyCwlAutopingsStart(
    lightbulb.SlashCommand,
    name="lazycwl-autopings-start",
    description="Start automated periodic pinging for missing players (runs for 7 days)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get active snapshots without auto-ping enabled
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True,
            "$or": [
                {"auto_ping_enabled": {"$exists": False}},
                {"auto_ping_enabled": False}
            ]
        }).sort("snapshot_date", -1).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No Available Snapshots"),
                        Text(content="No active snapshots found without auto-ping enabled."),
                        Text(content="Use `/fwa lazycwl-snapshot` to create a snapshot first."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "autopings_start",
            "user_id": ctx.member.id
        }
        await insert_state(mongo, data)

        # Build dropdown options
        options = []
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

        # ALL goes FIRST, matching lazycwl-snapshot / -ping / -reset. It is one
        # option, so the 25-option ceiling drops to 24 clans. Nothing here
        # truncates - see docs.
        options.insert(0, SelectOption(
            label="🌍 ALL FWA CLANS",
            value="ALL",
            description=f"Start auto-ping for all {len(snapshots)} snapshots",
            emoji="🌍"
        ))

        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content="## 🔔 Start Auto-Ping"),
                    Text(content="Select a snapshot to enable automated pinging, or ALL for every clan:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_autopings_select_snapshot:{action_id}",
                                placeholder="Select a snapshot...",
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
class LazyCwlAutopingsStop(
    lightbulb.SlashCommand,
    name="lazycwl-autopings-stop",
    description="Stop automated periodic pinging for a snapshot"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get snapshots with auto-ping enabled
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True,
            "auto_ping_enabled": True
        }).sort("snapshot_date", -1).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No Active Auto-Pings"),
                        Text(content="No snapshots currently have auto-ping enabled."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "autopings_stop",
            "user_id": ctx.member.id
        }
        await insert_state(mongo, data)

        # Build dropdown options with ALL option first, matching
        # lazycwl-snapshot / -ping / -reset.
        options = [
            SelectOption(
                label="🌍 ALL FWA CLANS",
                value="ALL",
                description=f"Stop auto-ping for all {len(snapshots)} snapshots",
                emoji="🌍"
            )
        ]
        for snapshot in snapshots:
            interval = snapshot.get("auto_ping_interval_minutes", 60)
            started = snapshot.get("auto_ping_started_at")
            started_str = started.strftime("%m/%d %I:%M%p") if started else "Unknown"

            options.append(
                SelectOption(
                    label=snapshot["clan_name"],
                    value=snapshot["_id"],
                    description=f"{snapshot['clan_tag']} • {interval}min interval • Started {started_str}",
                    emoji=emojis.FWA.partial_emoji
                )
            )

        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## 🛑 Stop Auto-Ping"),
                    Text(content="Select a snapshot to disable automated pinging, or ALL for every clan:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_autopings_stop_select:{action_id}",
                                placeholder="Select a snapshot...",
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
class LazyCwlAutopingsStatus(
    lightbulb.SlashCommand,
    name="lazycwl-autopings-status",
    description="View status of all active auto-pings"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get all snapshots with auto-ping enabled
        try:
            snapshots = await mongo.lazy_cwl_snapshots.find({
                "active": True,
                "auto_ping_enabled": True
            }).sort("auto_ping_started_at", -1).to_list(length=None)
        except Exception as exc:
            recovery_status = (
                startup_reconciler.status_text()
                if startup_reconciler is not None
                else "⏹️ Stopped"
            )
            await ctx.respond(
                components=[Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ⚠️ Auto-Ping Status Unavailable"),
                        Text(content=f"**Startup recovery:** {recovery_status}"),
                        Text(content=f"**MongoDB:** Unavailable ({type(exc).__name__})"),
                    ],
                )],
                ephemeral=True,
            )
            return

        if not snapshots:
            recovery_status = (
                startup_reconciler.status_text()
                if startup_reconciler is not None
                else "⏹️ Stopped"
            )
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## 📊 No Active Auto-Pings"),
                        Text(content="No snapshots currently have auto-ping enabled."),
                        Text(content=f"**Startup recovery:** {recovery_status}"),
                        Text(content="Use `/fwa lazycwl-autopings-start` to enable auto-ping for a snapshot."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        # Build status display
        components_list = [
            Text(content="## 📊 Active Auto-Ping Status"),
            Separator(),
        ]

        now = datetime.now(timezone.utc)
        scheduled_jobs = sum(
            1
            for snapshot in snapshots
            if scheduler is not None
            and scheduler.get_job(f"autopings_{snapshot['_id']}") is not None
        )
        recovery_status = (
            startup_reconciler.status_text()
            if startup_reconciler is not None
            else "⏹️ Stopped"
        )

        for i, snapshot in enumerate(snapshots, 1):
            interval = snapshot.get("auto_ping_interval_minutes", 60)
            started = snapshot.get("auto_ping_started_at")
            last_ping = snapshot.get("last_auto_ping_at")
            ping_count = snapshot.get("auto_ping_count", 0)

            if started:
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)

                elapsed = now - started
                remaining = timedelta(days=7) - elapsed

                # Calculate days, hours, minutes remaining
                days = remaining.days
                hours, remainder = divmod(remaining.seconds, 3600)
                minutes, _ = divmod(remainder, 60)

                if remaining.total_seconds() > 0:
                    time_left = f"{days}d {hours}h {minutes}m"
                    expires_at = started + timedelta(days=7)
                else:
                    time_left = "Expired"
                    expires_at = started + timedelta(days=7)
            else:
                time_left = "Unknown"
                expires_at = None

            last_ping_str = last_ping.strftime("%m/%d %I:%M%p UTC") if last_ping else "Not yet"

            components_list.extend([
                Text(content=(
                    f"**{i}. {snapshot['clan_name']}** `{snapshot['clan_tag']}`\n"
                    f"• **Interval:** Every {interval} minutes\n"
                    f"• **Started:** {started.strftime('%B %d, %I:%M %p UTC') if started else 'Unknown'}\n"
                    f"• **Expires:** {expires_at.strftime('%B %d, %I:%M %p UTC') if expires_at else 'Unknown'}\n"
                    f"• **Time Remaining:** {time_left}\n"
                    f"• **Last Ping:** {last_ping_str}\n"
                    f"• **Total Pings:** {ping_count}"
                )),
                Separator(divider=False, spacing=hikari.SpacingType.SMALL),
            ])

        components_list.extend([
            Separator(),
            Text(content=f"**Total Active Auto-Pings:** {len(snapshots)}"),
            Text(content=f"**Scheduled Jobs:** {scheduled_jobs}/{len(snapshots)}"),
            Text(content=f"**Startup Recovery:** {recovery_status}"),
            Separator(),
            Text(content="Use `/fwa lazycwl-autopings-stop` to disable auto-ping for a snapshot."),
        ])

        final_components = [Container(accent_color=BLUE_ACCENT, components=components_list)]
        await ctx.respond(components=final_components, ephemeral=True)


@fwa.register()
class LazyCwlRemovePlayer(
    lightbulb.SlashCommand,
    name="lazycwl-remove-player",
    description="Remove player(s) from a snapshot to stop auto-pinging them"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Get all active snapshots
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True
        }).sort("snapshot_date", -1).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No Active Snapshots"),
                        Text(content="No active snapshots found. Create a snapshot first with `/fwa lazycwl-snapshot`."),
                    ]
                )
            ]
            await ctx.respond(components=components, ephemeral=True)
            return

        # Create action for button store
        action_id = str(uuid.uuid4())
        data = {
            "_id": action_id,
            "command": "remove_player",
            "user_id": ctx.member.id
        }
        await insert_state(mongo, data)

        # Build snapshot options
        options = []
        for snapshot in snapshots:
            player_count = len(snapshot.get("players", []))
            snapshot_date = snapshot.get("snapshot_date")
            date_str = snapshot_date.strftime("%m/%d %I:%M%p") if snapshot_date else "Unknown"
            auto_ping_status = "🔔 Auto-ping ON" if snapshot.get("auto_ping_enabled") else ""

            description_parts = [f"{snapshot['clan_tag']} • {player_count} players • {date_str}"]
            if auto_ping_status:
                description_parts.append(auto_ping_status)

            options.append(
                SelectOption(
                    label=snapshot["clan_name"],
                    value=snapshot["_id"],
                    description=" • ".join(description_parts),
                    emoji=emojis.FWA.partial_emoji
                )
            )

        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## 🗑️ Remove Player from Snapshot"),
                    Text(content="Select a snapshot to remove players from:"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_remove_player_select_snapshot:{action_id}",
                                placeholder="Select a snapshot...",
                                max_values=1,
                                options=options
                            )
                        ]
                    )
                ]
            )
        ]

        await ctx.respond(components=components, ephemeral=True)


# ======================== HELPER FUNCTIONS ========================


async def process_single_clan_snapshot(
    clan_tag: str,
    user_id: int,
    coc_client: coc.Client,
    mongo: MongoClient
) -> dict:
    """
    Process a single clan snapshot creation.
    Returns dict with results: {
        'success': bool,
        'clan_name': str,
        'clan_tag': str,
        'player_count': int,
        'discord_coverage': int,
        'coverage_percent': float,
        'already_exists': bool (if True),
        'error': str (if failed)
    }
    """
    try:
        clan_tag = clan_tag.upper()

        # Fetch clan from CoC API
        clan = await coc_client.get_clan(clan_tag)
        if not clan:
            return {
                'success': False,
                'clan_name': 'Unknown',
                'clan_tag': clan_tag,
                'error': f"Clan {clan_tag} not found"
            }

        # Prepare player tags for ClashKing API
        player_tags = [member.tag for member in clan.members]

        # Get Discord IDs from ClashKing.
        # None means the lookup failed, NOT that nobody is linked. Persisting a
        # snapshot in that state produces one with discord_id None on every
        # player, which every downstream auto-ping then reads as "nobody to
        # ping" - silently, forever, until someone deletes it by hand. Fail the
        # snapshot instead; it is retried by re-running the command.
        discord_mapping = await get_discord_ids(player_tags)
        if discord_mapping is None:
            return {
                'success': False,
                'clan_name': clan.name,
                'clan_tag': clan_tag,
                'error': (
                    "Could not reach the ClashKing link API, so Discord mentions "
                    "could not be resolved. No snapshot was saved - try again shortly."
                )
            }

        # Check if snapshot already exists
        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        existing = await mongo.lazy_cwl_snapshots.find_one({
            "clan_tag": clan_tag,
            "active": True
        })

        if existing:
            return {
                'success': False,
                'clan_name': clan.name,
                'clan_tag': clan_tag,
                'already_exists': True,
                'existing_date': existing['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC')
            }

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

        # Return success
        coverage_percent = (discord_coverage / len(players) * 100) if players else 0
        return {
            'success': True,
            'clan_name': clan.name,
            'clan_tag': clan_tag,
            'player_count': len(players),
            'discord_coverage': discord_coverage,
            'coverage_percent': coverage_percent,
            'snapshot_date': snapshot['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC'),
            'month': current_month
        }

    except DuplicateKeyError:
        # The partial unique index is the final guard against two recruiters
        # creating an active snapshot for the same clan at the same time.
        existing = await mongo.lazy_cwl_snapshots.find_one({
            "clan_tag": clan_tag,
            "active": True,
        })
        existing_date = existing.get("snapshot_date") if existing else None
        return {
            'success': False,
            'clan_name': getattr(clan, "name", "Unknown"),
            'clan_tag': clan_tag,
            'already_exists': True,
            'existing_date': (
                existing_date.strftime('%B %d, %Y at %I:%M %p UTC')
                if existing_date else 'Unknown'
            ),
        }
    except Exception as e:
        return {
            'success': False,
            'clan_name': 'Unknown',
            'clan_tag': clan_tag,
            'error': str(e)
        }


async def process_single_autoping_start(
    snapshot: dict,
    interval_minutes: int,
    jitter_index: int,
    mongo: MongoClient,
    scheduler_instance: Optional[AsyncIOScheduler]
) -> dict:
    """Start auto-ping for ONE snapshot. NEVER RAISES.

    Returns the same {'success', 'clan_name', 'clan_tag', 'error'} shape
    process_single_snapshot_reset returns, so the ALL summary renderer is
    identical for both and there is no second reporting format to drift.

    JITTER. Seven jobs created in the same second fire together forever after,
    and EVERY LazyCWL ping goes to one hardcoded channel (the constant inside
    perform_lazy_cwl_ping), so they land in the same
    POST /channels/{id}/messages bucket rather than spreading across clans.
    Staggering the first run 5s per clan keeps that bucket off the ropes.
    """
    snapshot_id = snapshot["_id"]
    clan_name = snapshot.get("clan_name", "Unknown")
    clan_tag = snapshot.get("clan_tag", "?")

    try:
        if not scheduler_instance:
            raise Exception("Scheduler not initialized")

        # Re-read rather than trusting the list the menu was built from: the
        # per-clan path may have enabled this one between the menu render and
        # the confirm press.
        current = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not current:
            raise Exception("Snapshot not found")
        if not current.get("active"):
            raise Exception("Snapshot is no longer active")
        if current.get("auto_ping_enabled"):
            raise Exception("Auto-ping already enabled")

        now = datetime.now(timezone.utc)

        await mongo.lazy_cwl_snapshots.update_one(
            {"_id": snapshot_id},
            {
                "$set": {
                    "auto_ping_enabled": True,
                    "auto_ping_started_at": now,
                    "auto_ping_interval_minutes": interval_minutes,
                    "auto_ping_job_id": f"autopings_{snapshot_id}",
                    "last_auto_ping_at": None,
                    "auto_ping_count": 0
                }
            }
        )

        try:
            scheduler_instance.add_job(
                auto_ping_job,
                trigger=IntervalTrigger(minutes=interval_minutes),
                args=[snapshot_id],
                id=f"autopings_{snapshot_id}",
                replace_existing=True,
                next_run_time=now + timedelta(seconds=jitter_index * 5),
                **AUTOPING_JOB_DEFAULTS,
            )
        except Exception:
            await rollback_failed_autoping_start(mongo, snapshot_id)
            raise

        print(f"[LazyCWL AutoPing] Started auto-ping for {clan_name} "
              f"(interval: {interval_minutes}min, first run +{jitter_index * 5}s)")

        return {'success': True, 'clan_name': clan_name, 'clan_tag': clan_tag}

    except Exception as e:  # noqa: BLE001 - one clan must not abort the batch
        print(f"[LazyCWL AutoPing] Failed to start auto-ping for {clan_name}: {e}")
        return {'success': False, 'clan_name': clan_name, 'clan_tag': clan_tag,
                'error': str(e)}


async def process_single_autoping_stop(
    snapshot: dict,
    mongo: MongoClient,
    scheduler_instance: Optional[AsyncIOScheduler]
) -> dict:
    """Stop auto-ping for ONE snapshot. NEVER RAISES.

    A missing scheduler job is NOT a failure, matching the per-clan handler's
    tolerance. The Mongo flag is the source of truth for whether auto-ping is
    on; the job lives in an in-memory APScheduler with no jobstore and does not
    survive a restart, so "job already gone" is an ordinary state.
    """
    snapshot_id = snapshot["_id"]
    clan_name = snapshot.get("clan_name", "Unknown")
    clan_tag = snapshot.get("clan_tag", "?")

    try:
        await mongo.lazy_cwl_snapshots.update_one(
            {"_id": snapshot_id},
            {"$set": {"auto_ping_enabled": False}}
        )

        if scheduler_instance:
            try:
                scheduler_instance.remove_job(f"autopings_{snapshot_id}")
            except Exception as e:  # noqa: BLE001
                print(f"[LazyCWL AutoPing] Job not found or already removed "
                      f"for {clan_name}: {e}")

        print(f"[LazyCWL AutoPing] Stopped auto-ping for {clan_name}")
        return {'success': True, 'clan_name': clan_name, 'clan_tag': clan_tag,
                'ping_count': snapshot.get("auto_ping_count", 0)}

    except Exception as e:  # noqa: BLE001 - one clan must not abort the batch
        print(f"[LazyCWL AutoPing] Failed to stop auto-ping for {clan_name}: {e}")
        return {'success': False, 'clan_name': clan_name, 'clan_tag': clan_tag,
                'error': str(e)}


async def process_single_snapshot_reset(
    snapshot_id: str,
    mongo: MongoClient,
    scheduler_instance: Optional[AsyncIOScheduler]
) -> dict:
    """
    Process a single snapshot reset (deactivation).
    Returns dict with results: {
        'success': bool,
        'clan_name': str,
        'clan_tag': str,
        'player_count': int,
        'autopings_cancelled': bool,
        'error': str (if failed)
    }
    """
    try:
        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            return {
                'success': False,
                'clan_name': 'Unknown',
                'error': 'Snapshot not found'
            }

        clan_name = snapshot.get('clan_name', 'Unknown')
        clan_tag = snapshot.get('clan_tag', 'Unknown')
        player_count = len(snapshot.get('players', []))
        autopings_cancelled = False

        # Cancel auto-ping job if enabled
        if snapshot.get('auto_ping_enabled') and scheduler_instance:
            try:
                scheduler_instance.remove_job(f"autopings_{snapshot_id}")
                autopings_cancelled = True
                print(f"[LazyCWL Reset] Cancelled auto-ping for {clan_name}")
            except Exception as e:
                print(f"[LazyCWL Reset] Failed to cancel auto-ping: {e}")

        # Deactivate snapshot
        result = await mongo.lazy_cwl_snapshots.update_one(
            {"_id": snapshot_id},
            {"$set": {"active": False, "auto_ping_enabled": False}}
        )

        if result.modified_count == 0:
            return {
                'success': False,
                'clan_name': clan_name,
                'clan_tag': clan_tag,
                'error': 'Failed to deactivate snapshot'
            }

        return {
            'success': True,
            'clan_name': clan_name,
            'clan_tag': clan_tag,
            'player_count': player_count,
            'autopings_cancelled': autopings_cancelled
        }

    except Exception as e:
        return {
            'success': False,
            'clan_name': 'Unknown',
            'error': str(e)
        }


# ======================== COMPONENT HANDLERS ========================

@register_action("lazycwl_snapshot_select", no_return=True, requires_state=True)
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
    selection = ctx.interaction.values[0]

    try:
        if selection == "ALL":
            # Process all FWA clans
            fwa_clans = await mongo.clans.find({"type": "FWA"}).to_list(length=None)

            if not fwa_clans:
                components = [
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content="## ❌ No FWA Clans Found"),
                            Text(content="No FWA clans found to snapshot."),
                        ]
                    )
                ]
                await ctx.interaction.edit_initial_response(components=components)
                return

            # Process each clan
            results = []
            for clan_data in fwa_clans:
                c = Clan(data=clan_data)
                result = await process_single_clan_snapshot(c.tag, user_id, coc_client, mongo)
                results.append(result)

            # Build summary response
            total_clans = len(results)
            successful = sum(1 for r in results if r['success'])
            failed = sum(1 for r in results if not r['success'])
            already_exist = sum(1 for r in results if r.get('already_exists', False))
            total_players = sum(r.get('player_count', 0) for r in results if r['success'])
            total_coverage = sum(r.get('discord_coverage', 0) for r in results if r['success'])

            summary_parts = [
                Text(content="## 📊 All Clans Snapshot Complete"),
                Separator(),
                Text(content=(
                    f"**Total Clans Processed:** {total_clans}\n"
                    f"**Successfully Created:** {successful}\n"
                    f"**Already Existed:** {already_exist}\n"
                    f"**Failed:** {failed}\n"
                    f"**Total Players Tracked:** {total_players}\n"
                    f"**Total Discord Coverage:** {total_coverage}"
                )),
                Separator(),
                Text(content="**Clan Details:**")
            ]

            for result in results:
                if result['success']:
                    summary_parts.append(
                        Text(content=(
                            f"✅ **{result['clan_name']}** `{result['clan_tag']}`\n"
                            f"   • Players: {result['player_count']}\n"
                            f"   • Discord: {result['discord_coverage']}/{result['player_count']} ({result['coverage_percent']:.1f}%)"
                        ))
                    )
                elif result.get('already_exists'):
                    summary_parts.append(
                        Text(content=(
                            f"⚠️ **{result['clan_name']}** `{result['clan_tag']}`\n"
                            f"   • Already exists (created {result.get('existing_date', 'unknown')})"
                        ))
                    )
                else:
                    summary_parts.append(
                        Text(content=f"❌ **{result['clan_name']}** `{result['clan_tag']}`: {result.get('error', 'Unknown error')}")
                    )

            components = [Container(accent_color=BLUE_ACCENT, components=summary_parts)]

        else:
            # Process single clan
            clan_tag = selection
            result = await process_single_clan_snapshot(clan_tag, user_id, coc_client, mongo)

            if not result['success']:
                if result.get('already_exists'):
                    components = [
                        Container(
                            accent_color=RED_ACCENT,
                            components=[
                                Text(content="## ⚠️ Snapshot Already Exists"),
                                Text(content=f"An active snapshot for **{result['clan_name']}** `{result['clan_tag']}` already exists."),
                                Text(content=f"Created: {result.get('existing_date', 'Unknown')}"),
                                Text(content="Use `/fwa lazycwl-reset` to clear existing snapshots first."),
                            ]
                        )
                    ]
                else:
                    components = [
                        Container(
                            accent_color=RED_ACCENT,
                            components=[
                                Text(content="## ❌ Snapshot Creation Failed"),
                                Text(content=f"Failed to create snapshot for **{result['clan_name']}** `{result['clan_tag']}`:"),
                                Text(content=f"```{result.get('error', 'Unknown error')}```"),
                                Text(content="Please try again or contact support if the issue persists."),
                            ]
                        )
                    ]
            else:
                # Success response
                components = [
                    Container(
                        accent_color=GREEN_ACCENT,
                        components=[
                            Text(content="## ✅ Snapshot Created Successfully"),
                            Separator(),
                            Text(content=(
                                f"**Clan:** {result['clan_name']} `{result['clan_tag']}`\n"
                                f"**Players Tracked:** {result['player_count']}\n"
                                f"**Discord Coverage:** {result['discord_coverage']}/{result['player_count']} ({result['coverage_percent']:.1f}%)\n"
                                f"**Month:** {result['month']}\n"
                                f"**Created:** {result['snapshot_date']}"
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
                    Text(content=f"Failed to process snapshot request:"),
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
        # Hardcoded ping channel for all FWA LazyCWL pings
        announcement_channel = 1424256751913668770

        # Fetch clan data to get role ID for mentions
        clan_data = await mongo.clans.find_one({"tag": snapshot["clan_tag"]})

        # Get clan role ID for mentions (optional)
        clan_role_id = clan_data.get("role_id") if clan_data else None

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


async def auto_ping_job(snapshot_id: str):
    """
    Periodic job to check and ping missing players automatically.
    Runs at configured interval until 7 days elapsed or snapshot reset.
    """
    global bot_instance, coc_client, mongo_client, scheduler

    if not all([bot_instance, coc_client, mongo_client, scheduler]):
        print(f"[LazyCWL AutoPing] ERROR: Missing required clients for job {snapshot_id}")
        return

    try:
        # Fetch snapshot from MongoDB
        snapshot = await mongo_client.lazy_cwl_snapshots.find_one({"_id": snapshot_id})

        if not snapshot:
            print(f"[LazyCWL AutoPing] Snapshot {snapshot_id} not found, cancelling job")
            try:
                scheduler.remove_job(f"autopings_{snapshot_id}")
            except:
                pass
            return

        # Check if still active and enabled
        if not snapshot.get("active") or not snapshot.get("auto_ping_enabled"):
            print(f"[LazyCWL AutoPing] Snapshot {snapshot_id} no longer active/enabled, cancelling job")
            if not snapshot.get("active") and snapshot.get("auto_ping_enabled"):
                await mongo_client.lazy_cwl_snapshots.update_one(
                    {"_id": snapshot_id},
                    {"$set": {"auto_ping_enabled": False}},
                )
            try:
                scheduler.remove_job(f"autopings_{snapshot_id}")
            except:
                pass
            return

        # Check 7-day limit
        started_at = snapshot.get("auto_ping_started_at")
        if started_at:
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)

            now = datetime.now(timezone.utc)
            elapsed = now - started_at

            if elapsed > timedelta(days=7):
                print(f"[LazyCWL AutoPing] 7-day limit reached for {snapshot['clan_name']}, disabling")

                # Disable auto-ping
                await mongo_client.lazy_cwl_snapshots.update_one(
                    {"_id": snapshot_id},
                    {
                        "$set": {
                            "auto_ping_enabled": False,
                        }
                    }
                )

                # Cancel job
                try:
                    scheduler.remove_job(f"autopings_{snapshot_id}")
                except:
                    pass

                # Send expiry notification to hardcoded ping channel
                try:
                    ping_count = snapshot.get("auto_ping_count", 0)
                    expiry_components = [
                        Container(
                            accent_color=RED_ACCENT,
                            components=[
                                Text(content="## ⏰ Auto-Ping Expired"),
                                Separator(),
                                Text(content=(
                                    f"The automated ping for **{snapshot['clan_name']}** has expired after 7 days.\n\n"
                                    f"**Snapshot Date:** {snapshot['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC')}\n"
                                    f"**Total Pings Sent:** {ping_count}\n\n"
                                    f"Use `/fwa lazycwl-autopings-start` to restart if needed."
                                ))
                            ]
                        )
                    ]
                    await bot_instance.rest.create_message(
                        channel=1424256751913668770,
                        components=expiry_components
                    )
                except Exception as e:
                    print(f"[LazyCWL AutoPing] Failed to send expiry notification: {e}")

                return

        # Ping missing players
        print(f"[LazyCWL AutoPing] Running auto-ping for {snapshot['clan_name']}")
        result = await process_single_snapshot_ping(snapshot, bot_instance, coc_client, mongo_client)

        if result['success']:
            # Persist every successful check for cadence restoration, but only
            # count a ping when a Discord message was actually sent.
            update = {
                "$set": {
                    "last_auto_ping_at": datetime.now(timezone.utc)
                }
            }
            if not result.get('all_present'):
                update["$inc"] = {"auto_ping_count": 1}

            await mongo_client.lazy_cwl_snapshots.update_one(
                {"_id": snapshot_id},
                update,
            )

            if result.get('all_present'):
                print(f"[LazyCWL AutoPing] All players present for {snapshot['clan_name']}")
            else:
                print(f"[LazyCWL AutoPing] Pinged {result['missing_count']}/{result['total_count']} missing players for {snapshot['clan_name']}")
        else:
            print(f"[LazyCWL AutoPing] Ping failed for {snapshot['clan_name']}: {result.get('error', 'Unknown error')}")

    except Exception as e:
        print(f"[LazyCWL AutoPing] Error in job {snapshot_id}: {e}")
        import traceback
        traceback.print_exc()


async def restore_autopings():
    """Restore auto-ping jobs on bot restart."""
    global mongo_client, scheduler

    if not mongo_client or not scheduler:
        raise RuntimeError("cannot restore auto-pings: missing clients")

    # Restore only active snapshots. Inactive/enabled legacy rows are repaired
    # during startup and must never recreate scheduler jobs.
    snapshots = await mongo_client.lazy_cwl_snapshots.find({
        "active": True,
        "auto_ping_enabled": True
    }).to_list(length=None)

    if not snapshots:
        print("[LazyCWL AutoPing] No active auto-pings to restore")
        return

    now = datetime.now(timezone.utc)
    restored = 0
    expired = 0
    failed = 0

    for snapshot in snapshots:
        snapshot_id = snapshot["_id"]
        started_at = snapshot.get("auto_ping_started_at")

        if not started_at:
            continue

        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=timezone.utc)

        elapsed = now - started_at

        # Check if expired during downtime
        if elapsed > timedelta(days=7):
            print(f"[LazyCWL AutoPing] Snapshot {snapshot['clan_name']} expired during downtime, disabling")
            await mongo_client.lazy_cwl_snapshots.update_one(
                {"_id": snapshot_id},
                {"$set": {"auto_ping_enabled": False}}
            )
            expired += 1
            continue

        interval_minutes = snapshot.get("auto_ping_interval_minutes", 60)
        next_run_time = calculate_next_autoping_run(snapshot, now)
        job_id = f"autopings_{snapshot_id}"

        # A previous retry may already have restored this job before another
        # snapshot failed. Leave the healthy cadence untouched on later passes.
        if scheduler.get_job(job_id) is not None:
            restored += 1
            continue

        try:
            scheduler.add_job(
                auto_ping_job,
                trigger=IntervalTrigger(minutes=interval_minutes),
                args=[snapshot_id],
                id=job_id,
                replace_existing=True,
                next_run_time=next_run_time,
                **AUTOPING_JOB_DEFAULTS,
            )

            print(
                f"[LazyCWL AutoPing] Restored auto-ping for "
                f"{snapshot['clan_name']} (interval: {interval_minutes}min, "
                f"next: {next_run_time.isoformat()})"
            )
            restored += 1
        except Exception as e:
            failed += 1
            print(f"[LazyCWL AutoPing] Failed to restore job for {snapshot['clan_name']}: {e}")

    if restored > 0:
        print(f"[LazyCWL AutoPing] Restored {restored} auto-ping job(s)")
    if expired > 0:
        print(f"[LazyCWL AutoPing] Disabled {expired} expired auto-ping(s)")
    if failed > 0:
        raise RuntimeError(f"failed to restore {failed} auto-ping job(s)")


async def _reconcile_lazy_cwl_startup() -> None:
    """Repair durable state and restore enabled jobs without creating duplicates."""
    if not getattr(scheduler, "running", True):
        scheduler.start()
        print("[LazyCWL AutoPing] Scheduler initialized")

    try:
        await ensure_snapshot_invariants(mongo_client)
        print("[LazyCWL] Snapshot invariants verified")
    except Exception as exc:
        # The unique index is a data-integrity guard, but an index permission
        # failure must not prevent already-enabled notifications from running.
        print(
            f"[LazyCWL] WARNING snapshot invariants unavailable: "
            f"{type(exc).__name__}: {exc}"
        )

    await restore_autopings()
    print("[LazyCWL AutoPing] Active auto-ping jobs restored")


@register_action("lazycwl_ping_select", no_return=True, requires_state=True)
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


@register_action("lazycwl_roster_select", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_roster_select(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle snapshot selection to view full roster."""
    snapshot_id = ctx.interaction.values[0]

    try:
        # Fetch the selected snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        players = snapshot.get("players", [])

        # Sort players by TH level (descending), then alphabetically by name
        players_sorted = sorted(players, key=lambda p: (-p.get("th_level", 0), p.get("name", "").lower()))

        # Calculate Discord coverage
        discord_linked = sum(1 for p in players if p.get("discord_id"))
        coverage_percent = (discord_linked / len(players) * 100) if players else 0

        # Build header
        components_list = [
            Text(content=f"## 📋 {snapshot['clan_name']} Roster"),
            Separator(),
            Text(content=(
                f"**Clan Tag:** `{snapshot['clan_tag']}`\n"
                f"**Snapshot Date:** {snapshot['snapshot_date'].strftime('%B %d, %Y at %I:%M %p UTC')}\n"
                f"**Total Players:** {len(players)}\n"
                f"**Discord Coverage:** {discord_linked}/{len(players)} ({coverage_percent:.1f}%)"
            )),
            Separator(divider=True),
            Text(content="**Players:**")
        ]

        # Build player list (grouped for efficiency)
        player_lines = []
        for player in players_sorted:
            th_level = player.get("th_level", 0)
            name = player.get("name", "Unknown")
            tag = player.get("tag", "Unknown")
            discord_id = player.get("discord_id")

            if discord_id:
                discord_status = f"✅ <@{discord_id}>"
            else:
                discord_status = "❌ Not Linked"

            player_lines.append(f"• **TH{th_level}** | {name} | `{tag}` | {discord_status}")

        # Split into chunks to avoid hitting message length limits
        # Discord Text components can handle ~4000 characters, so we'll use chunks of ~20 players
        chunk_size = 20
        for i in range(0, len(player_lines), chunk_size):
            chunk = player_lines[i:i + chunk_size]
            components_list.append(Text(content="\n".join(chunk)))

        # Build final response
        components = [Container(accent_color=BLUE_ACCENT, components=components_list)]

    except Exception as e:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Failed to Load Roster"),
                    Text(content=f"Failed to load snapshot roster:"),
                    Text(content=f"```{str(e)}```"),
                ]
            )
        ]

    await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_reset_select", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_reset_select(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle snapshot selection for reset."""
    global scheduler

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
                            Text(content="No active snapshots found to reset."),
                        ]
                    )
                ]
                await ctx.interaction.edit_initial_response(components=components)
                return

            # Process each snapshot
            results = []
            for snapshot in snapshots:
                result = await process_single_snapshot_reset(snapshot["_id"], mongo, scheduler)
                results.append(result)

            # Build summary response
            total_snapshots = len(results)
            successful = sum(1 for r in results if r['success'])
            failed = sum(1 for r in results if not r['success'])
            total_autopings_cancelled = sum(1 for r in results if r.get('autopings_cancelled', False))

            summary_parts = [
                Text(content="## ✅ All Snapshots Reset Complete"),
                Separator(),
                Text(content=(
                    f"**Total Snapshots Processed:** {total_snapshots}\n"
                    f"**Successfully Reset:** {successful}\n"
                    f"**Failed:** {failed}\n"
                    f"**Auto-Pings Cancelled:** {total_autopings_cancelled}"
                )),
                Separator(),
                Text(content="**Snapshot Details:**")
            ]

            for result in results:
                if result['success']:
                    autopings_indicator = " (auto-ping cancelled)" if result.get('autopings_cancelled') else ""
                    summary_parts.append(
                        Text(content=(
                            f"✅ **{result['clan_name']}** `{result['clan_tag']}`\n"
                            f"   • Players: {result.get('player_count', 0)}{autopings_indicator}"
                        ))
                    )
                else:
                    summary_parts.append(
                        Text(content=f"❌ **{result['clan_name']}**: {result.get('error', 'Unknown error')}")
                    )

            summary_parts.extend([
                Separator(),
                Text(content="✅ You can now create new snapshots for the next LazyCWL season.")
            ])

            components = [Container(accent_color=GREEN_ACCENT, components=summary_parts)]

        else:
            # Process single snapshot
            snapshot_id = selection
            result = await process_single_snapshot_reset(snapshot_id, mongo, scheduler)

            if not result['success']:
                components = [
                    Container(
                        accent_color=RED_ACCENT,
                        components=[
                            Text(content="## ❌ Reset Failed"),
                            Text(content=f"Failed to reset **{result['clan_name']}**:"),
                            Text(content=f"```{result.get('error', 'Unknown error')}```"),
                            Text(content="Please try again or contact support if the issue persists."),
                        ]
                    )
                ]
            else:
                # Success response
                autopings_msg = "Auto-ping has been cancelled." if result.get('autopings_cancelled') else "No active auto-ping."
                components = [
                    Container(
                        accent_color=GREEN_ACCENT,
                        components=[
                            Text(content="## ✅ Snapshot Reset Successfully"),
                            Separator(),
                            Text(content=(
                                f"**Clan:** {result['clan_name']} `{result['clan_tag']}`\n"
                                f"**Players:** {result.get('player_count', 0)}\n"
                                f"**Auto-Ping:** {autopings_msg}"
                            )),
                            Separator(),
                            Text(content="✅ Snapshot has been deactivated. You can create a new one when needed."),
                        ]
                    )
                ]

    except Exception as e:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Reset Failed"),
                    Text(content=f"Failed to process reset request:"),
                    Text(content=f"```{str(e)}```"),
                    Text(content="Please try again or contact support if the issue persists."),
                ]
            )
        ]

    await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_confirm_reset", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_confirm_reset(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle confirmation of snapshot reset."""
    global scheduler

    try:
        # Cancel any active auto-ping jobs before deactivating snapshots
        autopings_cancelled = 0
        if scheduler:
            snapshots_with_autopings = await mongo.lazy_cwl_snapshots.find({
                "active": True,
                "auto_ping_enabled": True
            }).to_list(length=None)

            for snapshot in snapshots_with_autopings:
                try:
                    scheduler.remove_job(f"autopings_{snapshot['_id']}")
                    autopings_cancelled += 1
                    print(f"[LazyCWL Reset] Cancelled auto-ping for {snapshot['clan_name']}")
                except Exception as e:
                    print(f"[LazyCWL Reset] Failed to cancel auto-ping: {e}")

        # Deactivate all active snapshots
        result = await mongo.lazy_cwl_snapshots.update_many(
            {"active": True},
            {"$set": {"active": False, "auto_ping_enabled": False}}
        )

        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ Reset Complete"),
                    Separator(),
                    Text(content=(
                        f"**Snapshots Deactivated:** {result.modified_count}\n"
                        f"**Auto-Pings Cancelled:** {autopings_cancelled}\n"
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


# ======================== AUTO-PING COMPONENT HANDLERS ========================


@register_action("lazycwl_autopings_select_snapshot", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_autopings_select_snapshot(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle snapshot selection for auto-ping, show interval selector."""
    snapshot_id = ctx.interaction.values[0]

    try:
        # ALL passes through to the interval step as the literal string "ALL".
        # One interval is chosen once and applied to every clan - asking per
        # clan would defeat the point of the bulk option.
        if snapshot_id == "ALL":
            snapshot_label = "🌍 **ALL FWA CLANS**"
        else:
            # Fetch snapshot to get name
            snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
            if not snapshot:
                raise Exception("Snapshot not found")
            snapshot_label = f"{snapshot['clan_name']} `{snapshot['clan_tag']}`"

        # Create new action for interval selection
        new_action_id = str(uuid.uuid4())
        data = {
            "_id": new_action_id,
            "command": "autopings_interval",
            "user_id": user_id,
            "snapshot_id": snapshot_id
        }
        await insert_state(mongo, data)

        # Interval options
        interval_options = [
            SelectOption(
                label="30 minutes",
                value="30",
                description="Check every 30 minutes",
                emoji="⏱️"
            ),
            SelectOption(
                label="1 hour",
                value="60",
                description="Check every hour (recommended)",
                emoji="⏰"
            ),
            SelectOption(
                label="2 hours",
                value="120",
                description="Check every 2 hours",
                emoji="🕐"
            ),
        ]

        components = [
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"## ⏱️ Select Ping Interval"),
                    Text(content=f"**Snapshot:** {snapshot_label}"),
                    Separator(),
                    Text(content="Choose how often to check for missing players:"),
                    Text(content="*Auto-ping will run for up to 7 days or until snapshot is reset*"),
                    Separator(),
                    ActionRow(
                        components=[
                            TextSelectMenu(
                                custom_id=f"lazycwl_autopings_select_interval:{new_action_id}",
                                placeholder="Select interval...",
                                max_values=1,
                                options=interval_options
                            )
                        ]
                    )
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Error"),
                    Text(content=f"Failed to process selection: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_autopings_select_interval", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_autopings_select_interval(
    ctx,
    action_id: str,
    snapshot_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle interval selection and start auto-ping job."""
    global scheduler

    interval_minutes = int(ctx.interaction.values[0])

    try:
        if not scheduler:
            raise Exception("Scheduler not initialized")

        # ALL stops here and asks first. Start-all eventually posts to the
        # LazyCWL ping channel on a repeating interval for every clan, so it is
        # not something to fire off a single dropdown pick. The per-clan path
        # below keeps its existing no-confirm behaviour untouched.
        if snapshot_id == "ALL":
            pending = await mongo.lazy_cwl_snapshots.find({
                "active": True,
                "$or": [
                    {"auto_ping_enabled": {"$exists": False}},
                    {"auto_ping_enabled": False}
                ]
            }).to_list(length=None)

            confirm_action_id = str(uuid.uuid4())
            await insert_state(mongo, {
                "_id": confirm_action_id,
                "command": "autopings_start_all_confirm",
                "user_id": user_id,
                "interval_minutes": interval_minutes
            })

            names = "\n".join(
                f"• **{s.get('clan_name', 'Unknown')}** `{s.get('clan_tag', '?')}`"
                for s in pending
            ) or "*none*"

            components = [
                Container(
                    accent_color=GOLD_ACCENT,
                    components=[
                        Text(content="## ⚠️ Confirm Start Auto-Ping for ALL"),
                        Separator(),
                        Text(content=(
                            f"**Clans:** {len(pending)}\n"
                            f"**Interval:** Every {interval_minutes} minutes\n"
                            f"**Duration:** 7 days, or until each snapshot is reset"
                        )),
                        Separator(),
                        Text(content=names),
                        Separator(),
                        Text(content=(
                            "Each clan will be checked every "
                            f"{interval_minutes} minutes and missing players pinged "
                            "in the LazyCWL ping channel. First runs are staggered "
                            "5 seconds apart so they do not all fire at once."
                        )),
                        Text(content="Are you sure you want to start auto-ping for all of them?"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.DANGER,
                                    custom_id=f"lazycwl_autopings_start_all_confirm:{confirm_action_id}",
                                    label="Start All",
                                    emoji="✅"
                                ),
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    custom_id=f"lazycwl_autopings_start_all_cancel:{confirm_action_id}",
                                    label="Cancel",
                                    emoji="❌"
                                )
                            ]
                        )
                    ]
                )
            ]
            await ctx.interaction.edit_initial_response(components=components)
            return

        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")
        if not snapshot.get("active"):
            raise Exception("Snapshot is no longer active")

        # Check if auto-ping already enabled (race condition check)
        if snapshot.get("auto_ping_enabled"):
            raise Exception("Auto-ping already enabled for this snapshot")

        # Start time
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(days=7)

        # Update snapshot with auto-ping settings
        await mongo.lazy_cwl_snapshots.update_one(
            {"_id": snapshot_id},
            {
                "$set": {
                    "auto_ping_enabled": True,
                    "auto_ping_started_at": now,
                    "auto_ping_interval_minutes": interval_minutes,
                    "auto_ping_job_id": f"autopings_{snapshot_id}",
                    "last_auto_ping_at": None,
                    "auto_ping_count": 0
                }
            }
        )

        # Create APScheduler job
        try:
            scheduler.add_job(
                auto_ping_job,
                trigger=IntervalTrigger(minutes=interval_minutes),
                args=[snapshot_id],
                id=f"autopings_{snapshot_id}",
                replace_existing=True,
                **AUTOPING_JOB_DEFAULTS,
            )
        except Exception:
            await rollback_failed_autoping_start(mongo, snapshot_id)
            raise

        print(f"[LazyCWL AutoPing] Started auto-ping for {snapshot['clan_name']} (interval: {interval_minutes}min)")

        # Success response
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ Auto-Ping Started"),
                    Separator(),
                    Text(content=(
                        f"**Clan:** {snapshot['clan_name']} `{snapshot['clan_tag']}`\n"
                        f"**Interval:** Every {interval_minutes} minutes\n"
                        f"**Started:** {now.strftime('%B %d, %Y at %I:%M %p UTC')}\n"
                        f"**Expires:** {expires_at.strftime('%B %d, %Y at %I:%M %p UTC')} (7 days)\n\n"
                        f"The bot will automatically check for missing players every {interval_minutes} minutes and ping them if needed."
                    )),
                    Separator(),
                    Text(content="Use `/fwa lazycwl-autopings-status` to view active auto-pings."),
                    Text(content="Use `/fwa lazycwl-autopings-stop` to stop auto-ping manually."),
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:
        print(f"[LazyCWL AutoPing] Failed to start auto-ping: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Failed to Start Auto-Ping"),
                    Text(content=f"Error: {str(e)}"),
                    Text(content="Please try again or contact an administrator."),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_autopings_stop_select", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_autopings_stop_select(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle snapshot selection to stop auto-ping."""
    global scheduler

    snapshot_id = ctx.interaction.values[0]

    try:
        # ALL asks first. Stop-all silently kills every job, and the resulting
        # panel looks the same as one where nothing was running - so it gets a
        # confirm. The per-clan path below is untouched.
        if snapshot_id == "ALL":
            running = await mongo.lazy_cwl_snapshots.find({
                "active": True,
                "auto_ping_enabled": True
            }).to_list(length=None)

            confirm_action_id = str(uuid.uuid4())
            await insert_state(mongo, {
                "_id": confirm_action_id,
                "command": "autopings_stop_all_confirm",
                "user_id": user_id
            })

            names = "\n".join(
                f"• **{s.get('clan_name', 'Unknown')}** `{s.get('clan_tag', '?')}` "
                f"— {s.get('auto_ping_count', 0)} pings sent"
                for s in running
            ) or "*none*"

            components = [
                Container(
                    accent_color=GOLD_ACCENT,
                    components=[
                        Text(content="## ⚠️ Confirm Stop Auto-Ping for ALL"),
                        Separator(),
                        Text(content=f"**Clans with auto-ping running:** {len(running)}"),
                        Separator(),
                        Text(content=names),
                        Separator(),
                        Text(content=(
                            "All of these will stop being checked. Restarting means "
                            "running `/fwa lazycwl-autopings-start` again and "
                            "re-choosing an interval."
                        )),
                        Text(content="Are you sure you want to stop auto-ping for all of them?"),
                        ActionRow(
                            components=[
                                Button(
                                    style=hikari.ButtonStyle.DANGER,
                                    custom_id=f"lazycwl_autopings_stop_all_confirm:{confirm_action_id}",
                                    label="Stop All",
                                    emoji="✅"
                                ),
                                Button(
                                    style=hikari.ButtonStyle.SECONDARY,
                                    custom_id=f"lazycwl_autopings_stop_all_cancel:{confirm_action_id}",
                                    label="Cancel",
                                    emoji="❌"
                                )
                            ]
                        )
                    ]
                )
            ]
            await ctx.interaction.edit_initial_response(components=components)
            return

        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        # Update MongoDB to disable auto-ping
        await mongo.lazy_cwl_snapshots.update_one(
            {"_id": snapshot_id},
            {
                "$set": {
                    "auto_ping_enabled": False
                }
            }
        )

        # Cancel APScheduler job
        if scheduler:
            try:
                scheduler.remove_job(f"autopings_{snapshot_id}")
                print(f"[LazyCWL AutoPing] Stopped auto-ping for {snapshot['clan_name']}")
            except Exception as e:
                print(f"[LazyCWL AutoPing] Job not found or already removed: {e}")

        # Success response
        ping_count = snapshot.get("auto_ping_count", 0)
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ Auto-Ping Stopped"),
                    Separator(),
                    Text(content=(
                        f"**Clan:** {snapshot['clan_name']} `{snapshot['clan_tag']}`\n\n"
                        f"Automated pinging has been stopped.\n"
                        f"**Total Pings Sent:** {ping_count}\n\n"
                        f"Use `/fwa lazycwl-autopings-start` to restart if needed."
                    ))
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:
        print(f"[LazyCWL AutoPing] Failed to stop auto-ping: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Failed to Stop Auto-Ping"),
                    Text(content=f"Error: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


def _bulk_autoping_summary(title: str, results: list, extra: list) -> list:
    """Render an ALL-batch summary. Same shape as the reset ALL branch.

    Deliberately ONE renderer for both start-all and stop-all, so the two
    cannot drift into reporting failures differently.
    """
    successful = sum(1 for r in results if r['success'])
    failed = sum(1 for r in results if not r['success'])

    parts = [
        Text(content=title),
        Separator(),
        Text(content=(
            f"**Total Processed:** {len(results)}\n"
            f"**Successful:** {successful}\n"
            f"**Failed:** {failed}"
        )),
        Separator(),
        Text(content="**Clan Details:**")
    ]

    for result in results:
        if result['success']:
            pings = result.get('ping_count')
            suffix = f" • {pings} pings sent" if pings is not None else ""
            parts.append(Text(content=(
                f"✅ **{result['clan_name']}** `{result['clan_tag']}`{suffix}"
            )))
        else:
            # NAMED failure, never a bare count - a silent partial is the whole
            # thing this renderer exists to prevent.
            parts.append(Text(content=(
                f"❌ **{result['clan_name']}** `{result['clan_tag']}`: "
                f"{result.get('error', 'Unknown error')}"
            )))

    parts.extend(extra)
    accent = GREEN_ACCENT if failed == 0 else GOLD_ACCENT
    return [Container(accent_color=accent, components=parts)]


@register_action("lazycwl_autopings_start_all_confirm", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_autopings_start_all_confirm(
    ctx,
    action_id: str,
    interval_minutes: int,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Start auto-ping for every eligible snapshot.

    NO ROLLBACK on partial failure, deliberately. The eligibility query only
    returns snapshots WITHOUT auto-ping, so re-running naturally targets
    whatever failed; undoing the successes to punish the failures would throw
    away work for nothing.
    """
    global scheduler

    try:
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True,
            "$or": [
                {"auto_ping_enabled": {"$exists": False}},
                {"auto_ping_enabled": False}
            ]
        }).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ Nothing To Start"),
                        Text(content="No active snapshots without auto-ping remain."),
                    ]
                )
            ]
            await ctx.interaction.edit_initial_response(components=components)
            return

        results = []
        for index, snapshot in enumerate(snapshots):
            results.append(await process_single_autoping_start(
                snapshot, interval_minutes, index, mongo, scheduler
            ))

        components = _bulk_autoping_summary(
            "## ✅ Auto-Ping Started for All Clans",
            results,
            [
                Separator(),
                Text(content=(
                    f"Interval: every {interval_minutes} minutes • runs up to 7 days\n"
                    f"First runs staggered 5s apart."
                )),
                Text(content="Use `/fwa lazycwl-autopings-status` to view active auto-pings."),
            ]
        )
        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:  # noqa: BLE001
        print(f"[LazyCWL AutoPing] Bulk start failed: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Failed to Start Auto-Ping for All"),
                    Text(content=f"Error: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_autopings_start_all_cancel", no_return=True)
@lightbulb.di.with_di
async def handle_autopings_start_all_cancel(ctx, action_id: str, **kwargs) -> None:
    """Cancel the bulk start. Nothing has been written at this point."""
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## ❌ Cancelled"),
                Text(content="No auto-pings were started."),
            ]
        )
    ]
    await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_autopings_stop_all_confirm", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_autopings_stop_all_confirm(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Stop auto-ping for every snapshot currently running one."""
    global scheduler

    try:
        snapshots = await mongo.lazy_cwl_snapshots.find({
            "active": True,
            "auto_ping_enabled": True
        }).to_list(length=None)

        if not snapshots:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ Nothing To Stop"),
                        Text(content="No snapshots currently have auto-ping enabled."),
                    ]
                )
            ]
            await ctx.interaction.edit_initial_response(components=components)
            return

        results = []
        for snapshot in snapshots:
            results.append(await process_single_autoping_stop(snapshot, mongo, scheduler))

        components = _bulk_autoping_summary(
            "## ✅ Auto-Ping Stopped for All Clans",
            results,
            [
                Separator(),
                Text(content="Use `/fwa lazycwl-autopings-start` to restart if needed."),
            ]
        )
        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:  # noqa: BLE001
        print(f"[LazyCWL AutoPing] Bulk stop failed: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Failed to Stop Auto-Ping for All"),
                    Text(content=f"Error: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_autopings_stop_all_cancel", no_return=True)
@lightbulb.di.with_di
async def handle_autopings_stop_all_cancel(ctx, action_id: str, **kwargs) -> None:
    """Cancel the bulk stop. Every job is still running."""
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## ❌ Cancelled"),
                Text(content="All auto-pings are still running."),
            ]
        )
    ]
    await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_remove_player_select_snapshot", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_remove_player_select_snapshot(
    ctx,
    action_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    page: int = 0,
    **kwargs
) -> None:
    """Handle snapshot selection for player removal, show player selector with pagination."""
    snapshot_id = ctx.interaction.values[0]

    try:
        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        players = snapshot.get("players", [])
        if not players:
            components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ No Players"),
                        Text(content=f"Snapshot for **{snapshot['clan_name']}** has no players."),
                    ]
                )
            ]
            await ctx.interaction.edit_initial_response(components=components)
            return

        # Sort players by TH (desc) then name (asc)
        players_sorted = sorted(
            players,
            key=lambda p: (-p.get("th_level", 0), p.get("name", "").lower())
        )

        # Pagination calculations
        players_per_page = 25
        total_players = len(players_sorted)
        total_pages = (total_players + players_per_page - 1) // players_per_page  # Ceiling division
        current_page = page

        # Ensure page is within bounds
        if current_page < 0:
            current_page = 0
        if current_page >= total_pages:
            current_page = total_pages - 1

        # Get players for current page
        start_idx = current_page * players_per_page
        end_idx = min(start_idx + players_per_page, total_players)
        players_on_page = players_sorted[start_idx:end_idx]

        # Create new action for player selection
        new_action_id = str(uuid.uuid4())
        data = {
            "_id": new_action_id,
            "command": "remove_player_select",
            "user_id": user_id,
            "snapshot_id": snapshot_id,
            "page": current_page
        }
        await insert_state(mongo, data)

        # Build player options for current page
        options = []
        for player in players_on_page:
            th_level = player.get("th_level", 0)
            name = player.get("name", "Unknown")
            tag = player.get("tag", "Unknown")
            discord_id = player.get("discord_id")

            discord_status = "✅" if discord_id else "❌"

            options.append(
                SelectOption(
                    label=f"TH{th_level} {name}",
                    value=tag,
                    description=f"{tag} • Discord: {discord_status}",
                    emoji="👤"
                )
            )

        auto_ping_warning = ""
        if snapshot.get("auto_ping_enabled"):
            auto_ping_warning = "⚠️ **Auto-ping is active** - Removed players will stop being pinged immediately."

        # Build component list
        component_list = [
            Text(content=f"## 👥 Select Players to Remove"),
            Text(content=f"**Snapshot:** {snapshot['clan_name']} `{snapshot['clan_tag']}`"),
            Text(content=f"**Total Players:** {total_players} • **Page {current_page + 1} of {total_pages}** (Players {start_idx + 1}-{end_idx})"),
            Separator(),
            Text(content="Select up to 10 players to remove from this snapshot:"),
        ]

        if auto_ping_warning:
            component_list.extend([Text(content=auto_ping_warning), Separator()])

        # Player dropdown
        component_list.append(
            ActionRow(
                components=[
                    TextSelectMenu(
                        custom_id=f"lazycwl_remove_player_select_players:{new_action_id}",
                        placeholder="Select players to remove...",
                        min_values=1,
                        max_values=min(10, len(options)),
                        options=options
                    )
                ]
            )
        )

        # Pagination buttons (if needed)
        if total_pages > 1:
            pagination_buttons = []

            if current_page > 0:
                pagination_buttons.append(
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"lazycwl_remove_player_page_prev:{new_action_id}",
                        label="◀ Previous Page",
                        emoji="⬅️"
                    )
                )

            if current_page < total_pages - 1:
                pagination_buttons.append(
                    Button(
                        style=hikari.ButtonStyle.SECONDARY,
                        custom_id=f"lazycwl_remove_player_page_next:{new_action_id}",
                        label="Next Page ▶",
                        emoji="➡️"
                    )
                )

            if pagination_buttons:
                component_list.extend([
                    Separator(),
                    ActionRow(components=pagination_buttons)
                ])

        components = [Container(accent_color=GOLD_ACCENT, components=component_list)]

        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:
        print(f"[LazyCWL Remove] Error selecting snapshot: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Error"),
                    Text(content=f"Failed to load snapshot: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_remove_player_select_players", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_remove_player_select_players(
    ctx,
    action_id: str,
    snapshot_id: str,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle player selection and show confirmation."""
    selected_player_tags = ctx.interaction.values

    try:
        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        # Get full player info for selected tags
        players = snapshot.get("players", [])
        selected_players = [p for p in players if p.get("tag") in selected_player_tags]

        if not selected_players:
            raise Exception("Selected players not found in snapshot")

        # Create new action for confirmation
        new_action_id = str(uuid.uuid4())
        data = {
            "_id": new_action_id,
            "command": "remove_player_confirm",
            "user_id": user_id,
            "snapshot_id": snapshot_id,
            "player_tags": selected_player_tags
        }
        await insert_state(mongo, data)

        # Build player list for confirmation
        player_list_components = []
        for player in selected_players:
            th_level = player.get("th_level", 0)
            name = player.get("name", "Unknown")
            tag = player.get("tag", "Unknown")
            discord_id = player.get("discord_id")

            discord_str = f"<@{discord_id}>" if discord_id else "No Discord"
            player_list_components.append(
                Text(content=f"• **TH{th_level}** {name} `{tag}` - {discord_str}")
            )

        current_count = len(players)
        new_count = current_count - len(selected_players)

        components = [
            Container(
                accent_color=GOLD_ACCENT,
                components=[
                    Text(content="## ⚠️ Confirm Player Removal"),
                    Text(content=f"**Snapshot:** {snapshot['clan_name']} `{snapshot['clan_tag']}`"),
                    Separator(),
                    Text(content=f"**Players to Remove:** {len(selected_players)}"),
                    *player_list_components,
                    Separator(),
                    Text(content=f"**Current Player Count:** {current_count}"),
                    Text(content=f"**New Player Count:** {new_count}"),
                    *(
                        [
                            Separator(),
                            Text(content="⚠️ **Auto-ping is active** - These players will immediately stop being pinged.")
                        ]
                        if snapshot.get("auto_ping_enabled")
                        else []
                    ),
                    Separator(),
                    Text(content="Are you sure you want to remove these players?"),
                    ActionRow(
                        components=[
                            Button(
                                style=hikari.ButtonStyle.DANGER,
                                custom_id=f"lazycwl_remove_player_confirm:{new_action_id}",
                                label="Remove Players",
                                emoji="✅"
                            ),
                            Button(
                                style=hikari.ButtonStyle.SECONDARY,
                                custom_id=f"lazycwl_remove_player_cancel:{new_action_id}",
                                label="Cancel",
                                emoji="❌"
                            )
                        ]
                    )
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:
        print(f"[LazyCWL Remove] Error selecting players: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Error"),
                    Text(content=f"Failed to process selection: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_remove_player_confirm", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_remove_player_confirm(
    ctx,
    action_id: str,
    snapshot_id: str,
    player_tags: list,
    user_id: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle confirmation and remove players from snapshot."""
    try:
        # Fetch snapshot to get current state
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        original_count = len(snapshot.get("players", []))

        # Remove players using $pull operator
        result = await mongo.lazy_cwl_snapshots.update_one(
            {"_id": snapshot_id},
            {"$pull": {"players": {"tag": {"$in": player_tags}}}}
        )

        if result.modified_count == 0:
            raise Exception("Failed to update snapshot")

        # Fetch updated snapshot to get new count
        updated_snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        new_count = len(updated_snapshot.get("players", []))
        removed_count = original_count - new_count

        print(f"[LazyCWL Remove] Removed {removed_count} players from {snapshot['clan_name']}")

        # Success message
        components = [
            Container(
                accent_color=GREEN_ACCENT,
                components=[
                    Text(content="## ✅ Players Removed"),
                    Separator(),
                    Text(content=f"**Snapshot:** {snapshot['clan_name']} `{snapshot['clan_tag']}`"),
                    Text(content=f"**Players Removed:** {removed_count}"),
                    Text(content=f"**Remaining Players:** {new_count}"),
                    *(
                        [
                            Separator(),
                            Text(content="✅ Auto-ping system will no longer ping these players.")
                        ]
                        if snapshot.get("auto_ping_enabled")
                        else []
                    ),
                    Separator(),
                    Text(content="Players have been successfully removed from the snapshot."),
                ]
            )
        ]

        await ctx.interaction.edit_initial_response(components=components)

    except Exception as e:
        print(f"[LazyCWL Remove] Error removing players: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Removal Failed"),
                    Text(content=f"Failed to remove players: {str(e)}"),
                    Text(content="Please try again or contact support."),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_remove_player_page_next", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_remove_player_page_next(
    ctx,
    action_id: str,
    snapshot_id: str,
    user_id: int,
    page: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle next page button for player selection."""
    try:
        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        # Re-render with next page
        # We need to simulate the dropdown selection to reuse the handler
        # Create a mock context-like object with the snapshot_id as the selected value

        # Increment page
        next_page = page + 1

        # Call the snapshot selection handler with new page
        class MockInteraction:
            def __init__(self, snapshot_id):
                self.values = [snapshot_id]

        # Create mock context with new interaction
        mock_ctx = type('obj', (object,), {
            'interaction': MockInteraction(snapshot_id)
        })()
        mock_ctx.interaction.edit_initial_response = ctx.interaction.edit_initial_response

        await handle_remove_player_select_snapshot(
            mock_ctx,
            action_id,
            user_id,
            mongo,
            page=next_page
        )

    except Exception as e:
        print(f"[LazyCWL Remove] Error navigating to next page: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Error"),
                    Text(content=f"Failed to navigate: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_remove_player_page_prev", no_return=True, requires_state=True)
@lightbulb.di.with_di
async def handle_remove_player_page_prev(
    ctx,
    action_id: str,
    snapshot_id: str,
    user_id: int,
    page: int,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs
) -> None:
    """Handle previous page button for player selection."""
    try:
        # Fetch snapshot
        snapshot = await mongo.lazy_cwl_snapshots.find_one({"_id": snapshot_id})
        if not snapshot:
            raise Exception("Snapshot not found")

        # Decrement page
        prev_page = max(0, page - 1)

        # Call the snapshot selection handler with new page
        class MockInteraction:
            def __init__(self, snapshot_id):
                self.values = [snapshot_id]

        mock_ctx = type('obj', (object,), {
            'interaction': MockInteraction(snapshot_id)
        })()
        mock_ctx.interaction.edit_initial_response = ctx.interaction.edit_initial_response

        await handle_remove_player_select_snapshot(
            mock_ctx,
            action_id,
            user_id,
            mongo,
            page=prev_page
        )

    except Exception as e:
        print(f"[LazyCWL Remove] Error navigating to previous page: {e}")
        components = [
            Container(
                accent_color=RED_ACCENT,
                components=[
                    Text(content="## ❌ Error"),
                    Text(content=f"Failed to navigate: {str(e)}"),
                ]
            )
        ]
        await ctx.interaction.edit_initial_response(components=components)


@register_action("lazycwl_remove_player_cancel", no_return=True)
async def handle_remove_player_cancel(ctx, action_id: str, **kwargs) -> None:
    """Handle cancellation of player removal."""
    components = [
        Container(
            accent_color=BLUE_ACCENT,
            components=[
                Text(content="## ❌ Removal Cancelled"),
                Text(content="Player removal has been cancelled. No changes were made."),
            ]
        )
    ]
    await ctx.interaction.edit_initial_response(components=components)


# ======================== BOT STARTUP EVENT ========================


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    coc_api: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
):
    """Initialize scheduler and restore auto-ping jobs on bot startup."""
    global bot_instance, coc_client, mongo_client, scheduler, startup_reconciler

    # Store clients globally for auto_ping_job access
    bot_instance = bot
    coc_client = coc_api
    mongo_client = mongo

    # This listener is attached to the shared `fwa` loader, which fires once per
    # /fwa module. Construct both objects without an await so duplicate events
    # cannot interleave and create parallel schedulers or reconcilers.
    if scheduler is None:
        scheduler = AsyncIOScheduler(
            timezone="UTC",
            job_defaults=AUTOPING_JOB_DEFAULTS,
        )
    if startup_reconciler is None:
        startup_reconciler = StartupReconciler(
            "lazy_cwl_autopings",
            _reconcile_lazy_cwl_startup,
        )
    startup_reconciler.start()


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    """Stop the in-memory scheduler cleanly during every bot shutdown."""
    global scheduler, startup_reconciler

    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None

    current_scheduler = scheduler
    scheduler = None
    if current_scheduler is None:
        return

    try:
        current_scheduler.shutdown(wait=False)
        await asyncio.sleep(0)
        print("[LazyCWL AutoPing] Scheduler shutdown")
    except Exception as e:
        print(f"[LazyCWL AutoPing] Scheduler shutdown failed: {e}")


# Register the commands with the loader
loader.command(fwa)
