# Channel panel and DM interactions for the FWA sync panel (docs/band-sync-panel.md).
#
# Owns every component builder and register_action handler this brief adds: the one
# channel message per event that lists Going / Maybe / Not going and carries
# Opt in / Maybe / Deny / Open BAND / DM me the time (D003 in DECISIONS.md), plus the
# same buttons and a reminder select carried into a DM (D001, D002).
#
# Deliberately does NOT import extensions.tasks.band_sync_ical - that module imports
# THIS one (to post/replace the panel on discovery and to render DM content from
# deliver_outstanding), so the reverse import would cycle. Everything this module needs
# from Mongo is read directly through the four fwa_sync_* collections.

from dataclasses import dataclass
from datetime import datetime, timezone

import hikari
import lightbulb
from hikari.impl import (
    InteractiveButtonBuilder as Button,
    LinkButtonBuilder as LinkButton,
    MessageActionRowBuilder as ActionRow,
    SelectOptionBuilder as SelectOption,
    TextSelectMenuBuilder as TextSelectMenu,
)

from extensions.components import register_action
from extensions.tasks import band_sync_schema as schema
from utils.band_ical_parser import discord_timestamp, normalize_start
from utils.mongo import MongoClient

PANEL_COLOR = 0x5865F2

STATUS_ANSWER = {
    "in": "You're in. Pick reminders below if you want them.",
    "maybe": "You're marked maybe.",
    "no": "You're marked not going.",
}
STATUS_LINE = {
    "in": "You're in.",
    "maybe": "You're marked maybe.",
    "no": "You're marked not going.",
    None: "You haven't responded yet.",
}
REMINDER_LABEL = {
    "60": "1 hour before",
    "10": "10 minutes before",
    "0": "at sync time",
}
MSG_PASSED = "This sync has passed."
MSG_OPT_IN_FIRST = "Opt in first, then pick your reminders below."

PERMANENT_DM_ERRORS = (
    hikari.BadRequestError,
    hikari.UnauthorizedError,
    hikari.ForbiddenError,
    hikari.NotFoundError,
)

# No lightbulb.Loader here on purpose: this module has no commands or listeners of its
# own, only @register_action handlers, which run at import time. It is not scanned by
# utils/startup.py:load_cogs (that only walks extensions/commands/); it is loaded
# transitively because extensions/tasks/band_sync_ical.py (already in main.py's
# explicit_extensions) imports it.


@dataclass(frozen=True)
class DmSendResult:
    """Mirrors band_sync_ical._DmResult's fields so the poller can wrap this into its
    own retry/backoff bookkeeping without this module importing that one."""
    sent: bool
    permanent: bool = False
    error_type: str = ""
    detail: str = ""


def _error_detail(exc: Exception) -> str:
    return " ".join(str(exc).split())[:300]


# ---- Reads ----
async def event_row(mongo, uid):
    """The normalized fwa_sync_events row for uid, or None if it has passed/never
    existed - the one signal every handler uses for "This sync has passed."."""
    doc = await mongo.fwa_sync_events.find_one({"_id": schema.event_id(uid)})
    return schema.normalize_event(doc) if doc else None


async def config_row(mongo):
    doc = await mongo.fwa_sync_config.find_one({"_id": schema.CONFIG_ID})
    return schema.normalize_config(doc)


def band_url(event, config):
    """event['url'] if the feed ever carries one (utils/band_ical_parser.py does not
    extract one today - see docs/band-sync-panel.md), else the configured fallback."""
    return event.get("url") or config.get("band_url") or "https://www.band.us"


async def load_responses(mongo, uid):
    projection = {"user_id": 1, "status": 1, "reminders": 1,
                  "dm_channel_id": 1, "dm_message_id": 1}
    rows = []
    async for doc in mongo.fwa_sync_responses.find({"uid": uid}, projection).limit(500):
        rows.append(schema.normalize_response(doc))
    return rows


async def response_row(mongo, uid, user_id):
    doc = await mongo.fwa_sync_responses.find_one({"_id": schema.response_id(uid, user_id)})
    return schema.normalize_response(doc) if doc else None


