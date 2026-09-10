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
import time
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
BATCH_LEASE_RENEW_SECONDS = 15
PLAN_STALE_AFTER = timedelta(hours=24)
PREVIEW_SLEEP_SECONDS = 0.25
# Pause between copied tickets so a long confirmed run never leans on
# hikari's bucket limiter alone (each ticket is many REST calls).
RUN_SLEEP_SECONDS = 1.0
PROGRESS_EDIT_EVERY = 5
# Status writes share the console channel with normal recruiter work.  Count
# checkpoints alone can bunch several edits into one bucket, so also require a
# little wall time between routine updates.  Start and terminal states bypass
# this limit.
PROGRESS_EDIT_MIN_SECONDS = 10.0
CONSECUTIVE_FAILURE_LIMIT = 10
MAX_CHANNELS_PER_PLAN = 1000
DRY_RUN_PROBLEM_LIMIT = 15
# How often (in channels/tickets) the dry-run plan and confirmed run persist
# progress and print a `[Tickets] migrate_all_*_progress` line.
PLAN_PROGRESS_EVERY = 10
# Dry-run classification only needs the applicant mention/welcome message
# (near the start) and the decision embed (near the end); bound the history
# read to the first/last N messages instead of the full channel so a plan
# over ~160 channels does not stall on REST pagination. The confirmed run
# always re-previews with full history (no `history_limit`).
BULK_PLAN_HISTORY_LIMIT = 20

CLASS_READY = "ready"
CLASS_ALREADY_COPIED = "already_copied"
CLASS_OPEN = "open"
CLASS_NO_APPLICANT = "no_applicant"
CLASS_AMBIGUOUS_TYPE = "ambiguous_type"
CLASS_SKIPPED_OWNER_TEST = "skipped_owner_test"
CLASS_ABANDONED = "abandoned"
# The applicant's Discord account no longer exists (handoff "Owner rules" #8)
# -- never migrated.
CLASS_DELETED_APPLICANT = "deleted_applicant"
# Channel name matched the legacy category/prefix rules only incidentally
# (a commands/notes/log/etc. channel), or no applicant overwrite and no
# welcome/mention message was found at all -- never migrated.
CLASS_NOT_A_TICKET = "not_a_ticket"

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
    ticket_status: str | None = None,
) -> dict[str, Any]:
    return {
        "channel_id": int(channel_id),
        "channel_name": str(channel_name),
        "classification": classification,
        "detail": str(detail or "")[:300],
        "ticket_type": ticket_type,
        # The outcome (approved/denied/closed) a `ready` entry would import
        # with -- distinct from "status" below, which is this *run's*
        # pending/done/failed/skipped progress.
        "ticket_status": ticket_status,
        "status": "pending" if classification == CLASS_READY else "skipped",
    }


