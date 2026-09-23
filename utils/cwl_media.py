"""Native Discord image-upload modals with the pinned Hikari 2.6 runtime.

Hikari can serialize custom component builders but drops Label/File Upload
components and resolved attachments when reading modal submissions. A narrowly
scoped raw gateway listener retains just the CWL upload data until the normal
authenticated modal handler consumes it. No SDK monkeypatch or tokens stored.
Remove this bridge when the pinned SDK supports these modal components natively.
"""
from __future__ import annotations

import asyncio
import copy
import re
import time
from collections import OrderedDict
from urllib.parse import urlparse

import hikari
import requests

from utils.image_fetch import download_image_blocking
from utils.media_store import MediaStore, MediaStoreError
from utils.url_safety import MAX_IMAGE_BYTES

PREFIX = "cwl_image_submit:"
INPUT_ID = "cwl_image"
MAX_PENDING = 128
TTL_SECONDS = 300
_pending: OrderedDict[int, tuple[float, dict]] = OrderedDict()


class ImageUploadLabel(hikari.api.ComponentBuilder):
    @property
    def type(self):
        return 18

    @property
    def id(self):
        return hikari.UNDEFINED

    def build(self):
        return {
            "type": 18,
            "label": "Announcement image",
            "description": "PNG, JPG, GIF or WEBP. Maximum 10 MB. Saved to your draft.",
            "component": {
                "type": 19, "custom_id": INPUT_ID,
                "min_values": 1, "max_values": 1, "required": True,
                "file_types": [".png", ".jpg", ".jpeg", ".gif", ".webp"],
            },
        }, []


def upload_modal_components():
    return [ImageUploadLabel()]


def _prune():
    cutoff = time.monotonic() - TTL_SECONDS
    for key, (created, _) in list(_pending.items()):
        if created < cutoff:
            _pending.pop(key, None)
    while len(_pending) > MAX_PENDING:
        _pending.popitem(last=False)


async def capture_upload_payload(event: hikari.ShardPayloadEvent):
    """Register on the dashboard loader; ignore all other gateway traffic."""
    if event.name != "INTERACTION_CREATE":
        return
    payload = event.payload
    data = payload.get("data", {})
    if payload.get("type") != 5 or not str(data.get("custom_id", "")).startswith(PREFIX):
        return
    # Only retain fields needed to consume this one attachment. In particular,
    # never retain the interaction token or the raw user/member/message objects.
    values = []
    for label in data.get("components", []):
        component = label.get("component", {})
        if label.get("type") == 18 and component.get("type") == 19 and component.get("custom_id") == INPUT_ID:
            values.extend(component.get("values", []))
    attachments = data.get("resolved", {}).get("attachments", {})
    selected = attachments.get(str(values[0])) if len(values) == 1 else None
    user = payload.get("member", {}).get("user", payload.get("user", {}))
    try:
        record = {
            "custom_id": data["custom_id"], "guild_id": int(payload.get("guild_id", 0)),
            "user_id": int(user.get("id", 0)), "attachment": copy.deepcopy(selected),
        }
        _pending[int(payload["id"])] = (time.monotonic(), record)
    except (KeyError, TypeError, ValueError):
        return
    _prune()


async def upload_from_modal(interaction, media: MediaStore, *, guild_id: int, message_id: str, audience: str) -> str:
    """Called only after the dashboard validates the draft owner and permission."""
    _prune()
    # Raw and typed gateway events are dispatched independently. Yield once to
    # allow the raw listener to finish even if the typed event arrives first.
    if int(interaction.id) not in _pending:
        await asyncio.sleep(0)
    entry = _pending.pop(int(interaction.id), None)
    if entry is None:
        raise MediaStoreError("That upload expired. Click Upload replacement and upload it again.")
    record = entry[1]
    if (record["custom_id"] != interaction.custom_id
        or record["guild_id"] != int(guild_id)
        or int(interaction.guild_id or 0) != int(guild_id)
        or record["user_id"] != int(interaction.user.id)):
        raise MediaStoreError("This image upload belongs to another editor.")
    attachment = record["attachment"]
    if not isinstance(attachment, dict):
        raise MediaStoreError("Please attach exactly one image.")
    if not isinstance(attachment.get("size"), int) or not 0 < attachment["size"] <= MAX_IMAGE_BYTES:
        raise MediaStoreError("Images must be under 10 MB.")
    url = str(attachment.get("url", ""))
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise MediaStoreError("Discord did not return a valid image attachment.") from exc
    if (parsed.scheme != "https" or parsed.hostname not in {"cdn.discordapp.com", "media.discordapp.net"}
        or parsed.username or parsed.password or port not in (None, 443)
        or not parsed.path.startswith(("/attachments/", "/ephemeral-attachments/"))):
        raise MediaStoreError("Discord did not return a valid image attachment.")
    if audience not in {"main", "lazy"} or not re.fullmatch(r"[a-zA-Z0-9_:-]{1,80}", message_id):
        raise MediaStoreError("Choose a valid CWL message and audience first.")
    try:
        image_bytes = await asyncio.to_thread(download_image_blocking, url)
    except (requests.RequestException, ValueError, OSError) as exc:
        raise MediaStoreError("I could not download that image. Your draft is unchanged; please try again.") from exc
    slot = message_id.replace(":", "-")
    return await media.upload_bytes(image_bytes, folder=f"content/cwl/{int(guild_id)}/{slot}", name=audience)
