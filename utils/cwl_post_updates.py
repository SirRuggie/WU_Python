"""Reviewed dashboard workflow over the existing bot-owned post edit service."""

from __future__ import annotations

import asyncio
import copy
import logging

import hikari

from utils import cwl_campaign, cwl_publishing, cwl_web_bridge
from utils.cwl_post_update_store import PostUpdateConflict, PostUpdateStore

log = logging.getLogger(__name__)
EDIT_FIELDS = ("title", "body", "buttons")


async def create_review(
    mongo, *, guild_id, user_id, season_id, cycle, pool, nonce, generation, candidate
):
    """Persist an expiring private review, not saved campaign settings or a post."""
    if pool not in cwl_campaign.AUDIENCES:
        raise ValueError("Choose Main or Lazy")
    candidate = cwl_campaign.validate_roster_copy(candidate)
    loaded = await cwl_campaign.load_campaign(mongo, guild_id, cycle)
    if cwl_web_bridge.campaign_generation(loaded) != generation:
        raise PostUpdateConflict("Campaign changed. Refresh before previewing.")
    receipt = cwl_web_bridge.native_receipt(loaded, pool)
    if not receipt or not receipt.get("channel_id") or not receipt.get("message_id"):
        raise PostUpdateConflict("There is no recorded sent roster post to update.")
    if not isinstance(candidate, dict) or set(candidate) != set(EDIT_FIELDS):
        raise ValueError("Only roster text and link buttons can change")
    complete = copy.deepcopy(loaded["campaign"])
    complete["messages"]["roster"]["variants"][pool].update(copy.deepcopy(candidate))
    complete = cwl_campaign.normalize_signup_entry(complete)
    cwl_campaign.validate_campaign(complete)
    candidate = {
        field: copy.deepcopy(complete["messages"]["roster"]["variants"][pool][field])
        for field in EDIT_FIELDS
    }
    draft = await cwl_campaign.new_draft(
        mongo, guild_id, user_id, cycle, purpose="post_update"
    )
    try:
        if (
            draft["base_revision"] != loaded["revision"]
            or draft["defaults_base_revision"] != loaded["defaults_revision"]
            or draft.get("recurring_base_version") != loaded.get("recurring_version")
            or draft.get("recurring_roster_base_version")
            != loaded.get("recurring_roster_version")
        ):
            raise PostUpdateConflict("Campaign changed. Refresh before previewing.")
        await cwl_campaign.patch_draft(mongo, draft["_id"], {"campaign": complete})
        row, created = await PostUpdateStore(mongo).create(
            guild_id=guild_id,
            user_id=user_id,
            season_id=season_id,
            cycle=cycle,
            pool=pool,
            nonce=nonce,
            generation=generation,
            draft_id=draft["_id"],
            candidate=candidate,
            future_months=True,
        )
        if not created:
            await cwl_campaign.discard_draft(mongo, draft["_id"], user_id)
        return row
    except Exception:
        await cwl_campaign.discard_draft(mongo, draft["_id"], user_id)
        raise