async def upsert_response(mongo, uid, event, user_id, status, reminders):
    """Replace the response doc in place (never appended, per schema.new_response_doc's
    own docstring). Preserves any dm_channel_id/dm_message_id already on file so a
    status change never orphans the DM-replace tracking in D001."""
    existing = await response_row(mongo, uid, user_id)
    doc = schema.new_response_doc(
        uid, user_id, event["start_at"], event["event_version"], status,
        reminders=reminders,
        dm_channel_id=existing.get("dm_channel_id") if existing else None,
        dm_message_id=existing.get("dm_message_id") if existing else None,
        now=datetime.now(timezone.utc),
    )
    await mongo.fwa_sync_responses.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    return doc


async def upsert_dm_only(mongo, uid, event, user_id):
    """Create a response row for a user who has no status yet, purely so send_dm has
    somewhere to store dm_channel_id/dm_message_id. status stays None - "DM me the
    time" is a one-time send, not an RSVP, so it must never mark anyone Not going
    (refuter-03 must-fix 3)."""
    doc = schema.new_response_doc(
        uid, user_id, event["start_at"], event["event_version"], None,
        reminders=[], now=datetime.now(timezone.utc),
    )
    await mongo.fwa_sync_responses.update_one({"_id": doc["_id"]}, {"$set": doc}, upsert=True)
    return doc


# ---- Rendering ----
def _start_of(event):
    """Always run start_at/start through normalize_start(): Mongo hands back a naive
    datetime, the feed hands back an aware one, and Embed(timestamp=...) plus
    discord_timestamp() must agree on the same instant (refuter-03 must-fix 2)."""
    return normalize_start(event.get("start_at", event.get("start")))


def _summary_embed(event, title=None):
    embed = hikari.Embed(
        description=event.get("summary") or "FWA Sync",
        color=PANEL_COLOR,
        timestamp=_start_of(event),
    )
    if title:
        embed.title = title
    start = _start_of(event)
    embed.add_field(
        name="Sync Time",
        value=f"{discord_timestamp(start, 'F')}\n{discord_timestamp(start, 'R')}",
        inline=False,
    )
    return embed


_MENTIONS_MAX_CHARS = 1024  # Discord's hard field-value cap


def _mentions(user_ids) -> str:
    mentions = [f"<@{u}>" for u in user_ids]
    if not mentions:
        return "nobody yet"
    kept = []
    for index, mention in enumerate(mentions):
        candidate = ", ".join([*kept, mention])
        remaining_after = len(mentions) - (index + 1)
        suffix = f" +{remaining_after} more" if remaining_after else ""
        if len(candidate) + len(suffix) > _MENTIONS_MAX_CHARS:
            remaining = len(mentions) - len(kept)
            joined = ", ".join(kept)
            return f"{joined} +{remaining} more" if joined else f"+{remaining} more"
        kept.append(mention)
    return ", ".join(kept)


def panel_embed(event, responses):
    """event is a normalized fwa_sync_events row; responses are this uid's
    normalize_response()'d rows."""
    embed = _summary_embed(event)
    groups = {"in": [], "maybe": [], "no": []}
    for response in responses:
        status = response.get("status")
        # DM-once with no opt-in stores status=None (refuter-03 must-fix 3) - it is not
        # an RSVP, so it must not appear in any of the three groups.
        if status in groups:
            groups[status].append(response["user_id"])
    embed.add_field(name="✅ Going", value=_mentions(groups.get("in", [])), inline=False)
    embed.add_field(name="❔ Maybe", value=_mentions(groups.get("maybe", [])), inline=False)
    embed.add_field(name="❌ Not going", value=_mentions(groups.get("no", [])), inline=False)
    return embed


def dm_embed(event, response, old_start=None):
    if old_start is not None:
        embed = _summary_embed(event, title="⏰ FWA Sync Time CHANGED")
        embed.add_field(name="Was", value=discord_timestamp(normalize_start(old_start), "F"),
                         inline=False)
    else:
        embed = _summary_embed(event)
    status = (response or {}).get("status")
    embed.add_field(name="Your status", value=STATUS_LINE.get(status, STATUS_LINE["no"]),
                     inline=False)
    return embed


