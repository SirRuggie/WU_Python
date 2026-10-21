"""Discord REST transport shared by explicit staff announcement workflows."""
import asyncio
import os
import re
import aiohttp

GUILD_ID = "644963518025826315"
CHANNEL_TYPES = (0, 5)
DISCORD_API = "https://discord.com/api/v10"

class AnnouncementUnavailable(Exception):
    pass


class AnnouncementRejected(Exception):
    pass


class AnnouncementUncertain(Exception):
    pass


def _snowflake(value):
    value = str(value or "")
    if not re.fullmatch(r"[0-9]{15,22}", value) or int(value) == 0:
        raise ValueError("Invalid Discord channel ID")
    return value


def _channel(channel):
    if (not isinstance(channel, dict) or str(channel.get("guild_id")) != GUILD_ID
            or channel.get("type") not in CHANNEL_TYPES):
        raise AnnouncementRejected("Channel must be a text or announcement channel in Warriors United")
    try:
        channel_id = _snowflake(channel.get("id"))
    except ValueError as exc:
        raise AnnouncementRejected("Invalid Discord channel response") from exc
    name = channel.get("name")
    if not isinstance(name, str) or not name:
        raise AnnouncementRejected("Invalid Discord channel response")
    return {"id": channel_id, "name": name, "type": channel["type"]}


class DiscordTransport:
    """Minimal bot REST transport. Tests inject a transport through the aiohttp app."""

    def __init__(self, token=None):
        self.token = os.getenv("DISCORD_TOKEN", "").strip() if token is None else token.strip()

    def _headers(self):
        if not self.token:
            raise AnnouncementUnavailable("Discord bot token is not configured")
        return {"Authorization": f"Bot {self.token}", "Accept": "application/json"}

    async def _get(self, path):
        headers = self._headers()
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as client:
                async with client.get(DISCORD_API + path, headers=headers) as response:
                    if response.status != 200:
                        raise AnnouncementUnavailable("Discord channel lookup unavailable")
                    return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise AnnouncementUnavailable("Discord channel lookup unavailable") from exc

    async def list_channels(self):
        data = await self._get(f"/guilds/{GUILD_ID}/channels")
        if not isinstance(data, list):
            raise AnnouncementUnavailable("Invalid Discord channel listing")
        result = []
        for item in data:
            if not isinstance(item, dict) or item.get("type") not in CHANNEL_TYPES:
                continue
            # The guild-scoped endpoint may omit guild_id on individual records.
            result.append(_channel({**item, "guild_id": item.get("guild_id", GUILD_ID)}))
        return sorted(result, key=lambda item: (item["name"].casefold(), item["id"]))

    async def list_roles(self):
        data = await self._get(f"/guilds/{GUILD_ID}/roles")
        if not isinstance(data, list):
            raise AnnouncementUnavailable("Invalid Discord role listing")
        return sorted([
            {"id": str(item["id"]), "name": str(item.get("name", "Role"))}
            for item in data if isinstance(item, dict) and str(item.get("id", "")).isdigit()
        ], key=lambda item: (item["name"].casefold(), item["id"]))

    async def get_channel(self, channel_id):
        data = await self._get(f"/channels/{_snowflake(channel_id)}")
        return _channel(data)

    async def send(self, channel_id, content, nonce):
        headers = self._headers()
        payload = {"content": content, "nonce": nonce, "enforce_nonce": True,
                   "allowed_mentions": {"parse": []}, "tts": False}
        try:
            timeout = aiohttp.ClientTimeout(total=15)
            async with aiohttp.ClientSession(timeout=timeout) as client:
                async with client.post(DISCORD_API + f"/channels/{channel_id}/messages",
                                       headers=headers, json=payload) as response:
                    if response.status in (400, 401, 403, 404, 429):
                        raise AnnouncementRejected("Discord rejected the message or bot permissions")
                    if response.status not in (200, 201):
                        raise AnnouncementUncertain("Discord message result is uncertain")
                    result = await response.json()
        except AnnouncementRejected:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise AnnouncementUncertain("Discord message result is uncertain") from exc
        if (not isinstance(result, dict) or str(result.get("channel_id")) != channel_id
                or not str(result.get("id", "")).isdigit()
                or (result.get("nonce") is not None and str(result["nonce"]) != nonce)):
            raise AnnouncementUncertain("Discord message receipt is invalid")
        return str(result["id"])


