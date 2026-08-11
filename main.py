# NO WARNING FILTERS HERE, DELIBERATELY.
#
# This file carried `warnings.filterwarnings("ignore", category=Deprecation-
# Warning)` from the initial commit, and it never worked - coc.py's utcnow
# DeprecationWarnings reached the journal for the entire life of the repo,
# ~200 per /todo run. Three further attempts at filtering also failed, and the
# MECHANISM WAS NEVER ESTABLISHED: we never confirmed whether the record came
# through the warnings module, through logging.captureWarnings, or from a
# direct logger call. See docs/hikari-logging-and-warnings.md.
#
# The noise was removed at source instead, by taking coc.py 3.10.0, which
# deletes the utcnow() calls. If you ever need to suppress a warning in this
# process, DO NOT assume a filter here will work - it demonstrably did not.
import sys
# Force line-buffered stdout/stderr so logs reach journald immediately.
# Without this, Python block-buffers output when piped (as under systemd),
# delaying log delivery by hours. Belt-and-suspenders with PYTHONUNBUFFERED
# in the systemd unit, and travels with the code if the box is rebuilt.
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except (AttributeError, ValueError):
    pass  # non-standard stream (e.g. already wrapped); env var still covers us

# Fail fast on an untested interpreter. This bot is developed and deployed on
# Python 3.12.3; older versions are unvalidated and standard-library behavior
# can change across point releases, so a mismatch should be a loud startup
# error rather than a silent runtime bug.
if sys.version_info < (3, 12, 3):
    raise RuntimeError(
        "This bot requires Python 3.12.3 or newer. Detected "
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}. "
        "Upgrade the interpreter before running."
    )

import asyncio
import logging
import os
import hikari
import lightbulb
from dotenv import load_dotenv
from utils.mongo import MongoClient
import coc
from utils.startup import create_clash_client, load_cogs, unique_extensions
from utils.cloudinary_client import CloudinaryClient
from extensions.autocomplete import preload_autocomplete_cache
from utils import bot_data

load_dotenv()

# Create a GatewayBot instance with intents and custom rate limit settings
#
# Note: GatewayBot.__init__ calls ux.init_logging(), which reconfigures the
# process's logging AND prepends warnings.simplefilter("always",
# DeprecationWarning). Constructing this line has global side effects.
# See docs/hikari-logging-and-warnings.md.
bot = hikari.GatewayBot(
    token=os.getenv("DISCORD_TOKEN"),
    intents=(
        hikari.Intents.GUILD_MESSAGES
        | hikari.Intents.DM_MESSAGES
        | hikari.Intents.MESSAGE_CONTENT
        | hikari.Intents.GUILDS
        | hikari.Intents.GUILD_MEMBERS
        | hikari.Intents.GUILD_MODERATION
        | hikari.Intents.GUILD_MESSAGE_REACTIONS
    ),
    # Fix hikari's overly aggressive rate limiting
    max_rate_limit=120.0,  # Guild channel-create bucket slides to a 60s window; 30s made those a user-facing error
    max_retries=1,  # Fail fast instead of waiting
)

client = lightbulb.client_from_app(bot)

# coc.py logs the complete response object and every proxy header at INFO for
# an expected private-war-log 403. The todo layer emits one concise line when
# it classifies the response, while real HTTP warnings/errors remain visible.
logging.getLogger("coc.http").setLevel(logging.WARNING)

mongo_client = MongoClient(uri=os.getenv("MONGODB_URI"))
clash_client: coc.Client | None = None

cloudinary_client = CloudinaryClient()

bot_data.data["mongo"] = mongo_client
bot_data.data["cloudinary_client"] = cloudinary_client
bot_data.data["bot"] = bot

registry = client.di.registry_for(lightbulb.di.Contexts.DEFAULT)
registry.register_value(MongoClient, mongo_client)
registry.register_value(CloudinaryClient, cloudinary_client)
registry.register_value(hikari.GatewayBot, bot)

