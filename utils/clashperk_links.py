"""Read-only ClashPerk links. Credentials stay in env; JWTs only in memory."""
import asyncio
import os
import time

import aiohttp

BASE_URL = "https://api.clashperk.com/v1"
_token = ""
_expires = 0.0
_key = ""
_lock = asyncio.Lock()


async def _login(session, *, rejected=None):
    global _token, _expires, _key
    key = os.getenv("CLASHPERK_PASSKEY", "").strip()
    if not key:
        return None
    async with _lock:
        if _key == key and _token and time.monotonic() < _expires and _token != rejected:
            return _token
        async with session.post(BASE_URL + "/auth/login", json={"passKey": key}, allow_redirects=False) as response:
            if response.status != 200 and response.status != 201:
                return None
            data = await response.json()
        token = data.get("accessToken") if isinstance(data, dict) else None
        if not isinstance(token, str) or not token:
            return None
        _token, _key, _expires = token, key, time.monotonic() + 6600
        return token


async def lookup(*, discord_ids=None, player_tags=None):
    """Return records, [] for confirmed empty, or None for unavailable.

    Exactly one lookup direction per request. A failed batch invalidates the
    whole response; it must never masquerade as an authoritative short list.
    """
    field, values = ("userIds", discord_ids) if discord_ids is not None else ("playerTags", player_tags)
    if discord_ids is not None and player_tags is not None:
        raise ValueError("Choose one lookup direction")
    values = list(dict.fromkeys(values or []))
    if not values:
        return []
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
            token = await _login(session)
            if not token:
                return None
            records = []
            for start in range(0, len(values), 100):
                for attempt in range(2):
                    async with session.post(BASE_URL + "/links/query", json={field: values[start:start + 100]}, headers={"Authorization": "Bearer " + token}, allow_redirects=False) as response:
                        if response.status == 401 and attempt == 0:
                            token = await _login(session, rejected=token)
                            if not token:
                                return None
                            continue
                        if response.status != 200:
                            return None
                        payload = await response.json()
                        if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
                            return None
                        records.extend(payload)
                        break
            return records
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, TypeError):
        return None
