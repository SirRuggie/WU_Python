import asyncio
import uuid
import logging
import re
import lightbulb
import hikari
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger
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
from utils import cwl_campaign, cwl_web_bridge
from utils import cwl_campaign_catchup as catchup_policy
from utils.startup_reconciler import StartupReconciler
from utils.constants import WU_GOLD

loader = lightbulb.Loader()
_campaign_catchup_active: set[str] = set()
# Tokens describe every still-live local send, across in-process restarts.
# Do not clear this on lifecycle events: an old POST may still complete.
_campaign_send_activity: dict[tuple, set[object]] = {}

# Configuration
CWL_CHANNEL_ID = 1072714594625257502
LAZY_CWL_CHANNEL_ID = (
    865726525990633472  # Same for testing, change to actual channel later
)
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
# Proof belongs to this bot process and is recorded only after a complete load.
_campaign_load_targets: dict[int, set[str]] = {}
_campaign_loaded_generations: dict[tuple[int, str], str] = {}
_campaign_runtime_id = uuid.uuid4().hex
_campaign_load_scan_complete = False
_campaign_sync_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _loaded_campaign_generations(guild_id: int) -> dict[str, str] | None:
    targets = _campaign_load_targets.get(int(guild_id))
    if targets is None:
        return {} if _campaign_load_scan_complete else None
    if any(
        (int(guild_id), cycle) not in _campaign_loaded_generations for cycle in targets
    ):
        return None
    return {
        cycle: _campaign_loaded_generations[(int(guild_id), cycle)] for cycle in targets
    }


cwl_base_job_id = "cwl_monthly_reminder"
cwl_followup_job_prefix = "cwl_followup_"
cwl_initial_retry_job_id = "cwl_initial_retry"
CAMPAIGN_JOB_PREFIX = "cwl_campaign:"
CAMPAIGN_ROLLOVER_JOB_ID = "cwl_campaign_rollover"
WEB_ROSTER_BRIDGE_JOB_ID = "cwl_web_roster_bridge"
WEB_MANAGEMENT_FAST_JOB_ID = "manage_web_fast_poll"
# Kept only for importing historic timing and sent markers. Production
# delivery and command control belong exclusively to /manage section:CWL.
LEGACY_RUNTIME_DISABLED = True
CAMPAIGN_CLAIM_MINUTES = 15
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
    close_date = last_day_of_month.subtract(days=2).replace(
        hour=17, minute=0, second=0
    )

    # If we're already past the close date this month, get next month's close date
    if now > close_date:
        next_month = now.add(months=1)
        last_day_of_next_month = next_month.end_of("month")
        close_date = last_day_of_next_month.subtract(days=2).replace(
            hour=17, minute=0, second=0
        )

    # Convert to Unix timestamp for Discord
    # Discord will display this in the user's local timezone
    return f"<t:{int(close_date.timestamp())}:D>"


