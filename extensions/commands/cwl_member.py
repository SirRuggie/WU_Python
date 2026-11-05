"""Private Discord alternative for member CWL signup and assignments."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import hikari
import lightbulb

from extensions.components import register_action
from utils.constants import GOLDENROD_ACCENT, WARRIORS_UNITED_GUILD_ID
from utils.cwl_signup_policy import main_signup_error
from utils.cwl_member_summary import timing_lines
from utils.dashboard_urls import SIGNUP_URL, ASSIGNMENTS_URL, TASKS_URL, WARS_URL


PAGE_SIZE = 15
ASSIGNMENT_PAGE_SIZE = 5
SESSION_TTL = 12 * 60
_sessions: dict[str, "MemberSession"] = {}
_log = logging.getLogger(__name__)


class StaleSession(Exception):
    pass


@dataclass
class MemberSession:
    user_id: int
    guild_id: int
    created_at: float
    view: dict[str, Any] = field(default_factory=dict)
    screen: str = "home"
    pool: str | None = None
    page: int = 0
    selected: set[str] = field(default_factory=set)
    source_pools: dict[str, str] = field(default_factory=dict)
    pending_tag: str | None = None
    pending_pool: str | None = None
    version: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _clip(value: str, limit: int) -> str:
    """Discord validates string lengths in UTF-16 units, including emoji."""
    return value.encode("utf-16-le")[:limit * 2].decode("utf-16-le", errors="ignore")


def _safe(value: Any, limit: int = 80) -> str:
    """Keep provider text readable without allowing mentions or markdown links."""
    text = " ".join(str(value or "").split()).replace("@", "@\u200b").replace("`", "ˋ")
    text = text.replace("<", "‹").replace(">", "›").replace("[", "［").replace("]", "］")
    text = text.replace("*", "＊").replace("_", "＿").replace("~", "～").replace("|", "｜")
    return _clip(text, limit)


def _id(action: str, token: str, version: int) -> str:
    return f"cwl_member_{action}:{token}:{version}"


def _row(*buttons):
    row = hikari.impl.MessageActionRowBuilder()
    for style, custom_id, label, disabled in buttons:
        row.add_interactive_button(style, custom_id, label=label, is_disabled=disabled)
    return row


def _member_identity(ctx) -> tuple[int, int]:
    interaction = ctx.interaction
    guild_id = getattr(interaction, "guild_id", None)
    user_id = getattr(ctx.user, "id", None)
    # Discord's interaction.member is the server membership proof. Refuse DMs,
    # malformed contexts and interactions without the hydrated guild member.
    if guild_id is None or getattr(interaction, "member", None) is None:
        raise ValueError("Use this private CWL panel in the server.")
    if int(guild_id) != WARRIORS_UNITED_GUILD_ID:
        raise ValueError("This CWL signup is available in the Warriors United server.")
    return int(user_id), int(guild_id)


def _session_from(action_id: str, ctx) -> tuple[str, MemberSession, int]:
    token, sep, version = action_id.partition(":")
    if not sep or not version.isdecimal():
        raise StaleSession
    session = _sessions.get(token)
    if session is None or time.monotonic() - session.created_at >= SESSION_TTL:
        _sessions.pop(token, None)
        raise StaleSession
    user_id, guild_id = _member_identity(ctx)
    if user_id != session.user_id or guild_id != session.guild_id:
        raise ValueError("This CWL panel belongs to another member. Use `/cwl signup` to get your own private panel.")
    if int(version) != session.version:
        raise StaleSession
    return token, session, int(version)


def _account_label(account: dict) -> str:
    return f"{_safe(account.get('name') or 'Clash account', 45)} · {_safe(account.get('tag'), 20)} · TH{account.get('town_hall', '?')}"


def _accounts(session: MemberSession) -> list[dict]:
    accounts = session.view.get("accounts") or []
    linked = [row for row in accounts if isinstance(row, dict) and row.get("tag")]
    return sorted(linked, key=_account_order)


def _account_order(account: dict) -> tuple[int, str]:
    # Provider Town Halls are integers; unknown values belong at the end.
    town_hall = account.get("town_hall")
    level = town_hall if type(town_hall) is int and town_hall > 0 else 0
    return -level, str(account.get("tag") or "")


def _eligible_accounts(session: MemberSession) -> list[dict]:
    accounts = _accounts(session)
    if session.pool == "main":
        return [row for row in accounts if main_signup_error(row) is None]
    return accounts


def _signup_is_open(session: MemberSession) -> bool:
    season = session.view.get("season") or {}
    return season.get("signup_open") is True and season.get("status") == "draft"


def _signups(session: MemberSession) -> list[dict]:
    rows = session.view.get("signups") or []
    return [row for row in rows if isinstance(row, dict) and row.get("tag")]


def _remaining(session: MemberSession) -> list[dict]:
    if session.view.get("accounts_status") != "ok":
        return []
    signed = {row["tag"] for row in _signups(session)}
    return [row for row in _accounts(session) if row["tag"] not in signed]


def _signup_pages(session: MemberSession) -> int:
    return max(1, (len(_signups(session)) + PAGE_SIZE - 1) // PAGE_SIZE)


def _saved_text(session: MemberSession) -> str:
    signed, remaining = _signups(session), _remaining(session)
    season = session.view.get("season") or {}
    if not signed:
        heading = "You have not signed up any accounts yet."
    elif session.view.get("accounts_status") == "ok":
        total = len({row['tag'] for row in _accounts(session) + signed})
        count = f"all {total} account{'s' if total != 1 else ''}" if total == len(signed) else f"{len(signed)} of {total} accounts"
        heading = f"✓ You are signed up · {count}"
    else:
        heading = f"✓ You are signed up · {len(signed)} account{'s' if len(signed) != 1 else ''}"
    lines = ["## My signups", heading]
    published = bool(session.view.get('published'))
    assignments = {row['tag']: row for row in session.view.get('assignments') or []}
    waiting = [row for row in signed if not assignments.get(row['tag'], {}).get('assigned_clan_tag')]
    partial = published and 0 < len(waiting) < len(signed)
    if partial:
        lines[1] = "✓ You are signed up · waiting for your clan"
    if signed:
        lines.append("Your published clan assignments are ready to view." if published and not waiting else "Your signup was saved. Your clan shows here when staff finish the roster.")
    start = session.page * PAGE_SIZE
    lines.extend(f"• {_safe(row.get('player_name') or row['tag'], 45)} · {'Main' if row.get('pool') == 'main' else 'Lazy'} CWL" for row in (waiting if partial else signed)[start:start + PAGE_SIZE])
    lines.extend(timing_lines(season, bool(session.view.get('published'))))
    if remaining:
        n = len(remaining)
        state = 'not signed up' if _signup_is_open(session) else ("was not" if n == 1 else "were not") + ' signed up · signups are closed'
        lines.append(f"\n{n} account{'s' if n != 1 else ''} {state}")
        lines.extend(f"• {_safe(row.get('name') or row['tag'], 45)}" for row in remaining[:6])
        if n > 6:
            lines.append(f"+ {n - 6} more")
    if _signup_pages(session) > 1:
        lines.append(f"Page {session.page + 1} of {_signup_pages(session)}")
    if signed:
        lines.append("Select an account to change its pool or withdraw." if _signup_is_open(session) else "Signups are closed. You can only view your saved accounts.")
    return '\n'.join(lines)


def _published_assignments(session: MemberSession) -> list[dict]:
    if not session.view.get("published"):
        return []
    return [row for row in session.view.get("assignments") or [] if isinstance(row, dict)]


def _instruction_pages(session: MemberSession) -> list[str]:
    publication = session.view.get("published") or {}
    raw = publication.get("joining_instructions") or ""
    if not isinstance(raw, str) or not raw.strip():
        return []
    # Dashboard publication input is capped at 2,000 characters.
    safe = "\n".join(_safe(line, 4000) for line in raw.splitlines())
    pages = []
    while safe:
        part = _clip(safe, 1500)
        pages.append(part)
        safe = safe[len(part):]
    return pages


def _panel(text: str, rows: list) -> list:
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=GOLDENROD_ACCENT,
        components=[hikari.impl.TextDisplayComponentBuilder(content=text), *rows],
    )]


def _main_text(session: MemberSession) -> str:
    if session.screen == "home":
        season = session.view.get("season") or {}
        if not season.get("id"):
            return "## CWL signups\nStaff did not set up CWL for this season yet. Try again later, or ask staff."
        label = _safe(season.get("label") or "CWL season", 60)
        is_open = _signup_is_open(session)
        status = "Signups open" if is_open else "Signups closed"
        signup_help = "Select accounts for Main or Lazy CWL." if is_open else "Signups are closed for this season. Try again next month."
        saved_help = "View, change or withdraw your signups." if is_open else "View your saved signups."
        return (f"## CWL · {label}\n{status}.\n\n"
                f"**Sign up** — {signup_help}\n"
                f"**My signups** — {saved_help}\n"
                "**My clan assignments** — See your clans when staff publish the roster.")
    if session.screen == "signup_pool":
        season = _safe((session.view.get("season") or {}).get("label") or "CWL season", 45)
        return (f"## Select your CWL · {season}\n"
                "**Main:** Play at full strength. No hero upgrades.\n"
                "**Lazy:** Relaxed CWL. You can upgrade during the event. FWA accounts use Lazy.\n"
                "You can select a different pool for each account.")
    if session.screen == "select_accounts":
        accounts = _eligible_accounts(session)
        pages = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
        season = _safe((session.view.get("season") or {}).get("label") or "CWL season", 45)
        lines = [f"## {('Main' if session.pool == 'main' else 'Lazy')} CWL · {season} · Select accounts",
                 "Select one or more accounts from the list.",
                 f"Highest TH first · {len(session.selected)} selected total."]
        if pages > 1:
            lines.append(f"**Page {session.page + 1} of {pages}**")
            if session.page < pages - 1:
                lines.append("Select **Next page** to see more accounts. Accounts you selected stay selected.")
            else:
                lines.append("This is the last page.")
        lines.append("Then select **Review signup**.")
        if session.pool == "main" and any(str(row.get("current_clan_type") or "").casefold() == "fwa" for row in _accounts(session)):
            lines.append("FWA accounts use Lazy CWL.")
        if session.pool == "main" and any(main_signup_error(row) and row.get("current_clan_type") != "FWA" for row in _accounts(session)):
            lines.append("Some accounts need a clan check before you can select Main. Select **Refresh accounts** to check them.")
        if not accounts:
            lines.append("No linked accounts that can sign up were found. Link an account, or select Refresh accounts.")
        return "\n".join(lines)
    if session.screen == "review":
        labels = {str(row["tag"]): _account_label(row) for row in _accounts(session)}
        by_tag = {str(row["tag"]): row for row in _accounts(session)}
        selected = sorted(session.selected, key=lambda tag: _account_order(by_tag.get(tag, {"tag": tag})))
        pages = max(1, (len(selected) + 9) // 10)
        visible = selected[session.page * 10:(session.page + 1) * 10]
        existing = {str(row["tag"]): row for row in _signups(session)}
        moves = [tag for tag in selected if tag in existing and existing[tag].get("pool") != session.pool]
        already = [tag for tag in selected if tag in existing and existing[tag].get("pool") == session.pool]
        move_details = "\n".join(
            f"• {labels.get(tag, _safe(tag))}: {'Main' if existing[tag].get('pool') == 'main' else 'Lazy'} → {'Main' if session.pool == 'main' else 'Lazy'}"
            for tag in visible if tag in moves
        )
        if moves:
            page_note = f"Changes on this page:\n{move_details}" if move_details else "Go to another page to see the pool changes."
            note = f"\n\nPool changes: {len(moves)}. Staff must assign a clan again. {page_note}"
        else:
            note = ""
        if already and len(already) == len(selected):
            note = "\nThese accounts are already signed up for this pool. You do not need to change anything."
        page_label = f" · Page {session.page + 1} of {pages}" if pages > 1 else ""
        listing = "\n".join(f"• {labels.get(tag, _safe(tag))}" for tag in visible) or "Select at least one account."
        season = _safe((session.view.get("season") or {}).get("label") or "CWL season", 45)
        return f"## Review {('Main' if session.pool == 'main' else 'Lazy')} signup · {season} · Accounts: {len(selected)}{page_label}\n{listing}\n\nConfirm to save.{note}"
    if session.screen == "my_signups":
        return _saved_text(session)
    if session.screen == "signup_action":
        row = next((row for row in _signups(session) if row.get("tag") == session.pending_tag), {})
        pool = "Main" if row.get("pool") == "main" else "Lazy"
        return f"## {_safe(row.get('player_name') or session.pending_tag)}\n{_safe(session.pending_tag)} · {pool} CWL. Select a change."
    if session.screen == "change_pool":
        account = next((row for row in _accounts(session) if str(row.get("tag")) == session.pending_tag), {})
        reason = main_signup_error(account) if account else None
        warning = "\nYou cannot select Main for this account until its current clan is checked." if reason else ""
        return "## Change pool\nSelect the new pool for this account. You review the change before it is saved." + warning
    if session.screen == "pool_change_confirm":
        row = next((row for row in _signups(session) if str(row.get("tag")) == session.pending_tag), {})
        source = "Main" if session.source_pools.get(session.pending_tag) == "main" else "Lazy"
        destination = "Main" if session.pending_pool == "main" else "Lazy"
        return f"## Confirm pool change\n{_safe(row.get('player_name') or session.pending_tag)} ({_safe(session.pending_tag)}): {source} → {destination}. Staff must assign a clan again."
    if session.screen == "withdraw_confirm":
        row = next((row for row in _signups(session) if str(row.get("tag")) == session.pending_tag), {})
        pool = "Main" if row.get("pool") == "main" else "Lazy"
        return (f"## Withdraw signup?\nRemove **{_safe(row.get('player_name') or session.pending_tag)}** "
                f"({_safe(session.pending_tag)}) from {pool} CWL? You can sign up again while signups are open.")
    if session.screen == "assignments":
        publication = session.view.get("published")
        if not publication:
            if _signups(session):
                return "## My clan assignments\nYour signup is saved. Staff must publish the assignments first."
            return "## My clan assignments\nYou have no saved signup for the current season. Staff must publish the assignments first."
        rows = _published_assignments(session)
        if not rows:
            return "## My clan assignments\nThe published assignments do not include any of your accounts."
        pages = max(1, (len(rows) + ASSIGNMENT_PAGE_SIZE - 1) // ASSIGNMENT_PAGE_SIZE)
        page_label = f" · Page {session.page + 1} of {pages}" if pages > 1 else ""
        lines = [f"## My clan assignments{page_label}"]
        for row in rows[session.page * ASSIGNMENT_PAGE_SIZE:(session.page + 1) * ASSIGNMENT_PAGE_SIZE]:
            clan = row.get("assigned_clan_name") or "Waiting for a clan"
            tag = row.get("assigned_clan_tag")
            clan_tag = str(tag or "").upper().lstrip("#")
            link = (f"https://link.clashofclans.com/en?action=OpenClanProfile&tag={clan_tag}"
                    if re.fullmatch(r"[0289PYLQGRJCUV]{3,15}", clan_tag) else None)
            account = f"{_safe(row.get('player_name') or 'Account', 50)} · {_safe(row.get('tag'), 20)}"
            host = f"{_safe(clan, 60)} · {_safe(tag, 20)}" if tag else _safe(clan, 60)
            lines.append(f"• {account}\n  {host}" + (f" · [Open clan]({link})" if link else ""))
        if _instruction_pages(session):
            lines.append("Joining instructions are available below.")
        return "\n".join(lines)
    if session.screen == "instructions":
        pages = _instruction_pages(session)
        if not pages:
            return "## Joining instructions\nStaff did not add joining instructions."
        return f"## Joining instructions · {session.page + 1} of {len(pages)}\n{pages[session.page]}"
    return "This panel is old. Use `/cwl signup` to open a new one."


def _components(token: str, session: MemberSession) -> list:
    version = session.version
    c = hikari.impl
    if session.screen == "home":
        if not (session.view.get("season") or {}).get("id"):
            return []
        return [
            _row(
                (hikari.ButtonStyle.PRIMARY, _id("signup", token, version), "Sign up", not _signup_is_open(session)),
                (hikari.ButtonStyle.SECONDARY, _id("my_signups", token, version), "My signups", False),
            ),
            _row((hikari.ButtonStyle.SECONDARY, _id("assignments", token, version), "My clan assignments", False)),
            c.MessageActionRowBuilder().add_link_button(ASSIGNMENTS_URL, label="My clan assignments").add_link_button(TASKS_URL, label="My tasks").add_link_button(WARS_URL, label="Wars"),
        ]
    if session.screen == "signup_pool":
        return [
            _row(
                (hikari.ButtonStyle.PRIMARY, _id("pool_main", token, version), "Main CWL", False),
                (hikari.ButtonStyle.SECONDARY, _id("pool_lazy", token, version), "Lazy CWL", False),
            ),
            _row(
                (hikari.ButtonStyle.SECONDARY, _id("refresh", token, version), "Refresh accounts", False),
                (hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False),
            ),
        ]
    if session.screen == "select_accounts":
        accounts = _eligible_accounts(session)
        pages = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
        visible = accounts[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]
        rows = []
        if visible:
            menu = c.TextSelectMenuBuilder(custom_id=_id("select", token, version), placeholder="Select one or more accounts", min_values=0,
                                           max_values=min(len(visible), 20))
            signups = {str(row["tag"]): row for row in _signups(session)}
            for account in visible:
                tag = str(account["tag"])
                old = signups.get(tag)
                if old:
                    current = "Main" if old.get("pool") == "main" else "Lazy"
                    target = "Main" if session.pool == "main" else "Lazy"
                    description = f"Already in {target}" if current == target else f"Signed up: {current} → {target}"
                else:
                    description = "Not signed up"
                menu.add_option(_clip(_account_label(account), 100), tag, description=description,
                                is_default=tag in session.selected)
            rows.append(c.MessageActionRowBuilder().add_component(menu))
        else:
            rows.append(c.MessageActionRowBuilder().add_interactive_button(hikari.ButtonStyle.SECONDARY, _id("refresh", token, version), label="Refresh accounts"))
        more_pages = session.page < pages - 1
        if pages > 1:
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous page", session.page == 0),
                (hikari.ButtonStyle.PRIMARY if more_pages else hikari.ButtonStyle.SECONDARY,
                 _id("next", token, version), "Next page", not more_pages),
            ))
        rows.append(_row(
            (hikari.ButtonStyle.SECONDARY if more_pages else hikari.ButtonStyle.PRIMARY,
             _id("review", token, version), "Review signup", not session.selected),
            (hikari.ButtonStyle.SECONDARY, _id("signup", token, version), "Back", False),
        ))
        if session.selected:
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("clear_selection", token, version), "Clear selected", False),
            ))
        return rows
    if session.screen == "review":
        pages = max(1, (len(session.selected) + 9) // 10)
        rows = [_row(
            (hikari.ButtonStyle.SUCCESS, _id("confirm", token, version), "Confirm and save", not session.selected),
            (hikari.ButtonStyle.SECONDARY, _id("back_select", token, version), "Back", False),
            (hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Cancel", False),
        )]
        if pages > 1:
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
                (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
            ))
        return rows
    if session.screen == "my_signups":
        rows = []
        signups = _signups(session)
        visible = signups[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]
        if visible and _signup_is_open(session):
            menu = c.TextSelectMenuBuilder(custom_id=_id("signup_pick", token, version), placeholder="Select a saved signup", min_values=1, max_values=1)
            for row in signups[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]:
                menu.add_option(_clip(f"{_safe(row.get('player_name') or row['tag'], 45)} · {_safe(row['tag'], 18)} · {row['pool'].title()}", 100), str(row["tag"]))
            rows.append(c.MessageActionRowBuilder().add_component(menu))
        pages = _signup_pages(session)
        if not signups or (_remaining(session) and _signup_is_open(session)):
            rows.append(c.MessageActionRowBuilder().add_link_button(SIGNUP_URL, label="Sign up for CWL"))
        rows.append(_row((hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False)))
        if pages > 1:
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
                (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
            ))
        return rows
    if session.screen == "signup_action":
        return [_row(
            (hikari.ButtonStyle.PRIMARY, _id("change_pool", token, version), "Change pool", False),
            (hikari.ButtonStyle.DANGER, _id("withdraw", token, version), "Withdraw", False),
            (hikari.ButtonStyle.SECONDARY, _id("my_signups", token, version), "Back", False),
        )]
    if session.screen == "change_pool":
        account = next((row for row in _accounts(session) if str(row.get("tag")) == session.pending_tag), {})
        main_unavailable = not account or main_signup_error(account) is not None
        return [_row(
            (hikari.ButtonStyle.PRIMARY, _id("move_main", token, version), "Move to Main", main_unavailable),
            (hikari.ButtonStyle.SECONDARY, _id("move_lazy", token, version), "Move to Lazy", False),
            (hikari.ButtonStyle.SECONDARY, _id("signup_action", token, version), "Cancel", False),
        )]
    if session.screen == "pool_change_confirm":
        return [_row(
            (hikari.ButtonStyle.SUCCESS, _id("confirm_move", token, version), "Confirm pool change", False),
            (hikari.ButtonStyle.SECONDARY, _id("change_pool", token, version), "Back", False),
            (hikari.ButtonStyle.SECONDARY, _id("signup_action", token, version), "Cancel", False),
        )]
    if session.screen == "withdraw_confirm":
        return [_row(
            (hikari.ButtonStyle.DANGER, _id("withdraw_confirm", token, version), "Confirm withdrawal", False),
            (hikari.ButtonStyle.SECONDARY, _id("signup_action", token, version), "Keep signup", False),
        )]
    if session.screen == "assignments":
        pages = max(1, (len(_published_assignments(session)) + ASSIGNMENT_PAGE_SIZE - 1) // ASSIGNMENT_PAGE_SIZE)
        buttons = [(hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False)]
        if _instruction_pages(session):
            buttons.insert(0, (hikari.ButtonStyle.SECONDARY, _id("instructions", token, version), "Joining instructions", False))
        rows = [_row(*buttons)]
        if pages > 1:
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
                (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
            ))
        return rows
    if session.screen == "instructions":
        pages = _instruction_pages(session)
        rows = [_row((hikari.ButtonStyle.SECONDARY, _id("assignments", token, version), "Back to assignments", False))]
        if len(pages) > 1:
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
                (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= len(pages) - 1),
            ))
        return rows
    return [_row((hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False))]


def _season_id(session: MemberSession) -> int:
    season = session.view.get("season") or {}
    value = season.get("id")
    if type(value) is not int or value < 1:
        raise ValueError("CWL signups are not available now. Your saved signups did not change.")
    return value


def _revision(session: MemberSession) -> int:
    revision = session.view.get("revision")
    if type(revision) is not int or revision < 0:
        raise ValueError("The CWL data changed. Use `/cwl signup` to open the panel again before you save.")
    return revision


async def _refresh(session: MemberSession, user_id: int, guild_id: int, *, include_accounts: bool = True) -> None:
    from utils.cwl_member_client import request

    previous_season = (session.view.get("season") or {}).get("id")
    snapshot = await request("view", user_id=user_id, guild_id=guild_id, include_accounts=include_accounts)
    current_season = (snapshot.get("season") or {}).get("id")
    session.view = snapshot
    if previous_season != current_season:
        # Never carry an unfinished signup into a newly selected member season.
        session.selected.clear()
        session.source_pools.clear()
        session.pending_tag = None
        session.pending_pool = None
        session.pool = None
        session.page = 0
        session.screen = "home"


async def _edit(ctx, token: str, session: MemberSession, note: str | None = None):
    session.version += 1
    content = _main_text(session)
    if note:
        content += f"\n\n{note}"
    try:
        message = getattr(ctx.interaction, "message", None)
        flags = getattr(message, "flags", hikari.MessageFlag.IS_COMPONENTS_V2)
        legacy_clear = {"content": None, "embeds": []} if not flags & hikari.MessageFlag.IS_COMPONENTS_V2 else {}
        await ctx.interaction.edit_initial_response(
            components=_panel(content, _components(token, session)),
            user_mentions=False, role_mentions=False, mentions_everyone=False,
            **legacy_clear,
        )
    except Exception as exc:
        _log.warning("CWL member panel edit failed: %s", type(exc).__name__)
        # The screen generation has already advanced. A followup must not
        # restore the old confirmation or invite a duplicate write.
        try:
            await ctx.respond("Could not update this panel. Use `/cwl signup` to get a new private panel. Check My signups before you save again.",
                              ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False)
        except Exception:
            pass


class CwlMember(lightbulb.SlashCommand, name="signup", description="Sign up for CWL and view your clan assignments privately"):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        try:
            _member_identity(ctx)
        except ValueError as exc:
            await ctx.respond(str(exc), ephemeral=True)
            return
        # Acknowledge privately before the saved-data read. No dashboard gate
        # and no shared message/button is created by this command.
        await ctx.respond(
            components=_panel("## CWL signups\nLoading your signups…", []),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
            user_mentions=False, role_mentions=False, mentions_everyone=False,
        )
        await start(ctx, f"{int(ctx.user.id)}:{int(ctx.interaction.guild_id)}")


loader = lightbulb.Loader()
# Staff campaign/roster controls live under /manage. This public group contains
# only member self-service; it does not register the retired staff CWL group.
cwl = lightbulb.Group("cwl", "Your CWL signup and clan assignments")
cwl.register(CwlMember)
loader.command(cwl)



def _new_session(ctx) -> tuple[str, MemberSession]:
    user_id, guild_id = _member_identity(ctx)
    now = time.monotonic()
    for old_token, old_session in list(_sessions.items()):
        if now - old_session.created_at >= SESSION_TTL:
            _sessions.pop(old_token, None)
    token = secrets.token_urlsafe(9)
    session = MemberSession(user_id, guild_id, time.monotonic())
    _sessions[token] = session
    return token, session


@register_action("cwl_member_start", no_return=True, preload_state=False)
async def start(ctx, action_id: str, **_):
    try:
        bound_user, sep, bound_guild = action_id.partition(":")
        user_id, guild_id = _member_identity(ctx)
        if not sep or bound_user != str(user_id) or bound_guild != str(guild_id):
            raise ValueError("This CWL entry button belongs to another member. Run /cwl signup for your own private panel.")
        token, session = _new_session(ctx)
        async with session.lock:
            await _refresh(session, session.user_id, session.guild_id, include_accounts=False)
            if session.view.get("accounts_status") == "unavailable":
                message = "Linked accounts are temporarily unavailable. Your saved signups have not been changed. Try again shortly."
                session.screen = "home"
            else:
                message = None
            await _edit(ctx, token, session, message)
    except ValueError as exc:
        await ctx.respond(str(exc), ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False)
    except Exception:
        message = getattr(ctx.interaction, "message", None)
        flags = getattr(message, "flags", hikari.MessageFlag.IS_COMPONENTS_V2)
        legacy_clear = {"content": None, "embeds": []} if not flags & hikari.MessageFlag.IS_COMPONENTS_V2 else {}
        await ctx.interaction.edit_initial_response(
            components=_panel("The CWL service is temporarily unavailable. Your signups have not been changed. Run `/cwl signup` again shortly.", []),
            user_mentions=False, role_mentions=False, mentions_everyone=False,
            **legacy_clear,
        )


@register_action("cwl_member_check", no_return=True, preload_state=False)
async def check_signups(ctx, action_id: str, **_):
    """The shared post is never edited: reply with a private follow-up."""
    try:
        if action_id != "open":
            raise ValueError("Select Check my signups on the signup post.")
        token, session = _new_session(ctx)
        async with session.lock:
            await _refresh(session, session.user_id, session.guild_id, include_accounts=True)
            session.screen = "my_signups"
            session.version += 1
            components = _panel(_main_text(session), _components(token, session))
    except ValueError as exc:
        components = _panel(str(exc), [])
    except Exception:
        components = _panel("The CWL service is not available now. Your signups did not change. Try again in a few minutes.", [])
    await ctx.respond(components=components,
                      flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
                      user_mentions=False, role_mentions=False, mentions_everyone=False)


async def _handle(ctx, action_id: str, action: str) -> None:
    try:
        token, session, _ = _session_from(action_id, ctx)
    except StaleSession:
        await ctx.respond("This CWL panel expired or changed. Use `/cwl signup` to start again.", ephemeral=True,
                          user_mentions=False, role_mentions=False, mentions_everyone=False)
        return
    except ValueError as exc:
        await ctx.respond(str(exc), ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False)
        return
    async with session.lock:
        # Revalidate membership and generation after waiting for a concurrent click.
        try:
            _, current, _ = _session_from(action_id, ctx)
            assert current is session
        except (StaleSession, ValueError):
            await ctx.respond("This CWL panel changed. Use `/cwl signup` to start again.", ephemeral=True,
                              user_mentions=False, role_mentions=False, mentions_everyone=False)
            return
        user_id, guild_id = _member_identity(ctx)
        allowed_actions = {
            "home": {"signup", "my_signups", "assignments"},
            "signup_pool": {"pool_main", "pool_lazy", "home", "refresh"},
            "select_accounts": {"select", "prev", "next", "review", "clear_selection", "signup", "refresh"},
            "review": {"prev", "next", "confirm", "back_select", "home"},
            "my_signups": {"signup_pick", "prev", "next", "home"},
            "signup_action": {"change_pool", "withdraw", "my_signups"},
            "change_pool": {"move_main", "move_lazy", "signup_action"},
            "pool_change_confirm": {"confirm_move", "change_pool", "signup_action"},
            "withdraw_confirm": {"withdraw_confirm", "signup_action"},
            "assignments": {"prev", "next", "home", "instructions"},
            "instructions": {"prev", "next", "assignments"},
        }
        note = None
        if action not in allowed_actions.get(session.screen, set()):
            note = "That action is old. Use the controls in this panel."
        elif action == "home":
            session.screen = "home"
        elif action == "signup":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. You can still view your saved signups."
            else:
                try:
                    previous_season = (session.view.get("season") or {}).get("id")
                    await _refresh(session, user_id, guild_id, include_accounts=True)
                    if previous_season != (session.view.get("season") or {}).get("id"):
                        note = "The CWL season changed. Check the new season here. Then select Sign up again."
                        session.screen = "home"
                    elif _signup_is_open(session):
                        session.screen = "signup_pool"
                        if session.view.get("accounts_status") == "unavailable":
                            note = "Linked accounts are not available now. Select Refresh accounts before you select a pool."
                    else:
                        note = "Signups closed while this panel was open. You can still view your saved signups."
                except Exception:
                    note = "Could not load your linked accounts. Use `/cwl signup` again in a few minutes. No signup was changed."
        elif action == "pool_main" or action == "pool_lazy":
            session.pool = "main" if action.endswith("main") else "lazy"
            session.selected.clear()
            session.page = 0
            if session.view.get("accounts_status") == "unavailable":
                note = "Linked accounts are temporarily unavailable. Your saved signups did not change."
            elif not _accounts(session):
                note = "No linked accounts were found. Link an account with ClashKing `/link` or with ClashPerk. Then select Refresh accounts."
            elif not _eligible_accounts(session):
                note = ("Your FWA accounts can sign up for Lazy CWL only." if all(
                    str(row.get("current_clan_type") or "").casefold() == "fwa" for row in _accounts(session)
                ) else "Could not check the current clan category for Main. Select Refresh accounts, or select Lazy CWL.")
            else:
                session.screen = "select_accounts"
        elif action == "select":
            values = list(getattr(ctx.interaction, "values", ()) or ())
            allowed = {str(row["tag"]) for row in _eligible_accounts(session)[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]}
            if len(values) > PAGE_SIZE or not set(values) <= allowed:
                note = "Those account selections are old. Check the current page. Then try again."
            else:
                candidate = (session.selected - allowed) | set(values)
                if len(candidate) > 100:
                    note = "The limit is 100 accounts for each signup. Clear some selections. Then add more."
                else:
                    session.selected = candidate & {str(row["tag"]) for row in _eligible_accounts(session)}
                session.screen = "select_accounts"
        elif action == "prev":
            session.page = max(0, session.page - 1)
        elif action == "next":
            if session.screen == "instructions":
                maximum = max(0, len(_instruction_pages(session)) - 1)
            elif session.screen == "assignments":
                maximum = max(0, (len(_published_assignments(session)) - 1) // ASSIGNMENT_PAGE_SIZE)
            elif session.screen == "review":
                maximum = max(0, (len(session.selected) - 1) // 10)
            else:
                maximum = _signup_pages(session) - 1 if session.screen == "my_signups" else max(0, (len(_eligible_accounts(session)) - 1) // PAGE_SIZE)
            session.page = min(maximum, session.page + 1)
        elif action == "review":
            if session.selected:
                session.page = 0
                session.screen = "review"
            else:
                note = "Select at least one account first."
        elif action == "clear_selection":
            session.selected.clear()
        elif action == "back_select":
            session.screen = "select_accounts"
        elif action == "confirm":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups did not change."
                session.screen = "home"
            elif not session.selected or session.pool not in {"main", "lazy"}:
                note = "Select a pool and at least one account. Then save."
            else:
                season_id, expected_revision = _season_id(session), _revision(session)
                existing_by_tag = {str(row["tag"]): row for row in _signups(session)}
                accounts = []
                for tag in sorted(session.selected):
                    old = existing_by_tag.get(tag)
                    if old and old.get("pool") == session.pool:
                        continue
                    item = {"tag": tag, "prefer_crystal_1_or_lower": False}
                    if old:
                        item["prefer_crystal_1_or_lower"] = bool(old.get("prefer_crystal_1_or_lower", False))
                        item["move_from_pool"] = old["pool"]
                    accounts.append(item)
                # Consume this UI generation before awaiting the single write.
                session.screen = "home"
                session.version += 1
                from utils.cwl_member_client import MemberClientError, request
                try:
                    if accounts:
                        await request("submit", user_id=user_id, guild_id=str(guild_id), season_id=season_id,
                                      expected_revision=expected_revision, pool=session.pool, accounts=accounts)
                    session.selected.clear()
                    session.source_pools.clear()
                    if accounts:
                        note = "Signup saved. To check your accounts, select My signups."
                        try:
                            await _refresh(session, user_id, guild_id, include_accounts=False)
                        except Exception:
                            note += " Use `/cwl signup` again to see the new details."
                    else:
                        note = "Those accounts are already saved for this pool. No changes were made."
                except MemberClientError as exc:
                    note = ("Your change may not be saved. Select My signups to check. Then try again if needed." if getattr(exc, "uncertain", False)
                            else str(exc) or "Could not save the signup. Select My signups. Then try again.")
                except Exception:
                    note = "Your change may not be saved. Select My signups to check. Then try again if needed."
                session.screen = "home"
        elif action == "my_signups":
            try:
                await _refresh(session, user_id, guild_id, include_accounts=True)
                session.page = 0
                session.screen = "my_signups"
            except Exception:
                session.screen = "home"
                note = "CWL is temporarily unavailable. Your saved signups did not change. Try /cwl signup again shortly."
        elif action == "signup_pick":
            values = list(getattr(ctx.interaction, "values", ()) or ())
            known = {str(row["tag"]) for row in _signups(session)}
            if not _signup_is_open(session):
                note = "Signups are closed. You can only view your saved accounts."
            elif len(values) != 1 or values[0] not in known:
                note = "That saved signup changed. Select Back. Then select My signups."
            else:
                session.pending_tag = values[0]
                row = next(row for row in _signups(session) if str(row["tag"]) == session.pending_tag)
                session.source_pools[session.pending_tag] = str(row.get("pool"))
                session.screen = "signup_action"
        elif action == "signup_action":
            session.pending_pool = None
            session.screen = "signup_action"
        elif action == "change_pool":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. You can only view your saved signup."
                session.screen = "my_signups"
            else:
                try:
                    await _refresh(session, user_id, guild_id, include_accounts=True)
                    if session.pending_tag not in {str(row["tag"]) for row in _signups(session)}:
                        note = "That saved signup changed. Select an account again."
                        session.screen = "my_signups"
                    elif not _signup_is_open(session):
                        note = "Signups closed while this panel was open."
                        session.screen = "my_signups"
                    elif session.view.get("accounts_status") == "unavailable":
                        note = "Linked accounts are temporarily unavailable. Your saved signups did not change. Try again in a few minutes."
                        session.screen = "signup_action"
                    elif session.pending_tag not in {str(row["tag"]) for row in _accounts(session)}:
                        note = "This saved account is not linked to you now. Link it again before you change its pool."
                        session.screen = "signup_action"
                    else:
                        session.screen = "change_pool"
                except Exception:
                    note = "Linked accounts could not be loaded. Your saved signups did not change. Try again in a few minutes."
        elif action in {"move_main", "move_lazy"}:
            account = next((row for row in _accounts(session) if str(row.get("tag")) == session.pending_tag), {})
            if action == "move_main" and (not account or main_signup_error(account)):
                note = "You cannot select Main for this account. Select Lazy, or update your linked accounts."
            elif not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups did not change."
                session.screen = "home"
            else:
                destination = "main" if action == "move_main" else "lazy"
                if not session.pending_tag:
                    note = "Select a saved signup first."
                    session.screen = "my_signups"
                elif session.source_pools.get(session.pending_tag) == destination:
                    note = "That account is already signed up for this pool."
                    session.screen = "signup_action"
                else:
                    session.pending_pool = destination
                    session.screen = "pool_change_confirm"
        elif action == "confirm_move":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups did not change."
                session.screen = "home"
            elif not session.pending_tag or session.pending_pool not in {"main", "lazy"}:
                note = "Select a saved signup and a new pool first."
                session.screen = "my_signups"
            else:
                season_id, expected_revision = _season_id(session), _revision(session)
                tag = session.pending_tag
                source = session.source_pools.get(tag)
                existing = next((row for row in _signups(session) if str(row.get("tag")) == tag), {})
                preference = bool(existing.get("prefer_crystal_1_or_lower", False))
                destination = session.pending_pool
                session.version += 1
                session.screen = "home"
                from utils.cwl_member_client import MemberClientError, request
                try:
                    await request("submit", user_id=user_id, guild_id=str(guild_id), season_id=season_id,
                                  expected_revision=expected_revision, pool=destination,
                                  accounts=[{"tag": tag, "prefer_crystal_1_or_lower": preference, "move_from_pool": source}])
                    note = "Pool changed. To check your accounts, select My signups."
                    try:
                        await _refresh(session, user_id, guild_id, include_accounts=False)
                    except Exception:
                        note += " Use `/cwl signup` again to see the new details."
                except MemberClientError as exc:
                    note = ("Your change may not be saved. Select My signups to check. Then try again if needed." if getattr(exc, "uncertain", False)
                            else str(exc) or "Could not change the pool. Select My signups.")
                except Exception:
                    note = "Your change may not be saved. Select My signups to check. Then try again if needed."
        elif action == "withdraw":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. You can only view your saved signup."
                session.screen = "my_signups"
            else:
                session.screen = "withdraw_confirm"
        elif action == "withdraw_confirm":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups did not change."
                session.screen = "home"
            elif not session.pending_tag:
                note = "Select a saved signup first."
                session.screen = "my_signups"
            else:
                tag = session.pending_tag
                season_id, expected_revision = _season_id(session), _revision(session)
                session.screen = "home"
                session.version += 1
                from utils.cwl_member_client import MemberClientError, request
                try:
                    await request("withdraw", user_id=user_id, guild_id=str(guild_id), season_id=season_id,
                                  expected_revision=expected_revision, expected_pool=session.source_pools.get(tag), tag=tag)
                    note = "Signup withdrawn."
                    try:
                        await _refresh(session, user_id, guild_id, include_accounts=False)
                    except Exception:
                        note += " Use `/cwl signup` again to see the new details."
                except MemberClientError as exc:
                    note = ("Your change may not be saved. Select My signups to check. Then try again if needed." if getattr(exc, "uncertain", False)
                            else str(exc) or "Could not withdraw the signup. Select My signups.")
                except Exception:
                    note = "Your change may not be saved. Select My signups to check. Then try again if needed."
                session.screen = "home"
        elif action == "instructions":
            session.page = 0
            session.screen = "instructions"
        elif action == "assignments":
            try:
                await _refresh(session, user_id, guild_id, include_accounts=False)
                session.page = 0
                session.screen = "assignments"
            except Exception:
                session.screen = "home"
                note = "CWL is temporarily unavailable. Your saved signups did not change. Try /cwl signup again shortly."
        elif action == "refresh":
            try:
                previous_season = (session.view.get("season") or {}).get("id")
                await _refresh(session, user_id, guild_id, include_accounts=True)
                if previous_season != (session.view.get("season") or {}).get("id"):
                    note = "The CWL season changed. Check this panel before you select a pool."
                elif session.view.get("accounts_status") == "unavailable":
                    note = "Linked accounts are temporarily unavailable. Your saved signups did not change."
                else:
                    note = "Linked accounts refreshed."
            except Exception:
                note = "CWL is temporarily unavailable. Your saved signups did not change. Try /cwl signup again shortly."
        else:
            note = "That action is no longer available."
        await _edit(ctx, token, session, note)


for _action_name in (
    "home", "signup", "pool_main", "pool_lazy", "select", "prev", "next", "review", "clear_selection",
    "back_select", "confirm", "my_signups", "signup_pick", "change_pool", "instructions", "move_main",
    "move_lazy", "confirm_move", "withdraw", "withdraw_confirm", "signup_action", "assignments", "refresh",
):
    def _register(name: str):
        @register_action(f"cwl_member_{name}", no_return=True, preload_state=False)
        async def handler(ctx, action_id: str, **_):
            await _handle(ctx, action_id, name)
        return handler
    _register(_action_name)
