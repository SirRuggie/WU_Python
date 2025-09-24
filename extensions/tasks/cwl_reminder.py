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
scheduler.start()
bot_instance = None
mongo_client = None
cwl_base_job_id = "cwl_monthly_reminder"
cwl_followup_job_prefix = "cwl_followup_"


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


async def send_cwl_reminder(reminder_number: int = 0, test_mode: bool = False):
    """Send CWL signup reminder messages to channels"""
    global bot_instance, mongo_client

    if not bot_instance:
        print("[CWL Reminder] Bot instance not available!")
        return

    reminder_type = "initial" if reminder_number == 0 else f"follow-up #{reminder_number}"

    # Choose channels based on test mode
    if test_mode:
        channels = [
            {"id": TEST_CHANNEL_ID, "type": "main", "name": "Test"}
        ]
    else:
        channels = [
            {"id": CWL_CHANNEL_ID, "type": "main", "name": "Main"},
            {"id": LAZY_CWL_CHANNEL_ID, "type": "lazy", "name": "Lazy"}
        ]
    
    for channel_info in channels:
        try:
            # Create the reminder message for this channel type
            components = create_cwl_reminder_message(reminder_number, channel_info["type"])
            
            # Send the message
            await bot_instance.rest.create_message(
                channel=channel_info["id"],
                components=components,
                role_mentions=[ROLE_TO_PING]
            )
            
            print(f"[CWL Reminder] Sent {reminder_type} reminder to {channel_info['name']} channel at {datetime.now()}")
            
        except Exception as e:
            print(f"[CWL Reminder] Failed to send to {channel_info['name']} channel: {e}")
    
    # Update last sent time in MongoDB
    if mongo_client:
        await mongo_client.database.cwl_reminder.update_one(
            {"_id": "schedule"},
            {"$set": {
                f"last_sent_{reminder_number}": datetime.now(timezone.utc).isoformat()
            }},
            upsert=True
        )
        
        # If this is the initial reminder, schedule all follow-ups
        if reminder_number == 0:
            schedule_data = await mongo_client.database.cwl_reminder.find_one({"_id": "schedule"})
            if schedule_data:
                followups = schedule_data.get("followups", [])
                base_time = pendulum.now(DEFAULT_TIMEZONE)
                
                # Calculate cumulative delays
                cumulative_delay = 0
                for followup in sorted(followups, key=lambda x: x.get("number", 0)):
                    if followup.get("enabled", True):
                        followup_num = followup.get("number")
                        delay = followup.get("delay_minutes", 0)
                        cumulative_delay += delay
                        
                        if followup_num and cumulative_delay > 0:
                            await schedule_followup_reminder(base_time, followup_num, cumulative_delay)


async def schedule_followup_reminder(base_time: datetime, reminder_number: int, delay_minutes: int):
    """Schedule a follow-up reminder based on the base time and delay"""
    global scheduler
    
    # Calculate when this follow-up should run
    run_time = base_time + timedelta(minutes=delay_minutes)
    
    # Create job ID for this follow-up
    job_id = f"{cwl_followup_job_prefix}{reminder_number}"
    
    # Remove existing job if any
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
    
    # Schedule the follow-up
    scheduler.add_job(
        send_cwl_reminder,
        trigger=DateTrigger(run_date=run_time, timezone=DEFAULT_TIMEZONE),
        id=job_id,
        args=[reminder_number],
        replace_existing=True
    )
    
    print(f"[CWL Reminder] Scheduled follow-up #{reminder_number} for {run_time}")


