"""Admin-created, Mongo-backed polls with public aggregate voting."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from extensions.components import register_action
from utils import poll_store
from utils.component_state import delete_state, insert_state
from utils.constants import BLUE_ACCENT, GOLD_ACCENT, RED_ACCENT
from utils.mongo import MongoClient
from utils.startup_reconciler import StartupReconciler

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow,
    ModalActionRowBuilder as ModalActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)


loader = lightbulb.Loader()
poll = lightbulb.Group(
    "poll",
    "Create and manage timed server polls",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)

_log = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler(timezone=timezone.utc)
_bot: hikari.GatewayBot | None = None
_mongo: MongoClient | None = None
_startup_reconciler: StartupReconciler | None = None
_poll_locks: dict[str, asyncio.Lock] = {}

POLL_DURATION_CHOICES = (
    lightbulb.Choice("1 hour", 1),
    lightbulb.Choice("2 hours", 2),
    lightbulb.Choice("4 hours", 4),
    lightbulb.Choice("8 hours", 8),
    lightbulb.Choice("12 hours", 12),
    lightbulb.Choice("1 day", 24),
    lightbulb.Choice("2 days", 48),
)
POLL_DURATION_HOURS = frozenset(choice.value for choice in POLL_DURATION_CHOICES)
POLL_MODAL_TTL = timedelta(minutes=10)
POLL_JOB_PREFIX = "discord_poll_end:"
POLL_SYNC_JOB_PREFIX = "discord_poll_sync:"
POLL_SYNC_RETRY_DELAY = timedelta(minutes=5)
POLL_JOB_OPTIONS = {
    # Mongo is the clock. A suspended event loop must still run a late close.
    "misfire_grace_time": None,
    "coalesce": True,
    "max_instances": 1,
}
MAX_RECENT_POLLS = 15
MAX_NAMED_VOTERS_PER_OPTION = 50
POLL_BAR_WIDTH = 20


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _discord_timestamp(value: datetime, style: str = "R") -> str:
    return f"<t:{int(_as_utc(value).timestamp())}:{style}>"


def _escape_user_text(value: object) -> str:
    """Keep staff-entered copy readable without allowing mention injection."""
    text = str(value or "").strip().replace("\\", "\\\\")
    for character in "`*_~|>[]()":
        text = text.replace(character, f"\\{character}")
    return text.replace("@", "@\u200b")


def _guild_id(ctx) -> int | None:
    value = getattr(ctx, "guild_id", None)
    if value is None:
        value = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return int(value) if value is not None else None


def _member(ctx):
    member = getattr(ctx, "member", None)
    if member is None:
        member = getattr(getattr(ctx, "interaction", None), "member", None)
    return member


def _is_admin(ctx) -> bool:
    member = _member(ctx)
    permissions = getattr(member, "permissions", hikari.Permissions.NONE)
    return bool(permissions & hikari.Permissions.ADMINISTRATOR)


def _notice(title: str, body: str, *, color=RED_ACCENT) -> list[Container]:
    return [Container(
        accent_color=color,
        components=[
            Text(content=f"## {title}"),
            Separator(divider=True),
            Text(content=body),
        ],
    )]


async def _require_admin(ctx) -> bool:
    if _guild_id(ctx) is None:
        await ctx.respond(
            components=_notice(
                "Server only",
                "Poll administration can only be used inside a server.",
            ),
            ephemeral=True,
        )
        return False
    if not _is_admin(ctx):
        await ctx.respond(
            components=_notice(
                "Administrator access required",
                "Only server administrators can create, inspect, or end polls.",
            ),
            ephemeral=True,
        )
        return False
    return True


def _modal_value(ctx, custom_id: str) -> str:
    for row in getattr(ctx.interaction, "components", ()) or ():
        for component in row:
            if getattr(component, "custom_id", None) == custom_id:
                return str(getattr(component, "value", "") or "").strip()
    return ""


def _option_counts(document: dict) -> tuple[dict[int, int], int]:
    counts = {int(option["id"]): 0 for option in document.get("options", ())}
    for raw_choice in (document.get("votes") or {}).values():
        try:
            choice = int(raw_choice)
        except (TypeError, ValueError):
            continue
        if choice in counts:
            counts[choice] += 1
    return counts, sum(counts.values())


def _result_text(document: dict, counts: dict[int, int], total: int) -> str:
    if total == 0:
        return "No votes were cast."
    top = max(counts.values())
    winners = [
        _escape_user_text(option["text"])
        for option in document["options"]
        if counts[int(option["id"])] == top
    ]
    if len(winners) == 1:
        return f"Winner: **{winners[0]}** with **{top}** vote{'s' if top != 1 else ''}."
    return (
        f"Tie: **{' / '.join(winners)}** with **{top}** "
        f"vote{'s' if top != 1 else ''} each."
    )


def _round_half_up(numerator: int, denominator: int) -> int:
    """Round a non-negative rational number to the nearest integer."""
    if denominator <= 0:
        return 0
    return (max(int(numerator), 0) + denominator // 2) // denominator


def _vote_action_rows(document: dict) -> list[ActionRow]:
    """Build one compact numbered vote row without changing action IDs."""
    poll_id = str(document["_id"])
    buttons = [
        Button(
            style=hikari.ButtonStyle.PRIMARY,
            label=str(int(option["id"])),
            custom_id=f"poll_vote:{poll_id}|{int(option['id'])}",
        )
        for option in document.get("options", ())
    ]
    return [ActionRow(components=buttons)] if buttons else []


def build_poll_components(document: dict) -> list[Container]:
    """Render the public poll. Voter identities are intentionally omitted."""
    counts, total = _option_counts(document)
    active = bool(document.get("active"))
    title = _escape_user_text(document.get("title", "Poll")) or "Poll"
    description = _escape_user_text(document.get("description", ""))
    poll_id = str(document["_id"])
    ends_at = _as_utc(document["ends_at"])

    body: list = []
    if document.get("ping_role_id") is not None:
        body.append(Text(content=f"<@&{int(document['ping_role_id'])}>"))
    heading = f"# 📊 {title}"
    if description:
        heading += f"\n{description}"
    body.append(Text(content=heading))
    body.append(Separator(divider=True, spacing=hikari.SpacingType.SMALL))

    option_lines: list[str] = []
    for option in document.get("options", ()):
        option_id = int(option["id"])
        count = counts.get(option_id, 0)
        filled = min(
            _round_half_up(count * POLL_BAR_WIDTH, total),
            POLL_BAR_WIDTH,
        )
        bar = "█" * filled + "░" * (POLL_BAR_WIDTH - filled)
        percent = _round_half_up(count * 100, total)
        option_lines.extend([
            f"**{option_id}. {_escape_user_text(option['text'])}**",
            f"{bar} **{percent}% · {count}**",
        ])
    body.append(Text(content="\n".join(option_lines)))

    body.append(Separator(divider=True, spacing=hikari.SpacingType.SMALL))
    if active:
        body.extend(_vote_action_rows(document))
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                label="View voters",
                custom_id=f"poll_details:{poll_id}",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                label="End poll",
                custom_id=f"poll_end:{poll_id}",
            ),
        ]))
        body.append(Text(content=(
            f"-# {total} vote{'s' if total != 1 else ''} · "
            "You can change your vote.\n"
            f"-# ⏱️ Closes {_discord_timestamp(ends_at)} · "
            f"<@{int(document['creator_id'])}>"
        )))
    else:
        body.append(Text(content=f"**Poll closed.** {_result_text(document, counts, total)}"))
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                label="View voters",
                custom_id=f"poll_details:{poll_id}",
            ),
        ]))
        footer_time = _as_utc(document.get("ended_at") or ends_at)
        body.extend([
            Separator(divider=True, spacing=hikari.SpacingType.SMALL),
            Text(content=(
                f"-# ⏱️ Closed {_discord_timestamp(footer_time)} · "
                f"<@{int(document['creator_id'])}>"
            )),
        ])

    return [Container(
        accent_color=GOLD_ACCENT if active else BLUE_ACCENT,
        components=body,
    )]


def build_named_voter_components(document: dict) -> list[Container]:
    counts, total = _option_counts(document)
    votes = document.get("votes") or {}
    sections: list = [
        Text(content=f"## Named voters — {_escape_user_text(document.get('title', 'Poll'))}"),
        Text(content=(
            f"Poll `{document['_id']}` • **{total}** voter{'s' if total != 1 else ''} • "
            f"{'Open until ' + _discord_timestamp(document['ends_at']) if document.get('active') else 'Closed'}"
        )),
        Separator(divider=True),
    ]
    for option in document.get("options", ()):
        option_id = int(option["id"])
        voter_ids = sorted(
            int(user_id)
            for user_id, raw_choice in votes.items()
            if str(raw_choice) == str(option_id) and str(user_id).isdigit()
        )
        visible = voter_ids[:MAX_NAMED_VOTERS_PER_OPTION]
        names = ", ".join(f"<@{user_id}>" for user_id in visible) or "No votes"
        hidden = len(voter_ids) - len(visible)
        if hidden:
            names += f"\n…and {hidden} more."
        sections.append(Text(content=(
            f"**{option_id}. {_escape_user_text(option['text'])} — "
            f"{counts.get(option_id, 0)}**\n{names}"
        )))
    return [Container(accent_color=BLUE_ACCENT, components=sections)]


def build_poll_list_components(documents: list[dict], *, active_only: bool) -> list[Container]:
    title = "Active polls" if active_only else "Recent polls"
    if not documents:
        body = (
            "There are no open polls in this server."
            if active_only
            else "There is no retained poll history in this server."
        )
        return _notice(title, body, color=BLUE_ACCENT)

    lines = []
    for document in documents:
        counts, total = _option_counts(document)
        del counts
        status = (
            f"closes {_discord_timestamp(document['ends_at'])}"
            if document.get("active")
            else "closed"
        )
        lines.append(
            f"• `{document['_id']}` — **{_escape_user_text(document.get('title', 'Poll'))}** "
            f"({total} vote{'s' if total != 1 else ''}, {status})"
        )
    return [Container(
        accent_color=BLUE_ACCENT,
        components=[
            Text(content=f"## {title}"),
            Text(content="\n".join(lines)),
            Separator(divider=True),
            Text(content="Use `/poll view poll-id:<id>` to see the named breakdown."),
        ],
    )]


def _lock_for(poll_id: str) -> asyncio.Lock:
    return _poll_locks.setdefault(str(poll_id), asyncio.Lock())


def _job_id(poll_id: str) -> str:
    return f"{POLL_JOB_PREFIX}{poll_id}"


def _sync_job_id(poll_id: str) -> str:
    return f"{POLL_SYNC_JOB_PREFIX}{poll_id}"


def _schedule_poll(document: dict) -> None:
    if not getattr(_scheduler, "running", False):
        return
    _scheduler.add_job(
        _expire_poll,
        trigger=DateTrigger(run_date=_as_utc(document["ends_at"])),
        args=[int(document["guild_id"]), str(document["_id"])],
        id=_job_id(str(document["_id"])),
        replace_existing=True,
        **POLL_JOB_OPTIONS,
    )


def _remove_poll_job(poll_id: str) -> None:
    if getattr(_scheduler, "running", False) and _scheduler.get_job(_job_id(poll_id)):
        _scheduler.remove_job(_job_id(poll_id))


def _remove_sync_job(poll_id: str) -> None:
    if getattr(_scheduler, "running", False) and _scheduler.get_job(_sync_job_id(poll_id)):
        _scheduler.remove_job(_sync_job_id(poll_id))


def _schedule_sync_retry(document: dict) -> None:
    if not getattr(_scheduler, "running", False):
        return
    _scheduler.add_job(
        _retry_poll_sync,
        trigger=DateTrigger(run_date=_utcnow() + POLL_SYNC_RETRY_DELAY),
        args=[int(document["guild_id"]), str(document["_id"])],
        id=_sync_job_id(str(document["_id"])),
        replace_existing=True,
        **POLL_JOB_OPTIONS,
    )


async def _edit_poll_message(
    bot: hikari.GatewayBot,
    document: dict,
) -> tuple[str, str | None]:
    try:
        await bot.rest.edit_message(
            channel=int(document["channel_id"]),
            message=int(document["message_id"]),
            components=build_poll_components(document),
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
            mentions_reply=False,
        )
    except (hikari.NotFoundError, hikari.ForbiddenError) as exc:
        _log.warning(
            "poll message is unavailable poll=%s guild=%s error=%s",
            document.get("_id"), document.get("guild_id"), type(exc).__name__,
        )
        return "unavailable", type(exc).__name__
    except Exception as exc:
        _log.exception(
            "failed to refresh poll message poll=%s guild=%s channel=%s message=%s",
            document.get("_id"), document.get("guild_id"),
            document.get("channel_id"), document.get("message_id"),
        )
        return "retry", type(exc).__name__
    return "synced", None


async def _sync_poll_message(
    mongo: MongoClient,
    bot: hikari.GatewayBot,
    document: dict,
) -> bool:
    """Render durable state, retaining a restart-safe retry marker on failure."""
    poll_id = str(document["_id"])
    guild_id = int(document["guild_id"])
    outcome, error = await _edit_poll_message(bot, document)
    try:
        if outcome == "synced":
            await poll_store.mark_message_synced(
                mongo, guild_id=guild_id, poll_id=poll_id,
            )
            _remove_sync_job(poll_id)
            return True
        if outcome == "unavailable":
            await poll_store.mark_message_unavailable(
                mongo,
                guild_id=guild_id,
                poll_id=poll_id,
                error=error or "Discord message unavailable",
            )
            _remove_sync_job(poll_id)
            return True
        updated = await poll_store.mark_message_sync_pending(
            mongo,
            guild_id=guild_id,
            poll_id=poll_id,
            error=error or "Discord render failed",
        )
    except Exception:
        _log.exception(
            "failed to persist poll message sync state poll=%s guild=%s",
            poll_id, guild_id,
        )
        _schedule_sync_retry(document)
        return False

    if updated is None:
        _remove_sync_job(poll_id)
        return True
    _schedule_sync_retry(updated)
    return False


async def _finalize_poll(
    mongo: MongoClient,
    bot: hikari.GatewayBot,
    *,
    guild_id: int,
    poll_id: str,
    reason: str,
) -> tuple[dict | None, bool]:
    async with _lock_for(poll_id):
        ended = await poll_store.end_poll(
            mongo,
            guild_id=guild_id,
            poll_id=poll_id,
            reason=reason,
        )
        changed = ended is not None
        if ended is None:
            ended = await poll_store.get_poll(
                mongo, guild_id=guild_id, poll_id=poll_id,
            )
        if ended is not None:
            await _sync_poll_message(mongo, bot, ended)
            _remove_poll_job(poll_id)
        return ended, changed


async def _retry_poll_sync(guild_id: int, poll_id: str) -> None:
    if _mongo is None or _bot is None:
        return
    try:
        await _recover_pending_sync(
            _mongo, _bot, guild_id=guild_id, poll_id=poll_id,
        )
    except Exception:
        _log.exception("poll message sync retry failed poll=%s guild=%s", poll_id, guild_id)
        _schedule_sync_retry({"_id": poll_id, "guild_id": guild_id})


async def _recover_pending_sync(
    mongo: MongoClient,
    bot: hikari.GatewayBot,
    *,
    guild_id: int,
    poll_id: str,
) -> bool:
    """Reload and render a pending message under the vote/end serialization lock."""
    async with _lock_for(poll_id):
        document = await poll_store.get_poll(
            mongo, guild_id=guild_id, poll_id=poll_id,
        )
        if document is None or not document.get("message_sync_pending"):
            _remove_sync_job(poll_id)
            return True
        return await _sync_poll_message(mongo, bot, document)


async def _expire_poll(guild_id: int, poll_id: str) -> None:
    if _mongo is None or _bot is None:
        _log.error("poll expiry fired before dependencies were ready poll=%s", poll_id)
        return
    try:
        await _finalize_poll(
            _mongo, _bot, guild_id=guild_id, poll_id=poll_id, reason="expired",
        )
    except Exception:
        _log.exception("automatic poll expiry failed poll=%s guild=%s", poll_id, guild_id)
        if getattr(_scheduler, "running", False):
            _scheduler.add_job(
                _expire_poll,
                trigger=DateTrigger(run_date=_utcnow() + timedelta(minutes=5)),
                args=[guild_id, poll_id],
                id=_job_id(poll_id),
                replace_existing=True,
                **POLL_JOB_OPTIONS,
            )


async def _reconcile_poll_startup() -> None:
    if _mongo is None or _bot is None:
        raise RuntimeError("poll dependencies are not ready")
    if not getattr(_scheduler, "running", False):
        _scheduler.start()

    while True:
        due = await poll_store.list_due_polls(_mongo, limit=100)
        if not due:
            break
        for document in due:
            await _finalize_poll(
                _mongo,
                _bot,
                guild_id=int(document["guild_id"]),
                poll_id=str(document["_id"]),
                reason="expired",
            )

    for document in await poll_store.list_pending_message_sync(_mongo, limit=None):
        await _recover_pending_sync(
            _mongo,
            _bot,
            guild_id=int(document["guild_id"]),
            poll_id=str(document["_id"]),
        )

    for document in await poll_store.list_open_polls(_mongo, limit=None):
        _schedule_poll(document)

    # Index/TTL installation may need DBA repair, but cannot be allowed to stop
    # otherwise-valid polls from closing or recovering their public messages.
    await poll_store.ensure_indexes(_mongo)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_poll_started(
    event: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global _bot, _mongo, _startup_reconciler
    _bot = event.app
    _mongo = mongo
    if _startup_reconciler is None:
        _startup_reconciler = StartupReconciler(
            "discord_polls", _reconcile_poll_startup,
        )
    _startup_reconciler.start()


@loader.listener(hikari.StoppingEvent)
async def on_poll_stopping(_: hikari.StoppingEvent) -> None:
    global _bot, _mongo, _startup_reconciler
    if _startup_reconciler is not None:
        await _startup_reconciler.stop()
        _startup_reconciler = None
    if getattr(_scheduler, "running", False):
        _scheduler.shutdown(wait=False)
        await asyncio.sleep(0)
    _poll_locks.clear()
    _bot = None
    _mongo = None


@poll.register()
class CreatePoll(
    lightbulb.SlashCommand,
    name="create",
    description="Create a timed poll",
):
    duration = lightbulb.integer(
        "duration",
        "How long voting remains open",
        choices=list(POLL_DURATION_CHOICES),
    )
    ping_role = lightbulb.role(
        "ping-role",
        "Optional role to notify once when the poll is posted",
        default=None,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not await _require_admin(ctx):
            return
        if int(self.duration) not in POLL_DURATION_HOURS:
            await ctx.respond(
                components=_notice("Invalid duration", "Choose a duration from 1 hour to 2 days."),
                ephemeral=True,
            )
            return
        if self.ping_role is not None and int(self.ping_role.guild_id) != _guild_id(ctx):
            await ctx.respond(
                components=_notice("Wrong server role", "The notification role must belong to this server."),
                ephemeral=True,
            )
            return

        state_id = uuid.uuid4().hex
        await insert_state(mongo, {
            "_id": state_id,
            "type": "poll_create",
            "user_id": int(ctx.user.id),
            "guild_id": _guild_id(ctx),
            "channel_id": int(ctx.channel_id),
            "duration_hours": int(self.duration),
            "ping_role_id": int(self.ping_role.id) if self.ping_role is not None else None,
        }, ttl=POLL_MODAL_TTL)

        await ctx.respond_with_modal(
            title="Create a timed poll",
            custom_id=f"poll_create_submit:{state_id}",
            components=[
                ModalActionRow().add_text_input(
                    "title", "Question", required=True, min_length=1, max_length=100,
                    placeholder="Which option should we choose?",
                ),
                ModalActionRow().add_text_input(
                    "description", "Details (optional)", required=False, max_length=1000,
                    style=hikari.TextInputStyle.PARAGRAPH,
                ),
                ModalActionRow().add_text_input(
                    "option_1", "Option 1", required=True, min_length=1, max_length=80,
                ),
                ModalActionRow().add_text_input(
                    "option_2", "Option 2", required=True, min_length=1, max_length=80,
                ),
                ModalActionRow().add_text_input(
                    "option_3", "Option 3 (optional)", required=False, max_length=80,
                ),
            ],
        )


@poll.register()
class ViewPoll(
    lightbulb.SlashCommand,
    name="view",
    description="View recent polls or the named voters for one poll",
):
    poll_id = lightbulb.string(
        "poll-id", "Poll ID from /poll view or /poll active", default=None, max_length=32,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not await _require_admin(ctx):
            return
        await ctx.defer(ephemeral=True)
        guild_id = _guild_id(ctx)
        requested = str(self.poll_id or "").strip()
        if requested:
            document = await poll_store.get_poll(
                mongo, guild_id=guild_id, poll_id=requested,
            )
            components = (
                build_named_voter_components(document)
                if document is not None
                else _notice(
                    "Poll not found",
                    "That poll is not retained in this server. Check the ID or recent history.",
                )
            )
        else:
            documents = await poll_store.list_recent_polls(
                mongo, guild_id=guild_id, limit=MAX_RECENT_POLLS,
            )
            components = build_poll_list_components(documents, active_only=False)
        await ctx.respond(
            components=components,
            ephemeral=True,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )


@poll.register()
class ActivePolls(
    lightbulb.SlashCommand,
    name="active",
    description="List polls that are currently open",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not await _require_admin(ctx):
            return
        await ctx.defer(ephemeral=True)
        documents = await poll_store.list_active_polls(
            mongo, guild_id=_guild_id(ctx), limit=MAX_RECENT_POLLS,
        )
        await ctx.respond(
            components=build_poll_list_components(documents, active_only=True),
            ephemeral=True,
            user_mentions=False,
            role_mentions=False,
            mentions_everyone=False,
        )


@register_action(
    "poll_create_submit", is_modal=True, no_return=True, requires_state=True,
)
@lightbulb.di.with_di
async def poll_create_submit(
    ctx: lightbulb.components.ModalContext,
    action_id: str,
    user_id: int,
    guild_id: int,
    channel_id: int,
    duration_hours: int,
    ping_role_id: int | None,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    if _guild_id(ctx) != int(guild_id) or int(ctx.user.id) != int(user_id):
        await ctx.respond(
            components=_notice("Poll setup unavailable", "Only the administrator who opened this form can submit it."),
            ephemeral=True,
        )
        return
    if not _is_admin(ctx):
        await ctx.respond(
            components=_notice("Administrator access required", "Your permissions changed before this poll was submitted."),
            ephemeral=True,
        )
        return

    await ctx.defer(ephemeral=True)
    await delete_state(mongo, action_id)

    title = _modal_value(ctx, "title")
    description = _modal_value(ctx, "description")
    raw_options = [
        _modal_value(ctx, "option_1"),
        _modal_value(ctx, "option_2"),
        _modal_value(ctx, "option_3"),
    ]
    options = [value for value in raw_options if value]
    if not title or len(options) < 2:
        await ctx.respond(
            components=_notice("Poll not created", "A question and at least two non-empty options are required."),
            ephemeral=True,
        )
        return
    if len({value.casefold() for value in options}) != len(options):
        await ctx.respond(
            components=_notice("Poll not created", "Each option must be different."),
            ephemeral=True,
        )
        return
    if int(duration_hours) not in POLL_DURATION_HOURS:
        await ctx.respond(
            components=_notice("Poll not created", "The saved duration is no longer valid. Run `/poll create` again."),
            ephemeral=True,
        )
        return

    now = _utcnow()
    poll_id = uuid.uuid4().hex[:12]
    document = {
        "_id": poll_id,
        "guild_id": int(guild_id),
        "channel_id": int(channel_id),
        "creator_id": int(user_id),
        "created_at": now,
        "ends_at": now + timedelta(hours=int(duration_hours)),
        "duration_hours": int(duration_hours),
        "ping_role_id": int(ping_role_id) if ping_role_id is not None else None,
        "title": title,
        "description": description,
        "options": [
            {"id": index, "text": value}
            for index, value in enumerate(options, start=1)
        ],
        "votes": {},
        "active": True,
    }

    message = None
    try:
        message = await bot.rest.create_message(
            channel=int(channel_id),
            components=build_poll_components(document),
            user_mentions=False,
            role_mentions=[int(ping_role_id)] if ping_role_id is not None else False,
            mentions_everyone=False,
            mentions_reply=False,
        )
        document["message_id"] = int(message.id)
        document = await poll_store.create_poll(mongo, document, observed_at=now)
    except Exception:
        _log.exception("poll creation failed guild=%s actor=%s", guild_id, user_id)
        if message is not None:
            try:
                await bot.rest.edit_message(
                    channel=int(channel_id),
                    message=int(message.id),
                    components=_notice(
                        "Poll unavailable",
                        "This poll could not be saved, so voting is disabled.",
                    ),
                    user_mentions=False,
                    role_mentions=False,
                    mentions_everyone=False,
                    mentions_reply=False,
                )
            except Exception:
                _log.exception("failed to disable orphan poll message message=%s", message.id)
            try:
                await bot.rest.delete_message(int(channel_id), int(message.id))
            except Exception:
                _log.exception("failed to remove orphan poll message message=%s", message.id)
        await ctx.respond(
            components=_notice(
                "Poll not created",
                "The poll could not be posted or saved. Nothing was scheduled; the failure was logged.",
            ),
            ephemeral=True,
        )
        return

    _schedule_poll(document)
    await ctx.respond(
        components=_notice(
            "Poll created",
            f"Posted poll `{poll_id}` in <#{int(channel_id)}>; it closes {_discord_timestamp(document['ends_at'])}.",
            color=GOLD_ACCENT,
        ),
        ephemeral=True,
    )


@register_action("poll_vote", no_return=True)
@lightbulb.di.with_di
async def poll_vote(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    poll_id, separator, raw_choice = action_id.partition("|")
    guild_id = _guild_id(ctx)
    try:
        choice = int(raw_choice)
    except (TypeError, ValueError):
        choice = 0
    if not separator or not poll_id or guild_id is None or choice < 1:
        await ctx.respond("This poll button is invalid. Run the poll command again.", ephemeral=True)
        return

    document = None
    async with _lock_for(poll_id):
        current = await poll_store.get_poll(mongo, guild_id=guild_id, poll_id=poll_id)
        valid_choices = {
            int(option["id"]) for option in (current or {}).get("options", ())
        }
        if current is not None and choice in valid_choices:
            document = await poll_store.record_vote(
                mongo,
                guild_id=guild_id,
                poll_id=poll_id,
                user_id=int(ctx.user.id),
                choice=choice,
            )
            if document is not None:
                await _sync_poll_message(mongo, bot, document)

    if document is None:
        current = await poll_store.get_poll(mongo, guild_id=guild_id, poll_id=poll_id)
        if current is not None and current.get("active") and _as_utc(current["ends_at"]) <= _utcnow():
            await _finalize_poll(
                mongo, bot, guild_id=guild_id, poll_id=poll_id, reason="expired",
            )
        await ctx.respond("This poll is closed or no longer available.", ephemeral=True)
        return

    selected = next(
        option for option in document["options"] if int(option["id"]) == choice
    )
    await ctx.respond(
        f"Vote recorded for **{_escape_user_text(selected['text'])}**. You can change it while the poll is open.",
        ephemeral=True,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


@register_action("poll_details", no_return=True)
@lightbulb.di.with_di
async def poll_details(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    if not await _require_admin(ctx):
        return
    document = await poll_store.get_poll(
        mongo, guild_id=_guild_id(ctx), poll_id=action_id,
    )
    if document is None:
        await ctx.respond(
            components=_notice("Poll not found", "This poll is no longer retained in this server."),
            ephemeral=True,
        )
        return
    await ctx.respond(
        components=build_named_voter_components(document),
        ephemeral=True,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


@register_action("poll_end", no_return=True)
@lightbulb.di.with_di
async def poll_end(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **_kwargs,
) -> None:
    if not await _require_admin(ctx):
        return
    document, changed = await _finalize_poll(
        mongo,
        bot,
        guild_id=_guild_id(ctx),
        poll_id=action_id,
        reason="manual",
    )
    if document is None:
        message = "This poll is no longer retained in this server."
    elif changed:
        message = f"Poll `{action_id}` has been closed."
    else:
        message = f"Poll `{action_id}` was already closed."
    await ctx.respond(message, ephemeral=True)


loader.command(poll)