def create_cwl_reminder_message(
    reminder_number: int = 0, channel_type: str = "main"
) -> list[Container]:
    """Create a CWL reminder message based on the reminder number and channel type"""

    # Components based on channel type
    if channel_type == "lazy":
        # Only Lazy CWL button for lazy channel
        button_components = [
            LinkButton(url=LAZY_FORM_URL, label="Lazy CWL", emoji="😴"),
        ]
    else:
        # Both buttons for main channel
        button_components = [
            LinkButton(url=MAIN_FORM_URL, label="Main Clan", emoji="📋"),
            LinkButton(url=LAZY_FORM_URL, label="Lazy CWL", emoji="😴"),
        ]

    if reminder_number == 0:
        # Initial reminder
        if channel_type == "lazy":
            # Lazy channel version
            components = [
                Container(
                    accent_color=WU_GOLD,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(
                            content="## <:CWL:1399013745598009375> CWL Time <:CWL:1399013745598009375>"
                        ),
                        Separator(divider=True),
                        Text(
                            content=(
                                "The below form is required to participate within the Warriors United Lazy CWL Operation.\n\n"
                                "The form take less then a couple minutes to complete and the sooner you sign up "
                                "the better it is on us making Rosters.\n\n"
                                'Remember...if you are in one of our FWA Clans it\'s "LAZY WAY OR NO WAY!!" '
                                "Outside involvement is not permitted."
                            )
                        ),
                        Text(
                            content=f"\nDirect all questions and concerns in <#{LAZY_DISCUSSION_CHANNEL}> <:warriorcat:947992348971905035>"
                        ),
                        Media(
                            items=[MediaItem(media="assets/Gold_Footer.png")]
                        ),
                        ActionRow(components=button_components),
                    ],
                )
            ]
        else:
            # Main channel version
            components = [
                Container(
                    accent_color=WU_GOLD,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(
                            content="## <:CWL:1399013745598009375> CWL Time <:CWL:1399013745598009375>"
                        ),
                        Separator(divider=True),
                        Text(
                            content=(
                                "Below are the two signup forms required to participate here in Warriors United CWL. "
                                "LazyCWL is an option for all within the Family but if your in one of our FWA Clans "
                                'it\'s "Lazy Way or No Way".'
                            )
                        ),
                        Text(
                            content=(
                                "\nThe forms take less then a couple minutes to complete and the sooner you sign up "
                                "the better it is on us making Rosters.\n\n"
                                "Direct all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"
                            )
                        ),
                        Media(
                            items=[MediaItem(media="assets/Gold_Footer.png")]
                        ),
                        ActionRow(components=button_components),
                    ],
                )
            ]
    else:
        # Follow-up reminders
        close_timestamp = get_signup_close_timestamp(29)  # 29th of the month

        # Choose media based on reminder number
        media_item = None
        if reminder_number == 1:
            media_item = MediaItem(
                media="https://c.tenor.com/6b2bCHLqrUkAAAAd/tenor.gif"
            )
        elif reminder_number == 2:
            media_item = MediaItem(
                media="https://media.tenor.com/0XVm8XNzxFUAAAAj/its-not-too-late-to-get-involved-engage.gif"
            )
        elif reminder_number == 3:
            media_item = MediaItem(
                media="https://c.tenor.com/t-scOJYZGPEAAAAC/tenor.gif"
            )
        elif reminder_number == 4:
            media_item = MediaItem(
                media="https://c.tenor.com/fc51xvY2Tq4AAAAd/tenor.gif"
            )
        elif reminder_number == 5:
            media_item = MediaItem(
                media="https://c.tenor.com/egVC6wj7VV8AAAAC/tenor.gif"
            )
        else:
            media_item = MediaItem(media="assets/Gold_Footer.png")

        if channel_type == "lazy":
            # Lazy channel version of follow-ups
            components = [
                Container(
                    accent_color=WU_GOLD,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(
                            content=f"## <:CWL:1399013745598009375> Sign-up Reminder #{reminder_number} <:CWL:1399013745598009375>"
                        ),
                        Separator(divider=True),
                        Text(
                            content=(
                                "**If you already signed up, we got ya down. No need to sign up again. But everyone else...**\n\n"
                                "The below form is required to participate within the Warriors United Lazy CWL Operation.\n\n"
                                "The form take less then a couple minutes to complete and the sooner you sign up "
                                "the better it is on us making Rosters.\n\n"
                                'Remember...if you are in one of our FWA Clans it\'s "LAZY WAY OR NO WAY!!" '
                                "Outside involvement is not permitted."
                            )
                        ),
                        Text(
                            content=f"\n# **Signups close {close_timestamp}**"
                        ),
                        Text(
                            content=f"\nDirect all questions and concerns in <#{LAZY_DISCUSSION_CHANNEL}> <:warriorcat:947992348971905035>"
                        ),
                        Media(items=[media_item]),
                        ActionRow(components=button_components),
                    ],
                )
            ]
        else:
            # Main channel version of follow-ups
            components = [
                Container(
                    accent_color=WU_GOLD,
                    components=[
                        Text(content=f"<@&{ROLE_TO_PING}>"),
                        Separator(divider=True),
                        Text(
                            content=f"## <:CWL:1399013745598009375> Sign-up Reminder #{reminder_number} <:CWL:1399013745598009375>"
                        ),
                        Separator(divider=True),
                        Text(
                            content=(
                                "**If you already signed up, we got ya down. No need to sign up again. But everyone else...**\n\n"
                                "Below are the two signup forms required to participate here in Warriors United CWL. "
                                "LazyCWL is an option for all within the Family but if your in one of our FWA Clans "
                                'it\'s "Lazy Way or No Way".'
                            )
                        ),
                        Text(
                            content=(
                                "\nThe forms take less then a couple minutes to complete and the sooner you sign up "
                                "the better it is on us making Rosters."
                            )
                        ),
                        Text(
                            content=f"\n# **Signups close {close_timestamp}**"
                        ),
                        Text(
                            content="\nDirect all questions and concerns to <#801950200133976124> <:warriorcat:947992348971905035>"
                        ),
                        Media(items=[media_item]),
                        ActionRow(components=button_components),
                    ],
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
            year,
            month,
            day,
            hour,
            minute,
            tz=DEFAULT_TIMEZONE,
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
    current = (
        pendulum.instance(now, tz=DEFAULT_TIMEZONE)
        if now
        else pendulum.now(DEFAULT_TIMEZONE)
    )
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


def _campaign_job_id(
    guild_id: int, cycle: str, message_id: str, variant: str
) -> str:
    return (
        f"{CAMPAIGN_JOB_PREFIX}{int(guild_id)}:{cycle}:{message_id}:{variant}"
    )


def _campaign_generation(loaded: dict) -> str:
    return cwl_web_bridge.campaign_generation(loaded)


def _add_campaign_job(
    job_id: str,
    run_time: datetime,
    guild_id: int,
    cycle: str,
    message_id: str,
    variants: list[str],
    generation: str,
    *,
    catchup_due_at: str | None = None,
    staff_request_id: str | None = None,
) -> None:
    kwargs = {}
    if catchup_due_at:
        kwargs["catchup_due_at"] = catchup_due_at
    if staff_request_id:
        kwargs["staff_request_id"] = staff_request_id
    options = {"kwargs": kwargs} if kwargs else {}
    scheduler.add_job(
        send_campaign_message,
        trigger=DateTrigger(run_date=run_time, timezone=DEFAULT_TIMEZONE),
        id=job_id,
        args=[guild_id, cycle, message_id, variants, generation],
        replace_existing=True,
        **options,
        **JOB_OPTIONS,
    )


async def _persist_campaign_job(
    job_id: str,
    run_time: datetime,
    guild_id: int,
    cycle: str,
    message_id: str,
    variants: list[str],
    generation: str,
    *,
    failure_count: int = 0,
    job_kind: str = "scheduled",
    staff_request_id: str | None = None,
) -> None:
    now = pendulum.now("UTC").isoformat()
    staff_fields = {"staff_request_id": staff_request_id} if staff_request_id else {}
    obsolete = {"catchup": ""}
    if not staff_request_id:
        obsolete["staff_request_id"] = ""
    await mongo_client.cwl_pending_reminders.update_one(
        {"_id": job_id},
        {
            "$set": {
                "kind": "campaign",
                "guild_id": int(guild_id),
                "cycle": cycle,
                "message_id": message_id,
                "variants": list(variants),
                "generation": generation,
                "run_time": run_time.isoformat(),
                "job_id": job_id,
                "failure_count": int(failure_count),
                "job_kind": job_kind,
                "status": "scheduled",
                "updated_at": now,
                **staff_fields,
            },
            "$setOnInsert": {"created_at": now},
            "$unset": obsolete,
        },
        upsert=True,
    )


def _remove_catchup_scheduler_job(row):
    job = scheduler.get_job(row["_id"])
    if not job or list(getattr(job, "args", ()))[-1:] != [row.get("generation")]:
        return
    original = (row.get("catchup") or {}).get("original_due_at")
    if original:
        if (getattr(job, "kwargs", None) or {}).get("catchup_due_at") != original:
            return
    elif getattr(getattr(job, "trigger", None), "run_date", None) != pendulum.parse(row["run_time"]):
        return
    scheduler.remove_job(row["_id"])


async def _finish_catchup_decision(row, due, status, reason):
    variant = row["variants"][0]
    oid = cwl_campaign.occurrence_id(row["cycle"], row["message_id"], variant)
    entry = {
        "occurrence_id": oid,
        "message_key": row["message_id"],
        "variant": variant,
        "status": status,
        "reason": reason,
        "revision": row.get("generation"),
        **catchup_policy.late_receipt(due, pendulum.now(DEFAULT_TIMEZONE)),
    }
    recorded = await cwl_campaign.record_catchup_decision(
        mongo_client, int(row["guild_id"]), row["cycle"], entry,
    )
    if not recorded:
        state = await cwl_campaign.catchup_state(mongo_client, int(row["guild_id"]), row["cycle"])
        if oid in state["uncertain"] and oid not in state["reported"] and oid not in state["sent"]:
            status, reason = "uncertain", "Not sure it sent. Check Discord."
            entry.update(status=status, reason=reason)
            recorded = await cwl_campaign.record_catchup_decision(
                mongo_client, int(row["guild_id"]), row["cycle"], entry
            )
        elif (oid not in state["reported"]
              and cwl_campaign.catchup_report_key(entry) not in state["reported"]
              and oid not in state["sent"]):
            print("[CWL Reminder] ALERT campaign_catchup_decision_unavailable action=review delivery history")
            return
    if recorded:
        print(
            f"[CWL Reminder] ALERT campaign_catchup cycle={row['cycle']} "
            f"message={row['message_id']} variant={variant} status={status} reason={reason}"
        )
    retired_retry = type(row.get("failure_count")) is int and row["failure_count"] > 0
    await cwl_campaign.delete_catchup_job(mongo_client, row, retired_retry=retired_retry)
    _remove_catchup_scheduler_job(row)


def _campaign_retry_snapshot(row):
    return type(row.get("failure_count")) is int and row["failure_count"] > 0


async def _restore_scheduled_catchups(
    rows, now, *, tagged_only=False, loaded=None, stale_generation=None
):
    """Decide persisted jobs before restore/sync can replace their original due time."""
    groups = {}
    handled = set()
    kept = {}
    for row in rows:
        try:
            stale_retry = (
                stale_generation is not None
                and row.get("kind") == "campaign"
                and row.get("job_kind", "scheduled") in {"scheduled", "retry"}
                and row.get("message_id") != "roster"
                and row.get("status", "scheduled") == "scheduled"
                and row.get("generation") != stale_generation
                and type(row.get("failure_count")) is int
                and row["failure_count"] > 0
            )
            if not stale_retry and not catchup_policy.scheduled_candidate(row):
                continue
            combined_legacy = (
                row.get("job_kind", "scheduled") == "scheduled"
                and isinstance(row.get("variants"), list)
                and len(row["variants"]) > 1
            )
            stale_ordinary = (
                stale_generation is not None
                and row.get("job_kind", "scheduled") == "scheduled"
                and row.get("generation") != stale_generation
                and not combined_legacy
            )
            if (
                tagged_only
                and row.get("job_kind") != catchup_policy.CATCHUP_JOB_KIND
                and not combined_legacy
                and not stale_ordinary
                and not stale_retry
            ):
                continue
            due = catchup_policy.original_due(row)
            if due > now and not stale_retry:
                continue
            variants = row.get("variants")
            if isinstance(variants, list) and len(variants) > 1:
                recorded = await cwl_campaign.record_legacy_catchup_skip(
                    mongo_client, row, due.isoformat()
                )
                handled.add(row["_id"])
                _remove_catchup_scheduler_job(row)
                if recorded:
                    print("[CWL Reminder] ALERT campaign_catchup_legacy action=review delivery history")
                continue
            gid, cycle, message_id = int(row["guild_id"]), row["cycle"], row["message_id"]
            if (
                not isinstance(variants, list) or len(variants) != 1
                or variants[0] not in cwl_campaign.AUDIENCES
                or not isinstance(row["guild_id"], int) or isinstance(row["guild_id"], bool) or gid <= 0
                or not re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", str(cycle))
                or not re.fullmatch(r"[A-Za-z0-9:_-]{1,64}", str(message_id))
                or row.get("status", "scheduled") != "scheduled"
                or row["_id"] != _campaign_job_id(gid, cycle, message_id, variants[0])
            ):
                raise ValueError("Invalid persisted catch-up scope")
            handled.add(row["_id"])
            groups.setdefault((gid, cycle), []).append((row, due, variants[0]))
        except (KeyError, TypeError, ValueError):
            if row.get("kind") == "campaign" and row.get("job_kind", "scheduled") in {"scheduled", catchup_policy.CATCHUP_JOB_KIND}:
                handled.add(row.get("_id"))
                print("[CWL Reminder] ALERT campaign_catchup_invalid action=review persisted schedule")
    for (gid, cycle), candidates in groups.items():
        if loaded and loaded["guild_id"] == gid and loaded["cycle"] == cycle:
            current = loaded
        else:
            current = await cwl_campaign.load_campaign(mongo_client, gid, cycle)
        generation = _campaign_generation(current)
        state = await cwl_campaign.catchup_state(mongo_client, gid, cycle)
        eligible = {}
        for row, due, variant in candidates:
            # load_campaign/catchup_state yielded: a manual or scheduled owner
            # may have entered meanwhile. Do not report against its live POST.
            if row["_id"] in _campaign_catchup_active or _campaign_row_active(row):
                kept[row["_id"]] = row
                continue
            oid = cwl_campaign.occurrence_id(cycle, row["message_id"], variant)
            if oid in catchup_policy.handled_occurrences(current, state, due=due):
                await cwl_campaign.delete_catchup_job(
                    mongo_client, row, retired_retry=_campaign_retry_snapshot(row)
                )
                _remove_catchup_scheduler_job(row)
                continue
            claim_key = oid.replace(".", "_")
            has_claim = claim_key in state["claims"]
            claim = state["claims"].get(claim_key)
            if (
                isinstance(claim, dict) and claim.get("at")
                and oid not in state["uncertain"]
                and row.get("job_kind") == catchup_policy.CATCHUP_JOB_KIND
                and (row.get("catchup") or {}).get("protocol") == 1
                and claim.get("generation") == row.get("generation")
            ):
                if not await cwl_campaign.release_catchup_preflight_claim(
                    mongo_client, gid, cycle, oid, claim
                ):
                    continue
                claim = None
                has_claim = False
            if oid in state["uncertain"] or has_claim:
                await _finish_catchup_decision(row, due, "uncertain", "Not sure it sent. Check Discord.")
                continue
            reason = catchup_policy.exclusion_reason(current, row, variant, generation, now)
            if reason:
                await _finish_catchup_decision(row, due, "skipped", reason)
                continue
            eligible.setdefault(variant, []).append((row, due))
        for variant, choices in eligible.items():
            choices.sort(
                key=lambda item: (item[1], item[0]["message_id"], item[0]["_id"]),
                reverse=True,
            )
            newest, due = choices[0]
            for older, original in choices[1:]:
                await _finish_catchup_decision(older, original, "skipped", "Skipped: newer reminder kept")
            if _sequence_spacing_blocked(current, newest["message_id"], variant, now):
                await _finish_catchup_decision(newest, due, "skipped", "Skipped: too close to another send")
                continue
            if newest.get("job_kind") != catchup_policy.CATCHUP_JOB_KIND or not scheduler.get_job(newest["_id"]):
                if not await cwl_campaign.prepare_catchup_job(mongo_client, newest, due, now):
                    continue
                newest = {
                    **newest,
                    "job_kind": catchup_policy.CATCHUP_JOB_KIND,
                    "status": "scheduled",
                    "run_time": now.isoformat(),
                    "catchup": {"protocol": 1, "original_due_at": due.isoformat()},
                }
                _add_campaign_job(
                    newest["_id"], now, gid, cycle, newest["message_id"],
                    [variant], generation, catchup_due_at=due.isoformat(),
                )
            kept[newest["_id"]] = newest
    return handled, kept


async def _release_campaign_claim(
    guild_id: int, cycle: str, occurrence: str
) -> None:
    claim_key = occurrence.replace(".", "_")
    await mongo_client.bot_config.update_one(
        {"_id": cwl_campaign.cycle_id(guild_id, cycle)},
        {"$unset": {f"delivery_claims.{claim_key}": ""}},
    )


async def _claim_campaign_occurrence(
    guild_id: int,
    cycle: str,
    occurrence: str,
    generation: str,
    *,
    return_claim: bool = False,
    blocked_detail: dict | None = None,
) -> bool | dict:
    """Claim one delivery; optionally return its identity for guarded release."""
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    if occurrence in loaded.get("uncertain_occurrences", []):
        if blocked_detail is not None:
            blocked_detail["busy"] = True
        return False
    if occurrence in loaded.get("skipped", []) or occurrence in set(
        loaded.get("sent_occurrences", [])
    ) | {
        item.get("occurrence_id")
        for item in loaded.get("deliveries", [])
        if item.get("status") == "sent"
    }:
        return False
    claim_key = occurrence.replace(".", "_")
    now = pendulum.now("UTC")
    cycle_document = (
        await mongo_client.bot_config.find_one(
            {"_id": cwl_campaign.cycle_id(guild_id, cycle)}
        )
        or {}
    )
    existing = (cycle_document.get("delivery_claims") or {}).get(claim_key)
    if existing:
        try:
            claimed_at = pendulum.parse(existing["at"])
            if claimed_at > now.subtract(minutes=CAMPAIGN_CLAIM_MINUTES):
                if blocked_detail is not None:
                    blocked_detail["busy"] = True
                return False
        except (KeyError, TypeError, ValueError):
            pass
    result = await mongo_client.bot_config.update_one(
        {
            "_id": cwl_campaign.cycle_id(guild_id, cycle),
            f"delivery_claims.{claim_key}.at": (
                existing.get("at")
                if isinstance(existing, dict)
                else {"$exists": False}
            ),
            "sent_occurrences": {"$ne": occurrence},
            "uncertain_occurrences": {"$ne": occurrence},
        },
        {
            "$set": {
                f"delivery_claims.{claim_key}": {
                    "at": now.isoformat(),
                    "generation": generation,
                }
            },
            "$setOnInsert": {
                "kind": "cwl_campaign_cycle",
                "guild_id": int(guild_id),
                "cycle": cycle,
                "revision": 0,
            },
        },
        upsert=not bool(cycle_document),
    )
    claimed = bool(
        getattr(result, "matched_count", 0)
        or getattr(result, "upserted_id", None) is not None
        or getattr(result, "modified_count", 0)
    )
    if claimed and return_claim:
        return {"at": now.isoformat(), "generation": generation}
    if not claimed and blocked_detail is not None:
        blocked_detail["busy"] = True
    return claimed


async def _campaign_channel_belongs_to_guild(
    channel_id: int, guild_id: int
) -> bool:
    cache = getattr(bot_instance, "cache", None)
    channel = (
        cache.get_guild_channel(channel_id)
        if cache and hasattr(cache, "get_guild_channel")
        else None
    )
    can_fetch = hasattr(bot_instance.rest, "fetch_channel")
    if channel is None and can_fetch:
        channel = await bot_instance.rest.fetch_channel(channel_id)
    if channel is None:
        return False
    channel_guild = getattr(channel, "guild_id", None)
    return channel_guild is not None and int(channel_guild) == int(guild_id)


async def _schedule_campaign_retry(
    guild_id: int,
    cycle: str,
    message_id: str,
    variants: list[str],
    generation: str,
    errors: list[tuple[str, Exception]],
) -> None:
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    for variant, exc in errors:
        job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
        pending = (
            await mongo_client.cwl_pending_reminders.find_one({"_id": job_id})
            or {}
        )
        failure_count = max(0, int(pending.get("failure_count", 0))) + 1
        permanent = _is_permanent_delivery_error(exc)
        if permanent or failure_count >= MAX_DELIVERY_FAILURES:
            await cwl_campaign.record_delivery(
                mongo_client,
                guild_id,
                cycle,
                {
                    "occurrence_id": cwl_campaign.occurrence_id(
                        cycle, message_id, variant
                    ),
                    "message_id_key": message_id,
                    "variant": variant,
                    "status": "failed",
                    "error": _delivery_error_detail(exc),
                    "error_type": type(exc).__name__,
                    "failure_count": failure_count,
                    "revision": generation,
                },
            )
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": job_id}
            )
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            continue
        run_time = pendulum.now(DEFAULT_TIMEZONE).add(
            minutes=DELIVERY_RETRY_DELAYS_MINUTES[failure_count - 1]
        )
        if _sequence_delivery_blocked(loaded, message_id, run_time):
            await cwl_campaign.record_delivery(
                mongo_client,
                guild_id,
                cycle,
                {
                    "occurrence_id": cwl_campaign.occurrence_id(
                        cycle, message_id, variant
                    ),
                    "message_key": message_id,
                    "variant": variant,
                    "status": "skipped",
                    "reason": "The retry would run after signup closes or outside the reminder sequence.",
                },
            )
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": job_id}
            )
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            continue
        await _persist_campaign_job(
            job_id,
            run_time,
            guild_id,
            cycle,
            message_id,
            [variant],
            generation,
            failure_count=failure_count,
            job_kind="retry",
        )
        _add_campaign_job(
            job_id,
            run_time,
            guild_id,
            cycle,
            message_id,
            [variant],
            generation,
        )


