import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
import time

import aiohttp
import hikari
import lightbulb
from pymongo import ReturnDocument

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    LinkButtonBuilder as LinkButton,
    ContainerComponentBuilder as Container,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from extensions.components import register_action
from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler
from utils.constants import RED_ACCENT, GREEN_ACCENT
from utils.emoji import emojis

loader = lightbulb.Loader()

# Debug logging is opt-in. API payloads may contain private BAND post content.
DEBUG_MODE = os.getenv("BAND_DEBUG", "False").lower() == "true"


def debug_print(*args, **kwargs):
    """Only print if DEBUG_MODE is enabled"""
    if DEBUG_MODE:
        print(*args, **kwargs)


# BAND API Configuration
BAND_API_BASE = "https://openapi.band.us/v2/band/posts"
BAND_ACCESS_TOKEN = "ZQAAAR-9LGjvTxYmwok2WaTSYvcrA8M84ZK3s5BQSxxmggdJkyIFUUT4KCFvH1QNz2I3syNF_2aKaPLtownMSAVAC7pprIKu1TD_600hDD8GjhvX"

# Change these to monitor a different Band group
TARGET_BAND_NAME = "FWA© New Sync"  # Must match the band name exactly as shown in BAND
TARGET_BAND_NO = "94643112"          # The number from the Band page URL (used for link buttons)

# Resolved at startup from TARGET_BAND_NAME
BAND_KEY = None

# Discord channel to send notifications
NOTIFICATION_CHANNEL_ID = 1003886984462340166
ALLOWED_ROLE_ID = 769130325460254740

# Check interval in seconds (10 minutes to reduce API load)
CHECK_INTERVAL_SECONDS = 600  # 10 minutes
RESPONSE_RETENTION_DAYS = 30
WAR_SYNC_MARKER = "PLEASE stop searching when the window closes after 1.5 hours"

# Global variables
band_check_task = None
bot_instance = None  # Store bot reference for sending messages
mongo_client = None  # Store mongo reference
startup_reconciler = None
POLL_FAILURE_LOG_INTERVAL_SECONDS = 60 * 60


@dataclass
class BandPollHealth:
    state: str = "stopped"
    last_error: str | None = None
    last_failure_at: datetime | None = None
    last_success_at: datetime | None = None
    last_log_at: datetime | None = None


poll_health = BandPollHealth()


class BandKeyResolutionError(RuntimeError):
    """The BAND list response could not provide the configured band's key."""


def _record_poll_failure(reason: str, now: datetime | None = None) -> None:
    """Always log a transition, then throttle an unchanged prolonged outage."""
    global poll_health
    current = now or datetime.now(timezone.utc)
    safe_reason = "_".join(str(reason).split())[:100] or "unknown_failure"
    should_log = (
        poll_health.state != "unhealthy"
        or poll_health.last_error != safe_reason
        or poll_health.last_log_at is None
        or (current - poll_health.last_log_at).total_seconds()
        >= POLL_FAILURE_LOG_INTERVAL_SECONDS
    )
    poll_health.state = "unhealthy"
    poll_health.last_error = safe_reason
    poll_health.last_failure_at = current
    if should_log:
        poll_health.last_log_at = current
        print(
            f"[BAND Monitor] monitor_poll_failed reason={safe_reason} "
            "action=check BAND API connectivity, credentials, and permissions"
        )


def _record_poll_success(now: datetime | None = None) -> None:
    """Record health and log only when a failed monitor recovers."""
    global poll_health
    current = now or datetime.now(timezone.utc)
    previous_error = poll_health.last_error
    if poll_health.state == "unhealthy":
        print(
            f"[BAND Monitor] monitor_poll_recovered "
            f"previous_error={previous_error or 'unknown_failure'}"
        )
    poll_health.state = "healthy"
    poll_health.last_error = None
    poll_health.last_success_at = current


