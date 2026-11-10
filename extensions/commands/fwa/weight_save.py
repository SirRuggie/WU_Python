"""Save ``/fwa weight`` results to the official Clan weights through the dashboard bridge.

Flow: private "Save this weight?" question -> linked-account dropdown (ClashKing and
ClashPerk) or a player tag -> optional confirm -> save -> "Another account?" -> the
next account and its storage weight -> ... -> "All weights done". A typed player tag
is linked to the member in ClashPerk (unverified) just before its save. Each saved
weight posts its public panel once. The bot never writes the Clan weights ledger
itself.

Each round is its own session row: the first round holds the command's loot; later
rounds hold no loot and ask for the storage weight after the account is selected.
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
from utils import clashperk_link_writes, war_weight
from utils.clan_weight_client import WeightClientError, request as bridge
from utils.clan_weight_store import validate_weight
from utils.component_state import get_state, insert_state, update_state
from utils.constants import GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT
from utils.member_events import safe_text
from utils.mongo import MongoClient

log = logging.getLogger(__name__)
SESSION_TYPE = "fwa_weight_save"
SESSION_TTL = timedelta(minutes=30)
# Longer than the bridge client's 45-second request timeout.
SAVE_LOCK = timedelta(seconds=90)
CONFIRM_TYPE = "fwa_weight_confirm"
ENTRY_TYPE = "fwa_weight_entry"
SAVING = "A save for this weight is still running. Wait a moment, then select Try again."
STALE_CONFIRM = "This confirm button is out of date. Select the account again."
STORAGES = 5
MAX_LOOT = 100000
MAX_ROUNDS = 25  # A select menu holds 25 options; more accounts than this is not one member.
NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)
EXPIRED = "This weight panel expired. Run `/fwa weight` again."
HANDLED = "This weight was already handled. Run `/fwa weight` again for a new one."
LINK_OK = (clashperk_link_writes.LINKED, clashperk_link_writes.ALREADY_LINKED)


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
        "another": ("Another account", hikari.ButtonStyle.PRIMARY),
        "done": ("All weights done", hikari.ButtonStyle.SECONDARY),
    }
    row = Row()
    for name in names:
        label, style = labels[name]
        row.add_interactive_button(style, f"fws_{name}:{sid}", label=label)
    return row


def first_round(state: dict) -> bool:
    """The first round carries the command's loot; later rounds ask for it."""
    return isinstance(state.get("loot"), int)


def leave(state: dict) -> str:
    """The way out of a round: Post only first, All weights done after a save."""
    return "post" if first_round(state) else "done"


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


def parse_loot(value: str) -> int | None:
    text = (value or "").strip().replace(",", "")
    if not text.isdigit():
        return None
    loot = int(text)
    return loot if 1 <= loot <= MAX_LOOT else None


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
    """Mark the round handled exactly once; a double click cannot post twice.

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
    """Take the round's single save slot before any link or bridge write; None when taken."""
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


async def post_panel(bot, mongo, state: dict, loot: int, saved_for: str | None = None) -> bool:
    config = await war_weight.load(mongo, state["guild_id"])
    available = await load_th_emojis(bot)
    try:
        await bot.rest.create_message(
            channel=state["channel_id"],
            components=build_weight_panel(loot, config, available, saved_for=saved_for),
            **NO_MENTIONS,
        )
    except hikari.HTTPError:
        log.exception("Could not post the /fwa weight panel channel=%s", state["channel_id"])
        return False
    return True


def actor_name(ctx) -> str:
    member = getattr(ctx.interaction, "member", None)
    return str(getattr(member, "display_name", None) or getattr(ctx.user, "username", "") or "")


def saved_lines(saved: list) -> str:
    return "\n".join(f"• {row}" for row in saved if isinstance(row, str))


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
        "round": 1,
        "saved": [],
        "saved_tags": [],
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


async def clear_preview(mongo, sid: str) -> None:
    """Leaving a confirm preview (Back, Try again, another account) voids its button."""
    await update_state(mongo, {"_id": sid}, {"$set": {"pending_token": None}})