def _is_sequence_message(loaded, message_id):
    return bool(
        loaded["campaign"].get("reminder_sequence", {}).get("enabled")
        and re.fullmatch(r"reminder:(?:[1-9]|10)", message_id)
    )


def _sequence_delivery_blocked(loaded, message_id, now):
    if not _is_sequence_message(loaded, message_id):
        return False
    return now >= pendulum.parse(loaded["deadline"]) or not any(
        row["message_id"] == message_id and row.get("run_at")
        for row in loaded.get("schedule", ())
    )


def _sequence_spacing_blocked(loaded, message_id, variant, now):
    if not _is_sequence_message(loaded, message_id):
        return False
    # Scheduled HTTP sends naturally drift by a few seconds. A one-minute
    # tolerance avoids dropping an on-time reminder at the exact gap boundary.
    gap = max(
        0,
        int(loaded["campaign"]["reminder_sequence"]["min_gap_hours"]) * 3600
        - 60,
    )
    times = {
        row["message_id"]: pendulum.parse(row["run_at"])
        for row in loaded.get("schedule", ())
        if row.get("run_at")
        and row.get("variant") == variant
        and _is_sequence_message(loaded, row["message_id"])
    }
    current = times.get(message_id)
    # An overdue job must not crowd a newer reminder, including after restart.
    if current and any(
        when > current and (when - now).total_seconds() < gap
        for when in times.values()
    ):
        return True
    for row in loaded.get("deliveries", ()):
        key = row.get("message_key") or row.get("message_id_key")
        if not key and row.get("occurrence_id"):
            key = str(row["occurrence_id"]).split("|")[1]
        if (
            row.get("status") == "sent"
            and row.get("variant") == variant
            and key != message_id
            and (key == "signup" or _is_sequence_message(loaded, str(key)))
        ):
            if (
                row.get("at")
                and (now - pendulum.parse(row["at"])).total_seconds() < gap
            ):
                return True
    return False


async def _send_catchup_message(guild_id, cycle, message_id, variants, generation, due_at):
    if not variants or len(variants) != 1:
        return False
    job_id = _campaign_job_id(guild_id, cycle, message_id, variants[0])
    if job_id in _campaign_catchup_active:
        return False
    _campaign_catchup_active.add(job_id)
    try:
        return await _deliver_catchup_message(guild_id, cycle, message_id, variants, generation, due_at)
    finally:
        _campaign_catchup_active.discard(job_id)


async def _deliver_catchup_message(guild_id, cycle, message_id, variants, generation, due_at):
    if not variants or len(variants) != 1 or variants[0] not in cwl_campaign.AUDIENCES or message_id == "roster":
        return False
    variant = variants[0]
    job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
    row = await cwl_campaign.load_catchup_job(
        mongo_client, guild_id, cycle, message_id, variant, generation, due_at
    )
    if row is None:
        return False
    due = catchup_policy.original_due(row)
    oid = cwl_campaign.occurrence_id(cycle, message_id, variant)
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    state = await cwl_campaign.catchup_state(mongo_client, guild_id, cycle)
    if oid in catchup_policy.handled_occurrences(loaded, state, due=due):
        await cwl_campaign.delete_catchup_job(mongo_client, row)
        _remove_catchup_scheduler_job(row)
        return False
    reason = catchup_policy.exclusion_reason(loaded, row, variant, _campaign_generation(loaded), pendulum.now(DEFAULT_TIMEZONE))
    if reason is None and _sequence_spacing_blocked(loaded, message_id, variant, pendulum.now(DEFAULT_TIMEZONE)):
        reason = "Skipped: too close to another send"
    if reason:
        await _finish_catchup_decision(row, due, "skipped", reason)
        return False
    claim = await _claim_campaign_occurrence(
        guild_id, cycle, oid, generation, return_claim=True
    )
    if not claim:
        return False
    attempted = False
    try:
        item = loaded["campaign"]["messages"][message_id]["variants"][variant]
        channel_id = int(item["destination_channel_id"])
        if not await _campaign_channel_belongs_to_guild(channel_id, guild_id):
            raise ValueError("The configured channel is outside this Discord server")
        components = await cwl_campaign.render_message(
            {"campaign": loaded["campaign"], "deadline": loaded["deadline"]},
            message_id, variant, preview=False,
        )
        # Network preparation can await. Recheck the original generation and
        # all policy immediately before reserving the POST boundary.
        fresh = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
        reason = catchup_policy.exclusion_reason(fresh, row, variant, _campaign_generation(fresh), pendulum.now(DEFAULT_TIMEZONE))
        if reason is None and _sequence_spacing_blocked(fresh, message_id, variant, pendulum.now(DEFAULT_TIMEZONE)):
            reason = "Skipped: too close to another send"
        if reason:
            await cwl_campaign.release_catchup_preflight_claim(
                mongo_client, guild_id, cycle, oid, claim
            )
            await _finish_catchup_decision(row, due, "skipped", reason)
            return False
        if not await cwl_campaign.begin_catchup_attempt(
            mongo_client, guild_id=guild_id, cycle=cycle, occurrence=oid,
            generation=generation, job_id=job_id, original_due_at=due_at,
        ):
            await cwl_campaign.release_catchup_preflight_claim(
                mongo_client, guild_id, cycle, oid, claim
            )
            return False
        attempted = True
        result = await bot_instance.rest.create_message(
            channel=channel_id, components=components,
            role_mentions=item.get("role_ids", []), user_mentions=False,
            mentions_everyone=False,
            nonce=cwl_campaign.roster_delivery_nonce(guild_id, oid, loaded.get("deliveries", [])),
        )
    except Exception as exc:
        if attempted:
            await _finish_catchup_decision(row, due, "uncertain", "Not sure it sent. Check Discord.")
        else:
            await cwl_campaign.release_catchup_preflight_claim(
                mongo_client, guild_id, cycle, oid, claim
            )
            await _finish_catchup_decision(row, due, "failed", "Not sent: delivery unavailable")
        return False
    message_id_value = getattr(result, "id", None)
    if not isinstance(message_id_value, int) or isinstance(message_id_value, bool) or message_id_value <= 0:
        await _finish_catchup_decision(row, due, "uncertain", "Not sure it sent. Check Discord.")
        return False
    receipt = {
        "occurrence_id": oid, "message_key": message_id, "variant": variant,
        "at": pendulum.now("UTC").isoformat(),
        "status": "sent", "channel_id": channel_id,
        "message_id": int(message_id_value) if message_id_value is not None else None,
        "message_url": f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id_value}" if message_id_value is not None else None,
        "revision": generation,
        **catchup_policy.late_receipt(due, pendulum.now(DEFAULT_TIMEZONE)),
    }
    try:
        await cwl_campaign.record_catchup_delivery(mongo_client, guild_id, cycle, receipt)
    except Exception as exc:
        try:
            await cwl_campaign.persist_catchup_receipt(mongo_client, row, receipt, type(exc).__name__)
        except Exception:
            print("[CWL Reminder] ALERT campaign_catchup_receipt_unavailable action=check Discord before retrying")
            await _finish_catchup_decision(
                row, due, "uncertain", "Not sure it sent. Check Discord."
            )
        return True
    await cwl_campaign.finish_catchup_attempt(mongo_client, guild_id, cycle, oid)
    await _release_campaign_claim(guild_id, cycle, oid)
    await cwl_campaign.delete_catchup_job(mongo_client, row)
    _remove_catchup_scheduler_job(row)
    return True


def _register_campaign_activity(guild_id, cycle, message_id, variants):
    registry = _campaign_send_activity
    token = object()
    keys = [(int(guild_id), cycle, message_id, variant)
            for variant in (variants or cwl_campaign.AUDIENCES)]
    for key in keys:
        registry.setdefault(key, set()).add(token)
    return registry, token, keys