async def resolve_band_key():
    """Look up the band_key from TARGET_BAND_NO using the BAND API"""
    global BAND_KEY
    url = "https://openapi.band.us/v2.1/bands"
    params = {"access_token": BAND_ACCESS_TOKEN}

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url, params=params) as response:
            data = await response.json(content_type=None)

    if data.get("result_code") != 1:
        result_code = data.get("result_code")
        debug_print(
            f"[BAND Monitor] Key resolution API error {result_code}: "
            f"{data.get('result_msg')}"
        )
        raise BandKeyResolutionError(f"BAND API result code {result_code}")

    result_data = data.get("result_data", {})
    # The bands list may be under "items" or "bands" depending on API version
    bands = result_data.get("bands", result_data.get("items", []))

    if not bands:
        debug_print(
            f"[BAND Monitor] No bands in key response; "
            f"result_data keys={list(result_data.keys())}"
        )
        raise BandKeyResolutionError("BAND API returned no bands")

    for band in bands:
        if band.get("name") == TARGET_BAND_NAME:
            resolved_key = band.get("band_key")
            if not resolved_key:
                raise BandKeyResolutionError("configured band has no band_key")
            BAND_KEY = resolved_key
            print(f"[BAND Monitor] Resolved band key for '{TARGET_BAND_NAME}'")
            return True

    # If not found, print available bands to help debug
    debug_print(f"[BAND Monitor] No band found matching name: '{TARGET_BAND_NAME}'")
    debug_print("[BAND Monitor] Available bands:")
    for b in bands:
        debug_print(f"  - {b.get('name')}")
    raise BandKeyResolutionError(f"configured band '{TARGET_BAND_NAME}' not found")


async def fetch_band_posts():
    """Fetch posts from BAND API with enhanced error handling and timeout"""
    params = {
        "access_token": BAND_ACCESS_TOKEN,
        "band_key": BAND_KEY,
        "locale": "en_US"
    }

    # Create session with timeout
    timeout = aiohttp.ClientTimeout(total=30)  # 30 second timeout
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            debug_print(f"[BAND API] Making request to: {BAND_API_BASE}")
            debug_print(f"[BAND API] Band key resolved: {bool(BAND_KEY)}; locale=en_US")

            async with session.get(BAND_API_BASE, params=params) as response:
                debug_print(f"[BAND API] Response Status: {response.status}")
                text = await response.text()

                if response.status == 200:
                    try:
                        data = json.loads(text)
                        if "result_code" in data:
                            debug_print(f"[BAND API] result_code: {data['result_code']}")
                            if "result_msg" in data:
                                debug_print(f"[BAND API] result_msg: {data['result_msg']}")

                        return data
                    except json.JSONDecodeError as e:
                        debug_print(f"[BAND API] JSON Decode Error: {e}")
                        return None
                else:
                    debug_print(f"[BAND API] Non-200 Status: {response.status}")
                    return None

        except asyncio.TimeoutError:
            debug_print(f"[BAND API] Request timed out after 30 seconds")
            return None
        except aiohttp.ClientError as e:
            debug_print(f"[BAND API] Client Error: {type(e).__name__}: {e}")
            return None
        except Exception as e:
            debug_print(f"[BAND API] Unexpected Exception: {type(e).__name__}: {e}")
            import traceback
            debug_print(f"[BAND API] Traceback: {traceback.format_exc()}")
            return None


