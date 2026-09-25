"""Native Discord uploads for clan and FWA dashboard images.

The dashboard's older image controls accept URLs or point people to slash
commands. These handlers use Discord's native file-upload modal and still
write the same Mongo fields, so every existing reader keeps working.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import hikari
import lightbulb
import requests
from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from utils.constants import BLUE_ACCENT, GREEN_ACCENT, RED_ACCENT, FWA_ACTIVE_WAR_BASE, FWA_WAR_BASE
from utils.discord_file_upload import FileUploadModalComponentBuilder, pop_file_upload
from utils.image_fetch import download_image_blocking
from utils.media_store import (
    FWA_ACTIVE_BASE_NAME,
    FWA_WAR_BASE_NAME,
    MediaStore,
    MediaStoreError,
    clan_folder,
    fwa_base_folder,
)
from utils.media_urls import DETAIL, GALLERY, THUMBNAIL, optimized
from utils.mongo import MongoClient
from utils.url_safety import MAX_IMAGE_BYTES


LOG = logging.getLogger(__name__)
ROLE_ID = 993015846442127420
TTL_SECONDS = 5 * 60
MAX_PENDING = 256
_PENDING: OrderedDict[str, tuple[float, "UploadTarget"]] = OrderedDict()


@dataclass(frozen=True)
class UploadTarget:
    """All authority required to consume one upload modal."""

    kind: str                     # clan or fwa
    slot: str                     # logo/banner or war/active
    key: str                      # clan tag or TH level
    old_value: object
    guild_id: int
    owner_id: int
    source_channel_id: int
    source_message_id: int
    clan_name: str | None = None
    clan_id: object | None = None
    manage_token: str | None = None


def _prune_pending() -> None:
    cutoff = time.monotonic() - TTL_SECONDS
    while _PENDING and (
        len(_PENDING) > MAX_PENDING
        or next(iter(_PENDING.values()))[0] < cutoff
    ):
        _PENDING.popitem(last=False)


def _parse_target(kind: str, action_id: str) -> tuple[str, str] | None:
    slot, separator, key = action_id.partition(":")
    if not separator or not key:
        return None
    if kind == "clan" and slot in {"logo", "banner"} and key.startswith("#"):
        return slot, key
    if kind == "fwa" and slot in {"war", "active"}:
        # Local import keeps this registration-only module out of fwa_data's
        # import graph until its target validation is actually needed.
        from extensions.commands.clan.dashboard.fwa_data import FWA_TH_LEVELS

        if key in FWA_TH_LEVELS:
            return slot, key
    return None


def _role_present(ctx: Any) -> bool:
    interaction = ctx.interaction
    member = getattr(ctx, "member", None) or getattr(interaction, "member", None)
    roles = member.get_roles() if member and hasattr(member, "get_roles") else ()
    return ROLE_ID in {int(role.id) for role in roles}


def _identity(ctx: Any) -> tuple[int, int, int, int] | None:
    interaction = ctx.interaction
    user = getattr(interaction, "user", None) or getattr(ctx, "user", None)
    message = getattr(interaction, "message", None)
    try:
        return int(interaction.guild_id), int(user.id), int(interaction.channel_id), int(message.id)
    except (AttributeError, TypeError, ValueError):
        return None


def _navigation(target: UploadTarget) -> ActionRow:
    upload_id = (
        f"clan_image_upload:{target.slot}:{target.key}"
        if target.kind == "clan"
        else f"fwa_image_upload:{target.slot}:{target.key}"
    )
    back_id = f"back_to_clan_edit:{target.key}" if target.kind == "clan" else f"fwa_update_images:{target.key}"
    buttons = [
        Button(style=hikari.ButtonStyle.PRIMARY, label="Upload another", custom_id=upload_id),
        Button(style=hikari.ButtonStyle.SECONDARY, label="Back to editor", custom_id=back_id),
    ]
    if target.kind == "fwa" and target.manage_token:
        buttons.append(Button(
            style=hikari.ButtonStyle.SECONDARY, label="Management Home",
            custom_id=f"manage_home:{target.manage_token}",
        ))
    return ActionRow(components=buttons)


def _problem_panel(message: str, target: UploadTarget | None = None) -> list[Container]:
    components: list[Any] = [Text(content=f"## ❌ Upload needs attention\n{message}")]
    if target is not None:
        components.extend([Separator(divider=True), _navigation(target)])
    return [Container(accent_color=RED_ACCENT, components=components)]


def _success_panel(target: UploadTarget, url: str) -> list[Container]:
    subject = (
        f"{target.slot.title()} for `{target.key}`"
        if target.kind == "clan"
        else f"TH{target.key.removeprefix('th').replace('_new', ' New')} {target.slot.title()} base"
    )
    width = DETAIL if target.kind == "fwa" else (THUMBNAIL if target.slot == "logo" else GALLERY)
    return [Container(
        accent_color=GREEN_ACCENT,
        components=[
            Text(content=f"## ✅ {subject} saved"),
            Text(content="The replacement was saved immediately."),
            Media(items=[MediaItem(media=optimized(url, width=width))]),
            Separator(divider=True),
            _navigation(target),
        ],
    )]


async def _ack_modal(ctx: Any) -> None:
    """Acknowledge before a database, download, or object-store operation."""
    sent = getattr(ctx, "_initial_response_sent", None)
    if getattr(ctx, "_dashboard_upload_acked", False) or (sent is not None and getattr(sent, "is_set", lambda: False)()):
        return
    interaction = ctx.interaction
    if getattr(interaction, "message", None) is not None:
        await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)
    if sent is not None and hasattr(sent, "set"):
        sent.set()
    try:
        ctx._dashboard_upload_acked = True
    except (AttributeError, TypeError):
        pass


async def _edit(interaction: Any, components: list[Container]) -> None:
    await interaction.edit_initial_response(
        components=components, user_mentions=False, role_mentions=False, mentions_everyone=False
    )


def _attachment_url(attachment: dict[str, Any]) -> str | None:
    try:
        if not 0 < int(attachment["size"]) <= MAX_IMAGE_BYTES:
            return None
        parsed = urlparse(str(attachment["url"]))
        port = parsed.port
    except (KeyError, TypeError, ValueError):
        return None
    if (
        parsed.scheme != "https"
        or parsed.hostname not in {"cdn.discordapp.com", "media.discordapp.net"}
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not parsed.path.startswith(("/attachments/", "/ephemeral-attachments/"))
    ):
        return None
    return str(attachment["url"])


async def _open(ctx: Any, action_id: str, mongo: MongoClient, kind: str) -> None:
    parsed = _parse_target(kind, action_id)
    identity = _identity(ctx)
    label = "Clan Management" if kind == "clan" else "FWA Representative"
    if not _role_present(ctx):
        await ctx.respond(f"❌ {label} role required.", ephemeral=True)
        return
    if parsed is None or identity is None:
        await ctx.respond("❌ This image editor is out of date. Return to the dashboard and try again.", ephemeral=True)
        return
    slot, key = parsed
    guild_id, owner_id, source_channel_id, source_message_id = identity
    if kind == "clan":
        current = await mongo.clans.find_one({"tag": key})
        if current is None:
            await ctx.respond("❌ That clan no longer exists. No upload was opened.", ephemeral=True)
            return
        old_value = current.get(slot)
        clan_name = str(current.get("name") or key.lstrip("#"))
        clan_id = current.get("_id")
    else:
        # get_fwa_data creates the one configuration document when absent. This
        # keeps the subsequent compare-and-set update safe from an upsert race.
        from extensions.commands.clan.dashboard.fwa_data import get_fwa_data

        current = await get_fwa_data(mongo)
        old_value = current.get(f"{slot}_base_images", {}).get(key)
        clan_name = None
        clan_id = None
    manage_token = None
    if kind == "fwa":
        # Managed FWA panels carry their Home control on the source message.
        # Legacy clan uploads deliberately have no management provenance.
        from extensions.commands.clan.dashboard.fwa_data import _management_token
        manage_token = _management_token(ctx)
    token = secrets.token_urlsafe(18)
    _prune_pending()
    _PENDING[token] = (time.monotonic(), UploadTarget(
        kind=kind, slot=slot, key=key, old_value=old_value,
        guild_id=guild_id, owner_id=owner_id,
        source_channel_id=source_channel_id, source_message_id=source_message_id,
        clan_name=clan_name, clan_id=clan_id, manage_token=manage_token,
    ))
    _prune_pending()
    title = f"Upload {slot.title()} image"
    await ctx.respond_with_modal(
        title=title,
        custom_id=f"dashboard_image_submit:{token}",
        components=[FileUploadModalComponentBuilder(
            custom_id="image", label=title,
            description="PNG, JPG, GIF, or WEBP; maximum 10 MB. This saves the replacement immediately.",
        )],
    )


@register_action("clan_image_upload", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def clan_image_upload(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _open(ctx, action_id, mongo, "clan")


@register_action("fwa_image_upload", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def fwa_image_upload(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _open(ctx, action_id, mongo, "fwa")


def _consume(token: str) -> UploadTarget | None:
    _prune_pending()
    row = _PENDING.pop(token, None)
    if row is None or row[0] < time.monotonic() - TTL_SECONDS:
        return None
    return row[1]


async def _persist(target: UploadTarget, mongo: MongoClient, url: str) -> bool:
    if target.kind == "clan":
        result = await mongo.clans.update_one(
            {"_id": target.clan_id, "tag": target.key, target.slot: target.old_value},
            {"$set": {target.slot: url}},
        )
    else:
        field = f"{target.slot}_base_images.{target.key}"
        result = await mongo.fwa_data.update_one(
            {"_id": "fwa_config", field: target.old_value},
            {"$set": {field: url}},
        )
    return bool(getattr(result, "matched_count", 0))


def _update_memory(target: UploadTarget, url: str) -> None:
    if target.kind != "fwa":
        return
    target_map = FWA_WAR_BASE if target.slot == "war" else FWA_ACTIVE_WAR_BASE
    target_map[target.key] = optimized(url, width=DETAIL)


@register_action("dashboard_image_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def dashboard_image_submit(
    ctx: Any,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    media: MediaStore = lightbulb.di.INJECTED,
    **_: Any,
) -> None:
    """Consume a one-shot dashboard upload and save its selected field."""
    interaction = ctx.interaction
    # Consume before acknowledgement so malformed/replayed raw submissions cannot
    # be retained, then acknowledge before any I/O.
    attachment = pop_file_upload(interaction.id, interaction.custom_id, "image")
    target = _consume(action_id)
    await _ack_modal(ctx)
    if target is None:
        await _edit(interaction, _problem_panel("This upload expired or was already used. Run /manage and open a new upload from the FWA workspace."))
        return
    try:
        guild_id = int(interaction.guild_id)
        user_id = int(interaction.user.id)
        channel_id = int(interaction.channel_id)
    except (AttributeError, TypeError, ValueError):
        guild_id = user_id = channel_id = 0
    message = getattr(interaction, "message", None)
    try:
        source_matches = message is not None and int(message.id) == target.source_message_id
    except (AttributeError, TypeError, ValueError):
        source_matches = False
    if (guild_id, user_id, channel_id) != (target.guild_id, target.owner_id, target.source_channel_id) or not source_matches:
        await _edit(interaction, _problem_panel("This upload belongs to another dashboard editor."))
        return
    label = "Clan Management" if target.kind == "clan" else "FWA Representative"
    if not _role_present(ctx):
        await _edit(interaction, _problem_panel(f"{label} role required."))
        return
    if _parse_target(target.kind, f"{target.slot}:{target.key}") is None:
        await _edit(interaction, _problem_panel("That image target is no longer supported."))
        return
    if not isinstance(attachment, dict):
        await _edit(interaction, _problem_panel("Attach exactly one image. Nothing was changed.", target))
        return
    url = _attachment_url(attachment)
    if url is None:
        await _edit(interaction, _problem_panel("Discord did not return a valid image under 10 MB. Nothing was changed.", target))
        return
    # Recheck that a clan target still exists before allocating an R2 object.
    # A Mongo outage here is distinct from a failed image download and must not
    # claim that a later save was attempted.
    current_clan = None
    try:
        if target.kind == "clan":
            current_clan = await mongo.clans.find_one({"tag": target.key})
    except Exception:
        LOG.exception("dashboard image target lookup failed kind=%s key=%s", target.kind, target.key)
        await _edit(interaction, _problem_panel("I could not verify that target. Nothing was changed; try again shortly.", target))
        return
    if target.kind == "clan" and current_clan is None:
        await _edit(interaction, _problem_panel("That clan no longer exists. Nothing was changed.", target))
        return
    try:
        data = await asyncio.to_thread(download_image_blocking, url)
        folder = (
            clan_folder(str(current_clan.get("name") or target.clan_name or target.key.lstrip("#")))
            if target.kind == "clan" else fwa_base_folder(target.key)
        )
        name = target.slot if target.kind == "clan" else (FWA_WAR_BASE_NAME if target.slot == "war" else FWA_ACTIVE_BASE_NAME)
        uploaded_url = await media.upload_bytes(data, folder=folder, name=name)
    except (requests.RequestException, asyncio.TimeoutError, ValueError, OSError, MediaStoreError):
        await _edit(interaction, _problem_panel("I could not validate and store that image. Nothing was changed; try again shortly.", target))
        return
    try:
        saved = await _persist(target, mongo, uploaded_url)
    except Exception:
        LOG.exception("dashboard image Mongo write failed kind=%s slot=%s key=%s", target.kind, target.slot, target.key)
        await _edit(interaction, _problem_panel("The image uploaded, but I could not confirm its dashboard save. Reopen the editor to check before retrying.", target))
        return
    if not saved:
        await _edit(interaction, _problem_panel("This image changed while the upload was open. Nothing was saved; reopen the editor and try again.", target))
        return
    _update_memory(target, uploaded_url)
    await _edit(interaction, _success_panel(target, uploaded_url))
