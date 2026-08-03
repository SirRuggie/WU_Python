"""Resolving a ticket: the side effects, and the override path when you lose the race.

Two rules govern everything here.

1. SIDE EFFECTS RUN ONLY ON A WON TRANSITION. Before this module existed, the
   deny handlers posted the applicant-facing denial BEFORE writing the status, so
   two recruiters denying the same ticket in the same second sent the applicant
   two denial messages and both writes landed. The message now happens after
   Mongo has arbitrated, and only for the winner.

2. LOSING IS NOT A DEAD END. A mistaken deny, an appeal, or a leader overruling
   are all normal in recruiting, and none of them should require hand-editing
   Mongo. A recruiter who loses the race is offered an override; the audit array
   records that it overturned a prior resolution, and who did it.

The side effects live in one place so that the first attempt and the override
run identical code rather than two drifting copies.
"""

import asyncio

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SectionComponentBuilder as Section,
    TextDisplayComponentBuilder as Text,
    ThumbnailComponentBuilder as Thumbnail,
)

from extensions.commands.tickets import perms, store
from extensions.components import register_action
from utils.constants import RED_ACCENT
from utils.mongo import MongoClient

DENIED_THUMB = "https://res.cloudinary.com/dxmtzuomk/image/upload/v1753271403/misc_images/Denied.png"

KIND_APPROVE = "approve"
KIND_DENY_FWA = "deny_fwa"
KIND_DENY_MAIN = "deny_main"
KIND_DENY_CUSTOM = "deny_custom"

# Kept verbatim from the original handlers - this is copy the applicant reads.
_DENIAL_BODY = {
    KIND_DENY_FWA: (
        "I am sorry but unfortunately, you do not meet the criteria for Warriors United. "
        "Here's a resource link to other FWA Clans that may have a spot for you.\n\n"
        "https://band.us/@reqfwa\n\n"
        "Good luck!"
    ),
    KIND_DENY_MAIN: (
        "I am sorry but unfortunately, you do not meet the criteria for Warriors United. "
        "Here's a resource link to other Clans that may have a spot for you.\n\n"
        "https://discord.com/invite/clashofclans\n\n"
        "Good luck!"
    ),
}

DENIAL_TYPE = {
    KIND_DENY_FWA: "fwa_default",
    KIND_DENY_MAIN: "main_default",
    KIND_DENY_CUSTOM: "custom",
}

_LABEL = {
    KIND_APPROVE: "Overturn and approve",
    KIND_DENY_FWA: "Overturn and deny",
    KIND_DENY_MAIN: "Overturn and deny",
    KIND_DENY_CUSTOM: "Overturn and deny",
}


def get_channel_name_with_new_emoji(channel_name: str, new_emoji: str) -> str:
    """Replace the emoji prefix in a channel name with a new emoji.

    Moved verbatim from close.py so the override path and the first attempt share
    one implementation. Deliberately not "improved" into a regex - the behaviour
    on names that carry no known prefix is load-bearing.
    """
    ticket_emojis = ["🆕", "❌", "✅"]
    for emoji in ticket_emojis:
        if channel_name.startswith(emoji):
            return new_emoji + channel_name[len(emoji):]
    return new_emoji + channel_name


def ts(value, style: str = "R") -> str:
    """<t:unix:R> - ages itself, and renders in the reader's own timezone."""
    try:
        return f"<t:{int(value.timestamp())}:{style}>"
    except (AttributeError, TypeError, ValueError):
        return "earlier"


async def _clear_monitor_flag(mongo: MongoClient, channel_id) -> None:
    """Vestigial. The reader was deleted with the ticket_automation tree; the write
    is kept only to avoid touching the ticket_automation_state collection."""
    try:
        await mongo.ticket_automation_state.update_one(
            {"_id": str(channel_id)},
            {"$set": {"step_data.questionnaire.discord_skills_monitor_active": False}},
        )
    except Exception as exc:
        print(f"[TicketResolve] Error clearing monitor flag: {exc}")


async def _rename(bot: hikari.GatewayBot, channel_id, emoji: str, actor_name: str) -> None:
    try:
        channel = await bot.rest.fetch_channel(channel_id)
        await bot.rest.edit_channel(
            channel_id,
            name=get_channel_name_with_new_emoji(channel.name, emoji),
            reason=f"Ticket resolved by {actor_name}",
        )
    except Exception as exc:
        print(f"[TicketResolve] rename failed for {channel_id}: {exc}")


# --- side effects ------------------------------------------------------------

