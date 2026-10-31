"""Compare-only cached owner nicknames; reads never wait for Discord."""

import asyncio
import time


def cached_owner_nicknames(request, owner_ids):
    state = request.app.setdefault("roster_owner_nicknames", {})
    task = state.get("task")
    if (task is None or task.done()) and time.monotonic() >= state.get("until", 0):

        async def refresh():
            try:
                from .manage_roles import searchable_members

                async with asyncio.timeout(8):
                    rows = await searchable_members(request)
                    if not isinstance(rows, list):
                        raise ValueError("Invalid member directory")
                    state["names"] = {
                        str(row["user"]["id"]): row["nick"][:100]
                        for row in rows
                        if isinstance(row, dict)
                        and isinstance(row.get("user"), dict)
                        and row["user"].get("id")
                        and isinstance(row.get("nick"), str)
                        and row["nick"].strip()
                    }
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
            state["until"] = time.monotonic() + 120

        state["task"] = asyncio.create_task(refresh(), name="roster-owner-nicknames")
    names = state.get("names", {})
    return {str(owner): names[str(owner)] for owner in owner_ids if str(owner) in names}


async def lifecycle(app):
    yield
    task = app.get("roster_owner_nicknames", {}).get("task")
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def enrich(request, result):
    result['owner_nicknames'] = cached_owner_nicknames(
        request, {row['user_id'] for row in result['accounts']})
    task = request.app.get('roster_owner_nicknames', {}).get('task')
    result['metadata_updating'] = bool(result.get('metadata_updating') or task and not task.done())