def _release_campaign_activity(activity):
    if activity is None:
        return
    registry, token, keys = activity
    for key in keys:
        owners = registry.get(key)
        if owners is not None:
            owners.discard(token)
            if not owners and registry.get(key) is owners:
                registry.pop(key, None)


def _campaign_row_active(row):
    return any(_campaign_send_activity.get((
        int(row["guild_id"]), row["cycle"],
        row["message_id"], variant,
    )) for variant in row.get("variants", ()))


async def send_campaign_message(
    guild_id: int,
    cycle: str,
    message_id: str,
    variants: list[str] | None = None,
    generation: str | None = None,
    *,
    manual: bool = False,
    catchup_due_at: str | None = None,
    staff_request_id: str | None = None,
) -> bool:
    """Track every local owner of shared claims without changing claim policy."""
    activity = _register_campaign_activity(guild_id, cycle, message_id, variants)
    try:
        return await _deliver_campaign_message(
            guild_id, cycle, message_id, variants, generation, manual=manual,
            catchup_due_at=catchup_due_at, staff_request_id=staff_request_id,
            _activity=activity,
        )
    finally:
        _release_campaign_activity(activity)


async def _deliver_campaign_message(
    guild_id: int,
    cycle: str,
    message_id: str,
    variants: list[str] | None = None,
    generation: str | None = None,
    *,
    manual: bool = False,
    catchup_due_at: str | None = None,
    staff_request_id: str | None = None,
    _activity=None,
) -> bool:
    """Deliver one configured message with per-audience retry/idempotency."""
    if not bot_instance or not mongo_client:
        return False
    if catchup_due_at is not None:
        return await _send_catchup_message(guild_id, cycle, message_id, variants, generation, catchup_due_at)
    staff_row = None
    if staff_request_id and message_id != "roster" and variants and len(variants) == 1:
        staff_row = await cwl_campaign.load_queued_staff_job(
            mongo_client, guild_id, cycle, message_id, variants[0], generation,
            staff_request_id,
        )
        if staff_row is None:
            return False
        if staff_row.get("status") == "ledger_pending":
            if cwl_campaign.is_staff_not_sent_receipt(staff_row):
                await cwl_campaign.record_staff_not_sent(mongo_client, staff_row)
            return False
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    current_generation = _campaign_generation(loaded)
    if generation is not None and generation != current_generation:
        # No POST can occur on this path. Release only this invocation token
        # before deciding its old scheduled row; another owner stays visible.
        _release_campaign_activity(_activity)
        # A stale job must never send copy from a superseded campaign.
        await sync_campaign_schedule(guild_id, cycle)
        return False
    campaign = loaded["campaign"]
    message = campaign.get("messages", {}).get(message_id)
    if (
        (campaign.get("paused") and not manual)
        or not message
        or not message.get("enabled", True)
        or _sequence_delivery_blocked(
            loaded, message_id, pendulum.now(DEFAULT_TIMEZONE)
        )
    ):
        for variant in variants or cwl_campaign.AUDIENCES:
            job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": job_id}
            )
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        return False
    selected = variants or list(cwl_campaign.AUDIENCES)
    failures = []
    sent_any = False
    for variant in selected:
        item = message.get("variants", {}).get(variant)
        if not item or not item.get("enabled", True):
            continue
        if _sequence_spacing_blocked(
            loaded, message_id, variant, pendulum.now(DEFAULT_TIMEZONE)
        ):
            await cwl_campaign.record_delivery(
                mongo_client,
                guild_id,
                cycle,
                {
                    "occurrence_id": cwl_campaign.occurrence_id(
                        cycle, message_id, variant
                    ),
                    "message_key": message_id,
                    "variant": variant,
                    "status": "skipped",
                    "reason": "Skipped an overdue reminder to preserve the minimum spacing.",
                },
            )
            continue
        occurrence = cwl_campaign.occurrence_id(cycle, message_id, variant)
        blocked_detail = {}
        claim_options = {"blocked_detail": blocked_detail} if staff_row else {}
        if not await _claim_campaign_occurrence(
            guild_id, cycle, occurrence, current_generation, **claim_options
        ):
            if staff_row and blocked_detail.get("busy"):
                await cwl_campaign.record_staff_not_sent(mongo_client, staff_row)
                job = scheduler.get_job(staff_row["_id"])
                if job and (getattr(job, "kwargs", None) or {}).get("staff_request_id") == staff_request_id:
                    scheduler.remove_job(staff_row["_id"])
                return False
            continue
        channel_id = int(item["destination_channel_id"])
        discord_message_id = None
        try:
            if not await _campaign_channel_belongs_to_guild(
                channel_id, guild_id
            ):
                raise ValueError(
                    "The configured channel is outside this Discord server"
                )
            components = await cwl_campaign.render_message(
                {"campaign": campaign, "deadline": loaded["deadline"]},
                message_id,
                variant,
                preview=False,
            )
            nonce = cwl_campaign.roster_delivery_nonce(
                guild_id,
                occurrence,
                loaded.get("deliveries", []),
            )
            if _sequence_delivery_blocked(
                loaded, message_id, pendulum.now(DEFAULT_TIMEZONE)
            ):
                await _release_campaign_claim(guild_id, cycle, occurrence)
                continue
            if message_id == "roster":
                # Mark an attempted roster POST before entering the network.
                # If Discord's response is lost, neither Manage nor the web
                # worker may blindly create a second announcement.
                await mongo_client.bot_config.update_one(
                    {"_id": cwl_campaign.cycle_id(guild_id, cycle)},
                    {"$addToSet": {"uncertain_occurrences": occurrence}},
                )
            result = await bot_instance.rest.create_message(
                channel=channel_id,
                components=components,
                role_mentions=item.get("role_ids", []),
                user_mentions=False,
                mentions_everyone=False,
                nonce=nonce,
            )
            discord_message_id = getattr(result, "id", None)
            sent_any = True
        except Exception as exc:
            if message_id == "roster" and not _is_permanent_delivery_error(
                exc
            ):
                try:
                    await cwl_campaign.record_delivery(
                        mongo_client,
                        guild_id,
                        cycle,
                        {
                            "occurrence_id": occurrence,
                            "message_key": message_id,
                            "variant": variant,
                            "status": "uncertain",
                            "error": _delivery_error_detail(exc),
                            "error_type": type(exc).__name__,
                            "revision": current_generation,
                        },
                    )
                except Exception:
                    pass
                continue
            if message_id == "roster":
                await mongo_client.bot_config.update_one(
                    {"_id": cwl_campaign.cycle_id(guild_id, cycle)},
                    {"$pull": {"uncertain_occurrences": occurrence}},
                )
            failures.append((variant, exc))
            await _release_campaign_claim(guild_id, cycle, occurrence)
            continue
        try:
            await cwl_campaign.record_delivery(
                mongo_client,
                guild_id,
                cycle,
                {
                    "occurrence_id": occurrence,
                    "message_key": message_id,
                    "variant": variant,
                    "status": "sent",
                    "channel_id": channel_id,
                    "message_id": (
                        int(discord_message_id)
                        if discord_message_id is not None
                        else None
                    ),
                    "message_url": (
                        f"https://discord.com/channels/{guild_id}/{channel_id}/{discord_message_id}"
                        if discord_message_id is not None
                        else None
                    ),
                    "revision": current_generation,
                },
            )
        except Exception as exc:
            # Discord confirmed this post. Never classify an accounting outage
            # as a send failure: startup can write the durable receipt without
            # producing a second ping.
            try:
                await mongo_client.cwl_pending_reminders.update_one(
                    {
                        "_id": _campaign_job_id(
                            guild_id, cycle, message_id, variant
                        )
                    },
                    {
                        "$set": {
                            "status": "ledger_pending",
                            "guild_id": int(guild_id),
                            "cycle": cycle,
                            "message_id": message_id,
                            "variants": [variant],
                            "generation": current_generation,
                            "receipt": {
                                "occurrence_id": occurrence,
                                "message_key": message_id,
                                "variant": variant,
                                "status": "sent",
                                "channel_id": channel_id,
                                "message_id": (
                                    int(discord_message_id)
                                    if discord_message_id is not None
                                    else None
                                ),
                                "message_url": (
                                    f"https://discord.com/channels/{guild_id}/{channel_id}/{discord_message_id}"
                                    if discord_message_id is not None
                                    else None
                                ),
                                "revision": current_generation,
                            },
                            "last_error": _delivery_error_detail(exc),
                            "updated_at": _utc_iso(),
                        }
                    },
                    upsert=True,
                )
            except Exception:
                pass
            continue
        if message_id == "roster":
            await mongo_client.bot_config.update_one(
                {"_id": cwl_campaign.cycle_id(guild_id, cycle)},
                {"$pull": {"uncertain_occurrences": occurrence}},
            )
        await _release_campaign_claim(guild_id, cycle, occurrence)
    if failures and manual:
        for variant, exc in failures:
            await cwl_campaign.record_delivery(
                mongo_client,
                guild_id,
                cycle,
                {
                    "occurrence_id": cwl_campaign.occurrence_id(
                        cycle, message_id, variant
                    ),
                    "message_key": message_id,
                    "variant": variant,
                    "status": "failed",
                    "error": _delivery_error_detail(exc),
                    "error_type": type(exc).__name__,
                },
            )
        return False
    if failures:
        await _schedule_campaign_retry(
            guild_id,
            cycle,
            message_id,
            [variant for variant, _ in failures],
            current_generation,
            failures,
        )
        return False
    for variant in selected:
        job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
        pending = (
            await mongo_client.cwl_pending_reminders.find_one({"_id": job_id})
            or {}
        )
        if pending.get("status") == "ledger_pending":
            continue
        await mongo_client.cwl_pending_reminders.delete_one({"_id": job_id})
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
    return sent_any


async def sync_campaign_schedule(guild_id: int, cycle: str) -> None:
    """Install one complete cycle atomically with respect to concurrent reloads."""
    key = (int(guild_id), cycle)
    lock = _campaign_sync_locks.setdefault(key, asyncio.Lock())
    async with lock:
        await _install_campaign_schedule(guild_id, cycle)


