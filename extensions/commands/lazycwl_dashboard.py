# extensions/commands/lazycwl_dashboard.py
"""/lazycwl - Administrator-only dashboard over the LazyCWL saved-list
service (extensions/commands/fwa/lazy_cwl_service.py).

S0 (home), S1 (save list), and S2 (remind now) so far. The remaining four
action buttons exist but reply "Coming soon" until a later brief
(design-01-main.md B4-B6) wires them up. The old
`/fwa lazycwl-*` commands (extensions/commands/fwa/lazy_cwl.py) stay live and
untouched; this is a new, separate command.

Rules carried over from extensions/commands/todo.py:25-60 and enforced here:

  ONE COLON in every custom_id. Action name before the colon, action_id
  after. The selected clan tag lives in the action_id ("ALL" for every
  clan, "NONE" for no selection, or the clan's own tag) - never in
  component_state, so routing is stateless.

  FOUR TYPE SIZES: "##" panel title, "###" block heading, "**bold**" clan
  name, plain row text.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import coc
import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu,
    SelectOptionBuilder as SelectOption,
    InteractiveButtonBuilder as Button,
)

from extensions.components import register_action
from extensions.commands.fwa import lazy_cwl_service as service
from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT
from utils import lazy_cwl_store as store

loader = lightbulb.Loader()

_log = logging.getLogger(__name__)

MAX_SELECT_OPTIONS = 25
MAX_CLAN_OPTIONS = MAX_SELECT_OPTIONS - 1  # one slot spent on "All clans"

# Mongo clan-type filter value. See D010: a plain literal is correct here -
# it is a query value, not user-facing text, and the banned-word scan only
# walks render-facing keyword arguments (content/label/placeholder/
# description), so it was never at risk of being flagged.
_FWA_CLAN_TYPE = "FWA"

COMING_SOON_NOTE = "\U0001F6A7 Coming soon."

# D010: the compact multi-clan table is one Text component regardless of how
# many rows it holds, so the 40-component Components V2 ceiling is never at
# risk from row count - only the 4000-char Text budget is. Stay well clear
# of it.
COMPACT_TEXT_BUDGET = 3800


def _encode_tag(selected_tag: Optional[str]) -> str:
    """Selected clan tag -> the action_id segment of a custom_id."""
    if selected_tag is None:
        return "NONE"
    return selected_tag


def _decode_tag(action_id: str) -> Optional[str]:
    """The action_id segment of a custom_id -> a selected clan tag."""
    if action_id == "NONE":
        return None
    return action_id


def _format_expires(expires_at) -> str:
    return f"{expires_at.day} {expires_at.strftime('%B')}"


def _full_card(name: str, doc: Optional[dict], away_counts: dict, orphan: bool = False) -> list:
    """One clan's full card - up to 5 lines. Only used when exactly one clan
    is selected (D010); the ALL/nothing-selected case renders the compact
    table instead."""
    suffix = " (not in clan table)" if orphan else ""
    lines = [Text(content=f"### {name}{suffix}")]

    if doc is None:
        lines.append(Text(content="No list saved yet."))
        return lines

    players = doc.get("players", [])
    away = away_counts.get(doc["clan_tag"])
    away_text = "?" if away is None else str(away)

    reminders = doc.get("reminders", {}) or {}
    if reminders.get("enabled"):
        minutes = reminders.get("every_minutes")
        auto_text = f"\U0001F514 Auto reminders: On, every {minutes} minutes"
    else:
        auto_text = "\U0001F514 Auto reminders: Off"

    lines.append(Text(content=f"\U0001F465 {len(players)} players saved"))
    lines.append(Text(content=f"\U0001F6AA {away_text} away now"))
    lines.append(Text(content=auto_text))

    expires_at = doc.get("expires_at")
    if expires_at is not None:
        lines.append(Text(content=f"⏰ Expires {_format_expires(expires_at)}"))

    return lines


def _compact_row(name: str, doc: Optional[dict], away_counts: dict, orphan: bool = False) -> str:
    """One line of the D010 compact table."""
    suffix = " (not in clan table)" if orphan else ""
    if doc is None:
        return f"**{name}**{suffix} · no list yet"

    away = away_counts.get(doc["clan_tag"])
    away_text = "?" if away is None else str(away)

    reminders = doc.get("reminders", {}) or {}
    if reminders.get("enabled"):
        auto_text = f"On every {reminders.get('every_minutes')} min"
    else:
        auto_text = "Off"

    expires_at = doc.get("expires_at")
    expiry_text = _format_expires(expires_at) if expires_at is not None else "?"

    return (
        f"**{name}**{suffix} · \U0001F465 {len(doc.get('players', []))}"
        f" · \U0001F6AA {away_text} · \U0001F514 {auto_text} · ⏰ {expiry_text}"
    )


def _build_compact_text(rows: list, away_counts: dict) -> Text:
    """Join every row into ONE Text component, hard-capped under
    COMPACT_TEXT_BUDGET chars, truncating with "... and {k} more" (D010).
    `rows` is [(name, tag, doc, orphan), ...] already sorted by name."""
    lines: list = []
    total_len = 0
    for name, _tag, doc, orphan in rows:
        line = _compact_row(name, doc, away_counts, orphan)
        added_len = len(line) + (1 if lines else 0)
        if total_len + added_len > COMPACT_TEXT_BUDGET:
            break
        lines.append(line)
        total_len += added_len

    remaining = len(rows) - len(lines)
    if remaining > 0:
        more_line = f"… and {remaining} more"
        # Make room for the "more" line if it would blow the budget itself.
        while lines and total_len + len(more_line) + 1 > COMPACT_TEXT_BUDGET:
            dropped = lines.pop()
            total_len -= len(dropped) + 1
            remaining = len(rows) - len(lines)
            more_line = f"… and {remaining} more"
        lines.append(more_line)

    return Text(content="\n".join(lines))


def _rows_union(clans: list, lists_by_tag: dict) -> list:
    """[(name, normalized_tag, doc, orphan)] - the UNION of `clans` and
    active lists, sorted by name (D010). A list whose clan_tag is not in
    `clans` still appears, marked orphan so it stays finishable."""
    clan_tags = {store._normalize_tag(clan.get("tag", "")) for clan in clans if clan.get("tag")}

    rows = [
        (clan.get("name") or "Unknown clan", store._normalize_tag(clan.get("tag", "")), lists_by_tag.get(store._normalize_tag(clan.get("tag", ""))), False)
        for clan in clans
    ]
    rows.extend(
        (doc.get("clan_name") or "Unknown clan", tag, doc, True)
        for tag, doc in lists_by_tag.items()
        if tag not in clan_tags
    )
    rows.sort(key=lambda row: row[0])
    return rows


def _disabled_states(selected_tag: Optional[str], clans: list, lists_by_tag: dict) -> dict:
    """`lists_by_tag` must already be keyed by normalized (# + upper) tags."""
    if selected_tag is None:
        return {"save": True, "remind": True, "auto": True, "players": True, "add": True, "finish": True}

    if selected_tag == "ALL":
        tags = [store._normalize_tag(clan.get("tag", "")) for clan in clans if clan.get("tag")]
        any_has_list = any(tag in lists_by_tag for tag in tags)
        any_missing_list = any(tag not in lists_by_tag for tag in tags)
        return {
            "save": not any_missing_list,
            "remind": not any_has_list,
            "auto": not any_has_list,
            "players": True,
            "add": True,
            "finish": not any_has_list,
        }

    has_list = store._normalize_tag(selected_tag) in lists_by_tag
    return {
        "save": has_list,
        "remind": not has_list,
        "auto": not has_list,
        "players": not has_list,
        "add": not has_list,
        "finish": not has_list,
    }


def _button(label: str, emoji: str, action: str, selected_tag: Optional[str], disabled: bool) -> Button:
    return Button(
        style=hikari.ButtonStyle.SECONDARY,
        custom_id=f"{action}:{_encode_tag(selected_tag)}",
        label=label,
        emoji=emoji,
        is_disabled=disabled,
    )


def render_home(
    lists: list,
    clans: list,
    selected_tag: Optional[str],
    now,
    away_counts: Optional[dict] = None,
    note: Optional[str] = None,
) -> list:
    """Pure S0 renderer. No I/O; every caller passes in what it needs.

    D010: with ONE clan selected, render that clan's full card. With ALL or
    nothing selected, render ONE compact-table Text row per clan/orphan-list,
    so the 40-component ceiling is never at risk from clan count. Rows are
    the UNION of `clans` (mongo.clans) and active lists (a list whose tag is
    not in `clans` still shows, marked orphan). Tags are normalised
    (# + upper) before any comparison - see D006/D010.
    """
    away_counts = away_counts or {}
    lists_by_tag = {store._normalize_tag(doc["clan_tag"]): doc for doc in lists}
    clan_tags = {store._normalize_tag(clan.get("tag", "")) for clan in clans if clan.get("tag")}

    body = [
        Text(content="## Lazy CWL"),
        Text(content="Pick a clan, then press a button."),
    ]
    if note:
        body.append(Text(content=note))
    body.append(Separator())

    options = [SelectOption(label="\U0001F30D All clans", value="ALL")]
    # A clan doc with no tag can't be selected (no value to route on) - skip
    # it entirely rather than emit a null select value (builder-08 fix).
    taggeable_clans = [clan for clan in clans if clan.get("tag")]
    shown_clans = taggeable_clans[:MAX_CLAN_OPTIONS]
    for clan in shown_clans:
        tag = clan["tag"]
        ntag = store._normalize_tag(tag)
        description = "✅ list saved" if ntag in lists_by_tag else "no list yet"
        options.append(SelectOption(
            label=clan.get("name", "Unknown clan"),
            value=tag,
            description=description,
        ))

    # Orphan lists (D010 MUST-FIX 3): a list whose clan_tag has no matching
    # clan doc still needs to be selectable so Finish is reachable.
    orphan_docs = sorted(
        (doc for tag, doc in lists_by_tag.items() if tag not in clan_tags),
        key=lambda doc: doc.get("clan_name") or "",
    )
    for doc in orphan_docs[: max(0, MAX_SELECT_OPTIONS - len(options))]:
        options.append(SelectOption(
            label=doc.get("clan_name") or "Unknown clan",
            value=doc["clan_tag"],
            description="(not in clan table)",
        ))

    body.append(ActionRow(components=[
        TextSelectMenu(
            custom_id="lazycwl_pick:home",
            placeholder="Choose a clan",
            max_values=1,
            options=options,
        )
    ]))
    if len(taggeable_clans) > MAX_CLAN_OPTIONS:
        body.append(Text(content=f"Showing the first {MAX_CLAN_OPTIONS} clans."))

    if selected_tag is None or selected_tag == "ALL":
        rows = _rows_union(clans, lists_by_tag)
        if rows:
            body.append(Separator())
            body.append(_build_compact_text(rows, away_counts))
    else:
        normalized_selected = store._normalize_tag(selected_tag)
        clan = next((c for c in clans if store._normalize_tag(c.get("tag", "")) == normalized_selected), None)
        doc = lists_by_tag.get(normalized_selected)
        if clan is not None:
            name, orphan = clan.get("name") or "Unknown clan", False
        elif doc is not None:
            name, orphan = doc.get("clan_name") or "Unknown clan", True
        else:
            name = None
        if name is not None:
            body.append(Separator())
            body.extend(_full_card(name, doc, away_counts, orphan=orphan))

    body.append(Separator())

    disabled = _disabled_states(selected_tag, clans, lists_by_tag)
    body.append(ActionRow(components=[
        _button("\U0001F4BE Save list", "\U0001F4BE", "lazycwl_save", selected_tag, disabled["save"]),
        _button("\U0001F4E3 Remind now", "\U0001F4E3", "lazycwl_remind", selected_tag, disabled["remind"]),
        _button("\U0001F514 Auto reminders", "\U0001F514", "lazycwl_auto", selected_tag, disabled["auto"]),
    ]))
    body.append(ActionRow(components=[
        _button("\U0001F465 Player list", "\U0001F465", "lazycwl_players", selected_tag, disabled["players"]),
        _button("➕ Add player", "➕", "lazycwl_add", selected_tag, disabled["add"]),
        _button("\U0001F3C1 Finish", "\U0001F3C1", "lazycwl_finish", selected_tag, disabled["finish"]),
    ]))
    body.append(ActionRow(components=[
        _button("\U0001F504 Refresh", "\U0001F504", "lazycwl_home", selected_tag, False),
    ]))

    return [Container(accent_color=BLUE_ACCENT, components=body)]


async def build_home(mongo: MongoClient, selected_tag: Optional[str], note: Optional[str] = None) -> list:
    """Load clans, active lists, and away counts, then render S0.

    Store/service only - never touches the saved-list collection directly.
    One clan's away_players failure shows "? away now" on its own card
    instead of failing the whole panel.
    """
    clans = await mongo.clans.find({"type": _FWA_CLAN_TYPE}).to_list(length=None)
    clans = sorted(clans, key=lambda clan: clan.get("name") or "")

    lists = await store.list_active(mongo)

    away_counts: dict = {}
    for doc in lists:
        try:
            away = await service.away_players(doc)
            away_counts[doc["clan_tag"]] = len(away)
        except Exception:
            _log.warning(
                "lazycwl_dashboard.build_home: away_players failed clan_tag=%s",
                doc.get("clan_tag"), exc_info=True,
            )

    now = datetime.now(timezone.utc)
    return render_home(lists, clans, selected_tag, now, away_counts, note=note)


def _result_name(result: dict) -> str:
    """A result dict's display name - clan_name, falling back to whatever tag
    the call was made with (builder-08 merges `clan_tag` into every result
    before rendering, since save_list's "not found" path and every
    remind_now path omit it - D008's key sets don't include it)."""
    return result.get("clan_name") or result.get("clan_tag") or "?"


def _chunk_rows(rows: list, budget: int = COMPACT_TEXT_BUDGET) -> list:
    """One joined row string, or two if it would exceed `budget` chars - S1/S2
    never need more than one Text component per chunk at realistic clan
    counts, but this keeps the ceiling honest per the brief."""
    joined = "\n".join(rows)
    if len(joined) <= budget:
        return [joined]
    mid = len(rows) // 2
    return ["\n".join(rows[:mid]), "\n".join(rows[mid:])]


def _back_button(selected_tag: Optional[str]) -> ActionRow:
    return ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"lazycwl_home:{_encode_tag(selected_tag)}",
            label="⬅️ Back",
            emoji="⬅️",
        )
    ])


