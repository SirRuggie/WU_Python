"""Send yourself every message in the trade flow, without a live trade.

Each preview calls the real notifier or the real view function with a
synthetic trade document, so what arrives is exactly what a member gets -
never a second copy of the wording that can drift from it. Nothing is written
to Mongo and no card is reserved.

Controls that do not have handlers yet are rendered disabled rather than
omitted, so the layout can be judged before the logic exists.
"""

from __future__ import annotations

from datetime import datetime, timezone

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
)

from extensions.commands import cards as cards_command
from utils.constants import GREEN_ACCENT, RED_ACCENT

loader = lightbulb.Loader()

OWNER_ID = 505227988229554179

# Real card ids, so the troop art resolves the way it will in production.
WANTED_CARD = "meteor_golem"
GIVEN_CARD = "electro_titan"
ALTERNATIVES = ("balloon", "wizard", "dragon")


def _preview_trade(discord_id: int, *, alternatives: bool) -> dict:
    """A trade document shaped like the real thing, never persisted."""
    now = datetime.now(timezone.utc)
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
        "requester_clan_tag": "#HOME",
        "requester_clan_name": "Morning Woods",
        "holder_tag": "#9LRVV8G8",
        "holder_name": "Sir UwU",
        "holder_discord_id": int(discord_id),
        "holder_clan_tag": "#AWAY",
        "holder_clan_name": "Edrag Rush",
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
            lightbulb.Choice("11 · Card deducted after 24h", "auto_deduct"),
        ],
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
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

        me = int(ctx.user.id)
        wanted = self.which
        sent: list[tuple[str, bool]] = []
        one = _preview_trade(me, alternatives=False)
        many = _preview_trade(me, alternatives=True)

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

        # 3-4. What the proposer gets back once it is accepted.
        await notify(
            "accepted_move", "3 · Accepted, different clans",
            cards_command._notify_trade_accepted(
                bot, dict(one, status="move_needed")
            ),
        )
        await notify(
            "accepted_ready", "4 · Accepted, same clan",
            cards_command._notify_trade_accepted(bot, dict(one, status="ready")),
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

        # 8-11. Everything that arrives without you doing anything.
        await notify(
            "other_confirmed", "8 · They confirmed, card added",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title="Your card arrived",
                detail=(
                    "Sir UwU confirmed they sent it, so it has been added to "
                    "your collection."
                ),
            ),
        )
        await notify(
            "cancelled", "9 · Cancelled",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title="Card swap cancelled",
                detail="The other player cancelled it. Both cards are free again.",
            ),
        )
        await notify(
            "expired", "10 · Proposal expired after 12h",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title="Card proposal expired",
                detail=(
                    "Nobody accepted within 12 hours, so it closed. Nothing "
                    "changed in either collection."
                ),
            ),
        )
        await notify(
            "auto_deduct", "11 · Card deducted after 24h",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title="Your card was deducted automatically",
                detail=(
                    "brilliant31508 confirmed they sent theirs over 24 hours "
                    "ago and we did not hear back from you. If this is wrong, "
                    "open /cards, tap the card and set your real count."
                ),
            ),
        )

        await ctx.respond(
            components=_result(sent),
            flags=(
                hikari.MessageFlag.IS_COMPONENTS_V2
                | hikari.MessageFlag.EPHEMERAL
            ),
        )
