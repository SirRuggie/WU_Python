"""Close without a recruitment decision, and explicitly reopen closed tickets."""

import hashlib
import uuid

import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands import ticket_runtime
from . import perms, resolve, store, testing_service


def components(ticket, kind, *, staff=False):
    closing = kind == "close"
    title = "📁 Ticket closed" if closing else "🆕 Ticket reopened"
    reason = (
        ticket.get("closure_reason" if closing else "reopen_reason")
        or "No reason recorded."
    )
    text = (
        "This application was closed without an approval or denial. Contact recruitment staff if you want to continue."
        if closing
        else "Recruitment staff reopened this application. You can continue the conversation here."
    )
    return [
        Container(
            accent_color=hikari.Color(0x808080),
            components=[
                Text(
                    content=f"## {title} · {str(ticket['ticket_type']).upper()} #{ticket['ticket_number']}"
                ),
                *(
                    [Text(content="🧪 TEST MODE — simulated ticket.")]
                    if testing_service.is_test_ticket(ticket)
                    else []
                ),
                Text(
                    content=f"**Recruit:** <@{ticket['user_id']}>\n**Handled by:** <@{ticket['handled_by']}>\n**Time:** {resolve.ts(ticket['handled_at'], 'F')}"
                ),
                Text(content=f"{text}\n\n**Reason:** {reason}"),
            ],
        )
    ]


