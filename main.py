import logging
import warnings

# ---------------------------------------------------------------------------
# coc.py's utcnow spam, and why suppressing it is not a one-liner
#
# THE NOISE: coc.py 3.9.1 calls the stdlib datetime.utcnow(), deprecated in
# Python 3.12, from coc/utils.py - get_season_start, get_season_end,
# get_clan_games_start, get_clan_games_end. One /todo run emitted ~200 of these
# and buried every other log line. It is coc.py's code, not ours; fixed upstream
# in 3.9.2, which requirements.txt explains why we have not taken yet.
#
# WHY THE OBVIOUS FIX NEVER WORKED: this file carried a blanket
#     warnings.filterwarnings("ignore", category=DeprecationWarning)
# on line 2 from the initial commit. It was deployed. The spam came through
# anyway, for the entire life of the repo.
#
# hikari's GatewayBot.__init__ calls hikari.internal.ux.init_logging(), which
# does BOTH of these (verified in hikari 2.3.5, hikari/internal/ux.py):
#     warnings.simplefilter("always", DeprecationWarning)
#     logging.captureWarnings(True)
#
# simplefilter PREPENDS, so hikari's "always" lands in front of anything we
# installed earlier and wins outright. It is in __init__, not run() - so
# constructing the bot is what clobbers us, and every filter installed before
# `bot = hikari.GatewayBot(...)` is dead on arrival no matter how early it runs.
# That is the whole explanation, and it is why installing ours twice at import
# time changed nothing.
#
# TWO INDEPENDENT DEFENCES, because this has now failed twice:
#
#   1. install_warning_filters() is called AGAIN after the GatewayBot is
#      constructed. Ordering is the actual fix - ours then prepends over
#      hikari's. It is the only one of the two that stops the warning being
#      formatted at all.
#
#   2. a logging filter on the "py.warnings" logger, which is where
#      captureWarnings(True) routes anything that survives the filters. This
#      does not depend on filter ORDER, so it holds even if some future
#      dependency prepends its own "always" after us.
#
# Defence 2 is also the answer to a reasonable theory that turned out to be only
# half right: the warnings DO travel through logging, which is why they arrive in
# journald wearing log formatting. But that is not why filters failed - warnings
# filters are consulted BEFORE showwarning, so captureWarnings alone would never
# have defeated them. Ordering did.
#
# TARGETED, never global: a blanket DeprecationWarning ignore hides our own
# deprecations, and the next real one would be invisible.
# ---------------------------------------------------------------------------
_UTCNOW_RE = r"datetime\.datetime\.utcnow\(\) is deprecated"
_UTCNOW_SUBSTR = "utcnow() is deprecated"


def install_warning_filters() -> None:
    """Silence coc.py's utcnow noise. Idempotent - called more than once.

    MUST be called after hikari.GatewayBot(...) is constructed. Calling it
    before as well is harmless and covers the import-time window.
    """
    warnings.filterwarnings(
        "ignore", message=_UTCNOW_RE, category=DeprecationWarning, module=r"coc.*"
    )
    # Same warning, attributed to OUR call frame rather than to coc: the
    # `module` filter matches the module the warning is RAISED in, and
    # stacklevel can push that onto the caller. Both spellings, or it leaks.
    warnings.filterwarnings("ignore", message=_UTCNOW_RE, category=DeprecationWarning)


class _DropUtcnowWarnings(logging.Filter):
    """Defence 2. Substring, not regex - it must not itself become a bug."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return _UTCNOW_SUBSTR not in record.getMessage()
        except Exception:  # noqa: BLE001 - a broken record must not kill logging
            return True


install_warning_filters()

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

import os
import hikari
import lightbulb
from dotenv import load_dotenv
from utils.mongo import MongoClient
import coc
from utils.startup import load_cogs
from utils.cloudinary_client import CloudinaryClient
from extensions.autocomplete import preload_autocomplete_cache
from utils import bot_data

load_dotenv()

# Create a GatewayBot instance with intents and custom rate limit settings
#
# CONSTRUCTING THIS CLOBBERS OUR WARNING FILTERS. GatewayBot.__init__ calls
# ux.init_logging(), which prepends warnings.simplefilter("always",
# DeprecationWarning). Anything installed above this line loses. See the block
# at the top of the file, and DO NOT move the re-install below it back up here.
bot = hikari.GatewayBot(
    token=os.getenv("DISCORD_TOKEN"),
    intents=(
        hikari.Intents.GUILD_MESSAGES
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

# ---------------------------------------------------------------------------
# THE LINE THAT ACTUALLY SILENCES THE SPAM. It has to be here, after the
# GatewayBot above, because that constructor is what installs hikari's
# simplefilter("always", DeprecationWarning). filterwarnings prepends, so ours
# now sits in front of hikari's and wins.
install_warning_filters()

# Defence 2: order-independent. captureWarnings(True) - also set by
# init_logging - routes surviving warnings to the "py.warnings" logger, so a
# filter there catches anything that gets past the ordering above.
logging.getLogger("py.warnings").addFilter(_DropUtcnowWarnings())

# Prints what SURVIVED, not what was requested. The head of warnings.filters is
# the whole question: if entry 0 is not our "ignore", the ordering lost again.
print(
    "[startup] warning filters: "
    f"{len(warnings.filters)} active, head="
    f"{[(f[0], getattr(f[2], '__name__', f[2]), f[1].pattern if f[1] else None) for f in warnings.filters[:3]]}",
    flush=True,
)
# ---------------------------------------------------------------------------

client = lightbulb.client_from_app(bot)

mongo_client = MongoClient(uri=os.getenv("MONGODB_URI"))
clash_client = coc.Client(
    base_url='https://proxy.clashk.ing/v1',
    key_count=10,
    load_game_data=coc.LoadGameData(default=False),
    raw_attribute=True,
)

cloudinary_client = CloudinaryClient()

bot_data.data["mongo"] = mongo_client
bot_data.data["cloudinary_client"] = cloudinary_client
bot_data.data["bot"] = bot
bot_data.data["coc_client"] = clash_client

registry = client.di.registry_for(lightbulb.di.Contexts.DEFAULT)
registry.register_value(MongoClient, mongo_client)
registry.register_value(coc.Client, clash_client)
registry.register_value(CloudinaryClient, cloudinary_client)
registry.register_value(hikari.GatewayBot, bot)

@bot.listen(hikari.StartingEvent)
async def on_starting(_: hikari.StartingEvent) -> None:
    """Bot starting event"""
    all_extensions = [
        "extensions.components",
        "extensions.commands.clan.list",
        "extensions.commands.fwa.bases",
        "extensions.context_menus.get_message_id",
        "extensions.context_menus.get_user_id",
        "extensions.tasks.band_monitor",
        "extensions.tasks.recruit_role_cleanup",
        "extensions.tasks.cwl_reminder",
        "extensions.tasks.fwa_points_monitor",
        "extensions.tasks.band_sync_ical",
        "extensions.commands.fwa.upload_images",
        "extensions.commands.fwa.war_plans",
        "extensions.commands.tickets",
        "extensions.events.channel.ticket_channel_monitor",
        "extensions.events.message.message_events",  # Add message events handler
    ] + load_cogs(disallowed={"example"}, disallowed_folders={"tickets"})

    await client.load_extensions(*all_extensions)
    await client.start()
    await clash_client.login_with_tokens("")


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


@bot.listen(hikari.StoppingEvent)
async def on_stopping(_: hikari.StoppingEvent) -> None:
    """Bot stopping event"""
    # Properly close the coc.py client to avoid unclosed session warnings
    await clash_client.close()

bot.run()