def _tally(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        counts[entry["classification"]] = counts.get(entry["classification"], 0) + 1
    return counts


async def _candidate_channels(
    rest: hikari.api.RESTClient, guild_id: int, category_id: int | None
) -> tuple[list[Any], dict[int, str]]:
    """Legacy ticket channels in scope, plus a ``parent_id -> category name`` map.

    docs/handoff-legacy-migration.md "How a channel is read": server 1's
    channel names carry no ticket numbers, so detection uses category name
    or a bare name prefix (``legacy_migration._is_legacy_ticket_channel``)
    instead of `_TICKET_NUMBER_RE`.
    """
    channels = await rest.fetch_guild_channels(guild_id)
    categories = {
        int(channel.id): str(getattr(channel, "name", "") or "")
        for channel in channels
        if getattr(channel, "type", None) == hikari.ChannelType.GUILD_CATEGORY
    }
    matched = [
        channel for channel in channels
        if getattr(channel, "type", None) == hikari.ChannelType.GUILD_TEXT
        and (category_id is None or _as_int(getattr(channel, "parent_id", 0)) == category_id)
        and legacy_migration._is_legacy_ticket_channel(
            channel, categories.get(_as_int(getattr(channel, "parent_id", 0)), "")
        )
    ]
    matched.sort(key=lambda channel: int(channel.id))
    return matched, categories


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
) -> tuple[str, str, str | None]:
    try:
        preview = await legacy_migration.preview_legacy_ticket(
            bot=bot, mongo=mongo, request=request
        )
    except legacy_migration.NotALegacyTicketChannel as error:
        return CLASS_NOT_A_TICKET, str(error), None
    except legacy_migration.SkippedOwnerTestTicket as error:
        return CLASS_SKIPPED_OWNER_TEST, str(error), None
    except legacy_migration.AbandonedLegacyTicket as error:
        return CLASS_ABANDONED, str(error), None
    except legacy_migration.LegacyTicketStillOpen as error:
        return CLASS_OPEN, str(error), None
    except legacy_migration.DeletedApplicant as error:
        return CLASS_DELETED_APPLICANT, str(error), None
    except legacy_migration.LegacyMigrationError as error:
        message = str(error)
        if "candidate Discord ID could not be detected" in message:
            return CLASS_NO_APPLICANT, message, None
        if "ticket type could not be detected" in message:
            return CLASS_AMBIGUOUS_TYPE, message, None
        return f"error:{type(error).__name__}", message, None
    except Exception as error:  # pragma: no cover - defensive, logged below
        _log.exception(
            "[Tickets] bulk_migration_preview_failed channel=%s", request.source_channel_id
        )
        return f"error:{type(error).__name__}", str(error), None
    return CLASS_READY, "", getattr(preview, "status", None)


