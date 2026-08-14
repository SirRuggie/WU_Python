"""Send yourself every message in the trade flow, without a live trade.

Each preview calls the real notifier or the real view function with a
synthetic trade document, so what arrives is exactly what a member gets -
never a second copy of the wording that can drift from it. Nothing is written
to Mongo and no card is reserved.

Controls that do not have handlers yet are rendered disabled rather than
omitted, so the layout can be judged before the logic exists.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands import cards as cards_command
from extensions.tasks import cards_deadlines
from utils import cards
from utils.constants import BLUE_ACCENT, GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT
from utils.mongo import MongoClient
from utils.todo_data import Account

loader = lightbulb.Loader()

OWNER_ID = 505227988229554179

# Real card ids, so the troop art resolves the way it will in production.
WANTED_CARD = "meteor_golem"
GIVEN_CARD = "electro_titan"
ALTERNATIVES = ("balloon", "wizard", "dragon")

# Screens with live buttons use this deliberately unlinked tag, so tapping a
# control in a preview fails closed at _load_target instead of touching a
# real collection.
PREVIEW_TAG = "#PREVIEW"


def _preview_account() -> Account:
    return Account(
        tag=PREVIEW_TAG,
        name="Preview Member",
        clan_tag="#HOME",
        clan_name="Morning Woods",
        town_hall=17,
    )


def _preview_inventory() -> dict:
    """A collection with one scanner 2+ so the Set to 2 control renders."""
    counts = {card.id: cards.OWNED for card in cards.CARDS}
    counts[GIVEN_CARD] = cards.DUPLICATE
    return {
        "_id": PREVIEW_TAG,
        "cards": counts,
        "complete_categories": [],
        "count_confirmed_card_ids": [],
        "scan_duplicate_unverified_card_ids": [],
    }


def _preview_requester_doc(discord_id: int) -> dict:
    """The previewing member's own matchable collection document."""
    counts = {card.id: cards.OWNED for card in cards.CARDS}
    counts[WANTED_CARD] = cards.MISSING
    counts[GIVEN_CARD] = 3
    return {
        "_id": PREVIEW_TAG,
        "cards": counts,
        "complete_categories": [category.id for category in cards.CATEGORIES],
        "clan_tag": "#HOME",
        "clan_name": "Morning Woods",
        "player_name": "Preview Member",
        "confirmed_at": datetime.now(timezone.utc),
        "discord_id": int(discord_id),
    }


def _preview_holder_doc(discord_id: int) -> dict:
    """A same-clan holder with a spare of the wanted card."""
    counts = {card.id: cards.OWNED for card in cards.CARDS}
    counts[WANTED_CARD] = 2
    counts[GIVEN_CARD] = cards.MISSING
    return {
        "_id": "#9LRVV8G8",
        "cards": counts,
        "complete_categories": [category.id for category in cards.CATEGORIES],
        "clan_tag": "#HOME",
        "clan_name": "Morning Woods",
        "player_name": "Sir UwU",
        "confirmed_at": datetime.now(timezone.utc),
        "discord_id": int(discord_id),
    }


def _fwa_treatment_variant(
    discord_id: int, clans: list[dict], warning_markup: str
) -> list:
    """PREVIEW-ONLY: the accepted trade with an in-Container FWA treatment.

    A true nested compact callout is impossible: a Container's legal
    children are ActionRow, TextDisplay, Section, MediaGallery, Separator
    and File - never another Container - in the Discord schema and in the
    pinned hikari builders alike (`ContainerBuilderComponentsT`), so the
    accent bar cannot exist inside the box. These variants therefore test
    what native TextDisplay Markdown can do for the warning instead. The
    layout derives from the production builder, so it cannot drift;
    production stays `cards._accepted_trade_dm`.
    """
    trade = _preview_trade(discord_id, alternatives=False, clans=clans)
    trade["status"] = "move_needed"
    main = cards_command._accepted_trade_dm(trade, fwa_relevant=False)[0]
    children = list(main.components)
    # In front of the trailing [spacing separator, quiet subtext] pair.
    children[-2:-2] = [
        Separator(divider=True),
        Text(content=warning_markup),
    ]
    return [Container(accent_color=GREEN_ACCENT, components=children)]


