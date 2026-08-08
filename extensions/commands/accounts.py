"""/accounts - every Clash account linked to the invoking Discord user."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import coc
import hikari
import lightbulb

from extensions.components import register_action
from utils import coc_maintenance, todo_data
from utils.clash_links import resolve_tags
from utils.constants import RED_ACCENT
from utils.emoji import emojis

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)


loader = lightbulb.Loader()

PAGE_SIZE = 20
TEXT_BLOCK_LIMIT = 3_800
RESULT_TTL = 2 * 60
LINK_FAILURE = "link_service"
STATUS_LOADED = "loaded"
STATUS_NOT_FOUND = "not_found"
STATUS_ERROR = "error"


@dataclass(frozen=True, slots=True)
class AccountEntry:
    """One linked tag and the result of loading its player profile."""

    tag: str
    status: str
    account: todo_data.Account | None = None


@dataclass(frozen=True, slots=True)
class AccountsData:
    """Complete accounting for one Discord user's linked tags."""

    entries: tuple[AccountEntry, ...] = ()
    problem: str | None = None

    @property
    def linked_count(self) -> int:
        return len(self.entries)

    @property
    def loaded_count(self) -> int:
        return sum(entry.status == STATUS_LOADED for entry in self.entries)

    @property
    def error_count(self) -> int:
        return sum(entry.status == STATUS_ERROR for entry in self.entries)

    @property
    def not_found_count(self) -> int:
        return sum(entry.status == STATUS_NOT_FOUND for entry in self.entries)


# Page buttons should not fan out the same player requests again. The underlying
# player cache is already ten minutes, but NotFound and transient failures are
# deliberately not cached there. This short result cache keeps one panel stable
# while somebody pages through it without hiding a retry for long.
_result_cache: dict[int, tuple[float, AccountsData]] = {}


def _normalize_tag(value: object) -> str:
    tag = str(value or "").strip().upper()
    if tag and not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


def _normalize_tags(values: list[str]) -> list[str]:
    return list(dict.fromkeys(
        tag for value in values if (tag := _normalize_tag(value))
    ))


def _error_tags(errors: list[str]) -> set[str]:
    return {
        tag
        for error in errors
        if (tag := _normalize_tag(str(error).partition(":")[0]))
    }


def _entry_sort_key(entry: AccountEntry) -> tuple:
    if entry.account is not None:
        return (
            0,
            -entry.account.town_hall,
            entry.account.name.casefold(),
            entry.tag,
        )
    return (1 if entry.status == STATUS_ERROR else 2, 0, "", entry.tag)


def _cached_result(discord_id: int) -> AccountsData | None:
    hit = _result_cache.get(discord_id)
    if hit is None:
        return None
    expires_at, data = hit
    if time.monotonic() >= expires_at:
        _result_cache.pop(discord_id, None)
        return None
    return data


def _remember_result(discord_id: int, data: AccountsData) -> None:
    now = time.monotonic()
    for user_id, (expires_at, _data) in list(_result_cache.items()):
        if expires_at <= now:
            _result_cache.pop(user_id, None)
    _result_cache[discord_id] = (now + RESULT_TTL, data)