async def _install_campaign_schedule(guild_id: int, cycle: str) -> None:
    """Replace this cycle's jobs from durable config, preserving sent events."""
    runtime_id = _campaign_runtime_id
    proof_key = (int(guild_id), cycle)
    _campaign_load_targets.setdefault(int(guild_id), set()).add(cycle)
    _campaign_loaded_generations.pop(proof_key, None)
    if not scheduler.get_job(CAMPAIGN_ROLLOVER_JOB_ID):
        scheduler.add_job(
            _sync_all_campaigns,
            trigger=CronTrigger(day=1, hour=0, minute=5, timezone=DEFAULT_TIMEZONE),
            id=CAMPAIGN_ROLLOVER_JOB_ID,
            replace_existing=True,
            **JOB_OPTIONS,
        )
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    generation = _campaign_generation(loaded)
    # Activating the dashboard hands ownership to the guild-scoped scheduler.
    # Retire the globally keyed legacy jobs/state so both systems cannot send.
    legacy = await mongo_client.cwl_reminder.find_one({"_id": "schedule"}) or {}
    if int(guild_id) == cwl_campaign.LEGACY_WU_GUILD_ID and legacy.get("enabled"):
        existing_defaults = await mongo_client.bot_config.find_one(
            {"_id": cwl_campaign.defaults_id(guild_id)}
        )
        if not existing_defaults:
            await mongo_client.bot_config.update_one(
                {"_id": cwl_campaign.defaults_id(guild_id)},
                {
                    "$setOnInsert": {
                        "kind": "cwl_campaign_defaults",
                        "guild_id": int(guild_id),
                        "campaign": cwl_campaign.campaign_from_legacy(legacy),
                        "revision": 0,
                        "schema_version": cwl_campaign.SCHEMA_VERSION,
                        "activated": True,
                        "migrated_at": _utc_iso(),
                    }
                },
                upsert=True,
            )
        # Legacy success markers are the only available idempotency evidence.
        # Carry current-cycle sends forward before retiring fixed job ids.
        for number in range(0, 6):
            value = legacy.get(f"last_sent_{number}") or (
                legacy.get("last_sent") if number == 0 else None
            )
            if not value:
                continue
            try:
                sent_at = pendulum.parse(value).in_timezone(
                    loaded["campaign"].get("timezone", DEFAULT_TIMEZONE)
                )
            except (TypeError, ValueError):
                continue
            if sent_at.format("YYYY-MM") != cycle:
                continue
            message_key = "signup" if number == 0 else f"reminder:{number}"
            for variant in cwl_campaign.AUDIENCES:
                await mongo_client.bot_config.update_one(
                    {"_id": cwl_campaign.cycle_id(guild_id, cycle)},
                    {
                        "$setOnInsert": {
                            "kind": "cwl_campaign_cycle",
                            "guild_id": int(guild_id),
                            "cycle": cycle,
                            "revision": 0,
                            "activated": True,
                        },
                        "$addToSet": {
                            "sent_occurrences": cwl_campaign.occurrence_id(
                                cycle, message_key, variant
                            )
                        },
                    },
                    upsert=True,
                )
        await mongo_client.cwl_reminder.update_one(
            {"_id": "schedule"},
            {
                "$set": {
                    "enabled": False,
                    "campaign_managed": True,
                    "campaign_guild_id": int(guild_id),
                    "updated_at": _utc_iso(),
                }
            },
            upsert=True,
        )
        for job_id in [cwl_base_job_id, cwl_initial_retry_job_id] + [
            f"{cwl_followup_job_prefix}{i}" for i in range(1, 6)
        ]:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            await mongo_client.cwl_pending_reminders.delete_one({"_id": job_id})

        loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
        generation = _campaign_generation(loaded)

    all_pending = await mongo_client.cwl_pending_reminders.find().to_list(length=None)
    scoped = {
        row.get("_id"): row
        for row in all_pending
        if row.get("kind") == "campaign"
        and int(row.get("guild_id", 0)) == int(guild_id)
        and row.get("cycle") == cycle
    }
    recovered, retained = await _restore_scheduled_catchups(
        list(scoped.values()), pendulum.now(DEFAULT_TIMEZONE), tagged_only=True,
        loaded=loaded, stale_generation=generation
    )
    scoped = {
        key: retained.get(key, row)
        for key, row in scoped.items()
        if key not in recovered or key in retained
    }
    desired = {
        job_id: row
        for job_id, row in scoped.items()
        if job_id in retained or row.get("status") == "ledger_pending"
        or (
            (
                row.get("job_kind") in {"manual", "retry", catchup_policy.CATCHUP_JOB_KIND}
                or int(row.get("failure_count", 0)) > 0
            )
            and row.get("generation") == generation
        )
    }
    desired = {
        key: row
        for key, row in desired.items()
        if key in retained or row.get("status") == "ledger_pending"
        or not _sequence_delivery_blocked(
            loaded, row.get("message_id", ""), pendulum.now(DEFAULT_TIMEZONE)
        )
    }
    sent = set(loaded.get("sent_occurrences", [])) | {
        item.get("occurrence_id")
        for item in loaded.get("deliveries", [])
        if item.get("status") == "sent"
    }
    skipped = set(loaded.get("skipped", []))
    now = pendulum.now(DEFAULT_TIMEZONE)
    if not loaded["campaign"].get("paused"):
        for occurrence in loaded["schedule"]:
            if (
                occurrence.get("run_at") is None
                or occurrence["id"] in sent
                or occurrence["id"] in skipped
            ):
                continue
            message_id = occurrence["message_id"]
            variant = occurrence["variant"]
            when = pendulum.parse(occurrence["run_at"]).in_timezone(DEFAULT_TIMEZONE)
            if when <= now:
                continue
            job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
            desired[job_id] = (when, message_id, [variant])
            existing = scoped.get(job_id, {})
            # A confirmed post awaiting ledger persistence, or an active retry,
            # owns its occurrence until it completes.
            if (
                (job_id in retained and _campaign_row_active(existing))
                or existing.get("status") == "ledger_pending"
                or int(existing.get("failure_count", 0)) > 0
            ):
                desired[job_id] = existing
                continue
            await _persist_campaign_job(
                job_id,
                when,
                guild_id,
                cycle,
                message_id,
                [variant],
                generation,
            )
            _add_campaign_job(
                job_id,
                when,
                guild_id,
                cycle,
                message_id,
                [variant],
                generation,
            )
    for job_id in set(scoped) - set(desired):
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        await mongo_client.cwl_pending_reminders.delete_one({"_id": job_id})
    if runtime_id == _campaign_runtime_id:
        _campaign_loaded_generations[proof_key] = generation


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def queue_campaign_retry(
    guild_id: int, cycle: str, occurrence: str
) -> None:
    event_cycle, message_id, variant = occurrence.split("|", 2)
    if event_cycle != cycle:
        raise ValueError("Occurrence belongs to another cycle")
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    generation = _campaign_generation(loaded)
    run_time = pendulum.now(DEFAULT_TIMEZONE).add(seconds=2)
    if _sequence_delivery_blocked(loaded, message_id, run_time):
        raise ValueError(
            "This reminder is no longer scheduled or signups have closed."
        )
    job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
    staff_request_id = uuid.uuid4().hex if message_id != "roster" else None
    await _persist_campaign_job(
        job_id,
        run_time,
        guild_id,
        cycle,
        message_id,
        [variant],
        generation,
        job_kind="retry",
        staff_request_id=staff_request_id,
    )
    _add_campaign_job(
        job_id, run_time, guild_id, cycle, message_id, [variant], generation,
        staff_request_id=staff_request_id,
    )


async def queue_manual_campaign_occurrence(
    guild_id: int, cycle: str, message_id: str, variants: list[str]
) -> str:
    loaded = await cwl_campaign.load_campaign(mongo_client, guild_id, cycle)
    generation = _campaign_generation(loaded)
    run_time = pendulum.now(DEFAULT_TIMEZONE).add(seconds=2)
    if _sequence_delivery_blocked(loaded, message_id, run_time):
        raise ValueError(
            "This reminder is no longer scheduled or signups have closed."
        )
    job_ids = []
    for variant in variants:
        job_id = _campaign_job_id(guild_id, cycle, message_id, variant)
        staff_request_id = uuid.uuid4().hex if message_id != "roster" else None
        await _persist_campaign_job(
            job_id,
            run_time,
            guild_id,
            cycle,
            message_id,
            [variant],
            generation,
            job_kind="manual",
            staff_request_id=staff_request_id,
        )
        _add_campaign_job(
            job_id,
            run_time,
            guild_id,
            cycle,
            message_id,
            [variant],
            generation,
            staff_request_id=staff_request_id,
        )
        job_ids.append(job_id)
    return ",".join(job_ids)


async def remove_followup_configuration(
    number: int, mongo: MongoClient
) -> bool:
    """Remove a configured follow-up and all of its runnable state."""
    schedule_data = await mongo.cwl_reminder.find_one({"_id": "schedule"})
    if not schedule_data:
        return False

    followups = schedule_data.get("followups", [])
    remaining = [item for item in followups if item.get("number") != number]
    if len(remaining) == len(followups):
        return False

    await mongo.cwl_reminder.update_one(
        {"_id": "schedule"},
        {"$set": {"followups": remaining}},
    )

    job_id = f"{cwl_followup_job_prefix}{number}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    await mongo.cwl_pending_reminders.delete_one({"_id": job_id})
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

    await mongo_client.cwl_pending_reminders.update_one(
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
    await _persist_pending_reminder(
        job_id, run_time, reminder_number, channel_keys
    )
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
            ValueError,
            hikari.BadRequestError,
            hikari.UnauthorizedError,
            hikari.ForbiddenError,
            hikari.NotFoundError,
        ),
    )


def _delivery_issue_field(reminder_number: int) -> str:
    return f"delivery_issues.{reminder_number}"