def status_rows(uid, url):
    """Row 1 (Opt in / Maybe / Deny / Open BAND / DM me the time) and Row 2 (reminder
    select). Identical shape in the channel panel and every DM.

    The reminder select is always present - components are per-message, not per-user,
    so there is no way to hide it only from users who have not opted in. The handler
    (fwa_sync_reminders) rejects it ephemerally instead.
    """
    row1 = ActionRow(components=[
        Button(style=hikari.ButtonStyle.SUCCESS, custom_id=f"fwa_sync_in:{uid}", label="Opt in"),
        Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"fwa_sync_maybe:{uid}", label="Maybe"),
        Button(style=hikari.ButtonStyle.DANGER, custom_id=f"fwa_sync_no:{uid}", label="Deny"),
        LinkButton(url=url, label="Open BAND"),
        Button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"fwa_sync_dm_once:{uid}",
               label="DM me the time"),
    ])
    row2 = ActionRow(components=[
        TextSelectMenu(
            custom_id=f"fwa_sync_reminders:{uid}",
            placeholder="Reminders (opt in first)…",
            min_values=0,
            max_values=4,
            options=[
                SelectOption(label="1 hour before", value="60"),
                SelectOption(label="10 minutes before", value="10"),
                SelectOption(label="At sync time", value="0"),
                SelectOption(label="All", value="all"),
            ],
        ),
    ])
    return [row1, row2]


# ---- DM delivery (D001: one DM per user per event, replaced not appended) ----
async def send_dm(mongo, bot, event, response, url, delivery_type, old_start=None):
    """Deliver one interactive DM for (uid, user), deleting any previous DM tracked on
    `response` first. `event` needs uid/summary/start_at (or start)/calendar. Never
    raises - failures come back as a DmSendResult so the caller can decide on retry."""
    if not bot:
        return DmSendResult(False, error_type="BotUnavailable",
                            detail="bot instance unavailable")

    user_id = response["user_id"]
    old_channel_id = response.get("dm_channel_id")
    old_message_id = response.get("dm_message_id")
    if old_channel_id and old_message_id:
        try:
            await bot.rest.delete_message(old_channel_id, old_message_id)
        except hikari.NotFoundError:
            pass  # already gone - not an error
        except Exception as exc:
            print(f"[FWA Sync Panel] could not delete previous DM uid={event.get('uid')} "
                  f"user={user_id}: {type(exc).__name__}: {exc}")

    try:
        user = await bot.rest.fetch_user(user_id)
        channel = await bot.rest.create_dm_channel(user.id)
        embed = dm_embed(event, response, old_start)
        rows = status_rows(event["uid"], url)
        message = await bot.rest.create_message(channel=channel, embed=embed, components=rows)
    except Exception as exc:
        return DmSendResult(
            False,
            permanent=isinstance(exc, PERMANENT_DM_ERRORS),
            error_type=type(exc).__name__,
            detail=_error_detail(exc),
        )

    channel_id = int(getattr(channel, "id", channel))
    await mongo.fwa_sync_responses.update_one(
        {"_id": response["_id"]},
        {"$set": {"dm_channel_id": channel_id, "dm_message_id": int(message.id)}},
    )
    return DmSendResult(True)


