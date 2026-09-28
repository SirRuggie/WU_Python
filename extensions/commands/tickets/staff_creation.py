"""Private, recruiter-owned ticket setup from the shared console."""

from datetime import datetime, timedelta, timezone
import uuid
import logging
from types import SimpleNamespace
from utils.ticket_testing_context import test_dependencies
from utils.ticket_testing_control import require_test_access

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    LinkButtonBuilder as Link,
    MessageActionRowBuilder as Row,
    InteractiveButtonBuilder as Button,
    TextSelectMenuBuilder as Select,
    SelectOptionBuilder as Option,
)
from extensions.commands import ticket_runtime
from extensions.commands.tickets import (
    console,
    perms,
    store,
    testing_service,
    thread_service,
    thread_intake_ready,
)
from extensions.components import register_action
from utils.component_state import get_state, insert_state, update_state
from utils.mongo import MongoClient
from utils.constants import GOLDENROD_ACCENT


def panel(state):
    key = state["_id"]
    # Discord's native user menu provides searchable guild member selection.
    users = Row().add_select_menu(
        hikari.ComponentType.USER_SELECT_MENU,
        f"ticket_v2_staff_pick:{key}|user",
        placeholder="Search for a recruit",
        min_values=1,
        max_values=1,
    )
    heading = "## Create for Recruit\nChoose a recruit, clan type, and ticket mode.\nLive tickets count normally. Isolated test tickets are excluded."
    if state.get("recruit_id"):
        heading += f"\nSelected recruit: <@{state['recruit_id']}>"
    type_menu = Select(
        custom_id=f"ticket_v2_staff_pick:{key}|type",
        placeholder="Choose Main or FWA",
        min_values=1,
        max_values=1,
        options=[
            Option(
                label=label, value=value, is_default=state.get("ticket_type") == value
            )
            for label, value in [("Main", "main"), ("FWA", "fwa")]
        ],
    )
    mode_menu = Select(
        custom_id=f"ticket_v2_staff_pick:{key}|mode",
        placeholder="Ticket mode",
        min_values=1,
        max_values=1,
        options=[
            Option(
                label=label, value=value, is_default=state.get("mode", "live") == value
            )
            for label, value in [("Live", "live"), ("Isolated test", "test")]
        ],
    )
    actions = Row(
        components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=f"ticket_v2_staff_submit:{key}",
                label="Create Ticket",
                is_disabled=not (state.get("recruit_id") and state.get("ticket_type")),
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"ticket_v2_staff_cancel:{key}",
                label="Cancel",
            ),
        ]
    )
    return [
        Container(
            accent_color=GOLDENROD_ACCENT,
            components=[
                Text(content=heading),
                users,
                Row(components=[type_menu]),
                Row(components=[mode_menu]),
                actions,
            ],
        )
    ]


async def owned_state(ctx, mongo, key):
    state = await get_state(mongo, key)
    if (
        not state
        or state.get("type") != "staff_ticket_setup"
        or state.get("owner_id") != int(ctx.user.id)
        or state.get("guild_id") != int(ctx.guild_id or 0)
        or state.get("closed")
    ):
        return None
    if not await perms.is_recruiter(getattr(ctx, "member", None), mongo):
        return None
    return state


async def notice(ctx, text):
    await ctx.interaction.edit_initial_response(
        content=None,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
        components=[
            Container(accent_color=GOLDENROD_ACCENT, components=[Text(content=text)])
        ],
    )