async def load_accounts(
    coc_client: coc.Client,
    discord_id: int,
    *,
    force: bool = False,
) -> AccountsData:
    """Resolve and account for every tag linked to ``discord_id``.

    The accounting identity is deliberate and tested:

        linked tags = loaded profiles + not-found tags + temporary failures

    ``todo_data.fetch_accounts`` omits NotFound profiles because that is right
    for a to-do list. An inventory cannot silently lose them, so this function
    reconciles its output against the original link list.
    """
    discord_id = int(discord_id)
    if not force and (cached := _cached_result(discord_id)) is not None:
        return cached

    cache_key = f"links:{discord_id}"
    # A newly linked account must appear when the member reruns the command.
    # Page clicks use the warm result above; only a fresh slash invocation
    # bypasses the six-hour shared link cache.
    tags = None if force else todo_data.cache_get(cache_key)
    if tags is None:
        tags = await resolve_tags(discord_id)
        if tags is None:
            return AccountsData(problem=LINK_FAILURE)
        tags = _normalize_tags(tags)
        todo_data.cache_put(cache_key, tags, todo_data.TTL_LINKS)
    else:
        tags = _normalize_tags(tags)

    if not tags:
        data = AccountsData()
        _remember_result(discord_id, data)
        return data

    loaded, errors = await todo_data.fetch_accounts(coc_client, tags)
    loaded_by_tag = {
        _normalize_tag(account.tag): account
        for account in loaded
        if _normalize_tag(account.tag)
    }
    failed_tags = _error_tags(errors)

    # The current fetcher always prefixes errors with their tag. Keep a
    # defensive fallback so an upstream wording change cannot turn a reported
    # failure into a false "profile not found" verdict.
    unassigned_failures = max(0, len(errors) - len(failed_tags))
    entries: list[AccountEntry] = []
    for tag in tags:
        account = loaded_by_tag.get(tag)
        if account is not None:
            entries.append(AccountEntry(tag, STATUS_LOADED, account))
        elif tag in failed_tags:
            entries.append(AccountEntry(tag, STATUS_ERROR))
        elif unassigned_failures:
            entries.append(AccountEntry(tag, STATUS_ERROR))
            unassigned_failures -= 1
        else:
            entries.append(AccountEntry(tag, STATUS_NOT_FOUND))

    entries.sort(key=_entry_sort_key)
    data = AccountsData(entries=tuple(entries))
    _remember_result(discord_id, data)
    return data


def _escape_markdown(value: object, *, max_raw_length: int = 100) -> str:
    raw = str(value or "Unknown")
    if len(raw) > max_raw_length:
        raw = f"{raw[:max_raw_length - 1]}…"
    text = raw.replace("\\", "\\\\")
    for char in ("`", "*", "_", "~", "|", ">", "[", "]", "(", ")"):
        text = text.replace(char, f"\\{char}")
    return text.replace("@", "@\u200b")


def _plural(value: int, singular: str, plural: str | None = None) -> str:
    return singular if value == 1 else (plural or f"{singular}s")


def _player_link(entry: AccountEntry) -> str:
    if entry.account is not None and entry.account.share_link:
        return entry.account.share_link
    return (
        "https://link.clashofclans.com/en?action=OpenPlayerProfile"
        f"&tag=%23{entry.tag.lstrip('#')}"
    )


def _th_display(level: int) -> str:
    emoji = getattr(emojis, f"TH{level}", None)
    return f"{emoji} TH{level}" if emoji is not None else f"🏰 TH{level or '?'}"


def _entry_line(entry: AccountEntry, ordinal: int) -> str:
    if entry.account is not None:
        account = entry.account
        name = _escape_markdown(account.name)
        clan = _escape_markdown(account.clan_name or "No clan")
        return (
            f"{_th_display(account.town_hall)} · **[{name}]({_player_link(entry)})**\n"
            f"-# {ordinal}. `{entry.tag}` · {clan}"
        )
    if entry.status == STATUS_ERROR:
        return (
            f"⏳ **Account couldn't be loaded**\n"
            f"-# {ordinal}. `{entry.tag}` · The link is still included; try again shortly."
        )
    return (
        f"⚠️ **Player profile not found**\n"
        f"-# {ordinal}. `{entry.tag}` · This may be an old or mistyped link."
    )


def _text_blocks(lines: list[str]) -> list[str]:
    """Pack whole account rows into Discord-safe Text Display blocks."""
    blocks: list[str] = []
    current = ""
    for original in lines:
        # CoC names and tags are far below this, but never let malformed
        # upstream data make one row invalidate the entire Discord response.
        line = (
            original
            if len(original) <= TEXT_BLOCK_LIMIT
            else f"{original[:TEXT_BLOCK_LIMIT - 1]}…"
        )
        candidate = f"{current}\n\n{line}" if current else line
        if current and len(candidate) > TEXT_BLOCK_LIMIT:
            blocks.append(current)
            current = line
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def _notice(title: str, description: str) -> list[Container]:
    return [Container(
        accent_color=RED_ACCENT,
        components=[
            Text(content=f"# {title}"),
            Separator(divider=True),
            Text(content=description),
            Media(items=[MediaItem(media="assets/Red_Footer.png")]),
        ],
    )]


