"""Authenticated Discord account <-> Clash player tag resolution."""

import os

import aiohttp

LINK_API_URL = "https://api.clashk.ing/v2/links/shared"
LINK_API_TOKEN_ENV = "CLASHKING_API_TOKEN"

# The endpoint fans out internally; 15s is generous for a single id and still
# well inside the 15-minute deferred-response window.
_TIMEOUT = aiohttp.ClientTimeout(total=15)
# Clan-sized calls in the existing bot are 50 identifiers. Keep family sweeps
# conservative rather than handing the free community endpoint thousands at
# once; the hourly cache makes the extra batches cheap.
_BATCH_SIZE = 100


def _normalize_tag(value: object) -> str:
    tag = str(value or "").strip().upper().replace("O", "0")
    if tag and not tag.startswith("#"):
        tag = f"#{tag}"
    return tag


async def _lookup_shared_links(
    *,
    discord_ids: list[str] | None = None,
    player_tags: list[str] | None = None,
) -> list[dict] | None:
    """Look up visible links through ClashKing's developer API."""
    token = os.getenv(LINK_API_TOKEN_ENV, "").strip()
    if not token:
        print(f"[links] {LINK_API_TOKEN_ENV} is not configured")
        return None

    discord_ids = list(dict.fromkeys(
        str(value).strip() for value in (discord_ids or []) if str(value).strip()
    ))
    player_tags = list(dict.fromkeys(
        tag for value in (player_tags or []) if (tag := _normalize_tag(value))
    ))
    identifiers = [("discord_ids", value) for value in discord_ids]
    identifiers.extend(("player_tags", value) for value in player_tags)
    if not identifiers:
        return []

    items: list[dict] = []
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            for start in range(0, len(identifiers), _BATCH_SIZE):
                batch = identifiers[start:start + _BATCH_SIZE]
                body = {
                    "discord_ids": [value for kind, value in batch if kind == "discord_ids"],
                    "player_tags": [value for kind, value in batch if kind == "player_tags"],
                }
                async with session.post(
                    LINK_API_URL,
                    json=body,
                    headers={"Authorization": f"Bearer {token}"},
                ) as response:
                    if response.status != 200:
                        detail = await response.text()
                        print(f"[links] link API returned {response.status}: {detail[:200]}")
                        return None
                    payload = await response.json()
                    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                        print(f"[links] unexpected link API payload: {type(payload).__name__}")
                        return None
                    items.extend(item for item in payload["items"] if isinstance(item, dict))
    except Exception as exc:
        print(f"[links] link API request failed: {exc}")
        return None
    return items


async def resolve_tags(discord_id: int) -> list[str] | None:
    """Every Clash player tag linked to a Discord account.

    Returns:
        list[str]  tags WITH the "#" prefix. **May legitimately be empty** -
                   that is a real answer meaning "this user has linked nothing".
        None       the lookup FAILED. The answer is unknown.

    NONE AND [] ARE DIFFERENT AND CALLERS MUST TELL THEM APART. Conflating them
    tells a user whose link service is down that they have no accounts, and
    sends them off to fix a problem they do not have. This is the same bug that
    was fixed in lazy_cwl_service.get_discord_ids; do not reintroduce it here.
    """
    wanted = str(int(discord_id))
    items = await _lookup_shared_links(discord_ids=[wanted])
    if items is None:
        return None
    return list(dict.fromkeys(
        tag
        for item in items
        if str(item.get("user_id") or "") == wanted
        and (tag := _normalize_tag(item.get("player_tag")))
    ))


async def resolve_discord_ids(player_tags: list[str]) -> dict[str, str] | None:
    """Map visible player tags to their linked Discord IDs."""
    items = await _lookup_shared_links(player_tags=player_tags)
    if items is None:
        return None
    return {
        tag: str(item.get("user_id"))
        for item in items
        if (tag := _normalize_tag(item.get("player_tag")))
        and str(item.get("user_id") or "").isdigit()
    }


async def resolve_family_linked_tags(player_tags: list[str]) -> list[str] | None:
    """Expand current family-roster players to every linked Clash account.

    The first pass resolves roster tags to Discord owners. The second reverses
    those owners back to all their linked accounts, including accounts that are
    currently in arbitrary non-family clans.

    Returns None when either pass fails. An empty list is a successful lookup
    where none of the supplied roster players have a link.
    """
    owners_by_tag = await resolve_discord_ids(player_tags)
    if owners_by_tag is None:
        return None

    discord_ids = sorted({
        str(owner)
        for owner in owners_by_tag.values()
        if owner is not None
    })
    if not discord_ids:
        return []

    linked_items = await _lookup_shared_links(discord_ids=discord_ids)
    if linked_items is None:
        return None

    wanted_owners = set(discord_ids)
    return sorted({
        tag
        for item in linked_items
        if str(item.get("user_id") or "") in wanted_owners
        and (tag := _normalize_tag(item.get("player_tag")))
    })
