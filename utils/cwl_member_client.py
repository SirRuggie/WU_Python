"""Bot client for the dashboard-owned CWL member service; never retries writes."""
from __future__ import annotations

import ipaddress
import json
import os
from urllib.parse import urlsplit

import aiohttp


class MemberClientError(Exception):
    def __init__(self, message: str, *, uncertain: bool = False):
        super().__init__(message)
        self.uncertain = uncertain


def bridge_config() -> tuple[str, str]:
    base = os.getenv('CWL_DISCORD_BRIDGE_URL', 'http://127.0.0.1:8767').rstrip('/')
    secret = os.getenv('CWL_DISCORD_BRIDGE_SECRET', '')
    try:
        parsed = urlsplit(base)
        address = ipaddress.ip_address(parsed.hostname or '')
        valid = (parsed.scheme == 'http' and address.is_loopback
                 and not parsed.username and not parsed.password
                 and not parsed.query and not parsed.fragment and parsed.path in ('', '/'))
        parsed.port  # Reject invalid ports before attempting the request.
    except ValueError:
        valid = False
    if not valid or len(secret) < 32:
        raise MemberClientError('Discord CWL is unavailable. Please use the dashboard or try again later.')
    return base + '/api/cwl/discord/member', secret


async def request(action: str, *, user_id: int | str, guild_id: int | str, **payload) -> dict:
    """Make exactly one request. Transport failures after dispatch are ambiguous."""
    if action not in {'view', 'submit', 'withdraw'}:
        raise ValueError('Invalid member action')
    url, secret = bridge_config()
    writing = action != 'view'
    body = {**payload, 'action': action, 'user_id': str(user_id), 'guild_id': str(guild_id)}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post(url, json=body, headers={'X-CWL-Discord-Secret': secret},
                                    allow_redirects=False) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    raw.extend(chunk)
                    if len(raw) > 256 * 1024:
                        raise ValueError('Oversized response')
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError('Invalid response')
                if response.status != 200:
                    if response.status in {400, 403, 409, 423}:
                        raise MemberClientError(str(data.get('error') or 'This action is no longer available. Reopen /cwl-member.'))
                    raise MemberClientError(
                        'CWL is unavailable. Check My signups before trying to save again.' if writing
                        else 'CWL is unavailable. Please try again later.', uncertain=writing)
                return data
    except MemberClientError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise MemberClientError(
            'The save could not be confirmed. Check My signups before trying again.' if writing
            else 'CWL is unavailable. Please try again later.', uncertain=writing) from exc