@bot.listen(hikari.StartingEvent)
async def on_starting(_: hikari.StartingEvent) -> None:
    """Bot starting event"""
    global clash_client

    # Build coc.py only after Hikari has installed and started its event loop.
    clash_client = create_clash_client(loop=asyncio.get_running_loop())
    bot_data.data["coc_client"] = clash_client
    registry.register_value(coc.Client, clash_client)

    explicit_extensions = [
        "extensions.components",
        "extensions.commands.clan",
        "extensions.commands.fwa",
        "extensions.commands.recruit",
        "extensions.commands.recruit.dashboard.server_walkthrough",
        "extensions.commands.setup",
        "extensions.context_menus.get_message_id",
        "extensions.context_menus.get_user_id",
        "extensions.tasks.band_monitor",
        "extensions.tasks.recruit_role_cleanup",
        "extensions.tasks.cwl_reminder",
        "extensions.tasks.fwa_points_monitor",
        "extensions.tasks.clan_history_tracker",
        "extensions.tasks.band_sync_ical",
        "extensions.commands.tickets",
        "extensions.events.channel.ticket_channel_monitor",
        "extensions.events.message.message_events",  # Add message events handler
    ]
    all_extensions = unique_extensions(
        explicit_extensions,
        load_cogs(
            disallowed={"example"},
            disallowed_folders={"clan", "fwa", "recruit", "setup", "tickets"},
        ),
    )

    await client.load_extensions(*all_extensions)
    await client.start()
    await clash_client.login_with_tokens("")


@bot.listen(hikari.StoppingEvent)
async def on_stopping(_: hikari.StoppingEvent) -> None:
    """Stop Lightbulb-owned tasks and close its DI scopes before REST closes."""
    await client.stop()


@bot.listen(hikari.StartedEvent)
async def on_bot_start(event: hikari.StartedEvent):
    """Load FWA URLs from database on startup"""
    fwa_data = await mongo_client.fwa_data.find_one({"_id": "fwa_config"})

    if fwa_data:
        from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE

        # Load war base images
        if "war_base_images" in fwa_data:
            FWA_WAR_BASE.update(fwa_data["war_base_images"])
            print(f"[INFO] Loaded {len(fwa_data['war_base_images'])} FWA war base URLs")

        # Load active base images
        if "active_base_images" in fwa_data:
            FWA_ACTIVE_WAR_BASE.update(fwa_data["active_base_images"])
            print(f"[INFO] Loaded {len(fwa_data['active_base_images'])} FWA active base URLs")

    # Check for reboot notification
    try:
        reboot_status = await mongo_client.bot_config.find_one({"_id": "reboot_status"})
        if reboot_status and reboot_status.get("reboot_pending"):
            user_id = reboot_status.get("user_id")
            if user_id:
                try:
                    from hikari.impl import (
                        ContainerComponentBuilder as Container,
                        TextDisplayComponentBuilder as Text,
                        MediaGalleryComponentBuilder as Media,
                        MediaGalleryItemBuilder as MediaItem,
                    )
                    from utils.constants import GREEN_ACCENT

                    dm_channel = await bot.rest.create_dm_channel(user_id)
                    await bot.rest.create_message(
                        channel=dm_channel,
                        components=[
                            Container(
                                accent_color=GREEN_ACCENT,
                                components=[
                                    Text(content=(
                                        "## ✅ Bot is Back Online!\n\n"
                                        "Reboot completed successfully.\n"
                                        "All systems operational."
                                    )),
                                    Media(items=[MediaItem(media="assets/Green_Footer.png")])
                                ]
                            )
                        ]
                    )
                except Exception as e:
                    print(f"Failed to send reboot notification: {e}")

            # Clear the reboot flag
            await mongo_client.bot_config.delete_one({"_id": "reboot_status"})
    except Exception as e:
        print(f"Failed to check reboot status: {e}")


@bot.listen(hikari.StoppedEvent)
async def on_stopped(_: hikari.StoppedEvent) -> None:
    """Close shared clients after extension stopping handlers have unwound."""
    try:
        # Properly close the coc.py client to avoid unclosed session warnings.
        if clash_client is not None and clash_client.http is not None:
            await clash_client.close()
    finally:
        # AsyncMongoClient owns connection-pool monitoring tasks and must still
        # close even if the Clash client reports a shutdown error.
        await mongo_client.close()

    # Let cancellation callbacks and APScheduler's call_soon shutdown hooks
    # unwind before Hikari performs its final loop audit.
    await asyncio.sleep(0)
    current = asyncio.current_task()
    remaining = [
        task for task in asyncio.all_tasks()
        if task is not current and not task.done()
    ]
    if remaining:
        labels = set()
        for task in remaining:
            name = task.get_name()
            if name.startswith("Task-"):
                coro = task.get_coro()
                name = getattr(coro, "__qualname__", type(coro).__name__)
            labels.add(name)
        names = ",".join(sorted(labels))
        print(f"[shutdown] pending_tasks count={len(remaining)} names={names}")
    else:
        print("[shutdown] pending_tasks count=0")

bot.run()
