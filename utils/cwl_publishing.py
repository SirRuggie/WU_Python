"""Review and edit a previously delivered CWL post using an owned draft.

The scheduler's delivery ledger is the authority for the target. Preparing an
edit reads and fingerprints the actual Discord message; applying rechecks it
under a short lease so another editor's update is never silently overwritten.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import timedelta

import hikari
from pymongo.errors import DuplicateKeyError

from utils import cwl_campaign
from utils.component_state import utcnow

NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
_log = logging.getLogger(__name__)


def _fingerprint(message):
    from extensions.commands.content import canonical_media_url

    def node(component):
        result = {"type": int(component.type)}
        for key in ("content", "label", "url", "custom_id", "style", "is_disabled", "accent_color", "divider", "spacing"):
            value = getattr(component, key, None)
            if value is not None and value is not hikari.UNDEFINED:
                result[key] = int(value) if isinstance(value, int) else str(value)
        emoji = getattr(component, "emoji", None)
        if emoji is not None:
            result["emoji"] = str(emoji)
        if hasattr(component, "components"):
            result["components"] = [node(child) for child in component.components]
        if hasattr(component, "items"):
            result["media"] = [
                {"url": canonical_media_url(str(getattr(item.media, "url", item.media))),
                 "description": str(getattr(item, "description", "") or ""),
                 "spoiler": bool(getattr(item, "is_spoiler", False))}
                for item in component.items
            ]
        return result

    data = {"content": getattr(message, "content", None), "components": [node(item) for item in message.components]}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


async def _owned_draft(mongo, *, draft_id, guild_id, user_id, cycle, occurrence_id):
    draft = await cwl_campaign.load_draft(mongo, draft_id)
    if not draft or int(draft["guild_id"]) != int(guild_id) or int(draft["user_id"]) != int(user_id):
        raise ValueError("Open your own CWL draft before updating a post.")
    parts = occurrence_id.split("|", 2)
    if len(parts) != 3 or parts[0] != cycle or draft["cycle"] != cycle:
        raise ValueError("Choose a delivered message from this draft's month.")
    _, key, audience = parts
    if key not in draft["campaign"]["messages"] or audience not in cwl_campaign.AUDIENCES:
        raise ValueError("That message version is no longer in this draft.")
    return draft, key, audience


async def _bot_id(bot):
    me = bot.get_me()
    return int((me or await bot.rest.fetch_my_user()).id)


async def prepare_post_update(mongo, bot, *, guild_id, cycle, occurrence_id, user_id, draft_id):
    draft, key, audience = await _owned_draft(
        mongo, draft_id=draft_id, guild_id=guild_id, user_id=user_id, cycle=cycle, occurrence_id=occurrence_id
    )
    loaded = await cwl_campaign.load_campaign(mongo, guild_id, cycle)
    delivery = next((item for item in reversed(loaded["deliveries"])
                     if item.get("occurrence_id") == occurrence_id and item.get("status") == "sent"
                     and item.get("channel_id") and item.get("message_id")), None)
    if not delivery:
        raise ValueError("There is no recorded published post for this message version.")
    channel_id, message_id = int(delivery["channel_id"]), int(delivery["message_id"])
    channel = await bot.rest.fetch_channel(channel_id)
    if int(getattr(channel, "guild_id", 0)) != int(guild_id):
        raise ValueError("That published post belongs to another server.")
    message = await bot.rest.fetch_message(channel_id, message_id)
    if int(message.author.id) != await _bot_id(bot):
        raise ValueError("Only this bot's CWL posts can be updated.")
    return {"channel_id": channel_id, "message_id": message_id, "fingerprint": _fingerprint(message),
            "draft_updated_at": draft["updated_at"], "occurrence_id": occurrence_id,
            "guild_id": int(guild_id), "user_id": int(user_id), "draft_id": draft_id}


async def update_published_post(mongo, bot, *, guild_id, cycle, occurrence_id, user_id, draft_id, target):
    draft, key, audience = await _owned_draft(
        mongo, draft_id=draft_id, guild_id=guild_id, user_id=user_id, cycle=cycle, occurrence_id=occurrence_id
    )
    if any(target.get(field) != value for field, value in {
        "guild_id": int(guild_id), "user_id": int(user_id), "draft_id": draft_id,
        "occurrence_id": occurrence_id, "draft_updated_at": draft["updated_at"],
    }.items()):
        raise ValueError("The draft changed. Preview and review the post update again.")
    token = uuid.uuid4().hex
    lease_id = f"cwl:post-edit:{target['channel_id']}:{target['message_id']}"
    try:
        await mongo.bot_config.update_one(
            {"_id": lease_id, "until": {"$lte": utcnow()}},
            {"$set": {"until": utcnow() + timedelta(minutes=2), "token": token}}, upsert=True,
        )
    except DuplicateKeyError as exc:
        raise ValueError("Another editor is updating that post. Try again shortly.") from exc
    try:
        current = await prepare_post_update(
            mongo, bot, guild_id=guild_id, cycle=cycle, occurrence_id=occurrence_id,
            user_id=user_id, draft_id=draft_id,
        )
        if any(current[field] != target[field] for field in ("channel_id", "message_id", "fingerprint", "draft_updated_at")):
            raise ValueError("That post changed since you reviewed it. Preview the update again.")
        rendered = await cwl_campaign.render_message({
            "campaign": draft["campaign"], "cycle": cycle,
            "deadline": cwl_campaign.signup_deadline(draft["campaign"], cycle).isoformat(),
        }, key, audience, preview=False)
        message = await bot.rest.fetch_message(target["channel_id"], target["message_id"])
        if _fingerprint(message) != target["fingerprint"]:
            raise ValueError("That post changed since you reviewed it. Preview the update again.")
        from extensions.commands.content import discord_attachment_id, media_galleries, media_url
        referenced = {discord_attachment_id(media_url(item)) for gallery in media_galleries(rendered) for item in gallery.items}
        retained = [item for item in message.attachments if str(item.id) in referenced]
        await bot.rest.edit_message(target["channel_id"], target["message_id"], components=rendered, attachments=retained, **NO_MENTIONS)
        try:
            await cwl_campaign.record_delivery(mongo, guild_id, cycle, {
                "occurrence_id": occurrence_id, "status": "post_updated", "by": int(user_id),
                "channel_id": target["channel_id"], "message_id": target["message_id"],
                "message_url": f"https://discord.com/channels/{int(guild_id)}/{target['channel_id']}/{target['message_id']}",
            })
        except Exception:
            # The external edit already succeeded. Do not tell the editor it
            # failed and invite a repeat write because its audit append failed.
            _log.exception("CWL post %s updated; audit append failed (guild %s, editor %s)", target["message_id"], guild_id, user_id)
        return f"https://discord.com/channels/{int(guild_id)}/{target['channel_id']}/{target['message_id']}"
    finally:
        try:
            await mongo.bot_config.delete_one({"_id": lease_id, "token": token})
        except Exception:
            # A stranded lease expires in two minutes. Preserve the outcome of
            # the edit instead of replacing it with an unrelated cleanup error.
            _log.exception("Could not release CWL post edit lease %s", lease_id)