def render_accounts(data: AccountsData, page: int = 0) -> list[Container]:
    """Build a bounded Components V2 inventory page."""
    if data.problem == LINK_FAILURE:
        return _notice(
            "Couldn't reach the link service",
            "The Clash↔Discord link service didn't answer, so I can't tell "
            "which accounts are yours.\n\n"
            "This is a problem on their end, not yours — try `/accounts` again shortly.",
        )

    if not data.entries:
        return _notice(
            "No linked accounts",
            "I couldn't find any Clash of Clans accounts linked to your Discord.\n\n"
            "Link one with ClashKing's `/link` command (you'll need your in-game "
            "API token from **Settings → More Settings → API Token**), then run "
            "`/accounts` again.",
        )

    pages = max(1, math.ceil(data.linked_count / PAGE_SIZE))
    page = max(0, min(int(page), pages - 1))
    start = page * PAGE_SIZE
    window = data.entries[start:start + PAGE_SIZE]

    if data.loaded_count == data.linked_count:
        summary = (
            f"**{data.loaded_count} {_plural(data.loaded_count, 'player account')}** "
            "linked to your Discord."
        )
    else:
        summary = (
            f"**{data.loaded_count} {_plural(data.loaded_count, 'player profile')} loaded** "
            f"· **{data.linked_count} linked {_plural(data.linked_count, 'tag')} total**"
        )

    row_blocks = _text_blocks([
        _entry_line(entry, start + index + 1)
        for index, entry in enumerate(window)
    ])
    body: list = [
        Text(content="# 🪪 Your Player Accounts"),
        Text(content=(
            f"{summary}\n"
            "-# Every tag ClashKing currently links to you is included. "
            "Loaded profiles are sorted by Town Hall."
        )),
        Separator(divider=True),
    ]
    body.extend(Text(content=block) for block in row_blocks)

    notes: list[str] = []
    if data.error_count:
        if coc_maintenance.in_maintenance():
            notes.append(coc_maintenance.banner())
        elif data.error_count == 1:
            notes.append(
                "⚠️ **1 account couldn't be loaded this time.** "
                "Its linked tag is still shown above; try again shortly."
            )
        else:
            notes.append(
                f"⚠️ **{data.error_count} accounts couldn't be loaded this time.** "
                "Their linked tags are still shown above; try again shortly."
            )
    if data.not_found_count:
        notes.append(
            f"ℹ️ **{data.not_found_count} linked "
            f"{_plural(data.not_found_count, 'tag')} returned no player profile.** "
            "These may be old or mistyped links."
        )
    if notes:
        body.extend([
            Separator(divider=True),
            Text(content="\n".join(notes)),
        ])

    if pages > 1:
        # Unclamped ids stay unique on the first and last page; the renderer
        # clamps hostile/out-of-range values when they arrive.
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"accounts_page:{page - 1}",
                label="◀",
                is_disabled=page == 0,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"accounts_page:{page}",
                label=f"Page {page + 1}/{pages}",
                is_disabled=True,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"accounts_page:{page + 1}",
                label="▶",
                is_disabled=page >= pages - 1,
            ),
        ]))

    body.append(Media(items=[MediaItem(media="assets/Red_Footer.png")]))
    return [Container(accent_color=RED_ACCENT, components=body)]


def _page_number(value: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@register_action("accounts_page")
@lightbulb.di.with_di
async def accounts_page_handler(
    ctx: lightbulb.components.MenuContext,
    action_id: str,
    coc_client: coc.Client = lightbulb.di.INJECTED,
    **_kwargs,
) -> list[Container]:
    data = await load_accounts(coc_client, int(ctx.user.id))
    return render_accounts(data, _page_number(action_id))


@loader.command
class Accounts(
    lightbulb.SlashCommand,
    name="accounts",
    description="Show every Clash account linked to your Discord",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        coc_client: coc.Client = lightbulb.di.INJECTED,
    ) -> None:
        # Account ownership is private in a guild. DMs have no audience to hide
        # it from, and Discord does not support ephemeral DM messages.
        await ctx.defer(ephemeral=ctx.guild_id is not None)
        data = await load_accounts(coc_client, int(ctx.user.id), force=True)
        await ctx.interaction.edit_initial_response(
            components=render_accounts(data),
        )
