"""One optional read-only ownership/directory batch for a Declaration check."""

import asyncio
import logging
import re
from utils.account_links import linked_owners
from .manage_roles import searchable_members, member_option

log = logging.getLogger(__name__)


async def decorate(request, clans):
    rows = [
        row
        for clan in clans
        for field in ("extras", "low_th", "fillers", "unpublished")
        for row in clan.get(field) or []
    ]
    tags = sorted({row["tag"] for row in rows})
    if not tags:
        return
    identities = {}
    try:
        # Preserve member-comparison results on either provider's failure. This
        # timeout bounds the whole optional batch, not one timeout per account.
        async with asyncio.timeout(8):
            owners = await linked_owners(tags)
            if owners:
                directory = await searchable_members(request)
                wanted = set(owners.values())
                profiles = {}
                for member in directory:
                    uid = str(member.get("user", {}).get("id") or "")
                    if uid not in wanted or not re.fullmatch(r"[0-9]{15,22}", uid):
                        continue
                    profile = member_option(member)
                    profiles[uid] = {
                        key: profile.get(key)
                        for key in ("id", "display_name", "username", "avatar_url")
                    }
                identities = {
                    tag: profiles[uid] for tag, uid in owners.items() if uid in profiles
                }
    except asyncio.CancelledError:
        raise
    except Exception as error:
        log.warning(
            "Declaration optional Discord batch unavailable (%s)", type(error).__name__
        )
    for row in rows:
        profile = identities.get(row["tag"])
        if profile is not None:
            row["discord_id"] = profile["id"]
            row["discord_profile"] = profile