async def accounts_view(ctx, bot, mongo, state: dict) -> list:
    sid, out = state["_id"], leave(state)
    await clear_preview(mongo, sid)
    try:
        data = await bridge("accounts", actor_id=ctx.user.id, target_id=str(state["target_id"]))
    except WeightClientError as exc:
        if exc.code == "links_unavailable":
            return card(f"{exc}", buttons(sid, "retry", "tag", out), accent=RED_ACCENT)
        if exc.code == "forbidden":
            return await post_without_access(bot, mongo, state, exc, state.get("loot"))
        return card(f"{exc}", buttons(sid, "retry", out), accent=RED_ACCENT)
    accounts = data.get("accounts") or []
    if not accounts:
        return card(
            "This user has no linked accounts. Enter a player tag to link it in ClashPerk and save.",
            buttons(sid, "tag", out),
        )
    config = await war_weight.load(mongo, state["guild_id"])
    available = await load_th_emojis(bot)
    done_now = set(state.get("saved_tags") or ())
    row = Row()
    menu = row.add_text_menu(f"fws_pick:{sid}", placeholder="Select an account")
    for account in accounts:
        th = account.get("town_hall")
        name = (account.get("name") or account["tag"])[:60]
        label = f"{name} · TH{th}" if th else f"{name} · TH unknown"
        weight = account.get("weight")
        saved = f"Saved {weight:,}" if isinstance(weight, int) else "No saved weight"
        if account["tag"] in done_now:
            saved += " · Done now"
        emoji = parse_emoji(war_weight.emoji_for(th, config, available)) if th else None
        menu.add_option(
            label[:100], account["tag"], description=f"{account['tag']} · {saved}"[:100],
            emoji=emoji if emoji is not None else hikari.UNDEFINED,
        )
    menu.add_option("Other account", "other", description="Enter a player tag to link and save")
    if first_round(state):
        total, *_ = assess(state["loot"], config)
        lines = f"## Select the account\nWeight **{total:,}** for <@{state['target_id']}>."
    else:
        lines = (f"## Select the next account\nFor <@{state['target_id']}>. "
                 "Enter its storage weight after you select it.")
    if data.get("hidden"):
        lines += f"\n{data['hidden']} more linked accounts are not listed. Select Other account for them."
    return card(lines, row, buttons(sid, out))


async def choose(ctx, bot, mongo, state: dict, player_tag: str, loot: int, *, link: bool = False) -> list:
    """Show the confirm step for one account, or save at once when nothing needs a look.

    ``link`` is True for a typed player tag: it is linked in ClashPerk before the save.
    """
    sid, out = state["_id"], leave(state)
    await clear_preview(mongo, sid)
    try:
        account = (await bridge("lookup", actor_id=ctx.user.id, tag=player_tag))["account"]
    except WeightClientError as exc:
        if exc.code == "forbidden":
            return await post_without_access(bot, mongo, state, exc, loot)
        return card(f"{exc}", buttons(sid, "back", out), accent=RED_ACCENT)
    except (KeyError, TypeError):
        return card("Weight saving is unavailable now. Try again later.", buttons(sid, "back", out), accent=RED_ACCENT)
    account = dict(account, link=bool(link))
    config = await war_weight.load(mongo, state["guild_id"])
    total, th, status, ranges = assess(loot, config)
    if account.get("weight") == total and not link:
        return await finish(ctx, bot, mongo, state, account, loot, already=True)
    warning = th_warning(th, status, ranges, account.get("town_hall"))
    # A typed tag always confirms: staff see the account before it is linked.
    if not link and account.get("weight") is None and not warning:
        return await save(ctx, bot, mongo, state, account, loot)
    # Each preview gets its own confirm token; only the newest one can save.
    token = uuid.uuid4().hex
    pending = {key: account.get(key) for key in ("tag", "name", "revision", "weight", "town_hall", "link")}
    pending["loot"] = int(loot)
    await insert_state(mongo, {
        "_id": token, "type": CONFIRM_TYPE, "session_id": sid,
        "user_id": state["user_id"], "guild_id": state["guild_id"], "pending": pending,
    }, ttl=SESSION_TTL)
    await update_state(mongo, {"_id": sid, "done": {"$ne": True}}, {"$set": {"pending_token": token}})
    account_th = account.get("town_hall")
    th_line = f"TH{account_th}" if isinstance(account_th, int) else "TH unknown"
    lines = [f"## Confirm\n{account_label(account)} · {th_line}"]
    if account.get("weight") == total:
        lines.append(f"Already saved: {total:,}")
    elif isinstance(account.get("weight"), int):
        lines.append(f"Saved: {account['weight']:,} → New: {total:,}")
    else:
        lines.append(f"New: {total:,}")
    if warning:
        lines.append(warning)
    if link:
        lines.append(f"🔗 Links to <@{state['target_id']}> in ClashPerk first.")
    if account.get("weight") == total:
        label = "Link"
    elif isinstance(account.get("weight"), int):
        label = "Replace"
    else:
        label = "Save"
    row = Row()
    row.add_interactive_button(hikari.ButtonStyle.PRIMARY, f"fws_confirm:{token}", label=label)
    row.add_interactive_button(hikari.ButtonStyle.SECONDARY, f"fws_back:{sid}", label="Back")
    return card("\n".join(lines), row)