# ---- Channel panel lifecycle (D003) ----
async def post_or_replace_panel(mongo, bot, event):
    """Post `event`'s panel to the configured channel, deleting whichever OTHER
    event's panel is currently there first (events never overlap across the three
    feeds, D003). No-op if no panel channel is configured or the bot is unavailable.
    `event` is a normalized fwa_sync_events row (already inserted/updated).

    The previous panel's ids come from fwa_sync_config.current_panel, not from the
    event row - the event row that posted it may already be gone by the time the NEXT
    event is discovered (purge_finished_events() deletes it, D003/D013), so the config
    singleton is the only place that survives to tell us what to delete.
    """
    config = await config_row(mongo)
    channel_id = config.get("panel_channel_id")
    if not channel_id or not bot:
        return

    previous = config.get("current_panel") or {}
    if previous.get("uid") != event["uid"]:
        prev_channel = previous.get("channel_id")
        prev_message = previous.get("message_id")
        if prev_channel and prev_message:
            try:
                await bot.rest.delete_message(prev_channel, prev_message)
            except hikari.NotFoundError:
                pass
            except Exception as exc:
                print(f"[FWA Sync Panel] could not delete previous panel "
                      f"uid={previous.get('uid')}: {type(exc).__name__}: {exc}")

    responses = await load_responses(mongo, event["uid"])
    url = band_url(event, config)
    try:
        message = await bot.rest.create_message(
            channel_id, embed=panel_embed(event, responses), components=status_rows(event["uid"], url),
        )
    except Exception as exc:
        print(f"[FWA Sync Panel] could not post panel uid={event['uid']}: "
              f"{type(exc).__name__}: {exc}")
        return
    await mongo.fwa_sync_events.update_one(
        {"_id": event["_id"]},
        {"$set": {
            "panel_channel_id": channel_id,
            "panel_message_id": int(message.id),
            "panel_version": event["event_version"],
        }},
    )
    await mongo.fwa_sync_config.update_one(
        {"_id": schema.CONFIG_ID},
        {"$set": {"current_panel": {
            "uid": event["uid"], "channel_id": channel_id, "message_id": int(message.id),
        }}},
        upsert=True,
    )


async def refresh_panel_message(mongo, bot, event, responses, url):
    """Re-render the channel panel FROM MONGO. Reposts once and re-stores the id if
    the stored message was hand-deleted (NotFound, D003)."""
    channel_id = event.get("panel_channel_id")
    message_id = event.get("panel_message_id")
    if not (channel_id and message_id and bot):
        return
    embed = panel_embed(event, responses)
    rows = status_rows(event["uid"], url)
    try:
        await bot.rest.edit_message(channel_id, message_id, embed=embed, components=rows)
    except hikari.NotFoundError:
        try:
            message = await bot.rest.create_message(channel_id, embed=embed, components=rows)
        except Exception as exc:
            print(f"[FWA Sync Panel] repost after NotFound failed uid={event['uid']}: "
                  f"{type(exc).__name__}: {exc}")
            return
        await mongo.fwa_sync_events.update_one(
            {"_id": event["_id"]},
            {"$set": {
                "panel_message_id": int(message.id),
                "panel_version": event["event_version"],
            }},
        )
        # config.current_panel is the source of truth post_or_replace_panel reads to
        # find "the panel to delete next" (D013) - a repost that only updates the event
        # row leaves current_panel pointing at the hand-deleted message id, orphaning
        # THIS repost once the event row is purged (refuter-04 must-fix).
        await mongo.fwa_sync_config.update_one(
            {"_id": schema.CONFIG_ID},
            {"$set": {"current_panel": {
                "uid": event["uid"], "channel_id": channel_id, "message_id": int(message.id),
            }}},
            upsert=True,
        )
    except Exception as exc:
        print(f"[FWA Sync Panel] panel refresh failed uid={event['uid']}: "
              f"{type(exc).__name__}: {exc}")
        return
    else:
        await mongo.fwa_sync_events.update_one(
            {"_id": event["_id"]}, {"$set": {"panel_version": event["event_version"]}},
        )


# ---- Component handlers ----
async def _answer(ctx, text: str) -> None:
    """A short ephemeral followup. The dispatcher already deferred with edit=True (a
    DEFERRED_MESSAGE_UPDATE ack), which leaves no slot for a second, differently-scoped
    reply - a followup is a separate message and can be ephemeral. Same pattern as
    extensions/tasks/cards_sticky.py:cards_help."""
    try:
        await ctx.interaction.execute(content=text, flags=hikari.MessageFlag.EPHEMERAL)
    except Exception as exc:
        print(f"[FWA Sync Panel] ephemeral reply failed: {type(exc).__name__}: {exc}")