def render_save_result(results: list, selected_tag: Optional[str]) -> list:
    """Pure S1 renderer. `results` are lazy_cwl_service.save_list()'s D008
    dicts, one per clan attempted, each with `clan_tag` guaranteed present."""
    rows = []
    ok = already = failed = 0
    for result in results:
        name = _result_name(result)
        if result.get("already_saved"):
            already += 1
            when = result.get("existing_saved_at")
            when_text = _format_expires(when) if when is not None else "?"
            rows.append(f"ℹ️ **{name}** · already saved on {when_text}")
        elif result.get("ok"):
            ok += 1
            rows.append(
                f"✅ **{name}** · {result.get('player_count', 0)} players saved"
                f" · {result.get('linked_count', 0)} linked to Discord"
            )
        else:
            failed += 1
            rows.append(f"❌ **{name}** · {result.get('error') or 'Something went wrong.'}")

    body = [Text(content="## \U0001F4BE Save list")]
    body.extend(Text(content=chunk) for chunk in _chunk_rows(rows))
    if selected_tag == "ALL":
        body.append(Text(content=f"{ok} saved · {already} already saved · {failed} failed"))
    body.append(Separator())
    body.append(_back_button(selected_tag))
    return [Container(accent_color=BLUE_ACCENT, components=body)]


