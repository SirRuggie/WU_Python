"""Staff "Link account": link a Clash account to the applicant in ClashPerk.

Who may link: recruiters (ticket access) who also hold the dashboard permission
"Save weights from Discord", the same permission ``/fwa weight`` uses for link
writes. The permission is checked when the control opens and again just before
the write. All link rules live in ``utils.clashperk_link_writes``: one write per
call, no overwrite of another user's link, no retry of an uncertain write. No
in-game API token is ever requested, and no link is ever removed here.
"""
from __future__ import annotations

import logging

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as Row,
    ModalActionRowBuilder as ModalRow,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from extensions.commands.tickets import account_sync, player_info
from utils import clashperk_link_writes as writes
from utils.clan_weight_client import WeightClientError, request as bridge
from utils.constants import WU_GOLD, WU_RED
from utils.mongo import MongoClient

_log = logging.getLogger(__name__)

NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)
NOT_RECRUITER = "You must be a recruiter, and the ticket must exist."
NO_PERMISSION = "You need the dashboard permission Save weights from Discord to link accounts."
MAX_CHOICES = 24


def card(content: str, *rows: Row, accent: int = WU_GOLD) -> list:
    return [Container(accent_color=accent, components=[Text(content=content), *rows])]


def _escape(value: object, limit: int = 40) -> str:
    from extensions.commands.linked_accounts import _escape_markdown
    return _escape_markdown(value, max_raw_length=limit)


def _applicant(ticket: dict) -> str:
    user_id = int(ticket.get("user_id") or 0)
    return f"<@{user_id}>" if user_id else "the applicant"


def typed_tags(ticket: dict) -> list[str]:
    """Valid tags the applicant typed in chat that are not linked yet."""
    from extensions.commands.tickets.console import _mentioned_tags
    linked = {a.tag for a in account_sync.snapshot_from_ticket(ticket).current_accounts}
    tags = []
    for raw in _mentioned_tags(ticket):
        tag = writes.normalize_player_tag(raw)
        if tag and tag not in linked and tag not in tags:
            tags.append(tag)
    return tags[:MAX_CHOICES]


def start_view(ticket: dict) -> list:
    tid = str(ticket["_id"])
    lines = [
        "## 🔗 Link account",
        f"Link a Clash account to {_applicant(ticket)} in ClashPerk.",
    ]
    rows = []
    choices = typed_tags(ticket)
    if choices:
        lines.append("Select a tag the applicant typed, or enter a player tag.")
        row = Row()
        menu = row.add_text_menu(f"ticket_link_pick:{tid}", placeholder="Tags typed in this ticket")
        for tag in choices:
            menu.add_option(tag, tag)
        rows.append(row)
    buttons = Row()
    buttons.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"ticket_link_tag:{tid}", label="Enter player tag")
    rows.append(buttons)
    return card("\n".join(lines), *rows)


def confirm_view(ticket: dict, tag: str) -> list:
    tid = str(ticket["_id"])
    row = Row()
    row.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"ticket_link_confirm:{tid}|{tag}", label="Link")
    row.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"ticket_link_back:{tid}", label="Back")
    return card(f"## 🔗 Link account\nLink `{tag}` to {_applicant(ticket)} in ClashPerk?", row)


def result_view(ticket: dict, text: str, *, accent: int = WU_GOLD) -> list:
    row = Row()
    row.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"ticket_link_back:{ticket['_id']}", label="Link another")
    return card(text, row, accent=accent)


async def _allowed(ctx) -> str | None:
    """None when the actor holds the permission, else the reason to show."""
    try:
        await bridge("access", actor_id=ctx.user.id)
    except WeightClientError as exc:
        return NO_PERMISSION if exc.code == "forbidden" else str(exc)
    return None


async def _guard(ctx, mongo, ticket_id: str) -> tuple[dict | None, list | None]:
    """Return (ticket, None) when the actor may link, else (None, error card)."""
    ticket = await player_info._get_ticket(ctx, mongo, ticket_id)
    if ticket is None or not ticket.get("user_id"):
        return None, card(NOT_RECRUITER, accent=WU_RED)
    reason = await _allowed(ctx)
    if reason:
        return None, card(reason, accent=WU_RED)
    return ticket, None


