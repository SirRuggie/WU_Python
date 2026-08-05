"""Discord account <-> Clash player tag resolution.

The source of truth is the shared community link database (cocdiscord.link),
reached through ClashKing's unauthenticated passthrough. wu-bot holds no
credentials for it and needs none.

Read docs/clashking-discord-links.md before changing anything here. The two
facts that are easy to get wrong:

  1. The request body is an IDENTIFIER array, not a tag array. The server
     accepts player tags OR Discord ids in the same field, which is why one
     endpoint serves both directions.
  2. The response echoes your input back with a null value. A reverse lookup
     for 505227988229554179 contains {"#505227988229554179": null} alongside
     the real tags. Filter by VALUE, never by key.
"""

import aiohttp

LINK_API_URL = "https://api.clashk.ing/discord_links"

# The endpoint fans out internally; 15s is generous for a single id and still
# well inside the 15-minute deferred-response window.
_TIMEOUT = aiohttp.ClientTimeout(total=15)
# Clan-sized calls in the existing bot are 50 identifiers. Keep family sweeps
# conservative rather than handing the free community endpoint thousands at
# once; the hourly cache makes the extra batches cheap.
_BATCH_SIZE = 100


async def _resolve_identifiers(identifiers: list[str]) -> dict | None:
    """Resolve mixed player-tag/Discord identifiers in bounded API batches."""
    wanted = list(dict.fromkeys(str(value).strip().lstrip("#") for value in identifiers if str(value).strip()))
    if not wanted:
        return {}

    result: dict = {}
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            for start in range(0, len(wanted), _BATCH_SIZE):
                batch = wanted[start:start + _BATCH_SIZE]
                async with session.post(
                    LINK_API_URL,
                    json=batch,
                    headers={"Content-Type": "application/json"},
                ) as response:
                    if response.status != 200:
                        body = await response.text()
                        print(f"[links] link API returned {response.status}: {body[:200]}")
                        return None
                    payload = await response.json()
                    if not isinstance(payload, dict):
                        print(f"[links] unexpected link API payload type: {type(payload).__name__}")
                        return None
                    result.update(payload)
    except Exception as exc:
        print(f"[links] link API request failed: {exc}")
        return None
    return result


async def resolve_tags(discord_id: int) -> list[str] | None:
    """Every Clash player tag linked to a Discord account.

    Returns:
        list[str]  tags WITH the "#" prefix. **May legitimately be empty** -
                   that is a real answer meaning "this user has linked nothing".
        None       the lookup FAILED. The answer is unknown.

    NONE AND [] ARE DIFFERENT AND CALLERS MUST TELL THEM APART. Conflating them
    tells a user whose link service is down that they have no accounts, and
    sends them off to fix a problem they do not have. This is the same bug that
    was fixed in lazy_cwl.get_discord_ids; do not reintroduce it here.
    """
    result = await _resolve_identifiers([str(discord_id)])
    if result is None:
        return None

    # Keep only entries whose VALUE is the id we asked about. This drops the
    # echoed "#<discord_id>": null entry for free, and would also drop any
    # unrelated pair if the server ever batched differently.
    wanted = str(discord_id)
    return [tag for tag, owner in result.items() if owner is not None and str(owner) == wanted]


async def resolve_family_linked_tags(player_tags: list[str]) -> list[str] | None:
    """Expand current family-roster players to every linked Clash account.

    The first pass resolves roster tags to Discord owners. The second reverses
    those owners back to all their linked accounts, including accounts that are
    currently in arbitrary non-family clans.

    Returns None when either pass fails. An empty list is a successful lookup
    where none of the supplied roster players have a link.
    """
    owners_by_tag = await _resolve_identifiers(player_tags)
    if owners_by_tag is None:
        return None

    discord_ids = sorted({
        str(owner)
        for owner in owners_by_tag.values()
        if owner is not None
    })
    if not discord_ids:
        return []

    tags_by_owner = await _resolve_identifiers(discord_ids)
    if tags_by_owner is None:
        return None

    wanted_owners = set(discord_ids)
    return sorted({
        tag.upper()
        for tag, owner in tags_by_owner.items()
        if owner is not None and str(owner) in wanted_owners and str(tag).startswith("#")
    })
