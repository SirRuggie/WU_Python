"""Bot client for the dashboard-owned Clan weights bridge; never retries a save."""
from __future__ import annotations

import json

import aiohttp

from utils.cwl_member_client import MemberClientError, bridge_config

GUILD_ID = "644963518025826315"
UNAVAILABLE = "Weight saving is unavailable now. Try again later."


class WeightClientError(Exception):
    """``code`` is the bridge code; ``uncertain`` means a save may have happened."""

    def __init__(self, message: str, *, code: str = "error", uncertain: bool = False):
        super().__init__(message)
        self.code = code
        self.uncertain = uncertain


async def request(action: str, *, actor_id: int | str, **payload) -> dict:
    """Make exactly one request. A transport failure after a save is ambiguous."""
    if action not in {"access", "accounts", "lookup", "save"}:
        raise ValueError("Invalid weight action")
    try:
        url, secret = bridge_config()
    except MemberClientError:
        raise WeightClientError(UNAVAILABLE, code="unavailable") from None
    url = url.rsplit("/", 1)[0] + "/weight"
    writing = action == "save"
    body = {**payload, "action": action, "actor_id": str(actor_id), "guild_id": GUILD_ID}
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=45)) as session:
            async with session.post(
                url, json=body, headers={"X-CWL-Discord-Secret": secret}, allow_redirects=False
            ) as response:
                raw = bytearray()
                async for chunk in response.content.iter_chunked(16 * 1024):
                    raw.extend(chunk)
                    if len(raw) > 256 * 1024:
                        raise ValueError("Oversized response")
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Invalid response")
                if response.status == 200:
                    return data
                code = str(data.get("code") or "error")
                if response.status in {400, 403, 404, 409}:
                    raise WeightClientError(str(data.get("error") or UNAVAILABLE), code=code)
                if response.status == 503 and code in {"links_unavailable", "unavailable"}:
                    # The bridge raises these codes only before any ledger write.
                    raise WeightClientError(str(data.get("error") or UNAVAILABLE), code=code)
                raise WeightClientError(
                    "The save could not be confirmed. Select Try again to check the saved weight."
                    if writing else UNAVAILABLE,
                    code="uncertain" if writing else "unavailable",
                    uncertain=writing,
                )
    except WeightClientError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise WeightClientError(
            "The save could not be confirmed. Select Try again to check the saved weight."
            if writing else UNAVAILABLE,
            code="uncertain" if writing else "unavailable",
            uncertain=writing,
        ) from exc
