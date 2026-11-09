"""Save a ``/fwa weight`` result to the official Clan weights through the dashboard bridge.

Flow: private "Save this weight?" question -> linked-account dropdown (ClashKing and
ClashPerk) or a player tag -> optional confirm -> save. The public panel posts exactly
once, after Save or Post only. The bot never writes the Clan weights ledger itself.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    MessageActionRowBuilder as Row,
    ModalActionRowBuilder as ModalRow,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands.fwa.weight import (
    assess_weight, build_weight_panel, get_th_emoji, load_th_emojis,
)
from extensions.components import register_action
from utils import war_weight
from utils.clan_weight_client import WeightClientError, request as bridge
from utils.clan_weight_store import validate_weight
from utils.component_state import get_state, insert_state, update_state
from utils.constants import GOLD_ACCENT, RED_ACCENT
from utils.member_events import safe_text
from utils.mongo import MongoClient

log = logging.getLogger(__name__)
SESSION_TYPE = "fwa_weight_save"
SESSION_TTL = timedelta(minutes=30)
# Longer than the bridge client's 45-second request timeout.
SAVE_LOCK = timedelta(seconds=90)
CONFIRM_TYPE = "fwa_weight_confirm"
SAVING = "A save for this weight is still running. Wait a moment, then select Try again."
STALE_CONFIRM = "This confirm button is out of date. Select the account again."
STORAGES = 5
NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)
EXPIRED = "This weight panel expired. Run `/fwa weight` again."
HANDLED = "This weight was already handled. Run `/fwa weight` again for a new one."


class SessionError(ValueError):
    pass


# ---------------------------------------------------------------- rendering


def card(content: str, *rows: Row, accent: int = GOLD_ACCENT) -> list:
    return [Container(accent_color=accent, components=[Text(content=content), *rows])]


def buttons(sid: str, *names: str) -> Row:
    labels = {
        "save": ("Save", hikari.ButtonStyle.PRIMARY),
        "post": ("Post only", hikari.ButtonStyle.SECONDARY),
        "retry": ("Try again", hikari.ButtonStyle.SECONDARY),
        "tag": ("Enter player tag", hikari.ButtonStyle.SECONDARY),
        "back": ("Back", hikari.ButtonStyle.SECONDARY),
    }
    row = Row()
    for name in names:
        label, style = labels[name]
        row.add_interactive_button(style, f"fws_{name}:{sid}", label=label)
    return row


def account_label(account: dict) -> str:
    """Escaped "Name #TAG" text for Markdown."""
    name = account.get("name") or account["tag"]
    return f"{safe_text(name, 40)} `{account['tag']}`"


def th_text(total: int, th: int | None, status: str, ranges) -> str:
    if status == "exact":
        return f"TH{th}"
    if status == "between" and th is not None and th < max(ranges):
        return f"between TH{th} and TH{min(level for level in ranges if level > th)}"
    return "outside the Town Hall ranges"


def th_warning(th: int | None, status: str, ranges, account_th) -> str | None:
    """Warning when the account's Town Hall does not fit the weight; None when it fits."""
    if not isinstance(account_th, int):
        return None
    if status == "exact":
        return None if account_th == th else f"⚠️ This account is TH{account_th}. The weight is TH{th}."
    if status == "between" and th is not None and th < max(ranges):
        upper = min(level for level in ranges if level > th)
        if account_th in (th, upper):
            return None
        return f"⚠️ This account is TH{account_th}. The weight is between TH{th} and TH{upper}."
    return f"⚠️ This account is TH{account_th}. The weight is outside the Town Hall ranges."


def parse_emoji(value: str):
    try:
        return hikari.Emoji.parse(value)
    except (ValueError, TypeError):
        return None


def assess(loot: int, config):
    ranges = war_weight.ranges(config)
    total, th, status, _ = assess_weight(loot, ranges)
    return total, th, status, ranges


# ---------------------------------------------------------------- session


async def session(ctx, mongo, sid: str) -> dict:
    state = await get_state(mongo, sid)
    if (
        not state
        or state.get("type") != SESSION_TYPE
        or state.get("user_id") != int(ctx.user.id)
        or state.get("guild_id") != int(ctx.interaction.guild_id or 0)
    ):
        raise SessionError(EXPIRED)
    if state.get("done"):
        raise SessionError(HANDLED)
    return state


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def claim(mongo, sid: str, *, lock: str | None = None) -> bool:
    """Mark the session handled exactly once; a double click cannot post twice.

    Without ``lock`` the claim fails while a save is running. The save that holds
    ``lock`` claims through its own token.
    """
    query = {"_id": sid, "done": {"$ne": True}}
    if lock is None:
        query["saving_until"] = {"$not": {"$gt": utcnow()}}
    else:
        query["saving_token"] = lock
    result = await update_state(mongo, query, {"$set": {"done": True}})
    return bool(getattr(result, "modified_count", 0))


