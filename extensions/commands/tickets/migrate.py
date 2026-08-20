"""One-off migration of ticket documents out of button_store.

Copies `{"type": "ticket"}` documents from `button_store` into the dedicated
`tickets` collection. NON-DESTRUCTIVE: nothing is ever deleted from button_store,
so a rollback is a config flip rather than a data restore. Idempotent - the copy
is an upsert keyed on the unchanged `_id`, safe to re-run any number of times.

Read docs/ticket-data-model.md before changing anything here.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands.tickets import loader, perms, schema, store, ticket
from utils.constants import BLUE_ACCENT, RED_ACCENT
from utils.mongo import MongoClient

# Reconciled by Ruggie on 2026-08-02, after ghost cleanup. Shown alongside the
# live counts so drift is visible at a glance. NOT a gate: a ticket opened
# tonight legitimately moves these, and blocking on that would make the command
# unusable the moment anyone used the bot.
BASELINE_TOTAL = 361
BASELINE_BY_STATUS = {"approved": 64, "closed": 1, "denied": 273, "open": 23}
MAX_TEXT_CONTENT = 4000
TRUNCATION_HEADROOM = 120


class ClosedClassificationError(ValueError):
    """A legacy ``closed`` row has not been classified explicitly and safely."""


class OpenLegacyTicketsError(ValueError):
    """Canonical activation would strand active channel-era tickets."""


class CanonicalDatasetMismatchError(RuntimeError):
    """Canonical destination is not the exact normalized source dataset."""


def ensure_exact_canonical_dataset(
    expected_documents: list[dict], observed_documents: list[dict]
) -> None:
    """Fail closed unless canonical identity and content exactly match source."""
    expected = {document.get("_id"): document for document in expected_documents}
    observed = {document.get("_id"): document for document in observed_documents}
    if len(expected) != len(expected_documents) or None in expected:
        raise CanonicalDatasetMismatchError(
            "Normalized source contains a missing or duplicate ticket identity."
        )
    if len(observed) != len(observed_documents) or None in observed:
        raise CanonicalDatasetMismatchError(
            "Canonical destination contains a missing or duplicate ticket identity."
        )

    missing = sorted(set(expected) - set(observed), key=str)
    unexpected = sorted(set(observed) - set(expected), key=str)
    divergent = sorted(
        (
            ticket_id
            for ticket_id in set(expected) & set(observed)
            if observed[ticket_id] != expected[ticket_id]
        ),
        key=str,
    )
    if not (missing or unexpected or divergent):
        return

    def summary(label: str, ticket_ids: list) -> str:
        shown = ", ".join(f"`{ticket_id}`" for ticket_id in ticket_ids[:10])
        more = f" and {len(ticket_ids) - 10} more" if len(ticket_ids) > 10 else ""
        return f"{label} ({len(ticket_ids)}): {shown}{more}"

    details = []
    if missing:
        details.append(summary("missing", missing))
    if unexpected:
        details.append(summary("unexpected", unexpected))
    if divergent:
        details.append(summary("divergent", divergent))
    raise CanonicalDatasetMismatchError(
        "Canonical destination does not exactly match the normalized source dataset: "
        + "; ".join(details)
        + ". Activation remains disabled; no destination ticket was deleted."
    )


def _bson_stable(value):
    """Mirror BSON's millisecond datetime precision before exact verification."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.replace(microsecond=(value.microsecond // 1000) * 1000)
    if isinstance(value, dict):
        return {key: _bson_stable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_bson_stable(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_bson_stable(item) for item in value)
    return value


def _matching_closed_classification(document: dict, target: str) -> bool:
    return any(
        item.get("event") == "legacy_closed_classified"
        and item.get("from") == "closed"
        and item.get("to") == target
        for item in document.get("audit") or []
        if isinstance(item, dict)
    )


def ensure_no_open_legacy_tickets(documents: list[dict]) -> None:
    blockers = [
        str(document.get("_id"))
        for document in documents
        if document.get("status") == "open" and document.get("venue") != "thread"
    ]
    if not blockers:
        return
    shown = ", ".join(f"`{ticket_id}`" for ticket_id in blockers[:10])
    more = f" and {len(blockers) - 10} more" if len(blockers) > 10 else ""
    raise OpenLegacyTicketsError(
        f"Canonical activation is blocked by {len(blockers)} open legacy-channel "
        f"ticket(s): {shown}{more}. Resolve each source ticket explicitly to "
        "`approved` or `denied`, then re-run the dry run. This command never "
        "infers a terminal outcome."
    )


def prepare_source_documents(
    source: list[dict],
    *,
    closed_ticket_id: str | None,
    closed_status: str | None,
    actor_id,
    actor_name: str,
    now: datetime,
) -> tuple[list[dict], dict | None]:
    """Apply one explicit, audited closed-row classification in memory.

    The returned classification carries ``needs_source_write`` so the caller can
    durably CAS the exact legacy row before copying or activating the new store.
    """
    now = _bson_stable(now)
    ticket_id = str(closed_ticket_id or "").strip() or None
    target = str(closed_status or "").strip().casefold() or None
    if bool(ticket_id) != bool(target):
        raise ClosedClassificationError(
            "Provide both `closed-ticket-id` and `closed-status`, or neither."
        )
    if target is not None and target not in schema.TERMINAL_STATUSES:
        raise ClosedClassificationError(
            "`closed-status` must be exactly `approved` or `denied`."
        )

    prepared = [deepcopy(document) for document in source]
    closed_ids = [
        str(document.get("_id"))
        for document in prepared
        if str(document.get("status") or "").strip().casefold() == "closed"
    ]
    if ticket_id is None:
        if closed_ids:
            ids = ", ".join(f"`{value}`" for value in closed_ids)
            raise ClosedClassificationError(
                f"Legacy closed ticket(s) require an explicit approved/denied "
                f"classification: {ids}. Re-run with `closed-ticket-id` and "
                "`closed-status`."
            )
        return prepared, None

    matches = [document for document in prepared if str(document.get("_id")) == ticket_id]
    if len(matches) != 1:
        raise ClosedClassificationError(
            f"`closed-ticket-id` `{ticket_id}` does not identify exactly one source ticket."
        )
    document = matches[0]
    current = str(document.get("status") or "").strip().casefold()
    needs_source_write = False
    if current == "closed":
        revision = max(0, int(document.get("rev") or 0))
        actor = schema.snowflake(actor_id, field="actor_id")
        name = str(actor_name or "").strip() or str(actor)
        document["status"] = target
        document["rev"] = revision + 1
        document["updated_at"] = now
        document.setdefault("audit", []).append({
            "event": "legacy_closed_classified",
            "at": now,
            "actor": actor,
            "actor_name": name,
            "from": "closed",
            "to": target,
            "rev_before": revision,
            "rev_after": revision + 1,
        })
        needs_source_write = True
    elif current == target and _matching_closed_classification(document, target):
        # A retry after a successful write or lost acknowledgement is safe.
        pass
    else:
        raise ClosedClassificationError(
            f"Ticket `{ticket_id}` is `{current or '(missing)'}`, not an unclassified "
            f"`closed` row. Nothing was changed."
        )

    remaining = [
        str(item.get("_id"))
        for item in prepared
        if str(item.get("status") or "").strip().casefold() == "closed"
    ]
    if remaining:
        ids = ", ".join(f"`{value}`" for value in remaining)
        raise ClosedClassificationError(
            f"Additional legacy closed ticket(s) still require classification: {ids}."
        )
    return prepared, {
        "ticket_id": ticket_id,
        "status": target,
        "document": document,
        "needs_source_write": needs_source_write,
    }


async def persist_closed_classification(mongo: MongoClient, classification: dict) -> None:
    """CAS the operator's explicit classification into the preserved source store."""
    if not classification.get("needs_source_write"):
        return
    document = classification["document"]
    ticket_id = classification["ticket_id"]
    target = classification["status"]
    result = await mongo.button_store.replace_one(
        {"_id": document["_id"], "type": "ticket", "status": "closed"},
        document,
        upsert=False,
    )
    if result.matched_count:
        return
    current = await mongo.button_store.find_one({"_id": document["_id"], "type": "ticket"})
    if (
        current is not None
        and str(current.get("status") or "").casefold() == target
        and _matching_closed_classification(current, target)
    ):
        return
    raise ClosedClassificationError(
        f"Ticket `{ticket_id}` changed while it was being classified. Re-run the dry run."
    )


async def activate_canonical_store(
    mongo: MongoClient,
    *,
    expected_documents: list[dict],
    actor_id,
    actor_name: str,
    now: datetime,
) -> None:
    """Activate only after an immediate exact canonical dataset verification."""
    observed_documents = await mongo.tickets.find(store.TICKET_FILTER).to_list(length=None)
    ensure_exact_canonical_dataset(expected_documents, observed_documents)
    now = _bson_stable(now)
    update = {
        "$set": {
            "ticket_store": store.STORE_TICKETS,
            "ticket_store_activation_version": store.CANONICAL_ACTIVATION_VERSION,
            "ticket_store_activated_at": now,
            "ticket_store_activated_by": schema.snowflake(actor_id, field="actor_id"),
            "ticket_store_activated_by_name": str(actor_name or "").strip(),
        }
    }
    try:
        await mongo.ticket_setup.update_one({"_id": "config"}, update, upsert=True)
    except Exception:
        if await store.active_store(mongo) != store.STORE_TICKETS:
            raise
    if await store.active_store(mongo) != store.STORE_TICKETS:
        raise RuntimeError("canonical ticket store activation was not readable after commit")


def safe_text_content(body: str, empty_fallback: str) -> str:
    """Clamp migration output to Discord's text-display limits."""
    body = (body or "").strip()
    if not body:
        return empty_fallback
    if len(body) <= MAX_TEXT_CONTENT:
        return body
    lines = body.split("\n")
    kept: list[str] = []
    used = 0
    budget = MAX_TEXT_CONTENT - TRUNCATION_HEADROOM
    for line in lines:
        if used + len(line) + 1 > budget:
            break
        kept.append(line)
        used += len(line) + 1
    hidden = len(lines) - len(kept)
    return "\n".join(kept) + f"\n\n-# …truncated, {hidden} more line(s) not shown."


def _transform(doc: dict) -> dict:
    """button_store ticket document -> canonical, searchable ticket document."""
    return _bson_stable(store.normalize_ticket_document(doc))


def _panel(title: str, body: str, accent, footer: str) -> list:
    return [
        Container(
            accent_color=accent,
            components=[
                Text(content=title),
                Separator(divider=True),
                Text(content=safe_text_content(body, "Nothing to report.")),
                Media(items=[MediaItem(media=footer)]),
            ],
        )
    ]


def _count_lines(label: str, total: int, by_status: dict[str, int]) -> str:
    parts = ", ".join(f"`{k}`={v}" for k, v in sorted(by_status.items()))
    return f"• {label}: **{total}** — {parts or '(none)'}"


def _status_counts(documents: list[dict]) -> dict[str, int]:
    return dict(Counter(document.get("status") or "(missing)" for document in documents))


@ticket.register()
class MigrateStore(
    lightbulb.SlashCommand,
    name="migrate-store",
    description="Copy ticket documents from button_store into the tickets collection (Admin only)",
):
    confirm = lightbulb.boolean(
        "confirm",
        "Actually write the copy. Omit or set false for a dry run.",
        default=False,
    )
    closed_ticket_id = lightbulb.string(
        "closed-ticket-id",
        "Exact source ticket ID to classify when its stored status is closed",
        default=None,
    )
    closed_status = lightbulb.string(
        "closed-status",
        "Explicit classification for the selected closed source ticket",
        default=None,
        choices=[
            lightbulb.Choice(name="Approved", value="approved"),
            lightbulb.Choice(name="Denied", value="denied"),
        ],
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if not await perms.is_target_admin(ctx.member, mongo):
            await ctx.respond(
                "❌ Administrator permission is required in the configured ticket guild.",
                ephemeral=True,
            )
            return

        source = await mongo.button_store.find(store.TICKET_FILTER).to_list(length=None)
        src_counts = _status_counts(source)
        dst_counts = await store.status_counts(mongo.tickets)
        dst_total = sum(dst_counts.values())

        drift = [
            f"`{k}` expected {BASELINE_BY_STATUS.get(k, 0)}, found {src_counts.get(k, 0)}"
            for k in sorted(set(BASELINE_BY_STATUS) | set(src_counts))
            if BASELINE_BY_STATUS.get(k, 0) != src_counts.get(k, 0)
        ]

        header = [
            _count_lines("button_store (type=ticket)", len(source), src_counts),
            _count_lines("tickets", dst_total, dst_counts),
            "",
            f"Baseline at plan time (2026-08-02): **{BASELINE_TOTAL}** — "
            + ", ".join(f"`{k}`={v}" for k, v in sorted(BASELINE_BY_STATUS.items())),
        ]
        if drift:
            header += ["", "⚠️ **Drift from baseline** (expected if tickets have moved since):",
                       *(f"• {d}" for d in drift)]

        actor_name = str(
            getattr(ctx.member, "display_name", None)
            or getattr(ctx.user, "username", None)
            or ctx.user.id
        )
        migration_time = store.utcnow()
        try:
            prepared_source, classification = prepare_source_documents(
                source,
                closed_ticket_id=self.closed_ticket_id,
                closed_status=self.closed_status,
                actor_id=ctx.user.id,
                actor_name=actor_name,
                now=migration_time,
            )
            normalized_source = [_transform(document) for document in prepared_source]
            ensure_no_open_legacy_tickets(normalized_source)
        except (ClosedClassificationError, schema.TicketSchemaError, ValueError) as exc:
            body = "\n".join([
                *header,
                "",
                "🛑 **STOPPED — nothing was written.**",
                "",
                str(exc),
            ])
            await ctx.respond(components=_panel(
                "🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"
            ))
            return

        # Preflight the exact post-migration dataset before the first write.
        destination = await mongo.tickets.find(store.TICKET_FILTER).to_list(length=None)
        would_be = {str(doc.get("_id")): doc for doc in destination}
        for document in normalized_source:
            would_be[str(document.get("_id"))] = document
        collisions = store.index_conflicts_for_documents(would_be.values())
        if collisions:
            rows = []
            for kind, entries in list(collisions.items())[:10]:
                for entry in entries[:5]:
                    rows.append(f"• `{kind}`: `{entry}`")
            body = "\n".join([
                *header,
                "",
                "🛑 **STOPPED — nothing was written.**",
                "",
                "Canonical unique-index conflicts were found:",
                *rows,
                "",
                "Repair the source records before re-running. Do not weaken a unique index.",
            ])
            await ctx.respond(components=_panel("🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"))
            return

        if not self.confirm:
            classification_lines = []
            if classification is not None:
                classification_lines = [
                    "",
                    f"Would explicitly classify `{classification['ticket_id']}` as "
                    f"`{classification['status']}` with an audit record.",
                ]
            body = "\n".join([
                *header,
                "",
                "**DRY RUN — nothing was written.**",
                *classification_lines,
                "",
                f"Would upsert **{len(source)}** canonical schema-v3 document(s) into "
                "`tickets`, normalizing mixed IDs, search fields, revision/audit fields, "
                "and removing obsolete claim fields. No index conflicts detected. The "
                "indexed `tickets` store would then become active automatically.",
                "",
                "Nothing is deleted from `button_store`. Re-run with `confirm: true` to "
                "write. **Snapshot the collection first.**",
            ])
            await ctx.respond(components=_panel("🧰 **Ticket Store Migration**", body, BLUE_ACCENT, "assets/Blue_Footer.png"))
            return

        # --- write ------------------------------------------------------------
        try:
            if classification is not None:
                await persist_closed_classification(mongo, classification)
        except Exception as exc:
            body = "\n".join([
                *header,
                "",
                "🛑 **STOPPED — canonical storage was not activated.**",
                "",
                f"Closed-ticket classification failed: {str(exc)[:500]}",
            ])
            await ctx.respond(components=_panel(
                "🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"
            ))
            return

        copied = 0
        try:
            for document in normalized_source:
                await mongo.tickets.replace_one(
                    {"_id": document["_id"]}, document, upsert=True
                )
                copied += 1
        except Exception as exc:
            body = "\n".join([
                f"🛑 **Copy stopped after {copied} document(s).**",
                "",
                f"`tickets` write failed: {str(exc)[:500]}",
                "",
                "Canonical storage was not activated. Re-run the dry run; completed "
                "upserts are idempotent.",
            ])
            await ctx.respond(components=_panel(
                "🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"
            ))
            return

        try:
            names = await store.ensure_indexes(mongo)
        except Exception as exc:
            body = "\n".join([
                f"🛑 **Copied {copied} document(s), but index installation failed.**",
                "",
                str(exc)[:500],
                "",
                "Canonical storage was not activated. Repair the index failure and re-run; "
                "the copy is idempotent.",
            ])
            await ctx.respond(components=_panel(
                "🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"
            ))
            return

        # Refuse the switch if a source write raced the snapshot or a copied
        # document is not readable exactly as prepared. Re-running is safe.
        current_source = await mongo.button_store.find(store.TICKET_FILTER).to_list(length=None)
        expected_source = {document["_id"]: document for document in prepared_source}
        observed_source = {document["_id"]: document for document in current_source}
        copy_verified = True
        for document in normalized_source:
            observed = await mongo.tickets.find_one({"_id": document["_id"]})
            if observed != document:
                copy_verified = False
                break
        if observed_source != expected_source or not copy_verified:
            body = "\n".join([
                "🛑 **Copy verification detected concurrent or incomplete changes.**",
                "",
                "Canonical storage was not activated. Re-run the dry run; existing upserts "
                "are idempotent.",
            ])
            await ctx.respond(components=_panel(
                "🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"
            ))
            return

        try:
            await activate_canonical_store(
                mongo,
                expected_documents=normalized_source,
                actor_id=ctx.user.id,
                actor_name=actor_name,
                now=store.utcnow(),
            )
        except Exception as exc:
            body = "\n".join([
                "🛑 **Copy and indexes passed, but activation failed.**",
                "",
                str(exc)[:500],
                "",
                "No manual database change is required. Re-run this command with the same "
                "options; it is idempotent.",
            ])
            await ctx.respond(components=_panel(
                "🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"
            ))
            return

        after = await store.status_counts(mongo.tickets)
        after_total = sum(after.values())
        final_src_counts = _status_counts(current_source)
        divergence = [
            f"`{k}`: button_store {final_src_counts.get(k, 0)} vs tickets {after.get(k, 0)}"
            for k in sorted(set(final_src_counts) | set(after))
            if final_src_counts.get(k, 0) != after.get(k, 0)
        ]

        body = "\n".join([
            f"✅ **Upserted {copied} document(s)** into `tickets`.",
            "",
            _count_lines(
                "button_store (type=ticket)", len(current_source), final_src_counts
            ),
            _count_lines("tickets", after_total, after),
            "",
            "**Divergence:** " + ("none ✅" if not divergence else "⚠️ " + "; ".join(divergence)),
            "",
            "**Indexes**",
            *(f"• ✅ `{name}`" for name in names),
            "",
            f"Canonical reads and writes are now active on "
            f"**`{await store.active_store(mongo)}`**. Nothing was deleted from "
            "`button_store`.",
        ])
        await ctx.respond(components=_panel("🧰 **Ticket Store Migration**", body, BLUE_ACCENT, "assets/Blue_Footer.png"))
