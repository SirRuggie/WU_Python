"""One deterministic publication order for image lists and send sequences."""
import re
from collections.abc import Iterable, Mapping
from typing import TypeVar

Clan = TypeVar('Clan', bound=Mapping)


def roster_clan_key(clan: Mapping) -> tuple:
    name = str(clan.get('name') or '')
    tie = (name.casefold(), str(clan.get('tag') or ''))
    if clan.get('pool') == 'lazy':
        number = re.search(r'\.\s*([0-9]+)\s*$', name)
        return (1, 0, -int(number[1]), *tie) if number else (1, 1, 0, *tie)
    capacity = clan.get('capacity')
    group = 0 if capacity == 30 else 1 if capacity == 15 else 2
    return (0, group, 0, *tie)


def ordered_roster_clans(clans: Iterable[Clan]) -> list[Clan]:
    """Preserve the supplied snapshots; only order them, never mutate them."""
    return sorted(clans, key=roster_clan_key)
