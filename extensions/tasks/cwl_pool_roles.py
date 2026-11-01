"""Bot-owned CWL role transport, serialized with the management lane."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from types import SimpleNamespace as NS

import aiohttp
import hikari
import lightbulb

from utils.cwl_member_client import bridge_config
from utils.cwl_pool_roles import GUILD_ID
from utils.role_permissions import role_is_safe_for_pool
from utils.manage_web_worker import queue_lock

loader = lightbulb.Loader()
log = logging.getLogger(__name__)
driver = None


class RolePermissionMissing(Exception):
    pass


class BridgeUnavailable(Exception):
    pass


async def bridge(action, **payload):
    url, secret = bridge_config()
    url = url.rsplit("/", 1)[0] + "/pool-roles"
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=15)
        ) as client:
            async with client.post(
                url,
                json={"action": action, "guild_id": str(GUILD_ID), **payload},
                headers={"X-CWL-Discord-Secret": secret},
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    raise BridgeUnavailable("CWL role bridge unavailable")
                return await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise BridgeUnavailable("CWL role bridge unavailable") from exc


async def safe_role(bot, role_id):
    roles = {int(r.id): r for r in await bot.rest.fetch_roles(GUILD_ID)}
    me = bot.get_me()
    if me is None:
        raise BridgeUnavailable("Bot is starting")
    own = await bot.rest.fetch_member(GUILD_ID, me.id)
    guild = NS(
        id=GUILD_ID,
        owner_id=0,
        get_role=roles.get,
        get_member=lambda uid: own if int(uid) == int(me.id) else None,
    )
    role = roles.get(int(role_id))
    if role is None or role.permissions & hikari.Permissions.ADMINISTRATOR:
        raise ValueError("Role unavailable or unsafe.")
    if not role_is_safe_for_pool(guild, bot, role):
        raise RolePermissionMissing("Bot role permission missing.")
    return role


async def process_job(bot, job, *, send=bridge):
    receipt = {key: job[key] for key in ("id", "lease_token", "generation")}

    async def finish(**values):
        return await send("finish", **receipt, **values)

    try:
        budget = min(120, job["lease_until"] - time.time() - 15)
        if budget <= 0:
            return
        async with asyncio.timeout(budget):
            if job["kind"] not in {"sync", "scan", "remove"}:
                raise ValueError("Invalid role work.")
            current = await send("validate", **receipt)
            if current.get("valid") is not True:
                return
            await safe_role(bot, job["role_id"])
            if job["kind"] == "scan":
                page = [
                    m
                    async for m in bot.rest.fetch_members(
                        GUILD_ID, start_at=int(job["cursor"])
                    ).limit(1000)
                ]
                cursor = str(max((int(m.id) for m in page), default=int(job["cursor"])))
                holding = [str(m.id) for m in page if int(job["role_id"]) in m.role_ids]
                current = await send("validate", **receipt)
                if current["valid"]:
                    await finish(page=holding, cursor=cursor)
                return
            member = await bot.rest.fetch_member(GUILD_ID, int(job["user_id"]))
            current = await send("validate", **receipt)
            if not current["valid"]:
                return
            desired = current["desired"]
            if type(desired) is not bool:
                raise BridgeUnavailable("Role intent unavailable")
            held = int(job["role_id"]) in member.role_ids
            if held == desired:
                await finish(message="Already up to date.")
                return
            method = (
                bot.rest.add_role_to_member
                if desired
                else bot.rest.remove_role_from_member
            )
            await method(
                GUILD_ID,
                member.id,
                int(job["role_id"]),
                reason="CWL " + job["pool"] + " role",
            )
            log.info(
                "CWL pool role changed pool=%s member=%s role=%s added=%s",
                job["pool"],
                member.id,
                job["role_id"],
                desired,
            )
            await finish(message="Role added." if desired else "Role removed.")
    except asyncio.CancelledError:
        # Lease recovery reads actual roles before deciding whether another write is needed.
        raise
    except (hikari.ForbiddenError, RolePermissionMissing):
        await finish(retry=True, message="Bot permission missing. Will check again.")
    except (hikari.NotFoundError, ValueError):
        await finish(
            failed=True,
            message="Member or role unavailable, or bot permission missing.",
        )
    except BridgeUnavailable:
        # A receipt may already be durable. Never replay it or a role write here.
        return
    except Exception:
        await finish(retry=True, message="Discord unavailable. Will check again.")


async def poll_once(bot, *, send=bridge):
    lock = queue_lock()
    if lock.locked():
        return
    # An off/unavailable bridge never occupies the Discord mutation lane.
    result = await send("claim")
    job = result.get("job")
    if not job:
        return
    wait = min(60, job["lease_until"] - time.time() - 135)
    if wait <= 0:
        return
    try:
        async with asyncio.timeout(wait):
            await lock.acquire()
    except TimeoutError:
        return
    try:
        await process_job(bot, job, send=send)
    finally:
        lock.release()


async def run(bot):
    while True:
        try:
            await poll_once(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Blank/unconfigured bridge must add no warning or Discord call.
            log.debug("CWL role bridge not ready")
        await asyncio.sleep(1)


@loader.listener(hikari.StartedEvent)
async def started(event):
    global driver
    if driver is None or driver.done():
        driver = asyncio.create_task(run(event.app), name="cwl-pool-roles")


@loader.listener(hikari.StoppingEvent)
async def stopping(event):
    del event
    global driver
    if driver:
        driver.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await driver
        driver = None
