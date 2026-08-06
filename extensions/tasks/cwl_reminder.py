import asyncio
import lightbulb
import hikari
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
import pendulum

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    LinkButtonBuilder as LinkButton,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler
from utils.constants import GOLDENROD_ACCENT, GREEN_ACCENT, RED_ACCENT, BLUE_ACCENT

loader = lightbulb.Loader()

# Configuration
CWL_CHANNEL_ID = 1072714594625257502
LAZY_CWL_CHANNEL_ID = 865726525990633472  # Same for testing, change to actual channel later
TEST_CHANNEL_ID = 947166650321494067  # Test channel for development/testing
DEFAULT_TIMEZONE = "America/New_York"
ROLE_TO_PING = 1080521665584308286
MAIN_FORM_URL = "https://forms.gle/ntB6qFvstu4gKUXc6"
LAZY_FORM_URL = "https://forms.gle/qeow1ygVaJQeRC26A"
LAZY_DISCUSSION_CHANNEL = 872692009066958879

# Global variables
scheduler = AsyncIOScheduler(timezone=DEFAULT_TIMEZONE)
bot_instance = None
mongo_client = None
startup_reconciler = None
cwl_base_job_id = "cwl_monthly_reminder"
cwl_followup_job_prefix = "cwl_followup_"
cwl_initial_retry_job_id = "cwl_initial_retry"
DELIVERY_RETRY_DELAYS_MINUTES = (5, 15, 30, 60, 180)
# Kept for command text and backwards compatibility. The first retry remains
# five minutes after a failed delivery.
DELIVERY_RETRY_MINUTES = DELIVERY_RETRY_DELAYS_MINUTES[0]
MAX_DELIVERY_FAILURES = len(DELIVERY_RETRY_DELAYS_MINUTES) + 1
MAX_DELIVERY_RETRY_AGE_HOURS = 24
DELIVERY_ERROR_TEXT_LIMIT = 180
PENDING_EXPIRY_DAYS = 7
JOB_OPTIONS = {
    "misfire_grace_time": 24 * 60 * 60,
    "coalesce": True,
    "max_instances": 1,
}
PRODUCTION_CHANNELS = {
    "main": {"id": CWL_CHANNEL_ID, "type": "main", "name": "Main"},
    "lazy": {"id": LAZY_CWL_CHANNEL_ID, "type": "lazy", "name": "Lazy"},
}


def get_signup_close_timestamp(schedule_day: int) -> str:
    """Calculate and return Discord timestamp for signup closing (2 days before end of month)"""
    now = pendulum.now(DEFAULT_TIMEZONE)
    
    # Get the last day of the current month
    last_day_of_month = now.end_of("month")
    
    # Subtract 2 days to get the close date
    close_date = last_day_of_month.subtract(days=2).replace(hour=17, minute=0, second=0)
    
    # If we're already past the close date this month, get next month's close date
    if now > close_date:
        next_month = now.add(months=1)
        last_day_of_next_month = next_month.end_of("month")
        close_date = last_day_of_next_month.subtract(days=2).replace(hour=17, minute=0, second=0)
    
    # Convert to Unix timestamp for Discord
    # Discord will display this in the user's local timezone
    return f"<t:{int(close_date.timestamp())}:D>"


def create_cwl_reminder_message(reminder_number: int = 0, channel_type: str = "main") -> list[Container]:
    """Create a CWL reminder message based on the reminder number and channel type"""
    
    # Components based on channel type
    if channel_type == "lazy":
        # Only Lazy CWL button for lazy channel
        button_components = [
            LinkButton(
                url=LAZY_FORM_URL,
                label="Lazy CWL",
                emoji="😴"
            ),
        ]
    else:
        # Both buttons for main channel
        button_components = [
            LinkButton(
                url=MAIN_FORM_URL,
                label="Main Clan",
                emoji="📋"
            ),
            LinkButton(
                url=LAZY_FORM_URL,
                label="Lazy CWL",
                emoji="😴"
            ),
        ]
    
    if reminder_number == 0:
        # Initial reminder
        if channel_type == "lazy":
            # Lazy channel version
            components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(content="## <:CWL:1399013745598009375> CWL Time <:CWL:1399013745598009375>"),
                        Separator(divider=True),
                        Text(content=(
                            "The below form is required to participate within the Warriors United Lazy CWL Operation.\n\n"
                            "The form take less then a couple minutes to complete and the sooner you sign up "
                            "the better it is on us making Rosters.\n\n"
                            "Remember...if you are in one of our FWA Clans it's \"LAZY WAY OR NO WAY!!\" "
                            "Outside involvement is not permitted."
                        )),
                        Text(content=f"\nDirect all questions and concerns in <#{LAZY_DISCUSSION_CHANNEL}> <:warriorcat:947992348971905035>"),
                        Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
                        ActionRow(components=button_components),
                    ]
                )
            ]
        else:
            # Main channel version
            components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(content="## <:CWL:1399013745598009375> CWL Time <:CWL:1399013745598009375>"),
                        Separator(divider=True),
                        Text(content=(
                            "Below are the two signup forms required to participate here in Warriors United CWL. "
                            "LazyCWL is an option for all within the Family but if your in one of our FWA Clans "
                            "it's \"Lazy Way or No Way\"."
                        )),
                        Text(content=(
                            "\nThe forms take less then a couple minutes to complete and the sooner you sign up "
                            "the better it is on us making Rosters.\n\n"
                            "Direct all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"
                        )),
                        Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
                        ActionRow(components=button_components),
                    ]
                )
            ]
    else:
        # Follow-up reminders
        close_timestamp = get_signup_close_timestamp(29)  # 29th of the month
        
        # Choose media based on reminder number
        media_item = None
        if reminder_number == 1:
            media_item = MediaItem(media="https://c.tenor.com/6b2bCHLqrUkAAAAd/tenor.gif")
        elif reminder_number == 2:
            media_item = MediaItem(media="https://media.tenor.com/0XVm8XNzxFUAAAAj/its-not-too-late-to-get-involved-engage.gif")
        elif reminder_number == 3:
            media_item = MediaItem(media="https://c.tenor.com/t-scOJYZGPEAAAAC/tenor.gif")
        elif reminder_number == 4:
            media_item = MediaItem(media="https://c.tenor.com/fc51xvY2Tq4AAAAd/tenor.gif")
        elif reminder_number == 5:
            media_item = MediaItem(media="https://c.tenor.com/egVC6wj7VV8AAAAC/tenor.gif")
        else:
            media_item = MediaItem(media="assets/Gold_Footer.png")
        
        if channel_type == "lazy":
            # Lazy channel version of follow-ups
            components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(content=f"## <:CWL:1399013745598009375> Sign-up Reminder #{reminder_number} <:CWL:1399013745598009375>"),
                        Separator(divider=True),
                        Text(content=(
                            "**If you already signed up, we got ya down. No need to sign up again. But everyone else...**\n\n"
                            "The below form is required to participate within the Warriors United Lazy CWL Operation.\n\n"
                            "The form take less then a couple minutes to complete and the sooner you sign up "
                            "the better it is on us making Rosters.\n\n"
                            "Remember...if you are in one of our FWA Clans it's \"LAZY WAY OR NO WAY!!\" "
                            "Outside involvement is not permitted."
                        )),
                        Text(content=f"\n# **Signups close {close_timestamp}**"),
                        Text(content=f"\nDirect all questions and concerns in <#{LAZY_DISCUSSION_CHANNEL}> <:warriorcat:947992348971905035>"),
                        Media(items=[media_item]),
                        ActionRow(components=button_components),
                    ]
                )
            ]
        else:
            # Main channel version of follow-ups
            components = [
                Container(
                    accent_color=GOLDENROD_ACCENT,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(content=f"## <:CWL:1399013745598009375> Sign-up Reminder #{reminder_number} <:CWL:1399013745598009375>"),
                        Separator(divider=True),
                        Text(content=(
                            "**If you already signed up, we got ya down. No need to sign up again. But everyone else...**\n\n"
                            "Below are the two signup forms required to participate here in Warriors United CWL. "
                            "LazyCWL is an option for all within the Family but if your in one of our FWA Clans "
                            "it's \"Lazy Way or No Way\"."
                        )),
                        Text(content=(
                            "\nThe forms take less then a couple minutes to complete and the sooner you sign up "
                            "the better it is on us making Rosters."
                        )),
                        Text(content=f"\n# **Signups close {close_timestamp}**"),
                        Text(content="\nDirect all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"),
                        Media(items=[media_item]),
                        ActionRow(components=button_components),
                    ]
                )
            ]
    
    return components