async def build_save_result(mongo: MongoClient, action_id: str, saved_by: int) -> list:
    """Save `action_id`'s tag, or every FWA clan for "ALL" (same union source
    build_home uses, clans only - not orphan lists, per the brief). One
    failing call becomes a single ❌ row, never a crash."""
    if action_id == "ALL":
        clans = await mongo.clans.find({"type": _FWA_CLAN_TYPE}).to_list(length=None)
        clans = sorted(clans, key=lambda clan: clan.get("name") or "")
        tags = [clan["tag"] for clan in clans if clan.get("tag")]
    else:
        tags = [action_id]

    results = []
    for tag in tags:
        try:
            result = await service.save_list(tag, saved_by=saved_by)
        except Exception as exc:
            _log.warning(
                "lazycwl_dashboard.build_save_result: save_list failed clan_tag=%s",
                tag, exc_info=True,
            )
            result = {"ok": False, "error": str(exc) or "Something went wrong."}
        if not result.get("clan_tag"):
            result = {**result, "clan_tag": tag}
        results.append(result)

    return render_save_result(results, action_id)


def render_remind_result(results: list, selected_tag: Optional[str]) -> list:
    """Pure S2 renderer. `results` are lazy_cwl_service.remind_now()'s D008
    dicts, one per clan attempted, each with `clan_tag` guaranteed present."""
    rows = []
    sent = home = failed = 0
    for result in results:
        name = _result_name(result)
        if result.get("error"):
            failed += 1
            rows.append(f"❌ **{name}** · {result.get('error')}")
        elif result.get("sent"):
            sent += 1
            rows.append(
                f"\U0001F4E8 **{name}** · {result.get('away_count', 0)} of"
                f" {result.get('total_count', 0)} away · message sent"
            )
        else:
            home += 1
            rows.append(f"\U0001F3E0 **{name}** · everyone is here")

    body = [Text(content="## \U0001F4E3 Remind now")]
    body.extend(Text(content=chunk) for chunk in _chunk_rows(rows))
    if selected_tag == "ALL":
        body.append(Text(content=f"{sent} sent · {home} everyone home · {failed} failed"))
    body.append(Separator())
    body.append(_back_button(selected_tag))
    return [Container(accent_color=BLUE_ACCENT, components=body)]


