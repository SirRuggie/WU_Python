"""Administrator dashboard for saved CWL rosters.

The dashboard deliberately makes a clan selection before it offers a scoped
operation. Bulk work is confined to the selected FWA or Main section;
every operation that writes or sends has a review screen.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import coc
import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container, TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator, MessageActionRowBuilder as ActionRow,
    TextSelectMenuBuilder as TextSelectMenu, SelectOptionBuilder as SelectOption,
    InteractiveButtonBuilder as Button, ModalActionRowBuilder as ModalActionRow,
    SectionComponentBuilder as Section, ThumbnailComponentBuilder as Thumbnail,
)

from extensions.components import register_action
from extensions.commands.fwa import lazy_cwl_service as service
from utils.mongo import MongoClient
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, GOLDENROD_ACCENT, RED_ACCENT
from utils import lazy_cwl_store as store
from utils.manage_ui import breadcrumb, button_emoji

loader = lightbulb.Loader()
_log = logging.getLogger(__name__)
MAX_CLANS = 24
REMINDER_FREQUENCIES = (30, 60, 120)
_sessions: dict[str, dict[str, Any]] = {}
_SESSION_TTL = timedelta(minutes=20)


def is_admin(member: Optional[hikari.Member]) -> bool:
    return bool(member and member.permissions & hikari.Permissions.ADMINISTRATOR)


def _button(*, label: str, **kwargs: Any) -> Button:
    return Button(label=label, emoji=button_emoji(label), **kwargs)


def _tag(value: str | None) -> str:
    if value == "ALL":
        return "ALL"
    return store._normalize_tag(value or "") if value else ""


def _session(owner: int | None = None, guild: int | None = None) -> str:
    cutoff = datetime.now(timezone.utc) - _SESSION_TTL
    for key, state in list(_sessions.items()):
        if state["created"] < cutoff:
            _sessions.pop(key, None)
    token = secrets.token_urlsafe(8)
    _sessions[token] = {"owner": owner, "guild": guild, "created": datetime.now(timezone.utc), "pending": {}}
    return token


def _ctx_user(ctx) -> int | None:
    return getattr(getattr(ctx, "user", None), "id", None) or getattr(getattr(ctx, "interaction", None), "user", None) and getattr(ctx.interaction.user, "id", None)


async def _allow(ctx, token: str | None) -> bool:
    """Check admin and bind interactive panels to their creator and guild."""
    member = getattr(ctx, "member", None) or getattr(getattr(ctx, "interaction", None), "member", None)
    if not is_admin(member):
        if ctx is not None:
            await ctx.respond("Only server administrators can manage CWL rosters.", ephemeral=True)
        return False
    if not token:
        return False
    state = _sessions.get(token)
    if state is None or state["created"] < datetime.now(timezone.utc) - _SESSION_TTL:
        _sessions.pop(token, None)
        if ctx is not None:
            await ctx.respond("This dashboard has expired. Run /manage and choose CWL Return Pings again.", ephemeral=True)
        return False
    guild = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    user = _ctx_user(ctx)
    if (state["owner"] is not None and user != state["owner"]) or (state["guild"] is not None and guild != state["guild"]):
        await ctx.respond("This dashboard belongs to a different administrator or server.", ephemeral=True)
        return False
    return True


async def _fwa_clans(mongo: MongoClient) -> list[dict]:
    clans = await mongo.clans.find({"type": "FWA"}).to_list(length=None)
    return sorted((c for c in clans if c.get("tag")), key=lambda c: c.get("name") or "")


SECTION_LABELS = {"FWA": "FWA", "MAIN": "Main"}


def _section(token):
    return _sessions.get(token, {}).get("section", "FWA")


def _section_buttons(token):
    return ActionRow(components=[_button(
        style=hikari.ButtonStyle.PRIMARY if _section(token) == section else hikari.ButtonStyle.SECONDARY,
        custom_id=_id("lazycwl_section", token, section), label=label,
    ) for section, label in SECTION_LABELS.items()])


async def _clans(mongo, token):
    if _section(token) == "FWA":
        return await _fwa_clans(mongo)
    clans = await mongo.clans.find({"type": {"$in": ["Tactical", "Flexible Fun", "Competitive"]}}).to_list(length=None)
    return sorted((c for c in clans if c.get("tag")), key=lambda c: c.get("name") or "")


async def _active(mongo, token):
    return await store.list_active(mongo, section=_section(token))


def _id(action: str, token: str, value: str = "") -> str:
    return f"{action}:{token}|{value}" if value else f"{action}:{token}"


def _split(action_id: str) -> tuple[str, str]:
    token, sep, value = action_id.partition("|")
    return token, value if sep else ""


def _fmt_time(value: Any) -> str:
    if not value:
        return "Not set"
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return value
    if getattr(value, "tzinfo", None) is None:
        value = value.replace(tzinfo=timezone.utc)
    return f"<t:{int(value.timestamp())}:f>"


def _name(value: Any) -> str:
    return str(value or "Unknown")[:40].replace("@", "@\u200b").replace("\n", " ")


def _roster_description(doc: dict | None) -> str:
    if not doc:
        return "No saved roster"
    saved = doc.get("saved_at")
    expiry = doc.get("expires_at")
    if not isinstance(saved, datetime):
        return "Saved roster · capture date unavailable"
    description = f"Saved {store._utc(saved):%d %b %Y}"
    if isinstance(expiry, datetime):
        description += f" · expires {store._utc(expiry):%d %b %Y}"
    return description + " (UTC)"


def _header(clans, lists, chosen, tab, token):
    section = _section(token)
    label = SECTION_LABELS[section]
    by_tag = {_tag(doc.get("clan_tag")): doc for doc in lists}
    # Keep retired-clan rosters reachable whenever there is a free selector slot.
    entries = list(clans)
    known = {_tag(clan["tag"]) for clan in entries}
    entries.extend({"tag": tag, "name": doc.get("clan_name") or tag}
                   for tag, doc in by_tag.items() if tag not in known)
    options = [SelectOption(label=f"All {label} clans", value="ALL",
                            description="Review affected clans before applying", is_default=chosen == "ALL")]
    pages = max(1, (len(entries) + MAX_CLANS - 1) // MAX_CLANS)
    page = max(0, min(_sessions.get(token, {}).get("clan_page", 0), pages - 1))
    for clan in entries[page * MAX_CLANS:(page + 1) * MAX_CLANS]:
        tag = _tag(clan["tag"])
        options.append(SelectOption(label=_name(clan.get("name") or tag), value=tag,
                                    description=_roster_description(by_tag.get(tag)),
                                    is_default=tag == chosen))
    heading = Text(content=f"{breadcrumb('CWL Return Pings', label, tab.title())}\n## CWL Return Pings · {label} · {tab.title()}")
    clan = next((clan for clan in clans if _tag(clan["tag"]) == chosen), {})
    logo = clan.get("logo")
    if isinstance(logo, str) and logo.startswith("https://"):
        heading = Section(components=[heading], accessory=Thumbnail(media=logo))
    body = [heading, _section_buttons(token), Separator(), ActionRow(components=[TextSelectMenu(
        custom_id=_id("lazycwl_pick", token, tab), placeholder="Choose a clan",
        max_values=1, options=options)]), ActionRow(components=[
            _tab_button(label, key, tab, token, chosen)
            for label, key in (("Overview", "overview"), ("Edit saved members", "players")) if section == "FWA" or key != "reminders"])]
    if pages > 1:
        body.append(Text(content=f"-# Clan list · Page {page + 1} of {pages}"))
        body.append(ActionRow(components=[
            _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_clans_page", token, str(page - 1)), label="Previous clans", is_disabled=page == 0),
            _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_clans_page", token, str(page + 1)), label="Next clans", is_disabled=page == pages - 1),
        ]))
    return body


def _list_id(doc: dict) -> str:
    return str(doc.get("_id", ""))


def _selected_docs(lists: list[dict], tag: str) -> list[dict]:
    active = [doc for doc in lists if doc.get("status") == "active"]
    return active if tag == "ALL" else [doc for doc in active if tag and _tag(doc.get("clan_tag")) == _tag(tag)]


def _tab_button(label: str, tab: str, current: str, token: str, tag: str) -> Button:
    return _button(style=hikari.ButtonStyle.PRIMARY if tab == current else hikari.ButtonStyle.SECONDARY,
                  custom_id=_id("lazycwl_tab", token, f"{tab},{tag}"), label=label)


def _back(token: str, tag: str, tab: str = "overview") -> ActionRow:
    return ActionRow(components=[_button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_home", token, f"{tab},{tag}"), label="Back to CWL Return Pings")])


def _ping_controls(docs, token, tag, now):
    running = [d for d in docs if d.get("reminders", {}).get("enabled")]
    ends, next_runs = [], []
    for doc in docs:
        settings = doc.get("reminders") or {}
        end = store._utc(doc["expires_at"])
        if settings.get("started_at"):
            end = min(end, store._utc(settings["started_at"]) + timedelta(days=7))
        ends.append(end)
        if settings.get("enabled"):
            nxt = service.calculate_next_run(doc, now)
            if nxt < end:
                next_runs.append(nxt)
    frequencies = {d.get("reminders", {}).get("every_minutes") or 60 for d in docs}
    frequency = next(iter(frequencies)) if len(frequencies) == 1 else None
    choices = [(30, "Every 30 minutes"), (60, "Every 1 hour"), (120, "Every 2 hours")]
    summary = (f"### Return pings · {len(running)}/{len(docs)} clans running\n"
        f"Destination: <#{service.reminder_channel('FWA')}>\n"
        f"Next check: {_fmt_time(min(next_runs)) if next_runs else 'None scheduled'}\n"
        f"{'Stops' if len(set(ends)) == 1 else 'Earliest stop'}: {_fmt_time(min(ends))}\n"
        "Seven days from first start, or the 16th at 00:00 UTC, whichever comes first. "
        "Everyone home skips a ping; checks continue. Pausing or changing frequency does not restart the timer.")
    return [Text(content=summary), ActionRow(components=[TextSelectMenu(
        custom_id=_id("lazycwl_frequency_save", token, tag), placeholder="Ping frequency · saves automatically",
        max_values=1, options=[SelectOption(label=label, value=str(minutes), is_default=minutes == frequency) for minutes, label in choices],
    )]), ActionRow(components=[
        _button(style=hikari.ButtonStyle.PRIMARY, custom_id=_id("lazycwl_start_now", token, tag),
            label="Resume Return Pings" if any(d.get("reminders", {}).get("started_at") for d in docs) else "Start Return Pings", is_disabled=len(running) == len(docs)),
        _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_pause_now", token, tag), label="Pause Return Pings", is_disabled=not running),
    ])]


def render_home(lists: list, clans: list, selected_tag: Optional[str], now: datetime | None = None,
                away_counts: Optional[dict] = None, note: Optional[str] = None, *, token: str = "preview",
                tab: str = "overview") -> list:
    """Render explicit scope and status without selecting a clan for the user."""
    now = now or datetime.now(timezone.utc)
    away_counts = away_counts or {}
    section = _section(token)
    label = SECTION_LABELS[section]
    lists = [doc for doc in lists if doc.get("section", "FWA") == section]
    if section == "MAIN" and tab == "reminders": tab = "overview"
    chosen = _tag(selected_tag)
    by_tag = {_tag(doc.get("clan_tag")): doc for doc in lists if doc.get("status") == "active"}
    body = _header(clans, lists, chosen, tab, token)
    if note:
        body.append(Text(content=note))
    docs = _selected_docs(lists, chosen)
    if chosen == "ALL":
        body.append(Text(content=f"**Applies to all {label} clans**"))
    if tab == "overview":
        missing = sum(_tag(clan["tag"]) not in by_tag for clan in clans)
        capture_disabled = not chosen or (chosen == "ALL" and missing == 0)
        capture_label = "Save Current Members"
        if chosen == "ALL":
            if not clans:
                capture_label = "No clans to capture"
                summary = f"No {label} clans are configured for capture."
            elif missing == 0:
                capture_label = "All rosters already saved"
                saved_summary = "This clan already has a saved roster." if len(clans) == 1 else f"All {len(clans)} clans already have a saved roster."
                summary = f"**{saved_summary}**\nNothing new to capture. Choose a clan above to see its saved players and capture date."
            else:
                capture_label = f"Save Current Members ({missing} clans)"
                summary = f"Saved rosters: {len(docs)} · **Clans to capture: {missing}.**\nCapture saves the current members of the clans without a roster. Existing rosters are kept."
            if docs:
                if any(doc.get("legacy_snapshot_id") for doc in docs):
                    summary += "\nYour previous snapshots were carried over to this dashboard."
                summary += "\n**Need a fresh roster?** Select that clan and choose **Replace Saved Members** to review the change."
            if section == "FWA" and docs:
                known_away = [away_counts.get(d.get("clan_tag")) for d in docs]
                summary += (f"\nPlayers away: {sum(known_away)}" if all(value is not None for value in known_away) else "\nPlayers away: some statuses unavailable")
            body.append(Text(content=f"### All {label} clans\n{summary}"))
        elif not chosen:
            capture_label = "Choose a clan first"
            body.append(Text(content="### Choose a clan\nChoose one clan above to inspect its saved-list status."))
        else:
            doc = docs[0] if docs else None
            if not doc:
                body.append(Text(content="### No saved roster\nCapture the current clan members." + (" Track who returns after CWL." if section == "FWA" else " Review and manage your Main CWL roster here.")))
            else:
                capture_label = "Replace Saved Members"
                away = away_counts.get(doc.get("clan_tag")); away_text = "unavailable" if away is None else str(away)
                status = "Return status unavailable" if away is None else ("Players still away" if away else "Everyone is home · Checks continue while running")
                if not doc.get("players"):
                    status = "No players tracked"
                settings = doc.get("reminders") or {}
                reminders = f"On · every {settings.get('every_minutes')} minutes" if settings.get("enabled") else "Off"
                details = (f"### {_name(doc.get('clan_name') or chosen)}\n"
                    f"CWL season: {doc.get('cwl_season', 'Not recorded')}\nCaptured: {_fmt_time(doc.get('saved_at'))}\n"
                    f"Players captured: {len(doc.get('players', []))}\nExpires: {_fmt_time(doc.get('expires_at'))}\n")
                details += (f"Players away: {away_text}\nStatus: {status}\nReturn reminders: {reminders}" if section == "FWA" else "Status: Saved roster")
                body.append(Text(content=details))
        buttons = [_button(style=hikari.ButtonStyle.SECONDARY if capture_disabled else hikari.ButtonStyle.PRIMARY,
            custom_id=_id("lazycwl_replace" if chosen != "ALL" and docs else "lazycwl_capture", token, chosen), label=capture_label, is_disabled=capture_disabled)]
        buttons.append(_button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_send", token, chosen),
                              label="Send Ping Now",
                              is_disabled=not docs))
        buttons.append(_button(style=hikari.ButtonStyle.DANGER, custom_id=_id("lazycwl_close", token, chosen), label=f"Clear all {label} Rosters" if chosen == "ALL" else "Clear roster", is_disabled=not docs))
        body.append(ActionRow(components=buttons))
        if section == "FWA" and docs:
            body.extend(_ping_controls(docs, token, chosen, now))
    elif tab == "players":
        if chosen == "ALL" or not docs:
            body.append(Text(content="Select one clan with a saved list to view or edit players."))
        else:
            doc = docs[0]; players = doc.get("players", []); page = 0
            rows = [f"• **{p.get('name') or p.get('tag')}** · {p.get('tag')}" for p in players[:20]]
            body.append(Text(content=f"### Players ({len(players)}) · page 1 of {max(1, (len(players)+19)//20)}\n" + ("\n".join(rows) if rows else "No players captured.")))
            body.append(ActionRow(components=[_button(style=hikari.ButtonStyle.SUCCESS, custom_id=_id("lazycwl_add", token, _bind(token, chosen, [doc], operation="add")), label="Add player"), _button(style=hikari.ButtonStyle.DANGER, custom_id=_id("lazycwl_remove", token, f"{chosen},0"), label="Remove players", is_disabled=not players), _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_players_page", token, f"{chosen},1"), label="Next", is_disabled=len(players) <= 20)]))
    else:
        if not docs:
            body.append(Text(content="No saved lists are selected."))
        else:
            body.extend(_ping_controls(docs, token, chosen, now))
    footer_buttons = [_button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_refresh", token, f"{tab},{chosen}"), label="Refresh")]
    if manage_token := _sessions.get(token, {}).get("manage_token"):
        footer_buttons.append(_button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"manage_home:{manage_token}", label="Management Home"))
    body.append(ActionRow(components=footer_buttons))
    return [Container(accent_color=GOLDENROD_ACCENT, components=body)]


async def build_home(mongo: MongoClient, selected_tag: Optional[str] = "ALL", note: Optional[str] = None, *, token: str | None = None, tab: str = "overview") -> list:
    clans, lists = await _clans(mongo, token), await _active(mongo, token)
    if _section(token) == "MAIN" and tab == "reminders": tab = "overview"
    valid_tags = {_tag(c["tag"]) for c in clans} | {_tag(d["clan_tag"]) for d in lists}
    if selected_tag and selected_tag != "ALL" and _tag(selected_tag) not in valid_tags:
        selected_tag = None
    away = {}
    chosen = _tag(selected_tag)
    # Do not hit the game API for every clan merely to draw an unselected panel.
    scope = _selected_docs(lists, chosen) if chosen and tab == "overview" and _section(token) == "FWA" else []
    for doc in scope:
        try: away[doc["clan_tag"]] = len(await service.away_players(doc))
        except Exception: _log.warning("Could not refresh away count for %s", doc.get("clan_tag"), exc_info=True)
    if tab == "players" and chosen and chosen != "ALL" and _selected_docs(lists, chosen):
        return await _player_page(mongo, token or _session(), chosen, 0, note)
    return render_home(lists, clans, selected_tag, datetime.now(timezone.utc), away, note, token=token or _session(), tab=tab)


async def open_dashboard(ctx: lightbulb.Context, mongo: MongoClient, note: str | None = None,
                         *, manage_token: str | None = None, deferred: bool = False) -> None:
    """Open an owner- and guild-bound dashboard for CWL Return Pings from /manage."""
    if not is_admin(ctx.member):
        await ctx.respond("Only server administrators can manage CWL rosters.", ephemeral=True)
        return
    if not deferred and not getattr(ctx.interaction, "custom_id", None):
        await ctx.defer(ephemeral=True)
    token = _session(ctx.user.id, ctx.interaction.guild_id)
    _sessions[token]["section"] = "FWA"
    if manage_token:
        _sessions[token]["manage_token"] = manage_token
    await ctx.interaction.edit_initial_response(components=await build_home(mongo, note=note, token=token))


async def _review(mongo, token: str, tag: str, kind: str, *, minutes: int | None = None) -> list:
    if _section(token) == "MAIN" and kind in {"enable", "disable"}:
        return _notice("FWA only", "Scheduled reminders are available in the FWA section.", token, tag)
    docs = _selected_docs(await _active(mongo, token), tag)
    if kind == "replace":
        if tag == "ALL" or len(docs) != 1:
            return _notice("Choose a roster", "Select one saved roster to replace.", token, tag)
        return _confirm("Replace Saved Members?", [f"Section: {SECTION_LABELS[_section(token)]}",
            f"Clan: {_name(docs[0].get('clan_name'))}",
            f"Current capture: {_fmt_time(docs[0].get('saved_at'))}",
            "This closes the current roster and stops its reminders. A new roster will contain the clan’s current members; manual edits are not copied.",
            "If the new roster cannot be saved, the current roster is kept."],
            "lazycwl_replace_yes", token, _bind(token, tag, docs, operation="replace"), GOLDENROD_ACCENT)
    names = [_name(d.get('clan_name') or d.get('clan_tag')) for d in docs]
    if kind == "capture":
        clans = await _clans(mongo, token)
        valid = {_tag(clan["tag"]) for clan in clans}
        targets = [clan for clan in clans if tag == "ALL" or _tag(clan["tag"]) == tag]
        targets = [clan for clan in targets if _tag(clan["tag"]) not in {_tag(doc["clan_tag"]) for doc in await _active(mongo, token)}]
        if not targets or tag not in valid | {"ALL"}:
            return _notice("Nothing to capture", "Choose a clan without an active saved list.", token, tag)
        nonce = _bind(token, tag, [], operation="capture")
        _sessions[token]["pending"][nonce]["capture_tags"] = [_tag(clan["tag"]) for clan in targets]
        return _confirm("Save Current Members?", [f"Affected clans: {len(targets)}", ", ".join(_name(clan.get("name") or clan["tag"]) for clan in targets), "This creates saved lists from members currently in those clans."], "lazycwl_capture_yes", token, nonce, GREEN_ACCENT)
    if not docs:
        return _notice("Nothing to review", "There are no active saved lists in this scope.", token, tag)
    if kind == "send":
        recipients = []
        for d in docs:
            try: recipients.append((d, await (service.reminder_recipients(d) if _section(token) == "MAIN" else service.away_players(d))))
            except Exception: recipients.append((d, None))
        if any(away is None for _, away in recipients):
            return _notice("Could not check recipients", "Nothing was sent. Refresh and try again when player status is available.", token, tag, accent=GOLDENROD_ACCENT)
        detail = [f"Destination: <#{service.reminder_channel(_section(token))}>", "Recipients are checked again when you confirm."] + [f"{_name(d.get('clan_name'))}: {len(a)} away · {len({p.get('discord_id') for p in a if p.get('discord_id')})} linked Discord accounts" for d,a in recipients]
        return _confirm("Send reminders?", [f"Affected lists: {len(docs)}"] + detail, "lazycwl_send_yes", token, _bind(token, tag, docs, operation="send"), GREEN_ACCENT)
    if kind == "close":
        return _confirm("Clear saved rosters?", ["This removes the selected rosters from active tracking and stops their return reminders. Their records remain until the retention deadline.", f"Affected rosters: {len(docs)}"] + names, "lazycwl_close_yes", token, _bind(token, tag, docs, operation="close"), RED_ACCENT)
    verb = "Enable" if kind == "enable" else "Disable"
    lines = [f"Destination: <#{service.reminder_channel(_section(token))}>", f"Affected lists: {len(docs)}"] + names
    if minutes: lines.insert(0, f"Frequency: every {minutes} minutes. Next run is calculated after applying.")
    return _confirm(f"{verb} reminders?", lines, f"lazycwl_{kind}_yes", token, _bind(token, tag, docs, minutes, operation=kind), GREEN_ACCENT if kind == "enable" else RED_ACCENT)


def _confirm(title, lines, action, token, value, accent):
    bound = _sessions.get(token, {}).get("pending", {}).get(value, {})
    tag = bound.get("tag", value)
    tab = "players" if bound.get("operation") == "remove" else ("reminders" if bound.get("operation") in {"send", "enable", "disable"} and _section(token) == "FWA" else "overview")
    bound["tab"] = tab
    return [Container(accent_color=accent, components=[Text(content=f"## {title} · {SECTION_LABELS[_section(token)]}"), Text(content="\n".join(lines)), Separator(), ActionRow(components=[_button(style=hikari.ButtonStyle.SUCCESS if accent != RED_ACCENT else hikari.ButtonStyle.DANGER, custom_id=_id(action, token, value), label="Confirm"), _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_cancel", token, value), label="Cancel")])])]


def _notice(title, text, token, tag, *, accent=GOLDENROD_ACCENT):
    return [Container(accent_color=accent, components=[Text(content=f"## {title}"), Text(content=text), Separator(), _back(token, tag)])]


def _bind(token: str, tag: str, docs: list[dict], minutes: int | None = None, operation: str = "") -> str:
    nonce = secrets.token_urlsafe(6)
    _sessions[token]["pending"][nonce] = {"tag": tag, "ids": [d.get("_id") for d in docs], "minutes": minutes, "operation": operation, "section": _section(token)}
    return nonce


def _parse_bound(token: str, value: str) -> dict | None:
    bound = _sessions.get(token, {}).get("pending", {}).pop(value, None)
    if not bound:
        return None
    return bound


async def _apply_bound(mongo, token, value, operation: str, ctx) -> list:
    bound = _parse_bound(token, value)
    if bound is None:
        return _notice("Review expired", "This confirmation is no longer valid. Refresh and review again.", token, "", accent=RED_ACCENT)
    if bound.get("operation") != operation or bound.get("section", "FWA") != _section(token):
        return _notice("Review expired", "This confirmation does not match that action.", token, "", accent=RED_ACCENT)
    tag, ids, minutes = bound["tag"], bound["ids"], bound["minutes"]
    if _section(token) == "MAIN" and operation in {"enable", "disable"}:
        return _notice("FWA only", "Scheduled reminders are available in the FWA section.", token, tag)
    docs = _selected_docs(await _active(mongo, token), tag)
    current = {_list_id(d): d for d in docs}
    if bound.get("retry"):
        current = {key: value for key, value in current.items() if key in {str(item) for item in ids}}
    if {str(item) for item in ids} != set(current):
        return _notice("Review expired", "The saved-list scope changed. Nothing was applied; refresh and review again.", token, tag, accent=RED_ACCENT)
    results = []
    for list_id, doc in current.items():
        try:
            if operation == "replace": result = await service.replace_list(doc["clan_tag"], saved_by=_ctx_user(ctx), expected_list_id=doc["_id"], section=_section(token))
            elif operation == "send": result = await service.remind_now(doc["clan_tag"], expected_list_id=doc["_id"], section=_section(token))
            elif operation == "close": result = await service.finish(doc["clan_tag"], expected_list_id=doc["_id"], section=_section(token))
            elif operation == "enable": result = {"ok": True} if doc.get("reminders", {}).get("enabled") else await service.set_reminders(doc["clan_tag"], True, minutes or doc.get("reminders", {}).get("every_minutes") or 60, expected_list_id=doc["_id"], section=_section(token))
            else: result = await service.set_reminders(doc["clan_tag"], False, expected_list_id=doc["_id"], section=_section(token))
        except Exception:
            _log.exception("LazyCWL %s failed for %s", operation, doc["clan_tag"])
            result = {"ok": False, "error": "Could not complete this action. Check the result before retrying."}
        results.append((doc, result))
    failures = [(d, r) for d, r in results if not r.get("ok")]
    successes = len(results) - len(failures)
    verbs = {"replace": "Saved members replaced", "send": "Ping check completed", "close": "Saved members cleared", "enable": "Return pings running", "disable": "Return pings paused"}
    note = f"{verbs[operation]} for {successes} clan(s)."
    if operation == "send":
        sent = [(d, r) for d, r in results if r.get("sent")]
        note = f"Ping sent for {len(sent)} clans · {sum(r.get('away_count', 0) for _, r in sent)} players away." if sent else "Everyone is home · No ping needed."
        if failures and not sent:
            note = "No pings confirmed."
    components = await build_home(mongo, tag, note, token=token, tab="overview")
    if failures:
        failed_docs = [d for d, _ in failures]
        retry = _bind(token, tag, failed_docs, minutes, operation=operation)
        _sessions[token]["pending"][retry]["retry"] = True
        detail = "\n".join(f"• {_name(d.get('clan_name'))}: {r.get('error') or 'Could not complete action'}" for d, r in failures)
        components.append(Container(accent_color=RED_ACCENT, components=[
            Text(content="### Needs attention\n" + detail[:3000]),
            ActionRow(components=[_button(style=hikari.ButtonStyle.PRIMARY, custom_id=_id("lazycwl_retry_failed", token, retry), label="Retry Failed Clans")]),
        ]))
    return components



async def _player_page(mongo, token: str, tag: str, page: int, note: str | None = None) -> list:
    doc = await store.get_active(mongo, tag, section=_section(token))
    if not doc:
        return await build_home(mongo, tag, note or "The saved list is no longer active.", token=token, tab="players")
    players = doc.get("players", []); pages = max(1, (len(players) + 19) // 20); page = max(0, min(page, pages - 1))
    page_players = players[page * 20:(page + 1) * 20]
    try:
        if _section(token) == "MAIN":
            rows = [f"• **{_name(p.get('name') or p.get('tag'))}** · {p.get('tag')} · TH {p.get('town_hall', '?')}" for p in page_players]
        else:
            away_tags = {str(p.get("tag", "")).upper() for p in await service.away_players(doc)}
            rows = [f"• **{_name(p.get('name') or p.get('tag'))}** · {p.get('tag')} · TH {p.get('town_hall', '?')} · {'Away' if str(p.get('tag', '')).upper() in away_tags else 'Returned'}" for p in page_players]
    except Exception:
        rows = [f"• **{_name(p.get('name') or p.get('tag'))}** · {p.get('tag')} · status unavailable" for p in page_players]
    clans = await _clans(mongo, token)
    body = _header(clans, await _active(mongo, token), tag, "players", token)
    body.extend([Text(content=f"### {_name(doc.get('clan_name') or tag)} · {len(players)} players · page {page + 1} of {pages}"), Text(content="\n".join(rows) or "No players captured.")])
    if note: body.append(Text(content=note))
    if page_players:
        body.append(ActionRow(components=[TextSelectMenu(custom_id=_id("lazycwl_remove_pick", token, f"{tag},{page}"), placeholder="Choose players to remove", min_values=1, max_values=len(page_players), options=[SelectOption(label=(p.get("name") or p.get("tag"))[:100], value=p.get("tag", "")) for p in page_players])]))
    nonce = _bind(token, tag, [doc], operation="add")
    _sessions[token]["pending"][nonce]["page"] = page
    body.append(ActionRow(components=[_button(style=hikari.ButtonStyle.PRIMARY, custom_id=_id("lazycwl_add", token, nonce), label="Add player"), _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_players_page", token, f"{tag},{page - 1}"), label="Previous", is_disabled=page == 0), _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_players_page", token, f"{tag},{page + 1}"), label="Next", is_disabled=page >= pages - 1), _button(style=hikari.ButtonStyle.SECONDARY, custom_id=_id("lazycwl_players_page", token, f"{tag},{page}"), label="Refresh")]))
    if manage_token := _sessions.get(token, {}).get("manage_token"):
        body.append(ActionRow(components=[_button(style=hikari.ButtonStyle.SECONDARY, custom_id=f"manage_home:{manage_token}", label="Management Home")]))
    return [Container(accent_color=GOLDENROD_ACCENT, components=body)]


class CWLRosters(lightbulb.SlashCommand, name="rosters", description="Manage saved CWL rosters and return reminders"):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await open_dashboard(ctx, mongo)


async def _handler_ok(ctx, action_id):
    token, value = _split(action_id)
    return (token, value) if await _allow(ctx, token) else (None, None)

@register_action("lazycwl_section", preload_state=False)
@lightbulb.di.with_di
async def handle_section(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, section = await _handler_ok(ctx, action_id)
    if not token or section not in SECTION_LABELS:
        return _notice("Choose a section", "Run /manage and choose CWL Return Pings again.", "preview", "")
    previous = _sessions.pop(token)
    new_token = _session(previous["owner"], previous["guild"])
    _sessions[new_token]["section"] = section
    if previous.get("manage_token"):
        _sessions[new_token]["manage_token"] = previous["manage_token"]
    return await build_home(mongo, token=new_token)


@register_action("lazycwl_clans_page", preload_state=False)
@lightbulb.di.with_di
async def handle_clans_page(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token:
        return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    try:
        _sessions[token]["clan_page"] = max(0, int(value))
    except ValueError:
        _sessions[token]["clan_page"] = 0
    return await build_home(mongo, token=token)


@register_action("lazycwl_pick", preload_state=False)
@lightbulb.di.with_di
async def handle_pick(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, tab = await _handler_ok(ctx, action_id); values = getattr(ctx.interaction, "values", []) or []
    return await build_home(mongo, values[0] if values else None, token=token, tab=tab if tab in {"overview", "players", "reminders"} else "overview") if token else _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")


@register_action("lazycwl_cancel", preload_state=False)
@lightbulb.di.with_di
async def handle_cancel(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, nonce = await _handler_ok(ctx, action_id)
    if not token:
        return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    bound = _sessions[token]["pending"].pop(nonce, {})
    if bound.get("operation") == "remove":
        return await _player_page(mongo, token, bound["tag"], bound.get("page", 0))
    return await build_home(mongo, bound.get("tag", ""), token=token, tab=bound.get("tab", "overview"))

@register_action("lazycwl_tab", preload_state=False)
@lightbulb.di.with_di
async def handle_tab(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    tab, tag = value.split(",", 1); return await build_home(mongo, tag, token=token, tab=tab)

@register_action("lazycwl_home", aliases=("lazycwl_refresh",), preload_state=False)
@lightbulb.di.with_di
async def handle_home(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    tab, tag = (value.split(",", 1) if "," in value else ("overview", value)); return await build_home(mongo, tag, token=token, tab=tab)

@register_action("lazycwl_capture", preload_state=False)
@lightbulb.di.with_di
async def handle_capture(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, tag = await _handler_ok(ctx, action_id); return await _review(mongo, token, tag, "capture") if token else _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")

@register_action("lazycwl_capture_yes", preload_state=False)
@lightbulb.di.with_di
async def handle_capture_yes(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, nonce = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    bound = _sessions.get(token, {}).get("pending", {}).pop(nonce, None)
    if not bound or bound.get("operation") != "capture":
        return _notice("Review expired", "Refresh and review the capture again.", token, "", accent=RED_ACCENT)
    valid = {_tag(clan["tag"]) for clan in await _clans(mongo, token)}
    if bound.get("section", "FWA") != _section(token) or any(tag not in valid for tag in bound.get("capture_tags", [])):
        return _notice("Review expired", "Clan assignments changed. Refresh and review the capture again.", token, bound["tag"])
    results = []
    for tag in bound.get("capture_tags", []):
        try:
            results.append(await service.save_list(tag, saved_by=_ctx_user(ctx), section=_section(token)))
        except Exception:
            _log.exception("LazyCWL capture failed for %s", tag)
            results.append({"ok": False, "error": f"Could not capture {tag}"})
    saved = sum(1 for result in results if result.get("ok")); failed = len(results) - saved
    note = f"Captured {saved} saved list(s)." + (f" {failed} could not be captured; refresh to review." if failed else "")
    return await build_home(mongo, bound["tag"], note, token=token)

def _review_action(name, kind):
    @register_action(name, preload_state=False)
    @lightbulb.di.with_di
    async def handler(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
        token, tag = await _handler_ok(ctx, action_id); return await _review(mongo, token, tag, kind) if token else _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    return handler
@register_action("lazycwl_send", preload_state=False)
@lightbulb.di.with_di
async def handle_send(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    return await _direct_ping_action(ctx, action_id, mongo, "send")

handle_replace = _review_action("lazycwl_replace", "replace")
handle_close = _review_action("lazycwl_close", "close")
handle_disable = _review_action("lazycwl_disable", "disable")

@register_action("lazycwl_enable", preload_state=False)
@lightbulb.di.with_di
async def handle_enable(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, tag = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    if _section(token) != "FWA":
        return _notice("FWA only", "Scheduled reminders are available in the FWA section.", token, tag)
    return [Container(accent_color=GOLDENROD_ACCENT, components=[Text(content="## Enable reminders"), Text(content=f"Destination: <#{service.reminder_channel(_section(token))}>. Choose an explicit frequency."), ActionRow(components=[TextSelectMenu(custom_id=_id("lazycwl_frequency", token, tag), placeholder="Choose frequency", max_values=1, options=[SelectOption(label=f"Every {m} minutes", value=str(m)) for m in REMINDER_FREQUENCIES])]), Separator(), _back(token, tag, "reminders")])]

@register_action("lazycwl_frequency", preload_state=False)
@lightbulb.di.with_di
async def handle_frequency(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, tag = await _handler_ok(ctx, action_id); values = getattr(ctx.interaction, "values", []) or []
    try: minutes = int(values[0])
    except (IndexError, ValueError): minutes = 0
    return await _review(mongo, token, tag, "enable", minutes=minutes) if token and minutes in REMINDER_FREQUENCIES else _notice("Choose a frequency", "Select one of the offered reminder frequencies.", token or "preview", tag or "")


async def _direct_ping_action(ctx, action_id, mongo, operation):
    token, tag = await _handler_ok(ctx, action_id)
    if not token:
        return _notice("Access denied", "Reopen CWL Return Pings.", "preview", "")
    docs = _selected_docs(await _active(mongo, token), tag)
    if not docs:
        return await build_home(mongo, tag, "Save Current Members first.", token=token)
    nonce = _bind(token, tag, docs, operation=operation)
    return await _apply_bound(mongo, token, nonce, operation, ctx)


@register_action("lazycwl_start_now", preload_state=False)
@lightbulb.di.with_di
async def handle_start_now(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    return await _direct_ping_action(ctx, action_id, mongo, "enable")


@register_action("lazycwl_pause_now", preload_state=False)
@lightbulb.di.with_di
async def handle_pause_now(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    return await _direct_ping_action(ctx, action_id, mongo, "disable")


@register_action("lazycwl_retry_failed", preload_state=False)
@lightbulb.di.with_di
async def handle_retry_failed(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, nonce = await _handler_ok(ctx, action_id)
    bound = _sessions.get(token, {}).get("pending", {}).get(nonce, {})
    if not token or not bound.get("retry"):
        return _notice("Retry expired", "Refresh the panel.", token or "preview", "")
    return await _apply_bound(mongo, token, nonce, bound["operation"], ctx)


@register_action("lazycwl_frequency_save", preload_state=False)
@lightbulb.di.with_di
async def handle_frequency_save(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, tag = await _handler_ok(ctx, action_id)
    values = getattr(ctx.interaction, "values", []) or []
    if not token or len(values) != 1 or values[0] not in {str(v) for v in REMINDER_FREQUENCIES}:
        return _notice("Choose a frequency", "Use 30 minutes, 1 hour, or 2 hours.", token or "preview", tag or "")
    if _section(token) != "FWA":
        return await build_home(mongo, tag, "Main return pings are manual only.", token=token)
    docs = _selected_docs(await _active(mongo, token), tag)
    errors = []
    for doc in docs:
        try:
            result = await service.set_reminders(doc["clan_tag"], bool(doc.get("reminders", {}).get("enabled")), int(values[0]), expected_list_id=doc["_id"], section="FWA")
            if not result.get("ok"):
                errors.append(f"{_name(doc.get('clan_name'))}: {result.get('error')}")
        except Exception:
            errors.append(f"{_name(doc.get('clan_name'))}: Could not save frequency")
    return await build_home(mongo, tag, "Frequency saved. Running pings updated; paused pings stay paused." if not errors else "Some frequencies could not be saved: " + "; ".join(errors), token=token)


def _apply_action(name, operation):
    @register_action(name, preload_state=False)
    @lightbulb.di.with_di
    async def handler(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
        token, value = await _handler_ok(ctx, action_id); return await _apply_bound(mongo, token, value, operation, ctx) if token else _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    return handler
handle_send_yes = _apply_action("lazycwl_send_yes", "send")
handle_replace_yes = _apply_action("lazycwl_replace_yes", "replace")
handle_close_yes = _apply_action("lazycwl_close_yes", "close")
handle_enable_yes = _apply_action("lazycwl_enable_yes", "enable")
handle_disable_yes = _apply_action("lazycwl_disable_yes", "disable")

@register_action("lazycwl_add", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def handle_add(ctx=None, action_id="", **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return
    bound = _sessions.get(token, {}).get("pending", {}).get(value)
    if not bound or bound.get("operation") != "add" or len(bound["ids"]) != 1:
        await ctx.respond("This player form has expired. Refresh and try again.", ephemeral=True)
        return
    row = ModalActionRow().add_text_input("player_tag", "Player tag", placeholder="#ABC123", required=True)
    await ctx.respond_with_modal(title="Add player", custom_id=_id("lazycwl_add_submit", token, value), components=[row])

@register_action("lazycwl_add_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def handle_add_submit(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return
    bound = _sessions.get(token, {}).get("pending", {}).pop(value, None)
    if not bound or bound.get("operation") != "add" or len(bound["ids"]) != 1:
        await ctx.respond("This player form has expired. Refresh and try again.", ephemeral=True)
        return
    tag, expected = bound["tag"], bound["ids"][0]
    player = next((component.value for row in ctx.interaction.components for component in row.components if component.custom_id == "player_tag"), "")
    await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    result = await service.add_player_by_tag(tag, player, expected_list_id=expected, section=_section(token))
    await ctx.interaction.edit_initial_response(components=await _player_page(mongo, token, tag, bound.get("page", 0), result.get("error") or "Player added."))

@register_action("lazycwl_players_page", preload_state=False)
@lightbulb.di.with_di
async def handle_players_page(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    tag, page = value.rsplit(",", 1)
    try: page = int(page)
    except ValueError: page = 0
    return await _player_page(mongo, token, tag, page)

@register_action("lazycwl_remove", preload_state=False)
@lightbulb.di.with_di
async def handle_remove(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    tag, page = value.rsplit(",", 1)
    return await _player_page(mongo, token, tag, int(page))

@register_action("lazycwl_remove_pick", preload_state=False)
@lightbulb.di.with_di
async def handle_remove_pick(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, value = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    tag, page = value.rsplit(",", 1); values = getattr(ctx.interaction, "values", []) or []
    doc = await store.get_active(mongo, tag, section=_section(token))
    if not doc or not values: return await _player_page(mongo, token, tag, int(page), "Choose at least one player.")
    nonce = _bind(token, tag, [doc], operation="remove"); _sessions[token]["pending"][nonce]["players"] = list(values); _sessions[token]["pending"][nonce]["page"] = int(page)
    names = [_name(p.get("name") or player) for p in doc.get("players", []) for player in values if p.get("tag") == player]
    return _confirm("Remove selected players?", [f"{len(values)} player(s): " + ", ".join(names), "They will be removed from this saved list."], "lazycwl_remove_yes", token, nonce, RED_ACCENT)

@register_action("lazycwl_remove_yes", preload_state=False)
@lightbulb.di.with_di
async def handle_remove_yes(ctx=None, action_id="", mongo: MongoClient = lightbulb.di.INJECTED, **kw):
    token, nonce = await _handler_ok(ctx, action_id)
    if not token: return _notice("Access denied", "Run /manage and choose CWL Return Pings again.", "preview", "")
    bound = _sessions.get(token, {}).get("pending", {}).pop(nonce, None)
    if not bound or bound.get("operation") != "remove" or len(bound["ids"]) != 1: return _notice("Review expired", "Refresh and choose the players again.", token, "", accent=RED_ACCENT)
    try:
        removed = await store.remove_players(mongo, bound["tag"], bound.get("players", []), expected_list_id=bound["ids"][0], section=_section(token))
    except store.StaleListError:
        return await _player_page(mongo, token, bound["tag"], bound.get("page", 0), "The saved list changed. Refresh and try again.")
    return await _player_page(mongo, token, bound["tag"], bound.get("page", 0), f"Removed {removed} player(s).")

_started = False
@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def on_started(event, bot: hikari.GatewayBot = lightbulb.di.INJECTED, coc_api: coc.Client = lightbulb.di.INJECTED, mongo: MongoClient = lightbulb.di.INJECTED):
    global _started
    if not _started:
        await service.start(bot, coc_api, mongo)
        _started = True
@loader.listener(hikari.StoppingEvent)
async def on_stopping(event):
    global _started
    _started = False; await service.stop()
