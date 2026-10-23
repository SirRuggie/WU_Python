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
    value = str(value or '')
    if not value:
        return ''
    known_code = (
        r'(?:band_request_failed|unexpected_band_response|'
        r'band_api_result_-?[0-9]{1,12}|monitor_exception_[A-Za-z]{1,60})'
    )
    if re.fullmatch(known_code, value):
        return value
    return 'Monitor check failed. Review the bot logs for details.'


def runtime_snapshot(monitor):
    """Called only inside the bot worker; never expose the BAND credential."""
    health = monitor.poll_health
    running = monitor.band_check_task and not monitor.band_check_task.done()
    startup = monitor.startup_reconciler
    return {
        'checked_at': time.time(),
        'task': 'Running' if running else 'Stopped',
        'startup': startup.status_text() if startup else 'Stopped',
        'key_ready': bool(monitor.BAND_KEY),
        'health': str(getattr(health, 'state', 'unknown')),
        'last_success': str(getattr(health, 'last_success_at', None) or ''),
        'last_error': public_band_error(getattr(health, 'last_error', None)),
        'debug': bool(monitor.DEBUG_MODE),
    }


async def refresh_base_image_cache(mongo):
    """Bot-worker hook after a web base save, using the same native cache format."""
    from utils.constants import FWA_WAR_BASE, FWA_ACTIVE_WAR_BASE
    from utils.media_urls import optimized, DETAIL

    row = await mongo.fwa_data.find_one({'_id': 'fwa_config'}) or {}
    for key, target in (
        ('war_base_images', FWA_WAR_BASE),
        ('active_base_images', FWA_ACTIVE_WAR_BASE),
    ):
        for th, url in row.get(key, {}).items():
            if url:
                target[th] = optimized(url, width=DETAIL)
            else:
                target.pop(th, None)