async def build_remind_result(mongo: MongoClient, action_id: str) -> list:
    """Same fan-out as build_save_result, calling service.remind_now."""
    if action_id == "ALL":
        clans = await mongo.clans.find({"type": _FWA_CLAN_TYPE}).to_list(length=None)
        clans = sorted(clans, key=lambda clan: clan.get("name") or "")
        tags = [clan["tag"] for clan in clans if clan.get("tag")]
    else:
        tags = [action_id]

    results = []
    for tag in tags:
        try:
            result = await service.remind_now(tag)
        except Exception as exc:
            _log.warning(
                "lazycwl_dashboard.build_remind_result: remind_now failed clan_tag=%s",
                tag, exc_info=True,
            )
            result = {"ok": False, "error": str(exc) or "Something went wrong."}
        if not result.get("clan_tag"):
            result = {**result, "clan_tag": tag}
        results.append(result)

    return render_remind_result(results, action_id)


class LazyCwl(
    lightbulb.SlashCommand,
    name="lazycwl",
    description="Lazy CWL dashboard",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not (ctx.member and ctx.member.permissions & hikari.Permissions.ADMINISTRATOR):
            await ctx.respond("Only server admins can use this.", ephemeral=True)
            return

        await ctx.defer(ephemeral=True)
        components = await build_home(mongo, selected_tag=None)
        await ctx.interaction.edit_initial_response(components=components)


loader.command(LazyCwl)


@register_action("lazycwl_pick")
@lightbulb.di.with_di
async def handle_pick(
    ctx=None,
    action_id: str = "home",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    values = getattr(ctx.interaction, "values", None) or []
    selected_tag = values[0] if values else None
    return await build_home(mongo, selected_tag=selected_tag)


@register_action("lazycwl_home")
@lightbulb.di.with_di
async def handle_home(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await build_home(mongo, selected_tag=_decode_tag(action_id))


async def _placeholder(action_id: str, mongo: MongoClient) -> list:
    return await build_home(mongo, selected_tag=_decode_tag(action_id), note=COMING_SOON_NOTE)


@register_action("lazycwl_save")
@lightbulb.di.with_di
async def handle_save(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await build_save_result(mongo, action_id, ctx.user.id)


@register_action("lazycwl_remind")
@lightbulb.di.with_di
async def handle_remind(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await build_remind_result(mongo, action_id)


@register_action("lazycwl_auto")
@lightbulb.di.with_di
async def handle_auto(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await _placeholder(action_id, mongo)


@register_action("lazycwl_players")
@lightbulb.di.with_di
async def handle_players(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await _placeholder(action_id, mongo)


@register_action("lazycwl_add")
@lightbulb.di.with_di
async def handle_add(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await _placeholder(action_id, mongo)


@register_action("lazycwl_finish")
@lightbulb.di.with_di
async def handle_finish(
    ctx=None,
    action_id: str = "NONE",
    mongo: MongoClient = lightbulb.di.INJECTED,
    **kwargs,
) -> list:
    return await _placeholder(action_id, mongo)


# ======================== BOT STARTUP EVENT ========================

_started = False


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(
    event: hikari.StartedEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    coc_api: coc.Client = lightbulb.di.INJECTED,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    """Start the LazyCWL service once per process, even if this event
    fires more than once - service.start() is itself idempotent, but the
    flag here also stops it from being called a second time at all."""
    global _started
    if _started:
        return
    _started = True
    await service.start(bot, coc_api, mongo)


@loader.listener(hikari.StoppingEvent)
async def on_stopping(event: hikari.StoppingEvent) -> None:
    global _started
    _started = False
    await service.stop()
