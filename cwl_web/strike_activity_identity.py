"""Immediate cached identities; one bounded background refresh, including failures."""

import asyncio
import time
import logging

log = logging.getLogger(__name__)
from utils import recruit_links


async def account_identities(request, tags):
    wanted = tuple(sorted(set(tags)))
    state = request.app.setdefault("activity_identity_cache", {})
    task = state.get("task")
    if (task is None or task.done()) and (
        state.get("tags") != wanted or time.monotonic() >= state.get("until", 0)
    ):

        async def refresh():
            identities = {}
            failed = False
            started = time.monotonic()
            try:
                from .manage_roles import searchable_members

                async with asyncio.timeout(110):
                    owners = await recruit_links.resolve_players(list(wanted))
                    if owners.conflicts:
                        state["identities"] = {
                            k: v
                            for k, v in state.get("identities", {}).items()
                            if k not in owners.conflicts
                        }
                    identities = {
                        tag: {"discord_id": str(owner), "discord_name": None}
                        for tag, owner in owners.owners.items()
                        if tag not in owners.conflicts
                    }
                    directory = await searchable_members(request)
                    if not isinstance(directory, list):
                        raise ValueError("Invalid member directory")
                    names = {}
                    for item in directory:
                        user = item.get("user") if isinstance(item, dict) else None
                        if not isinstance(user, dict) or not user.get("id"):
                            continue
                        name = next(
                            (
                                v.strip()[:100]
                                for v in (
                                    item.get("nick"),
                                    user.get("global_name"),
                                    user.get("username"),
                                )
                                if isinstance(v, str) and v.strip()
                            ),
                            None,
                        )
                        if name:
                            names[str(user["id"])] = name
                    identities = {
                        tag: {
                            "discord_id": str(owner),
                            "discord_name": names.get(str(owner)),
                        }
                        for tag, owner in owners.owners.items()
                        if tag not in owners.conflicts
                    }
                    failed = (bool(owners.unavailable) and not identities) or (
                        bool(identities)
                        and not any(row["discord_name"] for row in identities.values())
                    )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failed = True
                for tag, row in identities.items():
                    old = state.get("identities", {}).get(tag, {})
                    if old.get("discord_id") == row["discord_id"]:
                        row["discord_name"] = old.get("discord_name")
                log.warning(
                    "Activity identity refresh failed tags=%s elapsed=%.2fs error=%s",
                    len(wanted),
                    time.monotonic() - started,
                    type(error).__name__,
                )
            state.update(tags=wanted, until=time.monotonic() + 120, failed=failed)
            if identities:
                state["identities"] = identities

        state["task"] = asyncio.create_task(refresh(), name="activity-identity-refresh")
    cached = state.get("identities", {})
    result = {tag: cached[tag] for tag in wanted if tag in cached}
    return result, bool(state.get("failed")) and not any(
        row.get("discord_name") for row in result.values()
    )


def identity_updating(request):
    task = request.app.get("activity_identity_cache", {}).get("task")
    return bool(task is not None and not task.done())
