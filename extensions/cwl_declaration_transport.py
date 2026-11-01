"""One explicit Components V2 send; no retries, scheduling or bot lifecycle."""

import asyncio
import copy
import os
import re
import aiohttp


class PingRejected(RuntimeError):
    pass


class PingUncertain(RuntimeError):
    pass


class DeclarationPingTransport:
    def __init__(self, token=None):
        self.token = (
            token if token is not None else os.getenv("DISCORD_TOKEN", "").strip()
        )

    async def send(self, channel_id, payload, nonce, *, test=False):
        allowed = payload.get("allowed_mentions") or {}
        users = allowed.get("users")
        if (
            allowed.get("parse") != []
            or allowed.get("roles") != []
            or not isinstance(users, list)
            or len(users) > 100
            or len(set(users)) != len(users)
            or any(
                not isinstance(uid, str) or not re.fullmatch(r"[1-9][0-9]{14,21}", uid)
                for uid in users
            )
            or (test and users)
        ):
            raise ValueError(
                "Declaration pings allow only reviewed users; tests allow nobody"
            )
        if not self.token:
            raise PingRejected("Discord connection is not configured")
        body = {**copy.deepcopy(payload), "nonce": nonce, "enforce_nonce": True}
        try:
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)
            ) as session:
                async with session.post(
                    f"https://discord.com/api/v10/channels/{channel_id}/messages",
                    json=body,
                    headers={"Authorization": "Bot " + self.token},
                ) as response:
                    if response.status in (400, 401, 403, 404, 429):
                        raise PingRejected(
                            f"Discord refused chunk ({response.status}); no retry was attempted"
                        )
                    if response.status not in (200, 201):
                        raise PingUncertain(
                            "Discord did not confirm whether this chunk posted"
                        )
                    data = await response.json()
        except PingRejected:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as error:
            raise PingUncertain(
                "Discord delivery could not be confirmed; inspect the channel"
            ) from error
        if (
            not isinstance(data, dict)
            or str(data.get("channel_id")) != channel_id
            or not re.fullmatch(r"[1-9][0-9]{14,21}", str(data.get("id", "")))
            or (data.get("nonce") is not None and str(data["nonce"]) != nonce)
        ):
            raise PingUncertain(
                "Discord returned an incomplete chunk receipt; inspect the channel"
            )
        return str(data["id"])