async def lock_save(mongo, sid: str) -> str | None:
    """Take the session's single save slot before any bridge write; None when taken."""
    token, now = uuid.uuid4().hex, utcnow()
    result = await update_state(
        mongo,
        {"_id": sid, "done": {"$ne": True}, "saving_until": {"$not": {"$gt": now}}},
        {"$set": {"saving_token": token, "saving_until": now + SAVE_LOCK}},
    )
    return token if getattr(result, "modified_count", 0) else None


async def unlock_save(mongo, sid: str, token: str) -> None:
    await update_state(
        mongo, {"_id": sid, "saving_token": token},
        {"$set": {"saving_token": None, "saving_until": None}},
    )


async def not_claimed(mongo, sid: str) -> list:
    """Explain a failed claim: handled already, or a save is still running."""
    state = await get_state(mongo, sid)
    if state and not state.get("done"):
        return card(SAVING, buttons(sid, "retry"))
    return card(HANDLED)


async def post_panel(bot, mongo, state: dict, saved_for: str | None = None) -> bool:
    config = await war_weight.load(mongo, state["guild_id"])
    available = await load_th_emojis(bot)
    try:
        await bot.rest.create_message(
            channel=state["channel_id"],
            components=build_weight_panel(state["loot"], config, available, saved_for=saved_for),
            **NO_MENTIONS,
        )
    except hikari.HTTPError:
        log.exception("Could not post the /fwa weight panel channel=%s", state["channel_id"])
        return False
    return True


def actor_name(ctx) -> str:
    member = getattr(ctx.interaction, "member", None)
    return str(getattr(member, "display_name", None) or getattr(ctx.user, "username", "") or "")


# ---------------------------------------------------------------- views


async def start_save_flow(ctx, bot, mongo, loot: int, target, config, available) -> None:
    """Replace the deferred private reply with the save question, or post at once."""
    total, th, status, ranges = assess(loot, config)

    async def post_now(note: str) -> None:
        try:
            await bot.rest.create_message(
                channel=ctx.channel_id, components=build_weight_panel(loot, config, available), **NO_MENTIONS
            )
            posted = "Panel posted. Nothing was saved."
        except hikari.HTTPError:
            log.exception("Could not post the /fwa weight panel channel=%s", ctx.channel_id)
            posted = "The panel could not be posted. Run `/fwa weight` again."
        await ctx.interaction.edit_initial_response(components=card(f"{posted}\n{note}"), **NO_MENTIONS)

    try:
        await bridge("access", actor_id=ctx.user.id)
    except WeightClientError as exc:
        await post_now(str(exc))
        return
    sid = uuid.uuid4().hex
    state = {
        "_id": sid,
        "type": SESSION_TYPE,
        "user_id": int(ctx.user.id),
        "guild_id": int(ctx.guild_id),
        "channel_id": int(ctx.channel_id),
        "target_id": int(target.id),
        "loot": int(loot),
        "done": False,
    }
    try:
        await insert_state(mongo, state, ttl=SESSION_TTL)
    except Exception:
        log.exception("Could not store the /fwa weight save session")
        await post_now("Weight saving is unavailable now. Try again later.")
        return
    emoji = get_th_emoji(th, config, available)
    question = (
        f"## Save weight\n{emoji} **{total:,}** ({th_text(total, th, status, ranges)})\n"
        f"Save this weight for <@{int(target.id)}>?"
    )
    try:
        validate_weight(total, STORAGES)
    except ValueError:
        question += (
            f"\n\nCannot save {total:,}. Saved weights must be a multiple of 1,000. Check the loot value."
        )
        components = card(question, buttons(sid, "post"))
    else:
        components = card(question, buttons(sid, "save", "post"))
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