async def deliver_candidate(bot, ticket, kind, marker):
    nonce = hashlib.sha256(f"candidate:{marker}".encode()).hexdigest()[:24]
    return await bot.rest.create_message(
        channel=ticket["location"]["id"],
        components=components(ticket, kind),
        nonce=nonce,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


async def finish_effects(bot, mongo, ticket, kind):
    if kind == "reopen":
        slot = ticket.get("reopen_slot") or {}
        current = await mongo.ticket_open_slots.find_one({"_id": slot["id"]})
        if (
            not current
            or current.get("ticket_id") != ticket["_id"]
            or current.get("state") != ticket_runtime.SLOT_OPEN
        ):
            await ticket_runtime.bind_open_slot(
                mongo,
                slot_id=slot["id"],
                owner_token=slot["owner"],
                ticket_id=ticket["_id"],
                location_id=ticket["location"]["id"],
            )
    for role, channel_id in (
        ("candidate", ticket["location"]["id"]),
        ("staff", ticket["location"].get("staff_space_id")),
    ):
        if not channel_id or ticket_runtime.thread_missing_has_role(ticket, role):
            continue
        channel = await bot.rest.fetch_channel(channel_id)
        desired = kind == "close"
        if bool(channel.is_archived) != desired or bool(channel.is_locked) != desired:
            await bot.rest.edit_channel(
                channel_id,
                archived=desired,
                locked=desired,
                reason=(
                    "Closing application without decision"
                    if desired
                    else "Recruiter reopened application"
                ),
            )


async def change(
    bot,
    mongo,
    *,
    ticket_id,
    member,
    actor_name,
    kind,
    reason,
    expected_rev=None,
    expected_activity_revision=None,
    expected_inactivity_token=None,
):
    if not await perms.is_recruiter(member, mongo):
        return store.Transition(
            store.UNAUTHORIZED, None, "Recruiter permission required."
        )
    if (
        kind not in {"close", "reopen"}
        or not 5 <= len(str(reason or "").strip()) <= 1000
    ):
        return store.Transition(
            store.BLOCKED, None, "Enter a reason between 5 and 1,000 characters."
        )
    ticket = await store.find_one(mongo, {"_id": ticket_id, **store.RUNTIME_FILTER})
    if ticket is None:
        return store.Transition(store.MISSING, None)
    if int(ticket["guild_id"]) != int(member.guild_id):
        return store.Transition(store.UNAUTHORIZED, ticket, "Use this ticket’s server.")
    source = "open" if kind == "close" else "closed"
    if ticket.get("status") != source:
        return store.Transition(
            store.LOST, ticket, "The ticket status changed. Refresh its details."
        )
    if expected_rev is not None and int(ticket.get("rev") or 0) != int(expected_rev):
        return store.Transition(
            store.LOST, ticket, "The ticket changed. Refresh its details."
        )
    if (
        kind == "reopen"
        and ((ticket.get("inactivity") or {}).get("prompt") or {}).get("state") == "yes"
    ):
        return store.Transition(
            store.BLOCKED,
            ticket,
            "The Ghosted flag update is still finishing. Try again shortly.",
        )
    if testing_service.is_test_scope(mongo):
        window = await testing_service.active_window(mongo)
        if (
            not testing_service.is_test_ticket(ticket)
            or not window
            or ticket.get("window_generation") != window.get("generation")
        ):
            return store.Transition(
                store.BLOCKED, ticket, "This test window has ended."
            )
        bot = testing_service.test_bot(bot, mongo)
    effects = ticket.get("resolution_effects") or {}
    if effects.get("marker") and not effects.get("complete"):
        return store.Transition(
            store.BLOCKED,
            ticket,
            "The previous ticket update is still finishing. Try again shortly.",
        )
    if kind == "reopen" and ticket_runtime.thread_missing_has_role(ticket, "candidate"):
        return store.Transition(
            store.BLOCKED,
            ticket,
            "The recruit thread was deleted. Create a new ticket instead.",
        )
    extra = {"closure_reason" if kind == "close" else "reopen_reason": reason.strip()}
    claim = None
    if kind == "reopen":
        workflow = f"reopen:{ticket_id}:{uuid.uuid4().hex}"
        if testing_service.is_test_scope(mongo):
            if await store.find_open_for_applicant(
                mongo, user_id=ticket["user_id"], ticket_type=ticket["ticket_type"]
            ):
                return store.Transition(
                    store.BLOCKED, ticket, "An open test ticket already exists."
                )
            claim = await ticket_runtime._insert_open_slot(
                mongo,
                user_id=ticket["user_id"],
                ticket_type=ticket["ticket_type"],
                route="thread",
                guild_id=ticket["guild_id"],
                workflow_id=workflow,
                rollout_revision=0,
                ticket_number=ticket["ticket_number"],
            )
        else:
            rollout = await ticket_runtime.get_rollout(mongo)
            claim = await ticket_runtime.claim_open_slot(
                mongo,
                user_id=ticket["user_id"],
                ticket_type=ticket["ticket_type"],
                route="thread",
                guild_id=ticket["guild_id"],
                workflow_id=workflow,
                rollout_revision=rollout.revision,
                ticket_number=ticket["ticket_number"],
            )
        if not claim.won:
            return store.Transition(
                store.BLOCKED,
                ticket,
                "This recruit already has an active ticket or ticket creation in progress.",
            )
        extra.update(
            open_slot_id=claim.slot["_id"],
            creation_workflow_id=workflow,
            reopen_slot={"id": claim.slot["_id"], "owner": claim.owner_token},
        )
    # Mongo arbitrates stale clicks and new activity before any Discord effects.
    result = await store.transition(
        mongo,
        ticket_id,
        to_status="closed" if kind == "close" else "open",
        actor_id=member.id,
        actor_name=actor_name,
        expect=source,
        expected_rev=(
            int(ticket.get("rev") or 0) if expected_rev is None else expected_rev
        ),
        expected_activity_revision=expected_activity_revision,
        expected_inactivity_token=expected_inactivity_token,
        effect_kind=kind,
        extra=extra,
    )
    if result.won:
        resolve._schedule_resolution_effects(bot, mongo, result.doc)
    elif claim is not None:
        await mongo.ticket_open_slots.delete_one(
            {
                "_id": claim.slot["_id"],
                "state": ticket_runtime.SLOT_RESERVED,
                "owner_token": claim.owner_token,
            }
        )
    return result
