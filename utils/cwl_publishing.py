"""Review and edit a previously delivered CWL post using an owned draft.

The scheduler's delivery ledger is the authority for the target. Preparing an
edit reads and fingerprints the actual Discord message; applying rechecks it
under a short lease so another editor's update is never silently overwritten.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta

import hikari
from pymongo.errors import DuplicateKeyError

from utils import cwl_campaign
from utils.component_state import utcnow

NO_MENTIONS = {
    "user_mentions": False,
    "role_mentions": False,
    "mentions_everyone": False,
}
_log = logging.getLogger(__name__)


def _fingerprint(message):
    from extensions.commands.content import canonical_media_url

    def node(component):
        result = {"type": int(component.type)}
        for key in (
            "content",
            "label",
            "url",
            "custom_id",
            "style",
            "is_disabled",
            "accent_color",
            "divider",
            "spacing",
        ):
            value = getattr(component, key, None)
            if value is not None and value is not hikari.UNDEFINED:
                result[key] = int(value) if isinstance(value, int) else str(value)
        # Discord REST fills the separator's default SMALL spacing, while
        # Hikari builders may leave it UNDEFINED. They describe the same post.
        # Keep explicit LARGE spacing distinct for change/stale-post checks.
        if int(component.type) == int(hikari.ComponentType.SEPARATOR):
            result.setdefault("spacing", int(hikari.SpacingType.SMALL))
        emoji = getattr(component, "emoji", None)
        if emoji is not None and emoji is not hikari.UNDEFINED:
            result["emoji"] = str(emoji)
        if hasattr(component, "components"):
            result["components"] = [node(child) for child in component.components]
        if hasattr(component, "items"):
            result["media"] = [
                {
                    "url": canonical_media_url(
                        str(getattr(item.media, "url", item.media))
                    ),
                    "description": str(getattr(item, "description", "") or ""),
                    "spoiler": bool(getattr(item, "is_spoiler", False)),
                }
                for item in component.items
            ]
        return result

    data = {
        "content": getattr(message, "content", None),
        "components": [node(item) for item in message.components],
        # Attachment retention is part of this edit's reviewed state. An
        # attachment-only edit can otherwise drop a newly attached file or
        # break an attachment:// reference without changing the components.
        "attachments": [
            {
                "id": str(item.id),
                "filename": str(getattr(item, "filename", "")),
                "description": str(getattr(item, "description", "") or ""),
                "spoiler": bool(getattr(item, "is_spoiler", False)),
                "url": canonical_media_url(str(getattr(item, "url", ""))),
            }
            for item in (getattr(message, "attachments", ()) or ())
        ],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def post_preview_parts(components, *, content=None, attachments=()):
    """Plain, non-interactive preview DTO from the observed Discord snapshot.

    It does not fetch media or change the fingerprint/edit path. Both native
    builders and REST components are supported; unknown components are explicit.
    """
    from urllib.parse import urlsplit

    attachment_urls = {
        "attachment://" + str(item.filename): str(item.url) for item in attachments
    }

    def url(value):
        value = attachment_urls.get(str(value), str(value or ""))
        try:
            parts = urlsplit(value)
            return (
                value
                if parts.scheme == "https"
                and parts.hostname
                and not parts.username
                and not parts.password
                else None
            )
        except ValueError:
            return None

    def payload(component):
        if isinstance(component, dict):
            return component
        if callable(getattr(component, "build", None)):
            return component.build()[0]
        result = {"type": int(component.type)}
        for key in ("content", "label", "url", "style", "accent_color", "divider"):
            value = getattr(component, key, None)
            if value is not None and value is not hikari.UNDEFINED:
                result[key] = value
        if getattr(component, "emoji", None) is not None:
            result["emoji"] = str(component.emoji)
        if hasattr(component, "components"):
            result["components"] = [payload(child) for child in component.components]
        if hasattr(component, "items"):
            result["items"] = [
                {
                    "media": {"url": str(getattr(item.media, "url", item.media))},
                    "description": str(getattr(item, "description", "") or ""),
                }
                for item in component.items
            ]
        return result

    def convert(node):
        kind = int(node.get("type", 0))
        children = [convert(child) for child in node.get("components", ())]
        if kind == 17:
            result = {"type": "container", "children": children}
            accent = node.get("accent_color")
            if isinstance(accent, int) and 0 <= accent <= 0xFFFFFF:
                result["accent"] = f"#{accent:06x}"
            return result
        if kind == 10:
            return {"type": "text", "text": str(node.get("content", ""))}
        if kind == 14:
            return {"type": "separator", "divider": bool(node.get("divider", True))}
        if kind == 1:
            return {"type": "row", "children": children}
        if kind == 2:
            emoji = node.get("emoji")
            if isinstance(emoji, dict):
                emoji = (
                    f"<{'a' if emoji.get('animated') else ''}:{emoji.get('name') or 'emoji'}:{emoji['id']}>"
                    if emoji.get("id")
                    else str(emoji.get("name") or "")
                )
            return {
                "type": "button",
                "label": str(node.get("label", "")),
                "url": url(node.get("url")),
                "style": int(node.get("style", 5)),
                **({"emoji": emoji} if isinstance(emoji, str) and emoji else {}),
            }
        if kind == 12:
            return {
                "type": "media",
                "items": [
                    {
                        "url": url(item.get("media", {}).get("url")),
                        "description": str(item.get("description") or "Post image"),
                    }
                    for item in node.get("items", ())
                ],
            }
        return {"type": "text", "text": "[Component not shown in this preview]"}

    result = [{"type": "text", "text": str(content)}] if content else []
    result.extend(convert(payload(component)) for component in components)
    return result


async def _owned_draft(mongo, *, draft_id, guild_id, user_id, cycle, occurrence_id):
    draft = await cwl_campaign.load_draft(mongo, draft_id)
    if (
        not draft
        or int(draft["guild_id"]) != int(guild_id)
        or int(draft["user_id"]) != int(user_id)
    ):
        raise ValueError("Open your own CWL draft before updating a post.")
    parts = occurrence_id.split("|", 2)
    if len(parts) != 3 or parts[0] != cycle or draft["cycle"] != cycle:
        raise ValueError("Choose a delivered message from this draft's month.")
    _, key, audience = parts
    if (
        key not in draft["campaign"]["messages"]
        or audience not in cwl_campaign.AUDIENCES
    ):
        raise ValueError("That message version is no longer in this draft.")
    return draft, key, audience


async def _bot_id(bot):
    me = bot.get_me()
    return int((me or await bot.rest.fetch_my_user()).id)


async def _render_post_update(
    draft, cycle, key, audience, message, *, preserve_media=False
):
    rendered = await cwl_campaign.render_message(
        {
            "campaign": draft["campaign"],
            "cycle": cycle,
            "deadline": cwl_campaign.signup_deadline(
                draft["campaign"], cycle
            ).isoformat(),
        },
        key,
        audience,
        preview=False,
    )
    if not preserve_media:
        return rendered
    if (
        key != "roster"
        or len(rendered) != 1
        or len(message.components) != 1
        or int(message.components[0].type) != 17
    ):
        raise ValueError("This post layout is not supported by the roster text editor")
    from extensions.commands.content import media_galleries, media_url

    galleries = []
    for gallery in media_galleries(message.components):
        items = []
        for item in gallery.items:
            description = getattr(item, "description", None)
            items.append(
                hikari.impl.MediaGalleryItemBuilder(
                    media=media_url(item),
                    description=(
                        description if description is not None else hikari.UNDEFINED
                    ),
                    spoiler=bool(getattr(item, "is_spoiler", False)),
                )
            )
        galleries.append(hikari.impl.MediaGalleryComponentBuilder(items=items))
    children = [node for node in rendered[0].components if int(node.type) != 12]
    # This editor changes text/buttons, not the post's visible notification
    # header. Saved roles may have changed since this older post was sent.
    configured_roles = (
        draft["campaign"]["messages"][key]["variants"][audience].get("role_ids") or []
    )
    if configured_roles:
        expected_header = " ".join(f"<@&{role}>" for role in configured_roles)
        if (
            len(children) < 2
            or getattr(children[0], "content", None) != expected_header
            or int(children[1].type) != 14
        ):
            raise ValueError("This post notification layout cannot be preserved")
        children = children[2:]
    observed_children = message.components[0].components
    header = (
        str(getattr(observed_children[0], "content", "")) if observed_children else ""
    )
    if re.fullmatch(r"<@&[0-9]+>(?:\s+<@&[0-9]+>)*", header):
        if len(observed_children) < 2 or int(observed_children[1].type) != 14:
            raise ValueError("This post notification layout cannot be preserved")
        children[:0] = [
            hikari.impl.TextDisplayComponentBuilder(content=header),
            hikari.impl.SeparatorComponentBuilder(
                divider=bool(getattr(observed_children[1], "divider", True))
            ),
        ]
    # Native roster sender: [optional mention, divider], title, divider,
    # body, [gallery], [button row]. Never guess where images belong in a
    # foreign layout. Keep every original gallery at its exact child index.
    original_nonmedia = [node for node in observed_children if int(node.type) != 12]
    if [int(node.type) for node in original_nonmedia] != [
        int(node.type) for node in children
    ]:
        raise ValueError("This post layout cannot be kept. Not updated.")
    for index, gallery in zip(
        [index for index, node in enumerate(observed_children) if int(node.type) == 12],
        galleries,
    ):
        children.insert(index, gallery)
    observed = message.components[0]
    accent = getattr(observed, "accent_color", None)
    result = [
        hikari.impl.ContainerComponentBuilder(
            accent_color=accent if accent is not None else hikari.UNDEFINED,
            spoiler=bool(getattr(observed, "is_spoiler", False)),
            components=children,
        )
    ]

    def units(nodes):
        return sum(
            1 + units(getattr(node, "components", ())) + len(getattr(node, "items", ()))
            for node in nodes
        )

    if units(result) > 40:
        raise ValueError("This post has too many components for the reviewed edit")

    def text_length(nodes):
        return sum(
            len(str(getattr(node, "content", "")))
            + text_length(getattr(node, "components", ()))
            for node in nodes
        )

    if text_length(result) > 4000:
        raise ValueError("This roster post text is too long after Discord formatting")
    return result


async def prepare_post_update(
    mongo,
    bot,
    *,
    guild_id,
    cycle,
    occurrence_id,
    user_id,
    draft_id,
    include_preview=False,
    preserve_media=False,
):
    draft, key, audience = await _owned_draft(
        mongo,
        draft_id=draft_id,
        guild_id=guild_id,
        user_id=user_id,
        cycle=cycle,
        occurrence_id=occurrence_id,
    )
    loaded = await cwl_campaign.load_campaign(mongo, guild_id, cycle)
    delivery = next(
        (
            item
            for item in reversed(loaded["deliveries"])
            if item.get("occurrence_id") == occurrence_id
            and item.get("status") == "sent"
            and item.get("channel_id")
            and item.get("message_id")
        ),
        None,
    )
    if not delivery:
        raise ValueError(
            "There is no recorded published post for this message version."
        )
    channel_id, message_id = int(delivery["channel_id"]), int(delivery["message_id"])
    try:
        channel = await bot.rest.fetch_channel(channel_id)
    except hikari.NotFoundError as exc:
        raise PermissionError("Post channel access changed") from exc
    if int(getattr(channel, "guild_id", 0)) != int(guild_id):
        raise ValueError("That published post belongs to another server.")
    message = await bot.rest.fetch_message(channel_id, message_id)
    if int(message.author.id) != await _bot_id(bot):
        raise ValueError("Only this bot's CWL posts can be updated.")
    target = {
        "channel_id": channel_id,
        "message_id": message_id,
        "fingerprint": _fingerprint(message),
        "draft_updated_at": draft["updated_at"],
        "occurrence_id": occurrence_id,
        "guild_id": int(guild_id),
        "user_id": int(user_id),
        "draft_id": draft_id,
    }
    if preserve_media:
        target["preserve_media"] = True
    if include_preview:
        rendered = await _render_post_update(
            draft, cycle, key, audience, message, preserve_media=preserve_media
        )
        channel_name = str(getattr(channel, "name", "") or "").strip()
        if not channel_name:
            raise ValueError(
                "The post channel name is unavailable. Preview again later."
            )
        target["draft_preview"] = post_preview_parts(
            rendered,
            content=getattr(message, "content", None) if preserve_media else None,
            attachments=getattr(message, "attachments", ()),
        )
        target.update(
            channel_name=channel_name,
            message_url=f"https://discord.com/channels/{int(guild_id)}/{channel_id}/{message_id}",
            observed_preview=post_preview_parts(
                message.components,
                content=getattr(message, "content", None),
                attachments=getattr(message, "attachments", ()),
            ),
        )
        from types import SimpleNamespace

        target["has_changes"] = _fingerprint(message) != _fingerprint(
            SimpleNamespace(
                content=getattr(message, "content", None),
                components=rendered,
                attachments=getattr(message, "attachments", ()),
            )
        )
        # Presentation only: identity/fingerprint/rendered payload retain exact
        # mentions; private previews display real role names, never snowflakes.
        role_ids = set(
            re.findall(
                r"<@&([0-9]+)>",
                json.dumps([target["observed_preview"], target["draft_preview"]]),
            )
        )
        try:
            roles = await bot.rest.fetch_roles(int(guild_id)) if role_ids else ()
        except hikari.NotFoundError as exc:
            raise PermissionError("Server access changed") from exc
        names = {str(role.id): str(role.name) for role in roles}

        def role_labels(value):
            if isinstance(value, str):
                return re.sub(
                    r"<@&([0-9]+)>",
                    lambda match: "@" + names.get(match[1], "role"),
                    value,
                )
            if isinstance(value, list):
                return [role_labels(item) for item in value]
            if isinstance(value, dict):
                return {key: role_labels(item) for key, item in value.items()}
            return value

        target["observed_preview"] = role_labels(target["observed_preview"])
        target["draft_preview"] = role_labels(target["draft_preview"])
    return target


async def update_published_post(
    mongo,
    bot,
    *,
    guild_id,
    cycle,
    occurrence_id,
    user_id,
    draft_id,
    target,
    before_edit=None,
    on_edit_attempt=None,
):
    draft, key, audience = await _owned_draft(
        mongo,
        draft_id=draft_id,
        guild_id=guild_id,
        user_id=user_id,
        cycle=cycle,
        occurrence_id=occurrence_id,
    )
    if any(
        target.get(field) != value
        for field, value in {
            "guild_id": int(guild_id),
            "user_id": int(user_id),
            "draft_id": draft_id,
            "occurrence_id": occurrence_id,
            "draft_updated_at": draft["updated_at"],
        }.items()
    ):
        raise ValueError("The draft changed. Preview and review the post update again.")
    token = uuid.uuid4().hex
    lease_id = f"cwl:post-edit:{target['channel_id']}:{target['message_id']}"
    try:
        await mongo.bot_config.update_one(
            {"_id": lease_id, "until": {"$lte": utcnow()}},
            {"$set": {"until": utcnow() + timedelta(minutes=2), "token": token}},
            upsert=True,
        )
    except DuplicateKeyError as exc:
        raise ValueError(
            "Another editor is updating that post. Try again shortly."
        ) from exc
    try:
        current = await prepare_post_update(
            mongo,
            bot,
            guild_id=guild_id,
            cycle=cycle,
            occurrence_id=occurrence_id,
            user_id=user_id,
            draft_id=draft_id,
        )
        if any(
            current[field] != target[field]
            for field in ("channel_id", "message_id", "fingerprint", "draft_updated_at")
        ):
            raise ValueError(
                "That post changed since you reviewed it. Preview the update again."
            )
        message = await bot.rest.fetch_message(
            target["channel_id"], target["message_id"]
        )
        if _fingerprint(message) != target["fingerprint"]:
            raise ValueError(
                "That post changed since you reviewed it. Preview the update again."
            )
        preserve_media = target.get("preserve_media", False)
        if type(preserve_media) is not bool:
            raise ValueError("Invalid post image preservation scope")
        rendered = await _render_post_update(
            draft, cycle, key, audience, message, preserve_media=preserve_media
        )
        from extensions.commands.content import (
            discord_attachment_id,
            media_galleries,
            media_url,
        )

        referenced = {
            discord_attachment_id(media_url(item))
            for gallery in media_galleries(rendered)
            for item in gallery.items
        }
        retained = (
            list(message.attachments)
            if preserve_media
            else [item for item in message.attachments if str(item.id) in referenced]
        )
        if before_edit is not None:
            if await before_edit() is not True:
                raise PermissionError(
                    "Announcement access or scope changed before the edit"
                )
            # Scope validation may await the backend. Re-read the fingerprint
            # afterward rather than opening a new stale-post window.
            checked = await bot.rest.fetch_message(
                target["channel_id"], target["message_id"]
            )
            if _fingerprint(checked) != target["fingerprint"]:
                raise ValueError(
                    "That post changed since you reviewed it. Preview the update again."
                )
        if on_edit_attempt is not None:
            on_edit_attempt()
        await bot.rest.edit_message(
            target["channel_id"],
            target["message_id"],
            components=rendered,
            attachments=retained,
            **NO_MENTIONS,
        )
        try:
            await cwl_campaign.record_delivery(
                mongo,
                guild_id,
                cycle,
                {
                    "occurrence_id": occurrence_id,
                    "status": "post_updated",
                    "by": int(user_id),
                    "channel_id": target["channel_id"],
                    "message_id": target["message_id"],
                    "message_url": f"https://discord.com/channels/{int(guild_id)}/{target['channel_id']}/{target['message_id']}",
                },
            )
        except Exception:
            # The external edit already succeeded. Do not tell the editor it
            # failed and invite a repeat write because its audit append failed.
            _log.exception(
                "CWL post %s updated; audit append failed (guild %s, editor %s)",
                target["message_id"],
                guild_id,
                user_id,
            )
        return f"https://discord.com/channels/{int(guild_id)}/{target['channel_id']}/{target['message_id']}"
    finally:
        try:
            await mongo.bot_config.delete_one({"_id": lease_id, "token": token})
        except Exception:
            # A stranded lease expires in two minutes. Preserve the outcome of
            # the edit instead of replacing it with an unrelated cleanup error.
            _log.exception("Could not release CWL post edit lease %s", lease_id)
