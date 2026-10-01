"""Combined recruitment identity lookup; neither provider outranks the other.

Source outages are explicit. Contradictory owners are quarantined, not merged
into the applicant's identity. Historical ticket identities are never erased.
"""
import asyncio
from dataclasses import dataclass, field

from utils import clash_links, clashperk_links


@dataclass(frozen=True)
class LinksResult:
    sources: dict[str, tuple[str, ...]] = field(default_factory=dict)
    verified: dict[str, bool] = field(default_factory=dict)
    unavailable: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()


async def resolve(discord_id: int) -> LinksResult:
    wanted = str(int(discord_id))
    providers = {"ClashKing": clash_links._lookup_shared_links, "ClashPerk": clashperk_links.lookup}
    results = await asyncio.gather(*(call(discord_ids=[wanted]) for call in providers.values()))
    sources, verified, unavailable, conflicts = {}, {}, [], set()
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
                if tag in sources and owner.isdigit() and owner != wanted:
                    conflicts.add(tag)
    return LinksResult(
        {tag: tuple(dict.fromkeys(labels)) for tag, labels in sources.items() if tag not in conflicts},
        {tag: flag for tag, flag in verified.items() if tag not in conflicts},
        tuple(unavailable), tuple(sorted(conflicts)),
    )
