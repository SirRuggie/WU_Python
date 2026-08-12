"""Send yourself each trade DM, for reading the copy without a live trade.

Every preview calls the real notifier with a synthetic trade document, so what
arrives is exactly what a member gets - not a second copy of the wording that
can drift from it. Nothing is written to Mongo and no card is reserved.
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
    lines = "\n".join(
        f"{'✅' if ok else '❌'} {name}" for name, ok in sent
    )
    delivered = all(ok for _name, ok in sent)
    return [Container(
        accent_color=GREEN_ACCENT if delivered else RED_ACCENT,
        components=[
            Text(content="## Trade DM preview"),
            Text(content=lines),
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
            lightbulb.Choice("New proposal, one card offered", "proposal_one"),
            lightbulb.Choice("New proposal, several cards offered", "proposal_many"),
            lightbulb.Choice("Accepted, clans differ", "accepted_move"),
            lightbulb.Choice("Accepted, same clan", "accepted_ready"),
            lightbulb.Choice("Cancelled", "cancelled"),
            lightbulb.Choice("Completed", "completed"),
            lightbulb.Choice("MOCKUP: proposal with Accept in the DM", "dm_accept_one"),
            lightbulb.Choice("MOCKUP: proposal with a pick-one menu", "dm_accept_many"),
            lightbulb.Choice("MOCKUP: did you send it?", "confirm_ask"),
            lightbulb.Choice("MOCKUP: you answered No", "confirm_no"),
            lightbulb.Choice("MOCKUP: you answered Yes", "confirm_yes"),
            lightbulb.Choice("MOCKUP: card deducted for you", "auto_deduct"),
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
                flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
            )
            return

        me = int(ctx.user.id)
        wanted = self.which
        sent: list[tuple[str, bool]] = []

        async def run(key: str, name: str, coro):
            if wanted in (key, "all"):
                sent.append((name, bool(await coro)))

        one = _preview_trade(me, alternatives=False)
        many = _preview_trade(me, alternatives=True)

        await run(
            "proposal_one", "New proposal, one card offered",
            cards_command._notify_trade_holder(bot, one),
        )
        await run(
            "proposal_many", "New proposal, several cards offered",
            cards_command._notify_trade_holder(bot, many),
        )
        await run(
            "accepted_move", "Accepted, clans differ",
            cards_command._notify_trade_accepted(bot, dict(one, status="move_needed")),
        )
        await run(
            "accepted_ready", "Accepted, same clan",
            cards_command._notify_trade_accepted(bot, dict(one, status="ready")),
        )
        await run(
            "cancelled", "Cancelled",
            cards_command._notify_trade_status(
                bot, one, recipient_id=me,
                title="Card swap cancelled",
                detail=(
                    "The other player cancelled it and exact-card reservations "
                    "were released."
                ),
            ),
        )
        await run(
            "completed", "Completed",
            cards_command._notify_trade_status(
                bot, dict(one, status="completed"), recipient_id=me,
                title="Card swap completed",
                detail="Both collections were updated.",
            ),
        )

        # The confirmation flow is not wired to logic yet, so its buttons are
        # rendered disabled. These are the real view functions, not a second
        # copy of the wording, so approving them here approves what ships.
        async def send_panel(key: str, name: str, components) -> None:
            if wanted not in (key, "all"):
                return
            try:
                channel = await bot.rest.create_dm_channel(me)
                await bot.rest.create_message(
                    channel=channel,
                    components=components,
                    flags=hikari.MessageFlag.IS_COMPONENTS_V2,
                )
                sent.append((f"{name} (mockup)", True))
            except Exception:
                sent.append((f"{name} (mockup)", False))

        await send_panel(
            "dm_accept_one", "Proposal with Accept in the DM",
            cards_command._trade_proposal_dm(
                one, controls=True, preview=True
            ),
        )
        await send_panel(
            "dm_accept_many", "Proposal with a pick-one menu",
            cards_command._trade_proposal_dm(
                many, controls=True, preview=True
            ),
        )
        await send_panel(
            "confirm_ask", "Did you send it?",
            cards_command._swap_confirm_view(one, role="holder", preview=True),
        )
        await send_panel(
            "confirm_no", "You answered No",
            cards_command._swap_cancel_check_view(
                one, role="holder", preview=True
            ),
        )
        await send_panel(
            "confirm_yes", "You answered Yes",
            cards_command._swap_sent_view(
                one, role="holder", remaining=1,
                other_confirmed=False, preview=True,
            ),
        )
        await run(
            "auto_deduct", "Card deducted for you",
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
            flags=hikari.MessageFlag.IS_COMPONENTS_V2 | hikari.MessageFlag.EPHEMERAL,
        )
