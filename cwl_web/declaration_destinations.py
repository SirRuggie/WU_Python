"""Live destination ownership/permissions for the manual declaration controls."""

import asyncio
from aiohttp import web
from hikari import Permissions
from utils.member_events import effective_permissions
from utils.declaration_ping_store import identity
from .server_management import discord, GUILD_ID


async def authorized(request, actor_id):
    """Current policy and role membership for a confirmed asynchronous job."""
    from utils.dashboard_access import OWNER_IDS, effective, expand_legacy
    from .access_settings import repository
    from .server_management import mongo

    if actor_id in OWNER_IDS:
        return True
    member = await discord(request, "GET", f"/guilds/{GUILD_ID}/members/{actor_id}")
    async with mongo(request) as client:
        document = await repository(client).read()
        if document is not None:
            return "cwl_send" in effective(document, actor_id, member.get("roles", []))
        grant = (
            await client.bot_config.find_one({"_id": "dashboard-access:" + actor_id})
            or {}
        )
        return "cwl_send" in expand_legacy(grant.get("permissions", []))


async def bot_actor(request):
    me, roles = await asyncio.gather(
        discord(request, "GET", "/users/@me"),
        discord(request, "GET", f"/guilds/{GUILD_ID}/roles"),
    )
    member = await discord(request, "GET", f"/guilds/{GUILD_ID}/members/{me['id']}")
    ids = {str(role) for role in member.get("roles", [])}
    base = 0
    for role in roles:
        if str(role.get("id")) in ids | {str(GUILD_ID)}:
            base |= int(role.get("permissions", 0))
    return dict(user_id=str(me["id"]), role_ids=ids, permissions=base)


def issue(channel, actor):
    if str(channel.get("guild_id")) != str(GUILD_ID) or channel.get("type") not in (
        0,
        5,
    ):
        return "Choose a text or announcement channel in this server"
    rights = effective_permissions(
        actor["permissions"],
        actor["role_ids"],
        actor["user_id"],
        channel.get("permission_overwrites", []),
        GUILD_ID,
    )
    needed = Permissions.VIEW_CHANNEL | Permissions.SEND_MESSAGES
    if not rights & Permissions.ADMINISTRATOR and rights & needed != needed:
        return "The bot needs View Channel and Send Messages here"
    return None


async def destination(request, channel_id):
    channel_id = identity(channel_id)
    channel, actor = await asyncio.gather(
        discord(request, "GET", f"/channels/{channel_id}"), bot_actor(request)
    )
    if str(channel.get("id")) != channel_id:
        raise web.HTTPBadRequest(text="The Discord channel identity changed")
    reason = issue(channel, actor)
    if reason:
        raise web.HTTPBadRequest(text=reason)
    return dict(
        id=channel_id,
        name=str(channel.get("name") or channel_id)[:100],
        type=channel["type"],
    )


async def channels(request):
    rows, actor = await asyncio.gather(
        discord(request, "GET", f"/guilds/{GUILD_ID}/channels"), bot_actor(request)
    )
    if not isinstance(rows, list):
        raise web.HTTPServiceUnavailable(text="Discord channels are unavailable")
    result = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type") not in (0, 5):
            continue
        row = {**row, "guild_id": row.get("guild_id", GUILD_ID)}
        if str(row.get("guild_id")) != str(GUILD_ID):
            continue
        try:
            channel_id = identity(row.get("id"))
        except ValueError:
            continue
        reason = issue(row, actor)
        result.append(
            dict(
                id=channel_id,
                name=str(row.get("name") or channel_id)[:100],
                type=row["type"],
                can_send=not reason,
                reason=reason,
            )
        )
    return sorted(result, key=lambda row: (row["name"].casefold(), row["id"]))