async def apply_denial(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        kind: str,
        channel_id,
        user_id,
        actor_name: str,
        reason: str | None = None,
) -> None:
    """Message the applicant and mark the channel. WON transitions only."""
    body = reason if kind == KIND_DENY_CUSTOM else _DENIAL_BODY[kind]
    components = [
        Container(
            accent_color=RED_ACCENT,
            components=[
                Section(
                    components=[
                        Text(content=(
                            f"<@{user_id}>, we regret to inform you that currently your "
                            f"application has been denied.\n\n"
                            f"## **Reason:**\n{body}"
                        ))
                    ],
                    accessory=Thumbnail(media=DENIED_THUMB),
                ),
                Media(items=[MediaItem(media="assets/Red_Footer.png")]),
            ],
        )
    ]
    await bot.rest.create_message(
        channel=channel_id, components=components, user_mentions=[int(user_id)]
    )
    await _clear_monitor_flag(mongo, channel_id)
    await _rename(bot, channel_id, "❌", actor_name)


async def apply_approval(
        bot: hikari.GatewayBot,
        mongo: MongoClient,
        *,
        channel_id,
        actor_name: str,
) -> None:
    """Mark the channel and congratulate. WON transitions only.

    The congratulations still sources its user id from ticket_automation_state and
    is skipped when that document is absent - preserved exactly as it was, so this
    change stays scoped to the race. The ticket document has user_id too, which
    would be the better source; that is a separate decision.
    """
    await _clear_monitor_flag(mongo, channel_id)
    await _rename(bot, channel_id, "✅", actor_name)
    await asyncio.sleep(1)
    try:
        automation_doc = await mongo.ticket_automation_state.find_one({"_id": str(channel_id)})
        if automation_doc and automation_doc.get("user_id"):
            user_id = automation_doc["user_id"]
            await bot.rest.create_message(
                channel=channel_id,
                content=(
                    f"<@{user_id}> Congratulations on being accepted to Warriors United! "
                    f"Stand by for further instructions."
                ),
                user_mentions=[user_id],
            )
        else:
            print(f"[TicketResolve] no automation doc for {channel_id}, skipping congratulations")
    except Exception as exc:
        print(f"[TicketResolve] congratulations failed for {channel_id}: {exc}")


def claim_note(doc: dict | None, actor_id: int) -> str:
    """A note when you resolved a ticket someone else had claimed.

    Advisory only, per the design decision: claiming records and signals intent,
    it does not gate. Discord cannot enforce ownership inside a thread anyway, so
    a hard block here would be theatre.
    """
    holder = (doc or {}).get("claimed_by")
    if holder and holder != actor_id:
        return f"\n-# <@{holder}> had claimed this one."
    return ""


async def run_side_effects(bot, mongo, *, kind: str, channel_id, user_id, actor_name, reason=None):
    if kind == KIND_APPROVE:
        await apply_approval(bot, mongo, channel_id=channel_id, actor_name=actor_name)
    else:
        await apply_denial(
            bot, mongo, kind=kind, channel_id=channel_id,
            user_id=user_id, actor_name=actor_name, reason=reason,
        )


# --- losing the race ---------------------------------------------------------

def _prior(current: dict) -> dict:
    """Who resolved it first, and when, from whichever pair of fields was written."""
    if current.get("status") == "approved":
        return {"verb": "approved", "by": current.get("approved_by"), "at": current.get("approved_at")}
    return {"verb": "denied", "by": current.get("denied_by"), "at": current.get("denied_at")}


def lost_message(kind: str, current: dict, action_id: str | None) -> tuple[str, list]:
    """(content, components) for the panel a recruiter sees when someone got there first.

    Deliberately NOT a Components V2 container. The ephemeral this replaces is
    plain content plus an ActionRow, and IS_COMPONENTS_V2 is a one-way latch:
    once set on a message, `content` is rejected with a 400 forever after. This
    panel gets edited with text when the override completes, so it must stay
    non-V2. (ActionRow alone does not trip the flag - hikari excludes it.)

    `action_id is None` means the viewer may not override, so no button is shown
    and the copy does not dangle an option they cannot take.
    """
    prior = _prior(current)
    who = f"<@{prior['by']}>" if prior["by"] else "Someone"
    when = ts(prior["at"])
    noun = "approval" if prior["verb"] == "approved" else "denial"

    if action_id is None:
        return (
            f"### {who} already {prior['verb']} this one\n"
            f"That was {when}, so I've left it as it stands. A recruiter can revisit it "
            f"if it needs another look.",
            [],
        )

    if kind == KIND_APPROVE:
        content = (
            f"### {who} {prior['verb']} this one already\n"
            f"That was {when}, so I've not touched anything — the applicant still has the "
            f"{noun}, and the channel still shows it.\n\n"
            f"Approving now overturns that. Normal enough if there's been an appeal or a "
            f"leader's called it differently; it'll go on the record as yours."
        )
        style = hikari.ButtonStyle.SUCCESS
    else:
        content = (
            f"### {who} already {prior['verb']} this one\n"
            f"That was {when}. I've left everything as it was — the applicant hasn't been "
            f"messaged again, and the channel still shows their call.\n\n"
            f"If this needs overturning, that's yours to make. Mistaken deny, an appeal, a "
            f"leader stepping in — go ahead and it'll be recorded as your decision."
        )
        style = hikari.ButtonStyle.DANGER

    rows = [ActionRow(components=[Button(
        style=style,
        custom_id=f"ticket_override:{action_id}",
        label=_LABEL[kind],
    )])]
    return content, rows