@register_action(
    "ticket_v2_staff_create", opens_modal=True, no_return=True, preload_state=False
)
@lightbulb.di.with_di
async def open_setup(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
):
    await ctx.defer(ephemeral=True)
    hub = await console._hub_state(mongo)
    if (
        action_id != "hub"
        or int(ctx.guild_id or 0) != store.as_int(hub.get("guild_id"))
        or not console._is_shared_actions_source(ctx, hub)
        or not await perms.is_recruiter(getattr(ctx, "member", None), mongo)
    ):
        await notice(
            ctx, "Recruiter access from the current shared console is required."
        )
        return
    state = {
        "_id": uuid.uuid4().hex,
        "type": "staff_ticket_setup",
        "owner_id": int(ctx.user.id),
        "guild_id": int(ctx.guild_id),
        "mode": "live",
    }
    await insert_state(mongo, state, ttl=timedelta(minutes=15))
    await ctx.interaction.edit_initial_response(
        content=None,
        components=panel(state),
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


@register_action(
    "ticket_v2_staff_pick", opens_modal=True, no_return=True, preload_state=False
)
@lightbulb.di.with_di
async def pick(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
):
    await ctx.defer(edit=True)
    key, _, field = action_id.partition("|")
    state = await owned_state(ctx, mongo, key)
    if state is None:
        await notice(
            ctx, "This private setup has expired or belongs to another recruiter."
        )
        return
    values = list(getattr(ctx.interaction, "values", ()) or ())
    if len(values) != 1 or field not in {"user", "type", "mode"}:
        await notice(ctx, "Invalid selection.")
        return
    value = values[0]
    if field == "user":
        value = store.as_int(value)
        if not value:
            await notice(ctx, "Choose a guild member.")
            return
        target = "recruit_id"
    else:
        if value not in ({"main", "fwa"} if field == "type" else {"live", "test"}):
            await notice(ctx, "Invalid selection.")
            return
        target = "ticket_type" if field == "type" else "mode"
    await update_state(
        mongo, {"_id": key, "closed": {"$ne": True}}, {"$set": {target: value}}
    )
    state[target] = value
    await ctx.interaction.edit_initial_response(
        content=None,
        components=panel(state),
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


def ticket_links(ticket):
    lines = ["✅ Ticket available."]
    for label, staff in [("Recruit Thread", False), ("Staff Thread", True)]:
        url = console.ticket_jump_url(ticket, staff=staff)
        if url:
            lines.append(f"[{label}]({url})")
    return "\n".join(lines)


async def show_ticket(ctx, ticket):
    links = [
        Link(url=url, label=label)
        for label, staff in [("Recruit Thread", False), ("Staff Thread", True)]
        if (url := console.ticket_jump_url(ticket, staff=staff))
    ]
    await ctx.interaction.edit_initial_response(
        content=None,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
        components=[
            Container(
                accent_color=GOLDENROD_ACCENT,
                components=(
                    [Text(content="✅ Ticket available."), Row(components=links)]
                    if links
                    else [Text(content="Ticket saved; links are pending recovery.")]
                ),
            )
        ],
    )


async def _create_for_recruit(bot, mongo, state, actor, on_ready):
    guild = int(state["guild_id"])
    recruit = int(state["recruit_id"])
    kind = state["ticket_type"]
    member = await bot.rest.fetch_member(guild, recruit)
    if member.is_bot:
        raise ValueError("The recruit must be a human guild member.")
    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    runtime_bot = bot
    if state.get("mode") == "test":
        mongo = testing_service.test_mongo(mongo)
        window = await testing_service.active_window(mongo)
        if not window:
            raise ValueError("An active isolated window is required.")
        await require_test_access(
            SimpleNamespace(guild_id=guild, user=actor), mongo, bot
        )
        await require_test_access(
            SimpleNamespace(guild_id=guild, user=member), mongo, bot
        )
        runtime_bot = testing_service.test_bot(bot, mongo)
        config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    elif testing_service.is_test_scope(mongo):
        raise ValueError("An isolated setup cannot create a live ticket.")
    elif not thread_intake_ready():
        raise ValueError("Thread ticketing is still completing safety checks.")
    # Staff creation reuses an existing application regardless of its clan type.
    for existing_kind in ("main", "fwa"):
        existing = await store.find_open_for_applicant(
            mongo, user_id=recruit, ticket_type=existing_kind
        )
        if existing and not ticket_runtime.thread_missing_has_role(
            existing, "candidate"
        ):
            return existing
    authoritative = await ticket_runtime._open_authoritative_tickets(
        mongo, user_id=recruit, limit=10
    )
    for _, existing in authoritative:
        if not ticket_runtime.thread_missing_has_role(existing, "candidate"):
            return dict(existing)
    if testing_service.is_test_scope(mongo):
        claim = await testing_service.claim_test_slot(
            mongo, guild_id=guild, user_id=recruit, ticket_type=kind
        )
    else:
        rollout = await ticket_runtime.get_rollout(mongo)
        source = (
            rollout.pilot_intake
            if rollout.phase == ticket_runtime.PHASE_PILOT
            else rollout.thread_intake
        )
        if not source or source.guild_id != guild:
            raise ValueError("No active thread intake is configured in this guild.")
        route = await ticket_runtime.route_public_intake(
            mongo,
            requested_route=ticket_runtime.ROUTE_THREAD,
            guild_id=guild,
            channel_id=source.channel_id,
            message_id=source.message_id,
            user_id=recruit,
            member_role_ids=member.role_ids,
            ticket_type=kind,
        )
        if not route.allowed or route.route != ticket_runtime.ROUTE_THREAD:
            raise ValueError(
                "The current rollout does not allow this recruit to create a thread ticket."
            )
        workflow = f"thread:{recruit}:{kind}"
        now = datetime.now(timezone.utc)
        claim = await ticket_runtime.claim_open_slot(
            mongo,
            user_id=recruit,
            ticket_type=kind,
            route=ticket_runtime.ROUTE_THREAD,
            guild_id=guild,
            workflow_id=workflow,
            rollout_revision=route.revision,
            now=now,
            lease_seconds=600,
        )
        if (
            not claim.won
            and claim.slot.get("state") == ticket_runtime.SLOT_RESERVED
            and claim.slot.get("workflow_id") == workflow
            and claim.slot.get("guild_id") == guild
            and claim.slot.get("route") == ticket_runtime.ROUTE_THREAD
        ):
            claim = await ticket_runtime.resume_open_slot(
                mongo,
                slot_id=claim.slot["_id"],
                workflow_id=workflow,
                route=ticket_runtime.ROUTE_THREAD,
                guild_id=guild,
                now=now,
                lease_seconds=600,
            )
    if not claim.won:
        location = store.as_int(claim.slot.get("location_id"))
        if location:
            existing = await store.find_by_location(mongo, location)
            if existing:
                return existing
            return {
                "guild_id": claim.slot.get("guild_id") or guild,
                "location": {"id": location},
            }
        raise ValueError(
            "An earlier ticket is being created or needs cleanup. Try again shortly."
        )

    async def run(service_bot):
        return await thread_service.create_live_thread_ticket(
            bot=service_bot,
            mongo=mongo,
            guild_id=guild,
            user_id=recruit,
            username=member.username,
            display_name=member.display_name,
            ticket_type=kind,
            config=config,
            open_slot_claim=claim,
            opened_by=int(actor.id),
            on_ready=on_ready,
        )

    if testing_service.is_test_scope(mongo):
        async with test_dependencies(mongo, bot) as (_, service_bot):
            result = await run(service_bot)
    else:
        result = await run(runtime_bot)
    return result.ticket


async def create_for_recruit(bot, mongo, state, actor, on_ready):
    """Serialize staff creation across clan types in the selected database."""
    from pymongo import ReturnDocument
    from pymongo.errors import DuplicateKeyError

    scoped = testing_service.test_mongo(mongo) if state.get("mode") == "test" else mongo
    now = datetime.now(timezone.utc)
    key = f"staff-create:{state['recruit_id']}"
    token = uuid.uuid4().hex
    try:
        lease = await scoped.ticket_automation_state.find_one_and_update(
            {
                "_id": key,
                "$or": [
                    {"lease_until": {"$lte": now}},
                    {"lease_until": {"$exists": False}},
                ],
            },
            {"$set": {"owner": token, "lease_until": now + timedelta(minutes=15)}},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )
    except DuplicateKeyError:
        raise ValueError(
            "A recruiter is already creating a ticket for this recruit. Try again shortly."
        ) from None
    if not lease or lease.get("owner") != token:
        raise ValueError("A recruiter is already creating this ticket.")
    try:
        return await _create_for_recruit(bot, mongo, state, actor, on_ready)
    finally:
        await scoped.ticket_automation_state.delete_one({"_id": key, "owner": token})


@register_action(
    "ticket_v2_staff_submit", opens_modal=True, no_return=True, preload_state=False
)
@lightbulb.di.with_di
async def submit(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
):
    await ctx.defer(edit=True)
    state = await owned_state(ctx, mongo, action_id)
    if (
        not state
        or not state.get("recruit_id")
        or state.get("ticket_type") not in {"main", "fwa"}
    ):
        await notice(
            ctx,
            "This setup is unavailable. Choose a recruit and ticket type in a new setup.",
        )
        return
    await notice(ctx, "Creating the recruit ticket…")
    ready = None

    async def on_ready(ticket):
        nonlocal ready
        ready = ticket
        await show_ticket(ctx, ticket)

    try:
        ticket = await create_for_recruit(bot, mongo, state, ctx.member, on_ready)
    except (ValueError, thread_service.ThreadTicketError) as error:
        if ready:
            await show_ticket(ctx, ready)
        else:
            await notice(ctx, str(error))
        return
    except Exception:
        logging.getLogger(__name__).exception(
            "Staff ticket creation failed recruit=%s", state.get("recruit_id")
        )
        if ready:
            await show_ticket(ctx, ready)
        else:
            await notice(
                ctx,
                "Ticket creation could not finish safely. The saved attempt can resume; try again shortly.",
            )
        return
    await update_state(mongo, action_id, {"$set": {"closed": True}})
    await show_ticket(ctx, ticket)


@register_action(
    "ticket_v2_staff_cancel", opens_modal=True, no_return=True, preload_state=False
)
@lightbulb.di.with_di
async def cancel(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
):
    await ctx.defer(edit=True)
    if not await owned_state(ctx, mongo, action_id):
        await notice(
            ctx, "This private setup has expired or belongs to another recruiter."
        )
        return
    await update_state(mongo, action_id, {"$set": {"closed": True}})
    await notice(ctx, "Ticket setup cancelled.")