async def _record_delivery_issue(reminder_number: int, issue: dict) -> None:
    await mongo_client.cwl_reminder.update_one(
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
    await mongo_client.cwl_pending_reminders.update_one(
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
    await mongo_client.cwl_pending_reminders.delete_one({"_id": job_id})
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
    pending = (
        await mongo_client.cwl_pending_reminders.find_one({"_id": job_id})
        or {}
    )
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
        first_failed = (
            pendulum.parse(first_failed_at) if first_failed_at else now
        )
    except (TypeError, ValueError):
        first_failed = now

    error_types = sorted({type(exc).__name__ for _, exc in failures})
    last_error = "; ".join(
        f"{key}:{type(exc).__name__}:{_delivery_error_detail(exc)}"
        for key, exc in failures
    )[:DELIVERY_ERROR_TEXT_LIMIT]
    has_permanent_error = any(
        _is_permanent_delivery_error(exc) for _, exc in failures
    )
    retry_age_hours = max(0.0, (now - first_failed).total_seconds() / 3600)

    if has_permanent_error:
        await _abandon_delivery(
            reminder_number,
            channel_keys,
            failure_count,
            "permanent_discord_error",
            error_types,
            last_error,
        )
        return False
    if failure_count >= MAX_DELIVERY_FAILURES:
        await _abandon_delivery(
            reminder_number,
            channel_keys,
            failure_count,
            "max_failures_reached",
            error_types,
            last_error,
        )
        return False
    if retry_age_hours >= MAX_DELIVERY_RETRY_AGE_HOURS:
        await _abandon_delivery(
            reminder_number,
            channel_keys,
            failure_count,
            "retry_age_exceeded",
            error_types,
            last_error,
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
    await mongo_client.cwl_pending_reminders.update_one(
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

    if LEGACY_RUNTIME_DISABLED:
        print(
            "[CWL Reminder] Legacy delivery suppressed; /manage section:CWL owns delivery"
        )
        return False

    if not bot_instance:
        print("[CWL Reminder] Bot instance not available!")
        return False
    if not test_mode and mongo_client:
        legacy_state = (
            await mongo_client.cwl_reminder.find_one({"_id": "schedule"}) or {}
        )
        if legacy_state.get("campaign_managed"):
            print(
                "[CWL Reminder] Legacy send suppressed: campaign dashboard owns delivery"
            )
            return False

    reminder_type = (
        "initial" if reminder_number == 0 else f"follow-up #{reminder_number}"
    )
    if test_mode:
        channels = [
            {
                "id": TEST_CHANNEL_ID,
                "type": "main",
                "name": "Test",
                "key": "test",
            }
        ]
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
            components = create_cwl_reminder_message(
                reminder_number, channel_info["type"]
            )
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
        await mongo_client.cwl_reminder.update_one(
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
        result = await mongo_client.cwl_pending_reminders.delete_one(
            {"_id": job_id}
        )
        if result.deleted_count > 0:
            print(
                f"[CWL Reminder] Cleaned up completed {reminder_type} reminder"
            )

        if reminder_number == 0:
            schedule_data = await mongo_client.cwl_reminder.find_one(
                {"_id": "schedule"}
            )
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
                                base_time,
                                followup_num,
                                cumulative_delay,
                            )
    else:
        print(
            f"[CWL Reminder] ALERT delivery_state_unavailable reminder={reminder_number} "
            "delivered=true action=check MongoDB; delivery accounting and follow-ups were not updated"
        )

    return True


async def schedule_followup_reminder(
    base_time: datetime, reminder_number: int, delay_minutes: int
):
    """Schedule a follow-up reminder based on the base time and delay"""
    global scheduler, mongo_client

    # Calculate when this follow-up should run
    run_time = base_time + timedelta(minutes=delay_minutes)

    # Create job ID for this follow-up
    job_id = f"{cwl_followup_job_prefix}{reminder_number}"

    await _schedule_durable_reminder(job_id, run_time, reminder_number)

    print(
        f"[CWL Reminder] Scheduled follow-up #{reminder_number} for {run_time}"
    )


async def restore_pending_reminders():
    """Restore pending follow-up reminders from MongoDB on bot startup"""
    global scheduler, mongo_client

    if not mongo_client:
        return

    print("[CWL Reminder] Checking for pending follow-up reminders...")

    # Get current time for comparison
    now = pendulum.now(DEFAULT_TIMEZONE)

    # Find all pending reminders
    pending_reminders = (
        await mongo_client.cwl_pending_reminders.find().to_list(length=None)
    )

    if not pending_reminders:
        print("[CWL Reminder] No pending reminders found")
        return

    restored_count = 0
    expired_count = 0
    failed_count = 0
    catchup_ids, _ = await _restore_scheduled_catchups(pending_reminders, now)
    for reminder in pending_reminders:
        reminder_id = reminder.get("_id")
        if reminder_id in catchup_ids:
            continue
        run_time_str = reminder.get("run_time")

        if reminder.get("kind") == "campaign":
            try:
                guild_id = int(reminder["guild_id"])
                cycle = str(reminder["cycle"])
                message_id = str(reminder["message_id"])
                if reminder.get("status") == "ledger_pending" and isinstance(
                    reminder.get("receipt"), dict
                ):
                    receipt = reminder["receipt"]
                    if reminder.get("staff_request_id") and receipt.get("status") != "sent":
                        if not cwl_campaign.is_staff_not_sent_receipt(reminder):
                            raise ValueError("Queued staff outcome needs review")
                        await cwl_campaign.record_staff_not_sent(mongo_client, reminder)
                        restored_count += 1
                        continue
                    if receipt.get("late") and message_id != "roster":
                        try:
                            await cwl_campaign.record_catchup_delivery(mongo_client, guild_id, cycle, receipt)
                        except Exception:
                            print("[CWL Reminder] ALERT campaign_catchup_receipt_unavailable action=review delivery history")
                            raise
                        await cwl_campaign.finish_catchup_attempt(
                            mongo_client, guild_id, cycle, receipt["occurrence_id"]
                        )
                    else:
                        await cwl_campaign.record_delivery(mongo_client, guild_id, cycle, receipt)
                    await _release_campaign_claim(
                        guild_id,
                        cycle,
                        receipt["occurrence_id"],
                    )
                    if receipt.get("late") and message_id != "roster":
                        await cwl_campaign.delete_catchup_job(mongo_client, reminder)
                    else:
                        await mongo_client.cwl_pending_reminders.delete_one(
                            {"_id": reminder_id}
                        )
                    restored_count += 1
                    continue
                variants = [
                    value
                    for value in reminder.get("variants", [])
                    if value in cwl_campaign.AUDIENCES
                ]
                run_time = pendulum.parse(run_time_str)
                loaded = await cwl_campaign.load_campaign(
                    mongo_client, guild_id, cycle
                )
                generation = _campaign_generation(loaded)
                if (
                    not variants
                    or loaded["campaign"].get("paused")
                    or _sequence_delivery_blocked(
                        loaded, message_id, max(now, run_time)
                    )
                    or reminder.get("generation") != generation
                ):
                    await mongo_client.cwl_pending_reminders.delete_one(
                        {"_id": reminder_id}
                    )
                    if scheduler.get_job(reminder_id):
                        scheduler.remove_job(reminder_id)
                    continue
                sent = set(loaded.get("sent_occurrences", [])) | {
                    item.get("occurrence_id")
                    for item in loaded.get("deliveries", [])
                    if item.get("status") == "sent"
                }
                skipped = set(loaded.get("skipped", []))
                variants = [
                    value
                    for value in variants
                    if cwl_campaign.occurrence_id(cycle, message_id, value)
                    not in sent | skipped
                ]
                if not variants:
                    await mongo_client.cwl_pending_reminders.delete_one(
                        {"_id": reminder_id}
                    )
                    continue
                staff_request_id = None
                if (
                    message_id != "roster"
                    and reminder.get("job_kind") in {"manual", "retry"}
                    and not reminder.get("failure_count", 0)
                ):
                    staff_request_id = reminder.get("staff_request_id") or uuid.uuid4().hex
                if run_time <= now:
                    if run_time < now.subtract(days=PENDING_EXPIRY_DAYS):
                        await mongo_client.cwl_pending_reminders.delete_one(
                            {"_id": reminder_id}
                        )
                        expired_count += 1
                        continue
                    run_time = now.add(seconds=5)
                    await _persist_campaign_job(
                        reminder_id,
                        run_time,
                        guild_id,
                        cycle,
                        message_id,
                        variants,
                        generation,
                        failure_count=int(reminder.get("failure_count", 0)),
                        job_kind=reminder.get("job_kind", "scheduled"),
                        staff_request_id=staff_request_id,
                    )
                elif staff_request_id and not reminder.get("staff_request_id"):
                    await _persist_campaign_job(
                        reminder_id, run_time, guild_id, cycle, message_id, variants,
                        generation, failure_count=int(reminder.get("failure_count", 0)),
                        job_kind=reminder["job_kind"], staff_request_id=staff_request_id,
                    )
                _add_campaign_job(
                    reminder_id,
                    run_time,
                    guild_id,
                    cycle,
                    message_id,
                    variants,
                    generation,
                    staff_request_id=staff_request_id,
                )
                restored_count += 1
            except Exception as exc:
                print(
                    f"[CWL Campaign] pending_restore_failed id={reminder_id} "
                    f"error={type(exc).__name__}:{_delivery_error_detail(exc)}"
                )
                failed_count += 1
            continue

        if LEGACY_RUNTIME_DISABLED:
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": reminder_id}
            )
            if reminder_id and scheduler.get_job(reminder_id):
                scheduler.remove_job(reminder_id)
            continue

        reminder_number = reminder.get("reminder_number")
        job_id = reminder.get("job_id")

        if reminder.get("status") == "abandoned":
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": reminder_id}
            )
            print(
                f"[CWL Reminder] Cleaned up terminal pending reminder {reminder_id}"
            )
            continue

        if (
            not reminder_id
            or not run_time_str
            or reminder_number is None
            or not job_id
        ):
            # Invalid reminder data, clean it up
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": reminder_id}
            )
            continue

        try:
            run_time = pendulum.parse(run_time_str)
        except Exception as e:
            print(
                f"[CWL Reminder] Invalid pending reminder {reminder_id}: {e}"
            )
            await mongo_client.cwl_pending_reminders.delete_one(
                {"_id": reminder_id}
            )
            continue

        try:
            if run_time > now:
                channel_keys = reminder.get("channel_keys")
                _add_reminder_job(
                    job_id, run_time, reminder_number, channel_keys
                )

                print(
                    f"[CWL Reminder] Restored follow-up #{reminder_number} for {run_time}"
                )
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
                _add_reminder_job(
                    job_id, retry_time, reminder_number, channel_keys
                )
                print(
                    f"[CWL Reminder] Restored overdue reminder #{reminder_number} "
                    f"for retry at {retry_time}"
                )
                restored_count += 1
            else:
                # Reminder has expired, clean it up
                await mongo_client.cwl_pending_reminders.delete_one(
                    {"_id": reminder_id}
                )
                print(
                    f"[CWL Reminder] Cleaned up expired reminder #{reminder_number} (was scheduled for {run_time})"
                )
                expired_count += 1

        except Exception as e:
            # Keep valid durable state so another restart can recover it if
            # scheduler registration is temporarily unavailable.
            print(
                f"[CWL Reminder] Error scheduling reminder {reminder_id}: {e}"
            )
            failed_count += 1

    if restored_count > 0:
        print(
            f"[CWL Reminder] Successfully restored {restored_count} pending reminder(s)"
        )
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
    if LEGACY_RUNTIME_DISABLED:
        return False
    current = (
        pendulum.instance(now, tz=DEFAULT_TIMEZONE)
        if now
        else pendulum.now(DEFAULT_TIMEZONE)
    )
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
            if (
                pendulum.parse(last_sent).in_timezone(DEFAULT_TIMEZONE)
                >= scheduled_time
            ):
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
    print(
        f"[CWL Reminder] Restored missed base reminder for retry at {retry_time}"
    )
    return True


async def schedule_cwl_reminder(
    day: int,
    hour: int,
    minute: int,
):
    """Schedule or reschedule the CWL reminder"""
    global scheduler, mongo_client
    if LEGACY_RUNTIME_DISABLED:
        raise RuntimeError(
            "Legacy CWL scheduling is retired; use /manage section:CWL"
        )
    if mongo_client:
        legacy_state = (
            await mongo_client.cwl_reminder.find_one({"_id": "schedule"}) or {}
        )
        if legacy_state.get("campaign_managed"):
            raise RuntimeError("CWL dashboard owns scheduling for this server")

    # Remove existing base job if any
    if scheduler.get_job(cwl_base_job_id):
        scheduler.remove_job(cwl_base_job_id)

    # Create new trigger for base reminder
    trigger = CronTrigger(
        day=day, hour=hour, minute=minute, timezone=DEFAULT_TIMEZONE
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
        await mongo_client.cwl_reminder.update_one(
            {"_id": "schedule"},
            {
                "$set": {
                    "day": day,
                    "hour": hour,
                    "minute": minute,
                    "timezone": DEFAULT_TIMEZONE,
                    "enabled": True,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            },
            upsert=True,
        )

    return True


async def _poll_web_roster_bridge() -> None:
    """Deliver reviewed web requests through the native campaign sender."""
    from utils.manage_poll_cache import timed_step

    if mongo_client is None or bot_instance is None:
        return
    try:
        try:
            with timed_step(logging.getLogger(__name__), "reconcile_campaign_changes"):
                await cwl_web_bridge.reconcile_campaign_changes(
                    mongo_client,
                    _sync_all_campaigns,
                    guild_id=cwl_campaign.LEGACY_WU_GUILD_ID,
                    loaded_generations=lambda: _loaded_campaign_generations(
                        cwl_campaign.LEGACY_WU_GUILD_ID
                    ),
                    runtime_id=_campaign_runtime_id,
                )
        except Exception as exc:
            # A bad schedule must not block the independent reviewed roster queue.
            # No acknowledgement is written; the next poll retries reconciliation.
            print(f"[CWL Web Bridge] Schedule sync failed: {type(exc).__name__}")

        async def can_send_roster(row):
            from utils.dashboard_access import (
                OWNER_IDS,
                AccessRepository,
                effective,
                expand_legacy,
            )

            uid = str(row["requested_by"])
            if uid in OWNER_IDS:
                return True
            member = await bot_instance.rest.fetch_member(
                int(row["guild_id"]), int(uid)
            )
            document = await AccessRepository(mongo_client.bot_config).read()
            if document is not None:
                return "cwl_send" in effective(document, uid, member.role_ids)
            grant = (
                await mongo_client.bot_config.find_one(
                    {"_id": "dashboard-access:" + uid}
                )
                or {}
            )
            return "cwl_send" in expand_legacy(grant.get("permissions", []))

        post_worker = None
        post_ready = False
        try:
            post_worker = _post_update_worker_for_runtime()
            post_ready = await post_worker.ensure_ready(cwl_campaign.LEGACY_WU_GUILD_ID)
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Roster post editor is unavailable (%s)", type(exc).__name__
            )

        with timed_step(logging.getLogger(__name__), "process_pending_roster_requests"):
            await cwl_web_bridge.process_pending_roster_requests(
                mongo_client,
                send_campaign_message,
                authorize=can_send_roster,
                guild_id=cwl_campaign.LEGACY_WU_GUILD_ID,
                worker_epoch=_campaign_runtime_id,
                schedule_ready=_loaded_campaign_generations(
                    cwl_campaign.LEGACY_WU_GUILD_ID
                )
                is not None,
                post_update_ready=post_ready,
            )
        if post_ready:

            async def can_update_post(row):
                if not await can_send_roster(row):
                    return False
                from extensions.tasks.cwl_post_update_bridge import validate_scope

                return await validate_scope(row)

            with timed_step(logging.getLogger(__name__), "process_post_updates"):
                await post_worker.poll(
                    guild_id=cwl_campaign.LEGACY_WU_GUILD_ID, authorize=can_update_post
                )
    except Exception as exc:
        # Leave pending or sending rows in place for inspection. In particular,
        # never auto-reset a possibly posted sending row after an outage.
        print(f"[CWL Web Bridge] Poll failed: {type(exc).__name__}")


_post_update_worker = None


def _post_update_worker_for_runtime():
    global _post_update_worker
    from utils.cwl_post_updates import PostUpdateWorker

    if (
        _post_update_worker is None
        or _post_update_worker.mongo is not mongo_client
        or _post_update_worker.bot is not bot_instance
    ):
        _post_update_worker = PostUpdateWorker(
            mongo_client, bot_instance, runtime_id=uuid.uuid4().hex
        )
    return _post_update_worker


_roster_driver = None


async def _drive_web_roster_requests():
    from utils.manage_web_worker import queue_lock, maintain_worker_heartbeat
    from utils.manage_poll_cache import timed_step

    logger = logging.getLogger(__name__)
    heartbeat = asyncio.create_task(maintain_worker_heartbeat(mongo_client))
    try:
        # Preserve the shared side-effect lane. Timing separates waiting for it
        # from actual Mongo/Discord work; admission ticks never start a duplicate.
        lock = queue_lock()
        with timed_step(logger, "cwl_queue_wait"):
            await lock.acquire()
        try:
            with timed_step(logger, "cwl_bridge"):
                await _poll_web_roster_bridge()
        finally:
            lock.release()
        try:
            from utils.manage_web_worker import poll as poll_management

            with timed_step(logger, "management_poll"):
                await poll_management(bot_instance, mongo_client)
        except Exception as exc:
            logger.warning("Manage Web Bridge poll failed: %s", type(exc).__name__)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("CWL Web Bridge driver failed: %s", type(exc).__name__)
    finally:
        heartbeat.cancel()
        import contextlib

        try:
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat
        except Exception as exc:
            logger.warning("Management heartbeat unavailable: %s", type(exc).__name__)


async def _poll_web_roster_requests() -> None:
    global _roster_driver
    if _management_stopping:
        return
    if _roster_driver is None or _roster_driver.done():
        _roster_driver = asyncio.create_task(_drive_web_roster_requests())


_management_driver = None
_management_stopping = False


async def _drive_web_management():
    try:
        from utils.manage_web_worker import fast_poll

        await fast_poll(bot_instance, mongo_client)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        print(f"[Manage Fast Poll] {type(error).__name__}")


async def _poll_web_management_fast():
    global _management_driver
    if _management_stopping or bot_instance is None or mongo_client is None:
        return
    if _management_driver is None or _management_driver.done():
        from utils.manage_web_worker import idle_poll_due

        if idle_poll_due(mongo_client):
            _management_driver = asyncio.create_task(_drive_web_management())


def _silence_fast_job_logs():
    import logging

    class FastJobFilter(logging.Filter):
        def filter(self, record):
            return record.levelno > logging.INFO or not any(
                name in record.getMessage()
                for name in ("_poll_web_management_fast", "_poll_web_roster_requests")
            )

    logger = logging.getLogger("apscheduler.executors.default")
    if not any(getattr(f, "_wu_fast_job", False) for f in logger.filters):
        quiet = FastJobFilter()
        quiet._wu_fast_job = True
        logger.addFilter(quiet)


async def _reconcile_cwl_startup() -> None:
    """Idempotently restore durable CWL jobs after dependencies are ready."""
    _silence_fast_job_logs()
    if not getattr(scheduler, "running", True):
        scheduler.start()
    scheduler.add_job(
        _poll_web_roster_requests,
        trigger=IntervalTrigger(seconds=10),
        id=WEB_ROSTER_BRIDGE_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    scheduler.add_job(
        _poll_web_management_fast,
        trigger=IntervalTrigger(seconds=1),
        id=WEB_MANAGEMENT_FAST_JOB_ID,
        replace_existing=True,
        coalesce=True,
        max_instances=1,
    )

    if LEGACY_RUNTIME_DISABLED:
        # APScheduler currently uses an in-memory job store, but clearing every
        # known id and non-campaign durable row also makes hot reloads and old
        # database state fail closed.
        for job_id in [
            cwl_base_job_id,
            cwl_initial_retry_job_id,
            *(f"{cwl_followup_job_prefix}{number}" for number in range(1, 6)),
        ]:
            if scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
        pending = await mongo_client.cwl_pending_reminders.find().to_list(
            length=None
        )
        for row in pending:
            if row.get("kind") == "campaign":
                continue
            job_id = row.get("_id")
            if job_id and scheduler.get_job(job_id):
                scheduler.remove_job(job_id)
            if job_id:
                await mongo_client.cwl_pending_reminders.delete_one(
                    {"_id": job_id}
                )

        await restore_pending_reminders()
        await _sync_all_campaigns()
        scheduler.add_job(
            _sync_all_campaigns,
            trigger=CronTrigger(
                day=1, hour=0, minute=5, timezone=DEFAULT_TIMEZONE
            ),
            id=CAMPAIGN_ROLLOVER_JOB_ID,
            replace_existing=True,
            **JOB_OPTIONS,
        )
        return

    # Current-cycle date jobs are the authoritative pending state. Restore
    # them before installing the next recurring base schedule so a restart
    # cannot replace them with next month's calculated follow-ups.
    await restore_pending_reminders()

    # Load saved schedule from MongoDB
    schedule_data = await mongo_client.cwl_reminder.find_one(
        {"_id": "schedule"}
    )

    if schedule_data and schedule_data.get("enabled", False):
        day = schedule_data.get("day")
        hour = schedule_data.get("hour")
        minute = schedule_data.get("minute")

        if all(x is not None for x in [day, hour, minute]):
            await restore_missed_base_reminder(schedule_data)

            # Schedule base reminder
            await schedule_cwl_reminder(day, hour, minute)
            print(
                f"[CWL Reminder] Loaded base schedule: Day {day} at {hour:02d}:{minute:02d}"
            )

            # Load and display follow-ups
            followups = schedule_data.get("followups", [])
            if followups:
                print(
                    f"[CWL Reminder] Found {len(followups)} follow-up reminder(s) to schedule:"
                )
                for f in followups:
                    if f.get("enabled", True):
                        # Try to get delay_display, fall back to calculating from delay_minutes
                        delay_display = f.get("delay_display")
                        if not delay_display and f.get("delay_minutes"):
                            minutes = f.get("delay_minutes", 0)
                            if minutes >= 1440:
                                delay_display = f"{minutes // 1440} days"
                            elif minutes >= 60:
                                delay_display = f"{minutes // 60} hours"
                            else:
                                delay_display = f"{minutes} minutes"
                        print(
                            f"  - Reminder #{f.get('number')}: {delay_display or 'unknown delay'}"
                        )

    await _sync_all_campaigns()
    scheduler.add_job(
        _sync_all_campaigns,
        trigger=CronTrigger(
            day=1, hour=0, minute=5, timezone=DEFAULT_TIMEZONE
        ),
        id=CAMPAIGN_ROLLOVER_JOB_ID,
        replace_existing=True,
        **JOB_OPTIONS,
    )


async def _sync_all_campaigns() -> bool:
    """Install current/next-cycle jobs for every guild using the dashboard."""
    global _campaign_load_scan_complete
    if not hasattr(mongo_client, "bot_config"):
        return False
    rows = await mongo_client.bot_config.find(
        {"kind": {"$in": ["cwl_campaign_defaults", "cwl_campaign_cycle"]}, "activated": True},
        {"_id": 1, "kind": 1, "activated": 1, "guild_id": 1, "cycle": 1},
    ).to_list(length=None)
    guilds = {
        int(row["guild_id"])
        for row in rows
        if row.get("kind") in {"cwl_campaign_defaults", "cwl_campaign_cycle"}
        and row.get("activated") is True
        and row.get("guild_id") is not None
    }
    now = pendulum.now(DEFAULT_TIMEZONE)
    current = now.format("YYYY-MM")
    following = now.add(months=1).format("YYYY-MM")
    explicit_cycles = {
        (int(row["guild_id"]), str(row["cycle"]))
        for row in rows
        if row.get("kind") == "cwl_campaign_cycle"
        and row.get("activated") is True
        and row.get("guild_id") is not None
        and row.get("cycle")
    }
    for guild_id in set(_campaign_load_targets) - guilds:
        _campaign_load_targets[guild_id] = set()
    for guild_id in guilds:
        targets = {current, following} | {
            value for owner, value in explicit_cycles if owner == guild_id
        }
        _campaign_load_targets[guild_id] = targets
        for cycle in targets:
            await sync_campaign_schedule(guild_id, cycle)
    _campaign_load_scan_complete = True
    return bool(guilds)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent, mongo: MongoClient = lightbulb.di.INJECTED
) -> None:
    """Start non-blocking, self-healing restoration of the saved schedule."""
    global bot_instance, mongo_client, startup_reconciler, _management_stopping, _campaign_runtime_id, _campaign_load_scan_complete
    _management_stopping = False
    if bot_instance is not event.app or mongo_client is not mongo:
        _campaign_load_targets.clear()
        _campaign_loaded_generations.clear()
        _campaign_sync_locks.clear()
        _campaign_load_scan_complete = False
        _campaign_runtime_id = uuid.uuid4().hex

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
    global startup_reconciler, _management_driver, _management_stopping, _roster_driver, _campaign_load_scan_complete, _post_update_worker
    _management_stopping = True
    _campaign_load_targets.clear()
    _campaign_loaded_generations.clear()
    _campaign_sync_locks.clear()
    _campaign_load_scan_complete = False
    import contextlib

    for driver in (_management_driver, _roster_driver):
        if driver is not None:
            driver.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await driver
    _management_driver = _roster_driver = None
    _post_update_worker = None
    if startup_reconciler is not None:
        await startup_reconciler.stop()
        startup_reconciler = None
    if getattr(scheduler, "running", False):
        scheduler.shutdown()
        await asyncio.sleep(0)
        print("[CWL Reminder] Scheduler shutdown")


async def _legacy_campaign_guard(ctx, mongo) -> bool:
    """Retired controls must never recreate the global scheduler after adoption."""
    interaction = ctx.interaction
    permissions = getattr(
        getattr(interaction, "member", None),
        "permissions",
        hikari.Permissions.NONE,
    )
    if not permissions & hikari.Permissions.ADMINISTRATOR:
        await ctx.respond(
            "You need Administrator permission to use legacy CWL controls.",
            ephemeral=True,
        )
        return True
    if LEGACY_RUNTIME_DISABLED:
        await ctx.respond(
            "The old CWL commands do not work now. Use `/manage section:CWL` to edit, preview, schedule, pause, or send CWL announcements.",
            ephemeral=True,
        )
        return True
    if (
        int(getattr(interaction, "guild_id", 0) or 0)
        != cwl_campaign.LEGACY_WU_GUILD_ID
    ):
        await ctx.respond(
            "Use `/manage section:CWL` to manage CWL in this server.",
            ephemeral=True,
        )
        return True
    if mongo is None:
        await ctx.respond(
            "The CWL scheduler is still starting. Try again shortly.",
            ephemeral=True,
        )
        return True
    schedule = await mongo.cwl_reminder.find_one({"_id": "schedule"}) or {}
    if schedule.get("campaign_managed"):
        await ctx.respond(
            "Use `/manage section:CWL` to manage CWL. There you can edit messages, change the times, pause delivery, or preview a message. A preview does not send a test ping.",
            ephemeral=True,
        )
        return True
    return False


# Create command group
cwl_reminder = lightbulb.Group(
    "cwl-reminder",
    "Manage CWL monthly reminders",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)


@cwl_reminder.register()
class Schedule(
    lightbulb.SlashCommand,
    name="schedule",
    description="Schedule the monthly CWL reminder",
):
    day = lightbulb.integer(
        "day", "Day of the month (1-31)", min_value=1, max_value=31
    )

    hour = lightbulb.integer(
        "hour", "Hour (0-23, 24-hour format)", min_value=0, max_value=23
    )

    minute = lightbulb.integer(
        "minute", "Minute (0-59)", min_value=0, max_value=59, default=0
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo_client):
            return

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
                f"❌ **Failed to schedule reminder!**\n" f"Error: {str(e)}"
            )


@cwl_reminder.register()
class Status(
    lightbulb.SlashCommand,
    name="status",
    description="Check the current CWL reminder schedule",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return
        startup_status = (
            startup_reconciler.status_text()
            if startup_reconciler is not None
            else "⏹️ Stopped"
        )
        # Get schedule from MongoDB
        try:
            schedule_data = await mongo.cwl_reminder.find_one(
                {"_id": "schedule"}
            )
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
                ephemeral=True,
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
        for number, issue in sorted(
            delivery_issues.items(), key=lambda item: str(item[0])
        ):
            reminder_label = (
                "initial" if str(number) == "0" else f"follow-up {number}"
            )
            failure_count = issue.get("failure_count", "?")
            max_failures = issue.get("max_failures", MAX_DELIVERY_FAILURES)
            channels = (
                ", ".join(issue.get("channel_keys", [])) or "unknown channel"
            )
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
    lightbulb.SlashCommand, name="test", description="Send a test CWL reminder"
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo_client):
            return

        try:
            delivered = await send_cwl_reminder(test_mode=True)
            if delivered:
                await ctx.respond(
                    f"✅ **Test reminder sent!**\n"
                    f"Check <#{TEST_CHANNEL_ID}> to see the message."
                )
            else:
                await ctx.respond(
                    "❌ **The test reminder could not be delivered.**"
                )
        except Exception as e:
            await ctx.respond(
                f"❌ **Failed to send test reminder!**\n" f"Error: {str(e)}"
            )


@cwl_reminder.register()
class Cancel(
    lightbulb.SlashCommand,
    name="cancel",
    description="Cancel the scheduled CWL reminder",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        # Remove the base job
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return
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
        result = await mongo.cwl_pending_reminders.delete_many(
            {"kind": {"$ne": "campaign"}}
        )
        if result.deleted_count > 0:
            print(
                f"[CWL Reminder] Cleared {result.deleted_count} pending reminder(s) from database"
            )

        # Update MongoDB
        await mongo.cwl_reminder.update_one(
            {"_id": "schedule"}, {"$set": {"enabled": False}}, upsert=True
        )

        await ctx.respond(
            "✅ **CWL reminder cancelled**\n"
            "The monthly reminder has been disabled.",
            ephemeral=True,
        )


@cwl_reminder.register()
class AddFollowup(
    lightbulb.SlashCommand,
    name="add-followup",
    description="Add or update a follow-up reminder",
):
    number = lightbulb.integer(
        "number", "Reminder number (1-5)", min_value=1, max_value=5
    )

    delay = lightbulb.integer(
        "delay",
        "Time delay after the previous reminder",
        min_value=1,
        max_value=36,  # Max 36 (hours/days depending on unit)
    )

    unit = lightbulb.string(
        "unit",
        "Time unit for delay",
        choices=[
            lightbulb.Choice("minutes", "minutes"),
            lightbulb.Choice("hours", "hours"),
            lightbulb.Choice("days", "days"),
        ],
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return

        # Get current schedule
        schedule_data = await mongo.cwl_reminder.find_one({"_id": "schedule"})

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
        existing_index = next(
            (
                i
                for i, f in enumerate(followups)
                if f.get("number") == self.number
            ),
            None,
        )

        followup_data = {
            "number": self.number,
            "delay_minutes": delay_minutes,
            "delay_display": f"{self.delay} {self.unit}",
            "enabled": True,
        }

        if existing_index is not None:
            followups[existing_index] = followup_data
        else:
            followups.append(followup_data)

        # Sort by number
        followups.sort(key=lambda x: x.get("number", 0))

        # Update MongoDB
        await mongo.cwl_reminder.update_one(
            {"_id": "schedule"}, {"$set": {"followups": followups}}
        )

        # Calculate total delay for this reminder
        total_delay = sum(
            f.get("delay_minutes", 0)
            for f in followups
            if f.get("number", 0) <= self.number
        )

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
            next_base_time = pendulum.instance(
                base_job.next_run_time, tz=DEFAULT_TIMEZONE
            )
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
    description="Remove a follow-up reminder",
):
    number = lightbulb.integer(
        "number", "Reminder number to remove (1-5)", min_value=1, max_value=5
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return

        if not await remove_followup_configuration(self.number, mongo):
            await ctx.respond(
                f"❌ **No follow-up reminder #{self.number} found!**"
            )
            return

        await ctx.respond(f"✅ **Removed follow-up reminder #{self.number}**")


@cwl_reminder.register()
class List(
    lightbulb.SlashCommand,
    name="list",
    description="List all configured CWL reminders and their times",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return

        # Get schedule data
        schedule_data = await mongo.cwl_reminder.find_one({"_id": "schedule"})

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

            for followup in sorted(
                followups, key=lambda x: x.get("number", 0)
            ):
                if followup.get("enabled", True):
                    number = followup.get("number")
                    delay = followup.get("delay_minutes", 0)
                    delay_display = followup.get(
                        "delay_display", f"{delay} minutes"
                    )
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
                    lines.append(
                        f"• {delay_display} after previous ({total_display} total)"
                    )
                    lines.append(f"• Sends at: {time_str}")
                    lines.append(f"• Message: Sign-up Reminder #{number}")

        lines.append(f"\n*All times in {DEFAULT_TIMEZONE}*")

        await ctx.respond("\n".join(lines))


@cwl_reminder.register()
class TestAll(
    lightbulb.SlashCommand,
    name="test-all",
    description="Test all configured reminders in sequence (5 second delays)",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return

        # Get schedule data
        schedule_data = await mongo.cwl_reminder.find_one({"_id": "schedule"})

        if not schedule_data:
            await ctx.respond("❌ **No reminders configured!**")
            return

        followups = schedule_data.get("followups", [])
        total_reminders = 1 + len(
            [f for f in followups if f.get("enabled", True)]
        )

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
    description="Send all reminders immediately with proper delays",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if await _legacy_campaign_guard(ctx, mongo):
            return

        # Get schedule data
        schedule_data = await mongo.cwl_reminder.find_one({"_id": "schedule"})

        if not schedule_data:
            await ctx.respond("❌ **No reminders configured!**")
            return

        followups = schedule_data.get("followups", [])

        # A successful initial delivery is the single owner that schedules
        # configured follow-ups. Do not schedule them a second time here.
        delivered = await send_cwl_reminder(0)
        scheduled_count = len(
            [
                followup
                for followup in followups
                if followup.get("enabled", True)
                and followup.get("number")
                and followup.get("delay_minutes", 0) > 0
            ]
        )

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


# Intentionally not registered: /manage section:CWL is the sole CWL announcement
# command surface. The classes stay importable during migration so any stale
# callback fails through _legacy_campaign_guard without sending.
