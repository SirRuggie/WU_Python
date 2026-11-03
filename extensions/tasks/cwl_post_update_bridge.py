"""Authenticated read-only season/binding revalidation for native post edits."""

import aiohttp
from utils.cwl_member_client import bridge_config


async def validate_scope(row):
    url, secret = bridge_config()
    url = url.rsplit("/", 1)[0] + "/post-updates/validate"
    body = {
        key: row[key]
        for key in ("guild_id", "user_id", "season_id", "cycle", "pool", "worker_epoch")
    }
    body["workflow_id"] = row["_id"]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as client:
        async with client.post(
            url,
            json=body,
            headers={"X-CWL-Discord-Secret": secret},
            allow_redirects=False,
        ) as response:
            if response.status != 200:
                raise RuntimeError("Post-update scope validation is unavailable")
            data = await response.json()
            if not isinstance(data, dict) or type(data.get("valid")) is not bool:
                raise RuntimeError("Post-update scope validation is unavailable")
            return data["valid"]
