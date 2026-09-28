"""Durable, per-step walkthrough delivery. Legacy recruit walkthrough is untouched."""

import asyncio
import hashlib
import logging
from datetime import timedelta
from uuid import uuid4
from types import SimpleNamespace
import hikari
from pymongo import ReturnDocument
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    MessageActionRowBuilder as Row,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)
from extensions.commands.tickets import thread_service
from utils.constants import GOLDENROD_ACCENT
from utils.media_urls import GALLERY, optimized
from . import core, content, schema

log = logging.getLogger(__name__)
_task = None
KIND = "warrior_walkthrough"


def run_id(guild, user):
    return f"warrior:{guild}:{user}"


def marker(run, index):
    return (
        int.from_bytes(
            hashlib.sha256(f'{run["token"]}:{index}'.encode()).digest()[:4], "big"
        )
        & 0x7FFFFFFF
    ) or 1


def plan(run):
    clan = run["clan"]
    channel = run["ticket_channel"]
    cfg = run["settings"]
    return [
        (
            channel,
            f'## Welcome to {clan["name"]}! 🎉\nYour recruiter has assigned your clan role. Ask them to begin your server walkthrough when your set-up is ready.',
            0,
        ),
        (
            channel,
            "## 🚀 Walkthrough started\nWe’ll guide you through the important channels for your clan. For members joining multiple clans, the same channel layout applies.",
            0,
        ),
        (
            int(clan["announcement_id"]),
            "**📢 Clan Announcements**\nWar announcements and special instructions will be made here in this channel.",
            10,
        ),
        (int(clan["chat_channel_id"]), content.TEXT_6 + "\n" + content.TEXT_7, 20),
        (int(cfg["channels"]["help"]), content.TEXT_0 + "\n" + content.TEXT_1, 20),
        (int(cfg["channels"]["lounge"]), content.TEXT_2 + "\n" + content.TEXT_3, 20),
        (int(cfg["channels"]["lounge"]), content.TEXT_4 + "\n" + content.TEXT_5, 0),
    ]


def components(run, index):
    text = plan(run)[index][1]
    items = [Text(content=f'<@{run["user_id"]}>\n{text}')]
    if index == 0:
        if run["clan"].get("banner"):
            items.append(
                Media(
                    items=[
                        MediaItem(media=optimized(run["clan"]["banner"], width=GALLERY))
                    ]
                )
            )
        row = Row().add_interactive_button(
            hikari.ButtonStyle.SUCCESS,
            f'warrior_begin:{run["_id"]}',
            label="Begin Walkthrough",
            emoji="🚀",
        )
        row.add_link_button(
            "https://link.clashofclans.com/en/?action=OpenClanProfile&tag="
            + run["clan"]["tag"].replace("#", ""),
            label="Join " + run["clan"]["name"][:65],
        )
        items.append(row)
    if index >= 2:
        items.append(Media(items=[MediaItem(media="assets/Red_Footer.png")]))
    return [
        Container(
            id=marker(run, index), accent_color=GOLDENROD_ACCENT, components=items
        )
    ]


def has_marker(message, wanted, bot_id):
    return int(message.author.id) == int(bot_id) and any(
        int(getattr(c, "id", 0) or 0) == wanted for c in message.components
    )


async def validate_destination(bot, c, channel_id):
    channel = await bot.rest.fetch_channel(channel_id)
    if int(channel.guild_id) != int(c["guild"].id):
        raise core.SetupError(
            "A walkthrough destination belongs to a different server."
        )
    parent = (
        await bot.rest.fetch_channel(channel.parent_id)
        if isinstance(channel, hikari.GuildThreadChannel)
        else channel
    )
    member_permissions = thread_service._effective_permissions(
        guild_id=c["guild"].id,
        owner_id=c["guild"].owner_id,
        member=c["member"],
        roles=c["roles"],
        channel=parent,
    )
    if (
        not member_permissions & hikari.Permissions.VIEW_CHANNEL
        or not member_permissions & hikari.Permissions.READ_MESSAGE_HISTORY
    ):
        raise core.SetupError(
            f"The member cannot read <#{channel_id}>. Fix access before continuing."
        )
    bot_permissions = thread_service._effective_permissions(
        guild_id=c["guild"].id,
        owner_id=c["guild"].owner_id,
        member=c["me"],
        roles=c["roles"],
        channel=parent,
    )
    required = hikari.Permissions.VIEW_CHANNEL | hikari.Permissions.READ_MESSAGE_HISTORY
    required |= (
        hikari.Permissions.SEND_MESSAGES_IN_THREADS
        if isinstance(channel, hikari.GuildThreadChannel)
        else hikari.Permissions.SEND_MESSAGES
    )
    if bot_permissions & required != required:
        raise core.SetupError(f"The bot cannot read and send in <#{channel_id}>.")