def _nested_fwa_variant(discord_id: int, clans: list[dict]) -> list:
    """The original in-Container experiment: bold heading + normal text."""
    return _fwa_treatment_variant(
        discord_id, clans, cards_command.FWA_WARNING_TEXT
    )


# The same two warning lines, wording untouched, markup varied. Only native
# Discord Markdown that renders reliably on mobile in both themes; code-fence
# syntax-coloring tricks (ansi/diff fences) are deliberately excluded because
# their colors are not dependable across clients and themes.
FWA_MARKUP_VARIANTS: tuple[tuple[str, str], ...] = (
    (
        "B — bold heading",
        "⚠️ **FWA — Wait for war**\nDo not trade until war starts.",
    ),
    (
        "C — blockquote",
        "> ⚠️ **FWA — Wait for war**\n> Do not trade until war starts.",
    ),
    (
        "D — inline-code line",
        "⚠️ **FWA — Wait for war**\n`Do not trade until war starts.`",
    ),
    (
        "E — small heading",
        "### ⚠️ FWA — Wait for war\nDo not trade until war starts.",
    ),
    (
        "F — blockquote + heading",
        "> ### ⚠️ FWA — Wait for war\n> Do not trade until war starts.",
    ),
    (
        "G — underline",
        "⚠️ **FWA — Wait for war**\n__Do not trade until war starts.__",
    ),
)


def _labelled(label: str, components: list) -> list:
    """A quiet root-level label above a preview message, preview-only."""
    return [Text(content=f"-# {label}"), *components]


def _preview_gem_ask(discord_id: int) -> dict:
    now = datetime.now(timezone.utc)
    card = cards.CARD_BY_ID[WANTED_CARD]
    return {
        "_id": f"gem:{PREVIEW_TAG}:#9LRVV8G8:{card.id}",
        "kind": "gem_ask",
        "status": "pending",
        "card_id": card.id,
        "gem_cost": cards.TRADE_GEM_COST.get(card.category, 0),
        "asker_tag": PREVIEW_TAG,
        "asker_name": "Preview Member",
        "asker_discord_id": int(discord_id),
        "holder_tag": "#9LRVV8G8",
        "holder_name": "Sir UwU",
        "holder_discord_id": int(discord_id),
        "generation": int(now.timestamp()),
        "created_at": now,
        "updated_at": now,
    }


