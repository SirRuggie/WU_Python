import asyncio
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any

import hikari
import lightbulb
import pendulum
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow,
)

from utils.mongo import MongoClient
from utils.constants import RED_ACCENT, GREEN_ACCENT, BLUE_ACCENT, MAGENTA_ACCENT

loader = lightbulb.Loader()

# Configuration
REQUIRED_ROLE_ID = 1060318031575793694
TASK_CHANNEL_ID = 1344445706588389466
AUTO_DELETE_DELAY = 60  # seconds
MAX_TASK_DESCRIPTION_LENGTH = 500
MAX_TASKS_PER_USER = 50
DEFAULT_TIMEZONE = "America/New_York"

# Track pending edit operations
edit_sessions: Dict[int, Dict[str, Any]] = {}

# Track auto-delete tasks
delete_tasks: Dict[int, asyncio.Task] = {}

# Initialize scheduler
scheduler = AsyncIOScheduler(timezone=DEFAULT_TIMEZONE)
scheduler.start()

# Store active reminders
active_reminders: Dict[str, Any] = {}


def create_task_embed(
        title: str,
        description: str,
        color: int = BLUE_ACCENT,
        footer: Optional[str] = None
) -> List[Container]:
    """Create a Components v2 embed for task responses."""
    components = [
        Container(
            accent_color=color,
            components=[
                           Text(content=f"## {title}"),
                           Separator(divider=True),
                           Text(content=description),
                           Media(items=[MediaItem(media="assets/Blue_Footer.png")]),
                       ] + ([Text(content=f"-# {footer}")] if footer else [])
        )
    ]
    return components


def format_task_list(tasks: List[Dict[str, Any]]) -> str:
    """Format tasks for display."""
    if not tasks:
        return "_No tasks in your list._"

    formatted_tasks = []
    for task in sorted(tasks, key=lambda t: t['task_id']):
        task_text = task['description']
        task_id = task['task_id']

        if task['completed']:
            formatted_tasks.append(f"`{task_id}` • ~~{task_text}~~")
        else:
            formatted_tasks.append(f"`{task_id}` • {task_text}")

    return "\n".join(formatted_tasks)


def parse_reminder_time(time_str: str, user_timezone: str = DEFAULT_TIMEZONE) -> Optional[pendulum.DateTime]:
    """Parse various time formats into a datetime object."""
    time_str = time_str.strip().lower()

    # Get current time in user's timezone
    now = pendulum.now(user_timezone)

    # Pattern for relative times (e.g., 5m, 1h, 2d)
    relative_pattern = r'^(\d+)\s*([mhd])$'
    match = re.match(relative_pattern, time_str)

    if match:
        amount = int(match.group(1))
        unit = match.group(2)

        if unit == 'm':
            return now.add(minutes=amount)
        elif unit == 'h':
            return now.add(hours=amount)
        elif unit == 'd':
            return now.add(days=amount)

    # Try parsing with pendulum for natural language
    try:
        if time_str == "tomorrow":
            return now.add(days=1).replace(hour=9, minute=0)
        elif time_str.startswith("tomorrow at "):
            time_part = time_str.replace("tomorrow at ", "")
            parsed_time = pendulum.parse(f"{now.add(days=1).date()} {time_part}", tz=user_timezone)
            return parsed_time

        # Try parsing as absolute time today
        if re.match(r'^\d{1,2}:\d{2}\s*(am|pm)?$', time_str) or re.match(r'^\d{1,2}\s*(am|pm)$', time_str):
            parsed_time = pendulum.parse(f"{now.date()} {time_str}", tz=user_timezone)
            if parsed_time < now:
                parsed_time = parsed_time.add(days=1)
            return parsed_time

        # Try direct parsing
        parsed = pendulum.parse(time_str, tz=user_timezone)
        return parsed

    except:
        return None


async def schedule_message_deletion(
        bot: hikari.GatewayBot,
        message: hikari.Message,
        delay: int = AUTO_DELETE_DELAY
) -> None:
    """Schedule a message for deletion after a delay."""
    try:
        await asyncio.sleep(delay)
        await bot.rest.delete_message(message.channel_id, message.id)
    except hikari.NotFoundError:
        pass
    except Exception:
        pass
    finally:
        if message.id in delete_tasks:
            del delete_tasks[message.id]