async def reschedule_all_reminders():
    """Reschedule all reminders based on current configuration"""
    global scheduler, mongo_client
    
    if not mongo_client:
        return
    
    # Get schedule configuration
    schedule_data = await mongo_client.database.cwl_reminder.find_one({"_id": "schedule"})
    if not schedule_data or not schedule_data.get("enabled", False):
        return
    
    # Get the next run time from the base job or calculate it
    base_job = scheduler.get_job(cwl_base_job_id)
    
    if base_job and base_job.next_run_time:
        # Use existing job's next run time
        next_run = pendulum.instance(base_job.next_run_time, tz=DEFAULT_TIMEZONE)
        print(f"[CWL Reminder] Using existing job next run time: {next_run}")
    else:
        # Calculate next run time from schedule data
        day = schedule_data.get("day")
        hour = schedule_data.get("hour")
        minute = schedule_data.get("minute")
        
        if not all(x is not None for x in [day, hour, minute]):
            print("[CWL Reminder] Missing schedule data for calculating next run")
            return
        
        # Calculate when the base reminder should next run
        now = pendulum.now(DEFAULT_TIMEZONE)
        next_run = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
        
        # If the time has passed this month, move to next month
        if next_run <= now:
            next_run = next_run.add(months=1)
        
        print(f"[CWL Reminder] Calculated next run time: {next_run}")
    
    # Get follow-up reminders configuration
    followups = schedule_data.get("followups", [])
    
    if not followups:
        print("[CWL Reminder] No follow-up reminders to schedule")
        return
    
    # Calculate cumulative delays and schedule follow-ups
    cumulative_delay = 0
    for followup in sorted(followups, key=lambda x: x.get("number", 0)):
        if followup.get("enabled", True):
            reminder_number = followup.get("number")
            delay_minutes = followup.get("delay_minutes", 0)
            cumulative_delay += delay_minutes
            
            if reminder_number and cumulative_delay > 0:
                await schedule_followup_reminder(next_run, reminder_number, cumulative_delay)


async def schedule_cwl_reminder(day: int, hour: int, minute: int):
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
        replace_existing=True
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
    
    # Small delay to ensure job is registered
    await asyncio.sleep(0.1)
    
    # Reschedule all follow-ups based on new base time
    await reschedule_all_reminders()
    
    return True


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_bot_started(
    event: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED
) -> None:
    """Load saved schedule when bot starts"""
    global bot_instance, mongo_client
    
    bot_instance = event.app
    mongo_client = mongo
    
    # Load saved schedule from MongoDB
    schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
    
    if schedule_data and schedule_data.get("enabled", False):
        day = schedule_data.get("day")
        hour = schedule_data.get("hour")
        minute = schedule_data.get("minute")
        
        if all(x is not None for x in [day, hour, minute]):
            # Check if we missed the scheduled time today
            now = pendulum.now(DEFAULT_TIMEZONE)
            scheduled_time = now.replace(day=day, hour=hour, minute=minute, second=0, microsecond=0)
            
            # If we're past the scheduled day/time this month but haven't sent yet
            last_sent_0 = schedule_data.get("last_sent_0")
            if last_sent_0:
                last_sent_dt = pendulum.parse(last_sent_0)
                # Check if last sent was not this month
                if last_sent_dt.month != now.month or last_sent_dt.year != now.year:
                    # We missed this month's reminder
                    if now.day > day or (now.day == day and now.hour > hour):
                        print(f"[CWL Reminder] Detected missed reminder for this month!")
                        # Ask user if they want to send catch-up reminders
                        print(f"[CWL Reminder] Note: Scheduled time {scheduled_time} has passed.")
                        print(f"[CWL Reminder] Use '/cwl-reminder test-all' if you want to send catch-up reminders.")
            
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


