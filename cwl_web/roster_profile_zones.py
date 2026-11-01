"""Editor-only, scoped profile timezone cache; Mongo reads stay off the page path."""

import asyncio
import logging
import time
from utils.member_profiles import MemberProfiles, member_id
from utils.member_timezones import zone

log = logging.getLogger(__name__)


def cached_profile_zones(request, owner_ids):
    wanted = []
    for owner in owner_ids:
        try:
            wanted.append(member_id(owner))
        except ValueError:
            continue
    wanted = tuple(sorted(set(wanted)))
    state = request.app.setdefault("roster_profile_zones", {})
    task = state.get("task")
    if (task is None or task.done()) and (
        state.get("wanted") != wanted or time.monotonic() >= state.get("until", 0)
    ):

        async def refresh():
            try:
                from .server_management import mongo

                async with asyncio.timeout(8):
                    async with mongo(request) as db:
                        rows = await MemberProfiles(db).for_members(wanted)
                values = {}
                for owner, row in rows.items():
                    try:
                        value = zone(row.get("zone_id"))
                        values[owner] = {
                            "label": value["gmt_label"],
                            "offsetMinutes": value["utc_offset_minutes"],
                        }
                    except ValueError:
                        log.warning(
                            "Invalid saved member timezone; falling back to nickname"
                        )
                state["zones"] = values
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.warning(
                    "Roster member profile read failed (%s); retaining cache",
                    type(error).__name__,
                )
            finally:
                state.update(wanted=wanted, until=time.monotonic() + 30)

        state["task"] = asyncio.create_task(refresh(), name="roster-profile-zones")
    return {
        owner: state.get("zones", {})[owner]
        for owner in wanted
        if owner in state.get("zones", {})
    }


async def lifecycle(app):
    yield
    task = app.get("roster_profile_zones", {}).get("task")
    if task is not None and not task.done():
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
