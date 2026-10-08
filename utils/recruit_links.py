"""Combined recruitment identity lookup; neither provider outranks the other.

Source outages are explicit. Contradictory owners are quarantined, not merged
into the applicant's identity. Historical ticket identities are never erased.
"""
import asyncio
import hashlib
import json
from dataclasses import dataclass, field

from utils import clash_links, clashperk_links


@dataclass(frozen=True)
class LinksResult:
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    verified: dict[str, bool] = field(default_factory=dict)
    unavailable: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    conflict_key: str = ""
    disputed_sources: dict[str, tuple[str, ...]] = field(default_factory=dict)


async def resolve(discord_id: int) -> LinksResult:
    wanted = str(int(discord_id))
    providers = {"ClashKing": clash_links._lookup_shared_links, "ClashPerk": clashperk_links.lookup}
    results = await asyncio.gather(*(call(discord_ids=[wanted]) for call in providers.values()))
    sources, verified, unavailable, conflicts = {}, {}, [], set()
    owners = {}
    def identity(row, provider):
        tag = clash_links._normalize_tag(row.get("player_tag" if provider == "ClashKing" else "tag"))
        owner = str(row.get("user_id" if provider == "ClashKing" else "userId") or "")
        # Actual Supercell alphabet; reject malformed upstream identifiers.
        if len(tag) < 4 or len(tag) > 10 or any(c not in "0289PYLQGRJCUV" for c in tag[1:]):
            return None, None
        return tag, owner
    for provider, rows in zip(providers, results):
        if rows is None:
            unavailable.append(provider)
            continue
        for row in rows:
            tag, owner = identity(row, provider)
            if tag is None or not owner.isdigit():
                if provider not in unavailable:
                    unavailable.append(provider)
                continue
            owners.setdefault(tag, {}).setdefault(provider, set()).add(owner)
            if owner == wanted:
                sources.setdefault(tag, []).append(provider)
                if provider == "ClashPerk":
                    verified[tag] = row.get("verified") is True
    # Check the union against both providers, including tags returned only by
    # the other service. A foreign owner must never silently become this user.
    if sources:
        reverse = await asyncio.gather(*(call(player_tags=list(sources)) for call in providers.values()))
        for provider, rows in zip(providers, reverse):
            if rows is None:
                if provider not in unavailable:
                    unavailable.append(provider)
                continue
            for row in rows:
                tag, owner = identity(row, provider)
                if tag is None or not owner.isdigit():
                    if provider not in unavailable:
                        unavailable.append(provider)
                    continue
                if tag in sources:
                    owners.setdefault(tag, {}).setdefault(provider, set()).add(owner)
                if tag in sources and owner.isdigit() and owner != wanted:
                    conflicts.add(tag)
    return LinksResult(
        {tag: tuple(dict.fromkeys(labels)) for tag, labels in sources.items() if tag not in conflicts},
        verified,
        tuple(unavailable), tuple(sorted(conflicts)),
        hashlib.sha256(json.dumps([wanted, {tag: {provider: sorted(ids) for provider, ids in owners[tag].items()} for tag in sorted(conflicts)}], sort_keys=True).encode()).hexdigest() if conflicts else "",
        {tag: tuple(dict.fromkeys(sources[tag])) for tag in sorted(conflicts)},
    )


@dataclass(frozen=True)
class PlayerOwners:
    owners: dict[str, str] = field(default_factory=dict)
    conflicts: tuple[str, ...] = ()
    unavailable: tuple[str, ...] = ()


async def resolve_players(player_tags: list[str]) -> PlayerOwners:
    """Combine CK and CP reverse links without arbitrarily choosing an owner."""
    wanted = {clash_links._normalize_tag(tag) for tag in player_tags}
    wanted.discard('')
    if not wanted:
        return PlayerOwners()
    providers = {'ClashKing': clash_links._lookup_shared_links, 'ClashPerk': clashperk_links.lookup}
    results = await asyncio.gather(
        *(call(player_tags=sorted(wanted)) for call in providers.values()),
        return_exceptions=True,
    )
    owners, unavailable = {}, []
    for provider, rows in zip(providers, results):
        if rows is None or isinstance(rows, Exception):
            unavailable.append(provider)
            continue
        for row in rows:
            tag = clash_links._normalize_tag(row.get('player_tag' if provider == 'ClashKing' else 'tag'))
            owner = str(row.get('user_id' if provider == 'ClashKing' else 'userId') or '')
            if tag not in wanted:
                continue
            if not owner.isascii() or not owner.isdigit() or int(owner) <= 0:
                if provider not in unavailable:
                    unavailable.append(provider)
                continue
            owners.setdefault(tag, set()).add(str(int(owner)))
    return PlayerOwners(
        owners={tag: next(iter(ids)) for tag, ids in owners.items() if len(ids) == 1},
        conflicts=tuple(sorted(tag for tag, ids in owners.items() if len(ids) > 1)),
        unavailable=tuple(unavailable),
    )