async def link_account(ctx, state: dict, account: dict) -> tuple[str | None, list | None, WeightClientError | None]:
    """Link a typed tag to the member in ClashPerk. Return (note, error_card, forbidden)."""
    sid, out = state["_id"], leave(state)
    try:
        # Linking needs the same permission as saving; recheck just before the write.
        await bridge("access", actor_id=ctx.user.id)
    except WeightClientError as exc:
        if exc.code == "forbidden":
            return None, None, exc
        return None, card(f"{exc}", buttons(sid, "back", out), accent=RED_ACCENT), None
    result = await clashperk_link_writes.create_link(int(state["target_id"]), account["tag"])
    if result.status == clashperk_link_writes.LINKED:
        return "🔗 Linked in ClashPerk.", None, None
    if result.status == clashperk_link_writes.ALREADY_LINKED:
        return "🔗 Already linked in ClashPerk.", None, None
    # Fixed helper text only; raw ClashPerk text is never shown. Nothing was saved.
    return None, card(f"{result.message}\nThe weight was not saved.", buttons(sid, "back", out),
                      accent=RED_ACCENT), None


async def save(ctx, bot, mongo, state: dict, account: dict, loot: int) -> list:
    sid, out = state["_id"], leave(state)
    config = await war_weight.load(mongo, state["guild_id"])
    total, *_ = assess(loot, config)
    lock = await lock_save(mongo, sid)
    if lock is None:
        return await not_claimed(mongo, sid)
    note = None
    try:
        if account.get("link"):
            note, failed, forbidden = await link_account(ctx, state, account)
            if forbidden is not None:
                await unlock_save(mongo, sid, lock)
                return await post_without_access(bot, mongo, state, forbidden, loot)
            if failed is not None:
                await unlock_save(mongo, sid, lock)
                return failed
            if account.get("weight") == total:
                saved = dict(account)
                return await finish(ctx, bot, mongo, state, saved, loot, already=True, lock=lock, note=note)
        result = await bridge(
            "save", actor_id=ctx.user.id, actor_name=actor_name(ctx),
            tag=account["tag"], weight=total, revision=int(account.get("revision") or 0),
        )
    except WeightClientError as exc:
        await unlock_save(mongo, sid, lock)
        prefix = f"{note}\n" if note else ""
        if exc.code == "conflict" or exc.uncertain:
            return card(f"{prefix}{exc}", buttons(sid, "retry", out), accent=RED_ACCENT)
        if exc.code == "forbidden":
            return await post_without_access(bot, mongo, state, exc, loot)
        return card(f"{prefix}{exc}", buttons(sid, "back", out), accent=RED_ACCENT)
    except BaseException:
        await unlock_save(mongo, sid, lock)
        raise
    saved = result.get("account") or account
    return await finish(ctx, bot, mongo, state, saved, loot, already=not result.get("changed"), lock=lock,
                        note=note)


