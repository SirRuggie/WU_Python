"""Shared, fail-closed account ownership across ClashKing and ClashPerk.

This module has no dashboard or Discord runtime dependency. Conflicting owners
are deliberately omitted from automatic mention maps.
"""
import asyncio
import re

from utils.clash_links import _lookup_shared_links
from utils.clashperk_links import lookup as _lookup_clashperk_links


class LinksUnavailable(Exception):
    """At least one link source could not supply an authoritative response."""


def normalize_records(results):
    combined = []
    for index, rows in enumerate(results):
        for item in rows:
            if not isinstance(item, dict):
                continue
            value = str(item.get('player_tag' if index == 0 else 'tag') or '').strip().upper().replace('O', '0')
            value = value if value.startswith('#') else '#'+value
            uid = str(item.get('user_id' if index == 0 else 'userId') or '')
            if re.fullmatch(r'#[0289PYLQGRJCUV]{3,15}', value) and re.fullmatch(r'[0-9]{1,22}', uid):
                verified = item.get('is_verified' if index == 0 else 'verified') is True
                combined.append((value, uid, verified))
    return combined


async def lookup_links(*, discord_ids=None, player_tags=None, king=None, perk=None):
    """Return normalized records; unavailable must never become unlinked."""
    if (discord_ids is None) == (player_tags is None):
        raise ValueError('Choose exactly one link lookup direction.')
    query = {'discord_ids': discord_ids} if discord_ids is not None else {'player_tags': player_tags}
    results = await asyncio.gather(
        (king or _lookup_shared_links)(**query),
        (perk or _lookup_clashperk_links)(**query),
    )
    if any(rows is None for rows in results):
        raise LinksUnavailable('Could not load all linked accounts. Try again shortly.')
    return normalize_records(results)


async def linked_owners(player_tags):
    wanted = set(player_tags)
    choices = {}
    for tag, uid, _ in await lookup_links(player_tags=player_tags):
        if tag in wanted:
            choices.setdefault(tag, set()).add(uid)
    return {tag: next(iter(ids)) for tag, ids in choices.items() if len(ids) == 1}
