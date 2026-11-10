"""Linked Clash accounts for one Discord user: loading and row rendering.

Shared by ``/profile``, the new-warrior staff alert, tickets and Clash of Cards.
This module has no command of its own.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import coc

from utils import coc_maintenance, todo_data
from utils.clash_links import resolve_tags
from utils.emoji import emojis


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
    link_sources: tuple[str, ...] = ()
    clashperk_verified: bool | None = None


@dataclass(frozen=True, slots=True)
class AccountsData:
    """Complete accounting for one Discord user's linked tags."""

    entries: tuple[AccountEntry, ...] = ()
    problem: str | None = None
    unavailable_sources: tuple[str, ...] = ()
    conflicting_tags: tuple[str, ...] = ()
    conflict_key: str = ""

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
    linked_result=None,
) -> AccountsData:
    """Resolve and account for every tag linked to ``discord_id``.

    The accounting identity is deliberate and tested:

        linked tags = loaded profiles + not-found tags + temporary failures

    ``todo_data.fetch_accounts`` omits NotFound profiles because that is right
    for a to-do list. An inventory cannot silently lose them, so this function
    reconciles its output against the original link list.
    """
    discord_id = int(discord_id)
    if linked_result is None and not force and (cached := _cached_result(discord_id)) is not None:
        return cached

    cache_key = f"links:{discord_id}"
    # A newly linked account must appear when the member reruns the command.
    # Page clicks use the warm result above; only a fresh slash invocation
    # bypasses the six-hour shared link cache.
    if linked_result is not None:
        tags = list(linked_result.sources)
    else:
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
        data = AccountsData(
            unavailable_sources=linked_result.unavailable if linked_result else (),
            conflicting_tags=linked_result.conflicts if linked_result else (),
            conflict_key=linked_result.conflict_key if linked_result else "",
        )
        if linked_result is None:
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

    if linked_result is not None:
        entries = [AccountEntry(
            entry.tag, entry.status, entry.account,
            linked_result.sources.get(entry.tag, ()),
            linked_result.verified.get(entry.tag),
        ) for entry in entries]
    entries.sort(key=_entry_sort_key)
    data = AccountsData(
        entries=tuple(entries),
        unavailable_sources=linked_result.unavailable if linked_result else (),
        conflicting_tags=linked_result.conflicts if linked_result else (),
        conflict_key=linked_result.conflict_key if linked_result else "",
    )
    if linked_result is None:
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
            f"**{ordinal}.** {_th_display(account.town_hall)} · "
            f"**[{name}]({_player_link(entry)})** · `{entry.tag}` · {clan}"
        )
    if entry.status == STATUS_ERROR:
        return (
            f"**{ordinal}.** ⏳ `{entry.tag}` · **Account not loaded** · "
            "The link is saved. Try again in a few minutes."
        )
    return (
        f"**{ordinal}.** ⚠️ `{entry.tag}` · **Player profile not found** · "
        "This may be an old or mistyped link."
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
        candidate = f"{current}\n{line}" if current else line
        if current and len(candidate) > TEXT_BLOCK_LIMIT:
            blocks.append(current)
            current = line
        else:
            current = candidate
    if current:
        blocks.append(current)
    return blocks


def _budget_pages(data: AccountsData, budget: int) -> list[list[str]]:
    """Greedy pages of at most PAGE_SIZE rows whose text fits ``budget``."""
    budget = max(200, int(budget))
    pages: list[list[str]] = []
    current: list[str] = []
    size = 0
    for index, entry in enumerate(data.entries):
        line = _entry_line(entry, index + 1)
        if len(line) > budget:
            line = f"{line[:budget - 1]}…"
        added = len(line) + (1 if current else 0)
        if current and (len(current) >= PAGE_SIZE or size + added > budget):
            pages.append(current)
            current, size, added = [], 0, len(line)
        current.append(line)
        size += added
    if current:
        pages.append(current)
    return pages or [[]]


def page_window(
    data: AccountsData, page: int = 0, *, budget: int = TEXT_BLOCK_LIMIT,
) -> tuple[int, int, list[str]]:
    """Clamp ``page``; return (page, pages, row blocks within ``budget`` chars).

    Discord counts every Text Display in one message against one 4000-character
    limit, so the caller passes what is left after its own text.
    """
    pages = _budget_pages(data, budget)
    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 0
    page = max(0, min(page, len(pages) - 1))
    return page, len(pages), _text_blocks(pages[page])


def summary_line(data: AccountsData) -> str:
    if data.loaded_count == data.linked_count:
        return f"**{data.loaded_count} {_plural(data.loaded_count, 'linked account')}**"
    return (
        f"**{data.loaded_count} {_plural(data.loaded_count, 'player profile')} loaded** "
        f"· **{data.linked_count} linked {_plural(data.linked_count, 'tag')} total**"
    )


def account_notes(data: AccountsData) -> list[str]:
    """Outage and partial-load notes. An outage is never shown as "no links"."""
    notes: list[str] = []
    if data.unavailable_sources:
        notes.append(
            f"⚠️ **Incomplete list:** Could not reach {', '.join(data.unavailable_sources)}. "
            "More accounts can be linked. Try again in a few minutes."
        )
    if data.error_count:
        if coc_maintenance.in_maintenance():
            notes.append(coc_maintenance.banner())
        elif data.error_count == 1:
            notes.append(
                "⚠️ **Could not load 1 account.** "
                "Its linked tag is shown above. Try again in a few minutes."
            )
        else:
            notes.append(
                f"⚠️ **Could not load {data.error_count} accounts.** "
                "Their linked tags are shown above. Try again in a few minutes."
            )
    if data.not_found_count:
        notes.append(
            f"ℹ️ **{data.not_found_count} linked "
            f"{_plural(data.not_found_count, 'tag')} returned no player profile.** "
            "These may be old or mistyped links."
        )
    return notes


# Merged ClashKing + ClashPerk results for /profile and the staff alert. Kept
# apart from ``_result_cache`` (ClashKing-only, Clash of Cards) so neither path
# can serve the other's answer.
_merged_cache: dict[int, tuple[float, AccountsData]] = {}


def cached_merged(discord_id: int) -> AccountsData | None:
    hit = _merged_cache.get(int(discord_id))
    if hit is None or time.monotonic() >= hit[0]:
        _merged_cache.pop(int(discord_id), None)
        return None
    return hit[1]


def remember_merged(discord_id: int, data: AccountsData) -> None:
    now = time.monotonic()
    for user_id, (expires_at, _data) in list(_merged_cache.items()):
        if expires_at <= now:
            _merged_cache.pop(user_id, None)
    _merged_cache[int(discord_id)] = (now + RESULT_TTL, data)


def forget(*discord_ids: int | None) -> None:
    """Drop cached link inventories after a link change."""
    for discord_id in discord_ids:
        if discord_id is not None:
            _result_cache.pop(int(discord_id), None)
            _merged_cache.pop(int(discord_id), None)