def _pending_job_id(reminder_number: int) -> str:
    if reminder_number == 0:
        return cwl_initial_retry_job_id
    return f"{cwl_followup_job_prefix}{reminder_number}"


def _month_run(year: int, month: int, day: int, hour: int, minute: int):
    """Return a configured run in a month, or None when that day does not exist."""
    try:
        return pendulum.datetime(
            year, month, day, hour, minute, tz=DEFAULT_TIMEZONE,
        )
    except ValueError:
        return None


def next_monthly_run(
    day: int,
    hour: int,
    minute: int,
    now: datetime | None = None,
):
    """Return the next Cron-compatible monthly occurrence for days 1 through 31."""
    current = pendulum.instance(now, tz=DEFAULT_TIMEZONE) if now else pendulum.now(DEFAULT_TIMEZONE)
    candidate_month = current.start_of("month")

    for _ in range(24):
        candidate = _month_run(
            candidate_month.year,
            candidate_month.month,
            day,
            hour,
            minute,
        )
        if candidate is not None and candidate > current:
            return candidate
        candidate_month = candidate_month.add(months=1)

    raise ValueError(f"Could not calculate the next monthly run for day {day}")


def get_last_sent(schedule_data: dict):
    """Read the initial reminder timestamp, with compatibility for legacy data."""
    return schedule_data.get("last_sent_0") or schedule_data.get("last_sent")


async def remove_followup_configuration(number: int, mongo: MongoClient) -> bool:
    """Remove a configured follow-up and all of its runnable state."""
    schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
    if not schedule_data:
        return False

    followups = schedule_data.get("followups", [])
    remaining = [item for item in followups if item.get("number") != number]
    if len(remaining) == len(followups):
        return False

    await mongo.database.cwl_reminder.update_one(
        {"_id": "schedule"},
        {"$set": {"followups": remaining}},
    )

    job_id = f"{cwl_followup_job_prefix}{number}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    await mongo.database.cwl_pending_reminders.delete_one({"_id": job_id})
    return True


def _add_reminder_job(
    job_id: str,
    run_time: datetime,
    reminder_number: int,
    channel_keys: list[str] | None = None,
) -> None:
    scheduler.add_job(
        send_cwl_reminder,
        trigger=DateTrigger(run_date=run_time, timezone=DEFAULT_TIMEZONE),
        id=job_id,
        args=[reminder_number, False, channel_keys],
        replace_existing=True,
        **JOB_OPTIONS,
    )


async def _persist_pending_reminder(
    job_id: str,
    run_time: datetime,
    reminder_number: int,
    channel_keys: list[str] | None = None,
    *,
    reset_delivery_state: bool = True,
) -> None:
    if not mongo_client:
        return

    reminder_data = {
        "_id": job_id,
        "reminder_number": reminder_number,
        "run_time": run_time.isoformat(),
        "job_id": job_id,
    }
    if channel_keys:
        reminder_data["channel_keys"] = channel_keys

    update = {
        "$set": reminder_data,
        "$setOnInsert": {
            "created_at": pendulum.now(DEFAULT_TIMEZONE).isoformat(),
        },
    }
    if reset_delivery_state:
        update["$unset"] = {
            "failure_count": "",
            "first_failed_at": "",
            "last_failed_at": "",
            "last_error": "",
            "error_types": "",
            "status": "",
            "abandon_reason": "",
            "updated_at": "",
        }
        if not channel_keys:
            update["$unset"]["channel_keys"] = ""

    await mongo_client.database.cwl_pending_reminders.update_one(
        {"_id": job_id},
        update,
        upsert=True,
    )