async def build_plan(
    *,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    source_guild_id: int,
    category_id: int | None,
    attachments: str,
    limit: int | None,
    include_abandoned: bool = False,
    guild_name: str | None = None,
) -> dict[str, Any]:
    """Read-only: list, classify, and durably record a fresh plan for one guild.

    Persisted incrementally (``state: "planning"``, ``entries``/``counts``
    updated every `PLAN_PROGRESS_EVERY` channels) so a plan killed mid-scan
    (long interaction tokens die after 15 minutes) leaves a partial plan
    behind instead of losing the scan entirely; a fresh plan simply replaces
    it once classification finishes.
    """
    start_perf = time.monotonic()
    rest = bot.rest
    channels, categories = await _candidate_channels(rest, source_guild_id, category_id)
    if len(channels) > MAX_CHANNELS_PER_PLAN:
        raise BulkMigrationError(
            f"this category has {len(channels)} matching channels, above the "
            f"{MAX_CHANNELS_PER_PLAN}-channel bulk-plan limit; narrow the category and try again"
        )
    total = len(channels)
    print(f"[Tickets] migrate_all_plan_start guild={source_guild_id} candidates={total}")

    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    target_guild_id = _as_int(config.get("ticket_target_guild_id"))

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

    base_fields = {
        "_id": batch_id,
        "kind": "legacy_migration_batch",
        "schema_version": 1,
        "source_guild_id": int(source_guild_id),
        "category_id": int(category_id) if category_id else None,
        "attachments": attachments,
        "requested_limit": int(limit) if limit else None,
        "include_abandoned": bool(include_abandoned),
        "state": "planning",
        "entries": [],
        "counts": {},
        "consecutive_failures": 0,
        "created_at": (current or {}).get("created_at", now),
    }
    filt: dict[str, Any] = {"_id": batch_id}
    upsert = current is None
    if not upsert:
        filt["revision"] = int(current.get("revision", 0))
    document = await mongo.ticket_migration_batches.find_one_and_update(
        filt,
        {"$set": {**base_fields, "updated_at": now}, "$inc": {"revision": 1}},
        upsert=upsert,
        return_document=ReturnDocument.AFTER,
    )
    if document is None:
        raise BulkMigrationError("the batch plan changed concurrently; run the dry run again")

    # This is a bot-authored console message, rather than an interaction
    # webhook response.  A large scan can outlive the 15-minute interaction
    # token that started it.
    document = await _ensure_progress_message(
        bot=bot, mongo=mongo, document=document,
        text=_plan_progress_text(guild_name or str(source_guild_id), scanned=0, total=total,
                                 ready=0, problems=0),
    )
    last_progress_edit = time.monotonic()

    entries: list[dict[str, Any]] = []

    async def _checkpoint(index: int) -> None:
        nonlocal document, last_progress_edit
        if index % PLAN_PROGRESS_EVERY:
            return
        counts = _tally(entries)
        ready = counts.get(CLASS_READY, 0)
        problems = sum(value for key, value in counts.items() if key != CLASS_READY)
        print(
            f"[Tickets] migrate_all_plan_progress guild={source_guild_id} "
            f"scanned={index}/{total} ready={ready} problems={problems}"
        )
        document = await _cas_update(
            mongo, document, set_fields={"entries": entries, "counts": counts}
        )
        if time.monotonic() - last_progress_edit >= PROGRESS_EDIT_MIN_SECONDS:
            await _edit_progress_message(
                bot=bot, document=document,
                text=_plan_progress_text(
                    guild_name or str(source_guild_id), scanned=index, total=total,
                    ready=ready, problems=problems,
                ),
            )
            last_progress_edit = time.monotonic()

    for index, channel in enumerate(channels, start=1):
        channel_id = int(channel.id)
        channel_name = str(getattr(channel, "name", channel_id))
        category_name = categories.get(_as_int(getattr(channel, "parent_id", 0)), "")
        migration_id = legacy_migration._migration_id(source_guild_id, channel_id)
        existing = await mongo.ticket_migrations.find_one({"_id": migration_id})
        if existing and existing.get("state") == "complete":
            entries.append(
                _entry(channel_id, channel_name, CLASS_ALREADY_COPIED, "already copied", None)
            )
            await _checkpoint(index)
            continue

        if legacy_migration._looks_like_non_ticket_channel_name(channel_name):
            entries.append(_entry(
                channel_id, channel_name, CLASS_NOT_A_TICKET,
                "channel name matches a non-ticket pattern "
                "(commands/notes/log/rules/info/general/chat/etc.)",
                None,
            ))
            await _checkpoint(index)
            continue

        try:
            ticket_type = legacy_migration._infer_ticket_type(
                None, channel_name, None, category_name=category_name,
            )
        except legacy_migration.LegacyMigrationError as error:
            entries.append(
                _entry(channel_id, channel_name, CLASS_AMBIGUOUS_TYPE, str(error), None)
            )
            await _checkpoint(index)
            continue

        parents = _destination_for_type(config, ticket_type)
        if not target_guild_id or parents is None:
            entries.append(_entry(
                channel_id, channel_name, f"error:{BulkMigrationError.__name__}",
                f"target destination or {ticket_type.upper()} parents are not configured",
                ticket_type,
            ))
            await _checkpoint(index)
            continue

        candidate_parent_id, staff_parent_id = parents
        request = legacy_migration.LegacyMigrationRequest(
            source_guild_id=source_guild_id,
            source_channel_id=channel_id,
            target_guild_id=target_guild_id,
            candidate_parent_id=candidate_parent_id,
            staff_parent_id=staff_parent_id,
            include_abandoned=include_abandoned,
            history_limit=BULK_PLAN_HISTORY_LIMIT,
        )
        classification, detail, ticket_status = await _classify(bot=bot, mongo=mongo, request=request)
        entries.append(
            _entry(channel_id, channel_name, classification, detail, ticket_type, ticket_status)
        )
        await _checkpoint(index)
        await asyncio.sleep(PREVIEW_SLEEP_SECONDS)

    final_now = utcnow()
    counts = _tally(entries)
    document = await _cas_update(mongo, document, set_fields={
        "entries": entries,
        "counts": counts,
        "state": "planned",
        "planned_at": final_now,
    })
    ready = counts.get(CLASS_READY, 0)
    problems = sum(value for key, value in counts.items() if key != CLASS_READY)
    elapsed = time.monotonic() - start_perf
    print(
        f"[Tickets] migrate_all_plan_done guild={source_guild_id} scanned={total} "
        f"ready={ready} problems={problems} elapsed={elapsed:.1f}s"
    )
    await _edit_progress_message(
        bot=bot, document=document,
        text=(
            f"✅ Dry run complete for {guild_name or source_guild_id}: "
            f"{total}/{total} scanned, {ready} ready, {problems} not ready."
        ),
    )
    return document


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
    by_outcome: dict[str, int] = {}
    for entry in entries:
        if entry["classification"] == CLASS_READY:
            key = str(entry.get("ticket_type") or "unknown")
            by_type[key] = by_type.get(key, 0) + 1
            outcome_key = str(entry.get("ticket_status") or "unknown")
            by_outcome[outcome_key] = by_outcome.get(outcome_key, 0) + 1
    if by_type:
        lines.append(
            "**By type:** " + ", ".join(f"{key}: `{value}`" for key, value in sorted(by_type.items()))
        )
    if by_outcome:
        outcome_bits = [
            f"{'closed, no decision' if key == 'closed' else key}: `{value}`"
            for key, value in sorted(by_outcome.items())
        ]
        lines.append("**By outcome:** " + ", ".join(outcome_bits))
    other = {key: value for key, value in counts.items() if key != CLASS_READY}
    if other:
        lines.append(
            "**Not ready:** " + ", ".join(f"{key}: `{value}`" for key, value in sorted(other.items()))
        )
    abandoned = int(counts.get(CLASS_ABANDONED, 0))
    if abandoned:
        lines.append(
            f"**Abandoned (applicant never wrote):** `{abandoned}` — skipped unless "
            "`include-abandoned: true`"
        )
    not_a_ticket = int(counts.get(CLASS_NOT_A_TICKET, 0))
    if not_a_ticket:
        lines.append(f"**Not tickets:** `{not_a_ticket}` — never migrated")
    deleted_applicant = int(counts.get(CLASS_DELETED_APPLICANT, 0))
    if deleted_applicant:
        lines.append(
            f"**Applicant account deleted:** `{deleted_applicant}` — never migrated"
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


async def _console_status_link(mongo: MongoClient) -> str | None:
    """Return the configured private-console link, if its durable binding is complete."""
    try:
        hub = await mongo.ticket_setup.find_one({"_id": "ticket_console_hub"}) or {}
    except Exception as error:
        _log.warning("[Tickets] migrate_all_console_link_lookup_failed error=%s", type(error).__name__)
        return None
    guild_id = _as_int(hub.get("guild_id"))
    channel_id = _as_int(hub.get("channel_id"))
    if not guild_id or not channel_id:
        return None
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


def _plan_progress_text(
    guild_name: str, *, scanned: int, total: int, ready: int, problems: int
) -> str:
    stamp = int(utcnow().timestamp())
    return (
        f"🔎 Scanning legacy tickets from {guild_name}: {scanned}/{total} scanned, "
        f"{ready} ready, {problems} not ready · <t:{stamp}:R>"
    )


async def _edit_progress_message(
    *, bot: hikari.GatewayBot, document: Mapping[str, Any], text: str
) -> str:
    """Best-effort update for the bot-authored, durable status message.

    Progress visibility must never interrupt a migration.  In particular, this
    route must not depend on the interaction webhook that expires after 15
    minutes. The count/time throttle is owned by the callers.
    """
    channel_id = _as_int(document.get("progress_channel_id"))
    message_id = _as_int(document.get("progress_message_id"))
    if not channel_id or not message_id:
        return "unavailable"
    try:
        await bot.rest.edit_message(
            channel_id, message_id, text, user_mentions=False, role_mentions=False,
            mentions_everyone=False,
        )
    except hikari.NotFoundError as error:
        _log.warning(
            "[Tickets] migrate_all_progress_edit_failed channel=%s message=%s error=%s",
            channel_id, message_id, type(error).__name__,
        )
        return "missing"
    except Exception as error:  # status delivery is strictly observational
        _log.warning(
            "[Tickets] migrate_all_progress_edit_failed channel=%s message=%s error=%s",
            channel_id, message_id, type(error).__name__,
        )
        return "unavailable"
    return "ok"


async def _ensure_progress_message(
    *, bot: hikari.GatewayBot, mongo: MongoClient, document: dict[str, Any], text: str
) -> dict[str, Any]:
    """Create or reuse one console status message without risking batch work."""
    if _as_int(document.get("progress_channel_id")) and _as_int(document.get("progress_message_id")):
        outcome = await _edit_progress_message(bot=bot, document=document, text=text)
        if outcome == "ok":
            return document
        if outcome != "missing":
            return document
        # A deleted status message must not leave every resumed run silently
        # attempting the same dead edit. Clearing first makes the next create
        # durable; if the CAS loses, batch work still proceeds without status.
        try:
            document = await _cas_update(mongo, document, set_fields={
                "progress_channel_id": None,
                "progress_message_id": None,
            })
        except Exception as error:
            _log.warning(
                "[Tickets] migrate_all_progress_clear_failed error=%s",
                type(error).__name__,
            )
            return document

    try:
        console_channel_id = await _console_channel_id(mongo)
    except Exception as error:
        _log.warning("[Tickets] migrate_all_progress_lookup_failed error=%s", type(error).__name__)
        return document
    if not console_channel_id:
        return document
    try:
        # The console setup validates its privacy and bot permissions. Fetching
        # here also catches a stale/deleted configured channel before posting.
        channel = await bot.rest.fetch_channel(console_channel_id)
        if getattr(channel, "type", None) != hikari.ChannelType.GUILD_TEXT:
            raise RuntimeError("configured console is not a guild text channel")
        message = await bot.rest.create_message(
            console_channel_id, text, user_mentions=False, role_mentions=False,
            mentions_everyone=False,
        )
    except Exception as error:  # a status failure must not stop scan/copy work
        _log.warning(
            "[Tickets] migrate_all_progress_create_failed channel=%s error=%s",
            console_channel_id, type(error).__name__,
        )
        return document

    try:
        return await _cas_update(mongo, document, set_fields={
            "progress_channel_id": console_channel_id,
            "progress_message_id": int(message.id),
        })
    except Exception as error:  # the message is useful even if reuse is lost
        _log.warning(
            "[Tickets] migrate_all_progress_store_failed channel=%s message=%s error=%s",
            console_channel_id, int(message.id), type(error).__name__,
        )
        return document


async def _replace_deferred_status(ctx: lightbulb.Context, text: str) -> None:
    """Resolve the interaction spinner before any migration network work."""
    try:
        await ctx.interaction.edit_initial_response(content=text)
    except Exception as error:  # durable console status still carries the run
        _log.warning("[Tickets] migrate_all_initial_status_failed error=%s", type(error).__name__)


def _summary_chunks(text: str) -> list[str]:
    """Split at line boundaries when possible, within Discord's content limit.

    Count UTF-16 units conservatively so emoji-heavy names fit too.
    """
    chunks: list[str] = []
    while text:
        units = 0
        end = 0
        for char in text:
            size = 2 if ord(char) > 0xFFFF else 1
            if units + size > 2000:
                break
            units += size
            end += 1
        if end < len(text):
            newline = text.rfind("\n", 0, end)
            if newline >= 0:
                end = newline + 1
        chunks.append(text[:end])
        text = text[end:]
    return chunks


async def _post_console_summary(*, bot: hikari.GatewayBot, mongo: MongoClient, text: str) -> None:
    """Durable copy of a dry-run/run summary: a plain message in the console

    channel, unpinged, posted alongside (never instead of) the ephemeral
    reply. An interaction token dies after 15 minutes, which a bulk plan or
    run over many channels can outlive; this is what survives that.
    """
    try:
        console_channel_id = await _console_channel_id(mongo)
    except Exception as error:
        _log.warning("[Tickets] migrate_all_console_summary_lookup_failed error=%s", type(error).__name__)
        return
    if not console_channel_id:
        return
    try:
        for chunk in _summary_chunks(text):
            await bot.rest.create_message(
                console_channel_id, chunk, user_mentions=False, role_mentions=False,
                mentions_everyone=False,
            )
    except Exception as error:
        _log.warning(
            "[Tickets] migrate_all_console_summary_failed channel=%s error=%s",
            console_channel_id, type(error).__name__,
        )


async def _finish_with_summary(
    *,
    ctx: lightbulb.Context,
    bot: hikari.GatewayBot,
    mongo: MongoClient,
    source_guild_id: int,
    text: str,
) -> None:
    """Post the durable console summary, then attempt the ephemeral reply.

    A dead interaction token (``UnauthorizedError``/``NotFoundError``, e.g.
    after a long dry run) is logged and otherwise ignored: the console post
    above already carries the result.
    """
    await _post_console_summary(bot=bot, mongo=mongo, text=text)
    try:
        for chunk in _summary_chunks(text):
            await ctx.respond(chunk, ephemeral=True)
    except (hikari.NotFoundError, hikari.BadRequestError, hikari.UnauthorizedError):
        print(f"[Tickets] migrate_all_reply_lost guild={source_guild_id}")


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
    query: dict[str, Any] = {"_id": document["_id"], "revision": revision}
    if document.get("state") == "running" and document.get("lease_owner"):
        query.update({
            "lease_owner": document["lease_owner"],
            "lease_until": {"$gt": now},
        })
    updated = await mongo.ticket_migration_batches.find_one_and_update(
        query,
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


async def _batch_lease_heartbeat(
    mongo: MongoClient,
    state: dict[str, Any],
    owner: str,
    work: asyncio.Task,
    stop: asyncio.Event,
) -> None:
    """Renew one owned batch while its current ticket awaits Discord.

    This deliberately does not increment the batch revision: the main loop's
    checkpoint CAS remains authoritative. A lost lease stops the in-flight
    ticket before another source channel can begin.
    """
    while True:
        try:
            await asyncio.wait_for(stop.wait(), timeout=BATCH_LEASE_RENEW_SECONDS)
            return
        except TimeoutError:
            pass
        document = state["document"]
        try:
            updated = await _renew_batch_lease(mongo, document, owner)
        except Exception as error:
            _log.warning("[Tickets] migrate_all_lease_renewal_failed error=%s", type(error).__name__)
            state["renewal_error"] = error
            work.cancel()
            return
        if updated is None:
            state["lost"] = True
            work.cancel()
            return
        state["document"] = updated


async def _renew_batch_lease(
    mongo: MongoClient, document: dict[str, Any], owner: str
) -> dict[str, Any] | None:
    """Extend an unexpired lease held by this runner without changing revision."""
    now = utcnow()
    return await mongo.ticket_migration_batches.find_one_and_update(
        {
            "_id": document["_id"],
            "lease_owner": owner,
            "state": "running",
            "lease_until": {"$gt": now},
        },
        {"$set": {"lease_until": now + BATCH_LEASE, "updated_at": now}},
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
    start_perf = time.monotonic()
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
    include_abandoned = bool(document.get("include_abandoned", False))
    total = sum(1 for entry in entries if entry["classification"] == CLASS_READY)
    done = sum(1 for entry in entries if entry["status"] == "done")
    failed = sum(1 for entry in entries if str(entry["status"]).startswith("failed:"))
    skipped = sum(1 for entry in entries if entry["classification"] != CLASS_READY)
    consecutive_failures = int(document.get("consecutive_failures", 0))

    print(f"[Tickets] migrate_all_run_start guild={source_guild_id} total={total}")
    document = await _ensure_progress_message(
        bot=bot, mongo=mongo, document=document,
        text=_progress_text(guild_name, done=done, failed=failed, skipped=skipped, total=total),
    )
    last_progress_edit = time.monotonic()

    async def _post_progress(*, force: bool = False) -> None:
        nonlocal last_progress_edit
        if not force and time.monotonic() - last_progress_edit < PROGRESS_EDIT_MIN_SECONDS:
            return
        await _edit_progress_message(
            bot=bot, document=document,
            text=_progress_text(guild_name, done=done, failed=failed, skipped=skipped, total=total),
        )
        last_progress_edit = time.monotonic()

    config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
    processed_this_run = 0
    paused = False

    for entry in entries:
        if entry["classification"] != CLASS_READY or entry["status"] == "done":
            continue
        if limit is not None and processed_this_run >= limit:
            break

        # A failed ready entry is retryable. Remove its previous contribution
        # before recording this attempt, so a repeat failure remains one
        # failure and a later success clears the displayed failure count.
        if str(entry["status"]).startswith("failed:"):
            failed -= 1

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
                include_abandoned=include_abandoned,
            )
            async def _preview_and_migrate() -> legacy_migration.LegacyMigrationResult:
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
                return await legacy_migration.migrate_legacy_ticket(
                    bot=bot, mongo=mongo, preview=preview,
                )

            try:
                # Do not begin even a preview if the run was displaced while
                # status/config setup was in progress.
                document = await _renew_batch_lease(mongo, document, owner)
                if document is None:
                    raise BulkMigrationError(
                        "the batch lease was lost before ticket migration began"
                    )
                migration_task = asyncio.create_task(
                    _preview_and_migrate(),
                    name=f"legacy-migration:{entry['channel_id']}",
                )
                lease_state = {"document": document, "lost": False, "renewal_error": None}
                heartbeat_stop = asyncio.Event()
                heartbeat = asyncio.create_task(
                    _batch_lease_heartbeat(
                        mongo, lease_state, owner, migration_task, heartbeat_stop
                    ),
                    name=f"legacy-batch-lease:{source_guild_id}",
                )
                try:
                    result = await migration_task
                except asyncio.CancelledError:
                    if lease_state["lost"]:
                        raise BulkMigrationError(
                            "the batch lease was lost during ticket migration"
                        ) from None
                    if lease_state["renewal_error"] is not None:
                        raise BulkMigrationError(
                            "the batch lease could not be renewed during ticket migration"
                        ) from lease_state["renewal_error"]
                    raise
                finally:
                    heartbeat_stop.set()
                    await heartbeat
                if lease_state["lost"]:
                    raise BulkMigrationError("the batch lease was lost during ticket migration")
                if lease_state["renewal_error"] is not None:
                    raise BulkMigrationError(
                        "the batch lease could not be renewed during ticket migration"
                    ) from lease_state["renewal_error"]
            except legacy_migration.DeletedApplicant as error:
                entry["classification"] = CLASS_DELETED_APPLICANT
                entry["status"] = "skipped"
                entry["detail"] = str(error)
                skipped += 1
                consecutive_failures = 0
            except BulkMigrationError:
                raise
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

        print(
            f"[Tickets] migrate_all_run_progress guild={source_guild_id} "
            f"done={done} failed={failed} skipped={skipped} total={total}"
        )

        if processed_this_run % PROGRESS_EDIT_EVERY == 0:
            await _post_progress()

        if consecutive_failures >= CONSECUTIVE_FAILURE_LIMIT:
            paused = True
            document = await _cas_update(mongo, document, set_fields={"state": "paused"})
            break
        await asyncio.sleep(RUN_SLEEP_SECONDS)

    remaining_work = any(
        entry["classification"] == CLASS_READY and entry["status"] != "done"
        for entry in entries
    )
    if not paused:
        if remaining_work:
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

    terminal_state = document.get("state", "running")
    if terminal_state == "complete":
        progress_text = (
            f"✅ Legacy migration complete for {guild_name}: {done}/{total} copied, "
            f"{failed} failed, {skipped} skipped."
        )
    elif terminal_state == "paused":
        progress_text = (
            f"⏸️ Legacy migration paused for {guild_name}: {done}/{total} copied, "
            f"{failed} failed, {skipped} skipped. Re-run to resume."
        )
    else:
        progress_text = (
            f"⏸️ Legacy migration stopped for {guild_name}: {done}/{total} copied, "
            f"{failed} failed, {skipped} skipped. Re-run to resume."
        )
    await _edit_progress_message(bot=bot, document=document, text=progress_text)
    elapsed = time.monotonic() - start_perf
    print(
        f"[Tickets] migrate_all_run_done guild={source_guild_id} done={done} "
        f"failed={failed} skipped={skipped} total={total} elapsed={elapsed:.1f}s"
    )
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
    include_abandoned = lightbulb.boolean(
        "include-abandoned",
        "Import abandoned tickets (applicant never wrote) as closed instead of skipping them",
        default=False,
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
        await _replace_deferred_status(
            ctx,
            "🔎 Preparing bulk migration work. Progress will appear in the ticket console.",
        )
        allowed, reason = await legacy_migration._migration_phase_allowed(mongo)
        if not allowed:
            await _finish_with_summary(
                ctx=ctx, bot=bot, mongo=mongo, source_guild_id=0,
                text=f"🛑 Migration unavailable: {reason}.",
            )
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
            console_link = await _console_status_link(mongo)
            if console_link:
                await _replace_deferred_status(
                    ctx,
                    "🔎 Starting bulk migration. Follow progress in the "
                    f"[ticket console]({console_link}).",
                )

            if not self.confirm:
                document = await build_plan(
                    bot=bot, mongo=mongo,
                    source_guild_id=source_guild_id,
                    category_id=category_id,
                    attachments=self.attachments,
                    limit=self.limit,
                    include_abandoned=self.include_abandoned,
                    guild_name=guild_name,
                )
                await _finish_with_summary(
                    ctx=ctx, bot=bot, mongo=mongo, source_guild_id=source_guild_id,
                    text=(
                        "🔎 **DRY RUN — nothing was written.**\n"
                        + dry_run_summary(document, guild_name=guild_name)
                    ),
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
            await _finish_with_summary(
                ctx=ctx, bot=bot, mongo=mongo, source_guild_id=source_guild_id,
                text=(
                    f"✅ **Batch `{document.get('state')}`.** `{done}` copied, `{failed}` failed, "
                    f"`{sum(v for k, v in counts.items() if k != CLASS_READY)}` skipped. "
                    "Re-run with `confirm: true` to resume."
                ),
            )
        except (legacy_migration.LegacyMigrationError, BulkMigrationError) as error:
            source_guild_id = _as_int(self.source_guild)
            await _finish_with_summary(
                ctx=ctx, bot=bot, mongo=mongo,
                source_guild_id=source_guild_id,
                text=f"❌ Bulk migration stopped safely: {error}",
            )
        except Exception as error:
            print(
                "[Tickets] legacy_bulk_migration_failed "
                f"source={self.source_guild} error={type(error).__name__}"
            )
            source_guild_id = _as_int(self.source_guild)
            await _finish_with_summary(
                ctx=ctx, bot=bot, mongo=mongo,
                source_guild_id=source_guild_id,
                text=(
                    "❌ Bulk migration stopped safely after an unexpected error. "
                    "Confirm again to resume."
                ),
            )