@loader.listener(hikari.StoppingEvent)
async def on_bot_stopping(event: hikari.StoppingEvent) -> None:
    """Shutdown scheduler when bot stops"""
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
        # Get schedule from MongoDB
        schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        
        if not schedule_data or not schedule_data.get("enabled", False):
            await ctx.respond(
                "❌ **No CWL reminder scheduled**\n"
                "Use `/cwl-reminder schedule` to set one up.",
                ephemeral=True
            )
            return
        
        day = schedule_data.get("day", "?")
        hour = schedule_data.get("hour", 0)
        minute = schedule_data.get("minute", 0)
        last_sent = schedule_data.get("last_sent")
        
        # Format time for display
        hour_12 = hour % 12 or 12
        am_pm = "AM" if hour < 12 else "PM"
        
        # Check if job is actually scheduled
        job = scheduler.get_job(cwl_base_job_id)
        job_status = "✅ Active" if job else "❌ Not running"
        
        status_text = (
            f"## CWL Reminder Status\n"
            f"• **Schedule**: Day {day} at {hour_12}:{minute:02d} {am_pm} ({DEFAULT_TIMEZONE})\n"
            f"• **Main CWL Channel**: <#{CWL_CHANNEL_ID}>\n"
            f"• **Lazy CWL Channel**: <#{LAZY_CWL_CHANNEL_ID}>\n"
            f"• **Status**: {job_status}"
        )
        
        if last_sent:
            last_sent_dt = pendulum.parse(last_sent)
            status_text += f"\n• **Last Sent**: {last_sent_dt.format('MMM D, YYYY [at] h:mm A')}"
        
        if job:
            next_run = job.next_run_time
            if next_run:
                next_run_pdt = pendulum.instance(next_run, tz=DEFAULT_TIMEZONE)
                status_text += f"\n• **Next Run**: {next_run_pdt.format('MMM D, YYYY [at] h:mm A')}"
        
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
            await send_cwl_reminder(test_mode=True)
            await ctx.respond(
                f"✅ **Test reminder sent!**\n"
                f"Check <#{TEST_CHANNEL_ID}> to see the message."
            )
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
        
        # Reschedule all reminders
        await reschedule_all_reminders()
        
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
        
        # Get current schedule
        schedule_data = await mongo.database.cwl_reminder.find_one({"_id": "schedule"})
        
        if not schedule_data:
            await ctx.respond("❌ **No reminder configuration found!**")
            return
        
        # Get followups
        followups = schedule_data.get("followups", [])
        
        # Remove the specified follow-up
        original_count = len(followups)
        followups = [f for f in followups if f.get("number") != self.number]
        
        if len(followups) == original_count:
            await ctx.respond(f"❌ **No follow-up reminder #{self.number} found!**")
            return
        
        # Update MongoDB
        await mongo.database.cwl_reminder.update_one(
            {"_id": "schedule"},
            {"$set": {"followups": followups}}
        )
        
        # Remove the scheduled job
        job_id = f"{cwl_followup_job_prefix}{self.number}"
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
        
        # Reschedule remaining reminders
        await reschedule_all_reminders()
        
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
        hour_12 = hour % 12 or 12
        am_pm = "AM" if hour < 12 else "PM"
        
        # Build reminder list
        lines = ["## 📅 CWL Reminder Schedule\n"]
        
        # Initial reminder
        base_time = f"{hour_12}:{minute:02d} {am_pm}"
        lines.append(f"**Initial Reminder**")
        lines.append(f"• Day {day} at {base_time}")
        lines.append(f"• Main Channel: <#{CWL_CHANNEL_ID}>")
        lines.append(f"• Lazy Channel: <#{LAZY_CWL_CHANNEL_ID}>")
        lines.append(f"• Message: CWL Time announcement\n")
        
        # Follow-up reminders
        followups = schedule_data.get("followups", [])
        if followups:
            lines.append("**Follow-up Reminders**")
            
            # Calculate cumulative delays
            current_delay = 0
            base_datetime = pendulum.now(DEFAULT_TIMEZONE).replace(
                day=day, hour=hour, minute=minute, second=0
            )
            
            for followup in sorted(followups, key=lambda x: x.get("number", 0)):
                if followup.get("enabled", True):
                    number = followup.get("number")
                    delay = followup.get("delay_minutes", 0)
                    delay_display = followup.get("delay_display", f"{delay} minutes")
                    current_delay += delay
                    
                    # Calculate actual time
                    followup_time = base_datetime.add(minutes=current_delay)
                    time_str = followup_time.format("h:mm A")
                    
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
        
        # Send initial reminder immediately
        await send_cwl_reminder(0)
        
        # Schedule follow-ups with their actual delays
        base_time = pendulum.now(DEFAULT_TIMEZONE)
        cumulative_delay = 0
        scheduled_count = 0
        
        for followup in sorted(followups, key=lambda x: x.get("number", 0)):
            if followup.get("enabled", True):
                reminder_number = followup.get("number")
                delay_minutes = followup.get("delay_minutes", 0)
                cumulative_delay += delay_minutes
                
                if reminder_number and cumulative_delay > 0:
                    await schedule_followup_reminder(base_time, reminder_number, cumulative_delay)
                    scheduled_count += 1
        
        await ctx.respond(
            f"✅ **Initial reminder sent!**\n"
            f"{scheduled_count} follow-up(s) scheduled with their configured delays.\n"
            f"Check <#{CWL_CHANNEL_ID}> and <#{LAZY_CWL_CHANNEL_ID}> for the messages."
        )


# Register the group with the loader
loader.command(cwl_reminder)