async def offer_override(
        ctx,
        mongo: MongoClient,
        *,
        kind: str,
        current: dict,
        ticket_id,
        channel_id,
        user_id,
        reason: str | None = None,
) -> tuple[str, list]:
    """Stash what an override would need, and build the panel offering it.

    Returns (content, components); the caller delivers them, because the deny
    handlers respond through edit_initial_response and approve responds directly.
    """
    if not await perms.is_recruiter(ctx.member, mongo):
        return lost_message(kind, current, None)

    prior = _prior(current)
    action_id = str(ctx.interaction.id)
    await mongo.button_store.insert_one({
        "_id": action_id,
        "type": "ticket_override",
        "kind": kind,
        "ticket_id": ticket_id,
        "channel_id": channel_id,
        "user_id": user_id,
        "reason": reason,
        "prior_status": current.get("status"),
        "prior_by": prior["by"],
        "prior_at": prior["at"],
    })
    return lost_message(kind, current, action_id)


@register_action("ticket_override", no_return=True)
@lightbulb.di.with_di
async def ticket_override_handler(
        ctx: lightbulb.components.MenuContext,
        action_id: str,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
):
    """Overturn a resolution someone else already made.

    Re-checks the recruiter role at click time. The dispatcher enforces nothing -
    `user_only` is stored and never read - so a button cannot inherit trust from
    the interaction that rendered it, even an ephemeral one.
    """
    data = await mongo.button_store.find_one({"_id": action_id})
    if not data:
        await ctx.interaction.edit_initial_response(
            content="That override has expired. Run the command again.", components=[]
        )
        return

    if not await perms.is_recruiter(ctx.member, mongo):
        await ctx.interaction.edit_initial_response(
            content="Only recruiters can overturn a resolution.", components=[]
        )
        return

    kind = data["kind"]
    to_status = "approved" if kind == KIND_APPROVE else "denied"
    now_extra = {}
    if kind == KIND_APPROVE:
        now_extra = {"approved_at": store.utcnow(), "approved_by": ctx.user.id}
    else:
        now_extra = {
            "denied_at": store.utcnow(),
            "denied_by": ctx.user.id,
            "denial_type": DENIAL_TYPE[kind],
        }
        if kind == KIND_DENY_CUSTOM and data.get("reason"):
            now_extra["denial_reason"] = data["reason"]

    result = await store.transition(
        mongo,
        data["ticket_id"],
        to_status=to_status,
        actor_id=ctx.user.id,
        actor_name=ctx.user.username,
        expect=None,  # the override: no precondition, deliberately
        extra=now_extra,
        overrides={
            "status": data.get("prior_status"),
            "by": data.get("prior_by"),
            "by_name": None,
            "at": data.get("prior_at"),
        },
    )

    if result.outcome == store.MISSING:
        await ctx.interaction.edit_initial_response(
            content=f"The ticket record `{data['ticket_id']}` has gone. Nothing was changed.",
            components=[],
        )
        return

    await run_side_effects(
        bot, mongo,
        kind=kind,
        channel_id=data["channel_id"],
        user_id=data.get("user_id"),
        actor_name=ctx.user.username,
        reason=data.get("reason"),
    )
    await mongo.button_store.delete_one({"_id": action_id})

    verb = "Approved" if kind == KIND_APPROVE else "Denied"
    prior_verb = "approved" if data.get("prior_status") == "approved" else "denied"
    who = f"<@{data['prior_by']}>" if data.get("prior_by") else "the previous decision"
    await ctx.interaction.edit_initial_response(
        content=(
            f"{verb}. That overturns {who}'s call from {ts(data.get('prior_at'))}, "
            f"recorded against your name."
        ),
        components=[],
    )