async def link(ctx, bot, mongo, ticket_id: str, raw_tag: str) -> list:
    """Recheck access, write one link, then refresh the ticket's account list."""
    ticket, error = await _guard(ctx, mongo, ticket_id)
    if error:
        return error
    result = await writes.create_link(int(ticket["user_id"]), raw_tag)
    _log.info("Ticket ClashPerk link actor=%s ticket=%s tag=%s status=%s",
              ctx.user.id, ticket_id, result.tag, result.status)
    if result.status == writes.OTHER_OWNER:
        owner = f" (**{_escape(result.owner)}**)" if result.owner else ""
        return result_view(ticket, f"`{result.tag}`: This account is linked to a different Discord user "
                                   f"in ClashPerk{owner}. Nothing was changed.\n"
                                   "Ask the applicant to unlink it in ClashPerk first.", accent=WU_RED)
    if result.status not in (writes.LINKED, writes.ALREADY_LINKED):
        return result_view(ticket, f"`{result.tag}`: {result.message}", accent=WU_RED)
    text = f"`{result.tag}`: {result.message}"
    try:
        refreshed, delivered = await player_info.refresh_accounts(bot, mongo, ticket_id)
    except (LookupError, player_info.RefreshBusy) as exc:
        return result_view(ticket, f"{text}\nThe account list did not refresh: {exc} Select Refresh Player Info later.")
    if refreshed is None:
        return card(f"{text}\nTicket no longer exists.")
    if not delivered:
        text += "\nThe staff summary update is waiting."
    return [*result_view(refreshed, text), *player_info.panel(refreshed)]


@register_action("ticket_link", opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def on_open(ctx, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await ctx.defer(ephemeral=True)
    ticket, error = await _guard(ctx, mongo, action_id)
    await ctx.interaction.edit_initial_response(components=error or start_view(ticket), **NO_MENTIONS)


@register_action("ticket_link_back", opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def on_back(ctx, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    ticket, error = await _guard(ctx, mongo, action_id)
    await ctx.interaction.edit_initial_response(components=error or start_view(ticket), **NO_MENTIONS)


@register_action("ticket_link_pick", opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def on_pick(ctx, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    values = getattr(ctx.interaction, "values", None) or ()
    await ctx.interaction.edit_initial_response(
        components=await _confirm_or_error(ctx, mongo, action_id, values[0] if values else ""), **NO_MENTIONS)


@register_action("ticket_link_tag", opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def on_tag(ctx, action_id: str, **_):
    await ctx.respond_with_modal(
        title="Link account", custom_id=f"ticket_link_tagged:{action_id}",
        components=[ModalRow().add_text_input(
            "tag", "Player tag", placeholder="#2PP", min_length=3, max_length=16, required=True)],
    )


@register_action("ticket_link_tagged", is_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def on_tagged(ctx, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    values = {item.custom_id: item.value or "" for row in ctx.interaction.components for item in row}
    await ctx.interaction.edit_initial_response(
        components=await _confirm_or_error(ctx, mongo, action_id, values.get("tag", "")), **NO_MENTIONS)


async def _confirm_or_error(ctx, mongo, ticket_id: str, raw_tag: str) -> list:
    ticket, error = await _guard(ctx, mongo, ticket_id)
    if error:
        return error
    tag = writes.normalize_player_tag(raw_tag)
    if tag is None:
        return result_view(ticket, "Enter a valid player tag.", accent=WU_RED)
    return confirm_view(ticket, tag)


@register_action("ticket_link_confirm", opens_modal=True, preload_state=False, no_return=True)
@lightbulb.di.with_di
async def on_confirm(ctx, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED,
                     bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    ticket_id, _, tag = action_id.partition("|")
    # Remove the Link button at once so a second select cannot start a second write.
    await ctx.interaction.edit_initial_response(components=card(f"Linking `{tag[:16]}`…"), **NO_MENTIONS)
    components = await link(ctx, bot, mongo, ticket_id, tag)
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)
