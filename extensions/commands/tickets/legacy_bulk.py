"""Admin-triggered bulk driver over many single legacy-channel migrations.

Every Discord/Mongo side effect for one ticket still belongs to
``legacy_migration.preview_legacy_ticket``/``migrate_legacy_ticket`` and its own
checkpointed ``ticket_migrations`` row. This module only decides *which*
legacy channels in a source guild are in scope, previews and classifies them
without writing anything (dry run), and then drives ``migrate_legacy_ticket``
over the ``ready`` ones in channel-id (oldest-first) order, one source guild
at a time, durably tracked in ``ticket_migration_batches`` so a restart
resumes cleanly. Legacy channels themselves are never modified.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import hikari
import lightbulb
from pymongo import ReturnDocument

from extensions.commands.tickets import legacy_migration, ticket
from utils.mongo import MongoClient


_log = logging.getLogger(__name__)

BATCH_LEASE = timedelta(seconds=45)
PLAN_STALE_AFTER = timedelta(hours=24)
PREVIEW_SLEEP_SECONDS = 0.25
PROGRESS_EDIT_EVERY = 5
CONSECUTIVE_FAILURE_LIMIT = 10
MAX_CHANNELS_PER_PLAN = 1000
DRY_RUN_PROBLEM_LIMIT = 15

CLASS_READY = "ready"
CLASS_ALREADY_COPIED = "already_copied"
CLASS_OPEN = "open"
CLASS_NO_APPLICANT = "no_applicant"
CLASS_AMBIGUOUS_TYPE = "ambiguous_type"

_as_int = legacy_migration._as_int
_aware = legacy_migration._aware
utcnow = legacy_migration.utcnow


class BulkMigrationError(RuntimeError):
    pass


def _batch_id(source_guild_id: int) -> str:
    return f"batch:{int(source_guild_id)}"


def _entry(
    channel_id: int,
    channel_name: str,
    classification: str,
    detail: str,
    ticket_type: str | None,
) -> dict[str, Any]:
    return {
        "channel_id": int(channel_id),
        "channel_name": str(channel_name),
        "classification": classification,
        "detail": str(detail or "")[:300],
        "ticket_type": ticket_type,
        "status": "pending" if classification == CLASS_READY else "skipped",
    }


def _tally(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
    return counts


async def _candidate_channels(
    rest: hikari.api.RESTClient, guild_id: int, category_id: int | None
) -> list[Any]:
    channels = await rest.fetch_guild_channels(guild_id)
    matched = [
        channel for channel in channels
        if getattr(channel, "type", None) == hikari.ChannelType.GUILD_TEXT
        and (category_id is None or _as_int(getattr(channel, "parent_id", 0)) == category_id)
        and legacy_migration._TICKET_NUMBER_RE.search(str(getattr(channel, "name", "")))
    ]
    matched.sort(key=lambda channel: int(channel.id))
    return matched


def _destination_for_type(
    config: Mapping[str, Any], ticket_type: str
) -> tuple[int, int] | None:
    candidate_parent_id = _as_int(config.get(f"{ticket_type}_candidate_parent"))
    staff_parent_id = _as_int(config.get(f"{ticket_type}_staff_parent"))
    if not candidate_parent_id or not staff_parent_id:
        return None
    return candidate_parent_id, staff_parent_id


async def _classify(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    request: legacy_migration.LegacyMigrationRequest,
) -> tuple[str, str]:
    try:
        await legacy_migration.preview_legacy_ticket(bot=bot, mongo=mongo, request=request)
    except legacy_migration.LegacyTicketStillOpen as error:
        return CLASS_OPEN, str(error)
    except legacy_migration.LegacyMigrationError as error:
        message = str(error)
        if "candidate Discord ID could not be detected" in message:
            return CLASS_NO_APPLICANT, message
        if "ticket type could not be detected" in message:
            return CLASS_AMBIGUOUS_TYPE, message
        return f"error:{type(error).__name__}", message
    except Exception as error:  # pragma: no cover - defensive, logged below
        _log.exception(
            "[Tickets] bulk_migration_preview_failed channel=%s", request.source_channel_id
        )
        return f"error:{type(error).__name__}", str(error)
    return CLASS_READY, ""


async def build_plan(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    source_guild_id: int,
    category_id: int | None,
    attachments: str,
    limit: int | None,
) -> dict[str, Any]:
    """Read-only: list, classify, and durably record a fresh plan for one guild."""
    rest = bot.rest
    channels = await _candidate_channels(rest, source_guild_id, category_id)
    if len(channels) > MAX_CHANNELS_PER_PLAN:
        raise BulkMigrationError(
            f"this category has {len(channels)} matching channels, above the "
            f"{MAX_CHANNELS_PER_PLAN}-channel bulk-plan limit; narrow the category and try again"
        )

    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))

    entries: list[dict[str, Any]] = []
    for channel in channels:
        channel_id = int(channel.id)
        channel_name = str(getattr(channel, "name", channel_id))
        migration_id = legacy_migration._migration_id(source_guild_id, channel_id)
        existing = await mongo.ticket_migrations.find_one({"_id": migration_id})
        if existing and existing.get("state") == "complete":
            entries.append(
                _entry(channel_id, channel_name, CLASS_ALREADY_COPIED, "already copied", None)
            )
            continue

        try:
            ticket_type = legacy_migration._infer_ticket_type(None, channel_name, None)
        except legacy_migration.LegacyMigrationError as error:
            entries.append(
                _entry(channel_id, channel_name, CLASS_AMBIGUOUS_TYPE, str(error), None)
            )
            continue

        parents = _destination_for_type(config, ticket_type)
        if not target_guild_id or parents is None:
            entries.append(_entry(
                channel_id, channel_name, f"error:{BulkMigrationError.__name__}",
                f"target destination or {ticket_type.upper()} parents are not configured",
                ticket_type,
            ))
            continue

        candidate_parent_id, staff_parent_id = parents
        request = legacy_migration.LegacyMigrationRequest(
            source_guild_id=source_guild_id,
            source_channel_id=channel_id,
            target_guild_id=target_guild_id,
            candidate_parent_id=candidate_parent_id,
            staff_parent_id=staff_parent_id,
        )
        classification, detail = await _classify(bot=bot, mongo=mongo, request=request)
        entries.append(_entry(channel_id, channel_name, classification, detail, ticket_type))
        await asyncio.sleep(PREVIEW_SLEEP_SECONDS)

    now = utcnow()
    batch_id = _batch_id(source_guild_id)
    current = await mongo.ticket_migration_batches.find_one({"_id": batch_id})
    if current is not None and current.get("state") == "running":
        lease_until = _aware(current.get("lease_until"))
        if lease_until is not None and lease_until > now:
            raise BulkMigrationError(
                "a bulk run is currently in progress for this source guild; wait for it "
                "to finish or let it pause before planning again"
            )

    document = {
        "_id": batch_id,
        "kind": "legacy_migration_batch",
        "schema_version": 1,
        "source_guild_id": int(source_guild_id),
        "category_id": int(category_id) if category_id else None,
        "attachments": attachments,
        "requested_limit": int(limit) if limit else None,
        "state": "planned",
        "entries": entries,
        "counts": _tally(entries),
        "consecutive_failures": 0,
        "created_at": (current or {}).get("created_at", now),
        "updated_at": now,
        "planned_at": now,
    }
    filt: dict[str, Any] = {"_id": batch_id}
    upsert = current is None
    if not upsert:
        filt["revision"] = int(current.get("revision", 0))
    saved = await mongo.ticket_migration_batches.find_one_and_update(
        filt,
        {"$set": document, "$inc": {"revision": 1}},
        upsert=upsert,
        return_document=ReturnDocument.AFTER,
    )
    if saved is None:
        raise BulkMigrationError("the batch plan changed concurrently; run the dry run again")
    return saved


def _jump_link(guild_id: int, channel_id: int) -> str:
    return f"https://discord.com/channels/{int(guild_id)}/{int(channel_id)}"


def dry_run_summary(document: dict[str, Any], *, guild_name: str) -> str:
    """Bounded, plain-English preview of a freshly planned batch."""
    counts = document.get("counts") or {}
    entries = document.get("entries") or []
    total = len(entries)
    ready = int(counts.get(CLASS_READY, 0))
    lines = [
        f"**Source:** `{document['source_guild_id']}` — {guild_name}",
        f"**Matching legacy channels:** `{total}`",
        f"**Ready to copy:** `{ready}`",
    ]
    by_type: dict[str, int] = {}
    for entry in entries:
        if entry["classification"] == CLASS_READY:
            key = str(entry.get("ticket_type") or "unknown")
            by_type[key] = by_type.get(key, 0) + 1
    if by_type:
        lines.append(
            "**By type:** " + ", ".join(f"{key}: `{value}`" for key, value in sorted(by_type.items()))
        )
    other = {key: value for key, value in counts.items() if key != CLASS_READY}
    if other:
        lines.append(
            "**Not ready:** " + ", ".join(f"{key}: `{value}`" for key, value in sorted(other.items()))
        )

    all_problems = [entry for entry in entries if entry["classification"] != CLASS_READY]
    problems = all_problems[:DRY_RUN_PROBLEM_LIMIT]
    if problems:
        lines.append("\n**First problem channels:**")
        for entry in problems:
            link = _jump_link(document["source_guild_id"], entry["channel_id"])
            lines.append(
                f"• [{entry['channel_name']}]({link}) — `{entry['classification']}`"
                + (f": {entry['detail']}" if entry["detail"] else "")
            )
        remaining = len(all_problems) - len(problems)
        if remaining > 0:
            lines.append(f"… +{remaining} more not shown")

    attachments = document.get("attachments", "copy")
    lines.append(
        f"\nRe-run with `confirm: true` (attachments: `{attachments}`) to copy the "
        f"`{ready}` ready ticket{'s' if ready != 1 else ''}. Nothing was written."
    )
    return "\n".join(lines)


async def _console_channel_id(mongo: MongoClient) -> int:
    hub = await mongo.ticket_setup.find_one({"_id": "ticket_console_hub"}) or {}
    return _as_int(hub.get("channel_id"))


def _progress_text(
    guild_name: str, *, done: int, failed: int, skipped: int, total: int
) -> str:
    stamp = int(utcnow().timestamp())
    return (
        f"Copying legacy tickets from {guild_name}: {done}/{total} done, "
        f"{failed} failed, {skipped} skipped · <t:{stamp}:R>"
    )


async def _cas_update(
    mongo: MongoClient,
    document: dict[str, Any],
    *,
    set_fields: dict[str, Any] | None = None,
    unset_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    revision = int(document.get("revision", 0))
    now = utcnow()
    update: dict[str, Any] = {"$set": {**(set_fields or {}), "updated_at": now}, "$inc": {"revision": 1}}
    if unset_fields:
        update["$unset"] = unset_fields
    updated = await mongo.ticket_migration_batches.find_one_and_update(
        {"_id": document["_id"], "revision": revision},
        update,
        return_document=ReturnDocument.AFTER,
    )
    if updated is None:
        raise BulkMigrationError(
            "the batch changed concurrently while a lease was held; this should not happen"
        )
    return updated


async def _claim_batch_lease(
    mongo: MongoClient, batch_id: str, owner: str, now: datetime
) -> dict[str, Any] | None:
    return await mongo.ticket_migration_batches.find_one_and_update(
        {
            "_id": batch_id,
            "$or": [
                {"lease_until": {"$exists": False}},
                {"lease_until": {"$lte": now}},
                {"lease_owner": owner},
            ],
        },
        {
            "$set": {
                "state": "running",
                "lease_owner": owner,
                "lease_until": now + BATCH_LEASE,
                "updated_at": now,
            },
            "$inc": {"revision": 1},
        },
        return_document=ReturnDocument.AFTER,
    )


async def run_batch(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    source_guild_id: int,
    guild_name: str,
    limit: int | None,
    actor_id: int,
    actor_name: str,
) -> dict[str, Any]:
    """Process `ready` entries oldest-first, up to `limit`, resuming durably."""
    batch_id = _batch_id(source_guild_id)
    now = utcnow()
    current = await mongo.ticket_migration_batches.find_one({"_id": batch_id})
    if current is None:
        raise BulkMigrationError(
            "no planned batch found for this source guild; run a dry run first"
        )
    state = current.get("state")
    if state == "planned":
        planned_at = _aware(current.get("planned_at")) or _aware(current.get("created_at"))
        if planned_at is None or now - planned_at > PLAN_STALE_AFTER:
            raise BulkMigrationError(
                "the plan is more than 24 hours old; run a new dry run first"
            )
    elif state not in {"running", "paused"}:
        raise BulkMigrationError(
            f"batch is `{state}`; run a new dry run before confirming"
        )

    owner = uuid.uuid4().hex
    claimed = await _claim_batch_lease(mongo, batch_id, owner, now)
    if claimed is None:
        raise BulkMigrationError(
            "another run is already in progress for this source guild"
        )
    document = claimed

    entries = document["entries"]
    attachments_policy = document.get("attachments", "copy")
    total = sum(1 for entry in entries if entry["classification"] == CLASS_READY)
    done = sum(1 for entry in entries if entry["status"] == "done")
    failed = sum(1 for entry in entries if str(entry["status"]).startswith("failed:"))
    skipped = sum(1 for entry in entries if entry["classification"] != CLASS_READY)
    consecutive_failures = int(document.get("consecutive_failures", 0))

    channel_id = _as_int(document.get("progress_channel_id"))
    message_id = _as_int(document.get("progress_message_id"))
    if not message_id:
        console_channel_id = await _console_channel_id(mongo)
        if console_channel_id:
            message = await bot.rest.create_message(
                console_channel_id,
                _progress_text(guild_name, done=done, failed=failed, skipped=skipped, total=total),
            )
            channel_id = console_channel_id
            message_id = int(message.id)
            document = await _cas_update(mongo, document, set_fields={
                "progress_channel_id": channel_id,
                "progress_message_id": message_id,
            })

    async def _post_progress() -> None:
        if not channel_id or not message_id:
            return
        try:
            await bot.rest.edit_message(
                channel_id, message_id,
                _progress_text(guild_name, done=done, failed=failed, skipped=skipped, total=total),
            )
        except (hikari.NotFoundError, hikari.ForbiddenError):
            _log.warning(
                "[Tickets] bulk_migration_progress_message_missing batch=%s", batch_id
            )

    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    processed_this_run = 0
    paused = False

    for entry in entries:
        if entry["classification"] != CLASS_READY or entry["status"] == "done":
            continue
        if limit is not None and processed_this_run >= limit:
            break

        ticket_type = entry.get("ticket_type")
        parents = _destination_for_type(config, ticket_type) if ticket_type else None
        target_guild_id = _as_int(config.get("ticket_target_guild_id"))
        if not target_guild_id or parents is None:
            entry["status"] = "failed:destination not configured"
            failed += 1
            consecutive_failures += 1
        else:
            candidate_parent_id, staff_parent_id = parents
            request = legacy_migration.LegacyMigrationRequest(
                source_guild_id=source_guild_id,
                source_channel_id=entry["channel_id"],
                target_guild_id=target_guild_id,
                candidate_parent_id=candidate_parent_id,
                staff_parent_id=staff_parent_id,
                attachment_ack_actor_id=actor_id,
                attachment_ack_actor_name=actor_name,
                bulk_batch_id=batch_id,
            )
            try:
                preview = await legacy_migration.preview_legacy_ticket(
                    bot=bot, mongo=mongo, request=request
                )
                if attachments_policy == "copy":
                    token = legacy_migration._attachment_ack_token(preview)
                    if token:
                        preview = await legacy_migration.preview_legacy_ticket(
                            bot=bot, mongo=mongo,
                            request=replace(request, attachment_ack=token),
                        )
                result = await legacy_migration.migrate_legacy_ticket(
                    bot=bot, mongo=mongo, preview=preview
                )
            except Exception as error:
                entry["status"] = f"failed:{type(error).__name__}: {str(error)[:180]}"
                failed += 1
                consecutive_failures += 1
                _log.warning(
                    "[Tickets] bulk_migration_channel_failed batch=%s channel=%s error=%s",
                    batch_id, entry["channel_id"], error,
                )
            else:
                entry["status"] = "done"
                entry["destination_ticket_id"] = result.ticket.get("_id")
                entry["destination_ticket_number"] = result.ticket.get("ticket_number")
                done += 1
                consecutive_failures = 0

        processed_this_run += 1
        document = await _cas_update(mongo, document, set_fields={
            "entries": entries,
            "counts": _tally(entries),
            "consecutive_failures": consecutive_failures,
            "lease_owner": owner,
            "lease_until": utcnow() + BATCH_LEASE,
        })

        if done % PROGRESS_EDIT_EVERY == 0:
            await _post_progress()

        if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
            paused = True
            document = await _cas_update(mongo, document, set_fields={"state": "paused"})
            break

    remaining_pending = any(
        entry["classification"] == CLASS_READY and entry["status"] == "pending"
        for entry in entries
    )
    if not paused:
        if remaining_pending:
            document = await _cas_update(
                mongo, document,
                set_fields={"updated_at": utcnow()},
                unset_fields={"lease_owner": "", "lease_until": ""},
            )
        else:
            document = await _cas_update(
                mongo, document,
                set_fields={"state": "complete", "completed_at": utcnow()},
                unset_fields={"lease_owner": "", "lease_until": ""},
            )

    await _post_progress()
    return document


async def _guild_choices_source(ctx: lightbulb.AutocompleteContext[str]) -> None:
    await legacy_migration._guild_choices(ctx)


async def _category_choices(ctx: lightbulb.AutocompleteContext[str]) -> None:
    operator = legacy_migration._autocomplete_operator(ctx)
    if operator is None:
        await ctx.respond([])
        return
    _operator_guild_id, actor_id = operator
    guild_id = _as_int(legacy_migration._option_value(ctx, "source-guild"))
    if not guild_id or not await legacy_migration._guild_administrator(
        ctx.client.app.rest, guild_id, actor_id
    ):
        await ctx.respond([])
        return
    query = str(ctx.focused.value or "").casefold()
    channels = await ctx.client.app.rest.fetch_guild_channels(guild_id)
    choices = [
        (f"{channel.name} — {channel.id}"[:100], str(channel.id))
        for channel in channels
        if getattr(channel, "type", None) == hikari.ChannelType.GUILD_CATEGORY
        and (query in str(channel.name).casefold() or query in str(channel.id))
    ][:25]
    await ctx.respond(choices)


@ticket.register()
class MigrateAllLegacyTickets(
    lightbulb.SlashCommand,
    name="migrate-all",
    description="Preview or bulk-copy many legacy ticket channels to archived threads (Admin only)",
):
    source_guild = lightbulb.string(
        "source-guild", "Select a bot-accessible source server", autocomplete=_guild_choices_source
    )
    category = lightbulb.string(
        "category",
        "Limit to one legacy category; leave blank for every category",
        default=None,
        autocomplete=_category_choices,
    )
    attachments = lightbulb.string(
        "attachments",
        "Copy attachments where possible, or skip them and keep text only",
        default="copy",
        choices=[
            lightbulb.Choice(name="Copy", value="copy"),
            lightbulb.Choice(name="Skip", value="skip"),
        ],
    )
    limit = lightbulb.integer(
        "limit", "Maximum channels to copy this run; leave blank for no limit",
        default=None, min_value=1,
    )
    confirm = lightbulb.boolean(
        "confirm", "False previews only. True copies or resumes this batch", default=False
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not ctx.member or not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ Administrator permission is required.", ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        allowed, reason = await legacy_migration._migration_phase_allowed(mongo)
        if not allowed:
            await ctx.respond(f"🛑 Migration unavailable: {reason}.", ephemeral=True)
            return
        try:
            source_guild_id = int(legacy_migration._numeric(self.source_guild, "source guild"))
            category_id = legacy_migration._numeric(self.category, "category", optional=True)
            if not await legacy_migration._guild_administrator(
                bot.rest, source_guild_id, int(ctx.user.id)
            ):
                raise BulkMigrationError(
                    "you must own or be an administrator of the selected source server"
                )
            source_guild = await bot.rest.fetch_guild(source_guild_id)
            guild_name = str(getattr(source_guild, "name", source_guild_id))

            if not self.confirm:
                document = await build_plan(
                    bot=bot, mongo=mongo,
                    source_guild_id=source_guild_id,
                    category_id=category_id,
                    attachments=self.attachments,
                    limit=self.limit,
                )
                await ctx.respond(
                    "🔎 **DRY RUN — nothing was written.**\n"
                    + dry_run_summary(document, guild_name=guild_name),
                    ephemeral=True,
                )
                return

            actor_name = str(
                getattr(ctx.member, "display_name", None)
                or getattr(ctx.user, "username", None)
                or ctx.user.id
            )
            document = await run_batch(
                bot=bot, mongo=mongo,
                source_guild_id=source_guild_id,
                guild_name=guild_name,
                limit=self.limit,
                actor_id=int(ctx.user.id),
                actor_name=actor_name,
            )
            counts = document.get("counts") or {}
            entries = document.get("entries") or []
            done = sum(1 for entry in entries if entry["status"] == "done")
            failed = sum(1 for entry in entries if str(entry["status"]).startswith("failed:"))
            await ctx.respond(
                f"✅ **Batch `{document.get('state')}`.** `{done}` copied, `{failed}` failed, "
                f"`{sum(v for k, v in counts.items() if k != CLASS_READY)}` skipped. "
                "Re-run with `confirm: true` to resume.",
                ephemeral=True,
            )
        except (legacy_migration.LegacyMigrationError, BulkMigrationError) as error:
            await ctx.respond(f"❌ Bulk migration stopped safely: {error}", ephemeral=True)
        except Exception as error:
            print(
                "[Tickets] legacy_bulk_migration_failed "
                f"source={self.source_guild} error={type(error).__name__}"
            )
            await ctx.respond(
                "❌ Bulk migration stopped safely after an unexpected error. Confirm again to resume.",
                ephemeral=True,
            )
