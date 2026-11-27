"""Shared management snapshots used by the bot and dashboard adapters."""

import hashlib
import json
import re
import time


def revision(row):
    encoded = json.dumps(row or {}, sort_keys=True, default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def public_band_error(value):
    """Expose known diagnostic codes, never arbitrary upstream exception text."""
    value = str(value or "")
    if not value:
        return ""
    known_code = (
        r"(?:band_request_failed|unexpected_band_response|"
        r"band_api_result_-?[0-9]{1,12}|monitor_exception_[A-Za-z]{1,60})"
    )
    if re.fullmatch(known_code, value):
        return value
    return "Monitor check failed. Staff can find details in the logs."


def runtime_snapshot(monitor):
    """Called only inside the bot worker; never expose the BAND credential."""
    health = monitor.poll_health
    running = monitor.band_check_task and not monitor.band_check_task.done()
    startup = monitor.startup_reconciler
    return {
        "checked_at": time.time(),
        "task": "Running" if running else "Stopped",
        "startup": startup.status_text() if startup else "Stopped",
        "key_ready": bool(monitor.BAND_KEY),
        "health": str(getattr(health, "state", "unknown")),
        "last_success": str(getattr(health, "last_success_at", None) or ""),
        "last_error": public_band_error(getattr(health, "last_error", None)),
        "debug": bool(monitor.DEBUG_MODE),
    }


def publish_base_image_snapshot(doc):
    """Publish shared registry images under both legacy variant cache keys."""
    from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE
    from utils.media_urls import optimized, DETAIL
    from utils import town_halls

    if doc is None:
        return False
    war, active = {}, {}
    for level in town_halls.levels(doc):
        if level < doc['lowest_fwa_town_hall']:
            continue
        bases = doc['levels'][str(level)].get('bases', {})
        for field, target in (('war_image', war), ('active_image', active)):
            url = bases.get(field, '')
            if url:
                converted = optimized(url, width=DETAIL)
                target[f'th{level}'] = converted
                target[f'th{level}_new'] = converted
    FWA_WAR_BASE.clear()
    FWA_WAR_BASE.update(war)
    FWA_ACTIVE_WAR_BASE.clear()
    FWA_ACTIVE_WAR_BASE.update(active)
    return True


async def refresh_base_image_cache(mongo, *, force=False):
    """Existing image poll now reads through the registry storage owner only."""
    from utils import town_halls
    from utils.manage_poll_cache import state_for
    state = state_for(mongo)
    async with state.images_lock:
        if not force and time.monotonic() - state.images_at < 60:
            return False
        doc = await town_halls.load(mongo, 644963518025826315)
        if doc is None:
            return False
        publish_base_image_snapshot(doc)
        state.images_at = time.monotonic()
        return True


async def refresh_town_halls_cache(mongo, *, force=False, startup=False, expected_revision=None):
    """Bot-only snapshot refresh; one attempt per five minutes after failure too."""
    from utils import town_halls
    from utils.manage_poll_cache import state_for

    state = state_for(mongo)
    async with state.town_halls_lock:
        if not force and time.monotonic() - state.town_halls_at < 300:
            return False
        refreshed = await town_halls.refresh_snapshot(
            mongo, 644963518025826315, log_failure=not startup, expected_revision=expected_revision
        )
        state.town_halls_at = time.monotonic()
        if refreshed:
            publish_base_image_snapshot(town_halls.snapshot(644963518025826315))
        if startup and not refreshed:
            import logging
            logging.getLogger(__name__).error("Town Halls not migrated or unavailable")
        return refreshed


async def apply_town_halls_refresh(mongo, row, actor):
    """Reauthorize a queued refresh and bind it to the committed revision.

    A newer save makes an older refresh request stale; the periodic refresh
    recovers the latest registry independently of durable request status.
    """
    from utils import town_halls
    from utils.dashboard_access import dashboard_allowed

    if (row.get("guild_id") != 644963518025826315
            or row.get("section") != "town_halls"
            or row.get("action") != "refresh"
            or row.get("values") != {}
            or type(row.get("revision")) is not int
            or row["revision"] < 0):
        raise ValueError("Invalid Town Halls refresh request.")
    if not actor or not (await dashboard_allowed(actor, "fwa_weight", mongo, write=True)
                         or await dashboard_allowed(actor, "fwa_bases", mongo, write=True)):
        raise ValueError("Your Discord access changed. This action was not run.")
    doc = await town_halls.load(mongo, row["guild_id"])
    if doc is None:
        raise town_halls.TownHallsMissing(town_halls.MISSING_MESSAGE)
    if doc["revision"] != row["revision"]:
        raise town_halls.TownHallsConflict(town_halls.CONFLICT_MESSAGE)
    if not await refresh_town_halls_cache(mongo, force=True, expected_revision=row["revision"]):
        raise ValueError("Town Halls could not refresh. The last saved snapshot is retained.")
    return {"message": "Town Halls refreshed.", "revision": doc["revision"]}