async def prepare(bot, mongo, c, clan, cfg):
    ticket = await core.open_ticket(mongo, c["guild"].id, c["member"].id)
    if int(clan["role_id"]) not in c["member"].role_ids:
        raise core.SetupError(
            "Assign this clan’s role before starting its walkthrough."
        )
    if not clan.get("announcement_id") or not clan.get("chat_channel_id"):
        raise core.SetupError(
            "This clan needs announcement and chat channel IDs configured."
        )
    run = {
        "_id": run_id(c["guild"].id, c["member"].id),
        "schema_version": schema.SCHEMA_VERSION,
        "kind": KIND,
        "guild_id": int(c["guild"].id),
        "user_id": int(c["member"].id),
        "actor_id": int(c["actor"].id),
        "ticket_id": ticket["_id"],
        "ticket_channel": int(ticket["location"]["id"]),
        "clan": {
            k: clan.get(k)
            for k in (
                "name",
                "tag",
                "role_id",
                "announcement_id",
                "chat_channel_id",
                "banner",
            )
        },
        "settings": cfg,
        "token": uuid4().hex,
        "started_at": core.now(),
        "state": "preparing",
        "next_step": 0,
        "due_at": core.now(),
        "messages": {},
        "cleanup_done": False,
    }
    for channel_id in set(item[0] for item in plan(run)):
        await validate_destination(bot, c, channel_id)
    await thread_service.ensure_candidate_thread_access(
        bot.rest, ticket, user_id=c["member"].id
    )
    existing = await mongo.warrior_walkthroughs.find_one({"_id": run["_id"]})
    if existing:
        if existing.get("state") == "complete":
            raise core.SetupError(
                "This member’s walkthrough is already complete. Use Advanced to explicitly restart it."
            )
        return existing
    try:
        await mongo.warrior_walkthroughs.insert_one(run)
    except Exception:
        existing = await mongo.warrior_walkthroughs.find_one({"_id": run["_id"]})
        if existing:
            return existing
        raise
    return run