async def post_without_access(bot, mongo, state: dict, exc, loot: int | None) -> list:
    """Access was removed during the flow: post the panel once (if a weight exists) and save nothing."""
    if not await claim(mongo, state["_id"]):
        return await not_claimed(mongo, state["_id"])
    if not isinstance(loot, int):
        return card(f"Nothing was saved.\n{exc}", accent=RED_ACCENT)
    if await post_panel(bot, mongo, state, loot):
        return card(f"Panel posted. Nothing was saved.\n{exc}", accent=RED_ACCENT)
    return card(f"The panel could not be posted. Run `/fwa weight` again.\n{exc}", accent=RED_ACCENT)


async def next_round(mongo, state: dict, label: str, tag: str) -> str | None:
    """Open the next round's session; None when the loop must end here."""
    rnd = int(state.get("round") or 1) + 1
    if rnd > MAX_ROUNDS:
        return None
    sid = uuid.uuid4().hex
    saved = [*(state.get("saved") or []), label][-MAX_ROUNDS:]
    saved_tags = [*(state.get("saved_tags") or []), tag][-MAX_ROUNDS:]
    try:
        await insert_state(mongo, {
            "_id": sid, "type": SESSION_TYPE, "user_id": state["user_id"], "guild_id": state["guild_id"],
            "channel_id": state["channel_id"], "target_id": state["target_id"], "loot": None,
            "round": rnd, "saved": saved, "saved_tags": saved_tags, "done": False,
        }, ttl=SESSION_TTL)
    except Exception:
        log.exception("Could not store the next /fwa weight round")
        return None
    return sid


async def finish(ctx, bot, mongo, state: dict, account: dict, loot: int, *, already: bool,
                 lock: str | None = None, note: str | None = None) -> list:
    config = await war_weight.load(mongo, state["guild_id"])
    total, *_ = assess(loot, config)
    label = account_label(account)
    clan = safe_text(account.get("clan_name"), 40) if account.get("clan_name") else "No clan"
    head = f"Already saved for {label}." if already else f"Saved {total:,} for {label} ({clan})."
    if note:
        head = f"{note}\n{head}"
    if not await claim(mongo, state["_id"], lock=lock):
        if already or lock is None:
            return await not_claimed(mongo, state["_id"])
        # The save lock expired and Post only won: report the write that did happen.
        return card(f"{head}\nThe panel was already posted without the saved line.")
    if await post_panel(bot, mongo, state, loot, saved_for=label):
        head += "\nPanel posted."
    else:
        head += "\nThe panel could not be posted. Run `/fwa weight` without a user to post it."
    following = await next_round(mongo, state, label, account["tag"])
    if following is None:
        return card(head, accent=GREEN_ACCENT)
    return card(f"{head}\n\n**Another account?**", buttons(following, "another", "done"), accent=GREEN_ACCENT)


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