async def send_auto_delete_response(
        bot: hikari.GatewayBot,
        channel_id: int,
        components: List[Container]
) -> hikari.Message:
    """Send a response that auto-deletes after configured delay."""
    message = await bot.rest.create_message(
        channel=channel_id,
        components=components
    )

    delete_task = asyncio.create_task(
        schedule_message_deletion(bot, message)
    )
    delete_tasks[message.id] = delete_task

    return message


async def update_task_list_message(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        user_id: int,
        tasks: List[Dict[str, Any]]
) -> Optional[int]:
    """Update or create the task list message in the designated channel."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    message_id = user_data.get("task_list_message_id") if user_data else None

    task_content = format_task_list(tasks)
    completed_count = sum(1 for t in tasks if t['completed'])

    components = [
        Container(
            accent_color=MAGENTA_ACCENT,
            components=[
                Text(content=f"# Ruggie's Tasks"),
                Separator(divider=True),
                Text(content=task_content),
                Separator(divider=True),
                Text(content=f"-# {len(tasks)} total • {completed_count} completed"),
                Media(items=[MediaItem(media="assets/Purple_Footer.png")]),
            ]
        )
    ]

    try:
        if message_id:
            await bot.rest.edit_message(
                channel=TASK_CHANNEL_ID,
                message=message_id,
                components=components
            )
            return message_id
    except (hikari.NotFoundError, hikari.ForbiddenError):
        pass

    try:
        message = await bot.rest.create_message(
            channel=TASK_CHANNEL_ID,
            components=components
        )

        await mongo.user_tasks.update_one(
            {"user_id": str(user_id)},
            {"$set": {"task_list_message_id": message.id}},
            upsert=True
        )

        return message.id
    except Exception:
        return None


async def get_user_tasks(mongo: MongoClient, user_id: int) -> List[Dict[str, Any]]:
    """Get all tasks for a user."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    return user_data.get("tasks", []) if user_data else []