async def send_war_sync_to_discord(post):
    """Send a War Sync reminder to Discord channel using Components V2"""
    global bot_instance

    if not bot_instance:
        debug_print("[BAND Monitor] Bot instance not available!")
        return False

    # Create message ID for tracking responses.
    message_id = str(datetime.now().timestamp())
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ⚔️ War Sync Event has been posted."),
                Text(content=f"<@&{ALLOWED_ROLE_ID}> - A new FWA War Sync has been scheduled!"),
                Separator(divider=True),
                ActionRow(
                    components=[
                        LinkButton(
                            url=f"https://www.band.us/band/{TARGET_BAND_NO}",
                            label="Check FWA Sync Time",
                            emoji="🕐",
                        )
                    ]
                ),
                Text(content=(
                    "Please review the **FWA Sync Time** and confirm your availability by selecting the "
                    "corresponding button below:"
                )),
                Separator(divider=True),
                Text(content=f"{str(emojis.yes)} - If you are available to start."),
                Text(content=f"{str(emojis.maybe)} - If you may be available to start."),
                Text(content=f"{str(emojis.no)} - If you are unavailable to start."),
                Separator(divider=True),
                Text(content=(
                    "*Please note that if your availability changes, you can update your response by "
                    "selecting the appropriate button.*"
                )),
                Separator(divider=True),
                Text(content="## Rep Availability"),
                Text(content="*No responses yet...*"),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            label="Yes",
                            emoji=emojis.yes.partial_emoji,
                            custom_id=f"war_response:yes_{message_id}",
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Maybe",
                            emoji=emojis.maybe.partial_emoji,
                            custom_id=f"war_response:maybe_{message_id}",
                        ),
                        Button(
                            style=hikari.ButtonStyle.DANGER,
                            label="No",
                            emoji=emojis.no.partial_emoji,
                            custom_id=f"war_response:no_{message_id}",
                        ),
                    ]
                ),
            ],
        )
    ]

    try:
        await bot_instance.rest.create_message(
            channel=NOTIFICATION_CHANNEL_ID,
            components=components,
            user_mentions=True,
            role_mentions=[ALLOWED_ROLE_ID],
        )
        debug_print("[BAND Monitor] Sent War Sync reminder to Discord")
        return True
    except Exception as e:
        print(f"[BAND Monitor] Failed to send Discord message: {e}")
        return False


def posts_after_checkpoint(posts: list[dict], last_processed_key: str | None) -> list[dict]:
    """Return unseen BAND posts in oldest-first processing order."""
    unseen = []
    for post in posts:  # BAND returns newest first.
        post_key = post.get("post_key")
        if post_key == last_processed_key:
            break
        if post_key:
            unseen.append(post)

    # On the first run, establish a checkpoint without replaying feed history.
    if last_processed_key is None:
        unseen = unseen[:1]
    return list(reversed(unseen))