class PostUpdateWorker:
    def __init__(self, mongo, bot, *, runtime_id):
        if not isinstance(runtime_id, str) or not runtime_id:
            raise ValueError("A worker process identity is required")
        self.mongo = mongo
        self.bot = bot
        self.runtime_id = runtime_id
        self.store = PostUpdateStore(mongo)
        self.recovered = False
        self.next_ready_attempt = 0.0

    async def ensure_ready(self, guild_id):
        if self.recovered:
            return True
        clock = asyncio.get_running_loop().time()
        if clock < self.next_ready_attempt:
            return False
        self.next_ready_attempt = clock + 300
        await self.store.recover_interrupted(
            guild_id=guild_id, runtime_id=self.runtime_id
        )
        self.recovered = True
        return True

    async def poll(self, *, guild_id, authorize):
        if not await self.ensure_ready(guild_id):
            return 0
        rows = await self.store.pending(guild_id, limit=1)
        for row in rows:
            await self.process(row, authorize=authorize)
        return len(rows)

    async def process(self, row, *, authorize):
        claimed = await self.store.claim(row, runtime_id=self.runtime_id)
        if not claimed:
            return None
        row = claimed
        updating = row["status"] == "updating"
        confirmed_url = None
        result = None
        status = "failed"
        try:
            async with asyncio.timeout(120):
                if not await authorize({**row, "requested_by": row["user_id"]}):
                    raise PermissionError("Announcement permission was removed")
                loaded = await cwl_campaign.load_campaign(
                    self.mongo, row["guild_id"], row["cycle"]
                )
                if cwl_web_bridge.campaign_generation(loaded) != row["generation"]:
                    raise PostUpdateConflict("Campaign changed. Preview again.")
                draft = await cwl_campaign.load_draft(self.mongo, row["draft_id"])
                if not draft or any(
                    draft["campaign"]["messages"]["roster"]["variants"][
                        row["pool"]
                    ].get(field)
                    != row["candidate"].get(field)
                    for field in EDIT_FIELDS
                ):
                    raise PostUpdateConflict("Draft changed. Preview again.")
                kwargs = dict(
                    guild_id=row["guild_id"],
                    cycle=row["cycle"],
                    occurrence_id=cwl_campaign.occurrence_id(
                        row["cycle"], "roster", row["pool"]
                    ),
                    user_id=row["user_id"],
                    draft_id=row["draft_id"],
                )
                if not updating:
                    target = await cwl_publishing.prepare_post_update(
                        self.mongo,
                        self.bot,
                        **kwargs,
                        include_preview=True,
                        preserve_media=True,
                    )
                    observed = target.pop("observed_preview")
                    proposed = target.pop("draft_preview")
                    result = dict(
                        target=target, live_preview=observed, draft_preview=proposed
                    )
                    status = "ready"
                else:

                    async def before_edit():
                        return await authorize({**row, "requested_by": row["user_id"]})

                    confirmed_url = await cwl_publishing.update_published_post(
                        self.mongo,
                        self.bot,
                        **kwargs,
                        target=row["target"],
                        before_edit=before_edit,
                    )
                    try:
                        saved = await cwl_campaign.save_updated_roster_variant(
                            self.mongo,
                            guild_id=row["guild_id"],
                            cycle=row["cycle"],
                            pool=row["pool"],
                            user_id=row["user_id"],
                            candidate=row["candidate"],
                            expected_generation=row["generation"],
                            future_months=row["future_months"],
                        )
                        result = dict(message_url=confirmed_url, **saved)
                    except Exception as exc:
                        log.warning(
                            "Roster post updated; saved copy could not be confirmed (%s)",
                            type(exc).__name__,
                        )
                        result = dict(
                            message_url=confirmed_url,
                            campaign_saved=False,
                            recurring_saved=False,
                            save_warning="The post was updated, but its saved copy could not be confirmed. Refresh and compare before making another update.",
                        )
                    status = "done"
        except asyncio.CancelledError:
            # Leave the claim intact. Startup marks interrupted edits uncertain,
            # never pending, even if Discord already accepted the edit.
            raise
        except hikari.NotFoundError:
            result = {
                "error": "The post was deleted or is no longer available. It cannot be updated.",
                "error_code": "deleted",
            }
        except (PermissionError, hikari.ForbiddenError):
            result = {
                "error": "You or the bot no longer have access to update this post."
            }
        except (PostUpdateConflict, ValueError) as exc:
            message = str(exc)
            if "post changed" in message.lower():
                message = "Post changed. Preview again."
            result = {"error": message}
        except Exception as exc:
            log.warning("Roster post workflow failed (%s)", type(exc).__name__)
            if confirmed_url:
                status = "done"
                result = {
                    "message_url": confirmed_url,
                    "campaign_saved": False,
                    "recurring_saved": False,
                    "save_warning": "The post was updated, but its saved copy could not be confirmed. Refresh before making another update.",
                }
            else:
                status = "uncertain" if updating else "failed"
                result = {
                    "error": (
                        "The update outcome is unconfirmed. Check the post before a new preview."
                        if updating
                        else "Preview is unavailable. Preview again."
                    )
                }
        await self.store.finish(
            row, status=status, **(result or {"error": "Post review unavailable"})
        )
        if status in ("done", "failed", "uncertain"):
            try:
                await cwl_campaign.discard_draft(
                    self.mongo, row["draft_id"], row["user_id"]
                )
            except Exception as exc:
                log.warning(
                    "Roster post scratch cleanup pending (%s)", type(exc).__name__
                )
        return await self.store.collection.find_one({"_id": row["_id"]})
