"""Short-lived single-flight Discord identity reads for moderation history only."""
import asyncio
import re
import time
from collections import OrderedDict

KEY = 'moderation_identity_reads'
TTL = 30
LIMIT = 128


def eligible(request):
    return request.method == 'GET' and (
        request.path == '/api/cwl/manage/member-events'
        or re.fullmatch(r'/api/cwl/manage/member-events/[^/]+/avatar', request.path)
    )


def invalidate(app, user_id):
    # Removing the task prevents its completion from repopulating the cache.
    app.get(KEY, {}).pop(str(user_id), None)


async def read(app, user_id, fetch):
    cache = app.setdefault(KEY, OrderedDict())
    key = str(user_id)
    entry = cache.get(key)
    if entry and entry['task'].done() and entry['until'] <= time.monotonic():
        cache.pop(key)
        entry = None
    if entry is None:
        entry = {'task': asyncio.create_task(fetch()), 'until': 0}
        cache[key] = entry
        def finished(task):
            # Retrieve errors even if the initiating HTTP request was cancelled.
            failed = task.cancelled() or task.exception() is not None
            if cache.get(key) is entry:
                if failed:
                    cache.pop(key, None)
                else:
                    entry['until'] = time.monotonic() + TTL
        entry['task'].add_done_callback(finished)
        while len(cache) > LIMIT:
            cache.popitem(last=False)
    cache.move_to_end(key)
    try:
        return await asyncio.shield(entry['task'])
    except BaseException:
        if entry['task'].done() and cache.get(key) is entry:
            cache.pop(key, None)
        raise