async def _schedule_durable_reminder(
    job_id: str,
    run_time: datetime,
    reminder_number: int,
    channel_keys: list[str] | None = None,
) -> None:
    """Persist a date job before exposing it to the in-memory scheduler."""
    await _persist_pending_reminder(job_id, run_time, reminder_number, channel_keys)
    _add_reminder_job(job_id, run_time, reminder_number, channel_keys)


def _delivery_error_detail(exc: Exception) -> str:
    """Return a bounded one-line diagnostic safe for logs and MongoDB."""
    detail = " ".join(str(exc).split()) or "no error detail"
    return detail[:DELIVERY_ERROR_TEXT_LIMIT]


def _is_permanent_delivery_error(exc: Exception) -> bool:
    """Discord errors that require configuration/permission changes, not retries."""
    return isinstance(
        exc,
        (
            hikari.BadRequestError,
            hikari.UnauthorizedError,
            hikari.ForbiddenError,
            hikari.NotFoundError,
        ),
    )


def _delivery_issue_field(reminder_number: int) -> str:
    return f"delivery_issues.{reminder_number}"


async def _record_delivery_issue(reminder_number: int, issue: dict) -> None:
    await mongo_client.database.cwl_reminder.update_one(
        {"_id": "schedule"},
        {"$set": {_delivery_issue_field(reminder_number): issue}},
        upsert=True,
    )


