"""Warriors United server membership for dashboard sessions.

Sign-in does not need the server. Only a CWL signup save does. The save always
checks Discord live; `/auth/me` uses a short cache so the page can show the
join line without a Discord call on every read.
"""

import asyncio
import time

from utils.cwl_member_service import MemberError

CHECK_KEY = "discord_member_check"
CACHE_KEY = "server_member_cache"
CACHE_SECONDS = 60
STATUS_TIMEOUT_SECONDS = 3
JOIN_REQUIRED = "Join the Warriors United Discord server to sign up."
CHECK_UNAVAILABLE = "Discord membership check is unavailable. Try again."


def _check(app):
    # None only in fixture and test apps, which have no Discord access.
    return app.get(CHECK_KEY)


def _remember(app, user_id, value):
    cache = app.setdefault(CACHE_KEY, {})
    now = time.monotonic()
    for key, (expires, _) in list(cache.items()):
        if expires <= now:
            cache.pop(key, None)
    cache[user_id] = (now + CACHE_SECONDS, value)


async def require_server_member(request, user_id):
    """Live check for a signup save. Never served from the cache."""
    check = _check(request.app)
    if check is None:
        return
    try:
        await check(request, user_id)
    except MemberError as exc:
        if exc.status == 403:
            _remember(request.app, user_id, False)
            raise MemberError(403, JOIN_REQUIRED) from None
        raise MemberError(503, CHECK_UNAVAILABLE) from None
    except Exception as exc:
        raise MemberError(503, CHECK_UNAVAILABLE) from exc
    _remember(request.app, user_id, True)


async def server_member_status(request, user_id):
    """True, False, or None when Discord could not answer. Never raises."""
    check = _check(request.app)
    if check is None:
        return True
    cached = request.app.get(CACHE_KEY, {}).get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        await asyncio.wait_for(check(request, user_id), STATUS_TIMEOUT_SECONDS)
    except MemberError as exc:
        if exc.status == 403:
            _remember(request.app, user_id, False)
            return False
        return None
    except Exception:
        return None
    _remember(request.app, user_id, True)
    return True