def _preview_partial_draft() -> dict:
    """A row-scanner draft where only the first two rows were confirmed."""
    accepted_rows = (1, 2)
    confirmed = [
        card.id
        for row in accepted_rows
        for card in cards.CARDS[(row - 1) * 6:row * 6]
    ]
    unseen = [card.id for card in cards.CARDS if card.id not in confirmed]
    manual_rows = [row for row in range(1, 11) if row not in accepted_rows]
    return {
        "version": 2,
        "capture_count": 5,
        "card_states": {card_id: cards.OWNED for card_id in confirmed},
        "card_confidences": {card_id: 0.95 for card_id in confirmed},
        "card_warnings": {},
        "unknown_card_ids": [],
        "unseen_card_ids": unseen,
        "duplicate_unverified_card_ids": [],
        "capture_issues": [],
        "warnings": ["manual_review_required"],
        "errors": [],
        "identity_bound": True,
        "coverage_complete": False,
        "missing_page_numbers": sorted({(row + 1) // 2 for row in manual_rows}),
        "missing_global_rows": manual_rows,
        "accepted_global_rows": list(accepted_rows),
        "manual_required_global_rows": manual_rows,
        "manual_required_card_ids": unseen,
        "row_decisions": [],
        "scanner_version": "preview",
    }


async def _real_clans(mongo) -> list[dict]:
    """Two actual family clans, so the preview shows their real emoji.

    Inventing clan data made this preview useless for judging the shields: a
    hardcoded URL always rendered and a hardcoded None never did, which said
    nothing about production. Reading the same collection /todo reads means a
    missing logo here is a missing logo there.
    """
    try:
        rows = await mongo.clans.find(
            {}, {"tag": 1, "name": 1, "emoji": 1}
        ).to_list(length=50)
    except Exception:
        return []
    # Prefer clans that actually have a logo, so the happy path is visible,
    # but keep the rest so a missing one can be seen too.
    rows.sort(key=lambda row: str(row.get("emoji") or "").count(":") < 2)
    return rows[:2]


def _preview_trade(
    discord_id: int, *, alternatives: bool, clans: list[dict] | None = None
) -> dict:
    """A trade document shaped like the real thing, never persisted."""
    now = datetime.now(timezone.utc)
    rows = list(clans or ())
    mine = rows[0] if rows else {}
    theirs = rows[1] if len(rows) > 1 else mine
    return {
        "_id": "preview-trade",
        "kind": "trade",
        "guild_id": 0,
        "status": "move_needed",
        "wanted_card_id": WANTED_CARD,
        "given_card_id": GIVEN_CARD,
        "compatible_card_ids": list(ALTERNATIVES) if alternatives else [],
        "requester_tag": "#YURL2QVJJ",
        "requester_name": "brilliant31508",
        "requester_discord_id": int(discord_id),
        "requester_clan_tag": theirs.get("tag") or "#HOME",
        "requester_clan_name": theirs.get("name") or "Morning Woods",
        "requester_clan_emoji": theirs.get("emoji"),
        "requester_town_hall": 17,
        "holder_tag": "#9LRVV8G8",
        "holder_name": "Sir UwU",
        "holder_discord_id": int(discord_id),
        "holder_clan_tag": mine.get("tag") or "#AWAY",
        "holder_clan_name": mine.get("name") or "Edrag Rush",
        "holder_clan_emoji": mine.get("emoji"),
        "holder_town_hall": 18,
        "created_at": now,
        "updated_at": now,
    }


def _result(sent: list[tuple[str, bool]]) -> list[Container]:
    delivered = all(ok for _name, ok in sent)
    return [Container(
        accent_color=GREEN_ACCENT if delivered else RED_ACCENT,
        components=[
            Text(content="## Trade flow preview"),
            Text(content="\n".join(
                f"{'✅' if ok else '❌'} {name}" for name, ok in sent
            ) or "Nothing matched that choice."),
            Text(content=(
                "-# Synthetic data. Nothing was saved and no card was reserved."
                if delivered
                else "-# A ❌ means your DMs are closed to the bot."
            )),
        ],
    )]


@loader.command
class CardsDmPreview(
    lightbulb.SlashCommand,
    name="cards-dm-preview",
    description="DM yourself the trade messages to check their wording (owner only)",
):
    which = lightbulb.string(
        "which",
        "Which message to send",
        default="all",
        choices=[
            lightbulb.Choice("Everything", "all"),
            lightbulb.Choice("1 · Proposal, one card offered", "proposal_one"),
            lightbulb.Choice("2 · Proposal, several cards offered", "proposal_many"),
            lightbulb.Choice("3 · Accepted, different clans", "accepted_move"),
            lightbulb.Choice("4 · Accepted, same clan", "accepted_ready"),
            lightbulb.Choice("5 · Did you send it?", "confirm_ask"),
            lightbulb.Choice("6 · You answered No", "confirm_no"),
            lightbulb.Choice("7 · You answered Yes", "confirm_yes"),
            lightbulb.Choice("8 · They confirmed, card added", "other_confirmed"),
            lightbulb.Choice("9 · Cancelled", "cancelled"),
            lightbulb.Choice("10 · Proposal expired after 12h", "expired"),
            lightbulb.Choice("11 · Card deducted after 7 days", "auto_deduct"),
            lightbulb.Choice("12 · Closed after 7 days, no spare", "auto_no_spare"),
            lightbulb.Choice("13 · Accepted with FWA warning", "accepted_fwa"),
            lightbulb.Choice("14 · Gem ask DM", "gem_ask"),
            lightbulb.Choice("15 · Gem cost confirm", "gem_confirm"),
            lightbulb.Choice("16 · Still trading check-in", "checkin"),
            lightbulb.Choice("17 · Trading is off screen", "paused"),
            lightbulb.Choice("18 · Scan complete, partial", "scan_partial"),
            lightbulb.Choice("19 · Update collection editor", "editor"),
            lightbulb.Choice("20 · Accept feedback (holder)", "accept_feedback"),
            lightbulb.Choice("21 · Dashboard + editor ready", "screens_core"),
            lightbulb.Choice("22 · Find trades, holders, My trades", "screens_trade"),
            lightbulb.Choice("23 · Upload prompt + progress", "scan_screens"),
            lightbulb.Choice("24 · Compact callouts + notices", "callouts"),
        ],
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)
        if ctx.user.id != OWNER_ID:
            await ctx.respond(
                components=[Container(
                    accent_color=RED_ACCENT,
                    components=[Text(content="This command is owner only.")],
                )],
                flags=(
                    hikari.MessageFlag.IS_COMPONENTS_V2
                    | hikari.MessageFlag.EPHEMERAL
                ),
            )
            return

        sent = await _send_previews(
            self.which, me=int(ctx.user.id), bot=bot, mongo=mongo
        )
        await ctx.respond(
            components=_result(sent),
            flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
        )


async def _send_previews(
    which: str, *, me: int, bot: hikari.GatewayBot, mongo: MongoClient,
) -> list[tuple[str, bool]]:
        """Every preview state, sent through the production builders.

        Module-level so tests can drive it with a stub bot and assert what a
        given choice actually sends, without a Discord context.
        """
        wanted = which
        sent: list[tuple[str, bool]] = []
        clans = await _real_clans(mongo)
        one = _preview_trade(me, alternatives=False, clans=clans)
        many = _preview_trade(me, alternatives=True, clans=clans)

        async def notify(key: str, name: str, coro) -> None:
            """Send through the real notifier."""
            if wanted in (key, "all"):
                sent.append((name, bool(await coro)))
            else:
                coro.close()

        async def panel(key: str, name: str, components) -> None:
            """Deliver a screen that has no notifier of its own."""
            if wanted not in (key, "all"):
                return
            try:
                channel = await bot.rest.create_dm_channel(me)
                await bot.rest.create_message(
                    channel=channel,
                    components=components,
                    flags=hikari.MessageFlag.IS_COMPONENTS_V2,
                )
                sent.append((name, True))
            except Exception:
                sent.append((name, False))

        # 1-2. The proposal, answered in the DM.
        await panel(
            "proposal_one", "1 · Proposal, one card offered",
            cards_command._trade_proposal_dm(one, controls=True, preview=True),
        )
        await panel(
            "proposal_many", "2 · Proposal, several cards offered",
            cards_command._trade_proposal_dm(many, controls=True, preview=True),
        )

        # 3-4. What the proposer gets back once it is accepted. Passing mongo
        # means the FWA lookup runs against the real clans collection, the
        # same way production does.
        await notify(
            "accepted_move", "3 · Accepted, different clans",
            cards_command._notify_trade_accepted(
                bot, dict(one, status="move_needed"), mongo=mongo
            ),
        )
        await notify(
            "accepted_ready", "4 · Accepted, same clan",
            cards_command._notify_trade_accepted(
                bot, dict(one, status="ready"), mongo=mongo
            ),
        )

        # 5-7. The confirmation loop, shown in /cards rather than by DM.
        await panel(
            "confirm_ask", "5 · Did you send it?",
            cards_command._swap_confirm_view(one, role="holder", preview=True),
        )
        await panel(
            "confirm_no", "6 · You answered No",
            cards_command._swap_cancel_check_view(
                one, role="holder", preview=True
            ),
        )
        await panel(
            "confirm_yes", "7 · You answered Yes",
            cards_command._swap_sent_view(
                one, role="holder", remaining=1,
                other_confirmed=False, preview=True,
            ),
        )

        # 8-12. Everything that arrives without you doing anything. Titles
        # and details are the production strings themselves, imported from
        # the modules that send them, so this preview cannot drift.
        await notify(
            "other_confirmed", "8 · They confirmed, card added",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title=cards_command.SWAP_ARRIVED_TITLE,
                detail=cards_command._swap_arrived_detail("Sir UwU"),
            ),
        )
        await notify(
            "cancelled", "9 · Cancelled",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title=cards_command.CANCELLED_DM_TITLE,
                detail=cards_command._cancelled_dm_detail(
                    one, reader_role="holder", released=True
                ),
            ),
        )
        await notify(
            "expired", "10 · Proposal expired after 12h",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title=cards_deadlines.PROPOSAL_EXPIRED_TITLE,
                detail=cards_deadlines.PROPOSAL_EXPIRED_DETAIL,
            ),
        )
        await notify(
            "auto_deduct", "11 · Card deducted after 7 days",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title=cards_deadlines.AUTO_DEDUCT_TITLE,
                detail=cards_deadlines.AUTO_DEDUCT_DETAIL_MOVED,
            ),
        )
        if wanted in ("auto_no_spare", "all"):
            await notify(
                "auto_no_spare", "12a · Closed, silent side had no spare",
                cards_command._notify_trade_status(
                    bot, one, recipient_id=me,
                    title=cards_deadlines.AUTO_DEDUCT_TITLE,
                    detail=cards_deadlines.AUTO_DEDUCT_DETAIL_NO_SPARE,
                ),
            )
            await notify(
                "auto_no_spare", "12b · Closed, what the owed player sees",
                cards_command._notify_trade_status(
                    bot, one, recipient_id=me,
                    title=cards_deadlines.SWAP_CLOSED_OWED_TITLE,
                    detail=cards_deadlines.SWAP_CLOSED_OWED_DETAIL,
                ),
            )

        # 13. The accepted DM with the FWA region forced on, so its layout can
        # be judged without editing the clans collection.
        await panel(
            "accepted_fwa", "13 · Accepted with FWA warning",
            cards_command._accepted_trade_dm(
                dict(one, status="move_needed"), fwa_relevant=True
            ),
        )

        # 14-19. Screens and DMs the harness previously could not show.
        preview_account = _preview_account()
        gem_ask = _preview_gem_ask(me)
        await panel(
            "gem_ask", "14 · Gem ask DM",
            cards_command._gem_ask_dm(gem_ask, preview=True),
        )
        await panel(
            "gem_confirm", "15 · Gem cost confirm",
            cards_command._gem_ask_confirm_view(
                preview_account,
                cards.CARD_BY_ID[WANTED_CARD],
                "Sir UwU",
                "#9LRVV8G8",
            ),
        )
        await panel(
            "checkin", "16 · Still trading check-in",
            cards_command._checkin_dm(PREVIEW_TAG, "Preview Member"),
        )
        await panel(
            "paused", "17 · Trading is off screen",
            cards_command._trading_paused_view(preview_account),
        )
        await panel(
            "scan_partial", "18 · Scan complete, partial",
            cards_command._scan_review(
                preview_account,
                _preview_inventory(),
                "preview-draft",
                _preview_partial_draft(),
            ),
        )
        await panel(
            "editor", "19 · Update collection editor",
            cards_command._quantity_editor(
                preview_account,
                _preview_inventory(),
                cards.CARD_BY_ID[GIVEN_CARD].category,
                card_id=GIVEN_CARD,
            ),
        )

        # 20. The holder's acceptance feedback, both clan states, through the
        # production builder - including the shared compact FWA callout.
        await panel(
            "accept_feedback", "20a · Accept feedback, different clans",
            cards_command._holder_accept_feedback(
                dict(one, status="move_needed"),
                taken_card_id=GIVEN_CARD,
                status="move_needed",
                dm_sent=True,
                fwa_relevant=False,
                tag=PREVIEW_TAG,
            ),
        )
        await panel(
            "accept_feedback", "20b · Accept feedback, same clan + FWA",
            cards_command._holder_accept_feedback(
                dict(one, status="ready"),
                taken_card_id=GIVEN_CARD,
                status="ready",
                dm_sent=True,
                fwa_relevant=True,
                tag=PREVIEW_TAG,
            ),
        )

        # 21. The dashboard (board render is CPU-bound, so off the loop) and
        # the editor's ready-state banner.
        if wanted in ("screens_core", "all"):
            dashboard = await asyncio.to_thread(
                cards_command._dashboard,
                preview_account,
                _preview_inventory(),
                account_count=2,
            )
            await panel("screens_core", "21a · Collection dashboard", dashboard)
            ready_inventory = dict(
                _preview_inventory(),
                complete_categories=[cards.CARD_BY_ID[GIVEN_CARD].category],
            )
            await panel(
                "screens_core", "21b · Editor, category ready",
                cards_command._quantity_editor(
                    preview_account,
                    ready_inventory,
                    cards.CARD_BY_ID[GIVEN_CARD].category,
                ),
            )

        # 22. The trade-discovery screens over synthetic matchable documents.
        if wanted in ("screens_trade", "all"):
            requester_doc = _preview_requester_doc(me)
            holder_doc = _preview_holder_doc(me)
            matches = cards.find_matches(requester_doc, [holder_doc])
            await panel(
                "screens_trade", "22a · Find trades",
                cards_command._matches_view(
                    preview_account,
                    requester_doc,
                    matches,
                    supply=cards.family_supply([holder_doc]),
                ),
            )
            holders = cards.holders_for_card(
                requester_doc, [holder_doc], WANTED_CARD
            )
            await panel(
                "screens_trade", "22b · Holder list",
                cards_command._holders_view(
                    preview_account, WANTED_CARD, holders
                ),
            )
            await panel(
                "screens_trade", "22c · My trades",
                cards_command._trades_view(
                    preview_account,
                    [dict(one, status="pending"), dict(one, status="ready")],
                ),
            )
            await panel(
                "screens_trade", "22d · My trades, empty",
                cards_command._trades_view(preview_account, []),
            )

        # 23. The upload prompt and mid-scan progress screens.
        upload_until = datetime.now(timezone.utc) + timedelta(minutes=20)
        await panel(
            "scan_screens", "23a · Upload prompt",
            cards_command._scan_upload_prompt(
                preview_account, "preview-session", usable_until=upload_until,
            ),
        )
        await panel(
            "scan_screens", "23b · Upload progress, rows missing",
            cards_command._scan_upload_progress(
                preview_account,
                "preview-session",
                _preview_partial_draft(),
                usable_until=upload_until,
            ),
        )

        # 24. The compact-callout primitive in all four semantic colors, one
        # message so the sizes compare directly, plus the real accepted-trade
        # message carrying its FWA callout - the state the owner inspects
        # before this primitive is standardized across WU Wizard. Then one
        # success and one failure notice for the accent canon.
        await panel(
            "callouts", "24a · Callout samples — red, gold, blue, green",
            [
                cards_command._compact_callout(
                    RED_ACCENT, cards_command.FWA_WARNING_TEXT,
                ),
                cards_command._compact_callout(
                    GOLD_ACCENT,
                    "⏳ **Waiting for you**\nAnswer this trade in **My trades**.",
                ),
                cards_command._compact_callout(
                    BLUE_ACCENT,
                    "ℹ️ **Need a place to trade?**\nOpen Noahs Ark · `#8VPQCR2R`",
                ),
                cards_command._compact_callout(
                    GREEN_ACCENT,
                    "✅ **Saved**\nYour collection is up to date.",
                ),
            ],
        )
        await panel(
            "callouts", "24b · Accepted trade + FWA callout",
            cards_command._accepted_trade_dm(
                dict(one, status="move_needed"), fwa_relevant=True
            ),
        )
        await panel(
            "callouts", "24c · Notice, collection saved",
            cards_command._scan_saved_notice(preview_account, pending=3),
        )
        await panel(
            "callouts", "24d · Notice, search unavailable",
            cards_command._search_unavailable_notice(PREVIEW_TAG),
        )
        # Nested-callout experiment: a Container cannot legally contain
        # another Container, so this renders the closest in-Container
        # warning treatment for comparison against 24b. Preview only.
        await panel(
            "callouts", "24e · Experiment: FWA inside the main container",
            _nested_fwa_variant(me, clans),
        )

        # FWA markup series: the same two warning lines under every native
        # TextDisplay treatment, each message labelled, so the owner can
        # choose the final design on a phone. Variant A is production.
        if wanted in ("callouts", "all"):
            fwa_trade = dict(
                _preview_trade(me, alternatives=False, clans=clans),
                status="move_needed",
            )
            await panel(
                "callouts", "24f · FWA A — compact red callout (production)",
                _labelled(
                    "Variant A — compact red callout (current production)",
                    cards_command._accepted_trade_dm(
                        fwa_trade, fwa_relevant=True
                    ),
                ),
            )
            for offset, (letter_label, markup) in enumerate(
                FWA_MARKUP_VARIANTS
            ):
                await panel(
                    "callouts",
                    f"24{'ghijkl'[offset]} · FWA {letter_label}",
                    _labelled(
                        f"Variant {letter_label}",
                        _fwa_treatment_variant(me, clans, markup),
                    ),
                )

        return sent