async def renumber_tasks(
        mongo: MongoClient,
        user_id: int,
        tasks: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Renumber tasks to be sequential starting from 1."""
    sorted_tasks = sorted(tasks, key=lambda t: t['task_id'])

    for index, task in enumerate(sorted_tasks, start=1):
        task['task_id'] = index

    next_id = len(sorted_tasks) + 1

    await mongo.user_tasks.update_one(
        {"user_id": str(user_id)},
        {
            "$set": {
                "tasks": sorted_tasks,
                "next_task_id": next_id
            }
        }
    )

    return sorted_tasks


async def add_task(
        mongo: MongoClient,
        user_id: int,
        description: str
) -> Optional[Dict[str, Any]]:
    """Add a new task for a user."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})

    if user_data:
        tasks = user_data.get("tasks", [])
    else:
        tasks = []

    if len(tasks) >= MAX_TASKS_PER_USER:
        return None

    next_id = len(tasks) + 1

    new_task = {
        "task_id": next_id,
        "description": description[:MAX_TASK_DESCRIPTION_LENGTH],
        "completed": False,
        "created_at": datetime.utcnow().isoformat(),
        "completed_at": None
    }

    tasks.append(new_task)

    await mongo.user_tasks.update_one(
        {"user_id": str(user_id)},
        {
            "$set": {
                "tasks": tasks,
                "next_task_id": next_id + 1
            }
        },
        upsert=True
    )

    return new_task


async def delete_task(
        mongo: MongoClient,
        user_id: int,
        task_id: int
) -> bool:
    """Delete a specific task and renumber remaining tasks."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    if not user_data:
        return False

    tasks = user_data.get("tasks", [])
    original_count = len(tasks)

    tasks = [t for t in tasks if t["task_id"] != task_id]

    if len(tasks) == original_count:
        return False

    await renumber_tasks(mongo, user_id, tasks)

    return True


async def complete_task(
        mongo: MongoClient,
        user_id: int,
        task_id: int
) -> bool:
    """Mark a task as completed."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    if not user_data:
        return False

    tasks = user_data.get("tasks", [])
    task_found = False

    for task in tasks:
        if task["task_id"] == task_id:
            task["completed"] = True
            task["completed_at"] = datetime.utcnow().isoformat()
            task_found = True
            break

    if not task_found:
        return False

    await mongo.user_tasks.update_one(
        {"user_id": str(user_id)},
        {"$set": {"tasks": tasks}}
    )

    return True


async def delete_all_tasks(
        mongo: MongoClient,
        user_id: int
) -> int:
    """Delete all tasks for a user."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    if not user_data:
        return 0

    task_count = len(user_data.get("tasks", []))

    await mongo.user_tasks.update_one(
        {"user_id": str(user_id)},
        {"$set": {"tasks": [], "next_task_id": 1}}
    )

    return task_count


async def edit_task(
        mongo: MongoClient,
        user_id: int,
        task_id: int,
        new_description: str
) -> bool:
    """Edit a task's description."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    if not user_data:
        return False

    tasks = user_data.get("tasks", [])
    task_found = False

    for task in tasks:
        if task["task_id"] == task_id:
            task["description"] = new_description[:MAX_TASK_DESCRIPTION_LENGTH]
            task_found = True
            break

    if not task_found:
        return False

    await mongo.user_tasks.update_one(
        {"user_id": str(user_id)},
        {"$set": {"tasks": tasks}}
    )

    return True


async def create_reminder(
        mongo: MongoClient,
        bot: hikari.GatewayBot,
        user_id: int,
        task_id: int,
        reminder_time: pendulum.DateTime,
        user_timezone: str = DEFAULT_TIMEZONE
) -> bool:
    """Create a reminder for a specific task."""
    user_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
    if not user_data:
        return False

    task = next((t for t in user_data.get("tasks", []) if t["task_id"] == task_id), None)
    if not task:
        return False

    reminder_datetime = reminder_time.in_tz(user_timezone).naive()
    reminder_id = f"{user_id}_{task_id}_{int(reminder_time.timestamp())}"

    async def send_reminder():
        try:
            user = await bot.rest.fetch_user(user_id)
            dm_channel = await bot.rest.create_dm_channel(user_id)

            current_data = await mongo.user_tasks.find_one({"user_id": str(user_id)})
            if current_data:
                current_task = next((t for t in current_data.get("tasks", []) if t["task_id"] == task_id), None)
                if current_task and not current_task.get("completed", False):
                    components = [
                        Container(
                            accent_color=BLUE_ACCENT,
                            components=[
                                Text(content="## 🔔 Task Reminder"),
                                Separator(divider=True),
                                Text(content=f"**Task #{task_id}:** {current_task['description']}"),
                                Text(content=f"\nThis task is still pending completion!"),
                                Separator(divider=True),
                                ActionRow(
                                    components=[
                                        Button(
                                            style=hikari.ButtonStyle.SUCCESS,
                                            label="Mark Complete",
                                            custom_id=f"complete_from_reminder:{user_id}_{task_id}",
                                            emoji="✅"
                                        ),
                                        Button(
                                            style=hikari.ButtonStyle.SECONDARY,
                                            label="Snooze 1h",
                                            custom_id=f"snooze_reminder:{user_id}_{task_id}_1h",
                                            emoji="⏰"
                                        )
                                    ]
                                ),
                                Text(
                                    content=f"-# You set this reminder • Task created {current_task['created_at'][:10]}"),
                            ]
                        )
                    ]

                    await bot.rest.create_message(
                        channel=dm_channel.id,
                        components=components
                    )

            if reminder_id in active_reminders:
                del active_reminders[reminder_id]

        except Exception:
            pass

    scheduler.add_job(
        send_reminder,
        trigger=DateTrigger(run_date=reminder_datetime, timezone=user_timezone),
        id=reminder_id,
        replace_existing=True
    )

    active_reminders[reminder_id] = {
        "user_id": user_id,
        "task_id": task_id,
        "reminder_time": reminder_time.isoformat(),
        "description": task["description"]
    }

    await mongo.user_tasks.update_one(
        {"user_id": str(user_id)},
        {
            "$push": {
                "reminders": {
                    "reminder_id": reminder_id,
                    "task_id": task_id,
                    "reminder_time": reminder_time.isoformat(),
                    "created_at": datetime.utcnow().isoformat()
                }
            }
        }
    )

    return True


@loader.listener(hikari.MessageCreateEvent)
async def on_task_command(
        event: hikari.MessageCreateEvent,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Handle task management commands."""
    try:
        if event.is_bot or not event.content:
            return

        content = event.content.strip()

        # Check if user is in a pending edit session
        if event.author_id in edit_sessions:
            session = edit_sessions[event.author_id]
            if session["channel_id"] == event.channel_id:
                task_id = session["task_id"]
                prompt_message_id = session.get("prompt_message_id")
                del edit_sessions[event.author_id]

                if prompt_message_id:
                    try:
                        await bot.rest.delete_message(event.channel_id, prompt_message_id)
                        if prompt_message_id in delete_tasks:
                            delete_tasks[prompt_message_id].cancel()
                            del delete_tasks[prompt_message_id]
                    except:
                        pass

                success = await edit_task(mongo, event.author_id, task_id, content)

                if success:
                    tasks = await get_user_tasks(mongo, event.author_id)
                    await update_task_list_message(bot, mongo, event.author_id, tasks)

                    components = create_task_embed(
                        "✅ Task Updated",
                        f"Task #{task_id} has been updated successfully!",
                        GREEN_ACCENT,
                        "This message will delete in 60 seconds"
                    )
                else:
                    components = create_task_embed(
                        "❌ Edit Failed",
                        f"Could not find task #{task_id} to edit.",
                        RED_ACCENT,
                        "This message will delete in 60 seconds"
                    )

                await send_auto_delete_response(bot, event.channel_id, components)
                return

        # Pattern matching for commands
        add_match = re.match(r'^add task\s+(.+)$', content, re.IGNORECASE)
        del_match = re.match(r'^del task\s+#?(\d+)$', content, re.IGNORECASE)
        complete_match = re.match(r'^complete task\s+#?(\d+)$', content, re.IGNORECASE)
        edit_match = re.match(r'^edit task\s+#?(\d+)$', content, re.IGNORECASE)
        del_all_match = re.match(r'^del all tasks$', content, re.IGNORECASE)
        remind_match = re.match(r'^remind(?:er)?\s+(?:task\s+)?#?(\d+)\s+(.+)$', content, re.IGNORECASE)

        if not any([add_match, del_match, complete_match, edit_match, del_all_match, remind_match]):
            return

        # Check role permission (only in guilds)
        if event.guild_id:
            try:
                member = await bot.rest.fetch_member(event.guild_id, event.author_id)
                if REQUIRED_ROLE_ID not in member.role_ids:
                    components = create_task_embed(
                        "❌ Permission Denied",
                        "You don't have permission to use task commands.",
                        RED_ACCENT,
                        "This message will delete in 60 seconds"
                    )
                    await send_auto_delete_response(bot, event.channel_id, components)
                    return
            except Exception:
                return

        # Process commands
        if add_match:
            description = add_match.group(1).strip()
            task = await add_task(mongo, event.author_id, description)

            if task:
                tasks = await get_user_tasks(mongo, event.author_id)
                await update_task_list_message(bot, mongo, event.author_id, tasks)

                components = create_task_embed(
                    "✅ Task Added",
                    f"Added task #{task['task_id']}: {task['description']}",
                    GREEN_ACCENT,
                    "This message will delete in 60 seconds"
                )
            else:
                components = create_task_embed(
                    "❌ Task Limit Reached",
                    f"You've reached the maximum of {MAX_TASKS_PER_USER} tasks.",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )

            await send_auto_delete_response(bot, event.channel_id, components)

        elif del_match:
            task_id = int(del_match.group(1))
            success = await delete_task(mongo, event.author_id, task_id)

            if success:
                tasks = await get_user_tasks(mongo, event.author_id)
                await update_task_list_message(bot, mongo, event.author_id, tasks)

                components = create_task_embed(
                    "✅ Task Deleted",
                    f"Task #{task_id} has been deleted.",
                    GREEN_ACCENT,
                    "This message will delete in 60 seconds"
                )
            else:
                components = create_task_embed(
                    "❌ Task Not Found",
                    f"Could not find task #{task_id}.",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )

            await send_auto_delete_response(bot, event.channel_id, components)

        elif complete_match:
            task_id = int(complete_match.group(1))
            success = await complete_task(mongo, event.author_id, task_id)

            if success:
                tasks = await get_user_tasks(mongo, event.author_id)
                await update_task_list_message(bot, mongo, event.author_id, tasks)

                components = create_task_embed(
                    "✅ Task Completed",
                    f"Task #{task_id} has been marked as complete!",
                    GREEN_ACCENT,
                    "This message will delete in 60 seconds"
                )
            else:
                components = create_task_embed(
                    "❌ Task Not Found",
                    f"Could not find task #{task_id}.",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )

            await send_auto_delete_response(bot, event.channel_id, components)

        elif edit_match:
            task_id = int(edit_match.group(1))

            tasks = await get_user_tasks(mongo, event.author_id)
            task_exists = any(t["task_id"] == task_id for t in tasks)

            if task_exists:
                components = create_task_embed(
                    "✏️ Edit Task",
                    f"Please type the new description for task #{task_id}:",
                    BLUE_ACCENT,
                    "This message will delete in 60 seconds or when you respond"
                )

                prompt_message = await send_auto_delete_response(bot, event.channel_id, components)

                edit_sessions[event.author_id] = {
                    "task_id": task_id,
                    "channel_id": event.channel_id,
                    "timestamp": datetime.utcnow(),
                    "prompt_message_id": prompt_message.id
                }

                async def cleanup_session():
                    await asyncio.sleep(300)
                    if event.author_id in edit_sessions:
                        if edit_sessions[event.author_id]["task_id"] == task_id:
                            del edit_sessions[event.author_id]

                asyncio.create_task(cleanup_session())
            else:
                components = create_task_embed(
                    "❌ Task Not Found",
                    f"Could not find task #{task_id} to edit.",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )
                await send_auto_delete_response(bot, event.channel_id, components)

        elif del_all_match:
            count = await delete_all_tasks(mongo, event.author_id)

            if count > 0:
                tasks = []
                await update_task_list_message(bot, mongo, event.author_id, tasks)

                components = create_task_embed(
                    "✅ All Tasks Deleted",
                    f"Deleted {count} task{'s' if count != 1 else ''} from your list.",
                    GREEN_ACCENT,
                    "This message will delete in 60 seconds"
                )
            else:
                components = create_task_embed(
                    "ℹ️ No Tasks",
                    "You don't have any tasks to delete.",
                    BLUE_ACCENT,
                    "This message will delete in 60 seconds"
                )

            await send_auto_delete_response(bot, event.channel_id, components)

        elif remind_match:
            task_id = int(remind_match.group(1))
            time_str = remind_match.group(2).strip()

            reminder_time = parse_reminder_time(time_str)

            if not reminder_time:
                components = create_task_embed(
                    "❌ Invalid Time Format",
                    "I couldn't understand that time. Try:\n"
                    "• Relative: `5m`, `1h`, `2d`\n"
                    "• Absolute: `3:30pm`, `tomorrow at 2pm`\n"
                    "• Date: `Dec 25 at 9am`",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )
                await send_auto_delete_response(bot, event.channel_id, components)
                return

            tasks = await get_user_tasks(mongo, event.author_id)
            task_exists = any(t["task_id"] == task_id for t in tasks)

            if not task_exists:
                components = create_task_embed(
                    "❌ Task Not Found",
                    f"Could not find task #{task_id}.",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )
                await send_auto_delete_response(bot, event.channel_id, components)
                return

            success = await create_reminder(
                mongo, bot, event.author_id, task_id,
                reminder_time, DEFAULT_TIMEZONE
            )

            if success:
                reminder_dt = reminder_time
                now = pendulum.now(DEFAULT_TIMEZONE)

                if reminder_dt.date() == now.date():
                    formatted_time = reminder_dt.format("h:mm A")
                    time_desc = f"today at {formatted_time}"
                elif reminder_dt.date() == now.add(days=1).date():
                    formatted_time = reminder_dt.format("h:mm A")
                    time_desc = f"tomorrow at {formatted_time}"
                else:
                    time_desc = reminder_dt.format("MMM D [at] h:mm A")

                components = create_task_embed(
                    "⏰ Reminder Set",
                    f"I'll remind you about task #{task_id} {time_desc}!",
                    GREEN_ACCENT,
                    "This message will delete in 60 seconds"
                )
            else:
                components = create_task_embed(
                    "❌ Reminder Failed",
                    "Could not create the reminder. Please try again.",
                    RED_ACCENT,
                    "This message will delete in 60 seconds"
                )

            await send_auto_delete_response(bot, event.channel_id, components)

    except Exception:
        pass


@loader.listener(hikari.StoppingEvent)
async def cleanup_tasks(event: hikari.StoppingEvent) -> None:
    """Cancel all pending delete tasks and shutdown scheduler on bot shutdown."""
    for task in delete_tasks.values():
        task.cancel()
    delete_tasks.clear()
    edit_sessions.clear()

    scheduler.shutdown()