async def accounts_view(ctx, bot, mongo, state: dict) -> list:
    sid = state["_id"]
    try:
        data = await bridge("accounts", actor_id=ctx.user.id, target_id=str(state["target_id"]))
    except WeightClientError as exc:
        if exc.code == "links_unavailable":
            return card(f"{exc}", buttons(sid, "retry", "tag", "post"), accent=RED_ACCENT)
        if exc.code == "forbidden":
            return await post_without_access(bot, mongo, state, exc)
        return card(f"{exc}", buttons(sid, "retry", "post"), accent=RED_ACCENT)
    accounts = data.get("accounts") or []
    if not accounts:
        return card(
            "This user has no linked accounts. Link the accounts first, or enter a player tag.",
            buttons(sid, "tag", "post"),
        )
    config = await war_weight.load(mongo, state["guild_id"])
    available = await load_th_emojis(bot)
    row = Row()
    menu = row.add_text_menu(f"fws_pick:{sid}", placeholder="Select an account")
    for account in accounts:
        th = account.get("town_hall")
        name = (account.get("name") or account["tag"])[:60]
        label = f"{name} · TH{th}" if th else f"{name} · TH unknown"
        weight = account.get("weight")
        saved = f"Saved {weight:,}" if isinstance(weight, int) else "No saved weight"
        emoji = parse_emoji(war_weight.emoji_for(th, config, available)) if th else None
        menu.add_option(
            label[:100], account["tag"], description=f"{account['tag']} · {saved}"[:100],
            emoji=emoji if emoji is not None else hikari.UNDEFINED,
        )
    menu.add_option("Other account", "other", description="Enter a player tag")
    total, *_ = assess(state["loot"], config)
    lines = f"## Select the account\nWeight **{total:,}** for <@{state['target_id']}>."
    if data.get("hidden"):
        lines += f"\n{data['hidden']} more linked accounts are not listed. Select Other account for them."
    return card(lines, row, buttons(sid, "post"))


async def choose(ctx, bot, mongo, state: dict, player_tag: str) -> list:
    sid = state["_id"]
    try:
        account = (await bridge("lookup", actor_id=ctx.user.id, tag=player_tag))["account"]
    except WeightClientError as exc:
        if exc.code == "forbidden":
            return await post_without_access(bot, mongo, state, exc)
        return card(f"{exc}", buttons(sid, "back", "post"), accent=RED_ACCENT)
    except (KeyError, TypeError):
        return card("Weight saving is unavailable now. Try again later.", buttons(sid, "back", "post"), accent=RED_ACCENT)
    config = await war_weight.load(mongo, state["guild_id"])
    total, th, status, ranges = assess(state["loot"], config)
    if account.get("weight") == total:
        return await finish(ctx, bot, mongo, state, account, already=True)
    warning = th_warning(th, status, ranges, account.get("town_hall"))
    if account.get("weight") is None and not warning:
        return await save(ctx, bot, mongo, state, account)
    # Each preview gets its own confirm token; only the newest one can save.
    token = uuid.uuid4().hex
    pending = {key: account.get(key) for key in ("tag", "name", "revision", "weight", "town_hall")}
    await insert_state(mongo, {
        "_id": token, "type": CONFIRM_TYPE, "session_id": sid,
        "user_id": state["user_id"], "guild_id": state["guild_id"], "pending": pending,
    }, ttl=SESSION_TTL)
    await update_state(mongo, {"_id": sid, "done": {"$ne": True}}, {"$set": {"pending_token": token}})
    lines = [f"## Confirm\n{account_label(account)}"]
    if isinstance(account.get("weight"), int):
        lines.append(f"Saved: {account['weight']:,} → New: {total:,}")
    else:
        lines.append(f"New: {total:,}")
    if warning:
        lines.append(warning)
    row = Row()
    row.add_interactive_button(
        hikari.ButtonStyle.PRIMARY, f"fws_confirm:{token}",
        label="Replace" if isinstance(account.get("weight"), int) else "Save",
    )
    row.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"fws_back:{sid}", label="Back")
    return card("\n".join(lines), row)


async def save(ctx, bot, mongo, state: dict, account: dict) -> list:
    sid = state["_id"]
    config = await war_weight.load(mongo, state["guild_id"])
    total, *_ = assess(state["loot"], config)
    lock = await lock_save(mongo, sid)
    if lock is None:
        return await not_claimed(mongo, sid)
    try:
        result = await bridge(
            "save", actor_id=ctx.user.id, actor_name=actor_name(ctx),
            tag=account["tag"], weight=total, revision=int(account.get("revision") or 0),
        )
    except WeightClientError as exc:
        await unlock_save(mongo, sid, lock)
        if exc.code == "conflict" or exc.uncertain:
            return card(f"{exc}", buttons(sid, "retry", "post"), accent=RED_ACCENT)
        if exc.code == "forbidden":
            return await post_without_access(bot, mongo, state, exc)
        return card(f"{exc}", buttons(sid, "back", "post"), accent=RED_ACCENT)
    except BaseException:
        await unlock_save(mongo, sid, lock)
        raise
    saved = result.get("account") or account
    return await finish(ctx, bot, mongo, state, saved, already=not result.get("changed"), lock=lock)


