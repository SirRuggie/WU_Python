"""Close without a recruitment decision, and explicitly reopen closed tickets."""

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands import ticket_runtime
from . import perms, resolve, schema, store, testing_service


MEMBER_REOPEN_DAYS = 60


def member_reopen_eligible(ticket, *, at=None):
    at = at or datetime.now(timezone.utc)
    closed = ticket.get("closed_at")
    if not isinstance(closed, datetime) or ticket.get("status") != "closed":
        return False
    if closed.tzinfo is None:
        closed = closed.replace(tzinfo=timezone.utc)
    return closed <= at <= closed + timedelta(days=MEMBER_REOPEN_DAYS)


def _member_message_authorized(ticket, message, member):
    if not member_reopen_eligible(ticket):
        return False
    author = getattr(message, "author", None)
    if author is None or getattr(author, "is_bot", True) or getattr(message, "webhook_id", None):
        return False
    closed = ticket["closed_at"]
    closed = closed.replace(tzinfo=timezone.utc) if closed.tzinfo is None else closed
    sent = getattr(message, "timestamp", None)
    if not isinstance(sent, datetime) or sent.tzinfo is None:
        return False
    return bool(
        int(getattr(author, "id", 0)) == int(ticket.get("user_id") or 0) == int(member.id)
        and int(getattr(message, "guild_id", 0) or 0) == int(ticket["guild_id"]) == int(member.guild_id)
        and int(getattr(message, "channel_id", 0)) == int((ticket.get("location") or {}).get("id") or 0)
        and isinstance(sent, datetime) and sent >= closed
    )


async def reopen_from_member_message(bot, mongo, ticket, message):
    author = message.author
    member = SimpleNamespace(id=int(author.id), guild_id=int(message.guild_id),
                             role_ids=(), permissions=hikari.Permissions.NONE)
    if not _member_message_authorized(ticket, message, member):
        return store.Transition(store.UNAUTHORIZED, None)
    result = await change(
        bot, mongo, ticket_id=ticket["_id"], member=member,
        actor_name=str(getattr(author, "username", None) or author.id),
        kind="reopen", reason="Member continued the conversation in their ticket.",
        expected_rev=int(ticket.get("rev") or 0), member_message=message,
    )
    if result.outcome == store.BLOCKED and "active ticket" in (result.reason or ""):
        # Claim before transport: an uncertain Discord acceptance is not retried.
        if await store.claim_member_reopen_notice(mongo, ticket):
            await bot.rest.create_message(
                int(message.channel_id),
                "This ticket was not reopened because you already have an active ticket. Continue there or ask staff for help.",
                user_mentions=False, role_mentions=False, mentions_everyone=False,
            )
    return result


def components(ticket, kind, *, staff=False):
    closing = kind == "close"
    desk = ticket.get("ticket_type") in schema.DESK_TICKET_TYPES
    title = "📁 Ticket closed" if closing else "🆕 Ticket reopened"
    reason = (
        ticket.get("closure_reason" if closing else "reopen_reason")
        or "No reason recorded."
    )
    text = (
        "Staff closed this application. They did not approve or deny it. Ask recruitment staff if you want to continue."
        if closing
        else "Recruitment staff reopened this application. You can continue the conversation here."
    )
    if desk:
        title = "📁 Request closed" if closing else "🆕 Request reopened"
        text = (
            "Staff closed this request. They did not approve or deny it."
            if closing
            else "Staff reopened this request. You can continue the conversation here."
        )
        if ticket.get("ticket_type") == "staff":
            title = "✅ Done" if closing else title
            text = (
                "Staff marked this request as done."
                if closing
                else "Staff reopened this request. You can continue the conversation here."
            )
    if closing and member_reopen_eligible(ticket):
        text += " You can still read this thread. Send a message here within 60 days of Close to reopen it, if you have no other active ticket of this type."
    elif not closing and (ticket.get("reopen_trigger") or {}).get("kind") == "member_message":
        text = "The member continued this conversation and reopened it."
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
                    content=f"**{'Member' if desk else 'Recruit'}:** <@{ticket['user_id']}>\n**Handled by:** <@{ticket['handled_by']}>\n**Time:** {resolve.ts(ticket['handled_at'], 'F')}"
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
        locked = desired and not (role == "candidate" and member_reopen_eligible(ticket))
        if bool(channel.is_archived) != desired or bool(channel.is_locked) != locked:
            await bot.rest.edit_channel(
                channel_id,
                archived=desired,
                locked=locked,
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
    member_message=None,
):
    if member_message is None and not await perms.is_ticket_staff(member, mongo):
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
    member_authorized = (kind == "reopen" and member_message is not None
                         and _member_message_authorized(ticket, member_message, member))
    if not member_authorized and not await perms.can_handle(member, mongo, ticket.get("ticket_type")):
        return store.Transition(
            store.UNAUTHORIZED, None, "Permission required for this request type."
        )
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
    if kind == "reopen":
        extra["reopen_trigger"] = {"kind": "staff"}
    if member_authorized:
        extra["reopen_trigger"] = {"kind": "member_message", "message_id": int(member_message.id)}
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
                "This recruit already has an active ticket, or we are creating one.",
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
        member_reopen=member_authorized,
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