async def begin(bot, mongo, run, actor_id, channel_id):
    if int(run["ticket_channel"]) != int(channel_id):
        raise core.SetupError("Use Begin Walkthrough in the recruit’s ticket.")
    c = await core.context(bot, mongo, run["guild_id"], actor_id, run["user_id"])
    ticket = await core.open_ticket(mongo, run["guild_id"], run["user_id"])
    if ticket["_id"] != run["ticket_id"]:
        raise core.SetupError(
            "The original ticket is no longer open. Start from /warrior in the current ticket."
        )
    updated = await mongo.warrior_walkthroughs.find_one_and_update(
        {"_id": run["_id"], "token": run["token"], "state": "awaiting"},
        {
            "$set": {
                "state": "running",
                "actor_id": int(c["actor"].id),
                "due_at": core.now(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    return updated is not None


async def deliver(bot, mongo, run, owner):
    index = int(run["next_step"])
    steps = plan(run)
    channel_id, _, _ = steps[index]
    c = await core.context(bot, mongo, run["guild_id"], run["actor_id"], run["user_id"])
    if index <= 1:
        ticket = await core.open_ticket(mongo, run["guild_id"], run["user_id"])
        if ticket["_id"] != run["ticket_id"]:
            raise core.SetupError("The walkthrough’s ticket is no longer open.")
    await validate_destination(bot, c, channel_id)
    # If a process stopped after sending but before saving, recognize its own
    # component marker. Never resend completed stages or scan before this run.
    found = None
    step_started = run.get("step_started_at") or core.now()
    if not run.get("step_started_at"):
        await mongo.warrior_walkthroughs.update_one(
            {"_id": run["_id"], "token": run["token"], "lease_owner": owner},
            {"$set": {"step_started_at": step_started}},
        )
    async for message in bot.rest.fetch_messages(
        channel_id, after=hikari.Snowflake.from_datetime(core.aware(step_started))
    ):
        if has_marker(message, marker(run, index), bot.get_me().id):
            found = message
            break
    if found is None:
        found = await bot.rest.create_message(
            channel_id,
            components=components(run, index),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2,
            user_mentions=[run["user_id"]],
            role_mentions=False,
            mentions_everyone=False,
        )
    nxt = index + 1
    state = (
        "awaiting" if index == 0 else ("complete" if nxt == len(steps) else "running")
    )
    values = {
        "next_step": nxt,
        "state": state,
        f"messages.{index}": int(found.id),
        "error": None,
        "due_at": core.now()
        + timedelta(seconds=steps[nxt][2] if nxt < len(steps) else 0),
    }
    if state == "complete":
        values.update(
            completed_at=core.now(), cleanup_at=core.now() + timedelta(hours=2)
        )
    await mongo.warrior_walkthroughs.update_one(
        {"_id": run["_id"], "token": run["token"], "lease_owner": owner},
        {
            "$set": values,
            "$unset": {"lease_owner": "", "lease_until": "", "step_started_at": ""},
        },
    )


async def sweep(bot, mongo):
    rows = (
        await mongo.warrior_walkthroughs.find(
            {
                "kind": KIND,
                "state": {"$in": ["preparing", "running"]},
                "due_at": {"$lte": core.now()},
            }
        )
        .limit(25)
        .to_list(length=25)
    )
    for row in rows:
        owner = uuid4().hex
        run = await mongo.warrior_walkthroughs.find_one_and_update(
            {
                "_id": row["_id"],
                "token": row["token"],
                "state": row["state"],
                "$or": [
                    {"lease_until": {"$exists": False}},
                    {"lease_until": {"$lte": core.now()}},
                ],
            },
            {
                "$set": {
                    "lease_owner": owner,
                    "lease_until": core.now() + timedelta(minutes=3),
                }
            },
            return_document=ReturnDocument.AFTER,
        )
        if not run:
            continue
        try:
            # Finish or pause before the durable lease expires. An ambiguous send
            # is found by its marker when a recruiter retries the paused step.
            await asyncio.wait_for(deliver(bot, mongo, run, owner), timeout=120)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.exception(
                "warrior walkthrough paused run=%s step=%s",
                run["_id"],
                run["next_step"],
            )
            await mongo.warrior_walkthroughs.update_one(
                {"_id": run["_id"], "lease_owner": owner},
                {
                    "$set": {"state": "paused", "error": str(error)[:500]},
                    "$unset": {"lease_owner": "", "lease_until": ""},
                },
            )
    # The legacy cleanup remains untouched. New runs remove their configured
    # New Recruit role two hours after successfully finishing the tour.
    complete = (
        await mongo.warrior_walkthroughs.find(
            {
                "kind": KIND,
                "state": "complete",
                "cleanup_done": False,
                "cleanup_at": {"$lte": core.now()},
            }
        )
        .limit(25)
        .to_list(length=25)
    )
    for run in complete:
        try:
            role = int(run["settings"]["roles"]["recruit"])
            await bot.rest.remove_role_from_member(
                run["guild_id"],
                run["user_id"],
                role,
                reason="Warrior walkthrough completed over two hours ago",
            )
            await mongo.warrior_walkthroughs.update_one(
                {"_id": run["_id"], "token": run["token"]},
                {"$set": {"cleanup_done": True}},
            )
        except Exception as error:
            log.exception("warrior recruit-role cleanup pending run=%s", run["_id"])
            await mongo.warrior_walkthroughs.update_one(
                {"_id": run["_id"], "token": run["token"]},
                {
                    "$set": {
                        "cleanup_at": core.now() + timedelta(hours=1),
                        "cleanup_error": type(error).__name__,
                    }
                },
            )


async def loop(bot, mongo):
    indexed = False
    while True:
        try:
            if not indexed:
                await schema.migrate_early_records(mongo)
                await mongo.warrior_walkthroughs.create_index(
                    [("kind", 1), ("state", 1), ("due_at", 1)], name="warrior_progress"
                )
                await mongo.warrior_walkthroughs.create_index(
                    [("kind", 1), ("state", 1), ("cleanup_done", 1), ("cleanup_at", 1)],
                    name="warrior_cleanup",
                )
                await mongo.warrior_history.create_index(
                    [("guild_id", 1), ("user_id", 1), ("completed_at", -1)],
                    name="warrior_member_history",
                )
                indexed = True
                log.info("Warrior walkthrough worker ready")
            await sweep(bot, mongo)
        except Exception:
            log.exception("warrior walkthrough worker failed")
        await asyncio.sleep(5)


def start(bot, mongo):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(loop(bot, mongo), name="warrior-walkthrough")


async def stop():
    global _task
    if _task:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