async def post_without_access(bot, mongo, state: dict, exc) -> list:
    """Access was removed during the flow: post the panel once and save nothing."""
    if not await claim(mongo, state["_id"]):
        return await not_claimed(mongo, state["_id"])
    if await post_panel(bot, mongo, state):
        return card(f"Panel posted. Nothing was saved.\n{exc}", accent=RED_ACCENT)
    return card(f"The panel could not be posted. Run `/fwa weight` again.\n{exc}", accent=RED_ACCENT)


async def finish(ctx, bot, mongo, state: dict, account: dict, *, already: bool, lock: str | None = None) -> list:
    config = await war_weight.load(mongo, state["guild_id"])
    total, *_ = assess(state["loot"], config)
    label = account_label(account)
    clan = safe_text(account.get("clan_name"), 40) if account.get("clan_name") else "No clan"
    head = f"Already saved for {label}." if already else f"Saved {total:,} for {label} ({clan})."
    if not await claim(mongo, state["_id"], lock=lock):
        if already or lock is None:
            return await not_claimed(mongo, state["_id"])
        # The save lock expired and Post only won: report the write that did happen.
        return card(f"{head}\nThe panel was already posted without the saved line.")
    if await post_panel(bot, mongo, state, saved_for=label):
        return card(f"{head}\nPanel posted.")
    return card(f"{head}\nThe panel could not be posted. Run `/fwa weight` without a user to post it.")


# ---------------------------------------------------------------- actions


async def guarded(ctx, mongo, sid, work):
    try:
        state = await session(ctx, mongo, sid)
    except SessionError as exc:
        return card(str(exc))
    return await work(state)


@register_action("fws_save", preload_state=False)
@lightbulb.di.with_di
async def on_save(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    return await guarded(ctx, mongo, action_id, lambda state: accounts_view(ctx, bot, mongo, state))


@register_action("fws_retry", preload_state=False)
@lightbulb.di.with_di
async def on_retry(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                   bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    return await guarded(ctx, mongo, action_id, lambda state: accounts_view(ctx, bot, mongo, state))


@register_action("fws_back", preload_state=False)
@lightbulb.di.with_di
async def on_back(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    return await guarded(ctx, mongo, action_id, lambda state: accounts_view(ctx, bot, mongo, state))


@register_action("fws_post", preload_state=False)
@lightbulb.di.with_di
async def on_post(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    async def work(state):
        if not await claim(mongo, state["_id"]):
            return await not_claimed(mongo, state["_id"])
        if await post_panel(bot, mongo, state):
            return card("Panel posted. Nothing was saved.")
        return card("The panel could not be posted. Run `/fwa weight` again.", accent=RED_ACCENT)

    return await guarded(ctx, mongo, action_id, work)


@register_action("fws_confirm", preload_state=False)
@lightbulb.di.with_di
async def on_confirm(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                     bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    preview = await get_state(mongo, action_id)
    if (
        not preview
        or preview.get("type") != CONFIRM_TYPE
        or preview.get("user_id") != int(ctx.user.id)
        or preview.get("guild_id") != int(ctx.interaction.guild_id or 0)
    ):
        return card(EXPIRED)
    sid = preview["session_id"]

    async def work(state):
        pending = preview.get("pending")
        if state.get("pending_token") != action_id or not isinstance(pending, dict) or not pending.get("tag"):
            return card(STALE_CONFIRM, buttons(sid, "back", "post"), accent=RED_ACCENT)
        return await save(ctx, bot, mongo, state, pending)

    return await guarded(ctx, mongo, sid, work)


def tag_modal(sid: str) -> list:
    return [ModalRow().add_text_input(
        "tag", "Player tag", placeholder="#2PP", min_length=3, max_length=16, required=True,
    )]


async def open_tag_modal(ctx, mongo, sid) -> None:
    try:
        await session(ctx, mongo, sid)
    except SessionError as exc:
        await ctx.respond(str(exc), ephemeral=True)
        return
    await ctx.respond_with_modal(title="Enter player tag", custom_id=f"fws_tagged:{sid}", components=tag_modal(sid))


@register_action("fws_tag", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_tag(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await open_tag_modal(ctx, mongo, action_id)


@register_action("fws_pick", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_pick(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    values = getattr(ctx.interaction, "values", None) or ()
    if values and values[0] == "other":
        await open_tag_modal(ctx, mongo, action_id)
        return
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    components = await guarded(
        ctx, mongo, action_id,
        lambda state: choose(ctx, bot, mongo, state, values[0]) if values else accounts_view(ctx, bot, mongo, state),
    )
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


@register_action("fws_tagged", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_tagged(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    values = {item.custom_id: item.value or "" for row in ctx.interaction.components for item in row}
    player_tag = values.get("tag", "").strip()
    components = await guarded(ctx, mongo, action_id, lambda state: choose(ctx, bot, mongo, state, player_tag))
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)
