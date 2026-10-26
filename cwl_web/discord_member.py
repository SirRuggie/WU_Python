"""Loopback Discord member adapter for the single dashboard-owned CWL writer."""

import ipaddress
import os
import re
import secrets

import aiohttp
from aiohttp import web

from utils import cwl_member_service as member


GUILD_ID = "644963518025826315"
USER_ID = re.compile(r"[0-9]{1,20}\Z")
SECRET_HEADER = "X-CWL-Discord-Secret"


async def _guild_member(request, user_id):
    """Recheck server membership with Discord for every action, including reads."""
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise member.MemberError(503, "Discord membership check is unavailable")
    url = f"https://discord.com/api/v10/guilds/{GUILD_ID}/members/{user_id}"
    timeout = aiohttp.ClientTimeout(total=8)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(url, headers={"Authorization": f"Bot {token}"}) as response:
                if response.status == 200:
                    data = await response.json()
                    if str(data.get("user", {}).get("id")) != user_id:
                        raise member.MemberError(503, "Discord membership check is unavailable")
                    return
                if response.status == 404:
                    raise member.MemberError(403, "Warriors United membership required")
                raise member.MemberError(503, "Discord membership check is unavailable")
    except member.MemberError:
        raise
    except (aiohttp.ClientError, TimeoutError, ValueError) as exc:
        raise member.MemberError(503, "Discord membership check is unavailable") from exc


def _authenticate(request):
    peer = request.transport.get_extra_info("peername") if request.transport else None
    try:
        host = ipaddress.ip_address(peer[0]) if peer else None
    except (ValueError, TypeError, IndexError):
        host = None
    if host is None or not host.is_loopback:
        raise member.MemberError(403, "Local Discord bridge only")
    secret = os.getenv("CWL_DISCORD_BRIDGE_SECRET", "")
    if len(secret) < 32:
        raise member.MemberError(503, "Discord CWL bridge is not configured")
    supplied = request.headers.get(SECRET_HEADER, "")
    if not secrets.compare_digest(secret, supplied):
        raise member.MemberError(403, "Discord CWL bridge authentication failed")


def _season_id(body):
    value = body.get("season_id")
    if type(value) is not int or not 0 < value < 2**63:
        raise member.MemberError(400, "Invalid season")
    return value


async def dispatch(request):
    try:
        _authenticate(request)
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise member.MemberError(400, "Invalid JSON") from None
        if not isinstance(body, dict):
            raise member.MemberError(400, "Expected JSON object")
        user_id = body.get("user_id")
        if not isinstance(user_id, str) or not USER_ID.fullmatch(user_id) or body.get("guild_id") != GUILD_ID:
            raise member.MemberError(403, "Warriors United membership required")
        check = request.app.get("discord_member_check") or _guild_member
        await check(request, user_id)
        action = body.get("action")
        store, provider = request.app["store"], request.app["providers"]
        if action == "view":
            include_accounts = body.get("include_accounts", True)
            if type(include_accounts) is not bool:
                raise member.MemberError(400, "Invalid account lookup option")
            result = await member.member_snapshot(
                store, provider, user_id, include_accounts=include_accounts
            )
            if "season_id" in body and (result["season"] is None or
                                        result["season"]["id"] != _season_id(body)):
                raise member.MemberError(409, "The member season changed. Reopen CWL.")
        elif action == "submit":
            if not isinstance(body.get("accounts"), list) or not body["accounts"]:
                raise member.MemberError(400, "Choose at least one account")
            if type(body.get("expected_revision")) is not int:
                raise member.MemberError(400, "Missing signup revision")
            result = await member.submit(
                store, provider, _season_id(body), user_id, body.get("pool"),
                body.get("accounts"), expected_revision=body["expected_revision"],
                verified_only=False,
            )
        elif action == "withdraw":
            if type(body.get("expected_revision")) is not int or body.get("expected_pool") not in ("main", "lazy"):
                raise member.MemberError(400, "Missing signup revision or source pool")
            result = member.withdraw(
                store, _season_id(body), user_id, body.get("tag"),
                expected_pool=body["expected_pool"],
                expected_revision=body["expected_revision"],
            )
        else:
            raise member.MemberError(400, "Invalid CWL action")
        return web.json_response(result)
    except member.MemberError as exc:
        return web.json_response({"error": str(exc)}, status=exc.status)


routes = [web.post("/api/cwl/discord/member", dispatch)]
