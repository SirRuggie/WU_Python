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
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.post(
                LINK_API_URL,
                json=[str(discord_id)],
                headers={"Content-Type": "application/json"},
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    print(f"[links] link API returned {response.status}: {body[:200]}")
                    return None
                result = await response.json()
    except Exception as exc:
        print(f"[links] link API request failed: {exc}")
        return None

    if not isinstance(result, dict):
        # Shape we were not expecting. Unknown beats wrong.
        print(f"[links] unexpected link API payload type: {type(result).__name__}")
        return None

    # Keep only entries whose VALUE is the id we asked about. This drops the
    # echoed "#<discord_id>": null entry for free, and would also drop any
    # unrelated pair if the server ever batched differently.
    wanted = str(discord_id)
    return [tag for tag, owner in result.items() if owner is not None and str(owner) == wanted]