async def _render_after_change(ctx, mongo, bot, uid, event, url, user_id):
    """Edit the message that was actually clicked (channel panel or DM), then, if the
    click came from a DM, also refresh the channel panel - the two are different
    messages and only one of them is `ctx.interaction.message`."""
    responses = await load_responses(mongo, uid)
    if ctx.interaction.guild_id is None:
        my_response = await response_row(mongo, uid, user_id)
        await ctx.respond(embed=dm_embed(event, my_response), components=status_rows(uid, url),
                          edit=True)
        await refresh_panel_message(mongo, bot, event, responses, url)
    else:
        await ctx.respond(embed=panel_embed(event, responses), components=status_rows(uid, url),
                          edit=True)


async def _apply_status(ctx, mongo, bot, uid, status):
    event = await event_row(mongo, uid)
    if event is None:
        await _answer(ctx, MSG_PASSED)
        return

    user_id = int(ctx.user.id)
    reminders = []
    if status == "in":
        existing = await response_row(mongo, uid, user_id)
        if existing and existing.get("status") == "in":
            reminders = existing.get("reminders") or []
    # Any other status clears reminders - they imply attendance (DECISIONS.md D002).
    await upsert_response(mongo, uid, event, user_id, status, reminders)

    config = await config_row(mongo)
    url = band_url(event, config)
    await _render_after_change(ctx, mongo, bot, uid, event, url, user_id)
    await _answer(ctx, STATUS_ANSWER[status])


@register_action("fwa_sync_in", no_return=True)
@lightbulb.di.with_di
async def fwa_sync_in(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "",
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _apply_status(ctx, mongo, bot, action_id, "in")


@register_action("fwa_sync_maybe", no_return=True)
@lightbulb.di.with_di
async def fwa_sync_maybe(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "",
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _apply_status(ctx, mongo, bot, action_id, "maybe")


@register_action("fwa_sync_no", no_return=True)
@lightbulb.di.with_di
async def fwa_sync_no(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "",
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _apply_status(ctx, mongo, bot, action_id, "no")


@register_action("fwa_sync_dm_once", no_return=True)
@lightbulb.di.with_di
async def fwa_sync_dm_once(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "",
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    """One-time DM, no schedule, no opt-in required - available to anyone who clicks
    it. Still goes through send_dm so it replaces any DM already on file (D001)."""
    uid = action_id
    event = await event_row(mongo, uid)
    if event is None:
        await _answer(ctx, MSG_PASSED)
        return

    user_id = int(ctx.user.id)
    response = await response_row(mongo, uid, user_id)
    if response is None:
        response = await upsert_dm_only(mongo, uid, event, user_id)

    config = await config_row(mongo)
    url = band_url(event, config)
    result = await send_dm(mongo, bot, event, response, url, "once")
    if result.sent:
        await _answer(ctx, "Sent - check your DMs.")
    else:
        await _answer(ctx, "Could not DM you - check that your DMs are open to server members.")


@register_action("fwa_sync_reminders", no_return=True)
@lightbulb.di.with_di
async def fwa_sync_reminders(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "",
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    uid = action_id
    event = await event_row(mongo, uid)
    if event is None:
        await _answer(ctx, MSG_PASSED)
        return

    user_id = int(ctx.user.id)
    response = await response_row(mongo, uid, user_id)
    if response is None or response.get("status") != "in":
        await _answer(ctx, MSG_OPT_IN_FIRST)
        return

    values = list(getattr(ctx.interaction, "values", None) or [])
    if "all" in values:
        reminders = [60, 10, 0]
    else:
        reminders = sorted({int(v) for v in values if v != "all"}, reverse=True)
    await upsert_response(mongo, uid, event, user_id, "in", reminders)

    config = await config_row(mongo)
    url = band_url(event, config)
    await _render_after_change(ctx, mongo, bot, uid, event, url, user_id)

    label = ", ".join(REMINDER_LABEL[str(m)] for m in reminders) or "none"
    await _answer(ctx, f"Reminders set: {label}.")
