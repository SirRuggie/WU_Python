"""Private Discord alternative for member CWL signup and assignments."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

import hikari
import lightbulb

from extensions.components import register_action
from utils.constants import WARRIORS_UNITED_GUILD_ID
from utils import cwl_campaign


PAGE_SIZE = 15
ASSIGNMENT_PAGE_SIZE = 5
SESSION_TTL = 12 * 60
DASHBOARD_URL = cwl_campaign.SIGNUP_URL
_sessions: dict[str, "MemberSession"] = {}


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
        raise ValueError("Open this private CWL flow from inside the server.")
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
        raise ValueError("This CWL panel belongs to another member. Run `/cwl-member` for your own private panel.")
    if int(version) != session.version:
        raise StaleSession
    return token, session, int(version)


def _account_label(account: dict) -> str:
    return f"{_safe(account.get('name') or 'Clash account', 45)} · {_safe(account.get('tag'), 20)} · TH{account.get('town_hall', '?')}"


def _accounts(session: MemberSession) -> list[dict]:
    accounts = session.view.get("accounts") or []
    return [row for row in accounts if isinstance(row, dict) and row.get("tag") and row.get("verified") is True]


def _eligible_accounts(session: MemberSession) -> list[dict]:
    accounts = _accounts(session)
    if session.pool == "main":
        return [row for row in accounts if str(row.get("current_clan_type") or "").casefold() != "fwa"]
    return accounts


def _signup_is_open(session: MemberSession) -> bool:
    season = session.view.get("season") or {}
    return season.get("signup_open") is True and season.get("status") == "draft"


def _signups(session: MemberSession) -> list[dict]:
    rows = session.view.get("signups") or []
    return [row for row in rows if isinstance(row, dict) and row.get("tag")]


def _published_assignments(session: MemberSession) -> list[dict]:
    if not session.view.get("published"):
        return []
    return [row for row in session.view.get("assignments") or [] if isinstance(row, dict)]


def _main_text(session: MemberSession) -> str:
    if session.screen == "home":
        season = session.view.get("season") or {}
        label = _safe(season.get("label") or "CWL season", 60)
        status = "Signups open" if _signup_is_open(session) else "Signups closed"
        return f"## CWL member tools · {label}\n{status}. Choose a private action below. The dashboard is the recommended signup path."
    if session.screen == "signup_pool":
        return "## Sign up\nChoose Main or Lazy CWL. Your linked accounts will be refreshed before saving."
    if session.screen == "select_accounts":
        accounts = _eligible_accounts(session)
        pages = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
        start = session.page * PAGE_SIZE
        visible = accounts[start:start + PAGE_SIZE]
        lines = [f"## {('Main' if session.pool == 'main' else 'Lazy')} CWL · Choose accounts",
                 f"Page {session.page + 1} of {pages}. Select up to 100 accounts, then Review."]
        if session.pool == "main" and any(str(row.get("current_clan_type") or "").casefold() == "fwa" for row in _accounts(session)):
            lines.append("FWA accounts must use Lazy CWL.")
        lines.extend(f"• {_account_label(row)}" for row in visible)
        return "\n".join(lines)
    if session.screen == "review":
        labels = {str(row["tag"]): _account_label(row) for row in _accounts(session)}
        selected = sorted(session.selected)
        pages = max(1, (len(selected) + 9) // 10)
        visible = selected[session.page * 10:(session.page + 1) * 10]
        existing = {str(row["tag"]): row for row in _signups(session)}
        moves = [tag for tag in selected if tag in existing and existing[tag].get("pool") != session.pool]
        already = [tag for tag in selected if tag in existing and existing[tag].get("pool") == session.pool]
        note = "\nConfirming moves accounts from their current pool and clears their working placements." if moves else ""
        if already and len(already) == len(selected):
            note = "\nThese accounts are already signed up for this pool; no changes are needed."
        return f"## Review signup · {len(selected)} account(s) · Page {session.page + 1} of {pages}\n" + ("\n".join(f"• {labels.get(tag, tag)}" for tag in visible) or "Choose at least one account.") + f"\n\nPool: {'Main' if session.pool == 'main' else 'Lazy'} CWL. Confirm saves these signups.{note}"
    if session.screen == "my_signups":
        rows = _signups(session)
        if not rows:
            return "## My signups\nYou have no saved signups for the member season."
        start = session.page * PAGE_SIZE
        visible = rows[start:start + PAGE_SIZE]
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        return f"## My signups · Page {session.page + 1} of {pages}\nChoose an account below to change its pool or withdraw.\n" + "\n".join(
            f"• {_safe(row.get('player_name') or row['tag'], 50)} · {_safe(row['tag'], 20)} · {'Main' if row.get('pool') == 'main' else 'Lazy'}"
            for row in visible
        )
    if session.screen == "signup_action":
        row = next((row for row in _signups(session) if row.get("tag") == session.pending_tag), {})
        return f"## {_safe(row.get('player_name') or session.pending_tag)}\nChoose a change for this saved signup."
    if session.screen == "change_pool":
        return "## Change pool\nChoose a destination. You will review before saving."
    if session.screen == "pool_change_confirm":
        row = next((row for row in _signups(session) if str(row.get("tag")) == session.pending_tag), {})
        source = "Main" if session.source_pools.get(session.pending_tag) == "main" else "Lazy"
        destination = "Main" if session.pending_pool == "main" else "Lazy"
        return f"## Confirm pool change\n{_safe(row.get('player_name') or session.pending_tag)}: {source} → {destination}. Confirm to save. Any working placement will be cleared."
    if session.screen == "withdraw_confirm":
        return f"## Withdraw signup?\nRemove {_safe(session.pending_tag)} from your saved signups? This cannot be undone here."
    if session.screen == "assignments":
        publication = session.view.get("published")
        if not publication:
            if _signups(session):
                return "## My clan assignments\nYour signup is saved. Staff have not published assignments yet."
            return "## My clan assignments\nYou have no saved signup for the current member season. Staff have not published assignments yet."
        rows = _published_assignments(session)
        if not rows:
            return "## My clan assignments\nNo accounts are included in the published assignments for you."
        pages = max(1, (len(rows) + ASSIGNMENT_PAGE_SIZE - 1) // ASSIGNMENT_PAGE_SIZE)
        lines = [f"## My clan assignments · Page {session.page + 1} of {pages}"]
        for row in rows[session.page * ASSIGNMENT_PAGE_SIZE:(session.page + 1) * ASSIGNMENT_PAGE_SIZE]:
            clan = row.get("assigned_clan_name") or "Awaiting placement"
            tag = row.get("assigned_clan_tag")
            clan_tag = str(tag or "").upper().lstrip("#")
            link = (f"https://link.clashofclans.com/en?action=OpenClanProfile&tag={clan_tag}"
                    if re.fullmatch(r"[0289PYLQGRJCUV]{3,15}", clan_tag) else None)
            account = f"{_safe(row.get('player_name') or 'Account', 50)} · {_safe(row.get('tag'), 20)}"
            host = f"{_safe(clan, 60)} · {_safe(tag, 20)}" if tag else _safe(clan, 60)
            lines.append(f"• {account}\n  {host}" + (f" · [Open clan]({link})" if link else ""))
        return "\n".join(lines)
    return "This panel is out of date. Run `/cwl-member` to open a fresh one."


def _components(token: str, session: MemberSession) -> list:
    version = session.version
    c = hikari.impl
    if session.screen == "home":
        return [_row(
            (hikari.ButtonStyle.PRIMARY, _id("signup", token, version), "Sign up", not _signup_is_open(session)),
            (hikari.ButtonStyle.SECONDARY, _id("my_signups", token, version), "My signups", False),
            (hikari.ButtonStyle.SECONDARY, _id("assignments", token, version), "My clan assignments", False),
        )]
    if session.screen == "signup_pool":
        return [_row(
            (hikari.ButtonStyle.PRIMARY, _id("pool_main", token, version), "Main CWL", False),
            (hikari.ButtonStyle.SECONDARY, _id("pool_lazy", token, version), "Lazy CWL", False),
            (hikari.ButtonStyle.SECONDARY, _id("refresh", token, version), "Refresh accounts", False),
            (hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False),
        )]
    if session.screen == "select_accounts":
        accounts = _eligible_accounts(session)
        pages = max(1, (len(accounts) + PAGE_SIZE - 1) // PAGE_SIZE)
        visible = accounts[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]
        rows = []
        if visible:
            menu = c.TextSelectMenuBuilder(custom_id=_id("select", token, version), placeholder="Select accounts", min_values=1,
                                           max_values=min(len(visible), 20))
            for account in visible:
                tag = str(account["tag"])
                menu.add_option(_clip(_account_label(account), 100), tag, description="Choose this Clash account",
                                is_default=tag in session.selected)
            rows.append(c.MessageActionRowBuilder().add_component(menu))
        else:
            rows.append(c.MessageActionRowBuilder().add_interactive_button(hikari.ButtonStyle.SECONDARY, _id("refresh", token, version), label="Refresh linked accounts"))
        rows.append(_row(
            (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
            (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
            (hikari.ButtonStyle.PRIMARY, _id("review", token, version), f"Review ({len(session.selected)})", not session.selected),
            (hikari.ButtonStyle.SECONDARY, _id("clear_selection", token, version), "Clear selected", not session.selected),
            (hikari.ButtonStyle.SECONDARY, _id("signup", token, version), "Cancel", False),
        ))
        return rows
    if session.screen == "review":
        pages = max(1, (len(session.selected) + 9) // 10)
        return [_row(
            (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
            (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
            (hikari.ButtonStyle.SUCCESS, _id("confirm", token, version), "Confirm and save", not session.selected),
            (hikari.ButtonStyle.SECONDARY, _id("back_select", token, version), "Back", False),
            (hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Cancel", False),
        )]
    if session.screen == "my_signups":
        rows = []
        signups = _signups(session)
        if signups:
            menu = c.TextSelectMenuBuilder(custom_id=_id("signup_pick", token, version), placeholder="Choose a saved signup", min_values=1, max_values=1)
            for row in signups[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]:
                menu.add_option(_clip(f"{_safe(row.get('player_name') or row['tag'], 55)} · {row['pool'].title()}", 100), str(row["tag"]))
            rows.append(c.MessageActionRowBuilder().add_component(menu))
            pages = max(1, (len(signups) + PAGE_SIZE - 1) // PAGE_SIZE)
            rows.append(_row(
                (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
                (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
                (hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False),
            ))
        else:
            rows.append(_row((hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False)))
        return rows
    if session.screen == "signup_action":
        return [_row(
            (hikari.ButtonStyle.PRIMARY, _id("change_pool", token, version), "Change pool", False),
            (hikari.ButtonStyle.DANGER, _id("withdraw", token, version), "Withdraw", False),
            (hikari.ButtonStyle.SECONDARY, _id("my_signups", token, version), "Back", False),
        )]
    if session.screen == "change_pool":
        return [_row(
            (hikari.ButtonStyle.PRIMARY, _id("move_main", token, version), "Move to Main", False),
            (hikari.ButtonStyle.SECONDARY, _id("move_lazy", token, version), "Move to Lazy", False),
            (hikari.ButtonStyle.SECONDARY, _id("signup_action", token, version), "Cancel", False),
        )]
    if session.screen == "withdraw_confirm":
        return [_row(
            (hikari.ButtonStyle.DANGER, _id("withdraw_confirm", token, version), "Confirm withdrawal", False),
            (hikari.ButtonStyle.SECONDARY, _id("signup_action", token, version), "Keep signup", False),
        )]
    if session.screen == "assignments":
        pages = max(1, (len(_published_assignments(session)) + ASSIGNMENT_PAGE_SIZE - 1) // ASSIGNMENT_PAGE_SIZE)
        return [_row(
            (hikari.ButtonStyle.SECONDARY, _id("prev", token, version), "Previous", session.page == 0),
            (hikari.ButtonStyle.SECONDARY, _id("next", token, version), "Next", session.page >= pages - 1),
            (hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False),
        )]
    return [_row((hikari.ButtonStyle.SECONDARY, _id("home", token, version), "Back", False))]


def _season_id(session: MemberSession) -> int:
    season = session.view.get("season") or {}
    value = season.get("id")
    if type(value) is not int or value < 1:
        raise ValueError("CWL signups are not available right now. Your saved signups have not been changed.")
    return value


def _revision(session: MemberSession) -> int:
    revision = session.view.get("revision")
    if type(revision) is not int or revision < 0:
        raise ValueError("CWL data changed. Refresh the panel before saving.")
    return revision


async def _refresh(session: MemberSession, user_id: int, guild_id: int) -> None:
    from utils.cwl_member_client import request

    previous_season = (session.view.get("season") or {}).get("id")
    snapshot = await request("view", user_id=user_id, guild_id=guild_id)
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
    await ctx.interaction.edit_initial_response(content=content, components=_components(token, session),
                                                user_mentions=False, role_mentions=False, mentions_everyone=False)


class CwlMember(lightbulb.SlashCommand, name="cwl-member", description="Open your private CWL signup and assignment options"):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        try:
            _member_identity(ctx)
        except ValueError as exc:
            await ctx.respond(str(exc), ephemeral=True)
            return
        row = hikari.impl.MessageActionRowBuilder()
        row.add_link_button(DASHBOARD_URL, label="Open CWL dashboard")
        row.add_interactive_button(hikari.ButtonStyle.SECONDARY,
                                   f"cwl_member_start:{int(ctx.user.id)}:{int(ctx.interaction.guild_id)}",
                                   label="Use Discord instead")
        await ctx.respond("## CWL signups\nUse the dashboard for the full experience, or open a private Discord flow here.",
                          components=[row], ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False)


loader = lightbulb.Loader()
loader.command(CwlMember)


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
            raise ValueError("This CWL entry button belongs to another member. Run /cwl-member for your own private panel.")
        token, session = _new_session(ctx)
        async with session.lock:
            await _refresh(session, session.user_id, session.guild_id)
            if session.view.get("accounts_status") == "unavailable":
                message = "Linked accounts are temporarily unavailable. Your saved signups have not been changed. Try again shortly."
                session.screen = "home"
            else:
                message = None
            await _edit(ctx, token, session, message)
    except ValueError as exc:
        await ctx.respond(str(exc), ephemeral=True, user_mentions=False, role_mentions=False, mentions_everyone=False)
    except Exception:
        await ctx.interaction.edit_initial_response(content="The CWL service is temporarily unavailable. Your signups have not been changed. Try again shortly.", components=[])


async def _handle(ctx, action_id: str, action: str) -> None:
    try:
        token, session, _ = _session_from(action_id, ctx)
    except StaleSession:
        await ctx.respond("This CWL panel expired or changed. Run `/cwl-member` to start again.", ephemeral=True,
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
            await ctx.respond("This CWL panel changed. Run `/cwl-member` to start again.", ephemeral=True,
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
            "assignments": {"prev", "next", "home"},
        }
        note = None
        if action not in allowed_actions.get(session.screen, set()):
            note = "That action is out of date. Use the controls shown in this panel."
        elif action == "home":
            session.screen = "home"
        elif action == "signup":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups remain available to view."
            else:
                session.screen = "signup_pool"
        elif action == "pool_main" or action == "pool_lazy":
            session.pool = "main" if action.endswith("main") else "lazy"
            session.selected.clear()
            session.page = 0
            if session.view.get("accounts_status") == "unavailable":
                note = "Linked accounts are temporarily unavailable. Your saved signups are still safe."
            elif not _accounts(session):
                note = "No verified linked accounts were found. Use ClashKing /link (or link through ClashPerk), then choose Refresh accounts."
            elif not _eligible_accounts(session):
                note = "Your linked accounts are in FWA clans and can sign up for Lazy CWL only."
            else:
                session.screen = "select_accounts"
        elif action == "select":
            values = list(getattr(ctx.interaction, "values", ()) or ())
            allowed = {str(row["tag"]) for row in _eligible_accounts(session)[session.page * PAGE_SIZE:(session.page + 1) * PAGE_SIZE]}
            if len(values) > PAGE_SIZE or not set(values) <= allowed:
                note = "Those account choices are out of date. Review the current page and try again."
            else:
                session.selected.difference_update(allowed)
                session.selected.update(values)
                if len(session.selected) > 100:
                    session.selected.difference_update(values)
                    note = "Select up to 100 accounts per signup. Clear some choices before adding more."
                session.selected.intersection_update({str(row["tag"]) for row in _eligible_accounts(session)})
                session.screen = "select_accounts"
        elif action == "prev":
            session.page = max(0, session.page - 1)
        elif action == "next":
            if session.screen == "assignments":
                maximum = max(0, (len(_published_assignments(session)) - 1) // ASSIGNMENT_PAGE_SIZE)
            elif session.screen == "review":
                maximum = max(0, (len(session.selected) - 1) // 10)
            else:
                maximum = max(0, (len(_signups(session)) - 1) // PAGE_SIZE) if session.screen == "my_signups" else max(0, (len(_eligible_accounts(session)) - 1) // PAGE_SIZE)
            session.page = min(maximum, session.page + 1)
        elif action == "review":
            if session.selected:
                session.page = 0
                session.screen = "review"
            else:
                note = "Choose at least one account first."
        elif action == "clear_selection":
            session.selected.clear()
        elif action == "back_select":
            session.screen = "select_accounts"
        elif action == "confirm":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups have not been changed."
                session.screen = "home"
            elif not session.selected or session.pool not in {"main", "lazy"}:
                note = "Choose a pool and at least one account before saving."
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
                        note = "Signup saved. It is now visible on the CWL dashboard."
                        try:
                            await _refresh(session, user_id, guild_id)
                        except Exception:
                            note += " Refresh /cwl-member to reload current details."
                    else:
                        note = "Those accounts are already saved for this pool. No changes were needed."
                except MemberClientError as exc:
                    note = ("The save result is unclear. Refresh My signups before trying again." if getattr(exc, "uncertain", False)
                            else str(exc) or "The signup could not be saved. Refresh and try again.")
                except Exception:
                    note = "The save result is unclear. Refresh My signups before trying again."
                session.screen = "home"
        elif action == "my_signups":
            try:
                await _refresh(session, user_id, guild_id)
                session.page = 0
                session.screen = "my_signups"
            except Exception:
                session.screen = "home"
                note = "CWL is temporarily unavailable. No signups were changed. Try /cwl-member again shortly."
        elif action == "signup_pick":
            values = list(getattr(ctx.interaction, "values", ()) or ())
            known = {str(row["tag"]) for row in _signups(session)}
            if len(values) != 1 or values[0] not in known:
                note = "That saved signup changed. Refresh My signups."
            else:
                session.pending_tag = values[0]
                row = next(row for row in _signups(session) if str(row["tag"]) == session.pending_tag)
                session.source_pools[session.pending_tag] = str(row.get("pool"))
                session.screen = "signup_action"
        elif action == "change_pool":
            session.screen = "change_pool"
        elif action in {"move_main", "move_lazy"}:
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups have not been changed."
                session.screen = "home"
            else:
                destination = "main" if action == "move_main" else "lazy"
                if not session.pending_tag:
                    note = "Choose a saved signup first."
                    session.screen = "my_signups"
                elif session.source_pools.get(session.pending_tag) == destination:
                    note = "That account is already signed up for this pool."
                    session.screen = "signup_action"
                else:
                    session.pending_pool = destination
                    session.screen = "pool_change_confirm"
        elif action == "confirm_move":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups have not been changed."
                session.screen = "home"
            elif not session.pending_tag or session.pending_pool not in {"main", "lazy"}:
                note = "Choose a saved signup and destination pool first."
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
                    note = "Pool changed. The dashboard now shows the change."
                    try:
                        await _refresh(session, user_id, guild_id)
                    except Exception:
                        note += " Refresh /cwl-member to reload current signup details."
                except MemberClientError as exc:
                    note = ("The save result is unclear. Refresh My signups before trying again." if getattr(exc, "uncertain", False)
                            else str(exc) or "The pool could not be changed. Refresh My signups.")
                except Exception:
                    note = "The save result is unclear. Refresh My signups before trying again."
        elif action == "withdraw":
            session.screen = "withdraw_confirm"
        elif action == "withdraw_confirm":
            if not _signup_is_open(session):
                note = "Signups are closed for this season. Your saved signups have not been changed."
                session.screen = "home"
            elif not session.pending_tag:
                note = "Choose a saved signup first."
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
                    note = "Signup withdrawn. It is now removed from the CWL dashboard."
                    try:
                        await _refresh(session, user_id, guild_id)
                    except Exception:
                        note += " Refresh /cwl-member to reload current details."
                except MemberClientError as exc:
                    note = ("The save result is unclear. Refresh My signups before trying again." if getattr(exc, "uncertain", False)
                            else str(exc) or "The signup could not be withdrawn. Refresh My signups.")
                except Exception:
                    note = "The save result is unclear. Refresh My signups before trying again."
                session.screen = "home"
        elif action == "assignments":
            try:
                await _refresh(session, user_id, guild_id)
                session.page = 0
                session.screen = "assignments"
            except Exception:
                session.screen = "home"
                note = "CWL is temporarily unavailable. Your saved signups are unchanged. Try /cwl-member again shortly."
        elif action == "refresh":
            try:
                await _refresh(session, user_id, guild_id)
                if session.view.get("accounts_status") == "unavailable":
                    note = "Linked accounts are temporarily unavailable. Your saved signups are still safe."
                else:
                    note = "Linked accounts refreshed."
            except Exception:
                note = "CWL is temporarily unavailable. Your saved signups are unchanged. Try /cwl-member again shortly."
        else:
            note = "That action is no longer available."
        await _edit(ctx, token, session, note)


for _action_name in (
    "home", "signup", "pool_main", "pool_lazy", "select", "prev", "next", "review", "clear_selection",
    "back_select", "confirm", "my_signups", "signup_pick", "change_pool", "move_main",
    "move_lazy", "confirm_move", "withdraw", "withdraw_confirm", "signup_action", "assignments", "refresh",
):
    def _register(name: str):
        @register_action(f"cwl_member_{name}", no_return=True, preload_state=False)
        async def handler(ctx, action_id: str, **_):
            await _handle(ctx, action_id, name)
        return handler
    _register(_action_name)
