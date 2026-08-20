"""Recruiter-only authoring commands for durable applicant flags."""

from __future__ import annotations

import re

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands.tickets import flag_store, store, ticket
from extensions.commands.tickets.console import (
    refresh_open_staff_contexts_for_flag_best_effort,
    request_hub_refresh_best_effort,
)
from utils.mongo import MongoClient


ACCENT_BLUE = 0x4A90F5
ACCENT_GREEN = 0x4BCE7A
ACCENT_RED = 0xF0555A
DISCORD_MESSAGE_TEXT_LIMIT = 4000

FLAG_LABELS = {
    flag_store.FLAG_BLACKLISTED: "Blacklisted",
    flag_store.FLAG_DENIED_BEFORE: "Previously denied",
    flag_store.FLAG_NOT_LOYAL: "Not loyal to WU",
}
FLAG_SOURCES = flag_store.FLAG_SOURCES
DISCORD_ID_RE = re.compile(r"^\d{17,20}$")


def _tags(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values: list[str] = []
    for token in re.split(r"[\s,]+", str(raw).strip()):
        if not token:
            continue
        tag = token.upper()
        if not tag.startswith("#"):
            tag = "#" + tag
        if tag not in values:
            values.append(tag)
    return tuple(values)


def _discord_ids(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values = tuple(dict.fromkeys(
        token for token in re.split(r"[\s,]+", str(raw).strip()) if token
    ))
    if any(not DISCORD_ID_RE.fullmatch(value) for value in values):
        raise ValueError("Every Discord ID must have 17 to 20 numbers.")
    return values


def _safe(value, limit=500) -> str:
    text = str(value or "").strip()
    for character in ("\\", "`", "*", "_", "~", "|", ">"):
        text = text.replace(character, "\\" + character)
    return text[:limit]


def _panel(title: str, body: str, *, accent: int) -> list[Container]:
    heading = f"## {title}"
    # Components V2 caps the aggregate Text Display content in a message, not
    # each field independently. Reserve the heading before truncating the body.
    body_budget = max(1, DISCORD_MESSAGE_TEXT_LIMIT - len(heading))
    return [Container(
        accent_color=accent,
        components=[
            Text(content=heading),
            Separator(divider=True),
            Text(content=str(body)[:body_budget] or " "),
        ],
    )]


async def _reply(ctx, title: str, body: str, *, accent: int) -> None:
    await ctx.interaction.edit_initial_response(
        components=_panel(title, body, accent=accent),
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


@ticket.register()
class FlagAddCommand(
    lightbulb.SlashCommand,
    name="flag-add",
    description="Add or update an applicant flag (Recruiter only)",
):
    kind = lightbulb.string(
        "kind",
        "Flag type",
        choices=[
            lightbulb.Choice(name="Blacklisted", value=flag_store.FLAG_BLACKLISTED),
            lightbulb.Choice(name="Previously denied", value=flag_store.FLAG_DENIED_BEFORE),
            lightbulb.Choice(name="Not loyal to WU", value=flag_store.FLAG_NOT_LOYAL),
        ],
    )
    reason = lightbulb.string(
        "reason",
        "Short staff reason shown on every matching ticket",
        min_length=2,
        max_length=500,
    )
    discord_ids = lightbulb.string(
        "discord-ids",
        "One or more Discord IDs, separated by commas",
        default=None,
        max_length=100,
    )
    player_tags = lightbulb.string(
        "player-tags",
        "One or more player tags, separated by commas",
        default=None,
        max_length=100,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        # Flag authorization and persistence can cross the interaction's
        # three-second response deadline; acknowledge before either await.
        await ctx.defer(ephemeral=True)
        try:
            discord_ids = _discord_ids(self.discord_ids)
            player_tags = _tags(self.player_tags)
            result = await flag_store.set_flag_authorized(
                mongo,
                member=ctx.member,
                actor_name=ctx.user.username,
                kind=self.kind,
                discord_ids=discord_ids,
                player_tags=player_tags,
                source=FLAG_SOURCES[self.kind],
                reason=self.reason,
            )
        except (ValueError, flag_store.FlagConflictError) as exc:
            await _reply(ctx, "Flag not saved", str(exc), accent=ACCENT_RED)
            return
        if result.outcome == store.UNAUTHORIZED:
            await _reply(
                ctx,
                "Recruiter access required",
                "Only recruiters can add applicant flags.",
                accent=ACCENT_RED,
            )
            return
        document = result.doc or {}
        await refresh_open_staff_contexts_for_flag_best_effort(bot, mongo, document)
        await request_hub_refresh_best_effort(bot, mongo, reason="flag changed")
        ids = ", ".join(f"`{value}`" for value in document.get("discord_ids") or ()) or "none"
        tags = ", ".join(f"`{_safe(value, 15)}`" for value in document.get("player_tags") or ()) or "none"
        await _reply(
            ctx,
            "Flag saved",
            (
                f"**Flag:** `{document.get('_id')}` · {FLAG_LABELS[self.kind]}\n"
                f"**Discord IDs:** {ids}\n"
                f"**Player tags:** {tags}\n"
                f"**Why:** {_safe(document.get('reason'))}"
            ),
            accent=ACCENT_GREEN,
        )


@ticket.register()
class FlagRemoveCommand(
    lightbulb.SlashCommand,
    name="flag-remove",
    description="Deactivate one applicant flag (Recruiter only)",
):
    flag_id = lightbulb.string(
        "flag-id",
        "Exact flag ID shown by /ticket flags or ticket detail",
        min_length=6,
        max_length=80,
    )
    reason = lightbulb.string(
        "reason",
        "Why this flag no longer applies",
        min_length=2,
        max_length=500,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        try:
            result = await flag_store.deactivate_flag_authorized(
                mongo,
                self.flag_id,
                member=ctx.member,
                actor_name=ctx.user.username,
                reason=self.reason,
            )
        except flag_store.FlagConflictError as exc:
            await _reply(ctx, "Flag not changed", str(exc), accent=ACCENT_RED)
            return
        if result.outcome == store.UNAUTHORIZED:
            await _reply(
                ctx,
                "Recruiter access required",
                "Only recruiters can remove applicant flags.",
                accent=ACCENT_RED,
            )
            return
        if result.outcome == store.MISSING:
            await _reply(
                ctx,
                "Flag not found",
                "Check the exact flag ID and try again.",
                accent=ACCENT_RED,
            )
            return
        if not result.won:
            await _reply(
                ctx,
                "Flag not changed",
                result.reason or "That flag changed before this command finished.",
                accent=ACCENT_RED,
            )
            return
        await refresh_open_staff_contexts_for_flag_best_effort(
            bot, mongo, result.doc or {}
        )
        await request_hub_refresh_best_effort(bot, mongo, reason="flag removed")
        await _reply(
            ctx,
            "Flag removed",
            f"`{self.flag_id}` is inactive. Its audit history was kept.",
            accent=ACCENT_GREEN,
        )


@ticket.register()
class FlagsCommand(
    lightbulb.SlashCommand,
    name="flags",
    description="Find active flags by Discord ID or player tag",
):
    identity = lightbulb.string(
        "identity",
        "A Discord ID or #player tag",
        min_length=3,
        max_length=20,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        # The read is staff-only too: reasons can contain private recruiter notes.
        from extensions.commands.tickets import perms

        if not await perms.is_recruiter(ctx.member, mongo):
            await _reply(
                ctx,
                "Recruiter access required",
                "Only recruiters can read applicant flags.",
                accent=ACCENT_RED,
            )
            return
        identity = str(self.identity).strip()
        try:
            discord_ids = _discord_ids(identity) if identity.isdigit() else ()
            player_tags = _tags(identity) if identity.startswith("#") else ()
        except ValueError as exc:
            await _reply(ctx, "Flag search not run", str(exc), accent=ACCENT_RED)
            return
        if not discord_ids and not player_tags:
            await _reply(
                ctx,
                "Flag search not run",
                "Use a Discord ID or a player tag that starts with #.",
                accent=ACCENT_RED,
            )
            return
        try:
            records = await flag_store.list_for_identity(
                mongo,
                discord_ids=discord_ids,
                player_tags=player_tags,
            )
        except ValueError as exc:
            await _reply(ctx, "Flag search not run", str(exc), accent=ACCENT_RED)
            return
        if not records:
            await _reply(
                ctx,
                "No active flags",
                "No staff flag matches that Discord ID or player tag.",
                accent=ACCENT_BLUE,
            )
            return
        lines: list[str] = []
        for record in records[:10]:
            kind = str(record.get("kind") or "")
            lines.append(
                f"**{FLAG_LABELS.get(kind, kind.replace('_', ' ').title())}** · "
                f"`{record.get('_id')}`\n"
                f"{_safe(record.get('reason'))}\n"
                f"Source: {_safe(record.get('source'), 120)}"
            )
        await _reply(
            ctx,
            "Active applicant flags",
            "\n\n".join(lines),
            accent=ACCENT_BLUE,
        )