async def process_band_posts(mongo: MongoClient, posts: list[dict]) -> int:
    """Process unseen posts and advance only through successfully handled work."""
    checkpoint = await mongo.fwa_band_data.find_one({"_id": "last_processed_post"})
    last_processed_key = checkpoint.get("post_key") if checkpoint else None
    processed = 0

    # A brand-new install has no safe boundary for replaying BAND history.
    # Establish the newest post as the baseline without sending a stale alert.
    available_keys = [post.get("post_key") for post in posts if post.get("post_key")]
    if last_processed_key is None or last_processed_key not in available_keys:
        latest = next((post for post in posts if post.get("post_key")), None)
        if latest:
            await mongo.fwa_band_data.update_one(
                {"_id": "last_processed_post"},
                {"$set": {
                    "post_key": latest["post_key"],
                    "processed_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            if last_processed_key is not None:
                print(
                    "[BAND Monitor] Stored checkpoint was outside the returned feed; "
                    "established a new baseline without replaying unknown history"
                )
            return 1
        return 0

    for post in posts_after_checkpoint(posts, last_processed_key):
        post_key = post["post_key"]
        content = post.get("content", "")
        if WAR_SYNC_MARKER in content and not await send_war_sync_to_discord(post):
            print(f"[BAND Monitor] Delivery failed for {post_key}; checkpoint retained")
            break

        await mongo.fwa_band_data.update_one(
            {"_id": "last_processed_post"},
            {"$set": {
                "post_key": post_key,
                "processed_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
        processed += 1
    return processed


@register_action("war_response", no_return=True)
@lightbulb.di.with_di
async def on_war_response(
        action_id: str,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs
):
    """Handle war sync response buttons"""
    ctx: lightbulb.components.MenuContext = kwargs["ctx"]
    response_type, message_id = action_id.split("_", 1)

    # Check if user has the required role
    member = ctx.member
    if not any(role == ALLOWED_ROLE_ID for role in member.role_ids):
        await ctx.respond(
            "❌ You don't have permission to respond to War Sync events.",
            ephemeral=True
        )
        return

    # Update one user's field atomically. The old read/replace sequence could lose a
    # simultaneous click and could race on the first insert.
    user_id = str(ctx.user.id)
    stored_data = await mongo.fwa_band_data.find_one_and_update(
        {"_id": message_id},
        {
            "$set": {f"responses.{user_id}": response_type},
            "$setOnInsert": {
                "created_at": datetime.now(timezone.utc),
                "expire_at": datetime.now(timezone.utc) + timedelta(days=RESPONSE_RETENTION_DAYS),
            },
        },
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    responses = stored_data.get("responses", {}) if stored_data else {user_id: response_type}

    # Build response lists
    yes_users = []
    maybe_users = []
    no_users = []

    for uid, resp in responses.items():
        mention = f"<@{uid}>"
        if resp == "yes":
            yes_users.append(mention)
        elif resp == "maybe":
            maybe_users.append(mention)
        elif resp == "no":
            no_users.append(mention)

    # Build response text
    response_lines = []
    if yes_users:
        for user in yes_users:
            response_lines.append(f"{str(emojis.yes)} **Available** - {user}")
    if maybe_users:
        for user in maybe_users:
            response_lines.append(f"{str(emojis.maybe)} **Maybe** - {user}")
    if no_users:
        for user in no_users:
            response_lines.append(f"{str(emojis.no)} **Unavailable** - {user}")

    if not response_lines:
        response_lines.append("*No responses yet...*")

    # Update the message with new responses
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Text(content="## ⚔️ War Sync Event has been posted."),
                Text(content=f"<@&{ALLOWED_ROLE_ID}> - A new FWA War Sync has been scheduled!"),
                Separator(divider=True),
                ActionRow(
                    components=[
                        LinkButton(
                            url=f"https://www.band.us/band/{TARGET_BAND_NO}",
                            label="Check FWA Sync Time",
                            emoji="🕐"
                        )
                    ]
                ),
                Text(content=(
                    "Please review the **FWA Sync Time** and confirm your availability by selecting the "
                    "corresponding button below:"
                )),
                Separator(divider=True),
                Text(content=f"{str(emojis.yes)} - If you are available to start."),
                Text(content=f"{str(emojis.maybe)} - If you may be available to start."),
                Text(content=f"{str(emojis.no)} - If you are unavailable to start."),
                Separator(divider=True),
                Text(content=(
                    "*Please note that if your availability changes, you can update your response by "
                    "selecting the appropriate button.*"
                )),
                Separator(divider=True),
                Text(content="## Rep Availability"),
                Text(content="\n".join(response_lines)),
                ActionRow(
                    components=[
                        Button(
                            style=hikari.ButtonStyle.SUCCESS,
                            label="Yes",
                            emoji=emojis.yes.partial_emoji,
                            custom_id=f"war_response:yes_{message_id}"
                        ),
                        Button(
                            style=hikari.ButtonStyle.SECONDARY,
                            label="Maybe",
                            emoji=emojis.maybe.partial_emoji,
                            custom_id=f"war_response:maybe_{message_id}"
                        ),
                        Button(
                            style=hikari.ButtonStyle.DANGER,
                            label="No",
                            emoji=emojis.no.partial_emoji,
                            custom_id=f"war_response:no_{message_id}"
                        ),
                    ]
                ),
            ]
        )
    ]

    # Update the message
    await ctx.interaction.edit_initial_response(components=components)


async def check_band_once(mongo: MongoClient) -> bool:
    """Run one existing BAND poll and update operator-visible runtime health."""
    global BAND_KEY

    if not BAND_KEY:
        resolved = await resolve_band_key()
        if not resolved or not BAND_KEY:
            raise BandKeyResolutionError("BAND key resolver returned no key")
    data = await fetch_band_posts()

    if data is None:
        debug_print("[BAND Monitor] fetch_band_posts returned None")
        _record_poll_failure("band_request_failed")
        return False
    if not isinstance(data, dict) or "result_code" not in data:
        debug_print("[BAND Monitor] Unexpected API response format")
        _record_poll_failure("unexpected_band_response")
        return False

    result_code = data.get("result_code")
    result_msg = data.get("result_msg", "No message provided")
    debug_print(
        f"[BAND Monitor] API Response - Code: {result_code}, "
        f"Message: {result_msg}"
    )

    if result_code != 1:
        debug_print(
            f"[BAND Monitor] API returned error code {result_code}: {result_msg}"
        )
        _record_poll_failure(f"band_api_result_{result_code}")
        if result_code == -102:
            # BAND says the cached key is invalid. Resolve it again on the next
            # normal poll; do not change the established polling cadence.
            BAND_KEY = None
        return False

    posts = data.get("result_data", {}).get("items", [])
    debug_print(f"[BAND Monitor] Found {len(posts)} posts")
    if posts:
        processed = await process_band_posts(mongo, posts)
        if processed == 0:
            debug_print("[BAND Monitor] No new posts since last check.")
    else:
        debug_print("[BAND Monitor] No posts found in API response")

    _record_poll_success()
    return True


async def band_checker_loop(mongo: MongoClient):
    """Main loop that checks BAND API periodically"""
    debug_print("[BAND Monitor] Starting BAND API monitoring task...")

    # Log initial configuration without credentials or private API payloads.
    debug_print(f"[BAND Monitor] Configuration:")
    debug_print(f"  - API Base: {BAND_API_BASE}")
    debug_print(f"  - Band Key resolved: {bool(BAND_KEY)}")
    debug_print(f"  - Notification Channel: {NOTIFICATION_CHANNEL_ID}")
    debug_print(f"  - Allowed Role: {ALLOWED_ROLE_ID}")
    debug_print(f"  - Check Interval: {CHECK_INTERVAL_SECONDS} seconds ({CHECK_INTERVAL_SECONDS//60} minutes)")

    while True:
        try:
            debug_print(f"\n{'=' * 60}")
            debug_print(f"[BAND Monitor] Checking at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            # Track execution time
            start_time = time.time()

            await check_band_once(mongo)
            
            # Log execution time
            elapsed_time = time.time() - start_time
            debug_print(f"[BAND Monitor] Check completed in {elapsed_time:.2f} seconds")

        except Exception as e:
            _record_poll_failure(f"monitor_exception_{type(e).__name__}")
            debug_print(f"[BAND Monitor] Error in loop: {type(e).__name__}: {e}")
            import traceback
            debug_print(f"[BAND Monitor] Traceback: {traceback.format_exc()}")
            
            # Log execution time even on error
            elapsed_time = time.time() - start_time
            debug_print(f"[BAND Monitor] Check failed after {elapsed_time:.2f} seconds")

        # Wait before next check
        debug_print(f"\n[BAND Monitor] Waiting {CHECK_INTERVAL_SECONDS} seconds ({CHECK_INTERVAL_SECONDS//60} minutes) until next check...")
        debug_print(f"{'=' * 60}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def _reconcile_band_startup() -> None:
    """Resolve BAND configuration and start exactly one existing monitor loop."""
    global band_check_task, poll_health

    if band_check_task and not band_check_task.done():
        return

    resolved = await resolve_band_key()
    if not resolved or not BAND_KEY:
        raise BandKeyResolutionError("BAND key resolver returned no key")

    try:
        await mongo_client.fwa_band_data.create_index(
            "expire_at", expireAfterSeconds=0, name="ttl_expire_at"
        )
    except Exception as e:
        print(
            f"[BAND Monitor] WARNING response_ttl_index_unavailable "
            f"error={type(e).__name__}; monitor delivery is unaffected"
        )

    poll_health = BandPollHealth(state="starting")
    band_check_task = asyncio.create_task(band_checker_loop(mongo_client))
    print(
        f"[BAND Monitor] monitor_started "
        f"poll_interval_seconds={CHECK_INTERVAL_SECONDS}"
    )


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
        event: hikari.StartedEvent,
        mongo: MongoClient = lightbulb.di.INJECTED
) -> None:
    """Start non-blocking, self-healing BAND monitor initialization."""
    global bot_instance, mongo_client, startup_reconciler

    bot_instance = event.app
    mongo_client = mongo

    if startup_reconciler is None:
        startup_reconciler = StartupReconciler(
            "band_post_monitor",
            _reconcile_band_startup,
        )
    startup_reconciler.start()


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    """Cancel the task when bot is stopping"""
    global band_check_task, startup_reconciler, poll_health

    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None

    if band_check_task and not band_check_task.done():
        band_check_task.cancel()
        await asyncio.gather(band_check_task, return_exceptions=True)
    band_check_task = None
    poll_health.state = "stopped"
    print("[BAND Monitor] monitor_stopped")


@loader.command
class BandMonitorStatus(
    lightbulb.SlashCommand,
    name="band-monitor-status",
    description="Show BAND post monitor runtime health",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        task_running = bool(band_check_task and not band_check_task.done())
        startup_status = (
            startup_reconciler.status_text()
            if startup_reconciler is not None
            else "⏹️ Stopped"
        )
        lines = [
            "## BAND Post Monitor",
            f"• **Task:** {'✅ Running' if task_running else '❌ Not running'}",
            f"• **Startup recovery:** {startup_status}",
            f"• **BAND key:** {'✅ Resolved' if BAND_KEY else '❌ Missing'}",
            f"• **Poll health:** {poll_health.state}",
        ]
        if poll_health.last_success_at:
            lines.append(
                f"• **Last successful poll:** "
                f"<t:{int(poll_health.last_success_at.timestamp())}:R>"
            )
        if poll_health.last_error:
            lines.append(f"• **Last error:** `{poll_health.last_error}`")
        await ctx.respond("\n".join(lines), ephemeral=True)


@loader.command
class ToggleDebug(
    lightbulb.SlashCommand,
    name="toggle-debug",
    description="Toggle debug mode for BAND monitor",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        global DEBUG_MODE
        DEBUG_MODE = not DEBUG_MODE
        status = "ON" if DEBUG_MODE else "OFF"
        await ctx.respond(f"🔧 BAND Monitor debug mode: **{status}**", ephemeral=True)
        debug_print(f"[DEBUG] Debug mode toggled to: {status} by {ctx.user.username}")


@loader.command
class TestBandAPI(
    lightbulb.SlashCommand,
    name="test-band-api",
    description="Test the BAND API connection",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("🔍 Testing BAND API connection...", ephemeral=True)

        # Test the API
        data = await fetch_band_posts()

        if data:
            result_code = data.get("result_code", "N/A")
            result_msg = data.get("result_msg", "N/A")

            if result_code == 1:
                posts = data.get("result_data", {}).get("items", [])
                await ctx.edit_last_response(
                    f"✅ **BAND API Test Successful!**\n"
                    f"• Result Code: {result_code}\n"
                    f"• Result Message: {result_msg}\n"
                    f"• Posts Found: {len(posts)}"
                )
            else:
                await ctx.edit_last_response(
                    f"❌ **BAND API Error!**\n"
                    f"• Result Code: {result_code}\n"
                    f"• Result Message: {result_msg}\n\n"
                    f"**Common Error Codes:**\n"
                    f"• -101: Invalid access token (expired)\n"
                    f"• -102: Invalid band key\n"
                    f"• -103: No permission to access band"
                )
        else:
            await ctx.edit_last_response("❌ **Failed to connect to BAND API!** Check logs for details.")


@loader.command
class TestWarSync(
    lightbulb.SlashCommand,
    name="test-war-sync",
    description="Test the war sync notification with custom emojis",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.respond("🚀 Sending test war sync notification...", ephemeral=True)
        
        # Create a dummy post for testing
        test_post = {
            'author': {
                'name': 'Test FWA Rep'
            },
            'content': 'TEST WAR SYNC - This is a test notification to verify custom emojis are working correctly.',
            'post_key': 'test_' + str(datetime.now().timestamp())
        }
        
        try:
            # Call the send function directly
            delivered = await send_war_sync_to_discord(test_post)
            if delivered:
                await ctx.edit_last_response(
                    f"✅ **Test war sync sent!**\n"
                    f"Check <#{NOTIFICATION_CHANNEL_ID}> to see the notification and test the buttons."
                )
            else:
                await ctx.edit_last_response(
                    "❌ **Failed to send test notification.** Check the bot logs for the Discord error."
                )
        except Exception as e:
            await ctx.edit_last_response(
                f"❌ **Failed to send test notification!**\n"
                f"Error: {str(e)}"
            )