async def _abandon_delivery(
    reminder_number: int,
    channel_keys: list[str],
    failure_count: int,
    reason: str,
    error_types: list[str],
    last_error: str,
) -> None:
    """Stop a terminal retry and retain one bounded operator-facing diagnostic."""
    job_id = _pending_job_id(reminder_number)
    now = pendulum.now(DEFAULT_TIMEZONE).isoformat()
    # Mark terminal before the cleanup writes. If MongoDB drops between calls,
    # startup restoration will discard this row instead of reviving the retry.
    await mongo_client.database.cwl_pending_reminders.update_one(
        {"_id": job_id},
        {
            "$set": {
                "status": "abandoned",
                "reminder_number": reminder_number,
                "job_id": job_id,
                "channel_keys": channel_keys,
                "failure_count": failure_count,
                "abandon_reason": reason,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        },
        upsert=True,
    )
    await _record_delivery_issue(
        reminder_number,
        {
            "status": "abandoned",
            "reason": reason,
            "failure_count": failure_count,
            "max_failures": MAX_DELIVERY_FAILURES,
            "channel_keys": channel_keys,
            "error_types": error_types,
            "last_error": last_error,
            "updated_at": now,
        },
    )
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    await mongo_client.database.cwl_pending_reminders.delete_one({"_id": job_id})
    print(
        f"[CWL Reminder] ALERT delivery_abandoned reminder={reminder_number} "
        f"reason={reason} failures={failure_count}/{MAX_DELIVERY_FAILURES} "
        f"channels={','.join(channel_keys)} errors={','.join(error_types)} "
        "action=check channel IDs, bot access, and Send Messages permission"
    )


async def _schedule_retry(
    reminder_number: int,
    channel_keys: list[str],
    failures: list[tuple[str, Exception]],
) -> bool:
    """Persist a bounded retry, or abandon failures that require intervention."""
    if not mongo_client:
        print(
            f"[CWL Reminder] ALERT delivery_retry_unavailable reminder={reminder_number} "
            f"channels={','.join(channel_keys)} reason=mongo_unavailable"
        )
        return False

    now = pendulum.now(DEFAULT_TIMEZONE)
    job_id = _pending_job_id(reminder_number)
    pending = await mongo_client.database.cwl_pending_reminders.find_one({"_id": job_id}) or {}
    try:
        previous_failures = max(0, int(pending.get("failure_count", 0)))
    except (TypeError, ValueError):
        previous_failures = 0
        print(
            f"[CWL Reminder] retry_state_repaired reminder={reminder_number} "
            "field=failure_count"
        )
    failure_count = previous_failures + 1
    first_failed_at = pending.get("first_failed_at")
    try:
        first_failed = pendulum.parse(first_failed_at) if first_failed_at else now
    except (TypeError, ValueError):
        first_failed = now

    error_types = sorted({type(exc).__name__ for _, exc in failures})
    last_error = "; ".join(
        f"{key}:{type(exc).__name__}:{_delivery_error_detail(exc)}"
        for key, exc in failures
    )[:DELIVERY_ERROR_TEXT_LIMIT]
    has_permanent_error = any(_is_permanent_delivery_error(exc) for _, exc in failures)
    retry_age_hours = max(0.0, (now - first_failed).total_seconds() / 3600)

    if has_permanent_error:
        await _abandon_delivery(
            reminder_number, channel_keys, failure_count, "permanent_discord_error",
            error_types, last_error,
        )
        return False
    if failure_count >= MAX_DELIVERY_FAILURES:
        await _abandon_delivery(
            reminder_number, channel_keys, failure_count, "max_failures_reached",
            error_types, last_error,
        )
        return False
    if retry_age_hours >= MAX_DELIVERY_RETRY_AGE_HOURS:
        await _abandon_delivery(
            reminder_number, channel_keys, failure_count, "retry_age_exceeded",
            error_types, last_error,
        )
        return False

    delay_minutes = DELIVERY_RETRY_DELAYS_MINUTES[failure_count - 1]
    run_time = now.add(minutes=delay_minutes)
    retry_state = {
        "_id": job_id,
        "reminder_number": reminder_number,
        "run_time": run_time.isoformat(),
        "job_id": job_id,
        "channel_keys": channel_keys,
        "failure_count": failure_count,
        "first_failed_at": first_failed.isoformat(),
        "last_failed_at": now.isoformat(),
        "last_error": last_error,
        "error_types": error_types,
        "status": "retrying",
    }
    await mongo_client.database.cwl_pending_reminders.update_one(
        {"_id": job_id},
        {
            "$set": retry_state,
            "$setOnInsert": {"created_at": now.isoformat()},
        },
        upsert=True,
    )
    await _record_delivery_issue(
        reminder_number,
        {
            "status": "retrying",
            "failure_count": failure_count,
            "max_failures": MAX_DELIVERY_FAILURES,
            "channel_keys": channel_keys,
            "error_types": error_types,
            "last_error": last_error,
            "next_retry_at": run_time.isoformat(),
            "updated_at": now.isoformat(),
        },
    )
    _add_reminder_job(job_id, run_time, reminder_number, channel_keys)
    print(
        f"[CWL Reminder] delivery_retry_scheduled reminder={reminder_number} "
        f"failure={failure_count}/{MAX_DELIVERY_FAILURES} delay_minutes={delay_minutes} "
        f"channels={','.join(channel_keys)} errors={','.join(error_types)} "
        f"next_retry={run_time.isoformat()}"
    )
    return True


async def send_cwl_reminder(
    reminder_number: int = 0,
    test_mode: bool = False,
    channel_keys: list[str] | None = None,
) -> bool:
    """Send a reminder and mutate production state only after full delivery."""
    global bot_instance, mongo_client

    if not bot_instance:
        print("[CWL Reminder] Bot instance not available!")
        return False

    reminder_type = "initial" if reminder_number == 0 else f"follow-up #{reminder_number}"
    if test_mode:
        channels = [{"id": TEST_CHANNEL_ID, "type": "main", "name": "Test", "key": "test"}]
    else:
        selected_keys = channel_keys or list(PRODUCTION_CHANNELS)
        channels = [
            {**PRODUCTION_CHANNELS[key], "key": key}
            for key in selected_keys
            if key in PRODUCTION_CHANNELS
        ]

    failures: list[tuple[str, Exception]] = []
    for channel_info in channels:
        try:
            components = create_cwl_reminder_message(reminder_number, channel_info["type"])
            await bot_instance.rest.create_message(
                channel=channel_info["id"],
                components=components,
                role_mentions=[ROLE_TO_PING],
            )
            print(
                f"[CWL Reminder] Sent {reminder_type} reminder to "
                f"{channel_info['name']} channel at {datetime.now()}"
            )
        except Exception as exc:
            failures.append((channel_info["key"], exc))
            print(
                f"[CWL Reminder] delivery_failed reminder={reminder_number} "
                f"channel={channel_info['key']} channel_id={channel_info['id']} "
                f"error={type(exc).__name__} retryable={str(not _is_permanent_delivery_error(exc)).lower()} "
                f"detail={_delivery_error_detail(exc)}"
            )

    # Tests are deliberately delivery-only. They never update the schedule,
    # pending reminders, or the production APScheduler.
    if test_mode:
        return not failures

    if failures:
        failed_keys = [key for key, _ in failures]
        try:
            await _schedule_retry(reminder_number, failed_keys, failures)
        except Exception as exc:
            print(
                f"[CWL Reminder] ALERT delivery_retry_setup_failed reminder={reminder_number} "
                f"channels={','.join(failed_keys)} error={type(exc).__name__} "
                f"detail={_delivery_error_detail(exc)} action=check MongoDB and scheduler health"
            )
        return False

    if not channels:
        invalid_keys = channel_keys or []
        if mongo_client:
            try:
                await _abandon_delivery(
                    reminder_number,
                    invalid_keys,
                    1,
                    "no_valid_channels",
                    ["ConfigurationError"],
                    "No configured production channel matched the stored channel keys",
                )
            except Exception as exc:
                print(
                    f"[CWL Reminder] ALERT delivery_retry_setup_failed reminder={reminder_number} "
                    f"error={type(exc).__name__} detail={_delivery_error_detail(exc)} "
                    "action=check MongoDB health"
                )
        else:
            print(
                f"[CWL Reminder] ALERT delivery_abandoned reminder={reminder_number} "
                "reason=no_valid_channels action=check stored channel keys"
            )
        return False

    if mongo_client:
        sent_at = datetime.now(timezone.utc).isoformat()
        await mongo_client.database.cwl_reminder.update_one(
            {"_id": "schedule"},
            {
                "$set": {f"last_sent_{reminder_number}": sent_at},
                "$unset": {_delivery_issue_field(reminder_number): ""},
            },
            upsert=True,
        )

        job_id = _pending_job_id(reminder_number)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        result = await mongo_client.database.cwl_pending_reminders.delete_one({"_id": job_id})
        if result.deleted_count > 0:
            print(f"[CWL Reminder] Cleaned up completed {reminder_type} reminder")

        if reminder_number == 0:
            schedule_data = await mongo_client.database.cwl_reminder.find_one({"_id": "schedule"})
            if schedule_data:
                cumulative_delay = 0
                base_time = pendulum.now(DEFAULT_TIMEZONE)
                for followup in sorted(
                    schedule_data.get("followups", []),
                    key=lambda item: item.get("number", 0),
                ):
                    if followup.get("enabled", True):
                        followup_num = followup.get("number")
                        cumulative_delay += followup.get("delay_minutes", 0)
                        if followup_num and cumulative_delay > 0:
                            await schedule_followup_reminder(
                                base_time, followup_num, cumulative_delay,
                            )
    else:
        print(
            f"[CWL Reminder] ALERT delivery_state_unavailable reminder={reminder_number} "
            "delivered=true action=check MongoDB; delivery accounting and follow-ups were not updated"
        )

    return True


async def schedule_followup_reminder(base_time: datetime, reminder_number: int, delay_minutes: int):
    """Schedule a follow-up reminder based on the base time and delay"""
    global scheduler, mongo_client

    # Calculate when this follow-up should run
    run_time = base_time + timedelta(minutes=delay_minutes)

    # Create job ID for this follow-up
    job_id = f"{cwl_followup_job_prefix}{reminder_number}"

    await _schedule_durable_reminder(job_id, run_time, reminder_number)

    print(f"[CWL Reminder] Scheduled follow-up #{reminder_number} for {run_time}")


async def restore_pending_reminders():
    """Restore pending follow-up reminders from MongoDB on bot startup"""
    global scheduler, mongo_client

    if not mongo_client:
        return

    print("[CWL Reminder] Checking for pending follow-up reminders...")

    # Get current time for comparison
    now = pendulum.now(DEFAULT_TIMEZONE)

    # Find all pending reminders
    pending_reminders = await mongo_client.database.cwl_pending_reminders.find().to_list(length=None)

    if not pending_reminders:
        print("[CWL Reminder] No pending reminders found")
        return

    restored_count = 0
    expired_count = 0
    failed_count = 0

    for reminder in pending_reminders:
        reminder_id = reminder.get("_id")
        run_time_str = reminder.get("run_time")
        reminder_number = reminder.get("reminder_number")
        job_id = reminder.get("job_id")

        if reminder.get("status") == "abandoned":
            await mongo_client.database.cwl_pending_reminders.delete_one({"_id": reminder_id})
            print(f"[CWL Reminder] Cleaned up terminal pending reminder {reminder_id}")
            continue

        if (
            not reminder_id
            or not run_time_str
            or reminder_number is None
            or not job_id
        ):
            # Invalid reminder data, clean it up
            await mongo_client.database.cwl_pending_reminders.delete_one({"_id": reminder_id})
            continue

        try:
            run_time = pendulum.parse(run_time_str)
        except Exception as e:
            print(f"[CWL Reminder] Invalid pending reminder {reminder_id}: {e}")
            await mongo_client.database.cwl_pending_reminders.delete_one({"_id": reminder_id})
            continue

        try:
            if run_time > now:
                channel_keys = reminder.get("channel_keys")
                _add_reminder_job(job_id, run_time, reminder_number, channel_keys)

                print(f"[CWL Reminder] Restored follow-up #{reminder_number} for {run_time}")
                restored_count += 1
            elif run_time >= now.subtract(days=PENDING_EXPIRY_DAYS):
                # Date jobs disappear from the in-memory scheduler when they
                # fire. If the process was down at that instant, retry shortly
                # after startup instead of treating an undelivered reminder as
                # complete.
                retry_time = now.add(seconds=5)
                channel_keys = reminder.get("channel_keys")
                await _persist_pending_reminder(
                    job_id,
                    retry_time,
                    reminder_number,
                    channel_keys,
                    reset_delivery_state=False,
                )
                _add_reminder_job(job_id, retry_time, reminder_number, channel_keys)
                print(
                    f"[CWL Reminder] Restored overdue reminder #{reminder_number} "
                    f"for retry at {retry_time}"
                )
                restored_count += 1
            else:
                # Reminder has expired, clean it up
                await mongo_client.database.cwl_pending_reminders.delete_one({"_id": reminder_id})
                print(f"[CWL Reminder] Cleaned up expired reminder #{reminder_number} (was scheduled for {run_time})")
                expired_count += 1

        except Exception as e:
            # Keep valid durable state so another restart can recover it if
            # scheduler registration is temporarily unavailable.
            print(f"[CWL Reminder] Error scheduling reminder {reminder_id}: {e}")
            failed_count += 1

    if restored_count > 0:
        print(f"[CWL Reminder] Successfully restored {restored_count} pending reminder(s)")
    if expired_count > 0:
        print(f"[CWL Reminder] Cleaned up {expired_count} expired reminder(s)")
    if failed_count > 0:
        raise RuntimeError(
            f"failed to restore {failed_count} pending reminder(s); durable state retained"
        )


async def restore_missed_base_reminder(
    schedule_data: dict,
    now: datetime | None = None,
) -> bool:
    """Create a durable near-term retry for a recently missed monthly base run."""
    current = pendulum.instance(now, tz=DEFAULT_TIMEZONE) if now else pendulum.now(DEFAULT_TIMEZONE)
    scheduled_time = _month_run(
        current.year,
        current.month,
        int(schedule_data["day"]),
        int(schedule_data["hour"]),
        int(schedule_data["minute"]),
    )
    if scheduled_time is None or scheduled_time > current:
        return False

    last_sent = get_last_sent(schedule_data)
    if last_sent:
        try:
            if pendulum.parse(last_sent).in_timezone(DEFAULT_TIMEZONE) >= scheduled_time:
                return False
        except (TypeError, ValueError):
            print("[CWL Reminder] Ignoring invalid stored last-sent timestamp")

    # Avoid stale signup reminders long after their useful window and do not
    # duplicate a pending initial-delivery retry restored just above.
    if scheduled_time < current.subtract(days=PENDING_EXPIRY_DAYS):
        print(
            f"[CWL Reminder] Missed base reminder from {scheduled_time} is too old; "
            "no catch-up scheduled"
        )
        return False
    if scheduler.get_job(cwl_initial_retry_job_id):
        return False

    retry_time = current.add(seconds=5)
    await _schedule_durable_reminder(cwl_initial_retry_job_id, retry_time, 0)
    print(f"[CWL Reminder] Restored missed base reminder for retry at {retry_time}")
    return True


async def schedule_cwl_reminder(
    day: int,
    hour: int,
    minute: int,
):
    """Schedule or reschedule the CWL reminder"""
    global scheduler, mongo_client
    
    # Remove existing base job if any
    if scheduler.get_job(cwl_base_job_id):
        scheduler.remove_job(cwl_base_job_id)
    
    # Create new trigger for base reminder
    trigger = CronTrigger(
        day=day,
        hour=hour,
        minute=minute,
        timezone=DEFAULT_TIMEZONE
    )
    
    # Schedule the base job
    scheduler.add_job(
        send_cwl_reminder,
        trigger=trigger,
        id=cwl_base_job_id,
        args=[0],  # reminder_number = 0 for base reminder
        replace_existing=True,
        **JOB_OPTIONS,
    )
    
    # Save to MongoDB
    if mongo_client:
        await mongo_client.database.cwl_reminder.update_one(
            {"_id": "schedule"},
            {"$set": {
                "day": day,
                "hour": hour,
                "minute": minute,
                "timezone": DEFAULT_TIMEZONE,
                "enabled": True,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
    
    return True


async def _reconcile_cwl_startup() -> None:
    """Idempotently restore durable CWL jobs after dependencies are ready."""
    if not getattr(scheduler, "running", True):
        scheduler.start()

    # Current-cycle date jobs are the authoritative pending state. Restore
    # them before installing the next recurring base schedule so a restart
    # cannot replace them with next month's calculated follow-ups.
    await restore_pending_reminders()
    
    # Load saved schedule from MongoDB
    schedule_data = await mongo_client.database.cwl_reminder.find_one({"_id": "schedule"})
    
    if schedule_data and schedule_data.get("enabled", False):
        day = schedule_data.get("day")
        hour = schedule_data.get("hour")
        minute = schedule_data.get("minute")
        
        if all(x is not None for x in [day, hour, minute]):
            await restore_missed_base_reminder(schedule_data)
            
            # Schedule base reminder
            await schedule_cwl_reminder(day, hour, minute)
            print(f"[CWL Reminder] Loaded base schedule: Day {day} at {hour:02d}:{minute:02d}")
            
            # Load and display follow-ups
            followups = schedule_data.get("followups", [])
            if followups:
                print(f"[CWL Reminder] Found {len(followups)} follow-up reminder(s) to schedule:")
                for f in followups:
                    if f.get("enabled", True):
                        # Try to get delay_display, fall back to calculating from delay_minutes
                        delay_display = f.get('delay_display')
                        if not delay_display and f.get('delay_minutes'):
                            minutes = f.get('delay_minutes', 0)
                            if minutes >= 1440:
                                delay_display = f"{minutes // 1440} days"
                            elif minutes >= 60:
                                delay_display = f"{minutes // 60} hours"
                            else:
                                delay_display = f"{minutes} minutes"
                        print(f"  - Reminder #{f.get('number')}: {delay_display or 'unknown delay'}")


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED
) -> None:
    """Start non-blocking, self-healing restoration of the saved schedule."""
    global bot_instance, mongo_client, startup_reconciler

    bot_instance = event.app
    mongo_client = mongo

    if startup_reconciler is None:
        startup_reconciler = StartupReconciler(
            "cwl_reminder",
            _reconcile_cwl_startup,
        )
    startup_reconciler.start()

@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    """Shutdown scheduler when bot stops"""
    global startup_reconciler
    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None
    if getattr(scheduler, "running", False):
        scheduler.shutdown()
        print("[CWL Reminder] Scheduler shutdown")


# Create command group
cwl_reminder = lightbulb.Group(
    "cwl-reminder", 
    "Manage CWL monthly reminders",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR
)


@cwl_reminder.register()
class Schedule(
    lightbulb.SlashCommand,
    name="schedule",
    description="Schedule the monthly CWL reminder"
):
    day = lightbulb.integer(
        "day",
        "Day of the month (1-31)",
        min_value=1,
        max_value=31
    )
    
    hour = lightbulb.integer(
        "hour",
        "Hour (0-23, 24-hour format)",
        min_value=0,
        max_value=23
    )
    
    minute = lightbulb.integer(
        "minute",
        "Minute (0-59)",
        min_value=0,
        max_value=59,
        default=0
    )
    
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.defer(ephemeral=True)
        
        try:
            await schedule_cwl_reminder(self.day, self.hour, self.minute)
            
            # Format time for display
            hour_12 = self.hour % 12 or 12
            am_pm = "AM" if self.hour < 12 else "PM"
            
            await ctx.respond(
                f"✅ **CWL Reminder Scheduled!**\n"
                f"• Day: {self.day} of every month\n"
                f"• Time: {hour_12}:{self.minute:02d} {am_pm} ({DEFAULT_TIMEZONE})\n"
                f"• Main CWL Channel: <#{CWL_CHANNEL_ID}>\n"
                f"• Lazy CWL Channel: <#{LAZY_CWL_CHANNEL_ID}>"
            )
        except Exception as e:
            await ctx.respond(
                f"❌ **Failed to schedule reminder!**\n"
                f"Error: {str(e)}"
            )


@cwl_reminder.register()
class Status(
    lightbulb.SlashCommand,
    name="status",
    description="Check the current CWL reminder schedule"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        startup_status = (
            startup_reconciler.status_text()
            if startup_reconciler is not None
            else "⏹️ Stopped"
        )
        # Get schedule from MongoDB
        try:
            schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        except Exception as exc:
            await ctx.respond(
                "## CWL Reminder Status\n"
                f"• **Startup recovery**: {startup_status}\n"
                f"• **MongoDB**: ❌ Unavailable ({type(exc).__name__})",
                ephemeral=True,
            )
            return
        
        if not schedule_data or not schedule_data.get("enabled", False):
            await ctx.respond(
                "❌ **No CWL reminder scheduled**\n"
                f"• **Startup recovery**: {startup_status}\n"
                "Use `/cwl-reminder schedule` to set one up.",
                ephemeral=True
            )
            return
        
        day = schedule_data.get("day", "?")
        hour = schedule_data.get("hour", 0)
        minute = schedule_data.get("minute", 0)
        last_sent = get_last_sent(schedule_data)
        
        # Format time for display
        hour_12 = hour % 12 or 12
        am_pm = "AM" if hour < 12 else "PM"
        
        # Check if job is actually scheduled
        job = scheduler.get_job(cwl_base_job_id)
        job_status = "✅ Active" if job else "❌ Not running"
        status_text = (
            f"## CWL Reminder Status\n"
            f"• **Monthly schedule**: Day {day} at {hour_12}:{minute:02d} {am_pm} ({DEFAULT_TIMEZONE})\n"
            f"• **Main CWL Channel**: <#{CWL_CHANNEL_ID}>\n"
            f"• **Lazy CWL Channel**: <#{LAZY_CWL_CHANNEL_ID}>\n"
            f"• **Scheduler job**: {job_status}\n"
            f"• **Startup recovery**: {startup_status}"
        )
        
        if last_sent:
            last_sent_dt = pendulum.parse(last_sent)
            status_text += f"\n• **Last Sent**: {last_sent_dt.format('MMM D, YYYY [at] h:mm A')}"
        
        if job:
            next_run = job.next_run_time
            if next_run:
                next_run_pdt = pendulum.instance(next_run, tz=DEFAULT_TIMEZONE)
                status_text += f"\n• **Next Run**: {next_run_pdt.format('MMM D, YYYY [at] h:mm A')}"

        delivery_issues = schedule_data.get("delivery_issues", {})
        reason_labels = {
            "permanent_discord_error": "channel access or permission needs attention",
            "max_failures_reached": "retry limit reached",
            "retry_age_exceeded": "retry window expired",
            "no_valid_channels": "channel configuration is invalid",
        }
        for number, issue in sorted(delivery_issues.items(), key=lambda item: str(item[0])):
            reminder_label = "initial" if str(number) == "0" else f"follow-up {number}"
            failure_count = issue.get("failure_count", "?")
            max_failures = issue.get("max_failures", MAX_DELIVERY_FAILURES)
            channels = ", ".join(issue.get("channel_keys", [])) or "unknown channel"
            if issue.get("status") == "retrying":
                status_text += (
                    f"\n• **Delivery retry ({reminder_label})**: "
                    f"failure {failure_count}/{max_failures} for {channels}"
                )
            else:
                reason = issue.get("reason", "delivery failed")
                status_text += (
                    f"\n• **Delivery alert ({reminder_label})**: "
                    f"{reason_labels.get(reason, reason)} for {channels}"
                )
        
        await ctx.respond(status_text, ephemeral=True)


@cwl_reminder.register()
class Test(
    lightbulb.SlashCommand,
    name="test",
    description="Send a test CWL reminder"
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.defer(ephemeral=True)
        
        try:
            delivered = await send_cwl_reminder(test_mode=True)
            if delivered:
                await ctx.respond(
                    f"✅ **Test reminder sent!**\n"
                    f"Check <#{TEST_CHANNEL_ID}> to see the message."
                )
            else:
                await ctx.respond("❌ **The test reminder could not be delivered.**")
        except Exception as e:
            await ctx.respond(
                f"❌ **Failed to send test reminder!**\n"
                f"Error: {str(e)}"
            )


@cwl_reminder.register()
class Cancel(
    lightbulb.SlashCommand,
    name="cancel",
    description="Cancel the scheduled CWL reminder"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        # Remove the base job
        if scheduler.get_job(cwl_base_job_id):
            scheduler.remove_job(cwl_base_job_id)

        # Remove all follow-up jobs
        for i in range(1, 6):  # Remove follow-ups 1-5
            followup_job_id = f"{cwl_followup_job_prefix}{i}"
            if scheduler.get_job(followup_job_id):
                scheduler.remove_job(followup_job_id)
        if scheduler.get_job(cwl_initial_retry_job_id):
            scheduler.remove_job(cwl_initial_retry_job_id)

        # Clear all pending reminders from database
        result = await mongo.database.cwl_pending_reminders.delete_many({})
        if result.deleted_count > 0:
            print(f"[CWL Reminder] Cleared {result.deleted_count} pending reminder(s) from database")

        # Update MongoDB
        await mongo.database.cwl_reminder.update_one(
            {"_id": "schedule"},
            {"$set": {"enabled": False}},
            upsert=True
        )
        
        await ctx.respond(
            "✅ **CWL reminder cancelled**\n"
            "The monthly reminder has been disabled.",
            ephemeral=True
        )


@cwl_reminder.register()
class AddFollowup(
    lightbulb.SlashCommand,
    name="add-followup",
    description="Add or update a follow-up reminder"
):
    number = lightbulb.integer(
        "number",
        "Reminder number (1-5)",
        min_value=1,
        max_value=5
    )
    
    delay = lightbulb.integer(
        "delay",
        "Time delay after the previous reminder",
        min_value=1,
        max_value=36  # Max 36 (hours/days depending on unit)
    )
    
    unit = lightbulb.string(
        "unit",
        "Time unit for delay",
        choices=[
            lightbulb.Choice("minutes", "minutes"),
            lightbulb.Choice("hours", "hours"),
            lightbulb.Choice("days", "days")
        ]
    )
    
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        
        # Get current schedule
        schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        
        if not schedule_data or not schedule_data.get("enabled", False):
            await ctx.respond(
                "❌ **No base reminder scheduled!**\n"
                "Use `/cwl-reminder schedule` to set up the initial reminder first."
            )
            return
        
        # Convert delay to minutes based on unit
        delay_minutes = self.delay
        if self.unit == "hours":
            delay_minutes = self.delay * 60
        elif self.unit == "days":
            delay_minutes = self.delay * 60 * 24
        
        # Get or create followups array
        followups = schedule_data.get("followups", [])
        
        # Find existing follow-up with this number or create new
        existing_index = next((i for i, f in enumerate(followups) if f.get("number") == self.number), None)
        
        followup_data = {
            "number": self.number,
            "delay_minutes": delay_minutes,
            "delay_display": f"{self.delay} {self.unit}",
            "enabled": True
        }
        
        if existing_index is not None:
            followups[existing_index] = followup_data
        else:
            followups.append(followup_data)
        
        # Sort by number
        followups.sort(key=lambda x: x.get("number", 0))
        
        # Update MongoDB
        await mongo.database.cwl_reminder.update_one(
            {"_id": "schedule"},
            {"$set": {"followups": followups}}
        )
        
        # Calculate total delay for this reminder
        total_delay = sum(f.get("delay_minutes", 0) for f in followups if f.get("number", 0) <= self.number)
        
        # Format total delay for display
        total_hours = total_delay // 60
        total_days = total_hours // 24
        if total_days > 0:
            total_display = f"{total_days} days, {total_hours % 24} hours"
        elif total_hours > 0:
            total_display = f"{total_hours} hours, {total_delay % 60} minutes"
        else:
            total_display = f"{total_delay} minutes"
        
        # Get next run time for base job
        base_job = scheduler.get_job(cwl_base_job_id)
        next_run_info = ""
        if base_job and base_job.next_run_time:
            next_base_time = pendulum.instance(base_job.next_run_time, tz=DEFAULT_TIMEZONE)
            next_followup_time = next_base_time.add(minutes=total_delay)
            next_run_info = f"\n• **Next run**: {next_followup_time.format('MMM D [at] h:mm A')}"
        
        await ctx.respond(
            f"✅ **Follow-up reminder #{self.number} configured!**\n"
            f"• Delay: {self.delay} {self.unit} after reminder #{self.number - 1}\n"
            f"• Total delay from initial: {total_display}"
            f"{next_run_info}"
        )


@cwl_reminder.register()
class RemoveFollowup(
    lightbulb.SlashCommand,
    name="remove-followup",
    description="Remove a follow-up reminder"
):
    number = lightbulb.integer(
        "number",
        "Reminder number to remove (1-5)",
        min_value=1,
        max_value=5
    )
    
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        
        if not await remove_followup_configuration(self.number, mongo):
            await ctx.respond(f"❌ **No follow-up reminder #{self.number} found!**")
            return

        await ctx.respond(f"✅ **Removed follow-up reminder #{self.number}**")


@cwl_reminder.register()
class List(
    lightbulb.SlashCommand,
    name="list",
    description="List all configured CWL reminders and their times"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        
        # Get schedule data
        schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        
        if not schedule_data or not schedule_data.get("enabled", False):
            await ctx.respond(
                "❌ **No CWL reminders configured!**\n"
                "Use `/cwl-reminder schedule` to set up reminders."
            )
            return
        
        # Base schedule info
        day = schedule_data.get("day", "?")
        hour = schedule_data.get("hour", 0)
        minute = schedule_data.get("minute", 0)

        base_datetime = next_monthly_run(day, hour, minute)

        # Build reminder list
        lines = ["## 📅 CWL Reminder Schedule\n"]

        # Initial reminder with full date
        base_time_with_date = base_datetime.format("MMM D [at] h:mm A")
        lines.append(f"**Initial Reminder**")
        lines.append(f"• Sends at: {base_time_with_date}")
        lines.append(f"• Main Channel: <#{CWL_CHANNEL_ID}>")
        lines.append(f"• Lazy Channel: <#{LAZY_CWL_CHANNEL_ID}>")
        lines.append(f"• Message: CWL Time announcement\n")
        
        # Follow-up reminders
        followups = schedule_data.get("followups", [])
        if followups:
            lines.append("**Follow-up Reminders**")

            # Calculate cumulative delays
            current_delay = 0
            
            for followup in sorted(followups, key=lambda x: x.get("number", 0)):
                if followup.get("enabled", True):
                    number = followup.get("number")
                    delay = followup.get("delay_minutes", 0)
                    delay_display = followup.get("delay_display", f"{delay} minutes")
                    current_delay += delay
                    
                    # Calculate actual time with date
                    followup_time = base_datetime.add(minutes=current_delay)
                    time_str = followup_time.format("MMM D [at] h:mm A")
                    
                    # Format total delay
                    total_hours = current_delay // 60
                    total_days = total_hours // 24
                    if total_days > 0:
                        total_display = f"{total_days}d {total_hours % 24}h"
                    elif total_hours > 0:
                        total_display = f"{total_hours}h {current_delay % 60}m"
                    else:
                        total_display = f"{current_delay}m"
                    
                    lines.append(f"\n**Reminder #{number}**")
                    lines.append(f"• {delay_display} after previous ({total_display} total)")
                    lines.append(f"• Sends at: {time_str}")
                    lines.append(f"• Message: Sign-up Reminder #{number}")
        
        lines.append(f"\n*All times in {DEFAULT_TIMEZONE}*")
        
        await ctx.respond("\n".join(lines))


@cwl_reminder.register()
class TestAll(
    lightbulb.SlashCommand,
    name="test-all",
    description="Test all configured reminders in sequence (5 second delays)"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        
        # Get schedule data
        schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        
        if not schedule_data:
            await ctx.respond("❌ **No reminders configured!**")
            return
        
        followups = schedule_data.get("followups", [])
        total_reminders = 1 + len([f for f in followups if f.get("enabled", True)])
        
        await ctx.respond(
            f"🚀 **Testing {total_reminders} reminder(s)...**\n"
            f"Each reminder will be sent with a 5-second delay.\n"
            f"Check <#{TEST_CHANNEL_ID}> to see the messages."
        )

        # Send initial reminder
        await send_cwl_reminder(0, test_mode=True)
        await asyncio.sleep(5)

        # Send follow-ups
        for followup in sorted(followups, key=lambda x: x.get("number", 0)):
            if followup.get("enabled", True):
                number = followup.get("number")
                await send_cwl_reminder(number, test_mode=True)
                await asyncio.sleep(5)


@cwl_reminder.register()
class SendNow(
    lightbulb.SlashCommand,
    name="send-now",
    description="Send all reminders immediately with proper delays"
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)
        
        # Get schedule data
        schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        
        if not schedule_data:
            await ctx.respond("❌ **No reminders configured!**")
            return
        
        followups = schedule_data.get("followups", [])
        
        # A successful initial delivery is the single owner that schedules
        # configured follow-ups. Do not schedule them a second time here.
        delivered = await send_cwl_reminder(0)
        scheduled_count = len([
            followup
            for followup in followups
            if followup.get("enabled", True)
            and followup.get("number")
            and followup.get("delay_minutes", 0) > 0
        ])

        if not delivered:
            await ctx.respond(
                f"⚠️ **Initial reminder was not fully delivered.**\n"
                f"A retry is scheduled in {DELIVERY_RETRY_MINUTES} minutes. "
                "Follow-ups will be scheduled after delivery succeeds."
            )
            return
        
        await ctx.respond(
            f"✅ **Initial reminder sent!**\n"
            f"{scheduled_count} follow-up(s) scheduled with their configured delays.\n"
            f"Check <#{CWL_CHANNEL_ID}> and <#{LAZY_CWL_CHANNEL_ID}> for the messages."
        )


# Register the group with the loader
loader.command(cwl_reminder)
