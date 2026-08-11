"""Bulk-upload the bundled troop artwork as application emojis.

Application emojis belong to the bot, not to a guild, so one upload works in
every server the bot is in.  The art is the checksum-pinned set already in
`assets/cards/`, credited in `assets/cards/NOTICE.md`.

Two independent gates stop this from touching an emoji it did not create:
every managed emoji is named `troop_<slug>`, and a delete additionally
requires a matching row in the `emoji_registry` collection.  A name match
alone is never enough, so the hand-curated emojis behind `utils/emoji.py`
cannot be replaced by a bug here.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb
from PIL import Image

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)

from utils import troop_emoji
from utils.card_board import CARD_ARTWORK_DIR
from utils.cards import CARDS
from utils.constants import GREEN_ACCENT, RED_ACCENT
from utils.mongo import MongoClient

OWNER_ID = 505227988229554179

# Discord publishes no numeric limit for POST /applications/{id}/emojis, so
# self-throttling is the only guard. main.py sets max_rate_limit=120.0, which
# is what raises RateLimitTooLongError instead of hanging; max_retries=1 covers
# connection errors and 5xx, NOT 429s.
CADENCE_SECONDS = 1.6
# Interaction tokens last 15 minutes. Stop cleanly before that and let a re-run
# resume rather than dying on an expired token.
RUN_BUDGET = timedelta(minutes=12)
EMOJI_EDGE = 128
MAX_EMOJI_BYTES = 256 * 1024
PROGRESS_EVERY = 10

loader = lightbulb.Loader()


def _payload(path) -> bytes:
    """Normalize one bundled icon into a Discord-acceptable emoji image.

    Discord accepts PNG, JPEG and GIF; the bundled art is WebP, so it is always
    re-encoded. 128 is the size Discord stores, so sending more is waste.
    """
    with Image.open(path) as image:
        image.load()
        icon = image.convert("RGBA")
    icon.thumbnail((EMOJI_EDGE, EMOJI_EDGE), Image.LANCZOS)
    buffer = io.BytesIO()
    icon.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def collect_sources() -> dict[str, bytes]:
    """Every catalog slug that has bundled artwork, as upload-ready bytes."""
    sources: dict[str, bytes] = {}
    for card in CARDS:
        path = CARD_ARTWORK_DIR / f"{card.id}.webp"
        if not path.is_file():
            continue
        try:
            data = _payload(path)
        except (OSError, ValueError):
            continue
        if len(data) <= MAX_EMOJI_BYTES:
            sources[card.id] = data
    return sources


async def _load_registry(mongo: MongoClient) -> dict[str, dict]:
    rows = await mongo.emoji_registry.find({"kind": "troop"}).to_list(length=None)
    return {str(row.get("slug")): row for row in rows if row.get("slug")}


async def refresh_cache(mongo: MongoClient) -> int:
    rows = await mongo.emoji_registry.find({"kind": "troop"}).to_list(length=None)
    return troop_emoji.prime(rows)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def _prime_troop_emojis(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    try:
        loaded = await refresh_cache(mongo)
    except Exception as exc:  # noqa: BLE001 - never block startup on a cache
        print(f"[EmojiSync] could not prime troop emojis: {exc}")
        return
    print(f"[EmojiSync] primed {loaded} troop emojis")


def _panel(title: str, body: str, *, ok: bool = True) -> list[Container]:
    return [Container(
        accent_color=GREEN_ACCENT if ok else RED_ACCENT,
        components=[Text(content=f"## {title}\n{body}")],
    )]


@loader.command
class EmojiSync(
    lightbulb.SlashCommand,
    name="emoji-sync",
    description="Upload the bundled troop artwork as application emojis (owner only)",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
):
    dry_run = lightbulb.boolean(
        "dry-run",
        "Report what would change without uploading anything",
        default=True,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        if ctx.user.id != OWNER_ID:
            await ctx.respond(
                components=_panel(
                    "Permission denied",
                    "This command is restricted to the bot owner.",
                    ok=False,
                ),
                ephemeral=True,
            )
            return

        await ctx.defer(ephemeral=True)
        sources = collect_sources()
        if not sources:
            await ctx.respond(components=_panel(
                "No artwork found",
                f"Nothing usable in `{CARD_ARTWORK_DIR}`.",
                ok=False,
            ))
            return

        application = await bot.rest.fetch_my_user()
        try:
            live_list = await bot.rest.fetch_application_emojis(application.id)
        except hikari.ForbiddenError:
            await ctx.respond(components=_panel(
                "Missing permission",
                "The bot cannot manage its own application emojis.",
                ok=False,
            ))
            return
        live = {emoji.name.lower(): emoji for emoji in live_list}
        registry = await _load_registry(mongo)

        planned: list[tuple[str, bytes, str, object, dict | None]] = []
        skipped = 0
        foreign: list[str] = []
        for slug in sorted(sources):
            data = sources[slug]
            name = troop_emoji.managed_name(slug)
            digest = hashlib.sha256(data).hexdigest()
            current = live.get(name.lower())
            record = registry.get(slug)
            if (
                current is not None
                and record is not None
                and record.get("digest") == digest
                and str(record.get("emoji_id")) == str(current.id)
            ):
                skipped += 1
                continue
            if current is not None and record is None:
                # Right name, but this bot never recorded creating it. Refuse.
                foreign.append(name)
                continue
            planned.append((slug, data, digest, current, record))

        if self.dry_run:
            lines = [
                f"**{len(sources)}** troop icons found in the bundled set.",
                f"**{len(planned)}** would be uploaded or replaced.",
                f"**{skipped}** already match and would be skipped.",
                f"Existing application emojis: **{len(live_list)}** of 2000.",
                f"Estimated run time: about **{int(len(planned) * CADENCE_SECONDS)}s**.",
            ]
            if foreign:
                lines.append(
                    f"\n**{len(foreign)}** name(s) already exist that this bot "
                    f"did not create and will NOT be touched: "
                    + ", ".join(f"`{n}`" for n in foreign[:10])
                )
            lines.append("\nRe-run with `dry-run: False` to apply.")
            await ctx.respond(components=_panel(
                "Emoji sync preview", "\n".join(lines)
            ))
            return

        created = replaced = failed = 0
        stopped: str | None = None
        started = datetime.now(timezone.utc)

        for index, (slug, data, digest, current, _record) in enumerate(planned, 1):
            if datetime.now(timezone.utc) - started > RUN_BUDGET:
                stopped = "Twelve-minute budget reached. Re-run to resume."
                break
            name = troop_emoji.managed_name(slug)
            try:
                if current is not None:
                    # There is no image parameter on edit_application_emoji, so
                    # changing art means delete then create.
                    await bot.rest.delete_application_emoji(
                        application=application.id, emoji=current.id
                    )
                    await asyncio.sleep(CADENCE_SECONDS)
                emoji = await bot.rest.create_application_emoji(
                    application=application.id, name=name, image=data
                )
            except hikari.RateLimitTooLongError as exc:
                stopped = (
                    f"Discord asked for a {exc.retry_after:.0f}s wait. "
                    "Re-run to resume; finished emojis are skipped."
                )
                break
            except (
                hikari.BadRequestError,
                hikari.ForbiddenError,
                hikari.InternalServerError,
            ) as exc:
                failed += 1
                print(f"[EmojiSync] {slug}: {type(exc).__name__}: {exc}")
                await asyncio.sleep(CADENCE_SECONDS)
                continue

            await mongo.emoji_registry.update_one(
                {"_id": f"troop:{slug}"},
                {"$set": {
                    "kind": "troop",
                    "slug": slug,
                    "name": name,
                    "emoji_id": int(emoji.id),
                    "digest": digest,
                    "updated_at": datetime.now(timezone.utc),
                }},
                upsert=True,
            )
            if current is not None:
                replaced += 1
            else:
                created += 1

            if index % PROGRESS_EVERY == 0:
                await ctx.respond(components=_panel(
                    "Uploading troop emojis",
                    f"{index}/{len(planned)} · {created} new · {replaced} "
                    f"replaced · {failed} failed",
                ))
            await asyncio.sleep(CADENCE_SECONDS)

        loaded = await refresh_cache(mongo)
        summary = [
            f"**{created}** created, **{replaced}** replaced, "
            f"**{skipped}** already current, **{failed}** failed.",
            f"**{loaded}** troop emojis are now usable in any server.",
        ]
        if foreign:
            summary.append(
                f"Left alone because this bot did not create them: "
                + ", ".join(f"`{n}`" for n in foreign[:10])
            )
        if stopped:
            summary.append(f"\n**Stopped early.** {stopped}")
        await ctx.respond(components=_panel(
            "Emoji sync finished", "\n".join(summary), ok=not stopped
        ))
