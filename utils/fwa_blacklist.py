# utils/fwa_blacklist.py
"""Ongoing list of opponent clans blacklisted from FWA wars.

Staff-maintained: ChocolateClash is Cloudflare-blocked with no API (see
docs/fwa-sites-access.md style notes), so there is no automated way to detect
"this opponent is a known blacklisted clan" - entries only get in when staff
pick "Blacklisted" in /fwa war-plans (which records the opponent CoC returns
for the current war) or add one by hand with /fwa blacklist add.

Documents are keyed by the sanitized tag (no '#', uppercase - see
utils.fwa_points_parser.sanitize_tag) and stored in mongo.fwa_blacklist:

    {
        "_id": "ABC123",
        "name": "Some Clan",
        "added_at": "2026-09-08T12:00:00+00:00",   # ISO, set once, never overwritten
        "added_by_id": 123456789012345678,
        "added_by_name": "SomeStaffer",
        "source": "war-plans" | "manual",           # set once, never overwritten
        "last_seen_clan_tag": "ABCDE",                # our clan tag, most recent sighting
        "last_war_end_time": "2026-09-08T20:00:00",   # ISO, most recent sighting
    }
"""

from datetime import datetime, timezone
from typing import Iterable, Optional

from utils.fwa_points_parser import sanitize_tag


async def add_blacklisted(
    mongo,
    tag: str,
    name: str,
    added_by_id,
    added_by_name: str,
    source: str,
    our_clan_tag: Optional[str] = None,
    war_end_time: Optional[str] = None,
) -> Optional[str]:
    """Add (or refresh) a blacklist entry. Returns the sanitized tag, or None
    if `tag` is invalid.

    On an existing entry, `added_at`/`added_by_id`/`added_by_name`/`source`
    are left untouched (set only on first insert via $setOnInsert) while
    `name` and the last-seen fields are always refreshed to the latest
    sighting.
    """
    t = sanitize_tag(tag)
    if not t:
        return None

    now = datetime.now(timezone.utc).isoformat()
    await mongo.fwa_blacklist.update_one(
        {"_id": t},
        {
            "$set": {
                "name": name,
                "last_seen_clan_tag": our_clan_tag,
                "last_war_end_time": war_end_time,
            },
            "$setOnInsert": {
                "added_at": now,
                "added_by_id": added_by_id,
                "added_by_name": added_by_name,
                "source": source,
            },
        },
        upsert=True,
    )
    return t


async def remove_blacklisted(mongo, tag: str) -> bool:
    """Remove a blacklist entry. Returns False if it was not there."""
    t = sanitize_tag(tag)
    if not t:
        return False
    result = await mongo.fwa_blacklist.delete_one({"_id": t})
    return bool(getattr(result, "deleted_count", 0))


async def is_blacklisted(mongo, tag: str) -> bool:
    t = sanitize_tag(tag)
    if not t:
        return False
    doc = await mongo.fwa_blacklist.find_one({"_id": t})
    return doc is not None


async def blacklisted_tags(mongo, tags: Iterable[str]) -> set[str]:
    """Which of `tags` (any format) are on the blacklist, as sanitized tags."""
    sanitized = {sanitize_tag(t) for t in tags}
    sanitized.discard("")
    if not sanitized:
        return set()
    docs = await mongo.fwa_blacklist.find(
        {"_id": {"$in": list(sanitized)}}, {"_id": 1}
    ).to_list(length=None)
    return {doc["_id"] for doc in docs}


async def list_blacklisted(mongo) -> list[dict]:
    """Every blacklist entry, sorted by name."""
    return await mongo.fwa_blacklist.find({}).sort("name", 1).to_list(length=None)
