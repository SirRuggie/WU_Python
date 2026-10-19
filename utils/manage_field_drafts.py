"""Short-lived, actor-bound snapshots for Discord field editors."""
import copy
import secrets
import time

_PENDING = {}
TTL = 900


def remember(owner, scope, document, fields):
    now = time.monotonic()
    for token, row in list(_PENDING.items()):
        if row[0] < now - TTL:
            del _PENDING[token]
    while len(_PENDING) >= 1000:
        del _PENDING[next(iter(_PENDING))]
    baseline = {}
    for field in fields:
        value = document
        for part in field.split('.'):
            if not isinstance(value, dict) or part not in value:
                value = {'$exists': False}
                break
            value = value[part]
        baseline[field] = copy.deepcopy(value)
    token = secrets.token_urlsafe(16)
    _PENDING[token] = (now, int(owner), scope, baseline)
    return token


def consume(token, owner, scope):
    row = _PENDING.get(token)
    if row is None or row[1:3] != (int(owner), scope):
        return None
    del _PENDING[token]
    return row[3] if row[0] >= time.monotonic() - TTL else None


async def save_fields(collection, key, baseline, changes):
    """Only changed fields participate, allowing unrelated concurrent edits."""
    if baseline is None or any(field not in baseline for field in changes):
        return False
    changes = {field: value for field, value in changes.items() if value != baseline[field]}
    if not changes:
        return True
    result = await collection.update_one(
        {'_id': key, **{field: baseline[field] for field in changes}},
        {'$set': changes},
    )
    return bool(result.matched_count)
