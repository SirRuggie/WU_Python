"""Loopback bridge for saving a ``/fwa weight`` result to the official Clan weights.

The dashboard process is the single durable writer of the Clan weights ledger, so
the bot saves through this bridge instead of writing the SQLite file itself.
Every action rechecks the staff member's "Save weights from Discord" permission.
"""

import asyncio
import re

from aiohttp import web

from utils.clan_weight_store import WeightConflict, validate_weight
from utils.dashboard_access import OWNER_IDS, PERMISSIONS, effective, expand_legacy

from .providers import ProviderUnavailable, tag

GUILD_ID = "644963518025826315"
PERMISSION = "discord_weights"
STORAGES = 5
MAX_ACCOUNTS = 24  # A select menu holds 25 options; one is "Other account".
USER_ID = re.compile(r"[0-9]{1,20}\Z")


class BridgeError(Exception):
    def __init__(self, status, message, code="error"):
        super().__init__(message)
        self.status = status
        self.code = code


def _user_id(value):
    if not isinstance(value, str) or not USER_ID.fullmatch(value):
        raise BridgeError(400, "Invalid Discord user")
    return value


def _legacy_permissions(request, user_id):
    from .access_control import scopes

    return expand_legacy(scopes(request.app["store"], user_id))


async def actor_permissions(request, user_id):
    """Dashboard Access grants for a Discord user, from a fresh role lookup."""
    injected = request.app.get("discord_weight_permissions")
    if injected is not None:
        return set(await injected(user_id))
    if user_id in OWNER_IDS:
        return set(PERMISSIONS)
    if request.app.get("dev_fixture") or not request.app.get("live_access"):
        return _legacy_permissions(request, user_id)
    from .access_settings import repository
    from .server_management import GUILD_ID as GUILD, discord, mongo

    unavailable = BridgeError(503, "Access could not be checked. Try again shortly.", "unavailable")
    try:
        async with mongo(request) as db:
            document = await repository(db).read()
    except web.HTTPException:
        raise unavailable from None
    if document is None:
        return _legacy_permissions(request, user_id)
    roles, role_error = [], False
    if any(grant["kind"] == "role" for grant in document.get("grants", [])):
        try:
            member = await discord(request, "GET", f"/guilds/{GUILD}/members/{user_id}")
            roles = member.get("roles", []) if isinstance(member, dict) else []
        except web.HTTPNotFound:
            roles = []
        except web.HTTPException:
            role_error = True  # Never authorize from stale roles; direct grants still work.
    permissions = effective(document, user_id, roles)
    if role_error and PERMISSION not in permissions:
        raise unavailable
    return permissions


async def _require_permission(request, actor_id):
    if PERMISSION not in await actor_permissions(request, actor_id):
        raise BridgeError(403, "You need weight saving access.", "forbidden")


def _account(player_tag, player, saved):
    saved = saved or {}
    player = player or {}
    return {
        "tag": player_tag,
        "name": player.get("name"),
        "town_hall": player.get("town_hall"),
        "clan_tag": player.get("current_clan_tag"),
        "clan_name": player.get("current_clan_name"),
        "available": bool(player),
        "weight": saved.get("weight"),
        "revision": saved.get("revision", 0),
    }


async def _player(request, player_tag):
    try:
        return await request.app["providers"].player(player_tag)
    except ProviderUnavailable as exc:
        if getattr(exc, "status_code", None) == 404:
            raise BridgeError(404, "No player was found with that tag.", "not_found") from None
        raise BridgeError(503, "Clash API is unavailable. Try again shortly.", "unavailable") from None


async def _accounts(request, body):
    target = _user_id(body.get("target_id"))
    try:
        links = await request.app["providers"].linked_tags(target)
    except ProviderUnavailable:
        raise BridgeError(503, "Could not load linked accounts.", "links_unavailable") from None
    tags = sorted(links)
    shown = tags[:MAX_ACCOUNTS]
    players = await asyncio.gather(
        *(request.app["providers"].player(value) for value in shown), return_exceptions=True
    )
    saved = request.app["clan_weight_trial"].for_members(shown)
    accounts = [
        _account(value, None if isinstance(player, BaseException) else player, saved.get(value))
        for value, player in zip(shown, players)
    ]
    accounts.sort(key=lambda row: (-(row["town_hall"] or 0), (row["name"] or "").casefold(), row["tag"]))
    return {"accounts": accounts, "hidden": len(tags) - len(shown)}


async def _lookup(request, body):
    try:
        player_tag = tag(body.get("tag"))
    except ValueError:
        raise BridgeError(400, "Enter a valid player tag, for example #2PP.", "invalid_tag") from None
    player = await _player(request, player_tag)
    saved = request.app["clan_weight_trial"].for_members([player_tag]).get(player_tag)
    return {"account": _account(player_tag, player, saved)}


async def _save(request, body, actor_id):
    try:
        player_tag = tag(body.get("tag"))
    except ValueError:
        raise BridgeError(400, "Enter a valid player tag, for example #2PP.", "invalid_tag") from None
    weight, revision = body.get("weight"), body.get("revision")
    if type(revision) is not int or revision < 0:
        raise BridgeError(400, "Missing weight revision. Try again.")
    try:
        validate_weight(weight, STORAGES)
    except ValueError as exc:
        raise BridgeError(400, str(exc), "invalid_weight") from None
    if weight is None:
        raise BridgeError(400, "Enter a weight to save.", "invalid_weight")
    actor_name = body.get("actor_name")
    if not isinstance(actor_name, str) or not actor_name.strip():
        actor_name = None
    else:
        actor_name = actor_name.strip()[:100]
    player = await _player(request, player_tag)
    try:
        row, changed = request.app["clan_weight_trial"].save_discord(
            player_tag,
            {"weight": weight, "revision": revision, "storages": STORAGES},
            player,
            actor_id,
            actor_name,
        )
    except WeightConflict:
        raise BridgeError(409, "Changed by someone else. Try again.", "conflict") from None
    except ValueError as exc:
        raise BridgeError(400, str(exc), "invalid_weight") from None
    return {"account": _account(player_tag, player, row), "changed": changed}


async def dispatch(request):
    from .discord_member import _authenticate
    from utils.cwl_member_service import MemberError

    try:
        try:
            _authenticate(request)
        except MemberError as exc:
            raise BridgeError(exc.status, str(exc), "bridge") from None
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise BridgeError(400, "Invalid JSON") from None
        if not isinstance(body, dict) or body.get("guild_id") != GUILD_ID:
            raise BridgeError(403, "Warriors United only")
        actor_id = _user_id(body.get("actor_id"))
        await _require_permission(request, actor_id)
        action = body.get("action")
        if action == "access":
            result = {"allowed": True}
        elif action == "accounts":
            result = await _accounts(request, body)
        elif action == "lookup":
            result = await _lookup(request, body)
        elif action == "save":
            result = await _save(request, body, actor_id)
        else:
            raise BridgeError(400, "Invalid weight action")
        return web.json_response(result)
    except BridgeError as exc:
        return web.json_response({"error": str(exc), "code": exc.code}, status=exc.status)


routes = [web.post("/api/cwl/discord/weight", dispatch)]