@register_action("fws_another", preload_state=False)
@lightbulb.di.with_di
async def on_another(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                     bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    return await guarded(ctx, mongo, action_id, lambda state: accounts_view(ctx, bot, mongo, state))


@register_action("fws_done", preload_state=False)
@lightbulb.di.with_di
async def on_done(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    async def work(state):
        if not await claim(mongo, state["_id"]):
            return await not_claimed(mongo, state["_id"])
        lines = saved_lines(state.get("saved") or [])
        return card(f"## All weights done\n{lines}" if lines else "## All weights done", accent=GREEN_ACCENT)

    return await guarded(ctx, mongo, action_id, work)


@register_action("fws_post", preload_state=False)
@lightbulb.di.with_di
async def on_post(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                  bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    async def work(state):
        if not first_round(state):
            return card(HANDLED)
        if not await claim(mongo, state["_id"]):
            return await not_claimed(mongo, state["_id"])
        if await post_panel(bot, mongo, state, state["loot"]):
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
        stale = card(STALE_CONFIRM, buttons(sid, "back", leave(state)), accent=RED_ACCENT)
        if not isinstance(pending, dict) or not pending.get("tag") or not isinstance(pending.get("loot"), int):
            return stale
        # Consume the token atomically: a button works once, and only while its
        # preview is the current screen.
        result = await update_state(
            mongo, {"_id": sid, "done": {"$ne": True}, "pending_token": action_id},
            {"$set": {"pending_token": None}},
        )
        if not getattr(result, "modified_count", 0):
            return stale
        return await save(ctx, bot, mongo, state, pending, pending["loot"])

    return await guarded(ctx, mongo, sid, work)


def tag_modal() -> list:
    return [ModalRow().add_text_input(
        "tag", "Player tag", placeholder="#2PP", min_length=3, max_length=16, required=True,
    )]


def loot_modal(with_tag: bool) -> list:
    rows = tag_modal() if with_tag else []
    rows.append(ModalRow().add_text_input(
        "loot", "Storage weight", placeholder="30000", min_length=1, max_length=7, required=True,
    ))
    return rows


async def open_entry_modal(ctx, mongo, state: dict, player_tag: str | None) -> None:
    """Later rounds: ask for the storage weight (and the tag for Other account)."""
    token = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": token, "type": ENTRY_TYPE, "session_id": state["_id"],
        "user_id": state["user_id"], "guild_id": state["guild_id"], "tag": player_tag,
    }, ttl=SESSION_TTL)
    title = "Enter player tag and weight" if player_tag is None else "Enter storage weight"
    await ctx.respond_with_modal(title=title, custom_id=f"fws_entry:{token}",
                                 components=loot_modal(player_tag is None))


async def open_tag_modal(ctx, mongo, sid) -> None:
    try:
        state = await session(ctx, mongo, sid)
    except SessionError as exc:
        await ctx.respond(str(exc), ephemeral=True)
        return
    if not first_round(state):
        await open_entry_modal(ctx, mongo, state, None)
        return
    await ctx.respond_with_modal(title="Enter player tag", custom_id=f"fws_tagged:{sid}", components=tag_modal())


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
    try:
        state = await session(ctx, mongo, action_id)
    except SessionError as exc:
        state, error = None, exc
    if state is not None and values and not first_round(state):
        await open_entry_modal(ctx, mongo, state, values[0])
        return
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    if state is None:
        components = card(str(error))
    elif values:
        components = await choose(ctx, bot, mongo, state, values[0], state["loot"])
    else:
        components = await accounts_view(ctx, bot, mongo, state)
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


def modal_values(ctx) -> dict:
    return {item.custom_id: item.value or "" for row in ctx.interaction.components for item in row}


@register_action("fws_tagged", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_tagged(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    player_tag = modal_values(ctx).get("tag", "").strip()

    async def work(state):
        if not first_round(state):
            return card(HANDLED)
        return await choose(ctx, bot, mongo, state, player_tag, state["loot"], link=True)

    components = await guarded(ctx, mongo, action_id, work)
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


@register_action("fws_entry", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def on_entry(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED,
                   bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    entry = await get_state(mongo, action_id)
    if (
        not entry
        or entry.get("type") != ENTRY_TYPE
        or entry.get("user_id") != int(ctx.user.id)
        or entry.get("guild_id") != int(ctx.interaction.guild_id or 0)
    ):
        await ctx.interaction.edit_initial_response(components=card(EXPIRED), **NO_MENTIONS)
        return
    values = modal_values(ctx)
    typed = entry.get("tag") is None
    player_tag = values.get("tag", "").strip() if typed else entry["tag"]
    loot = parse_loot(values.get("loot", ""))
    sid = entry["session_id"]

    async def work(state):
        if loot is None:
            return card(f"Enter a storage weight from 1 to {MAX_LOOT:,}.",
                        buttons(sid, "back", leave(state)), accent=RED_ACCENT)
        total = loot * STORAGES
        try:
            validate_weight(total, STORAGES)
        except ValueError:
            return card(f"Cannot save {total:,}. Saved weights must be a multiple of 1,000. Check the loot value.",
                        buttons(sid, "back", leave(state)), accent=RED_ACCENT)
        return await choose(ctx, bot, mongo, state, player_tag, loot, link=typed)

    components = await guarded(ctx, mongo, sid, work)
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)
