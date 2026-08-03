"""One-off migration of ticket documents out of button_store.

Copies `{"type": "ticket"}` documents from `button_store` into the dedicated
`tickets` collection. NON-DESTRUCTIVE: nothing is ever deleted from button_store,
so a rollback is a config flip rather than a data restore. Idempotent - the copy
is an upsert keyed on the unchanged `_id`, safe to re-run any number of times.

Read docs/ticket-data-model.md before changing anything here.
"""

from collections import Counter, defaultdict

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands.tickets import loader, ticket
from extensions.commands.tickets import store
from extensions.commands.tickets.manage import safe_text_content
from utils.constants import BLUE_ACCENT, RED_ACCENT
from utils.mongo import MongoClient

# Reconciled by Ruggie on 2026-08-02, after ghost cleanup. Shown alongside the
# live counts so drift is visible at a glance. NOT a gate: a ticket opened
# tonight legitimately moves these, and blocking on that would make the command
# unusable the moment anyone used the bot.
BASELINE_TOTAL = 361
BASELINE_BY_STATUS = {"approved": 64, "closed": 1, "denied": 273, "open": 23}


def _transform(doc: dict) -> dict:
    """button_store ticket document -> tickets document.

    Purely additive. Every original field keeps its name and value, so the
    inverse is a $unset of two keys and no information is destroyed.
    """
    out = dict(doc)
    out["schema_version"] = 2
    # Explicit rather than implied. The reconciliation commands in manage.py
    # already query {"venue": {"$ne": "thread"}}, which today holds only because
    # the field is absent - stating it turns an accident into a guarantee.
    out["venue"] = "channel"
    # Ids have been stored as both int and str across schema versions (see
    # store.as_int). Coerce, or the unique index below cannot do its job:
    # 1234 and "1234" are distinct keys and both would be permitted.
    coerced = store.as_int(out.get("channel_id"))
    if coerced:
        out["channel_id"] = coerced
    return out


def _collisions(docs: list[dict]) -> dict[int, list[str]]:
    """Coerced channel_id -> the _ids claiming it, for any claimed more than once.

    This is the step most likely to surface a real problem, and it runs in the
    dry run so it can stop the migration before anything is written. If it fires,
    STOP: two ticket documents pointing at one channel is a data error, and
    dropping the uniqueness to get past it would bury it permanently.
    """
    by_channel: dict[int, list[str]] = defaultdict(list)
    for doc in docs:
        by_channel[store.as_int(doc.get("channel_id"))].append(str(doc.get("_id")))
    return {cid: ids for cid, ids in by_channel.items() if len(ids) > 1}


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

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if not ctx.member.permissions & hikari.Permissions.ADMINISTRATOR:
            await ctx.respond("❌ You need Administrator permissions to use this command!",
                              ephemeral=True)
            return

        await ctx.defer(ephemeral=True)

        source = await mongo.button_store.find(store.TICKET_FILTER).to_list(length=None)
        src_counts = dict(Counter(d.get("status") or "(missing)" for d in source))
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

        # --- the blocking check, before any write ---------------------------
        collisions = _collisions(source)
        if collisions:
            rows = [
                f"• `channel_id={cid}` claimed by {len(ids)}: " + ", ".join(f"`{i}`" for i in ids)
                for cid, ids in list(collisions.items())[:10]
            ]
            body = "\n".join([
                *header,
                "",
                "🛑 **STOPPED — nothing was written.**",
                "",
                f"**{len(collisions)} channel_id value(s)** are claimed by more than one "
                f"ticket document once coerced to int:",
                *rows,
                "",
                "The unique index on `channel_id` cannot be created while this holds, and "
                "it must NOT be dropped to get past it — two documents pointing at one "
                "channel is a real data error, and one of them is wrong. Investigate "
                "before re-running.",
            ])
            await ctx.respond(components=_panel("🛑 **Ticket Store Migration**", body, RED_ACCENT, "assets/Red_Footer.png"))
            return

        if not self.confirm:
            body = "\n".join([
                *header,
                "",
                "**DRY RUN — nothing was written.**",
                "",
                f"Would upsert **{len(source)}** document(s) into `tickets`, adding "
                f"`schema_version: 2` and `venue: \"channel\"` and coercing `channel_id` "
                f"to int. No collisions detected.",
                "",
                "Nothing is deleted from `button_store`. Re-run with `confirm: true` to "
                "write. **Snapshot the collection first.**",
            ])
            await ctx.respond(components=_panel("🧰 **Ticket Store Migration**", body, BLUE_ACCENT, "assets/Blue_Footer.png"))
            return

        # --- write ------------------------------------------------------------
        copied = 0
        for doc in source:
            await mongo.tickets.replace_one({"_id": doc["_id"]}, _transform(doc), upsert=True)
            copied += 1

        index_notes = []
        try:
            await mongo.tickets.create_index(
                [("channel_id", 1)], unique=True, name="channel_unique")
            index_notes.append("✅ `channel_unique` (unique on channel_id)")
        except Exception as exc:
            index_notes.append(f"❌ `channel_unique` failed: {str(exc)[:200]}")
        try:
            await mongo.tickets.create_index(
                [("status", 1), ("created_at", -1)], name="status_created")
            index_notes.append("✅ `status_created`")
        except Exception as exc:
            index_notes.append(f"❌ `status_created` failed: {str(exc)[:200]}")

        after = await store.status_counts(mongo.tickets)
        after_total = sum(after.values())
        divergence = [
            f"`{k}`: button_store {src_counts.get(k, 0)} vs tickets {after.get(k, 0)}"
            for k in sorted(set(src_counts) | set(after))
            if src_counts.get(k, 0) != after.get(k, 0)
        ]

        body = "\n".join([
            f"✅ **Upserted {copied} document(s)** into `tickets`.",
            "",
            _count_lines("button_store (type=ticket)", len(source), src_counts),
            _count_lines("tickets", after_total, after),
            "",
            "**Divergence:** " + ("none ✅" if not divergence else "⚠️ " + "; ".join(divergence)),
            "",
            "**Indexes**",
            *(f"• {n}" for n in index_notes),
            "",
            f"Reads still come from **`{await store.active_store(mongo)}`**. Flip "
            "`ticket_store` to `\"tickets\"` on the `ticket_setup` config document when "
            "the counts above look right. Nothing was deleted from `button_store`.",
        ])
        await ctx.respond(components=_panel("🧰 **Ticket Store Migration**", body, BLUE_ACCENT, "assets/Blue_Footer.png"))
