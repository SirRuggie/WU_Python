"""Durable seven-day recruiter reminders for live candidate conversations."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import hikari
import lightbulb
from pymongo import ReturnDocument
from hikari.impl import ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text

from extensions.commands.tickets import store, perms, flag_store, resolve, testing_service
from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient

_log = logging.getLogger(__name__)
PERIOD = timedelta(days=7)
LEASE = timedelta(minutes=5)
SEND_TIMEOUT_SECONDS = 60
PROMPT = "There has been no activity within the last 7 days. Apply Ghosted and deny?"
REASON = "Recruit stopped responding"
YES_EMOJI = 1397096942907166831
NO_EMOJI = 1397096986506825778
_task: asyncio.Task | None = None


def now():
    return datetime.now(timezone.utc)


def aware(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def configured_period(config):
    """Persistent override for operator testing; absence means seven days."""
    try:
        minutes = int(config.get("ticket_inactivity_minutes", 10080))
    except (TypeError, ValueError):
        return PERIOD
    return timedelta(minutes=minutes) if 1 <= minutes <= 525600 else PERIOD


def period_label(period):
    minutes = int(period.total_seconds() // 60)
    amount, unit = (minutes // 1440, "day") if minutes % 1440 == 0 else (minutes, "minute")
    return f"{amount} {unit}{'' if amount == 1 else 's'}"


def activity_baseline(ticket):
    state = ticket.get("inactivity") or {}
    return max(value for value in (
        aware(state.get("last_human_at")), aware(state.get("reset_at")),
        aware(ticket.get("created_at")),
    ) if value is not None)


def eligible(ticket):
    return bool(ticket and all(ticket.get(k) == v for k, v in store.RUNTIME_FILTER.items())
                and ticket.get("status") == "open" and not ticket.get("thread_missing")
                and not testing_service.is_test_ticket(ticket))


def staff_id(ticket):
    return store.as_int((ticket.get("location") or {}).get("staff_space_id") or ticket.get("thread_id"))


def custom_id(ticket, token, choice):
    return f"ticket_inactivity:{ticket['_id']}:{token}:{choice}"


def card(ticket, token, role, period=PERIOD):
    row = hikari.impl.MessageActionRowBuilder()
    for choice, label, emoji in (("yes", "Yes", YES_EMOJI), ("no", "No", NO_EMOJI)):
        row.add_interactive_button(hikari.ButtonStyle.SECONDARY, custom_id(ticket, token, choice), label=label, emoji=hikari.CustomEmoji(id=emoji, name=label, is_animated=False))
    wording = f"There has been no activity within the last {period_label(period)}. Apply Ghosted and deny?"
    return [Container(accent_color=GOLDENROD_ACCENT, components=[Text(content=f"## Inactivity review · {period_label(period)}\n<@&{role}> · <#{ticket['location']['id']}>\n\n{wording}\n\nDenial reason: **{REASON}**"), row])]


async def record_human_activity(mongo, ticket, message):
    """Any human message in the candidate conversation invalidates the prompt."""
    if not eligible(ticket) or testing_service.is_test_scope(mongo):
        return False
    at = aware(message.timestamp) or now()
    result = await mongo.tickets.update_one({"_id": ticket["_id"], **store.RUNTIME_FILTER, "status": "open",
        "$or": [{"inactivity.last_human_at": {"$lt": at}}, {"inactivity.last_human_at": {"$exists": False}}]},
        {"$max": {"inactivity.last_human_at": at}, "$set": {"inactivity.baseline_verified": True},
         "$unset": {"inactivity.prompt": ""}, "$inc": {"activity_revision": 1}})
    return bool(result.modified_count)


async def retire_prompt(bot, ticket, wording):
    prompt = (ticket.get("inactivity") or {}).get("prompt") or {}
    if not prompt.get("message_id") or not staff_id(ticket):
        return
    try:
        await bot.rest.edit_message(staff_id(ticket), int(prompt["message_id"]),
            components=[Container(accent_color=GOLDENROD_ACCENT, components=[Text(content=wording)])],
            mentions_everyone=False, role_mentions=False, user_mentions=False)
    except Exception:
        _log.warning("could not retire inactivity prompt ticket=%s", ticket.get("_id"), exc_info=True)


async def verify_baseline(bot, mongo, ticket):
    """Fail closed if a bounded history scan cannot establish human activity."""
    latest = None
    count = 0
    async for message in bot.rest.fetch_messages(int(ticket["location"]["id"])).limit(500):
        count += 1
        if not message.author.is_bot and not getattr(message, "webhook_id", None):
            latest = aware(message.timestamp)
            break
    if latest is None and count >= 500:
        return None
    latest = latest or aware(ticket.get("created_at")) or now()
    previous = aware((ticket.get("inactivity") or {}).get("last_human_at"))
    if previous is None or latest > previous:
        changed = await record_human_activity(mongo, ticket, SimpleMessage(latest))
        if changed and (ticket.get("inactivity") or {}).get("prompt"):
            await retire_prompt(bot, ticket, "New conversation activity reset the inactivity timer.")
        return await mongo.tickets.find_one({"_id": ticket["_id"], **store.RUNTIME_FILTER, "status": "open"})
    revision = int(ticket.get("activity_revision") or 0)
    return await mongo.tickets.find_one_and_update({"_id": ticket["_id"], **store.RUNTIME_FILTER,
        "status": "open", "activity_revision": store._rev_filter(revision)},
        {"$max": {"inactivity.last_human_at": latest}, "$set": {"inactivity.baseline_verified": True}},
        return_document=ReturnDocument.AFTER)


class SimpleMessage:
    def __init__(self, timestamp):
        self.timestamp = timestamp


def _message_has_id(message, wanted):
    def walk(items):
        for item in items or ():
            if getattr(item, "custom_id", None) == wanted:
                return True
            if walk(getattr(item, "components", ())):
                return True
        return False
    return walk(getattr(message, "components", ()))


async def publish_prompt(bot, mongo, ticket, config):
    state = ticket.get("inactivity") or {}
    baseline = activity_baseline(ticket)
    period = configured_period(config)
    if now() - baseline < period:
        return
    role = store.as_int(config.get(f"{ticket.get('ticket_type')}_thread_recruiter_role"))
    channel = staff_id(ticket)
    if not role or not channel:
        return
    prompt = state.get("prompt") or {}
    if prompt.get("state") == "ready" or prompt.get("state") == "yes":
        return
    token = prompt.get("token") or uuid4().hex[:16]
    owner = uuid4().hex
    stamp = now()
    revision = int(ticket.get("activity_revision") or 0)
    query = {"_id": ticket["_id"], **store.RUNTIME_FILTER, "status": "open", "activity_revision": store._rev_filter(revision)}
    if prompt:
        query.update({"inactivity.prompt.token": token, "inactivity.prompt.lease_until": {"$lte": stamp}})
    else:
        query["inactivity.prompt"] = {"$exists": False}
    claimed = await mongo.tickets.find_one_and_update(query, {"$set": {"inactivity.prompt": {
        "token": token, "state": "sending", "owner": owner, "lease_until": stamp + LEASE,
        "started_at": prompt.get("started_at") or stamp, "activity_revision": revision}}}, return_document=ReturnDocument.AFTER)
    if not claimed:
        return
    # A crashed send is recovered from the exact durable token, never guessed
    # from wording. Refuse to send again if bounded history is inconclusive.
    message = None
    if prompt:
        scanned = 0
        me = bot.get_me()
        if me is None:
            return
        started = aware(prompt.get("started_at"))
        async for candidate in bot.rest.fetch_messages(channel).limit(100):
            scanned += 1
            if int(candidate.author.id) == int(me.id) and _message_has_id(candidate, custom_id(ticket, token, "yes")):
                message = candidate
                break
            if started and aware(candidate.timestamp) < started:
                break
        else:
            if scanned >= 100:
                return
    # query contained the pre-claim prompt; use the claim identity after mutation.
    current = await mongo.tickets.find_one({"_id": ticket["_id"], "status": "open", "inactivity.prompt.owner": owner})
    if current is None:
        return
    if message is None:
        # Hikari sends enforce_nonce=True with a supplied nonce. Keep the same
        # nonce across recovery and bound the request below the send lease so
        # another worker cannot reclaim it while this sender is still waiting.
        message = await asyncio.wait_for(
            bot.rest.create_message(
                channel, components=card(ticket, token, role, period),
                flags=hikari.MessageFlag.IS_COMPONENTS_V2,
                nonce=f"inact-{token}", role_mentions=[role],
                user_mentions=False, mentions_everyone=False,
            ),
            timeout=SEND_TIMEOUT_SECONDS,
        )
    await mongo.tickets.update_one({"_id": ticket["_id"], "status": "open", "inactivity.prompt.owner": owner},
        {"$set": {"inactivity.prompt.state": "ready", "inactivity.prompt.message_id": int(message.id)}})


async def finish_ghosted(bot, mongo, ticket):
    prompt = (ticket.get("inactivity") or {}).get("prompt") or {}
    if prompt.get("state") != "yes" or not prompt.get("token"):
        return False
    # Only our won denial may author the independent permanent flag. The
    # decision CAS is durable even if the process died before deny returned.
    won = next((entry for entry in ticket.get("audit", ())
                if entry.get("inactivity_token") == prompt.get("token") and entry.get("to") == "denied"), None)
    if won is None:
        return False
    ids = flag_store._discord_ids(ticket.get("user_id"))
    tags = ticket.get("player_tags") or ()
    async with flag_store.identity_guard(mongo, discord_ids=ids, player_tags=tags):
        existing = await mongo.ticket_flags.find({"kind": flag_store.FLAG_GHOSTED, "active": True,
            "$or": flag_store._identity_query(ids, list(tags))}).limit(2).to_list(length=2)
        flag_doc = existing[0] if existing else None
        if not existing:
            flag_doc = await flag_store._set_flag_unlocked(mongo, kind=flag_store.FLAG_GHOSTED, discord_ids=ids,
                player_tags=tags, source="Recruiter confirmed ticket inactivity",
                added_by=won["actor"], added_by_name=won.get("actor_name") or str(won["actor"]), reason=REASON)
    from extensions.commands.tickets import thread_service, console
    await console._refresh_after_flag_mutation(bot, mongo, flag_doc)
    await thread_service.notify_console_after_change(bot, mongo, ticket, reason="Ghosted inactivity flag")
    await retire_prompt(bot, ticket, "Ghosted applied and ticket denied: Recruit stopped responding.")
    await mongo.tickets.update_one({"_id": ticket["_id"], "inactivity.prompt.token": prompt["token"]},
        {"$set": {"inactivity.prompt.state": "complete"}})
    return True


@register_action("ticket_inactivity", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def handle_inactivity(ctx, action_id: str, bot: hikari.GatewayBot = lightbulb.di.INJECTED,
                            mongo: MongoClient = lightbulb.di.INJECTED, **_kwargs):
    await ctx.defer(ephemeral=True)
    if not await perms.is_recruiter(ctx.member, mongo) or testing_service.is_test_scope(mongo):
        await ctx.interaction.edit_initial_response(content="Recruiter permission required.")
        return
    parts = action_id.split(":")
    if len(parts) != 3 or parts[2] not in {"yes", "no"}:
        await ctx.interaction.edit_initial_response(content="This inactivity prompt is out of date.")
        return
    ticket_id, token, choice = parts
    ticket = await mongo.tickets.find_one({"_id": ticket_id, **store.RUNTIME_FILTER})
    if eligible(ticket):
        ticket = await verify_baseline(bot, mongo, ticket)
    prompt = ((ticket or {}).get("inactivity") or {}).get("prompt") or {}
    source = getattr(ctx.interaction, "message", None)
    if (not eligible(ticket) or prompt.get("token") != token or prompt.get("state") != "ready"
        or staff_id(ticket) != int(ctx.channel_id) or int(ticket.get("guild_id") or 0) != int(ctx.guild_id)
        or store.as_int(getattr(source, "id", 0)) != store.as_int(prompt.get("message_id"))):
        await ctx.interaction.edit_initial_response(content="This inactivity prompt is out of date.")
        return
    if not await perms.is_recruiter(ctx.member, mongo):
        await ctx.interaction.edit_initial_response(content="Recruiter permission required.")
        return
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    if now() - activity_baseline(ticket) < configured_period(config):
        await ctx.interaction.edit_initial_response(content="This ticket is not due for inactivity review under the current timer.")
        return
    query = {"_id": ticket_id, **store.RUNTIME_FILTER, "status": "open", "inactivity.prompt.token": token,
        "inactivity.prompt.state": "ready", "activity_revision": store._rev_filter(int(prompt.get("activity_revision") or 0))}
    if choice == "no":
        result = await mongo.tickets.update_one(query, {"$set": {"inactivity.reset_at": now()}, "$unset": {"inactivity.prompt": ""}})
        wording = "The inactivity timer has been reset." if result.modified_count else "This inactivity prompt is out of date."
    else:
        actor_name = str(getattr(ctx.user, "display_name", None) or getattr(ctx.user, "username", None) or ctx.user.id)
        claimed = await mongo.tickets.find_one_and_update(query, {"$set": {"inactivity.prompt.state": "yes",
            "inactivity.prompt.actor_id": int(ctx.user.id), "inactivity.prompt.actor_name": actor_name,
            "inactivity.prompt.expected_rev": int(ticket.get("rev") or 0),
            "inactivity.prompt.lease_until": now() + LEASE}}, return_document=ReturnDocument.AFTER)
        if not claimed:
            wording = "This inactivity prompt is out of date."
        else:
            result = await resolve.deny_ticket(bot, mongo, ticket_id=ticket_id, member=ctx.member,
                actor_name=actor_name, kind=resolve.KIND_DENY_CUSTOM, reason=REASON,
                expected_rev=int(ticket.get("rev") or 0), expected_activity_revision=int(prompt.get("activity_revision") or 0),
                expected_inactivity_token=token)
            if result.won or result.outcome == store.EFFECT_FAILED:
                try:
                    complete = await finish_ghosted(bot, mongo, result.doc)
                except Exception:
                    _log.exception("Ghosted flag pending after won inactivity denial ticket=%s", ticket_id)
                    complete = False
                wording = ("Ghosted applied and ticket denied: Recruit stopped responding." if complete else
                           "Ticket denied; Ghosted flag update is pending and will retry automatically.")
            else:
                await mongo.tickets.update_one({"_id": ticket_id, "inactivity.prompt.token": token}, {"$unset": {"inactivity.prompt": ""}})
                wording = "The ticket changed; no inactivity denial was applied."
    await retire_prompt(bot, ticket, wording)
    await ctx.interaction.edit_initial_response(content=wording)


async def sweep(bot, mongo, *, after=None, limit=50):
    if testing_service.is_test_scope(mongo):
        return None
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    query = {**store.RUNTIME_FILTER, "guild_id": store.as_int(config.get("ticket_target_guild_id")), "$or": [{"status": "open"}, {"inactivity.prompt.state": {"$in": ["yes", "ready"]}}]}
    if after is not None:
        query["_id"] = {"$gt": after}
    tickets = await mongo.tickets.find(query).sort("_id", 1).limit(limit).to_list(length=limit)
    for ticket in tickets:
        try:
            if testing_service.is_test_ticket(ticket):
                continue
            await finish_ghosted(bot, mongo, ticket)
            if not eligible(ticket):
                terminal_prompt = (ticket.get("inactivity") or {}).get("prompt") or {}
                if terminal_prompt.get("state") == "ready":
                    await retire_prompt(bot, ticket, "This ticket has already been resolved. The inactivity prompt is out of date.")
                    await mongo.tickets.update_one({"_id": ticket["_id"], "status": {"$ne": "open"},
                        "inactivity.prompt.token": terminal_prompt["token"], "inactivity.prompt.state": "ready"},
                        {"$set": {"inactivity.prompt.state": "stale"}})
                continue
            prompt = (ticket.get("inactivity") or {}).get("prompt") or {}
            if prompt.get("state") == "yes":
                if (aware(prompt.get("lease_until")) or now()) > now():
                    continue
                # An interrupted pre-decision click requires a fresh recruiter
                # confirmation; never resolve a ticket from stale authority.
                await mongo.tickets.update_one({"_id": ticket["_id"], "status": "open", "inactivity.prompt.token": prompt["token"]},
                    {"$set": {"inactivity.prompt.state": "ready"}})
                continue
            state = ticket.get("inactivity") or {}
            baseline = activity_baseline(ticket)
            if not state.get("baseline_verified") or now() - baseline >= configured_period(config):
                ticket = await verify_baseline(bot, mongo, ticket)
                if ticket is None:
                    continue
            await publish_prompt(bot, mongo, ticket, config)
        except Exception:
            _log.exception("ticket inactivity recovery failed ticket=%s", ticket.get("_id"))
    return tickets[-1]["_id"] if len(tickets) == limit else None


async def _run(bot, mongo):
    after = None
    while True:
        try:
            from extensions.commands.tickets import thread_intake_ready
            if thread_intake_ready():
                after = await sweep(bot, mongo, after=after)
        except Exception:
            _log.exception("ticket inactivity sweep failed")
        await asyncio.sleep(10 if after is not None else 60)


def start(bot, mongo):
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_run(bot, mongo), name="ticket-inactivity")


async def stop():
    global _task
    if _task is not None:
        _task.cancel()
        await asyncio.gather(_task, return_exceptions=True)
        _task = None
